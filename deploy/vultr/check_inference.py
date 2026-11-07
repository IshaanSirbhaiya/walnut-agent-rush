#!/usr/bin/env python3
"""Check an OpenAI-compatible model endpoint (for example Vultr Serverless Inference) before Walnut uses it.

Walnut's model adapter is provider-neutral: it posts to ``<IB_MODEL_URL>/chat/completions`` with an
optional bearer key. This script makes the same two kinds of call the adapter needs, so you can pick a
model that works before you restart the Brain:

  1. ``GET <url>/models``: the catalogue. Vultr's also lists music, image, speech and embedding models, so a
     model counts as chat only when its ``output_modalities`` include text (and its name is not a
     reranker or safety classifier). Prices come from ``/models?format=openrouter`` when offered.
  2. ``POST <url>/chat/completions``: one tiny, synthetic, grounded prompt to IB_MODEL_NAME (and each
     IB_MODEL_FALLBACKS name), reporting latency, token usage, and whether the reply keeps the
     ``[C1]`` citation format Walnut's grounding wall needs.

Reasoning. Per Vultr's docs, most chat models think first by default; the thinking comes back in
``message.reasoning`` and its tokens count against the same budget as the answer. So this check sends what
the Brain will send (``IB_MODEL_REASONING_EFFORT`` as ``reasoning.effort``), reports reasoning tokens, says
plainly when thinking used up the budget, and fails a model too slow for IB_MODEL_ANSWER_TIMEOUT_S, because
the Brain would silently serve the quoted answer instead.

Settings come from the environment (never from the command line, where a key would land in shell
history and ``ps``): IB_MODEL_URL, IB_MODEL_KEY, IB_MODEL_NAME, IB_MODEL_FALLBACKS,
IB_MODEL_REASONING_EFFORT, IB_MODEL_ANSWER_TIMEOUT_S. ``--env-file FILE``
reads them from a KEY=VALUE file instead (for example /opt/walnut/walnut.env on the VM). The key is
never printed. Standard library only.

  python3 deploy/vultr/check_inference.py --env-file /opt/walnut/walnut.env           # list + test
  python3 deploy/vultr/check_inference.py --env-file /opt/walnut/walnut.env --list    # list only

Exit status: 0 when the endpoint answers and at least one configured model passes; 1 otherwise.
The prompt is synthetic and contains no company data.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Optional

#: used only when --vultr is given and IB_MODEL_URL is empty (a documented preset, not a default)
VULTR_INFERENCE_URL = "https://api.vultrinference.com/v1"

#: model ids that are not chat models (embeddings, rerankers, safety classifiers)
NOT_CHAT = re.compile(r"embed|rerank|safety|guard|whisper|tts|stt|vision-encoder", re.I)

PROMPT_SYSTEM = ("Answer only from the numbered passages. End every sentence with the tag of the passage "
                 "it comes from, like [C1]. Do not add anything that is not in a passage.")
PROMPT_USER = ("Passages:\n[C1] Any purchase above SGD 10,000 needs three written quotes.\n\n"
               "Question: How many quotes does a SGD 18,000 purchase need?")


def read_env_file(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[k.strip()] = v
    return out


def _req(method: str, url: str, key: str, body: Optional[dict], timeout: float) -> tuple[int, dict, float]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("accept", "application/json")
    if data is not None:
        r.add_header("content-type", "application/json")
    if key:
        r.add_header("authorization", f"Bearer {key}")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {}), time.monotonic() - t0
    except urllib.error.HTTPError as e:
        try:
            parsed = json.loads(e.read() or b"{}")
        except Exception:                                             # noqa: BLE001
            parsed = {}
        return e.code, parsed if isinstance(parsed, dict) else {}, time.monotonic() - t0


def _problem(status: int, data: dict) -> str:
    """HTTP status plus the endpoint's own words: {"error": {"message": ...}} (OpenRouter's shape)."""
    err = data.get("error") if isinstance(data, dict) else None
    msg = err.get("message") if isinstance(err, dict) else None
    return f"HTTP {status}: {str(msg)[:200]}" if msg else f"HTTP {status}"


def list_catalogue(url: str, key: str, timeout: float = 20.0) -> list[dict]:
    status, data, _ = _req("GET", url.rstrip("/") + "/models", key, None, timeout)
    if status != 200:
        raise RuntimeError(f"GET /models returned {_problem(status, data)}")
    return [m for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]


def is_chat(model: dict) -> bool:
    """Text output (Vultr's ``output_modalities``: objects in its own catalogue, strings under
    ``architecture`` in the OpenRouter shape), and not a reranker or classifier by name."""
    mods = model.get("output_modalities") or (model.get("architecture") or {}).get("output_modalities")
    if mods:
        kinds = {m.get("type") if isinstance(m, dict) else m for m in mods}
        if "text" not in kinds:
            return False
    return not NOT_CHAT.search(str(model["id"]))


def prices(url: str, key: str, timeout: float = 20.0) -> dict[str, tuple[float, float]]:
    """US$ per million tokens by model id, when the endpoint publishes them. Optional, so never fatal."""
    out: dict[str, tuple[float, float]] = {}
    try:
        status, data, _ = _req("GET", url.rstrip("/") + "/models?format=openrouter", key, None, timeout)
        if status == 200:
            for m in data.get("data", []):
                p = m.get("pricing") or {}
                if p.get("prompt") is not None and p.get("completion") is not None:
                    out[str(m["id"])] = (float(p["prompt"]) * 1e6, float(p["completion"]) * 1e6)
    except (urllib.error.URLError, OSError, ValueError, TypeError, AttributeError, KeyError):
        pass
    return out


def try_model(url: str, key: str, model: str, timeout: float = 60.0, effort: str = "",
              answer_timeout: float = 12.0) -> dict:
    body: dict = {"model": model, "temperature": 0, "max_tokens": 1000,
                  "messages": [{"role": "system", "content": PROMPT_SYSTEM},
                               {"role": "user", "content": PROMPT_USER}]}
    if effort:
        body["reasoning"] = {"effort": effort}
    status, data, secs = _req("POST", url.rstrip("/") + "/chat/completions", key, body, timeout)
    res = {"model": model, "http": status, "seconds": round(secs, 2), "ok": False}
    if status != 200:
        res["problem"] = _problem(status, data)
        return res
    try:
        choice = data["choices"][0]
        message = choice["message"]
        text = str(message.get("content") or "")
    except (KeyError, IndexError, TypeError, AttributeError):
        res["problem"] = "no choices[0].message.content"
        return res
    usage = data.get("usage") or {}
    thinking = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
    res.update(tokens_in=usage.get("prompt_tokens"), tokens_out=usage.get("completion_tokens"),
               reasoning_tokens=thinking, reply=text.strip()[:200])
    if choice.get("finish_reason") == "length":
        res["problem"] = ("cut at the token limit" + (" while thinking" if message.get("reasoning") or thinking else "")
                          + ": the Brain refuses cut replies; set IB_MODEL_REASONING_EFFORT=none or pick another model")
    elif secs > answer_timeout:
        res["problem"] = (f"took {secs:.1f} s, over the Brain's {answer_timeout:g} s answer timeout "
                          "(IB_MODEL_ANSWER_TIMEOUT_S): users would get the quoted answer")
    elif "<think>" in text:
        res["problem"] = "reply contains <think> reasoning in its text; set IB_MODEL_REASONING_EFFORT=none or pick another model"
    elif "[C1]" not in text:
        res["problem"] = "reply dropped the [C1] citation tag (the grounding wall would refuse it)"
    elif "three" not in text.lower() and "3" not in text:
        res["problem"] = "reply did not answer from the passage"
    else:
        res["ok"] = True
    return res


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Check an OpenAI-compatible model endpoint for Walnut.")
    ap.add_argument("--env-file", help="read IB_MODEL_* from this KEY=VALUE file")
    ap.add_argument("--vultr", action="store_true",
                    help=f"use the Vultr Serverless Inference URL ({VULTR_INFERENCE_URL}) when IB_MODEL_URL is empty")
    ap.add_argument("--list", action="store_true", help="only list the model ids the key may use")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    a = ap.parse_args(argv)

    env = dict(os.environ)
    if a.env_file:
        env.update({k: v for k, v in read_env_file(a.env_file).items() if v != ""})
    url = (env.get("IB_MODEL_URL") or "").strip() or (VULTR_INFERENCE_URL if a.vultr else "")
    key = (env.get("IB_MODEL_KEY") or "").strip()
    if not url:
        print("IB_MODEL_URL is empty (set it, or pass --vultr for the Vultr Serverless Inference URL)", file=sys.stderr)
        return 1
    names = [n for n in [(env.get("IB_MODEL_NAME") or "").strip(),
                         *[x.strip() for x in (env.get("IB_MODEL_FALLBACKS") or "").split(",")]] if n]
    effort = (env.get("IB_MODEL_REASONING_EFFORT") or "").strip()
    try:
        answer_timeout = float(env.get("IB_MODEL_ANSWER_TIMEOUT_S") or 12)
    except ValueError:
        answer_timeout = 12.0
    out: dict = {"endpoint": url, "key_set": bool(key)}
    chat: set[str] = set()
    try:
        catalogue = list_catalogue(url, key)
        ids = [str(m["id"]) for m in catalogue]
        chat = {str(m["id"]) for m in catalogue if is_chat(m)}
        out["models"] = ids
        out["chat_models"] = sorted(chat)
    except (RuntimeError, urllib.error.URLError, OSError, ValueError) as e:
        out["models_error"] = str(e)
        ids = []
    if a.list:
        if a.json:
            print(json.dumps(out, indent=2))
        elif "models_error" in out:
            print(f"Could not list models at {url}: {out['models_error']}")
        else:
            price = prices(url, key)
            print(f"Models at {url} (key {'set' if key else 'not set'}): {len(chat)} chat models of {len(ids)}")
            for m in sorted(ids, key=lambda i: (i not in chat, i)):
                note = ""
                if m not in chat:
                    note = "   (not a chat model)"
                elif m in price:
                    note = f"   US${price[m][0]:.2f} in / US${price[m][1]:.2f} out per million tokens"
                print(f"  - {m}{note}")
        return 0 if "models_error" not in out else 1
    results = []
    for n in dict.fromkeys(names):
        if ids and n not in ids:
            results.append({"model": n, "ok": False, "problem": "not in this key's /models list"})
            continue
        try:
            results.append(try_model(url, key, n, effort=effort, answer_timeout=answer_timeout))
        except (urllib.error.URLError, OSError, ValueError) as e:
            results.append({"model": n, "ok": False, "problem": f"{type(e).__name__}: {e}"})
    out["results"] = results
    if a.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"Endpoint: {url} (key {'set' if key else 'not set'})")
        if "models_error" in out:
            print(f"  /models: {out['models_error']}")
        else:
            print(f"  /models: {len(ids)} ids, {len(out['chat_models'])} look like chat models")
        if not names:
            print("  IB_MODEL_NAME is empty: nothing to test. Pick one of the chat models above.")
        for r in results:
            mark = "PASS" if r["ok"] else "FAIL"
            extra = f"{r.get('seconds')} s, tokens {r.get('tokens_in')}/{r.get('tokens_out')}" if "seconds" in r else ""
            if r.get("reasoning_tokens"):
                extra += f" ({r['reasoning_tokens']} thinking)"
            print(f"  {mark}  {r['model']}  {extra}  {r.get('problem', '')}".rstrip())
    return 0 if any(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())

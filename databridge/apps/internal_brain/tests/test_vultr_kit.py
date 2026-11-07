"""The Vultr deploy kit and the Vultr Serverless Inference option (deploy/vultr/, deploy/docker/).

* The provider-neutral adapter, configured by environment only, answers through a REAL HTTP server that
  speaks the OpenAI-compatible shape Vultr Serverless Inference uses (``/v1/models``,
  ``/v1/chat/completions``, bearer key). The server is a local fake: no network, no key, no spend.
* ``check_inference.py`` lists models, passes a grounded model, flags a ``<think>`` model, never prints
  the key.
* ``provision.py`` (Vultr API v2) in dry run: the request plan, the firewall rules, the user-data.
* Static checks: no secret in the kit, only Caddy publishes ports, the model settings reach ``ib``.
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import re
import sys
import threading
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from e2e_world import E2E, load_world

REPO = Path(__file__).resolve().parents[4]
VULTR = REPO / "deploy" / "vultr"
DOCKER = REPO / "deploy" / "docker"
WORLD = load_world()
FACTS = {f["id"]: f for f in WORLD["facts"]}
Q_PROC = ("Who approves spend of SGD 18,000 on 12 laptops, and how many written quotes does the "
          "purchase take?")
KEY = "test-key-not-real-0123456789"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


check = _load("vultr_check_inference", VULTR / "check_inference.py")
prov = _load("vultr_provision", VULTR / "provision.py")


# -- a local OpenAI-compatible endpoint (the shape of Vultr Serverless Inference) -------------------
class FakeInference:
    """``/v1/models`` and ``/v1/chat/completions`` with a bearer key. The chat reply quotes, with its
    tag, every passage sentence that is a world fact's statement (derived, never written down)."""

    def __init__(self, models=("fake-chat", "fake-think", "fake-embed-4b")):
        self.models, self.requests = list(models), []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                raw = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _authed(self):
                return self.headers.get("authorization") == f"Bearer {KEY}"

            def do_GET(self):
                outer.requests.append(("GET", self.path, dict(self.headers), None))
                if not self._authed():
                    return self._send(401, {"error": "unauthorized"})
                if self.path == "/v1/models":
                    return self._send(200, {"object": "list", "data": [{"id": m, "object": "model"} for m in outer.models]})
                self._send(404, {})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
                outer.requests.append(("POST", self.path, dict(self.headers), body))
                if not self._authed():
                    return self._send(401, {"error": "unauthorized"})
                if self.path != "/v1/chat/completions":
                    return self._send(404, {})
                user = next(m["content"] for m in reversed(body["messages"]) if m["role"] == "user")
                text = outer.reply(body["model"], user)
                self._send(200, {"id": "x", "object": "chat.completion", "model": body["model"],
                                 "choices": [{"index": 0, "finish_reason": "stop",
                                              "message": {"role": "assistant", "content": text}}],
                                 "usage": {"prompt_tokens": len(user) // 4, "completion_tokens": len(text) // 4}})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def reply(self, model: str, user: str) -> str:
        if model == "fake-think":
            return "<think>the user wants quotes</think> Three quotes."
        out, first = [], None
        for line in user.splitlines():
            m = re.match(r"\[(C\d+)\]\s*(.*)", line)
            if not m:
                continue
            first = first or f"{m.group(2).strip()} [{m.group(1)}]"
            for f in FACTS.values():
                if f["statement"] in line:
                    out.append(f"{f['statement']} [{m.group(1)}]")
        return " ".join(out) or first or "I couldn't find an answer to that in the sources you can access."

    def close(self):
        self.server.shutdown()


@pytest.fixture
def fake():
    f = FakeInference()
    yield f
    f.close()


# -- the adapter against the OpenAI-compatible endpoint ---------------------------------------------
def test_the_adapter_answers_through_an_openai_compatible_endpoint_env_only(fake, monkeypatch, tmp_path):
    from databridge_ib.llm import ModelChain
    monkeypatch.setenv("IB_MODEL_URL", fake.url)
    monkeypatch.setenv("IB_MODEL_NAME", "fake-chat")
    monkeypatch.setenv("IB_MODEL_KEY", KEY)
    monkeypatch.setenv("IB_MODEL_GUARD_DIR", str(tmp_path / "guard"))
    monkeypatch.delenv("IB_FORCE_OFFLINE", raising=False)
    monkeypatch.delenv("IB_MODEL_LIVE", raising=False)
    chain = ModelChain.from_env()                     # the real HTTP backend: no SDK, no inner fake
    assert chain is not None
    e = E2E(tmp_path, chain=chain)
    resp = e.ask("admin.it", Q_PROC)
    assert resp.model.provider == "model" and resp.model.model == "fake-chat", resp.model
    plain = re.sub(r"\s*\[C\d+\]", "", resp.answer)              # the wall may move tags mid-sentence
    for fid in ("WP-approval-limits", "WP-procurement-quotes"):
        assert FACTS[fid]["statement"] in plain, fid
    posts = [r for r in fake.requests if r[0] == "POST"]
    assert posts and all(r[1] == "/v1/chat/completions" for r in posts)
    assert all(r[2].get("Authorization") == f"Bearer {KEY}" for r in posts)
    # filter before the model: no restricted canary ever reached the endpoint
    sent = json.dumps([r[3] for r in posts])
    for f in FACTS.values():
        if "admin.it" not in f.get("permitted", []) and f.get("canary"):
            assert f["canary"] not in sent, f["id"]


def test_a_model_that_breaks_the_citation_format_falls_back_to_the_quoted_answer(fake, monkeypatch, tmp_path):
    from databridge_ib.llm import ModelChain
    monkeypatch.setenv("IB_MODEL_URL", fake.url)
    monkeypatch.setenv("IB_MODEL_NAME", "fake-think")
    monkeypatch.setenv("IB_MODEL_KEY", KEY)
    monkeypatch.setenv("IB_MODEL_GUARD_DIR", str(tmp_path / "guard"))
    monkeypatch.delenv("IB_FORCE_OFFLINE", raising=False)
    monkeypatch.delenv("IB_MODEL_LIVE", raising=False)
    e = E2E(tmp_path, chain=ModelChain.from_env())
    resp = e.ask("admin.it", Q_PROC)
    assert resp.model.provider == "deterministic"                # the grounding wall refused it
    assert FACTS["WP-procurement-quotes"]["statement"] in re.sub(r"\s*\[C\d+\]", "", resp.answer)


# -- check_inference.py ----------------------------------------------------------------------------
def _run_check(argv, env, monkeypatch):
    for k in ("IB_MODEL_URL", "IB_MODEL_NAME", "IB_MODEL_KEY", "IB_MODEL_FALLBACKS", "IB_MODEL_REASONING_EFFORT",
              "IB_MODEL_ANSWER_TIMEOUT_S"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = check.main(argv)
    return rc, buf.getvalue()


def test_check_inference_lists_models_and_passes_a_grounded_model(fake, monkeypatch):
    rc, out = _run_check([], {"IB_MODEL_URL": fake.url, "IB_MODEL_KEY": KEY, "IB_MODEL_NAME": "fake-chat",
                              "IB_MODEL_FALLBACKS": "fake-think"}, monkeypatch)
    assert rc == 0, out
    assert "PASS  fake-chat" in out and "FAIL  fake-think" in out and "<think>" in out
    assert KEY not in out


def test_check_inference_list_marks_non_chat_models_and_reads_an_env_file(fake, monkeypatch, tmp_path):
    envf = tmp_path / "walnut.env"
    envf.write_text(f"IB_MODEL_URL={fake.url}\nIB_MODEL_KEY={KEY}\n# comment\n", encoding="utf-8")
    rc, out = _run_check(["--env-file", str(envf), "--list"], {}, monkeypatch)
    assert rc == 0 and "fake-chat" in out and "fake-embed-4b   (not a chat model)" in out
    assert KEY not in out


def test_check_inference_wrong_key_fails_without_echoing_it(fake, monkeypatch):
    rc, out = _run_check([], {"IB_MODEL_URL": fake.url, "IB_MODEL_KEY": "wrong-key-xyz", "IB_MODEL_NAME": "fake-chat"}, monkeypatch)
    assert rc == 1 and "wrong-key-xyz" not in out and "401" in out


def test_check_inference_vultr_preset_only_when_asked(monkeypatch):
    rc, _ = _run_check([], {}, monkeypatch)
    assert rc == 1                                               # no URL, no preset: nothing called
    assert check.VULTR_INFERENCE_URL == "https://api.vultrinference.com/v1"


# -- the shapes Vultr publishes, not the ones we assumed ----------------------------------------------
# Copied from api.vultrinference.com/docs (create-chat-completion, reasoning, errors, list-models) and the
# public catalogue, 6 Nov 2026: reasoning comes back in message.reasoning, counts against the token budget,
# and the catalogue holds music, image and speech models beside the chat ones.
VULTR_CATALOGUE = [
    {"id": "ace-step-1.5", "output_modalities": [{"type": "audio"}]},
    {"id": "moss-image", "output_modalities": [{"type": "image"}]},
    {"id": "auk", "output_modalities": [{"type": "speech"}]},
    {"id": "clef", "output_modalities": [{"type": "decisions"}]},
    {"id": "qwen3-embedding-4b", "output_modalities": [{"type": "embeddings"}]},
    {"id": "nemotron-3.5-content-safety", "output_modalities": [{"type": "text"}]},
    {"id": "glm-5.3-flash", "output_modalities": [{"type": "text"}]},
]


class FakeVultr(FakeInference):
    """Answers the way Vultr documents it. Thinks unless told ``reasoning.effort: none``, and the thinking
    spends ``max_tokens`` first, so a small budget ends with no content and finish_reason ``length``."""

    THINKING_TOKENS = 600

    def __init__(self):
        super().__init__(models=[])
        outer = self
        handler = self.server.RequestHandlerClass
        plain_post = handler.do_POST
        plain_get = handler.do_GET

        def do_get(h):
            if h.path == "/v1/models":
                return h._send(200, {"data": VULTR_CATALOGUE})
            if h.path == "/v1/models?format=openrouter":
                return h._send(200, {"data": [{"id": "glm-5.3-flash", "architecture": {"output_modalities": ["text"]},
                                               "pricing": {"prompt": "0.0000001", "completion": "0.00000035"}}]})
            return plain_get(h)

        def do_post(h):
            raw = h.rfile.read(int(h.headers.get("content-length", 0)))
            body = json.loads(raw or b"{}")
            outer.requests.append(("POST", h.path, dict(h.headers), body))
            if h.headers.get("authorization") != f"Bearer {KEY}":
                return h._send(401, {"error": {"code": 401, "message": "The API key is missing, unknown or not active.",
                                               "type": "authentication_error", "metadata": {"error_type": "unauthorized"}}})
            thinks = (body.get("reasoning") or {}).get("effort") != "none"
            budget = int(body.get("max_tokens") or 32768)
            spent = outer.THINKING_TOKENS if thinks else 0
            user = next(m["content"] for m in reversed(body["messages"]) if m["role"] == "user")
            cut = spent >= budget
            message = {"role": "assistant", "content": None if cut else outer.reply(body["model"], user)}
            if thinks:
                message["reasoning"] = "The user asks about quotes..."
            h._send(200, {"id": "chatcmpl-x", "object": "chat.completion", "model": body["model"],
                          "choices": [{"index": 0, "finish_reason": "length" if cut else "stop", "message": message}],
                          "usage": {"prompt_tokens": 40, "completion_tokens": min(budget, spent + 20),
                                    "prompt_tokens_details": {"cached_tokens": 0},
                                    "completion_tokens_details": {"reasoning_tokens": spent}}})

        handler.do_GET, handler.do_POST = do_get, do_post


@pytest.fixture
def vultr():
    f = FakeVultr()
    yield f
    f.close()


def test_the_catalogue_is_filtered_to_chat_models_and_shows_prices(vultr, monkeypatch):
    rc, out = _run_check(["--list"], {"IB_MODEL_URL": vultr.url, "IB_MODEL_KEY": KEY}, monkeypatch)
    assert rc == 0, out
    assert "1 chat models of 7" in out
    assert "glm-5.3-flash   US$0.10 in / US$0.35 out" in out
    for other in ("ace-step-1.5", "moss-image", "auk", "clef", "qwen3-embedding-4b", "nemotron-3.5-content-safety"):
        assert f"{other}   (not a chat model)" in out, other


def test_check_sends_the_reasoning_setting_and_passes_with_thinking_off(vultr, monkeypatch):
    rc, out = _run_check([], {"IB_MODEL_URL": vultr.url, "IB_MODEL_KEY": KEY, "IB_MODEL_NAME": "glm-5.3-flash",
                              "IB_MODEL_REASONING_EFFORT": "none"}, monkeypatch)
    assert rc == 0, out
    body = next(b for m, p, _, b in vultr.requests if m == "POST")
    assert body["reasoning"] == {"effort": "none"} and "PASS  glm-5.3-flash" in out


def test_thinking_within_the_budget_passes_and_is_reported(vultr, monkeypatch):
    rc, out = _run_check([], {"IB_MODEL_URL": vultr.url, "IB_MODEL_KEY": KEY, "IB_MODEL_NAME": "glm-5.3-flash"}, monkeypatch)
    assert rc == 0, out                 # the old 200-token budget failed here, blaming the citation tag
    assert "600 thinking" in out


def test_thinking_that_eats_the_budget_is_named_not_blamed_on_the_tag(vultr, monkeypatch):
    monkeypatch.setattr(FakeVultr, "THINKING_TOKENS", 5000)
    rc, out = _run_check([], {"IB_MODEL_URL": vultr.url, "IB_MODEL_KEY": KEY, "IB_MODEL_NAME": "glm-5.3-flash"}, monkeypatch)
    assert rc == 1 and "cut at the token limit while thinking" in out and "IB_MODEL_REASONING_EFFORT=none" in out
    assert "dropped" not in out


def test_a_model_slower_than_the_answer_timeout_fails_the_check(vultr, monkeypatch):
    rc, out = _run_check([], {"IB_MODEL_URL": vultr.url, "IB_MODEL_KEY": KEY, "IB_MODEL_NAME": "glm-5.3-flash",
                              "IB_MODEL_ANSWER_TIMEOUT_S": "0"}, monkeypatch)
    assert rc == 1 and "answer timeout" in out


def test_the_endpoints_own_error_message_is_shown_without_the_key(vultr, monkeypatch):
    rc, out = _run_check([], {"IB_MODEL_URL": vultr.url, "IB_MODEL_KEY": "wrong-key-xyz", "IB_MODEL_NAME": "glm-5.3-flash"}, monkeypatch)
    assert rc == 1 and "401" in out and "not active" in out and "wrong-key-xyz" not in out


def test_the_brain_sends_reasoning_effort_only_when_configured(vultr, monkeypatch, tmp_path):
    from databridge_ib.llm import ModelChain
    monkeypatch.setenv("IB_MODEL_URL", vultr.url)
    monkeypatch.setenv("IB_MODEL_KEY", KEY)
    monkeypatch.setenv("IB_MODEL_NAME", "glm-5.3-flash")
    monkeypatch.setenv("IB_MODEL_GUARD_DIR", str(tmp_path / "guard"))
    monkeypatch.delenv("IB_FORCE_OFFLINE", raising=False)
    monkeypatch.delenv("IB_MODEL_LIVE", raising=False)
    monkeypatch.delenv("IB_MODEL_REASONING_EFFORT", raising=False)
    e = E2E(tmp_path / "a", chain=ModelChain.from_env())
    e.ask("admin.it", Q_PROC)
    assert [b for m, _, _, b in vultr.requests if m == "POST"], "the model was called"
    assert all("reasoning" not in b for m, _, _, b in vultr.requests if m == "POST")
    vultr.requests.clear()
    monkeypatch.setenv("IB_MODEL_REASONING_EFFORT", "none")
    resp = E2E(tmp_path / "b", chain=ModelChain.from_env()).ask("admin.it", Q_PROC)
    posts = [b for m, _, _, b in vultr.requests if m == "POST"]
    assert posts and all(b["reasoning"] == {"effort": "none"} for b in posts)
    assert resp.model.provider != "deterministic", resp.model     # thinking off: the model's answer is served


# -- provision.py (Vultr API v2), dry run -------------------------------------------------------------
def test_provision_dry_run_plans_firewall_key_and_vm_in_order():
    sent: list = []
    base = prov.dry_sender(lambda s: None)

    def send(method, path, body):
        sent.append((method, path, body))
        return base(method, path, body)

    res = prov.plan(send, repo_url="https://github.com/example/walnut.git", ssh_pub="ssh-ed25519 AAAA test",
                    ssh_from="198.51.100.7", region="sgp", vm_plan="vc2-2c-4gb", os_name="Ubuntu 24.04 LTS x64",
                    label="walnut-demo", branch="main", log=lambda s: None, sleep=lambda s: None)
    paths = [(m, p.split("?")[0]) for m, p, _ in sent]
    assert paths[0] == ("GET", "/instances") and paths[1] == ("POST", "/firewalls")
    rules = [b for m, p, b in sent if p.endswith("/rules")]
    assert {(r["protocol"], r["port"]) for r in rules} == {("tcp", "22"), ("tcp", "80"), ("tcp", "443")}
    ssh = next(r for r in rules if r["port"] == "22")
    assert ssh["subnet"] == "198.51.100.7" and ssh["subnet_size"] == 32       # SSH from the operator only
    assert all(r["subnet_size"] == 0 for r in rules if r["port"] != "22")
    inst = next(b for m, p, b in sent if p == "/instances")
    assert inst["region"] == "sgp" and inst["plan"] == "vc2-2c-4gb" and inst["firewall_group_id"]
    ud = base64.b64decode(inst["user_data"]).decode()
    assert "--branch main https://github.com/example/walnut.git /opt/walnut/repo" in ud
    assert "REPO_URL /opt" not in ud                                          # the placeholder was filled
    assert ud.startswith("#cloud-config") and "deploy/docker/deploy.sh deploy" in ud
    assert res["url"] == "https://203-0-113-10.sslip.io"


def test_provision_refuses_a_second_billed_vm():
    created = []

    def send(method, path, body):
        if method == "GET" and path.startswith("/instances?"):
            assert "label=walnut-demo" in path
            return {"instances": [{"id": "abc", "main_ip": "203.0.113.10", "label": "walnut-demo"}]}
        created.append((method, path))
        return {}

    with pytest.raises(prov.VultrError, match="already exists"):
        prov.plan(send, repo_url="u", ssh_pub="ssh-ed25519 A", ssh_from="198.51.100.7", region="sgp",
                  vm_plan="vc2-2c-4gb", os_name="Ubuntu 24.04 LTS x64", label="walnut-demo", branch="main",
                  log=lambda s: None, sleep=lambda s: None)
    assert created == []


def test_provision_request_fields_match_vultrs_published_client():
    """Field names as declared in vultr/govultr (instance.go InstanceCreateReq, firewall_rule.go FirewallRuleReq,
    ssh_key.go, firewall_group.go), checked 6 Nov 2026; a typo here would be a live-only failure."""
    sent = []
    base = prov.dry_sender(lambda s: None)

    def send(method, path, body):
        sent.append((method, path, body))
        return base(method, path, body)

    prov.plan(send, repo_url="u", ssh_pub="ssh-ed25519 A", ssh_from="198.51.100.7", region="sgp",
              vm_plan="vc2-2c-4gb", os_name="Ubuntu 24.04 LTS x64", label="walnut-demo", branch="main",
              log=lambda s: None, sleep=lambda s: None)
    allowed = {"/firewalls": {"description"},
               "/ssh-keys": {"name", "ssh_key"},
               "/instances": {"region", "plan", "os_id", "label", "hostname", "sshkey_id", "firewall_group_id",
                              "backups", "enable_ipv6", "tags", "user_data"}}
    for method, path, body in sent:
        if method == "POST" and path in allowed:
            assert set(body) <= allowed[path], path
        if path.endswith("/rules"):
            assert set(body) == {"ip_type", "protocol", "subnet", "subnet_size", "port", "notes"}
            assert isinstance(body["subnet_size"], int) and isinstance(body["port"], str)
            assert body["protocol"] == "tcp"
    inst = next(b for m, p, b in sent if m == "POST" and p == "/instances")
    assert isinstance(inst["sshkey_id"], list) and inst["backups"] == "disabled"


def test_provision_cli_dry_run_needs_no_key(monkeypatch):
    monkeypatch.delenv("VULTR_API_KEY", raising=False)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = prov.main(["--repo-url", "https://github.com/example/walnut.git", "--ssh-key", "missing.pub"])
    assert rc == 0 and "DRY-RUN  POST https://api.vultr.com/v2/instances" in buf.getvalue()


def test_provision_apply_without_a_key_refuses(monkeypatch):
    monkeypatch.delenv("VULTR_API_KEY", raising=False)
    assert prov.main(["--repo-url", "x", "--ssh-key", "y", "--apply"]) == 2


# -- static checks on the kit -------------------------------------------------------------------------
def test_cloud_init_is_valid_yaml_and_holds_no_secret():
    text = (VULTR / "cloud-init.yaml").read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    assert text.startswith("#cloud-config") and "runcmd" in doc
    assert not re.search(r"IB_MODEL_KEY=\S|VULTR_API_KEY=\S|IB_TOKEN_KEY=\S", text)
    assert any("ufw allow 443/tcp" in " ".join(c) for c in doc["runcmd"])


def test_the_edge_serves_the_files_the_public_pages_read():
    caddy = (DOCKER / "Caddyfile").read_text(encoding="utf-8")
    assert "/eval_summary.json" in caddy                           # Trust centre (lib/api.ts evalSummary)
    # ...and the image must hold it: Next's standalone output leaves public/ behind
    assert "public/eval_summary.json ./public/eval_summary.json" in (DOCKER / "Dockerfile.web").read_text(encoding="utf-8")
    assert re.search(r"^\s*email \{\$ACME_EMAIL\}", caddy, re.M)     # Caddy >= 2.8: no email, no ZeroSSL fallback
    env = yaml.safe_load((DOCKER / "docker-compose.yml").read_text(encoding="utf-8"))["services"]["caddy"]["environment"]
    assert "ACME_EMAIL" in env


def test_deploy_script_survives_a_fresh_vm_and_always_prints_the_url():
    sh = (DOCKER / "deploy.sh").read_text(encoding="utf-8")
    assert "DPkg::Lock::Timeout" in sh
    # every apt-get but the retry itself and one optional probe goes through the retry
    bare = [l for l in sh.splitlines() if "apt-get" in l and "apt_retry" not in l and "warn " not in l and "die " not in l]
    assert len(bare) == 2, bare
    # a failed smoke test still prints the URL and passcode before it exits
    finish = sh[sh.index("finish() {"):]
    assert finish.index("summary") < finish.index("die ")
    assert "nip.io" in sh                                          # the documented way out of a rate limit


def test_cloud_init_logs_every_step_to_the_one_log():
    doc = yaml.safe_load((VULTR / "cloud-init.yaml").read_text(encoding="utf-8"))
    assert len(doc["runcmd"]) == 1
    cmd = " ".join(doc["runcmd"][0])
    assert cmd.index("git clone") < cmd.index("> /var/log/walnut-deploy.log")   # a clone failure lands in the log
    assert "HOME=/root" in cmd and "FAILED" in cmd


def test_compose_only_caddy_publishes_ports_and_model_settings_reach_ib():
    doc = yaml.safe_load((DOCKER / "docker-compose.yml").read_text(encoding="utf-8"))
    published = {n for n, s in doc["services"].items() if s.get("ports")}
    assert published == {"caddy"}
    env = doc["services"]["ib"]["environment"]
    for k in ("IB_MODEL_URL", "IB_MODEL_NAME", "IB_MODEL_KEY", "IB_MODEL_FALLBACKS",
              "IB_MODEL_PRICE_IN_USD", "IB_MODEL_PRICE_OUT_USD", "IB_MODEL_DAILY_CAP_USD",
              "IB_MODEL_REASONING_EFFORT"):
        assert k in env and str(env[k]).startswith("${"), k              # from the env file, never literal
    # in-stack traffic passes the Host allowlists, and ticket links point at the public origin
    assert env["IB_ALLOWED_HOSTS"] == "ib" and "IB_PUBLIC_ORIGIN" in env
    assert doc["services"]["mock"]["environment"]["MOCK_ALLOWED_HOSTS"] == "mock"
    assert doc["networks"]["backend"]["internal"] is True
    assert "egress" in doc["services"]["ib"]["networks"] and "egress" not in doc["services"]["mock"]["networks"]


def test_no_real_key_anywhere_in_the_kit():
    pat = re.compile(r"(IB_MODEL_KEY|VULTR_API_KEY)=(?!$|<|\s|\"|\.\.\.)\S+", re.M)
    for p in list(VULTR.glob("*")) + list(DOCKER.glob("*")) + [DOCKER / ".env.example"]:
        if p.is_file() and p.suffix != ".pyc":
            assert not pat.search(p.read_text(encoding="utf-8", errors="replace")), p.name

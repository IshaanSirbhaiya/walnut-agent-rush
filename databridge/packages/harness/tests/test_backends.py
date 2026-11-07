"""The capability table is a reviewed fact, caps lookup is by provider prefix, and the one real
backend (``ChatBackend``) is a plain chat-completions client: no vendor SDK, no default endpoint,
and a local-only model never leaves the customer's network."""
from __future__ import annotations

import types

import pytest

from databridge_harness import ChatBackend, EndpointRefused, ModelCallError, ModelTimeout, ModelTruncated
from databridge_harness.backends import (CAPABILITIES, caps_for, is_hosted, is_local_url,
                                         provider_of, split_model)


def test_capability_table():
    c = CAPABILITIES["chat/*"]
    assert (c.json_mode, c.strict_schema, c.tools, c.guided_decoding, c.seed) == \
        (True, False, True, False, True)
    lo = CAPABILITIES["local/*"]
    assert (lo.json_mode, lo.strict_schema, lo.tools, lo.guided_decoding, lo.seed) == \
        (True, False, "varies", False, True)
    v = CAPABILITIES["local_server/*"]
    assert (v.json_mode, v.strict_schema, v.tools, v.guided_decoding, v.seed) == \
        (True, True, True, "guided_json", True)


def test_only_the_local_server_has_guided_decoding():
    assert caps_for("local_server/x").has_guided_decoding is True
    assert caps_for("chat/x").has_guided_decoding is False
    assert caps_for("local/x").has_guided_decoding is False


def test_unknown_provider_is_conservative():
    c = caps_for("mystery/model")
    assert c.json_mode is False and c.has_guided_decoding is False and c.seed is False


def test_is_hosted_matches_perimeter_rule():
    assert is_hosted("chat/any-model") is True
    assert is_hosted("local/any-model") is False          # local
    assert is_hosted("local_server/any-model") is False    # local-served
    assert provider_of("local/model:72b") == "local"
    assert split_model("chat/org/model-x") == ("chat", "org/model-x")
    assert split_model("bare-name") == ("chat", "bare-name")


def test_local_url_rule():
    for url in ("http://localhost:8000/v1", "http://127.0.0.1:11434/v1", "http://[::1]:9/v1",
                "http://10.0.0.5/v1", "http://192.168.1.2/v1", "http://llm.internal/v1",
                "http://gpu-box:8000/v1"):
        assert is_local_url(url), url
    for url in ("https://models.example.com/v1", "https://8.8.8.8/v1", "", "not a url"):
        assert not is_local_url(url), url


class _Recorder:
    def __init__(self, reply=None, status=200, exc=None):
        self.calls: list[dict] = []
        self.reply = reply if reply is not None else {
            "model": "served-name", "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2}}
        self.status, self.exc = status, exc

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if self.exc is not None:
            raise self.exc
        return types.SimpleNamespace(status_code=self.status, json=lambda: self.reply)


def test_chat_backend_posts_the_common_shape(monkeypatch):
    monkeypatch.setenv("IB_MODEL_URL", "https://models.example.com/v1/")
    monkeypatch.setenv("IB_MODEL_KEY", "k-secret")
    rec = _Recorder()
    raw = ChatBackend(client=rec).generate(model="chat/my-model",
                                           messages=[{"role": "user", "content": "hi"}],
                                           json_mode=True, seed=7, max_tokens=16, timeout=5)
    (call,) = rec.calls
    assert call["url"] == "https://models.example.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer k-secret"
    assert call["json"]["model"] == "my-model" and call["json"]["temperature"] == 0
    assert call["json"]["seed"] == 7 and call["json"]["max_tokens"] == 16
    assert call["json"]["response_format"] == {"type": "json_object"}
    assert call["timeout"] == 5
    assert (raw.text, raw.tokens_in, raw.tokens_out, raw.served_model) == ("ok", 3, 2, "served-name")
    assert raw.model_used == "chat/my-model"


def test_no_endpoint_means_no_call(monkeypatch):
    monkeypatch.delenv("IB_MODEL_URL", raising=False)
    rec = _Recorder()
    with pytest.raises(EndpointRefused):
        ChatBackend(client=rec).generate(model="chat/m", messages=[])
    with pytest.raises(EndpointRefused):
        ChatBackend("https://x.example/v1", client=rec).generate(model="mystery/m", messages=[])
    assert rec.calls == []


def test_a_local_model_never_goes_to_a_public_host():
    rec = _Recorder()
    with pytest.raises(EndpointRefused):
        ChatBackend("https://models.example.com/v1", client=rec).generate(model="local/m", messages=[])
    assert rec.calls == []
    ChatBackend("http://127.0.0.1:8000/v1", client=rec).generate(model="local/m", messages=[])
    assert len(rec.calls) == 1


def test_errors_carry_the_status_never_the_body_or_key():
    rec = _Recorder(reply={"error": "k-secret was rejected"}, status=429)
    with pytest.raises(ModelCallError) as e:
        ChatBackend("https://x.example/v1", "k-secret", client=rec).generate(model="chat/m", messages=[])
    assert e.value.status_code == 429 and "k-secret" not in str(e.value)

    class ReadTimeout(Exception):
        pass
    with pytest.raises(ModelTimeout):
        ChatBackend("https://x.example/v1", client=_Recorder(exc=ReadTimeout("slow"))).generate(
            model="chat/m", messages=[])
    cut = _Recorder(reply={"choices": [{"message": {"content": "half"}, "finish_reason": "length"}]})
    with pytest.raises(ModelTruncated):
        ChatBackend("https://x.example/v1", client=cut).generate(model="chat/m", messages=[])


def test_embeddings_keep_input_order():
    rec = _Recorder(reply={"data": [{"index": 1, "embedding": [0.0, 1.0]},
                                    {"index": 0, "embedding": [1.0, 0.0]}],
                           "usage": {"prompt_tokens": 4}})
    raw = ChatBackend("https://x.example/v1", client=rec).embed(model="chat/e", inputs=["a", "b"])
    assert raw.vectors == [[1.0, 0.0], [0.0, 1.0]] and raw.tokens == 4
    assert rec.calls[0]["url"].endswith("/embeddings") and rec.calls[0]["json"]["model"] == "e"


def test_the_placeholder_names_are_the_configured_ones(monkeypatch):
    monkeypatch.setenv("IB_MODEL_NAME", "main-model")
    monkeypatch.setenv("IB_MODEL_FALLBACKS", "second-model, third-model")
    rec = _Recorder()
    b = ChatBackend("https://x.example/v1", client=rec)
    b.generate(model="chat/default", messages=[])
    b.generate(model="chat/alt", messages=[])
    assert [c["json"]["model"] for c in rec.calls] == ["main-model", "second-model"]
    monkeypatch.delenv("IB_MODEL_NAME")
    with pytest.raises(EndpointRefused):
        b.generate(model="chat/default", messages=[])
    assert len(rec.calls) == 2


def test_the_harness_imports_only_the_standard_library_and_its_three_dependencies():
    """The harness speaks plain HTTP: besides the standard library it may import only pydantic,
    httpx and databridge_core, so no vendor SDK or multi-vendor router can creep in."""
    import ast
    import sys
    from pathlib import Path

    allowed = {"pydantic", "httpx", "databridge_core", "databridge_harness"}
    pkg = Path(__file__).resolve().parents[1] / "databridge_harness"
    found = set()
    for f in pkg.glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                found.add(node.module.split(".")[0])
    extra = {m for m in found if m not in allowed and m not in sys.stdlib_module_names}
    assert not extra, extra

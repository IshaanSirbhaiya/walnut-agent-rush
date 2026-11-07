"""With a model configured (FAKE endpoint), every label a person sees is the neutral adapter's.

The browser keys off ``/ib/status``: ``models.active`` (any model) and ``models.active_provider``
("model" for the one configured adapter, None without one). The rules checked here:

1. ``/ib/status`` and the answer name only provider ``model`` and the configured model name (and
   the answer is never labelled extractive while the model wrote it);
2. no response ever carries the endpoint URL, its host or the key, not even to admin or compliance;
3. without a model, the status says so and the answer is the deterministic extractive one.
"""
from __future__ import annotations

import json

from test_deliverables import _ask, _c, _tag_of, _world

from model_fakes import FakeModel, configure

URL = "https://models.internal-endpoint.test/v1"
KEY = "k-secret-not-real-123"


def _reply(kind, text):
    tag = _tag_of(text, "SME pricing by market")
    return f"Indonesian SME customers are priced at a 0.4% FX margin [{tag}]."


def _bodies(app, svc):
    jd = _c(app, svc, "jdoe")
    st = jd.get("/ib/status").json()
    ans = _ask(jd)
    svc.directory._users["priya"] = svc.directory.get("priya").model_copy(update={"roles": ("admin_it",)})
    admin = _c(app, svc, "priya").get("/ib/status").json()
    return st, ans, admin


def test_status_and_answer_name_the_configured_model_only(tmp_path, monkeypatch):
    from databridge_ib.llm import ModelChain
    monkeypatch.setenv("IB_DELIVERABLES", "1")
    configure(monkeypatch, "main-model", ["second-model"], url=URL, key=KEY)
    chain = ModelChain.from_env(inner=FakeModel(_reply))
    app, svc = _world(tmp_path / "w", chain=chain)
    st, ans, admin = _bodies(app, svc)
    m = st["models"]
    assert m["active"] is True and m["active_provider"] == "model" and m["provider"] == "model"
    assert m["active_chain"] == ["main-model", "second-model"] == m["chain"]
    assert st["key_configured"] is True
    assert ans["model"] == {"provider": "model", "model": "main-model", "fallback_used": False}
    for body in (json.dumps(st), json.dumps(ans), json.dumps(admin)):
        assert KEY not in body
        assert URL not in body and "internal-endpoint" not in body


def test_a_fallback_model_is_labelled_as_such(tmp_path, monkeypatch):
    from databridge_ib.llm import ModelChain
    configure(monkeypatch, "main-model", ["second-model"], url=URL, key=KEY)

    calls = []

    class Flaky(FakeModel):
        def generate(self, *, model, messages, **kw):
            calls.append(model)
            if model.endswith("/main-model"):
                raise RuntimeError("down")
            return super().generate(model=model, messages=messages, **kw)
    chain = ModelChain.from_env(inner=Flaky(_reply))
    app, svc = _world(tmp_path / "w", chain=chain)
    ans = _ask(_c(app, svc, "jdoe"))
    assert calls == ["chat/main-model", "chat/second-model"]
    assert ans["model"] == {"provider": "model", "model": "second-model", "fallback_used": True}


def test_without_a_model_the_answer_is_quoted_and_the_status_says_so(tmp_path):
    app, svc = _world(tmp_path / "w", chain=None)
    jd = _c(app, svc, "jdoe")
    m = jd.get("/ib/status").json()["models"]
    assert m["active"] is False and m["active_provider"] is None and m["provider"] is None
    assert m["chain"] == [] and m["active_chain"] == []
    assert m["fallback"] == {"provider": "deterministic", "model": "extractive-v1"}
    assert _ask(jd)["model"]["model"] == "extractive-v1"

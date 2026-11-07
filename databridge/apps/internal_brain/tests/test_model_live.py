"""IB_MODEL_LIVE: a configured model a launcher found NOT live is never built, so never called.

``bootstrap.select_chain`` builds the one adapter's chain unless ``IB_MODEL_LIVE`` is set and not
"1" (unset: a configured model is used), and never under ``IB_FORCE_OFFLINE=1``. ``/ib/status``
reports the flag as ``models.primary_live``. FAKE endpoint only: no network, no spend.
"""
from __future__ import annotations

import pytest

from test_deliverables import _ask, _c, _tag_of, _world

from model_fakes import FakeModel, configure


def _reply(kind, text):
    tag = _tag_of(text, "SME pricing by market")
    return f"Indonesian SME customers are priced at a 0.4% FX margin [{tag}]."


@pytest.fixture
def built(monkeypatch):
    """A model is configured; records every chain build."""
    from databridge_ib.llm import ModelChain
    configure(monkeypatch)
    calls: list[str] = []
    real = ModelChain.from_env.__func__

    def guarded(cls, *a, **kw):
        calls.append("built")
        return real(cls, *a, **kw)
    monkeypatch.setattr(ModelChain, "from_env", classmethod(guarded))
    return calls


def test_a_model_not_live_is_never_built_and_answers_are_quoted(tmp_path, monkeypatch, built):
    from databridge_ib.bootstrap import select_chain
    monkeypatch.setenv("IB_MODEL_LIVE", "0")
    fake = FakeModel(_reply)
    chain = select_chain(tmp_path / "views", inner=fake)
    assert chain is None and built == []                           # not even built
    app, svc = _world(tmp_path / "w", chain=chain)
    jd = _c(app, svc, "jdoe")
    assert _ask(jd)["model"]["model"] == "extractive-v1" and fake.calls == []
    m = jd.get("/ib/status").json()["models"]
    assert m["active"] is False and m["active_provider"] is None and m["primary_live"] is False


@pytest.mark.parametrize("live", ["1", None])
def test_a_live_or_unflagged_model_is_the_chain_and_answers(tmp_path, monkeypatch, built, live):
    from databridge_ib.bootstrap import select_chain
    if live is None:
        monkeypatch.delenv("IB_MODEL_LIVE", raising=False)
    else:
        monkeypatch.setenv("IB_MODEL_LIVE", live)
    fake = FakeModel(_reply)
    chain = select_chain(tmp_path / "views", inner=fake)
    assert chain is not None and chain.provider == "model" and list(chain.models) == ["main-model"]
    assert built == ["built"]
    app, svc = _world(tmp_path / "w", chain=chain)
    jd = _c(app, svc, "jdoe")
    ans = _ask(jd)
    assert ans["model"] == {"provider": "model", "model": "main-model", "fallback_used": False}
    assert fake.calls
    m = jd.get("/ib/status").json()["models"]
    assert m["active"] is True and m["active_provider"] == "model"
    assert m["primary_live"] is (True if live == "1" else None)


def test_force_offline_still_wins(tmp_path, monkeypatch, built):
    from databridge_ib.bootstrap import select_chain
    monkeypatch.setenv("IB_FORCE_OFFLINE", "1")
    monkeypatch.setenv("IB_MODEL_LIVE", "1")
    fake = FakeModel(_reply)
    assert select_chain(tmp_path / "views", inner=fake) is None and fake.calls == []


# the guard on a FIRST run: no guard dir yet -> created fresh, calls allowed, spend 0
def test_model_guard_first_run_creates_the_dir_and_allows_calls(tmp_path):
    from databridge_ib.model_guard import Caps, ModelGuard
    d = tmp_path / "databridge" / "var" / "model_guard"          # not even var/ exists yet
    assert not d.parent.exists()
    g = ModelGuard(d, Caps())
    assert d.is_dir() and (d / "spend.json").is_file()
    st = g.status()
    assert st["ok"] is True and st["available"] is True
    assert float(st["spent_usd"]) == 0.0 and int(st["calls"]) == 0
    ticket, why = g.admit("jdoe", "answer", 0.05)
    assert ticket is not None and why == "none"
    g.settle(ticket, 0.01)
    assert int(ModelGuard(d, Caps()).status()["calls"]) == 1      # a restart reads the same ledger

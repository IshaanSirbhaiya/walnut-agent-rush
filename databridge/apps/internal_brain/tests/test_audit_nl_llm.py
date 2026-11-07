"""B13: the plain-English audit search's model parser over the answers' chain (a fake chain here):
valid JSON is used, invalid output or an exception falls back to the rule parser, the model sees only
the question and the clock, and the route records which parser was used."""
from __future__ import annotations

import datetime as dt
import json
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from databridge_harness import FakeBackend, Harness
from databridge_ib import bootstrap
from databridge_ib.audit.anchor import FileSink
from databridge_ib.audit.ledger import AccessLedger
from databridge_ib.audit.nl_filter import NlFilterError, parse_audit_question
from databridge_ib.audit.nl_llm import (FIELDS, ModelFilterError, make_chain_parser,
                                        parse_filter_json)
from databridge_ib.audit.query import AuditProjection
from databridge_ib.audit.routes import make_audit_router
from databridge_ib.llm import ModelChain

from test_audit_routes import CO, require_role
from test_audit_support import NOW, SPECS, clone, seed

VAGUE = "anything odd lately with zed?"          # the rules recognise nothing here


def _chain(reply_for: dict, seen: list):
    """A two-model chain (model-a -> model-b) over FakeBackends. ``reply_for[model]`` is the text
    that model returns, or an exception to raise."""
    def factory(model: str):
        def respond(model=None, messages=None, guided_json=None, _name=model):
            seen.append((_name, json.loads(json.dumps(messages))))
            r = reply_for.get(_name, "")
            if isinstance(r, Exception):
                raise r
            return r
        cfg = {"routing": {"ib_answer": "m"}, "aliases": {"m": {"model": f"chat/{model}"}},
               "profiles": {"cloud": {}, "airgapped": {}}}
        return Harness(FakeBackend(respond), config=cfg, profile="cloud", cache=None)
    return ModelChain(models=["model-a", "model-b"], harness_factory=factory)


def _valid(now=NOW) -> str:
    return json.dumps({"user": "zed", "since": (now - dt.timedelta(days=3)).isoformat(),
                       "until": now.isoformat(), "decision": "deny"})


def test_valid_json_is_used_and_names_the_model():
    seen: list = []
    parser = make_chain_parser(_chain({"model-a": _valid()}, seen))
    r = parse_audit_question(VAGUE, NOW, llm=parser, llm_fallback=True)
    assert r.source == "llm" and r.model == "model-a"
    assert (r.filter.user, r.filter.decision) == ("zed", "deny")
    assert r.filter.since == NOW - dt.timedelta(days=3)


def test_falls_through_the_chain_to_the_fallback():
    seen: list = []
    parser = make_chain_parser(_chain({"model-a": RuntimeError("429"),
                                       "model-b": "```json\n" + _valid() + "\n```"},
                                      seen))
    r = parse_audit_question(VAGUE, NOW, llm=parser, llm_fallback=True)
    assert r.source == "llm" and r.model == "model-b"
    assert [m for m, _ in seen] == ["model-a", "model-b"]


@pytest.mark.parametrize("reply", [
    "Sure! Here is the filter: user=zed",                    # not JSON
    json.dumps([{"user": "zed"}]),                           # not an object
    json.dumps({"user": "zed", "where": "1=1"}),             # outside the closed vocabulary
    json.dumps({"user": "zed; DROP TABLE"}),                 # fails the AuditFilter pattern
    json.dumps({"kind": "everything"}),                      # not an event kind
    json.dumps({"since": "2026-13-45"}),                     # not a date
])
def test_invalid_output_falls_back_to_the_rules(reply):
    parser = make_chain_parser(_chain({"model-a": reply, "model-b": reply}, []))
    r = parse_audit_question(VAGUE, NOW, llm=parser, llm_fallback=True)
    det = parse_audit_question(VAGUE, NOW)
    assert r.source == "deterministic" and r.model is None and r.model_tried
    assert r.filter == det.filter
    assert any("rule parser" in n for n in r.notes)


def test_exception_falls_back_to_the_rules():
    parser = make_chain_parser(_chain({"model-a": RuntimeError("down"),
                                       "model-b": TimeoutError("slow")}, []))
    r = parse_audit_question(VAGUE, NOW, llm=parser, llm_fallback=True)
    assert r.source == "deterministic" and r.filter == parse_audit_question(VAGUE, NOW).filter

    def boom(q, now):
        raise RuntimeError("parser crashed")
    assert parse_audit_question(VAGUE, NOW, llm=boom, llm_fallback=True).source == "deterministic"


def test_without_fallback_the_old_fail_closed_contract_holds():
    parser = make_chain_parser(_chain({"model-a": "nope", "model-b": "nope"}, []))
    with pytest.raises(NlFilterError):
        parse_audit_question(VAGUE, NOW, llm=parser)


def test_rules_first_the_model_is_not_asked_when_they_recognise_something():
    seen: list = []
    parser = make_chain_parser(_chain({"model-a": _valid()}, seen))
    r = parse_audit_question("denied requests for ken.ext", NOW, llm=parser, llm_fallback=True)
    assert r.source == "deterministic" and not r.model_tried and seen == []


def test_the_model_sees_only_the_question_the_clock_and_the_vocabulary(tmp_path):
    seen: list = []
    parser = make_chain_parser(_chain({"model-a": _valid()}, seen))
    parse_audit_question(VAGUE, NOW, llm=parser, llm_fallback=True)
    (model, messages), = seen
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[1]["content"] == f"Current time: {NOW.isoformat()}\nQuestion: {VAGUE}"
    blob = json.dumps(messages)
    for sp in SPECS:                                  # nothing from any ledger row
        assert sp.req_id not in blob and sp.question not in blob and sp.answer not in blob
    for f in FIELDS:
        assert f'"{f}"' in messages[0]["content"]


def test_parse_filter_json_is_strict():
    assert parse_filter_json('{"user": "zed", "doc": null}') == {"user": "zed"}
    for bad in ("", "null", "[]", '{"user": "zed"} trailing', '{"limit": 5, "x": 1}'):
        with pytest.raises(ModelFilterError):
            parse_filter_json(bad)


@pytest.fixture
def route(tmp_path_factory, tmp_path):
    src = tmp_path_factory.mktemp("nl-llm-src")
    seed(src)
    cfg, _, store = clone(src, tmp_path)
    ledger = AccessLedger(cfg, external=FileSink(tmp_path / "ext" / "heads.jsonl"))

    def make(parser):
        app = FastAPI()
        app.include_router(make_audit_router(ledger, store, AuditProjection(ledger), require_role,
                                             llm=parser, llm_fallback=True, clock=lambda: NOW))
        return TestClient(app)
    yield make, ledger
    store.close()


def _last_ask(ledger) -> dict:
    return [e.data["filter"] for e in ledger.events() if e.kind == "audit.query"
            and e.data["filter"].get("op") == "ask"][-1]


def test_route_records_the_parser_used(route):
    make, ledger = route
    c = make(make_chain_parser(_chain({"model-a": _valid()}, [])))
    body = c.post("/audit/ask", json={"question": VAGUE}, headers=CO).json()
    assert body["parser"] == "llm" and body["parser_model"] == "model-a"
    assert _last_ask(ledger)["parser"] == "llm" and _last_ask(ledger)["parser_model"] == "model-a"

    c = make(make_chain_parser(_chain({"model-a": "not json", "model-b": "{}x"}, [])))
    r = c.post("/audit/ask", json={"question": VAGUE}, headers=CO)
    assert r.status_code == 200
    body = r.json()
    assert body["parser"] == "deterministic" and body.get("parser_fallback") is True
    assert "parser_model" not in body
    assert _last_ask(ledger)["parser"] == "deterministic"


def test_bootstrap_wires_the_chain_only_when_one_is_active():
    svc = types.SimpleNamespace(pipeline=types.SimpleNamespace(chain=None))
    assert bootstrap.audit_filter_parser(svc) is None              # no key, or IB_FORCE_OFFLINE=1
    seen: list = []
    svc.pipeline.chain = _chain({"model-a": _valid()}, seen)
    parser = bootstrap.audit_filter_parser(svc)
    assert parser is not None
    assert parse_audit_question(VAGUE, NOW, llm=parser, llm_fallback=True).model == "model-a"


def test_forced_offline_gives_no_chain(monkeypatch):
    monkeypatch.setenv("IB_MODEL_URL", "https://models.invalid/v1")
    monkeypatch.setenv("IB_MODEL_NAME", "model-a")
    monkeypatch.setenv("IB_MODEL_KEY", "test-key-not-real")
    monkeypatch.setenv("IB_FORCE_OFFLINE", "1")
    assert ModelChain.from_env() is None

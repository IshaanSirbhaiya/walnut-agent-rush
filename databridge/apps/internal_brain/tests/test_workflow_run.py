"""The real-task workflow runner (``databridge/scripts/workflow_run.py``) end to end, in process.

The Brain is the app ``bootstrap.build_app`` builds (audit console included), over the REAL mock
platforms (in-process) and the REAL connectors, a real ledger, answer store and projection. Only the
transport differs from a deployment: the runner's sessions call the app through a TestClient instead of
HTTP. Expectations come from the world's facts, never written down here.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from databridge_ib import bootstrap
from databridge_ib.config import IbConfig
from databridge_ib.models import REFUSAL_TEXT
from e2e_world import ADMIN, CONNECTORS, SECRET, SVC, WORLD, _Client, load_world

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "workflow_run.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("workflow_run", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    import sys
    sys.modules["workflow_run"] = mod               # dataclasses resolve types through it
    spec.loader.exec_module(mod)
    return mod


wr = _load_runner()
FACTS = {f["id"]: f for f in load_world()["facts"]}


class TCSession:
    """The runner's Session contract (``call``) over a TestClient: one cookie jar per person."""

    def __init__(self, app):
        self.c = TestClient(app)

    def call(self, method, path, body=None):
        r = self.c.request(method, "/" + path.lstrip("/"), json=body)
        if r.status_code >= 400:
            try:
                parsed = r.json()
            except Exception:                                          # noqa: BLE001
                parsed = r.text
            raise wr.ApiError(r.status_code, parsed)
        return r.json()


@pytest.fixture(scope="module")
def app(tmp_path_factory, monkeypatch_module):
    import importlib

    from mock_platforms.app import create_app as create_mock

    tmp = tmp_path_factory.mktemp("workflow")
    holder: dict = {}

    def sink(platform, headers, body):                 # mock webhooks -> the Brain's own ingestor
        svc = holder.get("svc")
        conn = svc.connectors.get(platform) if svc else None
        if conn is None:
            return
        for ev in conn.parse_webhook({k.lower(): v for k, v in headers.items()}, body):
            svc.ingestor.apply_event(ev)

    mock = create_mock(WORLD, webhook_sink=sink, svc_token=SVC, admin_token=ADMIN, webhook_secret=SECRET)
    svc_c = _Client(mock, base_url="http://testserver", headers={"Authorization": f"Bearer {SVC}"})
    admin_c = _Client(mock, base_url="http://testserver", headers={"Authorization": f"Bearer {ADMIN}"})

    def connectors(cfg, directory):
        out = {}
        for platform, (mod, cls, prefix) in CONNECTORS.items():
            klass = getattr(importlib.import_module(mod), cls)
            out[platform] = klass(svc_c, directory, SECRET, admin_c, prefix=prefix)
        return out

    monkeypatch_module.setattr(bootstrap, "build_connectors", connectors)
    monkeypatch_module.delenv("IB_DEMO_PASSCODE", raising=False)
    monkeypatch_module.setenv("IB_FORCE_OFFLINE", "1")
    cfg = IbConfig(var_root=tmp / "var", demo_login=True, webhook_secret=SECRET,
                   engine_graph_db=tmp / "graph" / "enterprise.db", engine_token="", anchor_interval_s=0)
    built = bootstrap.build_app(cfg, sync=True)
    holder["svc"] = built.state.svc
    return built


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def _run(app, **kw):
    # the app is shared by this module; the action rate limit (10 a minute per person) is not under test here
    actions = app.state.svc.actions
    for limiter in (actions._rate, actions._confirm_rate):
        limiter._hits.clear()
        limiter._over.clear()
    lines: list[str] = []

    class Sink:
        def write(self, s):
            lines.append(s)

        def flush(self):
            pass

    wf = wr.Workflow(lambda: TCSession(app), out=wr.Out(stream=Sink()), target="in-process", **kw)
    rep = wf.run()
    return rep, "".join(lines)


def test_procurement_workflow_runs_end_to_end_with_approval(app):
    rep, text = _run(app, scenario="procurement", approve=True)
    assert rep.ok, text
    steps = {s.n: s for s in rep.steps}
    assert len(steps) == 7
    # the cited answer carries the two policy facts the question needs (derived from the world)
    cited = set(steps[2].detail["citations"])
    for fid in ("WP-approval-limits", "WP-procurement-quotes"):
        assert FACTS[fid]["doc"] in cited, (fid, cited)
    assert steps[2].detail["model"]["provider"] == "deterministic"          # forced offline here
    # the draft is never sent
    assert steps[3].detail["sent"] is False and steps[3].detail["sentences"] >= 2
    # the ticket is created only after approval, once, in a project checked live
    assert steps[4].detail["project"] == "ITHELP"
    assert steps[5].detail["outcome"] == "created" and steps[5].detail["issue"].startswith("ITHELP-")
    # the audit pull sees every sealed step of this request and an intact chain
    ev = steps[6].detail["events"]
    for kind in ("request.accepted", "retrieval.decided", "answer.released", "action.proposed",
                 "action.confirmed", "action.executed"):
        assert kind in ev, (kind, ev)
    assert ev.index("action.confirmed") < ev.index("action.executed")      # write-ahead
    assert steps[6].detail["verify_ok"] is True
    # the contractor gets the constant refusal
    assert steps[7].detail["refused"] is True
    assert REFUSAL_TEXT == wr.REFUSAL


def test_filed_tickets_do_not_crowd_out_the_policies_when_the_question_is_asked_again(app):
    """A run files a ticket, and tickets are indexed. Its summary repeated the question ("12 laptops") once: after
    two runs the answer was only the last ticket, citing no policy, for the next person to ask."""
    for _ in range(2):
        rep, text = _run(app, scenario="procurement", approve=True)
        assert rep.ok, text
    rep, text = _run(app, scenario="procurement", approve=False)
    steps = {s.n: s for s in rep.steps}
    cited = set(steps[2].detail["citations"])
    for fid in ("WP-approval-limits", "WP-procurement-quotes"):
        assert FACTS[fid]["doc"] in cited, (fid, cited)
    assert not any(str(c).startswith("jira:") or "ITHELP" in str(c) for c in cited), cited


def test_the_answer_is_exactly_the_two_policies_it_needs(app):
    rep, text = _run(app, scenario="procurement", approve=False)
    steps = {s.n: s for s in rep.steps}
    want = {FACTS[f]["doc"] for f in ("WP-approval-limits", "WP-procurement-quotes")}
    assert set(steps[2].detail["citations"]) == want, text


def test_rejected_approval_creates_nothing_and_is_ledgered(app):
    rep, text = _run(app, scenario="procurement", approve=False)
    assert rep.ok, text
    steps = {s.n: s for s in rep.steps}
    assert steps[5].detail["outcome"] == "rejected"
    ev = steps[6].detail["events"]
    assert "action.rejected" in ev and "action.executed" not in ev and "action.confirmed" not in ev


def test_no_terminal_and_no_flag_means_not_approved(app, monkeypatch):
    class NoTty:
        def isatty(self):
            return False
    monkeypatch.setattr(wr.sys, "stdin", NoTty())
    rep, text = _run(app, scenario="procurement", approve=None)
    steps = {s.n: s for s in rep.steps}
    assert steps[5].detail["outcome"] == "rejected", text


def test_support_workflow_refuses_the_ticket_at_action_time(app):
    rep, text = _run(app, scenario="support", approve=True)
    assert rep.ok, text
    steps = {s.n: s for s in rep.steps}
    script = FACTS["CX-review-script"]
    assert script["doc"] in steps[2].detail["citations"]
    assert steps[3].detail["model"]["model"] == "approved-script-v1"       # approved wording, no model
    assert steps[4].detail["outcome"] == "refused"                          # no create permission
    assert "action.failed" in steps[6].detail["events"]
    # nothing from the case reaches Amy's steps or her request's audit trail (Rachel, the contrast,
    # may open it: her step is left out)
    blob = json.dumps([s for s in rep.to_json()["steps"] if s["n"] <= 6])
    assert steps[7].detail["refused"] is False                              # Rachel gets an answer
    for fid, f in FACTS.items():
        if fid.startswith("FINCRIME-"):
            assert f["doc"] not in blob and f["canary"] not in blob


def test_report_json_shape(app, tmp_path):
    rep, _ = _run(app, scenario="procurement", approve=True)
    d = rep.to_json()
    assert d["ok"] is True and d["req_id"] and len(d["steps"]) == 7
    assert all({"n", "name", "ok", "ms"} <= set(s) for s in d["steps"])


def test_unknown_scenario_is_refused():
    with pytest.raises(ValueError):
        wr.Workflow(lambda: None, scenario="nope")


def test_cli_requires_a_target(capsys, monkeypatch):
    monkeypatch.delenv("WALNUT_BASE_URL", raising=False)
    with pytest.raises(SystemExit):
        wr.main([])

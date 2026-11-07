#!/usr/bin/env python3
"""Run one real enterprise workflow end to end against a running Walnut stack, and check every step.

The "real task" for judges and operators: a **procurement request** at Company A (synthetic).

  1. Alex (IT admin) signs in and asks what a SGD 18,000 laptop purchase needs.
  2. Walnut answers through both permission gates (index ACL, then a live per-document check at the
     source), with a citation on every sentence (``[C1]`` ...).
  3. Walnut drafts the approval note for Alex's department head from the cited sentences only. The draft
     is returned for review and is never sent.
  4. Walnut proposes a follow-up ticket in a Jira project Alex may create issues in (checked live).
     **Nothing is created until a human approves.** Without ``--approve`` the script asks on the terminal;
     answering "no" cancels the proposal (ledgered as ``action.rejected``).
  5. On approval, Walnut re-checks access live and creates the ticket once (``action.confirmed`` is
     written ahead, then ``action.executed``).
  6. Maya (compliance) pulls the audit trail for that request: every document considered, each live
     Gate-2 verdict, every sealed ledger record (ask, gates, answer, draft, approval, execution), and
     verifies the hash chain.
  7. Contrast: Ken (an external contractor) asks the same question and gets the constant refusal, with no
     hint that a procurement policy exists.

A second scenario, ``--scenario support``, is the customer-support call (Amy, account manager): a cited
answer, a reply draft that uses the approved customer script word for word, and a follow-up ticket that
is refused politely because Amy may not create issues anywhere (permission checked at action time).

Usage (Python 3.9+, standard library only, so it also runs on a bare VM):

  # through the public edge of a deployment (Caddy -> web proxy -> Brain)
  python databridge/scripts/workflow_run.py --base https://<ip-with-dashes>.sslip.io --passcode <passcode>
  # straight at a local Brain started by hand (no web app)
  python databridge/scripts/workflow_run.py --ib http://127.0.0.1:8100 --approve
  # options: --approve (no prompt), --scenario support, --json report.json, --insecure (self-signed TLS)

Env fallbacks: ``WALNUT_BASE_URL`` (for --base), ``IB_DEMO_PASSCODE``. Exit status 0 only when every check
passes. All data is synthetic; the ticket is created on the in-stack mock Jira.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

#: the Brain's constant refusal (databridge_ib/models.py REFUSAL_TEXT)
REFUSAL = "I couldn't find an answer to that in the sources you can access."

SCENARIOS: dict[str, dict[str, Any]] = {
    "procurement": {
        "title": "Procurement request: 12 laptops, about SGD 18,000",
        "requester": "admin.it",
        "question": ("Who approves spend of SGD 18,000 on 12 laptops, and how many written quotes does "
                     "the purchase take?"),
        "draft_kind": "message",
        "draft_purpose": "approval note to the department head",
        "ticket": True,
        # not the question's own words: a filed ticket is indexed, and a summary repeating "12 laptops"
        # would outrank the policies the next time anyone asks (every run files one)
        "ticket_summary": ("Hardware purchase: three written quotes, purchase order, department head "
                           "and Head of Finance approval"),
        "expect_ticket": "created",
        "auditor": "maya.compliance",
        "contrast": "ken.ext",
    },
    "support": {
        "title": "Customer-support call: a restricted business account",
        "requester": "amy.am",
        "question": "Why has Velquarry Trading's account been restricted, and what should I tell the customer?",
        "draft_kind": "reply",
        "draft_purpose": "reply to the customer",
        "ticket": True,
        "ticket_summary": "Customer follow-up: account review query",
        "expect_ticket": "refused",          # Amy holds no Jira "Create issues" permission
        "auditor": "maya.compliance",
        "contrast": "mlro.tan",
    },
}


class ApiError(Exception):
    def __init__(self, status: int, body: Any):
        super().__init__(f"HTTP {status}")
        self.status, self.body = status, body


# -- transport -------------------------------------------------------------------------------------
class Session:
    """One signed-in person: their own cookie jar, so identity comes only from the Brain's token."""

    def __init__(self, base: str, prefix: str, *, insecure: bool = False, timeout: float = 150.0):
        self.base, self.prefix, self.timeout = base.rstrip("/"), prefix, timeout
        self.jar = http.cookiejar.CookieJar()
        handlers: list = [urllib.request.HTTPCookieProcessor(self.jar)]
        if insecure:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            handlers.append(urllib.request.HTTPSHandler(context=ctx))
        self.opener = urllib.request.build_opener(*handlers)
        p = urllib.parse.urlsplit(self.base)
        self.origin = f"{p.scheme}://{p.netloc}"

    def call(self, method: str, path: str, body: Optional[dict] = None) -> Any:
        url = f"{self.base}{self.prefix}/{path.lstrip('/')}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("accept", "application/json")
        if data is not None:
            req.add_header("content-type", "application/json")
            req.add_header("origin", self.origin)            # the web proxy's same-origin check
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                parsed = json.loads(raw)
            except Exception:                                         # noqa: BLE001
                parsed = raw.decode("utf-8", "replace")[:300]
            raise ApiError(e.code, parsed) from None


Transport = Callable[[], Any]


# -- report ----------------------------------------------------------------------------------------
@dataclass
class Step:
    n: int
    name: str
    ok: bool
    detail: dict = field(default_factory=dict)
    ms: int = 0


@dataclass
class Report:
    scenario: str
    title: str
    target: str
    steps: list[Step] = field(default_factory=list)
    req_id: Optional[str] = None

    @property
    def ok(self) -> bool:
        return bool(self.steps) and all(s.ok for s in self.steps)

    def to_json(self) -> dict:
        return {"scenario": self.scenario, "title": self.title, "target": self.target,
                "req_id": self.req_id, "ok": self.ok,
                "steps": [{"n": s.n, "name": s.name, "ok": s.ok, "ms": s.ms, **s.detail} for s in self.steps]}


class Out:
    def __init__(self, stream=None, quiet: bool = False):
        self.stream, self.quiet = stream or sys.stdout, quiet

    def __call__(self, line: str = "") -> None:
        if not self.quiet:
            print(line, file=self.stream, flush=True)


def _wrap(text: str, indent: str = "      ", width: int = 96) -> str:
    import textwrap
    return "\n".join(textwrap.fill(p, width=width, initial_indent=indent, subsequent_indent=indent)
                     for p in str(text).split("\n") if p.strip()) or indent


# -- the workflow ----------------------------------------------------------------------------------
class Workflow:
    def __init__(self, new_session: Callable[[], Session], *, passcode: str = "", scenario: str = "procurement",
                 approve: Optional[bool] = None, ask_human: Optional[Callable[[str], bool]] = None,
                 out: Optional[Out] = None, target: str = ""):
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {scenario!r} (choose from {', '.join(SCENARIOS)})")
        self.new_session, self.passcode = new_session, passcode
        self.sc = SCENARIOS[scenario]
        self.approve, self.ask_human = approve, ask_human
        self.out = out or Out()
        self.report = Report(scenario=scenario, title=self.sc["title"], target=target)

    # helpers
    def _sign_in(self, persona: str) -> tuple[Session, dict]:
        s = self.new_session()
        body = {"persona": persona}
        if self.passcode:
            body["passcode"] = self.passcode
        me = s.call("POST", "auth/demo-login", body)
        return s, me

    def _step(self, name: str, fn: Callable[[], tuple[bool, dict]]) -> Step:
        n = len(self.report.steps) + 1
        self.out(f"\n[{n}] {name}")
        t0 = time.monotonic()
        try:
            ok, detail = fn()
        except ApiError as e:
            ok, detail = False, {"error": f"HTTP {e.status}", "body": e.body}
            self.out(f"      ERROR HTTP {e.status}: {json.dumps(e.body)[:300]}")
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            ok, detail = False, {"error": f"{type(e).__name__}: {e}"}
            self.out(f"      ERROR {type(e).__name__}: {e}")
        step = Step(n, name, ok, detail, int((time.monotonic() - t0) * 1000))
        self.report.steps.append(step)
        self.out(f"      -> {'PASS' if ok else 'FAIL'} ({step.ms} ms)")
        return step

    def _human_approves(self, proposal: dict) -> bool:
        if self.approve is not None:
            return self.approve
        prompt = (f"      Approve creating this {proposal.get('issue_type', 'Task')} in "
                  f"{(proposal.get('project') or {}).get('key')}? [y/N] ")
        if self.ask_human is not None:
            return self.ask_human(prompt)
        if not sys.stdin.isatty():
            self.out("      (no terminal to ask on and no --approve: treating as NOT approved)")
            return False
        return input(prompt).strip().lower() in ("y", "yes")

    # the run
    def run(self) -> Report:
        sc, out = self.sc, self.out
        out(f"Walnut workflow: {sc['title']}")
        out(f"Target: {self.report.target or '(in-process)'}   (synthetic data only)")
        state: dict[str, Any] = {}

        def sign_in_requester():
            s, me = self._sign_in(sc["requester"])
            state["req_s"] = s
            out(f"      signed in as {me.get('name')} ({me.get('sub')}), roles {', '.join(me.get('roles', []))}")
            return me.get("sub") == sc["requester"], {"persona": me.get("sub")}

        def ask():
            out(_wrap(f"Q: {sc['question']}"))
            r = state["req_s"].call("POST", "ib/ask", {"question": sc["question"]})
            state["answer"] = r
            self.report.req_id = r.get("request_id")
            cites = r.get("citations") or []
            model = r.get("model") or {}
            out(_wrap(f"A: {r.get('answer')}"))
            for c in cites:
                out(f"      [{c.get('tag', '?')}] {c.get('platform')}: {c.get('title')} (version {c.get('version')})")
            label = ("quoted from sources (no model)" if model.get("provider") == "deterministic"
                     else f"AI model {model.get('model')}" + (" (fallback)" if model.get("fallback_used") else ""))
            out(f"      written by: {label}; request {r.get('request_id')}")
            ok = bool(r.get("request_id")) and r.get("answer") != REFUSAL and len(cites) >= 1
            return ok, {"req_id": r.get("request_id"), "citations": [c.get("doc_id") for c in cites],
                        "model": model, "refused": r.get("answer") == REFUSAL}

        def draft():
            d = state["req_s"].call("POST", "ib/act/draft", {"req_id": self.report.req_id, "kind": sc["draft_kind"]})
            out(f"      {d.get('label')} ({sc['draft_purpose']}; sent: {d.get('sent')}):")
            out(_wrap(d.get("text", ""), indent="        | "))
            m = d.get("model") or {}
            out(f"      built by: {m.get('provider')}/{m.get('model')}; cites "
                f"{', '.join(c.get('tag', '?') for c in d.get('citations') or [])}")
            return (d.get("sent") is False and bool(d.get("body"))), {
                "action_id": d.get("action_id"), "sent": d.get("sent"), "model": m,
                "sentences": len(d.get("body") or [])}

        def propose():
            try:
                p = state["req_s"].call("POST", "ib/act/ticket/propose", {"req_id": self.report.req_id})
            except ApiError as e:
                if e.status == 409 and sc["expect_ticket"] == "refused":
                    msg = (e.body or {}).get("message") if isinstance(e.body, dict) else e.body
                    out(f"      refused at action time, as expected: {msg}")
                    state["proposal"] = None
                    return True, {"outcome": "refused", "status": 409}
                raise
            state["proposal"] = p
            out(f"      proposed (nothing created yet): {p.get('issue_type')} in {p['project']['key']} "
                f"({p['project']['name']}); allowed projects checked live: "
                f"{', '.join(x['key'] for x in p.get('projects') or [])}")
            out(_wrap(p.get("description", ""), indent="        | "))
            # through a public edge, the ticket's opaque source links must point back at that edge
            links = re.findall(r"Source \d+: (\S+)", p.get("description", ""))
            s = state["req_s"]
            edge = getattr(s, "prefix", "") == "/api/ib"
            on_origin = all(u.startswith(f"{s.origin}/api/ib/ib/open/") for u in links) if edge else None
            if edge:
                out(f"      source links point at this deployment ({s.origin}): {'yes' if on_origin else 'NO'}")
            return (sc["expect_ticket"] == "created" and on_origin is not False), {
                "proposal_id": p.get("proposal_id"), "project": p["project"]["key"],
                "expires_at": p.get("expires_at"), "links": len(links), "links_on_origin": on_origin}

        def approve_and_execute():
            p = state.get("proposal")
            if p is None:
                out("      nothing to approve (no proposal)")
                return True, {"outcome": "skipped"}
            if not self._human_approves(p):
                c = state["req_s"].call("POST", "ib/act/ticket/cancel", {"proposal_id": p["proposal_id"]})
                out(f"      NOT approved: proposal {c.get('status')} (ledgered as action.rejected). Nothing was created.")
                state["ticket"] = None
                return c.get("status") == "cancelled", {"outcome": "rejected"}
            r = state["req_s"].call("POST", "ib/act/ticket/confirm",
                                    {"proposal_id": p["proposal_id"], "summary": sc["ticket_summary"]})
            issue = r.get("issue") or {}
            state["ticket"] = issue
            out(f"      approved by {sc['requester']} -> {r.get('status')}: {issue.get('key')} \"{r.get('summary')}\"")
            return r.get("status") == "created" and bool(issue.get("key")), {
                "outcome": r.get("status"), "issue": issue.get("key"), "project": (r.get("project") or {}).get("key")}

        def audit():
            s, me = self._sign_in(sc["auditor"])
            j = s.call("GET", f"audit/journey/{self.report.req_id}")
            out(f"      as {me.get('name')} ({me.get('sub')}): request by {j.get('sub')}, status {j.get('status')}, "
                f"policy {j.get('policy_version')}")
            for g in j.get("considered") or []:
                out(f"      gate 2 {g.get('verdict'):>9} / {g.get('decision'):5}  {g.get('doc_id')}  "
                    f"{'cited' if g.get('cited') else ''}")
            m = j.get("model") or {}
            out(f"      answer path: {m.get('provider')}/{m.get('model')}; stage ms {json.dumps(j.get('stage_ms'))}")
            kinds = [e.get("kind") for e in j.get("events") or []]
            for e in j.get("events") or []:
                out(f"      #{e.get('seq'):<5} {e.get('kind'):<20} {str(e.get('hash'))[:16]}...")
            v = s.call("GET", "audit/verify")
            out(f"      verify audit chain: {'INTACT' if v.get('ok') else 'PROBLEMS'}; {v.get('records')} records; "
                f"head {str(v.get('head'))[:16]}...; off-host head match: {v.get('external_head_match')}")
            need = ["request.accepted", "retrieval.decided", "answer.released", "action.proposed"]
            if state.get("ticket"):
                need += ["action.confirmed", "action.executed"]
            missing = [k for k in need if k not in kinds]
            if missing:
                out(f"      missing ledger records: {', '.join(missing)}")
            return (not missing and bool(v.get("ok"))), {"events": kinds, "verify_ok": v.get("ok"),
                                                          "records": v.get("records"), "head": v.get("head"),
                                                          "missing": missing}

        def contrast():
            s, me = self._sign_in(sc["contrast"])
            r = s.call("POST", "ib/ask", {"question": sc["question"]})
            refused = r.get("answer") == REFUSAL
            if sc["contrast"] == "ken.ext":
                out(f"      {me.get('name')} ({me.get('sub')}, external contractor) asks the same question:")
                out(_wrap(f"A: {r.get('answer')}"))
                out(f"      citations: {len(r.get('citations') or [])} (the constant refusal; no hint the policy exists)")
                return refused and not r.get("citations"), {"persona": me.get("sub"), "refused": refused}
            out(f"      {me.get('name')} ({me.get('sub')}) asks the same question: "
                f"{len(r.get('citations') or [])} citations, different permitted sources")
            return not refused, {"persona": me.get("sub"), "refused": refused,
                                 "citations": [c.get("doc_id") for c in r.get("citations") or []]}

        steps = [
            (f"Sign in as the requester ({sc['requester']})", sign_in_requester),
            ("Ask: permission-checked, cited answer (Gate 1 + live Gate 2 + grounding wall)", ask),
            (f"Draft the {sc['draft_purpose']} from cited sentences only (never sent)", draft),
            ("Propose a follow-up ticket (projects checked live; nothing created yet)", propose),
            ("Human approval gate, then execute once", approve_and_execute),
            (f"Audit pull as compliance ({sc['auditor']}): journey, gate verdicts, sealed records, verify chain", audit),
            (f"Contrast: {sc['contrast']} asks the same question", contrast),
        ]
        for name, fn in steps:
            st = self._step(name, fn)
            if not st.ok and len(self.report.steps) <= 2:
                out("\nStopping: the workflow cannot continue without a released answer.")
                break
        passed = sum(s.ok for s in self.report.steps)
        out(f"\nWorkflow {'PASSED' if self.report.ok else 'FAILED'}: {passed}/{len(self.report.steps)} steps")
        return self.report


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--base", help="public URL of a deployment (requests go through /api/ib/*)")
    g.add_argument("--ib", help="URL of an Internal Brain service, called directly (local runs)")
    ap.add_argument("--passcode", default=os.environ.get("IB_DEMO_PASSCODE", ""))
    ap.add_argument("--scenario", default="procurement", choices=sorted(SCENARIOS))
    ap.add_argument("--approve", action="store_true", help="approve the ticket without asking")
    ap.add_argument("--reject", action="store_true", help="decline the ticket (shows the cancel path)")
    ap.add_argument("--json", dest="json_out", help="write the step report as JSON to this file")
    ap.add_argument("--insecure", action="store_true", help="accept a self-signed certificate (local TLS test)")
    a = ap.parse_args(argv)
    base = a.base or (None if a.ib else os.environ.get("WALNUT_BASE_URL"))
    if not base and not a.ib:
        ap.error("give --base <public URL> or --ib <Brain URL> (or set WALNUT_BASE_URL)")
    url, prefix = (base, "/api/ib") if base else (a.ib, "")
    approve = True if a.approve else (False if a.reject else None)
    wf = Workflow(lambda: Session(url, prefix, insecure=a.insecure), passcode=a.passcode,
                  scenario=a.scenario, approve=approve, target=url)
    rep = wf.run()
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as fh:
            json.dump(rep.to_json(), fh, indent=2)
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())

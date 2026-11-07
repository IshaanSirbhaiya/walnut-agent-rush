"""Source scans: no vendor SDK, and no transport of any kind.

``scripts/check_vendor_imports.py`` already enforces the vendor rule repo-wide (P2 / ADR-0002).
This file repeats it for ``databridge_agent`` because the rule that matters here is wider: **the
agent has no way to reach the outside world at all**. A vendor SDK is one way in; ``smtplib``,
``httpx`` and ``slack_sdk`` are others, and none of them are covered by the repo-wide check.

An import scan is a blunt instrument, so each scan is paired with a test that plants the violation
it claims to catch. Without those, a typo in a pattern would leave a green suite asserting nothing
— the failure mode AGENTS.md's house style calls out by name.
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

import databridge_agent

PKG_ROOT = pathlib.Path(databridge_agent.__file__).resolve().parent

# The hosted-model vendor SDKs are checked by digest, through the repo-wide vendor guard, so no
# vendor is named here (scripts/check_vendor_imports.py).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "scripts"))
import check_vendor_imports  # noqa: E402
from check_vendor_imports import FORBIDDEN_DIGESTS, digest, is_forbidden  # noqa: E402

# The vendor rule (P2 / ADR-0002): every model call goes through packages/harness, which is the
# only package allowed to import one of these. The vendor SDKs themselves are matched by digest
# (`is_forbidden`); this tuple holds the names that are not on the repo-wide list.
VENDOR_MODULES = ("google",)

# Anything that can open a connection, send mail, or speak a third-party API. The agent has no
# business importing any of them, and the day one appears is the day the design changed.
TRANSPORT_MODULES = (
    "smtplib", "imaplib", "poplib", "socket", "ssl", "http", "httpx", "requests", "urllib",
    "aiohttp", "websockets", "ftplib", "telnetlib", "slack_sdk", "slack_bolt", "slackclient",
    "googleapiclient", "google_auth_oauthlib", "boto3", "botocore", "paramiko", "smtpd",
    "subprocess", "webbrowser",
)


def _import_re(modules: tuple[str, ...]) -> re.Pattern:
    return re.compile(r"^[ \t]*(?:import|from)[ \t]+(" + "|".join(modules) + r")\b", re.M)


def _sources() -> list[pathlib.Path]:
    return [p for p in sorted(PKG_ROOT.rglob("*.py")) if "__pycache__" not in p.parts]


def _imported_module(line: str) -> str | None:
    found = re.match(r"^[ \t]*(?:import|from)[ \t]+([A-Za-z_][\w.]*)", line)
    return found.group(1) if found else None


def _violations(modules: tuple[str, ...], vendors: bool = False) -> list[str]:
    pattern = _import_re(modules)
    hits: list[str] = []
    for path in _sources():
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            module = _imported_module(line)
            if pattern.match(line) or (vendors and module and is_forbidden(module)):
                hits.append(f"{path.relative_to(PKG_ROOT)}:{line_no}: {line.strip()}")
    return hits


def test_the_package_has_sources_to_scan():
    """Guards every scan below: an empty file list would make all of them vacuously green.

    The list is named module by module rather than counted, so a new module is a deliberate
    addition to the scanned set rather than something that quietly joins it or quietly does not.
    """
    names = {p.name for p in _sources()}
    assert {"adapters.py", "agent.py", "frame.py", "guardrails.py", "policy.py", "render.py",
            "results.py", "sealed.py", "tools.py"} <= names


def test_the_same_rule_is_applied_to_adapters_that_arrive_from_outside():
    """`sealed.scan_source` is this scan pointed at the composition root's code (R-07).

    Two lists that are meant to encode one rule will drift, and the one that drifts is the one
    nobody reads. This asserts they still agree on the module names that matter.
    """
    from databridge_agent.sealed import _FORBIDDEN_MODULES
    for name in ("smtplib", "socket", "httpx", "requests", "subprocess", "slack_sdk"):
        assert name in _FORBIDDEN_MODULES, f"the adapter scan would not catch {name!r}"
    from databridge_agent.sealed import _VENDOR_DIGESTS
    assert FORBIDDEN_DIGESTS <= _VENDOR_DIGESTS, (
        "the adapter scan has fallen behind scripts/check_vendor_imports.py: "
        f"{sorted(FORBIDDEN_DIGESTS - _VENDOR_DIGESTS)}")


def test_no_vendor_sdk_is_imported():
    assert not _violations(VENDOR_MODULES, vendors=True), (
        "every model call goes through packages/harness (AGENTS.md §Working rules): "
        + "; ".join(_violations(VENDOR_MODULES, vendors=True)))


def test_no_transport_of_any_kind_is_imported():
    assert not _violations(TRANSPORT_MODULES), (
        "the agent has no send capability and no way to acquire one: "
        + "; ".join(_violations(TRANSPORT_MODULES)))


@pytest.mark.parametrize("line,modules", [
    ("import google.generativeai", VENDOR_MODULES),
    ("import smtplib", TRANSPORT_MODULES),
    ("from slack_sdk import WebClient", TRANSPORT_MODULES),
    ("    import httpx", TRANSPORT_MODULES),
])
def test_the_scanner_catches_a_planted_import(line, modules):
    """The scans above are only worth their runtime if they fail on what they claim to catch."""
    assert _import_re(modules).match(line), f"scanner missed {line!r}"


#: A first-party name planted on the digest list: the vendor scans are proved on it, so the test
#: needs no vendor's name to show that a digest match is caught.
PLANTED_VENDOR = "databridge_planted_vendor"


@pytest.mark.parametrize("line", [
    f"import {PLANTED_VENDOR}",
    f"from {PLANTED_VENDOR}.client import Client",
    f"    import {PLANTED_VENDOR} as sdk",
])
def test_the_vendor_scans_catch_a_planted_digest(monkeypatch, line):
    """Both vendor scans, this file's and `sealed.scan_source`, fire on a digest-listed import."""
    from databridge_agent import sealed
    from databridge_agent.sealed import TransportInAdapter

    module = _imported_module(line)
    assert module and not is_forbidden(module), "the planted name must start off the list"
    monkeypatch.setattr(check_vendor_imports, "FORBIDDEN_DIGESTS",
                        FORBIDDEN_DIGESTS | {digest(PLANTED_VENDOR)})
    assert is_forbidden(module), f"the vendor scan missed {line!r}"
    monkeypatch.setattr(sealed, "_VENDOR_DIGESTS",
                        sealed._VENDOR_DIGESTS | {digest(PLANTED_VENDOR)})
    with pytest.raises(TransportInAdapter):
        sealed.scan_source(line + "\n", "planted")


def test_the_scanner_ignores_a_mention_in_prose():
    """Over-broadness would push people to stop writing about the rule in the file that keeps it."""
    prose = '"""We never import a vendor SDK here."""\n# import smtplib would be a bug\n'
    assert not _import_re(VENDOR_MODULES).search(prose)
    assert not _import_re(TRANSPORT_MODULES).search(prose)


def test_the_only_model_entry_point_is_the_harness():
    """One call site, one routing table. A second way to reach a model is a second place the
    airgapped refusal and the token budget do not apply."""
    agent_src = (PKG_ROOT / "agent.py").read_text(encoding="utf-8")
    assert "from databridge_harness import Harness" in agent_src
    calls = re.findall(r"self\._harness\.(\w+)\(", agent_src)
    assert set(calls) == {"complete_structured"}, calls


def test_the_task_class_is_a_name_not_a_model_id():
    """Routing is config, so swapping the agent to a cheaper model — or to another provider
    altogether — is a config diff."""
    assert databridge_agent.AGENT_TASK_CLASS == "agent_reasoning"
    assert "/" not in databridge_agent.AGENT_TASK_CLASS

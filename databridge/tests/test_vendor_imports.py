"""The vendor-import CI rule (P2 / ADR-0001, ADR-0002): no AI-vendor SDK is imported anywhere.

There are no exceptions any more: not the harness (its one backend is plain HTTP), not the
Internal Brain. The rule must FAIL loudly the moment a vendor import appears in any file.

No vendor is named here either. The planted-violation tests add the digest of a first-party
placeholder module to the denylist for the length of one test, so they prove the scanner fires
without this file spelling out a single denied name.
"""
from __future__ import annotations

import pytest

import check_vendor_imports
from check_vendor_imports import (FORBIDDEN_DIGESTS, REPO_ROOT, digest, find_violations,
                                  is_forbidden, scan_text)

#: a first-party placeholder, denied only inside the tests below
PLANTED = "databridge_planted_vendor"
PLANTED_TOO = "databridge_planted_router"


@pytest.fixture
def planted(monkeypatch):
    monkeypatch.setattr(check_vendor_imports, "FORBIDDEN_DIGESTS",
                        FORBIDDEN_DIGESTS | {digest(PLANTED), digest(PLANTED_TOO)})


def test_repo_has_no_vendor_imports():
    assert find_violations(REPO_ROOT) == []


def test_rule_catches_a_violation(planted):
    assert scan_text(f"import {PLANTED}\n")
    assert scan_text(f"from {PLANTED_TOO} import Client\n")
    assert scan_text(f"import {PLANTED}.client\n")
    assert scan_text(f"    import {PLANTED}  # lazy\n")
    assert scan_text(f"import json, {PLANTED}\n")
    assert is_forbidden(PLANTED) and is_forbidden(f"{PLANTED_TOO}.sub.module")


def test_rule_does_not_false_positive(planted):
    assert scan_text(f"import {PLANTED}ish\n") == []          # prefix, not the module
    assert scan_text(f"# import {PLANTED} in a comment\n") == []
    assert scan_text(f'msg = "import {PLANTED}"\n') == []     # string literal, not an import
    assert scan_text("import httpx\nfrom pydantic import BaseModel\n") == []


def test_the_planted_name_is_not_denied_outside_the_fixture():
    """The fixture, not the shipped denylist, is what denies the placeholder."""
    assert not is_forbidden(PLANTED)


def test_nothing_is_exempt_not_even_the_harness(tmp_path, planted):
    harness = tmp_path / "packages" / "harness"
    harness.mkdir(parents=True)
    (harness / "client.py").write_text(f"import {PLANTED}\n", encoding="utf-8")
    ib = tmp_path / "apps" / "internal_brain" / "databridge_ib"
    ib.mkdir(parents=True)
    (ib / "llm.py").write_text(f"def f():\n    import {PLANTED_TOO}\n", encoding="utf-8")
    flagged = {v[0] for v in find_violations(tmp_path)}
    assert flagged == {"packages/harness/client.py", "apps/internal_brain/databridge_ib/llm.py"}


def test_the_denylist_is_digests():
    assert len(FORBIDDEN_DIGESTS) >= 30
    assert all(len(d) == 16 and int(d, 16) >= 0 for d in FORBIDDEN_DIGESTS)
    assert not any(is_forbidden(m) for m in ("httpx", "pydantic", "json", "databridge_harness"))

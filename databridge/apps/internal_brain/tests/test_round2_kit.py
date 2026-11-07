"""Round-2 review fixes in the live-kit scripts (imported by path; nothing here touches a network,
a server or a real output folder).

- docs/live_kit/check_absent.py --sim reads ``documents_containing`` (review track B #7);
- docs/live_kit/templates/fill_template.py: --name is a plain file name inside out/, no
  overwrite without --force, CSV formula cells neutralised (review track B #13, review track A 2b #2).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
DB = REPO / "databridge"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------------------------------------
# check_absent --sim
# ------------------------------------------------------------------------------------------------
def test_check_absent_sim_reads_documents_containing():
    ca = _load(REPO / "docs" / "live_kit" / "check_absent.py", "check_absent_under_test")
    assert ca.sim_absent({"documents_containing": 0, "index_size": 412})[0] is True
    assert ca.sim_absent({"documents_containing": 2, "index_size": 412})[0] is False
    # the old field name, a missing count, or a non-integer count all fail closed
    for bad in ({"count": 0}, {}, {"documents_containing": None}, {"documents_containing": "0"},
                {"documents_containing": False}, None):
        assert ca.sim_absent(bad)[0] is False, bad


def test_check_absent_matches_the_sim_endpoint_field():
    src = (DB / "apps" / "internal_brain" / "databridge_ib" / "sim.py").read_text(encoding="utf-8")
    assert '"documents_containing": hits' in src


# ------------------------------------------------------------------------------------------------
# fill_template
# ------------------------------------------------------------------------------------------------
@pytest.fixture()
def ft():
    return _load(REPO / "docs" / "live_kit" / "templates" / "fill_template.py",
                 "fill_template_under_test")


@pytest.mark.parametrize("name", ["../template_note.md", "..\\x.md", "/etc/passwd", "a/b.md",
                                  "C:\\x.md", "C:x.md", "..", ".", "", " x.md", "x..md"])
def test_fill_template_rejects_anything_but_a_plain_name(ft, tmp_path, name):
    with pytest.raises(ValueError):
        ft.safe_name(name, tmp_path / "out")


def test_fill_template_plain_name_stays_inside_out(ft, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    assert ft.safe_name("Audit calendar.md", out) == (out / "Audit calendar.md").resolve()


@pytest.mark.parametrize("cell,want", [
    ("=HYPERLINK(\"http://x\")", "'=HYPERLINK(\"http://x\")"),
    ("+1", "'+1"), ("-1", "'-1"), ("@SUM(A1)", "'@SUM(A1)"), ("\tx", "'\tx"), ("\rx", "'\rx"),
    ("  =1", "'  =1"), ("a, b", "a; b"), ("Vendor renewal", "Vendor renewal"),
])
def test_fill_template_csv_cells_are_never_formulas(ft, cell, want):
    assert ft.csv_cell(cell) == want


def test_fill_template_cli_refuses_traversal_and_overwrite(ft, tmp_path, monkeypatch, capsys):
    # run the CLI against a COPY of the templates so the real out/ folder is never written
    for f in ft.KINDS.values():
        (tmp_path / f).write_text((ft.HERE / f).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(ft, "HERE", tmp_path)

    def run(*args):
        monkeypatch.setattr(sys, "argv", ["fill_template.py", *args])
        return ft.main()

    assert run("md", "The audit committee meets on 9 Dec 2026.", "--name", "../template_note.md") == 2
    assert "{{" in (tmp_path / "template_note.md").read_text(encoding="utf-8")   # untouched
    assert run("csv", "=cmd|' /C calc'!A0", "--name", "t.csv") == 0
    body = (tmp_path / "out" / "t.csv").read_text(encoding="utf-8")
    assert "'=cmd|' /C calc'!A0" in body and ",=cmd" not in body
    assert run("csv", "Second run.", "--name", "t.csv") == 1                      # no overwrite
    assert "Second run." not in (tmp_path / "out" / "t.csv").read_text(encoding="utf-8")
    assert run("csv", "Second run.", "--name", "t.csv", "--force") == 0
    assert "Second run." in (tmp_path / "out" / "t.csv").read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------------
# Round 4 (web/kit review track B #9, #12)

@pytest.mark.parametrize("cell", [
    '"=HYPERLINK(""http://x"")"', '"+1', ' "-1', '"@SUM(A1)', '" =1',
    "＝1+1", "＋1", "－1", "＠SUM(A1)", " =1", "　＝1", ' "=1',
    "\t=1", "\r=1", "\tx", "\rx",
])
def test_fill_template_csv_guard_matches_the_server_guard(ft, cell):
    assert ft.csv_cell(cell).startswith("'"), cell


@pytest.mark.parametrize("cell", ['"quoted text"', "Vendor renewal", "Owner: Hana", "1+1"])
def test_fill_template_csv_guard_leaves_plain_text(ft, cell):
    assert not ft.csv_cell(cell).startswith("'"), cell


# check_absent --all --sim: /sim/check-absent allows 10 calls a minute (STAGE_QA_30OCT #6)

class _FakeClient:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def post(self, path, body):
        self.calls += 1
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _http_429(retry_after):
    import urllib.error
    from email.message import Message
    h = Message()
    if retry_after is not None:
        h["Retry-After"] = retry_after
    return urllib.error.HTTPError("http://127.0.0.1:8100/sim/check-absent", 429, "Too Many Requests", h, None)


@pytest.mark.parametrize("retry_after,want", [("7", 7.0), (None, 60.0), ("999", 65.0), ("soon", 60.0)])
def test_check_absent_sim_waits_and_retries_once_on_429(monkeypatch, capsys, retry_after, want):
    ca = _load(REPO / "docs" / "live_kit" / "check_absent.py", "check_absent_retry_under_test")
    slept = []
    monkeypatch.setattr(ca, "_sleep", slept.append)
    c = _FakeClient([_http_429(retry_after), {"documents_containing": 0, "index_size": 9}])
    assert ca.sim_check(c, "phrase")["documents_containing"] == 0
    assert c.calls == 2 and slept == [want]
    assert f"waiting {want:.0f} s" in capsys.readouterr().out


def test_check_absent_sim_retries_only_once(monkeypatch):
    import urllib.error
    ca = _load(REPO / "docs" / "live_kit" / "check_absent.py", "check_absent_retry1_under_test")
    monkeypatch.setattr(ca, "_sleep", lambda s: None)
    c = _FakeClient([_http_429("1"), _http_429("1")])
    with pytest.raises(urllib.error.HTTPError):
        ca.sim_check(c, "phrase")
    assert c.calls == 2

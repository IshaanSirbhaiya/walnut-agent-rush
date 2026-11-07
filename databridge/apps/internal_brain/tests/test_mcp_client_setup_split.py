"""Round 2b finding 2: ``mcp_client_setup.py`` never writes the compliance connector into the same
MCP client connector list as the employee connectors (tests the merge rule; starts no client)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "mcp_client_setup.py"


def _load():
    spec = importlib.util.spec_from_file_location("mcp_client_setup_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ALL = {"ib-as-jdoe": {"x": 1}, "ib-as-ken": {"x": 2}, "ib-compliance": {"x": 3}}


def test_employee_mode_drops_compliance_even_a_stale_entry():
    ws = _load()
    current = {"mcpServers": {"other": {"keep": True}, "ib-compliance": {"stale": True}}}
    out = ws.merge_user_servers(current, ALL, compliance=False)
    assert set(out) == {"other", "ib-as-jdoe", "ib-as-ken"}
    assert out["other"] == {"keep": True}


def test_compliance_mode_writes_only_compliance_and_removes_employees():
    ws = _load()
    current = {"mcpServers": {"other": {"keep": True}, "ib-as-jdoe": {"old": 1}}}
    out = ws.merge_user_servers(current, ALL, compliance=True)
    assert set(out) == {"other", "ib-compliance"}


def test_flags_are_mutually_exclusive(capsys):
    ws = _load()
    try:
        ws.main(["--out", "x", "--client-config", "a.json", "--compliance-client-config", "b.json"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover
        raise AssertionError("combining the two flags must be refused")


def test_out_is_required(capsys):
    ws = _load()
    try:
        ws.main([])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover
        raise AssertionError("--out has no default; it must be given")


def test_client_config_goes_to_the_given_path_with_employees_only(tmp_path, monkeypatch):
    import json
    ws = _load()
    monkeypatch.setattr(ws, "mint_for", lambda persona, hours: "fake-token")
    cfg = tmp_path / "client" / "mcp.json"
    cfg.parent.mkdir()
    cfg.write_text(json.dumps({"mcpServers": {"other": {"keep": True}}}), encoding="utf-8")
    assert ws.main(["--out", str(tmp_path / "out"), "--client-config", str(cfg)]) == 0
    servers = json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]
    assert set(servers) == {"other", "ib-as-jdoe", "ib-as-ken"}
    for folder, *_ in ws.WORKSPACES:
        assert (tmp_path / "out" / folder / "mcp.json").is_file()

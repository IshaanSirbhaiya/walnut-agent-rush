"""HC1 (2026-10-01), SWEEP hardcode audit #9: the CLI's harness runs models READ from
`config/models.yaml`, per task class — never a model id written in `llm.py`."""
from __future__ import annotations

import ast
import copy
import re
from pathlib import Path

import pytest

from databridge_mcp_ingest import llm

_MODEL_ID = re.compile(r"^[a-z_]+/[A-Za-z0-9][A-Za-z0-9.:_-]*$")


def _config():
    from databridge_core.config import load_model_config

    return copy.deepcopy(load_model_config())


def _all_config_models(cfg) -> set[str]:
    return {v["model"] for v in (cfg.get("aliases") or {}).values()
            if isinstance(v, dict) and v.get("model")}


ENDPOINT = "http://127.0.0.1:9/v1"          # never called: detect() only reads the env


@pytest.fixture
def no_keys(monkeypatch):
    monkeypatch.delenv("DATABRIDGE_FORCE_GOLD", raising=False)
    monkeypatch.delenv(llm.MODEL_URL_ENV, raising=False)
    return monkeypatch


def test_llm_py_names_no_model_id_in_code():
    tree = ast.parse(Path(llm.__file__).read_text(encoding="utf-8"))
    strings = [n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert [s for s in strings if _MODEL_ID.match(s)] == []
    # Non-vacuous: the same pattern does recognise the ids the config holds.
    assert any(_MODEL_ID.match(m) for m in _all_config_models(_config()))


def test_with_the_endpoint_set_every_effective_model_comes_from_the_config(no_keys):
    no_keys.setenv(llm.MODEL_URL_ENV, ENDPOINT)
    cfg = _config()
    detected = llm.detect(cfg)
    assert set(detected["routing"]) == set(llm.TASK_CLASSES)
    assert detected["model"] is not None
    for route in detected["routing"].values():
        assert route["effective"] in _all_config_models(cfg)


def test_the_configured_model_wins_when_its_endpoint_is_set(no_keys):
    cfg = _config()
    alias = cfg["routing"][llm.TASK_CLASSES[0]]
    configured = cfg["aliases"][alias]["model"]
    no_keys.setenv(llm.MODEL_URL_ENV, ENDPOINT)
    detected = llm.detect(cfg)
    assert detected["routing"][llm.TASK_CLASSES[0]]["effective"] == configured
    assert detected["routing"][llm.TASK_CLASSES[0]]["fallback"] is False


def test_a_synthetic_table_falls_back_only_to_a_model_it_names(no_keys):
    # "offline/" is a provider the model adapter never reaches; "chat/" is one it does
    cfg = {"routing": {t: "gen" for t in llm.TASK_CLASSES},
           "aliases": {"gen": {"model": "offline/synthetic-gen-1"},
                       llm.FALLBACK_ALIAS: {"model": "chat/synthetic-fallback-1"}}}
    no_keys.setenv(llm.MODEL_URL_ENV, ENDPOINT)
    detected = llm.detect(cfg)
    assert detected["model"] == "chat/synthetic-fallback-1"
    assert all(r["fallback"] for r in detected["routing"].values())


def test_nothing_reachable_is_reported_not_papered_over(no_keys):
    cfg = {"routing": {t: "gen" for t in llm.TASK_CLASSES},
           "aliases": {"gen": {"model": "chat/synthetic-gen-1"}}}
    detected = llm.detect(cfg)
    assert detected["model"] is None and detected["backend"] == "none"
    assert llm.MODEL_URL_ENV in detected["reason"] or any(
        llm.MODEL_URL_ENV in r["reason"] for r in detected["routing"].values())

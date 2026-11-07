"""Put the IB package and the Walnut libraries it imports on sys.path (no editable install needed).

Kept local to this test tree so the root ``pyproject.toml`` pythonpath (and the gateway's
``serve.py`` mirror of it) are not touched (plan C0; review track B H7).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]          # databridge/
for rel in ("apps/internal_brain", "apps/mock_platforms", "packages/core", "packages/harness",
            "packages/adapter", "packages/retrieval"):
    p = str(_ROOT / rel)
    if p not in sys.path:
        sys.path.insert(0, p)


import pytest  # noqa: E402

#: every setting of the one model adapter and its guard
MODEL_ENV = ("IB_MODEL_URL", "IB_MODEL_NAME", "IB_MODEL_KEY", "IB_MODEL_FALLBACKS", "IB_MODEL_LIVE",
             "IB_MODEL_CAP_USD", "IB_MODEL_DAILY_CAP_USD", "IB_MODEL_RPM", "IB_MODEL_USER_RPM",
             "IB_MODEL_PRICE_IN_USD", "IB_MODEL_PRICE_OUT_USD", "IB_MODEL_ANSWER_TIMEOUT_S",
             "IB_MODEL_FIXED_SAMPLING", "IB_FORCE_OFFLINE")


@pytest.fixture(autouse=True)
def _no_model_from_the_environment(monkeypatch, tmp_path_factory):
    """No test builds an app that reaches a model from the developer's shell: the model adapter's
    endpoint, name, key, fallbacks, prices and caps are cleared for every test (a test that wants
    one sets them). The spend ledger goes to a NEW per-test directory, so no test writes into the
    repo's var/ and no two tests share a ledger."""
    for k in MODEL_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("IB_MODEL_GUARD_DIR", str(tmp_path_factory.mktemp("model_guard") / "guard"))

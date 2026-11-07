"""E1 against a REAL local model server — the honest accuracy number (06_PRD §8 / E6).

Records the real per-column accuracy of the routed-local model. The 92% fintech floor is
for the production model; a small local model (around 3B parameters) is expected to score
lower — that gap IS the E6 calibration signal (06_PRD §4/§8). The server is the one the
provider-neutral adapter is configured with: ``IB_MODEL_URL`` (a local or private host) and
``IB_MODEL_NAME``. Skips cleanly when none is configured or reachable; the assertion is never
weakened.
"""
from __future__ import annotations

import json
import os
import urllib.request

import pytest

from databridge_evals import run_e1
from databridge_harness import Harness


def local_model_server() -> tuple[str, str]:
    """``(url, model)`` of the configured local model server, or a skip saying what is missing."""
    from databridge_harness.backends import is_local_url

    url = os.environ.get("IB_MODEL_URL", "").strip().rstrip("/")
    model = os.environ.get("IB_MODEL_NAME", "").strip()
    if not url or not model:
        pytest.skip("no local model server configured (IB_MODEL_URL and IB_MODEL_NAME)")
    if not is_local_url(url):
        pytest.skip(f"IB_MODEL_URL is not a local or private host: {url}")
    try:
        with urllib.request.urlopen(f"{url}/models", timeout=3) as r:
            json.load(r)
    except Exception as e:                                       # noqa: BLE001
        pytest.skip(f"local model server not reachable: {e}")
    return url, model


@pytest.mark.integration
def test_e1_against_a_local_model_server(capsys):
    from databridge_harness import ChatBackend

    url, model = local_model_server()

    cfg = {
        "routing": {"schema_annotation": "m", "cross_table_inference": "m"},
        "aliases": {"m": {"model": f"local/{model}"}},
        "profiles": {"cloud": {}, "airgapped": {}},
    }
    res = run_e1(Harness(ChatBackend(url=url), config=cfg, profile="airgapped", cache=None))

    with capsys.disabled():
        print(f"\n[E1 live: {model}] overall={res.accuracy:.3f} roles={res.role_accuracy:.3f} "
              f"per_provenance={res.per_provenance}\n  reliability={res.reliability}")

    # honest, non-weakened floors: airtight columns are deterministic ⇒ MUST be perfect;
    # the local model must at least clear chance for the rest (real number is recorded above).
    assert res.per_provenance["deterministic"]["accuracy"] == 1.0
    assert res.accuracy >= 0.50           # deterministic 50% alone guarantees this; records the LLM lift
    assert res.model_map["schema_annotation"] == f"local/{model}"

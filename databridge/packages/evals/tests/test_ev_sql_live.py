"""EV-SQL against a REAL local model server — the honest execution-accuracy number.

Gate is ≥70% for the production model; a 3B local model is expected lower (the §29 risk:
"NL→SQL in S1 underdelivers" — published number, never a silently-adjusted gate). The server is
the one ``IB_MODEL_URL`` / ``IB_MODEL_NAME`` configure; skips when none is configured or reachable.
"""
from __future__ import annotations

import json
import os
import urllib.request

import pytest

from databridge_convert.demos.d9 import fintech_sqlite_engine
from databridge_evals import run_ev_sql
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
def test_ev_sql_against_a_local_model_server(capsys):
    from databridge_harness import ChatBackend

    url, model = local_model_server()

    cfg = {
        "routing": {"sql_generation": "m", "sql_revision": "m"},
        "aliases": {"m": {"model": f"local/{model}"}},
        "profiles": {"cloud": {}, "airgapped": {}},
    }
    res = run_ev_sql(Harness(ChatBackend(url=url), config=cfg, profile="airgapped", cache=None),
                     fintech_sqlite_engine())

    with capsys.disabled():
        print(f"\n[EV-SQL live: {model}] accuracy={res.accuracy:.3f} "
              f"(gate {res.passed and '>=' or '<'} 0.70), correct={res.correct}/{res.total}")
        for q in res.per_question:
            mark = "OK " if q["match"] else ("REF" if q["refusal"] else "xx ")
            print(f"  [{mark}] {q['question']}")

    # Derived (HC2, SWEEP #24-34): every gold pair was scored — none skipped, none invented.
    from databridge_evals.e_sql import PAIRS
    assert len(PAIRS) >= 1 and len({q for q, _ in PAIRS}) == len(PAIRS)   # non-vacuous, distinct
    assert res.total == len(PAIRS) and len(res.per_question) == len(PAIRS)

"""Integration: the SAME calling code yields valid structured output from a LOCAL model.

This is the 07_PRD §2 / Task 2 Done-when for the local backend (P2 proof). It runs for real only
when ``IB_MODEL_URL`` points at a local chat-completions endpoint and ``IB_MODEL_NAME`` names a
model it serves, and SKIPS otherwise — the assertion is never weakened.
"""
from __future__ import annotations

import os
from typing import Literal

import pytest
from pydantic import BaseModel

from databridge_harness import ChatBackend, Harness
from databridge_harness.backends import is_local_url


class Sentiment(BaseModel):
    sentiment: Literal["positive", "negative", "neutral"]


@pytest.mark.integration
def test_local_model_produces_valid_structured_output():
    url, name = os.environ.get("IB_MODEL_URL", ""), os.environ.get("IB_MODEL_NAME", "")
    if not (url and name and is_local_url(url)):
        pytest.skip("no local model endpoint configured (IB_MODEL_URL + IB_MODEL_NAME)")
    cfg = {
        "routing": {"smoke": "local"},
        "aliases": {"local": {"model": f"local/{name}"}},
        "profiles": {"cloud": {}, "airgapped": {}},
    }
    # airgapped profile + a local model: no refusal, no egress.
    h = Harness(ChatBackend(), config=cfg, profile="airgapped", cache=None)
    res = h.complete_structured(
        "smoke",
        [{"role": "user",
          "content": "Classify the sentiment of this review: 'I absolutely love this "
                     "product, it works great!'. Reply ONLY with JSON of the form "
                     '{"sentiment": "positive"|"negative"|"neutral"}.'}],
        Sentiment,
        strict=True,
        max_retries=2,
    )
    assert res.parsed.sentiment in ("positive", "negative", "neutral")
    assert res.event.model_used == f"local/{name}"
    assert res.event.tokens and res.event.tokens > 0

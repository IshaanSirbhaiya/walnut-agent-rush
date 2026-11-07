"""Shared fixtures for harness tests.

CFG is an injected routing table (so tests don't depend on the repo's models.yaml). It
deliberately includes a ``leak`` alias that is NOT remapped under the airgapped profile,
so a task routed to it resolves to a HOSTED model under airgapped — the case the P1
refusal must catch.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel


class Out(BaseModel):
    label: str
    score: int


CFG = {
    "routing": {
        "unknown_task": "a",   # unknown kind → conservative: no json_mode, no seed → L1/L2
        "chat_task": "o",      # chat       → json_mode, seed (no guided) → L1/L2
        "local_task": "ol",    # local      → json_mode, not hosted
        "guided_task": "v",    # guided server → guided_json → L3
        "leak_task": "leak",   # hosted, intentionally unremapped under airgapped
    },
    "aliases": {
        "a": {"model": "mystery/model-x"},
        "o": {"model": "chat/model-x"},
        "ol": {"model": "local/model-l"},
        "v": {"model": "local_server/model-v"},
        "leak": {"model": "chat/model-leak"},
    },
    "profiles": {
        "cloud": {},
        "airgapped": {"a": "ol", "o": "ol", "v": {"model": "local/model-l2"}},
    },
}


@pytest.fixture
def out() -> type[BaseModel]:
    return Out


@pytest.fixture
def cfg() -> dict:
    return CFG


@pytest.fixture
def valid_str() -> str:
    return '{"label": "x", "score": 1}'


@pytest.fixture
def invalid_str() -> str:
    return '{"label": "x"}'          # missing required `score` → drives an L2 retry

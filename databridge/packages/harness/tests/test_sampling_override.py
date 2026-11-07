"""R-019 (review batch 2, High): a model that rejects a sampling override must not be sent one —
temperature is a supported parameter NAME whose allowed VALUE is restricted, so dropping unknown
parameter names would not help. ``IB_MODEL_FIXED_SAMPLING`` names such models (patterns), and
nothing is dropped for anyone else. The HTTP client is a recorder: no network, no key."""
from __future__ import annotations

import types

import pytest

from databridge_harness.backends import (REJECTED_SAMPLING_CONTROLS, ChatBackend,
                                         accepts_sampling_override)

URL = "https://models.example.com/v1"


@pytest.fixture
def recorder():
    calls: list[dict] = []
    reply = {"choices": [{"message": {"content": "ok"}}]}

    class Client:
        def post(self, url, json=None, headers=None, timeout=None):
            calls.append(json)
            return types.SimpleNamespace(status_code=200, json=lambda: reply)
    return calls, ChatBackend(URL, client=Client())


def test_models_that_reject_a_sampling_override_are_sent_none(recorder, monkeypatch):
    monkeypatch.setenv("IB_MODEL_FIXED_SAMPLING", "big-model-*, other-fixed")
    calls, backend = recorder
    rejecting = ["chat/big-model-5", "chat/other-fixed", "big-model-x"]
    for model in rejecting:
        backend.generate(model=model, messages=[{"role": "user", "content": "hi"}])
    assert len(calls) == len(rejecting)
    assert all("temperature" not in c and "drop_params" not in c for c in calls)


def test_other_models_keep_temperature_zero_and_nothing_is_dropped(recorder, monkeypatch):
    monkeypatch.setenv("IB_MODEL_FIXED_SAMPLING", "big-model-*")
    calls, backend = recorder
    accepting = ["chat/small-model", "chat/any", "chat/model-big"]
    for model in accepting:
        backend.generate(model=model, messages=[{"role": "user", "content": "hi"}])
    assert [c["temperature"] for c in calls] == [0] * len(accepting)
    assert all("drop_params" not in c for c in calls)


def test_the_default_is_that_every_model_accepts_an_override(monkeypatch):
    monkeypatch.delenv("IB_MODEL_FIXED_SAMPLING", raising=False)
    assert accepts_sampling_override("chat/anything")


# --- R-019 round 3 (review, High #7): a caller kwarg must not re-add the override -------------------
def test_a_caller_supplied_sampling_override_never_reaches_a_rejecting_model(recorder, monkeypatch):
    monkeypatch.setenv("IB_MODEL_FIXED_SAMPLING", "big-model-*")
    calls, backend = recorder
    sampling = {name: 0 for name in REJECTED_SAMPLING_CONTROLS}
    assert "temperature" in sampling, "the explicit temperature case is exercised"
    backend.generate(model="chat/big-model-5", messages=[{"role": "user", "content": "hi"}],
                     max_tokens=16, **sampling)
    (call,) = calls
    assert not set(call) & set(REJECTED_SAMPLING_CONTROLS)
    assert call["max_tokens"] == 16, "only the rejected controls are removed; the rest pass"
    # a model that accepts an override still gets determinism, not the caller's value
    backend.generate(model="chat/small-model", messages=[{"role": "user", "content": "hi"}],
                     temperature=0.9)
    assert calls[-1]["temperature"] == 0

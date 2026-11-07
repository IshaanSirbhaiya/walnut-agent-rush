"""Which model chain the Internal Brain builds from the environment (no network call is made).

One provider-neutral adapter: ``IB_MODEL_URL`` + ``IB_MODEL_NAME`` (+ ``IB_MODEL_KEY``,
``IB_MODEL_FALLBACKS``). Nothing configured is the deterministic, quoted path; there is no default
URL and no default model name."""
from __future__ import annotations

from databridge_ib import llm

from model_fakes import FakeModel, configure


def test_nothing_configured_means_the_deterministic_path():
    assert llm.ModelChain.from_env() is None
    assert llm.configured_models() == [] and llm.model_configured() is False


def test_the_configured_model_and_its_fallbacks_in_order(monkeypatch):
    configure(monkeypatch, "main-model", ["second-model", "main-model", "third-model"])
    chain = llm.ModelChain.from_env()
    assert chain is not None
    assert list(chain.models) == ["main-model", "second-model", "third-model"]   # no repeats
    assert chain.provider == "model" == llm.provider_label()


def test_force_offline_wins_over_any_configuration(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setenv("IB_FORCE_OFFLINE", "1")
    assert llm.ModelChain.from_env() is None
    assert llm.model_configured() is True and llm.model_enabled() is False


def test_a_url_without_a_name_or_a_name_without_a_url_is_not_enough(monkeypatch):
    monkeypatch.setenv("IB_MODEL_URL", "https://models.example.test/v1")
    assert llm.ModelChain.from_env() is None
    monkeypatch.delenv("IB_MODEL_URL")
    monkeypatch.setenv("IB_MODEL_NAME", "main-model")
    assert llm.ModelChain.from_env() is None
    monkeypatch.setenv("IB_MODEL_KEY", "k-test-not-real")          # a key alone changes nothing
    assert llm.ModelChain.from_env() is None


def test_the_chain_sends_the_configured_name_through_the_neutral_adapter(monkeypatch):
    configure(monkeypatch, "main-model")
    fake = FakeModel(lambda kind, text: "")
    chain = llm.ModelChain.from_env(inner=fake)
    chain.complete([{"role": "user", "content": "hi"}])
    (call,) = fake.calls
    assert call["model"] == "chat/main-model"
    assert call["max_tokens"] == llm.ANSWER_MAX_TOKENS
    assert call["timeout"] == llm.answer_timeout_s() == llm.ANSWER_TIMEOUT_DEFAULT_S


def test_the_answer_timeout_is_bounded(monkeypatch):
    for raw, want in (("30", 30.0), ("0", 1.0), ("999", 120.0), ("nan", 12.0), ("x", 12.0)):
        monkeypatch.setenv("IB_MODEL_ANSWER_TIMEOUT_S", raw)
        assert llm.answer_timeout_s() == want, raw

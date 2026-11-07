"""A fake model endpoint for the IB tests: an ``inner`` / ``backend`` for ``llm.GuardedBackend``,
``llm.ModelChain.from_env`` and ``views.composer.ModelComposer``. It records every call and never
touches the network."""
from __future__ import annotations

from databridge_harness import RawCompletion


def kind_of(messages: list[dict]) -> str:
    system = " ".join(str(m.get("content", "")) for m in messages if m.get("role") == "system")
    if "decide how an answer is shown" in system:
        return "decide"
    if "standalone search question" in system:
        return "rewrite"
    if "design one-page views" in system:
        return "compose"
    return "answer"


class FakeModel:
    """``generate(**kw)`` returning what ``reply(kind, user_text)`` says (``str`` or an
    ``Exception`` to raise). ``usage``: the ``(tokens_in, tokens_out)`` each call reports."""

    name = "fake-model"

    def __init__(self, reply, *, usage=(1_000, 400)):
        self.reply, self.usage = reply, usage
        self.calls: list[dict] = []

    def generate(self, *, model, messages, **kw):
        self.calls.append({"model": model, "messages": messages, **kw})
        user = next((str(m.get("content", "")) for m in reversed(messages) if m.get("role") == "user"), "")
        out = self.reply(kind_of(messages), user)
        if isinstance(out, Exception):
            raise out
        return RawCompletion(text=str(out), tokens_in=self.usage[0], tokens_out=self.usage[1],
                             model_used=model, served_model=model.split("/", 1)[-1])


def configure(monkeypatch, name="main-model", fallbacks=None, url="https://models.example.test/v1",
              key="k-test-not-real"):
    """Set the one adapter's environment (a model is configured; nothing is ever called)."""
    monkeypatch.setenv("IB_MODEL_URL", url)
    monkeypatch.setenv("IB_MODEL_NAME", name)
    if key:
        monkeypatch.setenv("IB_MODEL_KEY", key)
    if fallbacks:
        monkeypatch.setenv("IB_MODEL_FALLBACKS", ",".join(fallbacks))

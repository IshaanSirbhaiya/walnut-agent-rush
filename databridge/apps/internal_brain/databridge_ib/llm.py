"""Model access for the Internal Brain: ONE provider-neutral adapter, or no model at all (plan §4.10).

With nothing configured (the default) there is no model: every answer is the deterministic,
quoted-evidence answer, and it says so. An optional model is plugged in by environment only:

* ``IB_MODEL_URL``: the base URL of a chat-completions-style JSON endpoint (the adapter posts to
  ``<url>/chat/completions``). There is no default URL.
* ``IB_MODEL_NAME``: the model name sent to it, and the model id answers and ``/ib/status`` show.
  There is no default name.
* ``IB_MODEL_KEY``: an optional bearer key. Never logged, never shown.
* ``IB_MODEL_FALLBACKS``: optional, comma-separated: more model names on the same endpoint, tried
  in order after ``IB_MODEL_NAME``.

Routing goes through Walnut's harness (``databridge_harness.ChatBackend``: plain HTTPS, no vendor
SDK) and the shared guard (``model_guard.ModelGuard``: a per-person and a service-wide rate, a total
and a daily spend cap). The chain is explicit: each model in order, then the deterministic
extractive answer. Any error, timeout, rate or cap refusal, or grounding violation moves down the
chain; the answer always says which model produced it. The model sees only passages that passed
both permission checks, and the grounding wall applies to every word it writes.
"""
from __future__ import annotations

import contextlib
import contextvars
import copy
import logging
import math
import os
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

from .models import ModelInfo
from .narrate import IB_SYSTEM_PROMPT, TASK, IbGroundedNarrator, user_message

log = logging.getLogger("databridge_ib.llm")

#: the provider label answers, the ledger and ``/ib/status`` show for the configured model
PROVIDER = "model"
#: the most output tokens one answer, draft or structured call may use
ANSWER_MAX_TOKENS = 4_000
#: the slowest a model answer may take before the quoted answer is served instead
#: (``IB_MODEL_ANSWER_TIMEOUT_S``). An answer that has not arrived in about 12 s is better served
#: quoted, with the label saying the model did not reply in time, than waited for. Bounded to 1 to
#: 120 s; an unreadable value means the default.
ANSWER_TIMEOUT_DEFAULT_S = 12.0

#: the person a model call is made for (the guard's per-person limit reads it; never sent to a
#: model, never logged). Unset: "" (the guard then counts the call under one shared key).
MODEL_SUB: contextvars.ContextVar[str] = contextvars.ContextVar("ib_model_sub", default="")


@contextlib.contextmanager
def for_person(sub: str):
    """Model calls inside this block are made for ``sub`` (per-person rate limits)."""
    tok = MODEL_SUB.set(str(sub or ""))
    try:
        yield
    finally:
        MODEL_SUB.reset(tok)


# -- configuration (environment only) --------------------------------------------------------
def model_url() -> str:
    return os.environ.get("IB_MODEL_URL", "").strip()


def model_name() -> str:
    return os.environ.get("IB_MODEL_NAME", "").strip()


def model_fallbacks() -> list[str]:
    return [m.strip() for m in os.environ.get("IB_MODEL_FALLBACKS", "").split(",") if m.strip()]


def model_configured() -> bool:
    """An endpoint and a model name are set (whether or not ``IB_FORCE_OFFLINE`` is on)."""
    return bool(model_url() and model_name())


def force_offline() -> bool:
    return os.environ.get("IB_FORCE_OFFLINE") == "1"


def model_enabled() -> bool:
    """A model may be called: configured, and the IB is not forced offline."""
    return model_configured() and not force_offline()


def configured_models() -> list[str]:
    """``IB_MODEL_NAME`` then ``IB_MODEL_FALLBACKS``, in order, without repeats ([] when unset)."""
    name = model_name()
    if not name:
        return []
    out: list[str] = []
    for m in [name, *model_fallbacks()]:
        if m not in out:
            out.append(m)
    return out


def provider_label() -> str:
    return PROVIDER


def answer_timeout_s() -> float:
    raw = os.environ.get("IB_MODEL_ANSWER_TIMEOUT_S", "").strip()
    try:
        val = float(raw) if raw else ANSWER_TIMEOUT_DEFAULT_S
    except ValueError:
        return ANSWER_TIMEOUT_DEFAULT_S
    if not math.isfinite(val):
        return ANSWER_TIMEOUT_DEFAULT_S
    return min(120.0, max(1.0, val))


def _price(name: str) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        v = float(raw) if raw else 0.0
    except ValueError:
        return 0.0
    return v if math.isfinite(v) and v >= 0 else 0.0


def prices() -> tuple[float, float]:
    """``(input, output)`` US$ per million tokens: ``IB_MODEL_PRICE_IN_USD`` and
    ``IB_MODEL_PRICE_OUT_USD`` (default 0: the spend caps then count nothing; the rates still hold)."""
    return _price("IB_MODEL_PRICE_IN_USD"), _price("IB_MODEL_PRICE_OUT_USD")


def worst_usd(chars: int, max_tokens: int) -> float:
    """An upper bound for one call, so a cap is hard: a token is at least one character (input at
    most one token per character, plus a margin for message framing), and the output at most
    ``max_tokens``."""
    pin, pout = prices()
    return (chars + 8_000) * pin / 1_000_000 + max_tokens * pout / 1_000_000


def cost_usd(tokens_in: int, tokens_out: int) -> float:
    pin, pout = prices()
    return (max(0, int(tokens_in or 0)) * pin + max(0, int(tokens_out or 0)) * pout) / 1_000_000


def wire_model(name: str) -> str:
    """The harness model id for a configured name (the ``chat`` kind: ``ChatBackend``)."""
    return f"chat/{name}"


class GuardedBackend:
    """A harness ``Backend``: every call is admitted by the shared guard first (no ticket, no call),
    bounded by ``max_tokens`` and the answer timeout, and its real cost recorded after it."""

    name = "guarded"

    def __init__(self, guard: Any, inner: Any = None, *, kind: str = "answer"):
        if inner is None:
            from databridge_harness import ChatBackend
            inner = ChatBackend()
        self.guard, self.inner, self.kind = guard, inner, kind

    def generate(self, *, model: str, messages: list[dict], json_mode: bool = False,
                 guided_json: Optional[dict] = None, seed: Optional[int] = None, **kwargs: Any):
        from .model_guard import REFUSED
        chars = sum(len(str(m.get("content", ""))) for m in messages)
        ticket, why = self.guard.admit(MODEL_SUB.get() or "-", self.kind,
                                       worst_usd(chars, ANSWER_MAX_TOKENS))
        if ticket is None:
            log.info("model call refused by the guard: %s", why)
            raise RuntimeError(REFUSED)
        actual = 0.0
        try:
            kwargs.setdefault("max_tokens", ANSWER_MAX_TOKENS)
            kwargs.setdefault("timeout", answer_timeout_s())
            # reasoning models (OpenAI/OpenRouter-style endpoints): thinking counts against max_tokens and
            # the answer timeout; ``none`` turns it off. Off unless set; the engine passes it through.
            effort = os.environ.get("IB_MODEL_REASONING_EFFORT", "").strip()
            if effort:
                kwargs.setdefault("reasoning", {"effort": effort})
            raw = self.inner.generate(model=model, messages=messages, json_mode=json_mode,
                                      guided_json=guided_json, seed=seed, **kwargs)
            actual = cost_usd(raw.tokens_in, raw.tokens_out)
            return raw
        finally:
            try:
                self.guard.settle(ticket, actual)
            except Exception as exc:                                # noqa: BLE001
                log.error("spend not recorded: %s", type(exc).__name__)


def _config_for(model: str) -> dict:
    return {"routing": {TASK: "ib_model", "ib_deliver": "ib_model"},
            "aliases": {"ib_model": {"model": wire_model(model)}},
            "profiles": {"cloud": {}, "airgapped": {}}}


@dataclass
class ModelChain:
    """Ordered narrators; ``harness_factory(model)`` returns a Walnut Harness (or a test double)."""
    models: Sequence[str]
    harness_factory: Callable[[str], Any]
    provider: str = PROVIDER

    @classmethod
    def from_env(cls, models: Optional[Sequence[str]] = None, *, guard: Any = None,
                 inner: Any = None) -> Optional["ModelChain"]:
        """The configured chain (``IB_MODEL_NAME`` then ``IB_MODEL_FALLBACKS`` on ``IB_MODEL_URL``),
        or None for the deterministic quoting path: nothing configured, or ``IB_FORCE_OFFLINE=1``.
        ``inner`` (a test double) replaces the HTTP backend; ``guard`` the shared guard."""
        if not model_enabled():
            return None
        from databridge_harness import Harness

        from .model_guard import ModelGuard
        backend = GuardedBackend(guard or ModelGuard.shared(), inner)

        def factory(model: str):
            return Harness(backend, config=copy.deepcopy(_config_for(model)), profile="cloud",
                           cache=None)
        return cls(models=list(models) if models else configured_models(), harness_factory=factory)

    def answer(self, context: str, question: str) -> tuple[Optional[str], Optional[ModelInfo], list[str]]:
        """``(grounded_text | None, model_info | None, notes)``. None ⇒ caller serves extractive."""
        return self._grounded(IB_SYSTEM_PROMPT, context, question)

    def draft(self, system_prompt: str, context: str, instruction: str
              ) -> tuple[Optional[str], Optional[ModelInfo], list[str]]:
        """A draft (``actions.py``) under the SAME grounding wall as an answer: the context is the
        asker's own released, cited passages; no tools are passed; a sentence that binds to no
        passage is dropped and an unsupported value or name refuses the draft. None ⇒ the caller
        builds the deterministic draft."""
        return self._grounded(system_prompt, context, instruction)

    def _grounded(self, system_prompt: str, context: str, question: str
                  ) -> tuple[Optional[str], Optional[ModelInfo], list[str]]:
        notes: list[str] = []
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message(context, question)}]
        for i, model in enumerate(self.models):
            try:
                narrator = IbGroundedNarrator(self.harness_factory(model))
                res = narrator.complete_text(TASK, messages, seed=7)
                text = getattr(res, "text", "") or ""
                if text.strip():
                    return text, ModelInfo(provider=self.provider, model=model, fallback_used=i > 0), notes
                notes.append(f"{model}: empty")
            except Exception as exc:                                # noqa: BLE001
                notes.append(f"{model}: {type(exc).__name__}")
                log.warning("model %s failed: %s", model, type(exc).__name__)
        return None, None, notes

    def complete(self, messages: list[dict], *, seed: int = 7) -> tuple[Optional[str], Optional[str], list[str]]:
        """``(text | None, model | None, notes)`` from the first model in the chain that returns
        non-empty text, in the chain's order, with NO grounding wall. Only for output that is
        validated against a closed schema before use (the audit filter parser, audit/nl_llm.py);
        answers to employees always go through `answer`."""
        notes: list[str] = []
        for model in self.models:
            try:
                res = self.harness_factory(model).complete_text(TASK, messages, seed=seed)
                text = getattr(res, "text", "") or ""
                if text.strip():
                    return text, model, notes
                notes.append(f"{model}: empty")
            except Exception as exc:                                # noqa: BLE001
                notes.append(f"{model}: {type(exc).__name__}")
                log.warning("model %s failed: %s", model, type(exc).__name__)
        return None, None, notes

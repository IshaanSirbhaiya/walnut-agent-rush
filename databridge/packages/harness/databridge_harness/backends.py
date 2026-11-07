"""Backend capability table + the one real backend: a plain HTTPS chat-completions client.

The capability table is EXPLICIT, not probed (07_PRD §3): the gaps between endpoint kinds
are exactly where silent quality loss hides, so we encode them as a reviewed fact. The
structured-output ladder in client.py reads these caps to decide L3 vs L2 vs L1 per call.

No vendor SDK is imported anywhere (P2 / ADR-0002): ``ChatBackend`` speaks the common
chat-completions JSON shape over ``httpx`` to whatever endpoint ``IB_MODEL_URL`` names. There is
no default URL and no default model name: with nothing configured, nothing is called.
"""
from __future__ import annotations

import fnmatch
import ipaddress
import os
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Protocol, Union
from urllib.parse import urlsplit

if TYPE_CHECKING:  # pragma: no cover
    from .embedding import RawEmbedding


@dataclass(frozen=True)
class Caps:
    """What a backend family can guarantee about structured output (07_PRD §3)."""

    json_mode: bool                       # can force syntactically-valid JSON
    strict_schema: bool                   # near-guaranteed schema compliance
    tools: Union[bool, str]               # True | False | "varies"
    guided_decoding: Union[bool, str]     # False | "guided_json"
    seed: bool                            # honours a seed for reproducibility

    @property
    def has_guided_decoding(self) -> bool:
        """True when token-level grammar constraint (L3) is available."""
        return bool(self.guided_decoding)


# The table: a reviewed fact, keyed by "<provider>/*". The providers are KINDS of endpoint, not
# vendors: every one is a chat-completions-style JSON endpoint reached by ``ChatBackend``.
CAPABILITIES: dict[str, Caps] = {
    # Any chat-completions-style endpoint (``IB_MODEL_URL``). JSON mode guarantees JSON syntax,
    # NOT your schema → L1/L2 carry weight.
    "chat/*": Caps(json_mode=True, strict_schema=False, tools=True,
                   guided_decoding=False, seed=True),
    # The same kind of endpoint on the customer's own network (the airgapped profile's target).
    "local/*": Caps(json_mode=True, strict_schema=False, tools="varies",
                    guided_decoding=False, seed=True),
    # A self-hosted model server with guided decoding: guided_json = token-level grammar ⇒ schema
    # guaranteed; the strongest local option, the recommended airgapped serving stack.
    "local_server/*": Caps(json_mode=True, strict_schema=True, tools=True,
                          guided_decoding="guided_json", seed=True),
}

# Conservative fallback for an unrecognised provider: force nothing, lean on L1/L2.
_UNKNOWN_CAPS = Caps(json_mode=False, strict_schema=False, tools=False,
                     guided_decoding=False, seed=False)

# Provider prefixes whose models leave the customer perimeter (P1 airgapped refusal).
HOSTED_PROVIDERS = frozenset({"chat"})
#: Provider prefixes that must be served from the customer's own network. ``ChatBackend`` refuses
#: to send one to an endpoint whose host is not local or private.
LOCAL_PROVIDERS = frozenset({"local", "local_server"})
#: Every provider ``ChatBackend`` can reach.
KNOWN_PROVIDERS = HOSTED_PROVIDERS | LOCAL_PROVIDERS

#: The one model endpoint: its base URL (``<url>/chat/completions``) and an optional bearer key.
MODEL_URL_ENV, MODEL_KEY_ENV = "IB_MODEL_URL", "IB_MODEL_KEY"
#: The configured model's name; a routed model named ``default`` (``chat/default``) means it.
MODEL_NAME_ENV, DEFAULT_NAME = "IB_MODEL_NAME", "default"
#: More model names, comma-separated, tried in order after it; ``alt`` means the first of them.
MODEL_FALLBACKS_ENV, ALT_NAME = "IB_MODEL_FALLBACKS", "alt"
#: Model names (comma-separated ``fnmatch`` patterns) that accept NO sampling override: for them
#: ``temperature``/``top_p``/``top_k`` are never sent. Empty by default.
FIXED_SAMPLING_ENV = "IB_MODEL_FIXED_SAMPLING"
DEFAULT_TIMEOUT_S = 60.0


def provider_of(model: str) -> str:
    """The provider segment of a model id, e.g. 'chat/my-model' → 'chat'."""
    return model.split("/", 1)[0]


def caps_for(model: str) -> Caps:
    """Capabilities for a model id; conservative defaults for unknown providers."""
    return CAPABILITIES.get(f"{provider_of(model)}/*", _UNKNOWN_CAPS)


#: The sampling controls such a model rejects. They are removed AFTER every argument is combined,
#: so no caller keyword can put one back (R-019 round 3, High #7).
REJECTED_SAMPLING_CONTROLS = ("temperature", "top_p", "top_k")


def accepts_sampling_override(model: str) -> bool:
    """False when ``model`` (its id, or the name after the provider) matches a pattern in
    ``IB_MODEL_FIXED_SAMPLING``: such a model rejects any temperature other than its default."""
    pats = [p.strip() for p in os.environ.get(FIXED_SAMPLING_ENV, "").split(",") if p.strip()]
    name = endpoint_name(model.split("/", 1)[-1])
    return not any(fnmatch.fnmatchcase(model, p) or fnmatch.fnmatchcase(name, p) for p in pats)


def is_hosted(model: str) -> bool:
    """True if the model would call out of the customer perimeter (hosted API)."""
    return provider_of(model) in HOSTED_PROVIDERS


_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")


def is_local_url(url: str) -> bool:
    """True when ``url``'s host is loopback, a private or link-local address, a single-label name
    or a local-only DNS suffix: an endpoint inside the customer's own network."""
    try:
        host = (urlsplit(str(url)).hostname or "").strip("[]").lower()
    except ValueError:
        return False
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host == "localhost" or host.endswith(_LOCAL_SUFFIXES) or "." not in host
    return ip.is_loopback or ip.is_private or ip.is_link_local


@dataclass(frozen=True)
class RawCompletion:
    """What a backend returns: the raw text plus usage telemetry."""

    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    model_used: str = ""
    #: the model name the endpoint says served the call ("" when it did not say)
    served_model: str = ""

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out


class Backend(Protocol):
    """The single method client.py calls. FakeBackend and ChatBackend both satisfy it."""

    name: str

    def generate(
        self,
        *,
        model: str,
        messages: list[dict],
        json_mode: bool = False,
        guided_json: Optional[dict] = None,
        seed: Optional[int] = None,
        **kwargs: Any,
    ) -> RawCompletion: ...

    # Optional (additive): ``embed(*, model, inputs) -> RawEmbedding``. A backend without it
    # makes ``Harness.embed`` fall back to the labelled offline embedding rather than fail.


class ModelCallError(RuntimeError):
    """The endpoint answered with an error, or not at all. Carries the HTTP status only: never
    the response body, the URL or the key."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class ModelTimeout(ModelCallError):
    """The endpoint did not answer within the call's timeout."""


class ModelTruncated(ModelCallError):
    """The reply was cut at ``max_tokens`` (``finish_reason: length``): never used as an answer."""


class EndpointRefused(ModelCallError):
    """No endpoint is configured for the model's provider, or a local-only provider would be
    sent to an endpoint outside the customer's network."""


def split_model(model: str) -> tuple[str, str]:
    """``(provider, name)`` for a model id. The name is what the endpoint is sent; it may itself
    contain a ``/``. An id without a provider prefix is a ``chat`` model."""
    head, sep, rest = str(model).partition("/")
    return (head, rest) if sep else ("chat", head)


def endpoint_name(name: str) -> str:
    """The model name sent to the endpoint. The repo names no model, so ``config/models.yaml``
    routes to two placeholders: ``default`` is ``IB_MODEL_NAME`` ("" when unset), and ``alt``
    (the verifier, a DIFFERENT model for adversarial separation) is the first name in
    ``IB_MODEL_FALLBACKS``, else ``IB_MODEL_NAME``."""
    if name == DEFAULT_NAME:
        return os.environ.get(MODEL_NAME_ENV, "").strip()
    if name == ALT_NAME:
        alts = [n.strip() for n in os.environ.get(MODEL_FALLBACKS_ENV, "").split(",") if n.strip()]
        return alts[0] if alts else os.environ.get(MODEL_NAME_ENV, "").strip()
    return name


class ChatBackend:
    """The real backend: one chat-completions-style JSON endpoint over HTTPS (P2).

    ``url`` and ``key`` default to ``IB_MODEL_URL`` / ``IB_MODEL_KEY``, read per call. The key is
    sent as a bearer token and never logged or put in an error. A ``local/`` or ``local_server/``
    model is only ever sent to a local or private host (``is_local_url``)."""

    name = "chat"

    def __init__(self, url: Optional[str] = None, key: Optional[str] = None, *,
                 timeout_s: Optional[float] = None, client: Any = None) -> None:
        self._url, self._key = url, key
        self.timeout_s = float(timeout_s) if timeout_s else DEFAULT_TIMEOUT_S
        self._client = client
        self._lock = threading.Lock()

    # -- the endpoint -----------------------------------------------------------------------
    def endpoint(self) -> tuple[str, str]:
        """``(base_url, key)``; the URL is "" when none is configured."""
        url = self._url if self._url is not None else os.environ.get(MODEL_URL_ENV, "")
        key = self._key if self._key is not None else os.environ.get(MODEL_KEY_ENV, "")
        return str(url or "").strip().rstrip("/"), str(key or "").strip()

    def configured(self) -> bool:
        return bool(self.endpoint()[0])

    def _http(self):
        with self._lock:
            if self._client is None:
                import httpx
                self._client = httpx.Client()
            return self._client

    def _post(self, model: str, path: str, body: dict, timeout: Optional[float]) -> dict:
        provider, _name = split_model(model)
        if provider not in KNOWN_PROVIDERS:
            raise EndpointRefused(f"no endpoint for provider {provider!r}")
        if not body.get("model"):
            raise EndpointRefused(f"no model name ({MODEL_NAME_ENV} is not set)")
        url, key = self.endpoint()
        if not url:
            raise EndpointRefused(f"{MODEL_URL_ENV} is not set")
        if provider in LOCAL_PROVIDERS and not is_local_url(url):
            raise EndpointRefused(f"a {provider} model is only sent to a local endpoint")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            resp = self._http().post(url + path, json=body, headers=headers,
                                     timeout=float(timeout or self.timeout_s))
        except Exception as exc:                                    # noqa: BLE001
            if "Timeout" in type(exc).__name__:
                raise ModelTimeout("model endpoint timed out") from None
            raise ModelCallError(f"model endpoint unreachable ({type(exc).__name__})") from None
        status = int(getattr(resp, "status_code", 0) or 0)
        if status >= 400:
            raise ModelCallError(f"model endpoint returned HTTP {status}", status)
        try:
            data = resp.json()
        except Exception:                                           # noqa: BLE001
            raise ModelCallError("model endpoint returned no JSON", status) from None
        if not isinstance(data, dict):
            raise ModelCallError("model endpoint returned an unexpected shape", status)
        return data

    # -- the calls --------------------------------------------------------------------------
    def generate(
        self,
        *,
        model: str,
        messages: list[dict],
        json_mode: bool = False,
        guided_json: Optional[dict] = None,
        seed: Optional[int] = None,
        **kwargs: Any,
    ) -> RawCompletion:
        name = endpoint_name(split_model(model)[1])
        timeout = kwargs.pop("timeout", None)
        # temperature=0 where the model accepts a sampling override (determinism); OMITTED for
        # the models ``IB_MODEL_FIXED_SAMPLING`` names.
        body: dict[str, Any] = {"model": name, "messages": messages}
        if accepts_sampling_override(model):
            body["temperature"] = 0
        if seed is not None:
            body["seed"] = seed
        if guided_json is not None:
            body["guided_json"] = guided_json          # the server's token-level grammar (L3)
        elif json_mode:
            body["response_format"] = {"type": "json_object"}
        for k, v in kwargs.items():
            body.setdefault(k, v)
        if not accepts_sampling_override(model):
            # applied last: a caller-supplied ``temperature=`` (or top_p/top_k) never reaches a
            # model that answers it with a 400
            for ctl in REJECTED_SAMPLING_CONTROLS:
                body.pop(ctl, None)

        data = self._post(model, "/chat/completions", body, timeout)
        try:
            choice = data["choices"][0]
            text = (choice.get("message") or {}).get("content") or ""
        except (KeyError, IndexError, TypeError, AttributeError):
            raise ModelCallError("model endpoint returned no choices") from None
        if choice.get("finish_reason") == "length":
            raise ModelTruncated("the reply was cut at max_tokens")
        usage = data.get("usage") or {}
        return RawCompletion(text=str(text),
                             tokens_in=int(usage.get("prompt_tokens", 0) or 0),
                             tokens_out=int(usage.get("completion_tokens", 0) or 0),
                             cost_usd=0.0, model_used=model,
                             served_model=str(data.get("model") or ""))

    def embed(self, *, model: str, inputs: list[str], **kwargs: Any) -> "RawEmbedding":
        """One embedding batch (``<url>/embeddings``, ``task_class: embed``)."""
        from .embedding import RawEmbedding

        name = endpoint_name(split_model(model)[1])
        timeout = kwargs.pop("timeout", None)
        data = self._post(model, "/embeddings", {"model": name, "input": list(inputs), **kwargs},
                          timeout)
        try:
            rows = sorted(data["data"], key=lambda d: d["index"])
            vectors = [list(d["embedding"]) for d in rows]
        except (KeyError, TypeError):
            raise ModelCallError("model endpoint returned no embeddings") from None
        usage = data.get("usage") or {}
        return RawEmbedding(vectors=vectors, tokens=int(usage.get("prompt_tokens", 0) or 0),
                            cost_usd=0.0, model_used=model)

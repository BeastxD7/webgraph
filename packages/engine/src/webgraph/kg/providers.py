"""Bring your own model: three raw-`httpx` adapters and a fake one for tests.

Why no SDKs
-----------
Every system studied for the design converged on "one module per vendor plus an
OpenAI-compatible route with a `base_url`", or on LiteLLM. LiteLLM would be the engine's
heaviest dependency by an order of magnitude (92 requirements, 23 MB); the three official
SDKs carry 14-18 dependencies each. The engine's stance is httpx, lxml, pydantic and
jsonschema, and httpx already speaks to every one of these APIs. Three small adapters cost a
few hundred lines and add nothing to `pip install webgraph`.

The OpenAI-compatible adapter covers Ollama (`http://localhost:11434/v1`), LM Studio, vLLM,
Groq, Together, OpenRouter, DeepSeek, Mistral, xAI and OpenAI itself -- a `base_url` and a
model name. Anthropic and Gemini have their own request shapes and get their own adapters.

Keys
----
A key arrives in the request body (the web UI) or from an environment variable (the CLI, a
self-hosted default); it lives in a `ProviderConfig` field excluded from `repr`, is sent as a
header to the provider and nowhere else, and is never written to a trace, a store or a log.
`ProviderConfig.redacted()` is the only form that leaves the process.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Final, Literal, Protocol
from urllib.parse import urlsplit

import httpx

from webgraph import config as _config

__all__ = [
    "PRESETS",
    "AnthropicProvider",
    "FakeProvider",
    "GeminiProvider",
    "JsonMode",
    "LLMError",
    "LLMResult",
    "OpenAICompatProvider",
    "Provider",
    "ProviderConfig",
    "ProviderName",
    "Usage",
    "make_provider",
]

ProviderName = Literal["openai-compatible", "anthropic", "gemini", "fake"]
JsonMode = Literal["json_schema", "json_object", "prompt"]

PRESETS: Final[dict[str, dict[str, str]]] = {
    "openai": {"provider": "openai-compatible", "base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY"},
    "groq": {"provider": "openai-compatible", "base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY"},
    "together": {"provider": "openai-compatible", "base_url": "https://api.together.xyz/v1", "api_key_env": "TOGETHER_API_KEY"},
    "openrouter": {"provider": "openai-compatible", "base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY"},
    "deepseek": {"provider": "openai-compatible", "base_url": "https://api.deepseek.com/v1", "api_key_env": "DEEPSEEK_API_KEY"},
    "mistral": {"provider": "openai-compatible", "base_url": "https://api.mistral.ai/v1", "api_key_env": "MISTRAL_API_KEY"},
    "xai": {"provider": "openai-compatible", "base_url": "https://api.x.ai/v1", "api_key_env": "XAI_API_KEY"},
    "ollama": {"provider": "openai-compatible", "base_url": "http://localhost:11434/v1", "api_key_env": ""},
    "lmstudio": {"provider": "openai-compatible", "base_url": "http://localhost:1234/v1", "api_key_env": ""},
    "vllm": {"provider": "openai-compatible", "base_url": "http://localhost:8000/v1", "api_key_env": ""},
    "anthropic": {"provider": "anthropic", "base_url": "https://api.anthropic.com", "api_key_env": "ANTHROPIC_API_KEY"},
    "gemini": {"provider": "gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta", "api_key_env": "GEMINI_API_KEY"},
}
"""A preset is a `base_url` and the conventional key variable, nothing more."""

_RETRY_STATUSES: Final[frozenset[int]] = frozenset({408, 409, 429, 500, 502, 503, 504})
_MAX_ATTEMPTS: Final[int] = 4


class LLMError(RuntimeError):
    """The provider could not produce a usable answer. Carries the status when there is one."""

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens)


@dataclass(frozen=True, slots=True)
class LLMResult:
    text: str
    usage: Usage
    model: str
    cached: bool = False

    def json(self) -> Any:
        return _parse_json(self.text)


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Everything needed to call a model. `api_key` is excluded from `repr` and `redacted()`."""

    provider: ProviderName = "openai-compatible"
    base_url: str = "https://api.openai.com/v1"
    model: str = ""
    answer_model: str | None = None
    api_key: str | None = field(default=None, repr=False)
    api_key_env: str | None = None
    json_mode: JsonMode = "json_schema"
    max_concurrency: int = _config.KG_CONCURRENCY
    timeout_s: float = 120.0
    price_per_m_in: float | None = None
    price_per_m_out: float | None = None
    max_output_tokens: int = 4096

    def resolve_key(self, environ: Mapping[str, str] | None = None) -> str | None:
        """The key to send: the explicit one, else the named variable, else the preset's."""
        if self.api_key:
            return self.api_key
        env = os.environ if environ is None else environ
        for name in (self.api_key_env, _preset_key_env(self.base_url)):
            if name and env.get(name):
                return env[name]
        return None

    def redacted(self) -> dict[str, Any]:
        """The shape that may be logged, traced or echoed: no key, only whether one exists."""
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "answer_model": self.answer_model,
            "json_mode": self.json_mode,
            "has_key": bool(self.api_key) or bool(self.api_key_env and os.environ.get(self.api_key_env)),
        }

    def usd(self, usage: Usage) -> float | None:
        if self.price_per_m_in is None and self.price_per_m_out is None:
            return None
        return (
            usage.input_tokens * (self.price_per_m_in or 0.0)
            + usage.output_tokens * (self.price_per_m_out or 0.0)
        ) / 1_000_000

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ProviderConfig:
        """`WEBGRAPH_LLM_{PROVIDER,BASE_URL,API_KEY,API_KEY_ENV,MODEL,ANSWER_MODEL,CONCURRENCY,
        JSON_MODE,PRICE_IN,PRICE_OUT}`. `PROVIDER` may be a preset name (`ollama`, `groq`)."""
        env = os.environ if environ is None else environ
        raw = env.get("WEBGRAPH_LLM_PROVIDER", "").strip().lower()
        preset = PRESETS.get(raw, {})
        provider = preset.get("provider") or raw or "openai-compatible"
        if provider not in ("openai-compatible", "anthropic", "gemini", "fake"):
            provider = "openai-compatible"

        def price(name: str) -> float | None:
            value = env.get(name, "").strip()
            return float(value) if value else None

        return cls(
            provider=provider,  # type: ignore[arg-type]
            base_url=env.get("WEBGRAPH_LLM_BASE_URL", "").strip() or preset.get("base_url") or "https://api.openai.com/v1",
            model=env.get("WEBGRAPH_LLM_MODEL", "").strip(),
            answer_model=env.get("WEBGRAPH_LLM_ANSWER_MODEL", "").strip() or None,
            api_key=env.get("WEBGRAPH_LLM_API_KEY", "").strip() or None,
            api_key_env=env.get("WEBGRAPH_LLM_API_KEY_ENV", "").strip() or preset.get("api_key_env") or None,
            json_mode=_json_mode(env.get("WEBGRAPH_LLM_JSON_MODE", "")),
            max_concurrency=int(env.get("WEBGRAPH_LLM_CONCURRENCY", "") or _config.KG_CONCURRENCY),
            price_per_m_in=price("WEBGRAPH_LLM_PRICE_IN"),
            price_per_m_out=price("WEBGRAPH_LLM_PRICE_OUT"),
        )

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any], *, base: ProviderConfig | None = None, trusted: bool = True
    ) -> ProviderConfig:
        """A request-body config over an environment default. Unknown keys are ignored;
        `provider` may be a preset name. With `trusted=False` (a body from the network)
        `api_key_env` may only name a variable in `KEY_ENVS_A_CALLER_MAY_NAME`."""
        current = base or cls.from_env()
        named_env = data.get("api_key_env")
        if not trusted and isinstance(named_env, str) and named_env.strip() and named_env.strip() not in KEY_ENVS_A_CALLER_MAY_NAME:
            raise ValueError(
                f"api_key_env may name one of {', '.join(sorted(KEY_ENVS_A_CALLER_MAY_NAME))}; send api_key instead"
            )
        raw = str(data.get("provider") or "").strip().lower()
        preset = PRESETS.get(raw, {})
        updates: dict[str, Any] = {}
        if raw:
            updates["provider"] = preset.get("provider") or raw
            if preset.get("base_url") and not data.get("base_url"):
                updates["base_url"] = preset["base_url"]
            if preset.get("api_key_env") and not data.get("api_key_env"):
                updates["api_key_env"] = preset["api_key_env"]
        for key in ("base_url", "model", "answer_model", "api_key", "api_key_env"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                updates[key] = value.strip()
        if data.get("json_mode"):
            updates["json_mode"] = _json_mode(str(data["json_mode"]))
        for key in ("price_per_m_in", "price_per_m_out", "timeout_s"):
            if isinstance(data.get(key), int | float):
                updates[key] = float(data[key])
        if isinstance(data.get("max_concurrency"), int):
            updates["max_concurrency"] = max(1, min(int(data["max_concurrency"]), 16))
        merged = replace(current, **updates)
        if merged.provider not in ("openai-compatible", "anthropic", "gemini", "fake"):
            raise ValueError(f"unknown provider {merged.provider!r}")
        return merged


def _json_mode(value: str) -> JsonMode:
    value = value.strip().lower()
    return value if value in ("json_schema", "json_object", "prompt") else "json_schema"  # type: ignore[return-value]


def _preset_key_env(base_url: str) -> str | None:
    """The conventional key variable for a `base_url`, decided by the host it names, never
    by a string prefix: `https://api.openai.com.evil.example/v1` starts with OpenAI's URL
    and is not OpenAI, and a key sent there is a key given away."""
    target = urlsplit(base_url)
    for preset in PRESETS.values():
        if not preset["base_url"]:
            continue
        known = urlsplit(preset["base_url"])
        if (target.scheme, target.netloc.lower()) == (known.scheme, known.netloc.lower()):
            return preset["api_key_env"] or None
    return None


KEY_ENVS_A_CALLER_MAY_NAME: frozenset[str] = frozenset(
    {preset["api_key_env"] for preset in PRESETS.values() if preset["api_key_env"]} | {"WEBGRAPH_LLM_API_KEY"}
)
"""The environment variables a request over the API may point `api_key_env` at. Anything
else -- `AWS_SECRET_ACCESS_KEY`, `DATABASE_URL` -- would be read off the server and sent as
a bearer token to whatever `base_url` the same request named. The CLI is the operator's own
shell and is not limited."""


class Provider(Protocol):
    """What `build.py` and `retrieve.py` need from a model."""

    config: ProviderConfig

    def complete_json(self, system: str, user: str, schema: dict[str, Any], *, model: str | None = None) -> LLMResult: ...

    def complete_text(self, system: str, user: str, *, model: str | None = None) -> LLMResult: ...


_FENCE: Final[re.Pattern[str]] = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def _parse_json(text: str) -> Any:
    """Tolerate a fenced or prefixed JSON object; raise `LLMError` otherwise."""
    cleaned = _FENCE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass
    raise LLMError("the model did not return a JSON object")


def _schema_in_prompt(user: str, schema: dict[str, Any]) -> str:
    return f"{user}\n\nReturn ONLY a JSON object matching this JSON Schema:\n{json.dumps(schema)}"


class _HttpProvider:
    """Shared retry loop. Subclasses build the request and read the response."""

    def __init__(self, config: ProviderConfig, *, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        self._client = httpx.Client(timeout=config.timeout_s, transport=transport)

    def close(self) -> None:
        self._client.close()

    def _post(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        last: LLMError | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = self._client.post(url, headers=headers, json=body)
            except httpx.HTTPError as exc:
                last = LLMError(f"{type(exc).__name__} talking to {url}", retryable=True)
            else:
                if response.status_code < 300:
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise LLMError("provider returned a non-object response", status=response.status_code)
                    return payload
                # Never echo the response body wholesale: some providers repeat the
                # request, and the request may quote page text, but never the key --
                # keys travel in headers. The first 300 characters name the error.
                detail = response.text[:300].replace("\n", " ")
                last = LLMError(
                    f"provider answered {response.status_code}: {detail}",
                    status=response.status_code,
                    retryable=response.status_code in _RETRY_STATUSES,
                )
                if not last.retryable:
                    raise last
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(min(8.0, (2**attempt) * 0.5 + random.random() * 0.25))
        raise last or LLMError("provider unreachable")


class OpenAICompatProvider(_HttpProvider):
    """`/chat/completions` with `response_format`; Ollama, vLLM, OpenAI, Groq and friends.

    Structured output is a ladder: `json_schema` (strict) where the server honours it,
    `json_object` with the schema in the prompt where it does not (Ollama accepts the
    schema form; some proxies 400 on it), plain prompting as the last rung. A 400 on one
    rung steps down and remembers, so a build pays the failed call once.
    """

    def __init__(self, config: ProviderConfig, *, transport: httpx.BaseTransport | None = None) -> None:
        super().__init__(config, transport=transport)
        self._mode: JsonMode = config.json_mode

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        key = self.config.resolve_key()
        if key:
            headers["authorization"] = f"Bearer {key}"
        return headers

    def complete_json(self, system: str, user: str, schema: dict[str, Any], *, model: str | None = None) -> LLMResult:
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        while True:
            body: dict[str, Any] = {
                "model": model or self.config.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0,
                "max_tokens": self.config.max_output_tokens,
            }
            if self._mode == "json_schema":
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "webgraph_extract", "schema": schema, "strict": True},
                }
            elif self._mode == "json_object":
                body["response_format"] = {"type": "json_object"}
                body["messages"][1]["content"] = _schema_in_prompt(user, schema)
            else:
                body["messages"][1]["content"] = _schema_in_prompt(user, schema)
            try:
                payload = self._post(url, self._headers(), body)
            except LLMError as exc:
                if exc.status == 400 and self._mode != "prompt":
                    self._mode = "json_object" if self._mode == "json_schema" else "prompt"
                    continue
                raise
            return _openai_result(payload, str(body["model"]))

    def complete_text(self, system: str, user: str, *, model: str | None = None) -> LLMResult:
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        body = {
            "model": model or self.config.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": self.config.max_output_tokens,
        }
        return _openai_result(self._post(url, self._headers(), body), str(body["model"]))


def _openai_result(payload: dict[str, Any], model: str) -> LLMResult:
    try:
        message = payload["choices"][0]["message"]
        text = message.get("content") or ""
        if isinstance(text, list):  # some servers return content parts
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("unexpected chat-completions response shape") from exc
    usage = payload.get("usage") or {}
    return LLMResult(
        text=str(text),
        usage=Usage(int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)),
        model=str(payload.get("model") or model),
    )


class AnthropicProvider(_HttpProvider):
    """`/v1/messages` with `output_config.format` json_schema; schema-in-prompt fallback."""

    VERSION: Final[str] = "2023-06-01"

    def __init__(self, config: ProviderConfig, *, transport: httpx.BaseTransport | None = None) -> None:
        super().__init__(config, transport=transport)
        self._structured = config.json_mode == "json_schema"

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json", "anthropic-version": self.VERSION}
        key = self.config.resolve_key()
        if key:
            headers["x-api-key"] = key
        return headers

    def _url(self) -> str:
        base = self.config.base_url.rstrip("/")
        return base if base.endswith("/v1/messages") else f"{base.removesuffix('/v1')}/v1/messages"

    def complete_json(self, system: str, user: str, schema: dict[str, Any], *, model: str | None = None) -> LLMResult:
        while True:
            body: dict[str, Any] = {
                "model": model or self.config.model,
                "max_tokens": self.config.max_output_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user if self._structured else _schema_in_prompt(user, schema)}],
            }
            if self._structured:
                body["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
            try:
                payload = self._post(self._url(), self._headers(), body)
            except LLMError as exc:
                if exc.status == 400 and self._structured:
                    self._structured = False
                    continue
                raise
            return _anthropic_result(payload, str(body["model"]))

    def complete_text(self, system: str, user: str, *, model: str | None = None) -> LLMResult:
        body = {
            "model": model or self.config.model,
            "max_tokens": self.config.max_output_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        return _anthropic_result(self._post(self._url(), self._headers(), body), str(body["model"]))


def _anthropic_result(payload: dict[str, Any], model: str) -> LLMResult:
    blocks = payload.get("content") or []
    text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
    usage = payload.get("usage") or {}
    return LLMResult(
        text=text,
        usage=Usage(int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)),
        model=str(payload.get("model") or model),
    )


class GeminiProvider(_HttpProvider):
    """`models/{model}:generateContent` with `responseJsonSchema`."""

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        key = self.config.resolve_key()
        if key:
            headers["x-goog-api-key"] = key
        return headers

    def _url(self, model: str) -> str:
        return f"{self.config.base_url.rstrip('/')}/models/{model}:generateContent"

    def complete_json(self, system: str, user: str, schema: dict[str, Any], *, model: str | None = None) -> LLMResult:
        chosen = model or self.config.model
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": self.config.max_output_tokens,
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
            },
        }
        try:
            payload = self._post(self._url(chosen), self._headers(), body)
        except LLMError as exc:
            if exc.status != 400:
                raise
            del body["generationConfig"]["responseJsonSchema"]
            body["contents"][0]["parts"][0]["text"] = _schema_in_prompt(user, schema)
            payload = self._post(self._url(chosen), self._headers(), body)
        return _gemini_result(payload, chosen)

    def complete_text(self, system: str, user: str, *, model: str | None = None) -> LLMResult:
        chosen = model or self.config.model
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": self.config.max_output_tokens},
        }
        return _gemini_result(self._post(self._url(chosen), self._headers(), body), chosen)


def _gemini_result(payload: dict[str, Any], model: str) -> LLMResult:
    try:
        parts = payload["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("unexpected generateContent response shape") from exc
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    usage = payload.get("usageMetadata") or {}
    return LLMResult(
        text=text,
        usage=Usage(int(usage.get("promptTokenCount") or 0), int(usage.get("candidatesTokenCount") or 0)),
        model=model,
    )


# -- the fake -----------------------------------------------------------------------------

_MARKER: Final[re.Pattern[str]] = re.compile(r"^\[(b\d+)\] ", re.MULTILINE)
_PROPER: Final[re.Pattern[str]] = re.compile(
    r"\b[A-Z][\w&.'-]*(?:[ \t]+(?:of|and|for|the|de|&|[A-Z][\w&.'-]*)){1,7}"
)
_TRAILING_CONNECTOR: Final[re.Pattern[str]] = re.compile(r"(?:[ \t]+(?:of|and|for|the|de|&))+$")
_SENTENCE_END: Final[re.Pattern[str]] = re.compile(r"(?<=\w{5})\.\s")
_TRAILING_PERIOD: Final[re.Pattern[str]] = re.compile(r"(?<=\w{4})\.$")
"""A period after a word of five or more letters ends a sentence; `Dr.` and `B.E.` do not."""
_MONEY: Final[re.Pattern[str]] = re.compile(r"(?:₹|Rs\.?|INR|USD|\$|€|£)\s?[\d,]+(?:\.\d+)?(?:\s?(?:per|/)\s?(?:year|month|semester|annum))?", re.IGNORECASE)
_DATE: Final[re.Pattern[str]] = re.compile(r"\b(?:\d{1,2}\s+)?(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}?,?\s*\d{4}\b|\b\d{4}-\d{2}-\d{2}\b")
_EMAIL: Final[re.Pattern[str]] = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE: Final[re.Pattern[str]] = re.compile(r"\+?\d[\d\s-]{8,}\d")
_QUESTION_STOP: Final[frozenset[str]] = frozenset({"what", "which", "who", "whom", "when", "where", "how", "does", "the", "for", "and", "are", "is", "of", "in", "on", "to", "do", "much", "many", "there"})
_STOP: Final[frozenset[str]] = frozenset({"The", "This", "These", "Those", "Our", "Your", "Their", "It", "In", "On", "At", "For", "From", "With", "By", "About", "Contact", "Read", "Learn", "More", "Click", "Here"})


class FakeProvider:
    """A deterministic stand-in with no network and no key.

    For extraction it reads the `[bN]` blocks out of the prompt and returns, as the model
    would, capitalised multi-word names as entities, money/date/email/phone strings as
    attributes of the nearest entity, and a `mentioned_with` relation between the first two
    entities in a block -- every quote copied verbatim from the block, so verification
    passes. For answering it cites every evidence line it was given, one sentence each.

    `scripted` overrides the next responses in order (a test hands it a fabricated quote to
    watch the extractor reject it). `calls` counts requests, which is how the cache test
    proves the second build made none.
    """

    def __init__(self, config: ProviderConfig | None = None, *, scripted: list[str] | None = None, fabricate: bool = False) -> None:
        self.config = config or ProviderConfig(provider="fake", base_url="fake://", model="fake-1")
        self.scripted = list(scripted or [])
        self.fabricate = fabricate
        self.calls = 0
        self.prompts: list[str] = []
        self.on_call: Callable[[str], None] | None = None

    def complete_json(self, system: str, user: str, schema: dict[str, Any], *, model: str | None = None) -> LLMResult:  # noqa: ARG002
        self.calls += 1
        self.prompts.append(user)
        if self.on_call:
            self.on_call(user)
        text = self.scripted.pop(0) if self.scripted else json.dumps(self._extract(user))
        return LLMResult(text=text, usage=Usage(len(system + user) // 4, len(text) // 4), model=model or self.config.model)

    def complete_text(self, system: str, user: str, *, model: str | None = None) -> LLMResult:
        self.calls += 1
        self.prompts.append(user)
        if self.on_call:
            self.on_call(user)
        text = self.scripted.pop(0) if self.scripted else self._answer(user)
        return LLMResult(text=text, usage=Usage(len(system + user) // 4, len(text) // 4), model=model or self.config.model)

    # -- extraction ---------------------------------------------------------------------

    def _extract(self, user: str) -> dict[str, Any]:
        section = user.split("Section blocks:", 1)[-1].split("\n\nReturn the JSON object.")[0]
        parts = _MARKER.split(section)
        # `split` with one group yields [prefix, marker, text, marker, text, ...].
        blocks = [(parts[i], parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]
        known = re.findall(r"^- (.+?) \(([A-Za-z]+)\)$", user, re.MULTILINE)
        known_names = {name for name, _ in known}
        entities: dict[str, dict[str, Any]] = {}
        relations: list[dict[str, Any]] = []
        for marker, text in blocks:
            names: list[str] = []
            found = [
                _TRAILING_PERIOD.sub("", _TRAILING_CONNECTOR.sub("", _SENTENCE_END.split(m.group(0))[0]).strip(",;:"))
                for m in _PROPER.finditer(text)
            ]
            for candidate in list(known_names) + found:
                if candidate in text and candidate.split()[0] not in _STOP and candidate not in names and len(candidate) > 3:
                    names.append(candidate)
            for name in names:
                quote = _window(text, name)
                entry = entities.setdefault(
                    name,
                    {"name": name, "type": _guess_type(name, known), "aliases": [], "attributes": [], "mentions": []},
                )
                entry["mentions"].append({"block": marker, "quote": quote})
            if names:
                owner = names[0]
                for key, pattern in (("price", _MONEY), ("date", _DATE), ("email", _EMAIL), ("phone", _PHONE)):
                    for m in pattern.finditer(text):
                        value = m.group(0).strip().rstrip(".,;:")
                        if len(value) < 4:
                            continue
                        quote = _window(text, value)
                        if self.fabricate:
                            quote = "this sentence is not on the page"
                        entities[owner]["attributes"].append({"key": key, "value": value, "unit": _unit(key, value), "block": marker, "quote": quote})
            if len(names) >= 2:
                relations.append({
                    "subject": names[0],
                    "predicate": "mentioned_with",
                    "object": names[1],
                    "fact": f"{names[0]} is mentioned with {names[1]}.",
                    "evidence": [{"block": marker, "quote": _window(text, names[1])}],
                })
        return {"entities": list(entities.values()), "relations": relations}

    # -- answering ----------------------------------------------------------------------

    def _answer(self, user: str) -> str:
        """An extractive answer: the evidence lines that share the most words with the
        question, each cited. Deterministic, so the benchmark's CI run is repeatable."""
        question = user.split("\n", 1)[0].removeprefix("Question:").strip()
        terms = {w.lower() for w in re.findall(r"[A-Za-z0-9][\w.'-]*", question) if len(w) > 2 and w.lower() not in _QUESTION_STOP}
        lines = re.findall(r"^\[(\d+)\] .*?\"(.*?)\"\s*$", user, re.MULTILINE)
        if not lines:
            return "Not stated on this site."
        scored = []
        for n, quote in lines:
            words = {w.lower() for w in re.findall(r"[A-Za-z0-9][\w.'-]*", quote)}
            overlap = len(terms & words)
            scored.append((-overlap, int(n), quote))
        scored.sort()
        if scored[0][0] == 0:
            return "Not stated on this site."
        best = [(n, q) for neg, n, q in scored[:2] if neg < 0]
        # One sentence per citation: a stop inside the quote becomes a semicolon, so the
        # `[n]` at the end covers the whole of what was quoted.
        return " ".join(f"{re.sub(r'(?<=\w{5})[.!?]\s+', '; ', quote).rstrip('.')} [{n}]." for n, quote in best)


def _window(text: str, needle: str, *, words: int = 6) -> str:
    """A verbatim quote around `needle`: the needle plus up to `words` words either side,
    cut on word boundaries of the original text so whitespace stays exactly as written."""
    at = text.find(needle)
    if at < 0:
        return needle
    end_needle = at + len(needle)
    spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    before = [s for s, e in spans if e <= at]
    after = [e for s, e in spans if s >= end_needle]
    start = before[-words] if len(before) >= words else (before[0] if before else at)
    end = after[words - 1] if len(after) >= words else (after[-1] if after else end_needle)
    return text[start:end].strip()


def _guess_type(name: str, known: list[tuple[str, str]]) -> str:
    for known_name, known_type in known:
        if known_name == name:
            return known_type
    lowered = name.lower()
    if any(w in lowered for w in ("college", "institute", "university", "school", "ltd", "inc", "company", "trust", "department")):
        return "Organization"
    if any(w in lowered for w in ("course", "programme", "program", "b.e", "m.tech", "diploma", "bsc", "msc")):
        return "Course"
    if lowered.startswith(("dr.", "dr ", "prof", "mr", "ms", "mrs", "shri", "smt")):
        return "Person"
    return "Topic"


def _unit(key: str, value: str) -> str:
    if key == "price":
        if "₹" in value or "rs" in value.lower() or "inr" in value.lower():
            return "INR"
        if "$" in value or "usd" in value.lower():
            return "USD"
        if "€" in value:
            return "EUR"
        if "£" in value:
            return "GBP"
    return ""


def make_provider(config: ProviderConfig, *, transport: httpx.BaseTransport | None = None) -> Provider:
    if config.provider == "fake":
        return FakeProvider(config)
    if config.provider == "anthropic":
        return AnthropicProvider(config, transport=transport)
    if config.provider == "gemini":
        return GeminiProvider(config, transport=transport)
    return OpenAICompatProvider(config, transport=transport)

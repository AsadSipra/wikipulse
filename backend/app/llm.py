"""LLM client for any OpenAI-compatible endpoint, with per-feature call budgets."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Protocol

import httpx

log = logging.getLogger(__name__)


class LLMError(Exception):
    pass


class LLM(Protocol):
    async def complete_json(self, system: str, user: str) -> dict[str, Any]: ...


class RateLimiter:
    """Sliding one-minute window. `try_acquire` never blocks."""

    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.per_minute = per_minute
        self._clock = clock
        self._calls: deque[float] = deque()

    def try_acquire(self) -> bool:
        now = self._clock()
        while self._calls and now - self._calls[0] >= 60:
            self._calls.popleft()
        if len(self._calls) >= self.per_minute:
            return False
        self._calls.append(now)
        return True


# Optional: dropped for a provider that rejects them.
OPTIONAL_FIELDS: dict[str, Any] = {
    "temperature": 0.2,
    "response_format": {"type": "json_object"},
}


class OpenAICompatibleLLM:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 30.0,
        max_tokens: int = 800,
        max_concurrency: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.model = model
        self.max_tokens = max_tokens  # required by some providers; also caps cost
        self._sem = asyncio.Semaphore(max_concurrency)
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout, transport=transport
        )
        self.calls = 0
        self.failures = 0
        self.last_error: str | None = None  # shown in /health
        self.unsupported: set[str] = set()

    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        async with self._sem:
            self.calls += 1
            try:
                resp = await self._post(system, user)
                while resp.status_code == 400 and (rejected := self._rejected_optional(resp.text)):
                    # e.g. Anthropic rejects response_format, newer models reject temperature.
                    log.info("provider rejected %s; retrying without it", rejected)
                    self.unsupported.add(rejected)
                    resp = await self._post(system, user)
                if resp.is_error:
                    # The provider's message (redacted) says far more than the status.
                    raise LLMError(f"HTTP {resp.status_code}: {_provider_message(resp)}")
                text = _reply_text(resp)
                try:
                    return extract_json(text)
                except ValueError as exc:
                    # "length" means the reply hit LLM_MAX_TOKENS and was cut off.
                    raise LLMError(
                        f"bad reply: {exc} (finish_reason={_finish_reason(resp)}, {len(text)} chars)"
                    ) from None
            except LLMError as exc:
                self._fail(str(exc))
                raise
            except httpx.HTTPError as exc:
                self._fail(f"{type(exc).__name__}: network error or timeout")
                raise LLMError(str(exc)) from exc
            except ValueError as exc:  # bad body or no JSON object in the reply
                self._fail(f"bad reply: {exc}")
                raise LLMError(str(exc)) from exc

    async def _post(self, system: str, user: str) -> httpx.Response:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        for name, value in OPTIONAL_FIELDS.items():
            if name not in self.unsupported:
                body[name] = value
        return await self._client.post("/chat/completions", json=body)

    def _rejected_optional(self, error_text: str) -> str | None:
        """The optional field a 400 error complains about, if any (and not yet dropped)."""
        for name in OPTIONAL_FIELDS:
            if name not in self.unsupported and name in error_text:
                return name
        return None

    def _fail(self, message: str) -> None:
        self.failures += 1
        self.last_error = redact(message)[:200]
        log.warning("LLM call failed: %s", self.last_error)

    async def aclose(self) -> None:
        await self._client.aclose()


class Budgeted:
    """A per-feature call budget, so one feature can't use up another's calls."""

    def __init__(
        self, inner: LLM, per_minute: int, name: str, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.inner = inner
        self.name = name
        self.limiter = RateLimiter(per_minute, clock)
        self.rate_limited = 0

    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        if not self.limiter.try_acquire():
            self.rate_limited += 1
            raise LLMError(f"{self.name} budget used up for this minute")
        return await self.inner.complete_json(system, user)


def _finish_reason(resp: httpx.Response) -> Any:
    with contextlib.suppress(Exception):
        return resp.json()["choices"][0].get("finish_reason")
    return None


def _reply_text(resp: httpx.Response) -> str:
    """The reply text, or LLMError (a 200 can still have null choices or content)."""
    body = resp.json()
    choices = body.get("choices") if isinstance(body, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise LLMError("reply has no choices")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        reason = choices[0].get("finish_reason")
        raise LLMError(f"reply has no text content (finish_reason={reason})")
    return content


def _provider_message(resp: httpx.Response) -> str:
    """The error message from a provider's error body, without the rest of it."""
    try:
        body = resp.json()
        error = body.get("error") if isinstance(body, dict) else None
        message = error.get("message") if isinstance(error, dict) else error
        if isinstance(message, str):
            return message
    except ValueError:
        pass
    return resp.text


_SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{6,}|Bearer\s+\S+|[A-Za-z0-9_-]{32,})")


def redact(text: str) -> str:
    """Mask anything that looks like a key or token before it is logged or shown."""
    return _SECRET.sub("[redacted]", " ".join(text.split()))


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating ``` fences and surrounding prose."""
    text = text.strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object in model output") from None
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model output is not a JSON object")
    return value


def untrusted(label: str, text: str, limit: int = 500) -> str:
    """Wrap editor-written text in a marked data block (prompt-injection defence)."""
    clean = text.replace("<<<", "").replace(">>>", "")[:limit]
    return f"<<<{label}\n{clean}\n>>>"

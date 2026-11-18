"""Thin LLM client.

Talks to any OpenAI-compatible chat endpoint: Ollama locally
(http://localhost:11434/v1), OpenAI, or most hosted providers. Switching
provider is a config change (LLM_BASE_URL / LLM_API_KEY / LLM_MODEL), not a
code change.

Two guards keep LLM usage predictable:
  * per-feature call budgets (calls per minute, see `Budgeted`), so a busy
    stream can't turn into a flood of calls and one feature can't use up
    another's calls;
  * a concurrency cap, so a slow model can't pile up requests.
These limit calls in this process, not money: a hard spending cap belongs at
the provider. When a budget says no, callers fall back to non-LLM behaviour
instead of waiting.
"""

from __future__ import annotations

import asyncio
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


# Sent when the provider accepts them; dropped per provider when it doesn't.
OPTIONAL_FIELDS: dict[str, Any] = {
    "temperature": 0.2,  # steadier summaries and verdicts
    "response_format": {"type": "json_object"},  # stricter JSON where supported
}


class OpenAICompatibleLLM:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 30.0,
        max_tokens: int = 300,
        max_concurrency: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.model = model
        self.max_tokens = max_tokens  # some providers (e.g. Anthropic) require it; it also caps cost
        self._sem = asyncio.Semaphore(max_concurrency)
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout, transport=transport
        )
        self.calls = 0
        self.failures = 0
        self.last_error: str | None = None  # shown in /health so failures are diagnosable
        # Optional request fields this provider has rejected; they are not sent again.
        self.unsupported: set[str] = set()

    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        async with self._sem:
            self.calls += 1
            try:
                resp = await self._post(system, user)
                while resp.status_code == 400 and (rejected := self._rejected_optional(resp.text)):
                    # Providers disagree on optional fields: Anthropic's compatible
                    # endpoint rejects response_format={"type": "json_object"}, and
                    # newer models reject temperature. Neither is essential (the
                    # prompts ask for JSON and extract_json copes with prose), so
                    # drop the field for this provider and retry.
                    log.info("provider rejected %s; retrying without it", rejected)
                    self.unsupported.add(rejected)
                    resp = await self._post(system, user)
                if resp.is_error:
                    # Keep the provider's own message: "model not found" is far
                    # more useful than the status alone. It is redacted and
                    # shortened before it is logged or shown in /health.
                    raise LLMError(f"HTTP {resp.status_code}: {_provider_message(resp)}")
                return extract_json(_reply_text(resp))
            except LLMError as exc:
                self._fail(str(exc))
                raise
            except httpx.HTTPError as exc:
                self._fail(f"{type(exc).__name__}: network error or timeout")
                raise LLMError(str(exc)) from exc
            except ValueError as exc:  # unparseable body or no JSON object in the reply
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
    """A per-feature call budget in front of a shared client.

    Vandalism review gets its own budget and so does Pulse: a burst of
    suspicious edits can use up the vandalism budget but never stops the
    trend summary from refreshing.
    """

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


def _reply_text(resp: httpx.Response) -> str:
    """The assistant message text from an OpenAI-style reply, or LLMError.

    A 200 can still carry a malformed body (null choices, null content), and
    that must count as a failed call so the caller falls back."""
    body = resp.json()
    choices = body.get("choices") if isinstance(body, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise LLMError("reply has no choices")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise LLMError("reply has no text content")
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
    """Parse a JSON object from model output.

    Smaller local models sometimes wrap JSON in ``` fences or add a sentence
    around it even when asked not to, so we tolerate both.
    """
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
    """Wrap user-generated text (edit comments, diffs) so the model treats it
    as data. Wikipedia comments are written by anyone, so they are a prompt-
    injection vector; the system prompts tell the model to ignore instructions
    inside these blocks."""
    clean = text.replace("<<<", "").replace(">>>", "")[:limit]
    return f"<<<{label}\n{clean}\n>>>"

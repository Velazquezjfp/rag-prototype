"""One small httpx client for the OpenAI-compatible endpoints (chat completions, embeddings), JSON and SSE.

Copied from docling-graph-service ``llm_http.py`` (that package pulls torch, so it is not imported) with two changes:
``trust_env=False`` — the endpoints are loopback/SSH tunnels and a corporate ``HTTPS_PROXY`` in the environment must
never capture them — and ``post_sse()`` for streamed chat completions.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from typing import Any

import httpx

log = logging.getLogger(__name__)

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMHTTPError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class LLMClient:
    """Bearer-authenticated JSON client with bounded retries (429/5xx/timeouts/connect errors)."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        timeout_s: float,
        *,
        max_attempts: int = 3,
        backoff_s: float = 1.0,
        transport: httpx.BaseTransport | None = None,
    ):
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.base_url = base_url.rstrip("/")
        self.max_attempts = max(1, max_attempts)
        self.backoff_s = backoff_s
        self._client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            transport=transport,
            trust_env=False,
        )

    def close(self) -> None:
        self._client.close()

    def post_json(self, path: str, payload: dict[str, Any], *, timeout_s: float | None = None) -> dict[str, Any]:
        last: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                kwargs: dict[str, Any] = {"json": payload}
                if timeout_s is not None:
                    kwargs["timeout"] = httpx.Timeout(timeout_s, connect=10.0)
                resp = self._client.post(path, **kwargs)
                if resp.status_code in RETRY_STATUS and attempt < self.max_attempts:
                    last = LLMHTTPError(f"{path}: HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)
                    self._sleep(attempt)
                    continue
                if resp.status_code >= 400:
                    raise LLMHTTPError(f"{path}: HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)
                return resp.json()
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last = exc
                if attempt < self.max_attempts:
                    self._sleep(attempt)
                    continue
        raise LLMHTTPError(f"{path}: giving up after {self.max_attempts} attempts: {last}") from last

    def post_sse(self, path: str, payload: dict[str, Any], *, timeout_s: float | None = None) -> Iterator[dict[str, Any]]:
        """POST and yield every ``data:`` JSON object of the server-sent event stream until ``[DONE]``.

        Retries apply only until the response headers arrive; once tokens flow, an error is raised as is."""
        last: Exception | None = None
        timeout = httpx.Timeout(timeout_s, connect=10.0) if timeout_s is not None else None
        for attempt in range(1, self.max_attempts + 1):
            try:
                kwargs: dict[str, Any] = {"json": payload}
                if timeout is not None:
                    kwargs["timeout"] = timeout
                with self._client.stream("POST", path, **kwargs) as resp:
                    if resp.status_code in RETRY_STATUS and attempt < self.max_attempts:
                        body = resp.read()
                        last = LLMHTTPError(f"{path}: HTTP {resp.status_code}: {body[:300]!r}", resp.status_code)
                        self._sleep(attempt)
                        continue
                    if resp.status_code >= 400:
                        body = resp.read()
                        raise LLMHTTPError(
                            f"{path}: HTTP {resp.status_code}: {body[:300].decode('utf-8', 'replace')}",
                            resp.status_code,
                        )
                    yield from _parse_sse(resp.iter_lines())
                    return
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last = exc
                if attempt < self.max_attempts:
                    self._sleep(attempt)
                    continue
        raise LLMHTTPError(f"{path}: giving up after {self.max_attempts} attempts: {last}") from last

    def get_json(self, path: str, *, timeout_s: float = 10.0) -> dict[str, Any]:
        resp = self._client.get(path, timeout=timeout_s)
        if resp.status_code >= 400:
            raise LLMHTTPError(f"{path}: HTTP {resp.status_code}", resp.status_code)
        return resp.json()

    def probe(self) -> str:
        """Cheap liveness check: 'ok', or the error text."""
        try:
            self.get_json("/models", timeout_s=5.0)
            return "ok"
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            return f"unreachable: {exc}"[:200]

    def _sleep(self, attempt: int) -> None:
        delay = self.backoff_s * (2 ** (attempt - 1))
        log.warning("LLM endpoint retry %d/%d in %.1fs", attempt, self.max_attempts, delay)
        time.sleep(delay)


def _parse_sse(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            log.debug("skipping non-JSON SSE line: %r", data[:120])

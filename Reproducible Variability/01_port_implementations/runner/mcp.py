"""Tiny wrapper that adapts the Medeloop MCP tool surface into a
synchronous-looking call from the harness.

The harness calls `session.query("…")` and gets back a Python dict that
either contains the query result or raises. Internally we always go through
`execute_query` → `poll_query_results` with a capped exponential back-off.

This module intentionally has no knowledge of the Medeloop MCP tool *names*
themselves; the caller injects two callables (`execute`, `poll`) so the
harness can be exercised under a mock during development or dry-runs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class _ExecuteCallable(Protocol):
    def __call__(self, *, user_id: str, medebook_id: str, query: str) -> Any: ...


class _PollCallable(Protocol):
    def __call__(
        self, *, async_query_id: str, user_id: str, medebook_id: str
    ) -> Any: ...


@dataclass
class MedeloopSession:
    """Holds the (user_id, medebook_id) pair + the two MCP callables."""

    user_id: str
    medebook_id: str
    execute: _ExecuteCallable
    poll: _PollCallable
    initial_poll_s: float = 1.0
    max_poll_s: float = 5.0
    max_total_s: float = 180.0
    log: list[dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------

    def query(self, prompt: str) -> dict[str, Any]:
        """Fire a single `execute_query`, poll until it resolves, return the
        raw MCP response dict."""
        if len(prompt) > 350:
            # 350 char cap is a performance/quality rule, not a hard error in
            # the MCP, but we log it so the harness can tune chunk sizes.
            self.log.append(
                {"event": "long_prompt", "len": len(prompt), "head": prompt[:120]}
            )
        resp = self.execute(
            user_id=self.user_id, medebook_id=self.medebook_id, query=prompt
        )
        aid = _extract_async_id(resp)
        if aid is None:
            # Sometimes the MCP returns a synchronous answer
            return resp
        return self._poll_until_done(aid)

    # ------------------------------------------------------------------

    def _poll_until_done(self, aid: str) -> dict[str, Any]:
        wait = self.initial_poll_s
        start = time.monotonic()
        while True:
            resp = self.poll(
                async_query_id=aid,
                user_id=self.user_id,
                medebook_id=self.medebook_id,
            )
            status = _extract_status(resp)
            if status in {"done", "completed", "ready", "success"}:
                return resp
            if status in {"error", "failed"}:
                raise RuntimeError(f"Medeloop query {aid} failed: {resp}")
            elapsed = time.monotonic() - start
            if elapsed > self.max_total_s:
                raise TimeoutError(
                    f"Medeloop query {aid} not done after {elapsed:.0f}s"
                )
            time.sleep(wait)
            wait = min(wait * 1.7, self.max_poll_s)


def _extract_async_id(resp: Any) -> str | None:
    if isinstance(resp, dict):
        for k in ("async_query_id", "id", "query_id"):
            if k in resp:
                return resp[k]
    return None


def _extract_status(resp: Any) -> str | None:
    if isinstance(resp, dict):
        for k in ("status", "state"):
            if k in resp:
                return str(resp[k]).lower()
    return None

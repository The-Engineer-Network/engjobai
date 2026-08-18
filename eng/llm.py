"""Groq client — used only for the jobs that rules could not decide.

Two things this module guarantees:

1. It NEVER blocks the run. If the key is missing, the tier is exhausted, or
   Groq is having a bad day, every call returns None and the pipeline falls
   back to rules. A digest with rules-only classification is still a good
   digest; a crashed cron job is not.
2. It respects the free tier. 30 requests/min and 6,000 tokens/min are real
   limits, so calls are throttled and batched rather than fired in a loop.
"""

from __future__ import annotations

import json
import os
import time

import httpx

ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

# Groq retired the Llama models. Verified available as of Aug 2026:
#   openai/gpt-oss-20b   fastest, cheapest, correct on this task  <- default
#   openai/gpt-oss-120b  stronger, ~same latency, costs more
#   qwen/qwen3.6-27b     also correct, slightly slower
# Check the current list any time:
#   curl -H "Authorization: Bearer $GROQ_API_KEY" https://api.groq.com/openai/v1/models
DEFAULT_MODEL = "openai/gpt-oss-20b"

# Free tier limits, measured against the live API (Aug 2026):
#   30 requests/min  and  8,000 tokens/min
#
# The token budget is what actually bites. Groq reserves `max_tokens` up front
# rather than charging actual usage, so a call asking for 1,500 output tokens
# books ~2,500 against the window even though it really spends ~350. Throttling
# on requests alone therefore looks safe and still earns a wall of 429s.
TPM_BUDGET = 7000    # of 8,000, leaving headroom
MIN_INTERVAL = 2.0   # floor, keeps us under 30 RPM regardless
TIMEOUT = 45.0


class Groq:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self.model = model or os.getenv("GROQ_MODEL", DEFAULT_MODEL)
        self._last_call = 0.0
        self._window: list[tuple[float, int]] = []   # (timestamp, tokens reserved)
        self.calls = 0
        self.failures = 0
        # Failures are counted by reason, not just totalled. A silent client
        # that only says "8 failed" cannot be debugged.
        self.errors: dict[str, int] = {}

    def _note(self, reason: str) -> None:
        self.failures += 1
        self.errors[reason] = self.errors.get(reason, 0) + 1

    def error_summary(self) -> str:
        if not self.errors:
            return "none"
        return ", ".join(f"{k} x{v}" for k, v in
                         sorted(self.errors.items(), key=lambda kv: -kv[1]))

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _throttle(self, cost: int) -> None:
        """Hold until `cost` tokens fit inside the rolling 60-second window."""
        # Request-rate floor.
        gap = time.monotonic() - self._last_call
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)

        # Token-rate ceiling.
        while True:
            now = time.monotonic()
            self._window = [(t, n) for t, n in self._window if now - t < 60.0]
            used = sum(n for _, n in self._window)
            if used + cost <= TPM_BUDGET or not self._window:
                break
            # Sleep until the oldest reservation ages out of the window.
            time.sleep(max(0.5, 60.0 - (now - self._window[0][0]) + 0.25))

        self._window.append((time.monotonic(), cost))
        self._last_call = time.monotonic()

    def ask_json(self, system: str, user: str, max_tokens: int = 1500) -> dict | None:
        """Return parsed JSON, or None on any failure. Never raises.

        max_tokens must stay generous. Every model Groq now offers is a
        reasoning model that spends tokens thinking before it answers; at 900
        they run out mid-object and Groq rejects the whole call with
        "Failed to validate JSON". 1500 is comfortably clear of that.
        """
        if not self.enabled:
            return None

        # ~4 characters per token is close enough to budget against.
        cost = (len(system) + len(user)) // 4 + max_tokens
        self._throttle(cost)
        try:
            r = httpx.post(
                ENDPOINT,
                timeout=TIMEOUT,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "temperature": 0,
                    "max_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
            if r.status_code == 429:
                # Respect Groq's own backoff hint when it sends one.
                wait = float(r.headers.get("retry-after", 8))
                time.sleep(min(wait, 30))
                self._note("429 rate limit")
                return None
            if r.status_code == 400 and "json" in r.text.lower():
                # The model ran out of room mid-object. Retry once with more
                # headroom before giving up — reasoning models are variable.
                if max_tokens < 3000:
                    return self.ask_json(system, user, max_tokens=3000)
                self._note("400 invalid JSON")
                return None
            if r.status_code != 200:
                self._note(f"HTTP {r.status_code}")
                return None

            # Trust Groq's own number over our estimate when it is running low.
            remaining = r.headers.get("x-ratelimit-remaining-tokens")
            if remaining and remaining.isdigit() and int(remaining) < 2000:
                time.sleep(12)
            self.calls += 1
            return json.loads(r.json()["choices"][0]["message"]["content"])
        except Exception as exc:
            self._note(type(exc).__name__)
            return None

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

# Free tier: 30 RPM. We stay meaningfully under it.
MIN_INTERVAL = 2.5   # seconds between calls
TIMEOUT = 45.0


class Groq:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self.model = model or os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        self._last_call = 0.0
        self.calls = 0
        self.failures = 0

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last_call
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)
        self._last_call = time.monotonic()

    def ask_json(self, system: str, user: str, max_tokens: int = 900) -> dict | None:
        """Return parsed JSON, or None on any failure. Never raises."""
        if not self.enabled:
            return None
        self._throttle()
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
                # Tier exhausted for now. Back off once, then give up quietly.
                time.sleep(8)
                self.failures += 1
                return None
            r.raise_for_status()
            self.calls += 1
            return json.loads(r.json()["choices"][0]["message"]["content"])
        except Exception:
            self.failures += 1
            return None

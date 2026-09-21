"""Pluggable notification backends. ntfy.sh is the default.

Secrets (ntfy topic, webhook URLs) come from environment variables /
GitHub Actions secrets -- never hardcode them here.
"""

from __future__ import annotations

import os
from typing import Protocol

import httpx

DISCLAIMER = (
    "Dining hall data may be incomplete or wrong -- confirm allergens "
    "with dining hall staff before eating."
)


class Notifier(Protocol):
    def send(self, title: str, message: str) -> None: ...


class NtfyNotifier:
    """Sends a push notification via ntfy.sh."""

    def __init__(self, topic: str | None = None, base_url: str = "https://ntfy.sh"):
        self.topic = topic or os.environ.get("NTFY_TOPIC")
        self.base_url = base_url.rstrip("/")

    def send(self, title: str, message: str) -> None:
        if not self.topic:
            raise ValueError("No ntfy topic configured (set NTFY_TOPIC or config.toml)")
        body = f"{message}\n\n{DISCLAIMER}"
        httpx.post(
            f"{self.base_url}/{self.topic}",
            data=body.encode("utf-8"),
            headers={"Title": title},
            timeout=10.0,
        )


class ConsoleNotifier:
    """Fallback notifier that just prints -- useful for local runs/tests."""

    def send(self, title: str, message: str) -> None:
        print(f"=== {title} ===")
        print(message)
        print(DISCLAIMER)

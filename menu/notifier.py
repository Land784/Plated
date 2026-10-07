"""Pluggable notification backends. ntfy.sh is the default.

Secrets (ntfy topic, webhook URLs) come from environment variables /
GitHub Actions secrets -- never hardcode them here.

The disclaimer is appended here rather than by the message builder, so
no path can send food suggestions without it.
"""

from __future__ import annotations

import os
from typing import Protocol

import httpx

DISCLAIMER = "Data may be incomplete; confirm allergens with staff."


def compose_body(message: str) -> str:
    """The body exactly as sent: the message, then the disclaimer last."""
    return f"{message}\n\n{DISCLAIMER}"


class Notifier(Protocol):
    def send(
        self,
        title: str,
        message: str,
        *,
        tags: list[str] | None = None,
        click: str | None = None,
    ) -> None: ...


class NtfyNotifier:
    """Sends a push notification via ntfy.sh."""

    def __init__(self, topic: str | None = None, base_url: str = "https://ntfy.sh"):
        self.topic = topic or os.environ.get("NTFY_TOPIC")
        self.base_url = base_url.rstrip("/")

    def send(
        self,
        title: str,
        message: str,
        *,
        tags: list[str] | None = None,
        click: str | None = None,
    ) -> None:
        if not self.topic:
            raise ValueError("No ntfy topic configured (set NTFY_TOPIC or config.toml)")
        # ntfy reads every header from a query parameter of the same name
        # too. Titles contain "·", and httpx only sends ASCII headers, so
        # the query string (UTF-8, percent-encoded) is the one that works.
        params = {"title": title}
        if tags:
            params["tags"] = ",".join(tags)
        if click:
            params["click"] = click
        httpx.post(
            f"{self.base_url}/{self.topic}",
            params=params,
            content=compose_body(message).encode("utf-8"),
            timeout=10.0,
        )


class ConsoleNotifier:
    """Fallback notifier that just prints -- useful for local runs/tests."""

    def send(
        self,
        title: str,
        message: str,
        *,
        tags: list[str] | None = None,
        click: str | None = None,
    ) -> None:
        print(f"=== {title} ===")
        headers = [f"tags: {','.join(tags)}"] if tags else []
        if click:
            headers.append(f"click: {click}")
        if headers:
            print(" · ".join(headers))
        print(compose_body(message))

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
# Sets off each hall's full menu and the footer. Box drawing is safe in
# a proportional font as long as nothing has to line up with it.
SEPARATOR = "─" * 10


def compose_body(message: str, link: str | None = None) -> str:
    """The body exactly as sent: the message, then the footer.

    The footer sits under a separator: an optional "Full menu: <url>"
    line, then the disclaimer, always last. The URL is plain text so the
    phone makes it tappable; tapping the push itself opens nothing.
    """
    footer = [SEPARATOR, *([f"Full menu: {link}"] if link else []), DISCLAIMER]
    return f"{message}\n\n" + "\n".join(footer)


class Notifier(Protocol):
    def send(
        self,
        title: str,
        message: str,
        *,
        tags: list[str] | None = None,
        link: str | None = None,
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
        link: str | None = None,
    ) -> None:
        if not self.topic:
            raise ValueError("No ntfy topic configured (set NTFY_TOPIC or config.toml)")
        # ntfy reads every header from a query parameter of the same name
        # too. Titles contain "·", and httpx only sends ASCII headers, so
        # the query string (UTF-8, percent-encoded) is the one that works.
        # No "click": the owner doesn't want a tap to open a page.
        params = {"title": title}
        if tags:
            params["tags"] = ",".join(tags)
        response = httpx.post(
            f"{self.base_url}/{self.topic}",
            params=params,
            content=compose_body(message, link).encode("utf-8"),
            timeout=10.0,
        )
        # Not raise_for_status(): its message includes the URL, and so the
        # topic, which would then be printed in the dispatch problem log.
        if response.is_error:
            raise RuntimeError(f"ntfy returned HTTP {response.status_code}")


class ConsoleNotifier:
    """Fallback notifier that just prints -- useful for local runs/tests."""

    def send(
        self,
        title: str,
        message: str,
        *,
        tags: list[str] | None = None,
        link: str | None = None,
    ) -> None:
        print(f"=== {title} ===")
        if tags:
            print(f"tags: {','.join(tags)}")
        print(compose_body(message, link))

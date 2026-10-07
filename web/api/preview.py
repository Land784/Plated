"""POST /api/preview: the push for unsaved settings, as a Vercel Python function.

A thin adapter: everything (validation, the rate limit, reading menus
from Supabase and rendering) is menu.preview.handle_request, which is
tested in this repo's tests/test_preview.py. The `menu` package comes
from requirements.txt. Reads SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY;
there is no secret key on Vercel.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler

from menu.preview import MAX_BODY_BYTES, RateLimiter, client_ip, handle_request

# Module level, so it lasts as long as the function instance does.
LIMITER = RateLimiter()


class handler(BaseHTTPRequestHandler):  # noqa: N801 - the name Vercel looks for
    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("content-length") or 0)
        except ValueError:
            length = 0
        # Read one byte past the cap so an oversized body is still caught.
        body = self.rfile.read(max(0, min(length, MAX_BODY_BYTES + 1)))
        ip = client_ip(
            self.headers.get("x-forwarded-for"), self.headers.get("x-real-ip"), self.client_address
        )
        status, payload = handle_request(body, ip, limiter=LIMITER, env=os.environ)
        self._reply(status, payload)

    def do_GET(self) -> None:  # noqa: N802
        self._reply(405, {"error": "use POST"}, allow="POST")

    def _reply(self, status: int, payload: dict, allow: str | None = None) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if allow:
            self.send_header("Allow", allow)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # request lines would log client IPs

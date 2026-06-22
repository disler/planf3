"""Localhost HTTPServer that captures the OAuth callback.

Runs a single-shot HTTPServer on 127.0.0.1:<port> in a daemon thread.
The handler validates the CSRF state, captures the authorization code,
responds with a friendly HTML page, and shuts the server down.

Tries the requested port first, then the fallback (Codex defaults:
1455, 1457). Raises PortInUse if neither binds.
"""
from __future__ import annotations

import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

from . import errors as err

CALLBACK_PATH = "/auth/callback"
HTML_SUCCESS = """<!doctype html>
<html><head><meta charset="utf-8"><title>Login complete</title></head>
<body style="font-family:-apple-system,Segoe UI,sans-serif;background:#0b0b0f;color:#e7e7ea;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
  <div style="text-align:center;padding:2rem;border-radius:12px;background:#16161d;max-width:420px">
    <h1 style="color:#7cf07c;margin:0 0 .5rem">Login complete</h1>
    <p style="margin:0;color:#a0a0aa">You can close this tab and return to the terminal.</p>
  </div>
</body></html>"""

HTML_FAILURE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Login failed</title></head>
<body style="font-family:-apple-system,Segoe UI,sans-serif;background:#0b0b0f;color:#e7e7ea;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
  <div style="text-align:center;padding:2rem;border-radius:12px;background:#16161d;max-width:420px">
    <h1 style="color:#ff6b6b;margin:0 0 .5rem">{title}</h1>
    <p style="margin:0;color:#a0a0aa">{message}</p>
  </div>
</body></html>"""


def _try_bind(host: str, port: int) -> HTTPServer | None:
    try:
        server = HTTPServer((host, port), _CallbackHandler)
        return server
    except OSError:
        return None


class _CallbackHandler(BaseHTTPRequestHandler):
    # Populated by _CallbackHTTPServer before serve_forever().
    expected_state: str = ""
    captured: dict[str, str | None] = {"code": None, "state": None, "error": None}
    on_done: Callable[[], None] | None = None

    def log_message(self, format: str, *args: object) -> None:  # silence stderr noise
        return

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler signature)
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        code = (params.get("code") or [None])[0]
        state = (params.get("state") or [None])[0]
        error = (params.get("error") or [None])[0]
        self.captured["code"] = code
        self.captured["state"] = state
        self.captured["error"] = error
        if error:
            self._respond(400, "Login failed", f"Provider returned: {error}")
        elif not code:
            self._respond(400, "Login failed", "No authorization code in callback URL.")
        elif not state or state != self.expected_state:
            self._respond(400, "Login failed", "State mismatch — possible CSRF attempt.")
        else:
            self._respond(200, "Login complete", "You can close this tab and return to the terminal.")
        if self.on_done is not None:
            try:
                self.on_done()
            except Exception:
                pass

    def _respond(self, code: int, title: str, message: str) -> None:
        body = HTML_FAILURE.format(title=title, message=message).encode("utf-8") \
            if code != 200 else HTML_SUCCESS.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _CallbackHTTPServer:
    """Wraps HTTPServer with explicit lifecycle control."""

    def __init__(self, host: str, port: int, expected_state: str) -> None:
        self.host = host
        self.port = port
        self.server = HTTPServer((host, port), _CallbackHandler)
        # Inject shared state into the handler class.
        _CallbackHandler.expected_state = expected_state
        _CallbackHandler.captured = {"code": None, "state": None, "error": None}
        self._done = threading.Event()
        _CallbackHandler.on_done = self._done.set
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def captured(self) -> dict[str, str | None]:
        return _CallbackHandler.captured

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    def start(self) -> None:
        self._thread.start()

    def wait(self, timeout: float) -> bool:
        return self._done.wait(timeout=timeout)

    def stop(self) -> None:
        try:
            self.server.shutdown()
        except Exception:
            pass
        try:
            self.server.server_close()
        except Exception:
            pass
        self._thread.join(timeout=2)


def start_callback_server(
    *,
    expected_state: str,
    host: str = "127.0.0.1",
    primary_port: int = 1455,
    fallback_port: int = 1457,
) -> tuple[_CallbackHTTPServer, int]:
    """Bind a localhost server. Tries primary then fallback. Returns (server, port)."""
    for port in (primary_port, fallback_port):
        try:
            server = HTTPServer((host, port), _CallbackHandler)
            wrapper = _CallbackHTTPServer.__new__(_CallbackHTTPServer)
            wrapper.host = host
            wrapper.server = server
            wrapper._done = threading.Event()
            _CallbackHandler.expected_state = expected_state
            _CallbackHandler.captured = {"code": None, "state": None, "error": None}
            _CallbackHandler.on_done = wrapper._done.set
            wrapper._thread = threading.Thread(target=server.serve_forever, daemon=True)
            return wrapper, port
        except OSError:
            continue
    raise err.PortInUse(
        f"Could not bind callback server to {host}:{primary_port} or {host}:{fallback_port}"
    )
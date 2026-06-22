"""
Shared helpers for ChatGPT-Plus OAuth image generation via the Codex Responses API.

Used by both generate_gpt_image.py and edit_gpt_image.py in this directory.
The Codex Responses endpoint (https://chatgpt.com/backend-api/codex/responses)
accepts ChatGPT-Plus OAuth bearer tokens (the JWT stored in OPENAI_API_KEY
by hermes-oauth-codex login) and routes through the image_generation tool —
same path Hermes's plugins/image_gen/openai-codex/ uses, just self-contained.

NOT invoked directly. Import as:  from _codex_common import ...
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator

from dotenv import load_dotenv

# Load .env from the directory the calling script is run from (matches planf3
# convention — the .env sits next to scripts/ in ~/.claude/skills/planf3/).
load_dotenv(Path.cwd() / ".env")

CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
CODEX_CHAT_MODEL = "gpt-5.5"
IMAGE_MODEL = "gpt-image-2"
RESPONSES_PATH = "/responses"

# Default refresh window: 48 hours before exp. The OAuth access token expires
# ~10 days after login; refreshing 2 days early leaves margin for retries.
DEFAULT_REFRESH_SKEW_SECONDS = 48 * 3600


def read_token() -> str:
    """Read the OAuth bearer token from OPENAI_API_KEY (or .env)."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY environment variable not set. "
            "Run `python -m hermes_oauth_openai_codex login` to populate it, "
            "or set it manually in .env."
        )
    return api_key


def jwt_claims(token: str) -> dict[str, Any] | None:
    """Decode the JWT payload and return the claims dict, or None on any failure."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")))
    except Exception:
        return None


def jwt_exp(token: str) -> int | None:
    """Return the JWT `exp` claim as epoch seconds, or None."""
    claims = jwt_claims(token)
    if not isinstance(claims, dict):
        return None
    exp = claims.get("exp")
    return int(exp) if isinstance(exp, (int, float)) else None


def chatgpt_account_id(token: str) -> str | None:
    """Extract chatgpt_account_id from the JWT for the Cloudflare ChatGPT-Account-ID header."""
    claims = jwt_claims(token)
    if not isinstance(claims, dict):
        return None
    acct = claims.get("https://api.openai.com/auth", {})
    if isinstance(acct, dict):
        v = acct.get("chatgpt_account_id")
        if isinstance(v, str) and v:
            return v
    v = claims.get("chatgpt_account_id")
    return v if isinstance(v, str) and v else None


def cloudflare_headers(token: str) -> dict[str, str]:
    """Headers required to avoid Cloudflare 403s on chatgpt.com/backend-api/codex.

    Mirrors hermes_agent/agent/auxiliary_client.py:_codex_cloudflare_headers.
    The User-Agent and originator shape match codex_cli_rs so the Cloudflare
    WAF treats us as a first-party Codex client.
    """
    headers = {
        "User-Agent": "codex_cli_rs/0.0.0 (Hermes Agent)",
        "originator": "codex_cli_rs",
        "Accept": "text/event-stream",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    acct = chatgpt_account_id(token)
    if acct:
        headers["ChatGPT-Account-ID"] = acct
    return headers


def extract_image_b64(value: Any) -> str | None:
    """Recursively find the final image b64 inside an SSE event payload.

    The Codex Responses API emits image_generation_call events with the
    completed image in `result` and intermediate partials in
    `partial_image_b64`. We prefer `result` when present and recurse into
    nested structures to handle wrapper shapes the server may add.
    """
    found: str | None = None
    if isinstance(value, dict):
        if value.get("type") == "image_generation_call":
            result = value.get("result")
            if isinstance(result, str) and result:
                found = result
        partial = value.get("partial_image_b64")
        if isinstance(partial, str) and partial:
            found = partial
        for child in value.values():
            nested = extract_image_b64(child)
            if nested:
                found = nested
    elif isinstance(value, list):
        for child in value:
            nested = extract_image_b64(child)
            if nested:
                found = nested
    return found


def iter_sse_json(response: Any) -> Iterator[dict[str, Any]]:
    """Yield JSON payloads from a streaming SSE response.

    No OpenAI SDK parsing — the Codex backend emits event shapes the pinned
    SDK doesn't always know about, and urllib gives us raw byte streams.
    """
    event_name: str | None = None
    data_lines: list[str] = []

    def flush() -> dict[str, Any] | None:
        nonlocal event_name, data_lines
        if not data_lines:
            event_name = None
            return None
        raw = "\n".join(data_lines).strip()
        event = event_name
        event_name = None
        data_lines = []
        if not raw or raw == "[DONE]":
            return None
        payload = json.loads(raw)
        if isinstance(payload, dict) and event and "type" not in payload:
            payload["type"] = event
        return payload

    for raw_line in response:
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8", errors="replace")
        else:
            line = str(raw_line)
        line = line.rstrip("\r\n")
        if line == "":
            payload = flush()
            if payload is not None:
                yield payload
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].lstrip())

    payload = flush()
    if payload is not None:
        yield payload


def post_streaming(token: str, payload: dict[str, Any], *, timeout: int = 300) -> str:
    """POST a Codex Responses payload and return the final image as base64.

    Returns the final b64 from the last image_generation_call event. If the
    stream contains only partials, returns the last partial.
    Raises RuntimeError on HTTP failure or empty stream.
    """
    body = json.dumps(payload).encode("utf-8")
    headers = cloudflare_headers(token)
    req = urllib.request.Request(
        f"{CODEX_BASE_URL}{RESPONSES_PATH}",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        response = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Codex Responses API returned HTTP {e.code}: {body_text[:500]}"
        ) from e

    image_b64: str | None = None
    partial_count = 0
    error_text: str | None = None
    with response:
        for event in iter_sse_json(response):
            b64 = extract_image_b64(event)
            if b64:
                image_b64 = b64
                partial_count += 1
            etype = event.get("type")
            if etype in ("response.completed", "response.done"):
                break
            if etype in ("error", "response.failed"):
                error_text = json.dumps(event)[:500]

    if not image_b64:
        if error_text:
            raise RuntimeError(f"Codex stream returned an error event: {error_text}")
        raise RuntimeError(
            "Codex response contained no image_generation_call result. "
            f"Saw {partial_count} partial image(s)."
        )
    return image_b64


def refresh_if_needed(skew_seconds: int = DEFAULT_REFRESH_SKEW_SECONDS) -> bool:
    """Refresh the OAuth token if its JWT exp is within skew_seconds of now.

    Calls `python -m hermes_oauth_openai_codex refresh` as a subprocess. On
    success, that command updates ~/.claude/skills/planf3/.env (and the
    Hermes auth.json + raw cache). Returns True if a refresh was performed
    and the .env was rewritten, False otherwise.

    Best-effort: refresh failures print a warning but do not raise — the
    caller can still attempt the API call with the current token.
    """
    import time

    try:
        token = read_token()
    except EnvironmentError as e:
        print(f"  refresh_if_needed: {e}", file=sys.stderr)
        return False

    exp = jwt_exp(token)
    if exp is None:
        # Not a JWT or unparseable — leave it alone.
        return False

    now = int(time.time())
    if exp - now > skew_seconds:
        return False

    print(f"  Token expires in {(exp - now) // 3600}h — refreshing...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "hermes_oauth_openai_codex", "refresh"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        print("  refresh_if_needed: refresh timed out after 60s", file=sys.stderr)
        return False
    except FileNotFoundError as e:
        print(f"  refresh_if_needed: {e}", file=sys.stderr)
        return False

    if result.returncode != 0:
        print(
            f"  refresh_if_needed: refresh failed (exit {result.returncode}); "
            f"stderr: {(result.stderr or '').strip()[:300]}",
            file=sys.stderr,
        )
        return False

    # Reload .env so os.environ reflects the new OPENAI_API_KEY.
    load_dotenv(Path.cwd() / ".env", override=True)
    print("  Refresh OK.")
    return True
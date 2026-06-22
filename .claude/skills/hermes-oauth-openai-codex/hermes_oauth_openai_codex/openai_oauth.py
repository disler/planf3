"""HTTP layer for auth.openai.com — authorize URL, token POSTs, refresh, token-exchange.

Endpoints and parameters sourced from openai/codex codex-rs/login/ (main branch).
All requests are stdlib urllib.request — no requests dependency, matching
the Hermes Anthropic PKCE pattern (anthropic_adapter.py uses urllib).

Constants:
    CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
    ISSUER    = "https://auth.openai.com"
    AUTHORIZE = f"{ISSUER}/oauth/authorize"
    TOKEN     = f"{ISSUER}/oauth/token"
    SCOPE     = "openid profile email offline_access api.connectors.read api.connectors.invoke"
    REDIRECT_URI = "http://localhost:1455/auth/callback"
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import errors as err

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = f"{ISSUER}/oauth/authorize"
TOKEN_URL = f"{ISSUER}/oauth/token"
DEFAULT_REDIRECT_URI = "http://localhost:1455/auth/callback"
# NOTE: the redirect URI string in the authorize URL MUST be `localhost`, not
# `127.0.0.1`, because that's what's allow-listed on the Codex OAuth client.
# The HTTP listener can bind to either — they resolve to the same address on
# Windows. Codex itself does exactly this: binds 127.0.0.1, advertises localhost.
DEFAULT_PORT = 1455
FALLBACK_PORT = 1457
SCOPE = "openid profile email offline_access api.connectors.read api.connectors.invoke"
USER_AGENT = "hermes-oauth-openai-codex/0.1.0"
ORIGINATOR = "codex_cli_rs"
HTTP_TIMEOUT_SECONDS = 30
TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
TOKEN_EXCHANGE_REQUESTED = "openai-api-key"
TOKEN_EXCHANGE_SUBJECT_TYPE = "urn:ietf:params:oauth:token-type:id_token"


def build_authorize_url(
    *,
    code_challenge: str,
    state: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
) -> str:
    """Build the authorize URL the user opens in a browser.

    Mirrors Codex's server.rs build_authorize_url: extra params
    `id_token_add_organizations=true`, `codex_cli_simplified_flow=true`,
    `originator=codex_cli_rs`.
    """
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "state": state,
        "originator": ORIGINATOR,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def _post(url: str, body: bytes, content_type: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": content_type,
            "User-Agent": USER_AGENT,
            "Originator": ORIGINATOR,
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as e:
        _raise_for_status(e)
    except urllib.error.URLError as e:
        raise err.NetworkError(f"transport failure: {e}") from e
    return json.loads(payload)


def _raise_for_status(http_err: urllib.error.HTTPError) -> None:
    body = ""
    try:
        body = http_err.read().decode("utf-8", errors="replace")
    except Exception:
        pass
    code = http_err.code
    if code == 429:
        raise err.RateLimited(f"429 from token endpoint: {body}")
    if code >= 500:
        raise err.ServerError(f"{code} from token endpoint: {body}")
    # Try to extract a Codex-style error code from JSON body.
    detail = body
    try:
        parsed = json.loads(body)
        detail = parsed.get("error_description") or parsed.get("error") or body
    except Exception:
        pass
    codex_code = ""
    try:
        parsed = json.loads(body)
        codex_code = (parsed.get("error") or parsed.get("error_code") or "").lower()
    except Exception:
        pass
    if codex_code == "refresh_token_expired":
        raise err.TokenExpired(f"{code}: {detail}")
    if codex_code in ("refresh_token_reused", "refresh_token_invalidated"):
        raise err.TokenRevoked(f"{code}: {detail}")
    raise err.TokenExchangeFailed(f"{code}: {detail}")


def exchange_code_for_tokens(
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
) -> dict[str, Any]:
    """Trade authorization code for OAuth tokens (access/refresh/id).

    Matches Codex server.rs exchange_code_for_tokens (form-urlencoded
    Content-Type matches codex-rs, although Anthropic Hermes uses JSON —
    Codex explicitly serializes x-www-form-urlencoded here).
    """
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": CLIENT_ID,
        "code_verifier": code_verifier,
    }).encode("utf-8")
    return _post(TOKEN_URL, body, "application/x-www-form-urlencoded")


def refresh_tokens(*, refresh_token: str) -> dict[str, Any]:
    """Exchange refresh_token for a new OAuth token bundle.

    Codex uses JSON Content-Type for refresh (manager.rs), distinct from
    the form-urlencoded exchange/refresh pattern Anthropic Hermes tries.
    Single endpoint, no fallback list — Codex confirms a single URL.
    """
    body = json.dumps({
        "client_id": CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }).encode("utf-8")
    return _post(TOKEN_URL, body, "application/json")


def token_exchange(*, id_token: str) -> dict[str, Any]:
    """Mint an API-key-shaped token from the id_token.

    Implements the OAuth 2.0 token-exchange grant Codex uses to convert
    an OIDC id_token into a Bearer token accepted by api.openai.com/v1.

    Raises TokenExchangeFailed; callers should detect the personal-account
    case (no organization_id in id_token) and fall back to using the OAuth
    access_token directly — see login.run_login / refresh.run_refresh.
    """
    body = urllib.parse.urlencode({
        "grant_type": TOKEN_EXCHANGE_GRANT,
        "client_id": CLIENT_ID,
        "requested_token": TOKEN_EXCHANGE_REQUESTED,
        "subject_token": id_token,
        "subject_token_type": TOKEN_EXCHANGE_SUBJECT_TYPE,
    }).encode("utf-8")
    return _post(TOKEN_URL, body, "application/x-www-form-urlencoded")


def is_personal_account_error(exc: BaseException) -> bool:
    """True if the exception matches the "missing organization_id" personal-account case.

    Codex handles this by using the OAuth access_token directly. The exact
    server message is 'Invalid ID token: missing organization_id' with code
    'invalid_subject_token' and HTTP 401.
    """
    msg = str(exc)
    return "missing organization_id" in msg or "organization_id" in msg and "401" in msg


def now_ms() -> int:
    """Current epoch time in milliseconds (Hermes schema)."""
    return int(time.time() * 1000)
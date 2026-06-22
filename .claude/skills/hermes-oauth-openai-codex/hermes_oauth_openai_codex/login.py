"""Run the full ChatGPT-Plus OAuth PKCE login flow.

Steps:
    1. Generate PKCE verifier/challenge + state CSRF token.
    2. Start a localhost callback server (1455, fallback 1457).
    3. Open the user's browser to the authorize URL.
    4. Wait (up to 300s) for the callback with code+state.
    5. Exchange the code for OAuth tokens (access/refresh/id).
    6. Run the token-exchange to mint an API-key-shaped token from id_token.
    7. Write the credential-pool entry + raw token cache + planf3 .env.

Prints numbered progress lines to stdout and writes structured errors to
stderr on failure (matching Hermes CLI style).
"""
from __future__ import annotations

import sys
import time
import webbrowser
from typing import Any

from . import auth_json, errors as err, openai_oauth, pkce, planf3_env
from .callback_server import CALLBACK_PATH, start_callback_server

CALLBACK_TIMEOUT_SECONDS = 300
TOTAL_STEPS = 7


def _print(step: int, total: int, msg: str) -> None:
    print(f"[{step}/{total}] {msg}", flush=True)


def _print_indent(msg: str) -> None:
    print(f"      {msg}", flush=True)


def _error(step: int, exc: Exception, hint: str = "") -> None:
    print(f"[{step}/{TOTAL_STEPS}] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    if hint:
        print(f"      Hint: {hint}", file=sys.stderr, flush=True)


def run_login(
    *,
    primary_port: int = openai_oauth.DEFAULT_PORT,
    fallback_port: int = openai_oauth.FALLBACK_PORT,
    do_token_exchange: bool = True,
    update_planf3_env: bool = True,
    open_browser: bool = True,
    timeout_seconds: int = CALLBACK_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run the PKCE flow end-to-end. Returns a summary dict on success."""
    total = TOTAL_STEPS
    verifier, challenge = ("", "")
    state = ""
    auth_url = ""

    try:
        _print(1, total, "Generating PKCE verifier and challenge...")
        verifier, challenge = pkce.generate_pkce()
        _print_indent(f"verifier={len(verifier)} chars, challenge={len(challenge)} chars")

        _print(2, total, "Generating CSRF state token...")
        state = pkce.generate_state()
        _print_indent(f"state={len(state)} chars")

        _print(3, total, "Starting local callback server...")
        server, bound_port = start_callback_server(
            expected_state=state,
            host="127.0.0.1",
            primary_port=primary_port,
            fallback_port=fallback_port,
        )
        # Advertise `localhost` (not 127.0.0.1) in the redirect_uri so it
        # matches the Codex client allow-list on auth.openai.com's Hydra server.
        redirect_uri = f"http://localhost:{bound_port}{CALLBACK_PATH}"
        server.start()
        _print_indent(f"bound to http://127.0.0.1:{bound_port}{CALLBACK_PATH}")

        _print(4, total, "Building authorize URL and opening browser...")
        auth_url = openai_oauth.build_authorize_url(
            code_challenge=challenge,
            state=state,
            redirect_uri=redirect_uri,
        )
        _print_indent(f"URL: {auth_url}")
        if open_browser:
            try:
                webbrowser.open(auth_url)
                _print_indent("Browser opened.")
            except Exception as e:
                _print_indent(f"Browser open failed ({e!r}); copy the URL above into a browser manually.")

        _print(5, total, f"Waiting for callback (timeout {timeout_seconds}s)...")
        if not server.wait(timeout=timeout_seconds):
            server.stop()
            raise err.CallbackTimeout(
                f"No callback within {timeout_seconds}s. Re-run `hermes-oauth-codex login`."
            )
        captured = server.captured
        server.stop()
        if captured.get("error"):
            raise err.OAuthError(f"Provider returned error: {captured['error']}")
        if captured.get("code") is None:
            raise err.OAuthError("No authorization code received.")
        if captured.get("state") != state:
            raise err.StateMismatch("State mismatch on callback.")
        _print_indent("CSRF state check: OK")
        _print_indent(f"code={captured['code'][:12]}...")

        _print(6, total, "Exchanging authorization code for tokens...")
        tokens = openai_oauth.exchange_code_for_tokens(
            code=captured["code"],
            code_verifier=verifier,
            redirect_uri=redirect_uri,
        )
        access_token = tokens["access_token"]
        refresh_token = tokens["refresh_token"]
        id_token = tokens.get("id_token", "")
        expires_in = int(tokens.get("expires_in", 3600))
        expires_at_ms = (int(time.time()) + expires_in) * 1000
        _print_indent(f"access_token={len(access_token)} chars, refresh_token={len(refresh_token)} chars, expires_in={expires_in}s")

        api_key = access_token
        email = None
        org_id = None
        project_id = None
        token_source = "oauth_access_token"
        if do_token_exchange and id_token:
            _print_indent("Running token-exchange (id_token -> openai-api-key)...")
            try:
                exch = openai_oauth.token_exchange(id_token=id_token)
                api_key = exch.get("access_token") or access_token
                email = exch.get("email") or email
                org_id = exch.get("organization_id") or org_id
                project_id = exch.get("project_id") or project_id
                token_source = "token_exchange"
                _print_indent(f"api_key={len(api_key)} chars, org={org_id}, email={email}")
            except err.TokenExchangeFailed as e:
                if openai_oauth.is_personal_account_error(e):
                    _print_indent(f"Token-exchange skipped (personal ChatGPT account, no org).")
                    _print_indent(f"Falling back to OAuth access_token as Bearer key.")
                    _print_indent(f"  reason: {e}")
                else:
                    raise

        _print(7, total, "Writing credentials...")
        entry = auth_json.build_pool_entry(
            access_token=api_key,
            refresh_token=refresh_token,
            expires_at_ms=expires_at_ms,
            id_token=id_token or None,
            email=email,
            organization_id=org_id,
            project_id=project_id,
        )
        stored = auth_json.add_pool_entry(
            auth_json_path_value=auth_json.auth_json_path(),
            entry=entry,
        )
        _print_indent(f"credential_pool.openai-codex-pkce[{stored['id']}] added")

        auth_json.save_raw_token_cache(
            raw_path=auth_json.raw_token_path(),
            access_token=access_token,
            refresh_token=refresh_token,
            id_token=id_token,
            api_key=api_key,
            expires_at_ms=expires_at_ms,
            email=email,
            organization_id=org_id,
            project_id=project_id,
        )
        _print_indent(f"raw token cache: {auth_json.raw_token_path()}")

        if update_planf3_env:
            try:
                planf3_env.update_openai_api_key(api_key)
                _print_indent(f"planf3 .env updated: OPENAI_API_KEY (len={len(api_key)}, {planf3_env.fingerprint(api_key)})")
            except FileNotFoundError:
                _print_indent(f"planf3 .env path not found; skipping (set HERMES_OAUTH_PLANF3_ENV to override).")
            except Exception as e:
                _print_indent(f"planf3 .env update failed: {type(e).__name__}: {e}")

        print()
        print(f"Login successful. Entry id={stored['id']} expires={expires_at_ms}.")
        return {
            "entry_id": stored["id"],
            "expires_at_ms": expires_at_ms,
            "auth_json_path": str(auth_json.auth_json_path()),
            "raw_token_path": str(auth_json.raw_token_path()),
            "email": email,
            "organization_id": org_id,
            "project_id": project_id,
        }

    except err.OAuthError as e:
        _error(0, e)
        raise
    except Exception as e:
        _error(0, e)
        raise err.OAuthError(str(e)) from e
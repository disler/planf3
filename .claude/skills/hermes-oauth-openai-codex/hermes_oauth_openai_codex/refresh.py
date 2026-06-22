"""Refresh ChatGPT-Plus OAuth tokens and update storage.

Reads the refresh_token from the raw cache (preferred — has the original
OAuth token, even after token-exchange rotates the API key), calls
auth.openai.com /oauth/token, then runs the token-exchange step again
to mint a fresh API-key-shaped token. Writes both files and the planf3 .env.
"""
from __future__ import annotations

import sys
import time
from typing import Any

from . import auth_json, errors as err, openai_oauth, planf3_env

TOTAL_STEPS = 5


def _print(step: int, total: int, msg: str) -> None:
    print(f"[{step}/{total}] {msg}", flush=True)


def _print_indent(msg: str) -> None:
    print(f"      {msg}", flush=True)


def _error(step: int, exc: Exception, hint: str = "") -> None:
    print(f"[{step}/{TOTAL_STEPS}] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    if hint:
        print(f"      Hint: {hint}", file=sys.stderr, flush=True)


def _find_refresh_source() -> tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]:
    """Return (refresh_token, entry_id, pool_entry, raw_cache).

    Tries raw cache first (preserves the OAuth refresh_token even if the
    pool entry's access_token is the token-exchange-derived one).
    """
    raw = auth_json.load_raw_token_cache(auth_json.raw_token_path())
    entries = auth_json.list_pool_entries(auth_json_path_value=auth_json.auth_json_path())
    if not entries:
        raise err.OAuthError("No openai-codex-pkce entries found. Run `hermes-oauth-codex login` first.")
    entry = entries[0]
    entry_id = entry.get("id", "")
    refresh_token = (raw or {}).get("refreshToken") or entry.get("refresh_token") or ""
    if not refresh_token:
        raise err.OAuthError("No refresh_token available. Re-run `login`.")
    return refresh_token, entry_id, entry, raw


def run_refresh(
    *,
    do_token_exchange: bool = True,
    update_planf3_env: bool = True,
) -> dict[str, Any]:
    """Refresh the OAuth token, re-derive API key, persist."""
    total = TOTAL_STEPS
    try:
        _print(1, total, "Locating refresh_token...")
        refresh_token, entry_id, pool_entry, raw = _find_refresh_source()
        _print_indent(f"entry={entry_id}, refresh_token={len(refresh_token)} chars")

        _print(2, total, "Calling POST /oauth/token (grant_type=refresh_token)...")
        tokens = openai_oauth.refresh_tokens(refresh_token=refresh_token)
        access_token = tokens["access_token"]
        new_refresh = tokens["refresh_token"]
        id_token = tokens.get("id_token", "") or (raw or {}).get("idToken", "")
        expires_in = int(tokens.get("expires_in", 3600))
        expires_at_ms = (int(time.time()) + expires_in) * 1000
        _print_indent(f"new access_token={len(access_token)} chars, new refresh_token={len(new_refresh)} chars, expires_in={expires_in}s")

        _print(3, total, "Running token-exchange (id_token -> openai-api-key)..." if do_token_exchange and id_token else "Skipping token-exchange (no id_token or disabled).")
        api_key = access_token
        email = None
        org_id = None
        project_id = None
        if do_token_exchange and id_token:
            try:
                exch = openai_oauth.token_exchange(id_token=id_token)
                api_key = exch.get("access_token") or access_token
                email = exch.get("email") or (pool_entry or {}).get("email")
                org_id = exch.get("organization_id") or (pool_entry or {}).get("organization_id")
                project_id = exch.get("project_id") or (pool_entry or {}).get("project_id")
                _print_indent(f"api_key={len(api_key)} chars")
            except err.TokenExchangeFailed as e:
                if openai_oauth.is_personal_account_error(e):
                    _print_indent(f"Token-exchange skipped (personal account).")
                    _print_indent(f"Falling back to OAuth access_token as Bearer key.")
                else:
                    raise

        _print(4, total, "Updating auth.json credential pool...")
        auth_json.update_pool_entry(
            auth_json_path_value=auth_json.auth_json_path(),
            entry_id=entry_id,
            updates={
                "access_token": api_key,
                "refresh_token": new_refresh,
                "expires_at_ms": expires_at_ms,
                "last_status": "ok",
                "last_status_at": int(time.time() * 1000),
                "id_token": id_token,
                "secret_fingerprint": auth_json.compute_fingerprint(new_refresh),
            },
        )
        _print_indent(f"entry {entry_id} updated")

        auth_json.save_raw_token_cache(
            raw_path=auth_json.raw_token_path(),
            access_token=access_token,
            refresh_token=new_refresh,
            id_token=id_token,
            api_key=api_key,
            expires_at_ms=expires_at_ms,
            email=email,
            organization_id=org_id,
            project_id=project_id,
        )
        _print_indent(f"raw cache: {auth_json.raw_token_path()}")

        _print(5, total, "Updating planf3 .env..." if update_planf3_env else "Skipping planf3 .env update.")
        if update_planf3_env:
            try:
                planf3_env.update_openai_api_key(api_key)
                _print_indent(f"OPENAI_API_KEY updated (len={len(api_key)}, {planf3_env.fingerprint(api_key)})")
            except Exception as e:
                _print_indent(f"planf3 .env update skipped: {type(e).__name__}: {e}")

        print()
        print(f"Refresh successful. Entry id={entry_id} expires={expires_at_ms}.")
        return {
            "entry_id": entry_id,
            "expires_at_ms": expires_at_ms,
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
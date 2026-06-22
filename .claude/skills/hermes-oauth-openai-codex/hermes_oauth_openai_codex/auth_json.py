"""Hermes credential-pool writer at ~/.hermes/auth.json.

Schema matches Hermes's PooledCredential dataclass (credential_pool.py:131-175):
    credential_pool: {<provider>: [PooledCredential, ...]}
    providers: {}
    version: 1
    updated_at: <ISO timestamp>

Provider key for this module: "openai-codex-pkce" (the existing
"openai-codex" slot is reserved for Hermes's device-code flow).
Source field: "openai_codex_pkce".
Auth type: "oauth".

Raw token cache (mirrors Hermes's .anthropic_oauth.json camelCase):
    ~/.hermes/.openai_codex_oauth.json
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROVIDER_KEY = "openai-codex-pkce"
SOURCE_TAG = "openai_codex_pkce"
AUTH_TYPE = "oauth"
RAW_TOKEN_FILENAME = ".openai_codex_oauth.json"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


def hermes_home() -> Path:
    """Return ~/.hermes, honoring HERMES_HOME for non-standard installs."""
    override = os.environ.get("HERMES_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".hermes"


def auth_json_path() -> Path:
    return hermes_home() / "auth.json"


def raw_token_path() -> Path:
    return hermes_home() / RAW_TOKEN_FILENAME


def _atomic_write(path: Path, data: str) -> None:
    """Write text atomically: tmp file + os.replace. Windows-safe."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "x", encoding="utf-8") as fh:
            fh.write(data)
    except FileExistsError:
        os.remove(tmp)
        with open(tmp, "x", encoding="utf-8") as fh:
            fh.write(data)
    os.replace(tmp, path)


def load_auth_json(path: Path) -> dict[str, Any]:
    """Load auth.json; initialize shape if missing or invalid."""
    if not path.exists():
        return {
            "credential_pool": {},
            "providers": {},
            "version": 1,
            "updated_at": _iso_now(),
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "credential_pool": {},
            "providers": {},
            "version": 1,
            "updated_at": _iso_now(),
        }
    data.setdefault("credential_pool", {})
    data.setdefault("providers", {})
    data.setdefault("version", 1)
    return data


def save_auth_json(path: Path, data: dict[str, Any]) -> None:
    """Persist auth.json atomically with an updated_at stamp."""
    data["updated_at"] = _iso_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, json.dumps(data, indent=2, sort_keys=False))


def compute_id(existing_ids: set[str]) -> str:
    """Return a 6-char hex id that doesn't collide with existing_ids."""
    for _ in range(10):
        candidate = secrets.token_hex(3)
        if candidate not in existing_ids:
            return candidate
    # Astronomically unlikely; fall back to 8-char with timestamp suffix.
    return secrets.token_hex(3) + secrets.token_hex(1)


def compute_fingerprint(secret: str) -> str:
    """sha256:<first 16 hex chars> — fingerprint of the refresh_token."""
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_pool_entry(
    *,
    access_token: str,
    refresh_token: str,
    expires_at_ms: int,
    id_token: str | None = None,
    email: str | None = None,
    organization_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Build a credential-pool entry shaped like Hermes's PooledCredential."""
    label_email = email or "chatgpt-plus"
    label = f"ChatGPT-Plus  {label_email}"
    entry: dict[str, Any] = {
        "id": secrets.token_hex(3),
        "label": label,
        "auth_type": AUTH_TYPE,
        "priority": 0,
        "source": SOURCE_TAG,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at_ms": expires_at_ms,
        "last_status": "ok",
        "last_status_at": expires_at_ms,  # caller can adjust; matches "now" semantics at write time
        "last_error_code": None,
        "last_error_reason": None,
        "last_error_message": None,
        "last_error_reset_at": None,
        "base_url": DEFAULT_BASE_URL,
        "request_count": 0,
        "secret_fingerprint": compute_fingerprint(refresh_token),
    }
    if id_token is not None:
        entry["id_token"] = id_token
    if organization_id is not None:
        entry["organization_id"] = organization_id
    if project_id is not None:
        entry["project_id"] = project_id
    if email is not None:
        entry["email"] = email
    return entry


def add_pool_entry(
    *,
    auth_json_path_value: Path,
    entry: dict[str, Any],
    provider: str = PROVIDER_KEY,
) -> dict[str, Any]:
    """Append entry to credential_pool[provider], creating the list if needed.

    Returns the entry as stored (may have a different id if there was a
    collision — for safety we regenerate).
    """
    data = load_auth_json(auth_json_path_value)
    pool = data.setdefault("credential_pool", {})
    bucket = pool.setdefault(provider, [])
    existing_ids = {e.get("id") for e in bucket if isinstance(e, dict)}
    if entry.get("id") in existing_ids:
        entry["id"] = compute_id(existing_ids)
    bucket.append(entry)
    save_auth_json(auth_json_path_value, data)
    return entry


def update_pool_entry(
    *,
    auth_json_path_value: Path,
    entry_id: str,
    updates: dict[str, Any],
    provider: str = PROVIDER_KEY,
) -> dict[str, Any] | None:
    """Update fields on an existing pool entry; return updated entry or None."""
    data = load_auth_json(auth_json_path_value)
    bucket = data.get("credential_pool", {}).get(provider, [])
    for entry in bucket:
        if entry.get("id") == entry_id:
            entry.update(updates)
            # Recompute fingerprint if refresh_token changed.
            if "refresh_token" in updates and updates["refresh_token"]:
                entry["secret_fingerprint"] = compute_fingerprint(updates["refresh_token"])
            save_auth_json(auth_json_path_value, data)
            return entry
    return None


def remove_pool_entry(
    *,
    auth_json_path_value: Path,
    entry_id: str | None = None,
    remove_all: bool = False,
    provider: str = PROVIDER_KEY,
) -> int:
    """Remove one or all entries for the provider. Returns count removed."""
    data = load_auth_json(auth_json_path_value)
    bucket = data.get("credential_pool", {}).get(provider, [])
    if remove_all:
        removed = len(bucket)
        data["credential_pool"][provider] = []
        save_auth_json(auth_json_path_value, data)
        return removed
    if entry_id is None:
        return 0
    before = len(bucket)
    bucket[:] = [e for e in bucket if e.get("id") != entry_id]
    removed = before - len(bucket)
    if removed:
        save_auth_json(auth_json_path_value, data)
    return removed


def list_pool_entries(
    *,
    auth_json_path_value: Path,
    provider: str = PROVIDER_KEY,
) -> list[dict[str, Any]]:
    data = load_auth_json(auth_json_path_value)
    return list(data.get("credential_pool", {}).get(provider, []))


def save_raw_token_cache(
    *,
    raw_path: Path,
    access_token: str,
    refresh_token: str,
    id_token: str,
    api_key: str,
    expires_at_ms: int,
    email: str | None = None,
    organization_id: str | None = None,
    project_id: str | None = None,
) -> None:
    """Write the raw OAuth token cache (camelCase, mirrors .anthropic_oauth.json)."""
    payload: dict[str, Any] = {
        "clientId": "app_EMoamEEZ73f0CkXaXp7hrann",
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresAt": expires_at_ms,
        "idToken": id_token,
        "apiKey": api_key,
        "issuedAt": _iso_now(),
    }
    if email is not None:
        payload["email"] = email
    if organization_id is not None:
        payload["organizationId"] = organization_id
    if project_id is not None:
        payload["projectId"] = project_id
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(raw_path, json.dumps(payload, indent=2, sort_keys=False))


def load_raw_token_cache(raw_path: Path) -> dict[str, Any] | None:
    """Read the raw OAuth cache; None if missing or invalid."""
    if not raw_path.exists():
        return None
    try:
        return json.loads(raw_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
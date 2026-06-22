"""Update the planf3 .env file with the OAuth-derived API key.

Planf3's image-gen scripts (scripts/generate_gpt_image.py) read OPENAI_API_KEY
from the environment / .env file at ~/.claude/skills/planf3/.env. After a
successful ChatGPT-Plus login, this module writes the token-exchange-derived
API-key-shaped token into that file so planf3 image gen works without any
manual key paste.

Path precedence: HERMES_OAUTH_PLANF3_ENV env var > default.
Atomic write preserves comment lines and ordering; first write creates a
timestamped backup.
"""
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable

DEFAULT_PLANF3_ENV = Path.home() / ".claude" / "skills" / "planf3" / ".env"
ENV_OVERRIDE = "HERMES_OAUTH_PLANF3_ENV"
OPENAI_API_KEY_LINE = "OPENAI_API_KEY"


def planf3_env_path() -> Path:
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        return Path(override).expanduser()
    return DEFAULT_PLANF3_ENV


def _backup_path(env_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return env_path.with_name(env_path.name + f".bak.{stamp}")


def read_env(env_path: Path) -> list[tuple[str, str | None, str]]:
    """Parse an .env file into (key, value|None, raw_line) tuples.

    Preserves ordering and comment/blank lines (value=None for those).
    """
    if not env_path.exists():
        return []
    out: list[tuple[str, str | None, str]] = []
    for raw in env_path.read_text(encoding="utf-8").splitlines(keepends=False):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            out.append(("", None, raw))
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", stripped)
        if not m:
            out.append(("", None, raw))
            continue
        key, value = m.group(1), m.group(2)
        # Strip optional surrounding quotes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out.append((key, value, raw))
    return out


def write_env(
    env_path: Path,
    updates: dict[str, str],
    *,
    backup: bool = True,
) -> Path:
    """Atomically update keys in the .env file. Creates the file if missing.

    Returns the path written. Preserves comments and ordering; updates the
    existing line in place when present, otherwise appends.
    """
    entries = read_env(env_path)
    keys_updated: set[str] = set()
    new_lines: list[str] = []
    for key, _value, raw in entries:
        if key in updates:
            new_lines.append(f"{key}={updates[key]}\n")
            keys_updated.add(key)
        else:
            new_lines.append(raw + "\n" if not raw.endswith("\n") else raw)
    for key, value in updates.items():
        if key not in keys_updated:
            new_lines.append(f"{key}={value}\n")
    if backup and env_path.exists():
        bp = _backup_path(env_path)
        if not bp.exists():
            shutil.copy2(env_path, bp)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = env_path.with_name(env_path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    tmp.write_text("".join(new_lines), encoding="utf-8")
    os.replace(tmp, env_path)
    return env_path


def update_openai_api_key(api_key: str) -> Path:
    """Write OPENAI_API_KEY to the planf3 .env. Returns the path written."""
    return write_env(planf3_env_path(), {OPENAI_API_KEY_LINE: api_key})


def fingerprint(secret: str) -> str:
    """Short, non-reversible fingerprint for log output."""
    import hashlib
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]
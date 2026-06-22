"""PKCE primitives — S256 method, 32-byte verifier, base64url no padding.

The shape is copied verbatim from Hermes's Anthropic adapter
(agent/anthropic_adapter.py:1260-1270) for symmetry with that pattern.
Codex (codex-rs/login/src/pkce.rs) uses 64 bytes; 32 is RFC 7636-compliant
and matches the Anthropic precedent in this repo.
"""
from __future__ import annotations

import base64
import hashlib
import secrets


def _b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256.

    Verifier is 43 base64url chars (32 bytes of entropy). Challenge is
    base64url(sha256(verifier)) with no padding.
    """
    verifier = _b64url_no_pad(secrets.token_bytes(32))
    challenge = _b64url_no_pad(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def generate_state() -> str:
    """Return a 43-char CSRF state token (URL-safe base64, 32 bytes entropy)."""
    return secrets.token_urlsafe(32)
"""Exception types for hermes_oauth_openai_codex.

Mirrors the Hermes Anthropic PKCE flow's error taxonomy (silent failures
become loud, class-named exceptions so callers can branch on intent).
"""
from __future__ import annotations


class OAuthError(Exception):
    """Base class for all hermes_oauth_openai_codex errors."""


class PortInUse(OAuthError):
    """Neither the requested port nor the fallback could be bound."""


class CallbackTimeout(OAuthError):
    """The browser callback never arrived within the timeout window."""


class StateMismatch(OAuthError):
    """The state query param on the callback did not match what we issued."""


class TokenExchangeFailed(OAuthError):
    """The token endpoint returned a non-2xx status."""


class TokenExpired(OAuthError):
    """refresh_token has expired — re-login required (terminal)."""


class TokenRevoked(OAuthError):
    """refresh_token was reused or invalidated (terminal)."""


class RateLimited(OAuthError):
    """429 from the token endpoint; transient."""


class ServerError(OAuthError):
    """5xx from the token endpoint; transient."""


class NetworkError(OAuthError):
    """urllib-level transport failure; transient."""
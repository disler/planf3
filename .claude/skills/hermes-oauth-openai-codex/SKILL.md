---
name: hermes-oauth-openai-codex
description: ChatGPT-Plus OAuth PKCE login that issues a refreshable Bearer token and writes it to Hermes's auth.json credential pool (provider "openai-codex-pkce"). Mirrors Hermes's existing Anthropic-PKCE pattern; swaps in auth.openai.com endpoints and the documented Codex PKCE flow. The derived bearer also lands in the planf3 .env so planf3's image-gen scripts (now Codex-Responses-API-backed) work with a ChatGPT-Plus subscription — no sk-... API key needed.
---

# Hermes OAuth OpenAI Codex

## Purpose

Run a ChatGPT-Plus OAuth PKCE browser login once, get a refreshable Bearer token in `~/.hermes/auth.json` (provider `openai-codex-pkce`, `source: openai_codex_pkce`, `auth_type: oauth`) and `~/.hermes/.openai_codex_oauth.json` (raw cache). The same token is pushed into `~/.claude/skills/planf3/.env` as `OPENAI_API_KEY` so planf3 image generation works without an `sk-...` API key.

The PKCE pattern is copied from Hermes's Anthropic adapter (`agent/anthropic_adapter.py:972-1393`); endpoints and token-exchange step come from `codex-rs/login/`. For personal ChatGPT-Plus accounts the `urn:ietf:params:oauth:grant-type:token-exchange` step is rejected with "missing organization_id"; the module catches that specific failure and falls back to using the OAuth `access_token` directly — exactly what Codex itself does for personal subscribers.

## Install

```bash
cd .claude/skills/hermes-oauth-openai-codex/hermes_oauth_openai_codex
pip install --user .
```

That installs the `hermes-oauth-codex` shim and registers `python -m hermes_oauth_openai_codex`.

## Variables

USER_PROMPT: $1 — usually empty; just run `login` once.

## Instructions

- If the user asks to log in to ChatGPT-Plus for use with Hermes / planf3, run `python -m hermes_oauth_openai_codex login` (or the installed shim `hermes-oauth-codex login`).
- The flow opens the default browser to `auth.openai.com`. If the browser can't open (headless, RDP), the URL is printed for manual paste — pass `--no-browser` to skip the open attempt.
- Wait for the user to complete the login in their browser. The script blocks up to 300 seconds.
- After login, the access_token lives in `~/.hermes/auth.json` AND the planf3 `.env` (`OPENAI_API_KEY=`). Hermes's credential pool picks it up automatically on next start; planf3's image-gen scripts read it from `.env` directly.
- If the token expires (every ~10 days), run `python -m hermes_oauth_openai_codex refresh`. Planf3's image scripts auto-refresh when the JWT is within 48 hours of expiry, so this rarely needs to be run by hand.

## CLI

```
hermes-oauth-codex login                [--no-planf3-env] [--no-token-exchange] [--no-browser] [--port 1455] [--timeout 300]
hermes-oauth-codex refresh              [--no-planf3-env] [--no-token-exchange]
hermes-oauth-codex status [--json]
hermes-oauth-codex logout               --all | --id <hex6>
hermes-oauth-codex whoami               # decode id_token JWT claims (no signature verify)
hermes-oauth-codex path                 # print resolved file paths
hermes-oauth-codex version
```

## Files written

| File | Contents |
| --- | --- |
| `~/.hermes/auth.json` | Credential-pool entry under provider `openai-codex-pkce`; existing entries (anthropic, etc.) preserved. |
| `~/.hermes/.openai_codex_oauth.json` | Raw OAuth cache (camelCase), mirrors Hermes's `.anthropic_oauth.json`. |
| `~/.claude/skills/planf3/.env` | `OPENAI_API_KEY=<OAuth bearer JWT>`. Override path with `HERMES_OAUTH_PLANF3_ENV`. First write creates a `.env.bak.YYYYMMDD-HHMMSS` backup. |

See `README.md` in this skill for the full install + usage walkthrough.
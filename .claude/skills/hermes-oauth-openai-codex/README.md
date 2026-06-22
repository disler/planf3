# hermes-oauth-openai-codex (skill)

This skill ships a standalone Python package that performs a ChatGPT-Plus OAuth PKCE browser login and writes the resulting Bearer token into Hermes's credential pool (`~/.hermes/auth.json`) and the planf3 `.env`. After a single login, planf3 image generation works on a ChatGPT-Plus subscription — no `sk-...` API key required.

## Install

From this skill's package directory:

```bash
cd .claude/skills/hermes-oauth-openai-codex/hermes_oauth_openai_codex
pip install --user .
```

On POSIX this puts the `hermes-oauth-codex` shim at `~/.local/bin/`. On Windows it's at `%APPDATA%\Python\Python3xx\Scripts\hermes-oauth-codex.exe`. If that directory isn't on `PATH`, the module invocation works regardless:

```bash
python -m hermes_oauth_openai_codex login
```

## Login (one-time)

```bash
hermes-oauth-codex login
```

The browser opens to `https://auth.openai.com/oauth/authorize?code_challenge=...&code_challenge_method=S256&...`. Complete the ChatGPT login in your browser; the script captures the redirect on `http://localhost:1455/auth/callback`, exchanges the code for tokens, and writes three files:

- `~/.hermes/auth.json` — credential-pool entry under provider `openai-codex-pkce`. Existing entries are preserved.
- `~/.hermes/.openai_codex_oauth.json` — raw OAuth cache.
- `~/.claude/skills/planf3/.env` — `OPENAI_API_KEY=<OAuth bearer JWT>`.

If port `1455` is busy, the module falls back to `1457` automatically. If the browser can't open, the authorize URL is printed for manual paste.

## Using with planf3

After login, planf3's image scripts (`generate_gpt_image.py`, `edit_gpt_image.py` — modified to use the Codex Responses API at `chatgpt.com/backend-api/codex/responses`) pick up the token from the planf3 `.env`. Each invocation auto-refreshes the token when its JWT is within 48 hours of expiry, so long-running planf3 sessions don't silently fail mid-plan.

To force-refresh manually:

```bash
hermes-oauth-codex refresh
```

## CLI

```bash
hermes-oauth-codex login                [--no-planf3-env] [--no-token-exchange] [--no-browser] [--port 1455] [--timeout 300]
hermes-oauth-codex refresh              [--no-planf3-env] [--no-token-exchange]
hermes-oauth-codex status [--json]
hermes-oauth-codex logout               --all | --id <hex6>
hermes-oauth-codex whoami               # decode id_token JWT claims
hermes-oauth-codex path                 # print resolved file paths
hermes-oauth-codex version
```

## How it works

1. Generate PKCE pair: 32 random bytes → base64url-no-pad verifier, SHA256 → base64url-no-pad challenge.
2. Bind `127.0.0.1:1455` (fallback `1457`) for the OAuth callback.
3. Open the user's browser to `https://auth.openai.com/oauth/authorize` with `code_challenge`, `code_challenge_method=S256`, `state=<secrets.token_urlsafe(32)>`, and the Codex-specific extras `id_token_add_organizations=true`, `codex_cli_simplified_flow=true`, `originator=codex_cli_rs`.
4. Wait for the callback (300s default). Validate the CSRF `state`.
5. POST `/oauth/token` (form-urlencoded): `grant_type=authorization_code`, `code`, `redirect_uri`, `code_verifier`. Returns `{access_token, refresh_token, id_token, expires_in}`.
6. Follow-up POST same endpoint: `grant_type=urn:ietf:params:oauth:grant-type:token-exchange`, `requested_token=openai-api-key`, `subject_token=<id_token>`. For **personal ChatGPT-Plus accounts** (no `organization_id` in the id_token) this is rejected; the module catches that specific failure and falls back to the OAuth `access_token` directly — exactly how Codex itself handles personal accounts.
7. Write the credential-pool entry + raw cache + planf3 `.env`.

## Reference patterns reused

- Hermes Anthropic-PKCE template: `agent/anthropic_adapter.py:972-1393` in `~/.hermes/hermes-agent/`
- Hermes credential-pool schema: `agent/credential_pool.py:131-175` (`PooledCredential` dataclass)
- OpenAI Codex PKCE flow: `codex-rs/login/src/server.rs` and `codex-rs/login/src/pkce.rs` in `github.com/openai/codex`
- Codex image generation: `plugins/image_gen/openai-codex/__init__.py` and `agent/auxiliary_client.py:_codex_cloudflare_headers` in `~/.hermes/hermes-agent/`

## License

MIT.
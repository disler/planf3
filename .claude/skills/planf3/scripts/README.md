# planf3 image scripts (OAuth-backed)

Drop-in replacements for planf3's `generate_gpt_image.py` and `edit_gpt_image.py`. Both target the Codex Responses API at `https://chatgpt.com/backend-api/codex/responses` using a ChatGPT-Plus OAuth bearer token (set in `OPENAI_API_KEY` by `hermes-oauth-codex login`), instead of the `api.openai.com/v1/images/generations` endpoint that requires a paid `sk-...` API key.

## Files

| File | Purpose |
| --- | --- |
| `_codex_common.py` | Shared auth + HTTP helpers. JWT decode, Cloudflare-friendly header builder, SSE streaming parser, auto-refresh-on-expiry. |
| `generate_gpt_image.py` | Generate one or more images from a text prompt. |
| `edit_gpt_image.py` | Edit one image, or compose two or more source images into a single new image. |

## Install

```bash
# From the planf3-chatgpt-pkce repo root:
cp planf3-image-scripts/*.py ~/.claude/skills/planf3/scripts/

# Then log in once (one-time):
python -m hermes_oauth_openai_codex login
```

Both scripts read `OPENAI_API_KEY` from `~/.claude/skills/planf3/.env` (via `python-dotenv`), so they're a no-op config swap once the login has populated the file.

## Usage

```bash
cd ~/.claude/skills/planf3

# Generate
python scripts/generate_gpt_image.py "A sunset over mountains" sunset.png --size 1024x1024 --quality medium

# Edit (one input)
python scripts/edit_gpt_image.py "Add a rainbow in the sky" edited.png photo.png

# Compose (multiple inputs)
python scripts/edit_gpt_image.py "Make a group photo" group.png p1.png p2.png p3.png
```

`--size` accepts the Codex Responses shapes (`1024x1024`, `1536x1024`, `1024x1536`, etc.); `--quality` is `low | medium | high`. `auto` is accepted and mapped to sensible defaults. CLI surface is otherwise identical to the originals.

## Auto-refresh

`_codex_common.refresh_if_needed()` is called at the start of every script invocation. It decodes the JWT's `exp` claim; if the token expires within 48 hours, it shells out to `python -m hermes_oauth_openai_codex refresh`, which rotates the OAuth token and rewrites both `~/.hermes/auth.json` and the planf3 `.env`. Pass `--refresh-skew-seconds 0` to disable, or any other value to widen/narrow the refresh window.

The rotation is automatic and silent — long-running planf3 sessions don't fail mid-plan when the token ages out.

## Environment variables

| Variable | Required | Set by |
| --- | --- | --- |
| `OPENAI_API_KEY` | yes | `hermes-oauth-codex login` (writes to planf3 `.env`) |
| `HERMES_OAUTH_PLANF3_ENV` | no | override planf3 `.env` path |

## What changes vs the originals

- Dropped the `openai` SDK dependency. The module uses `urllib` only — no runtime requirements beyond `python-dotenv`.
- Replaced the SDK call with a direct HTTP POST to the Codex Responses API.
- Added JWT-aware Cloudflare headers (originator / User-Agent / ChatGPT-Account-ID).
- Replaced SDK response parsing with a manual SSE stream reader that handles the latest Codex Responses event shapes (the pinned SDK sometimes doesn't know about them).
- Added the `refresh_if_needed` auto-rotation step on every invocation.
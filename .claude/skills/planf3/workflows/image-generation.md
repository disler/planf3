# Image Generation

Fill or update the embedded images in an existing plan `.html` file. Pick the sub-workflow based on the incoming `USER_PROMPT`:

| Sub-workflow | When to call it |
| --- | --- |
| Create | The prompt asks to generate, fill, or add the plan's images from scratch (empty `{{...IMAGE` slots) |
| Update | The prompt asks to change, refine, regenerate, or replace images that already exist in the plan |

Scripts (run with `uv run`, needs `OPENAI_API_KEY`):
- Create image: `uv run scripts/generate_gpt_image.py "<prompt>" <output.png> --size 1536x1024 --quality high`
- Edit image: `uv run scripts/edit_gpt_image.py "<instruction>" <output.png> <input.png> --size 1536x1024 --quality high`

## `OPENAI_API_KEY`

The scripts read `OPENAI_API_KEY` from `.env` via `python-dotenv`. Two ways to populate it:

1. **ChatGPT-Plus subscription (default)**: install and run the sibling skill `hermes-oauth-openai-codex` once — it performs a PKCE browser login and writes the OAuth bearer into this `.env`. No `sk-...` API key needed; the scripts hit `chatgpt.com/backend-api/codex/responses` with the bearer.
2. **OpenAI API key (legacy)**: paste an `sk-...` key into this `.env` directly. The scripts will fall back to `api.openai.com/v1/images/generations` if you swap the endpoint back.

The ChatGPT-Plus path is the default — it costs no API credits and works on the same subscription that powers ChatGPT image generation in the UI.

## Auto-refresh

`_codex_common.refresh_if_needed()` runs at the start of every script invocation. It decodes the JWT's `exp` claim; if the token expires within 48 hours, it shells out to `python -m hermes_oauth_openai_codex refresh` to rotate the token before the image call. Pass `--refresh-skew-seconds 0` to disable, or any other value to widen/narrow the window.

## Shared rules for every image prompt

- always generate in wide format (`--size 1536x1024`) at high quality (`--quality high`)
- convey the one or two core ideas of that section for a professional software engineer
- match the plan's synced visual identity (professional, focused, minimal)
- keep total words shown in the image under 10
- save images to `IMAGES_OUTPUT_DIR` (create it if missing)

## Create

1. Find slots - Grep the plan for `{{...IMAGE` placeholders (hero + per-phase). Each comment names the intended subject.
2. Write prompts - For each slot, write a prompt following the shared rules above.
3. Generate - Run `generate_gpt_image.py` once per slot, writing to `IMAGES_OUTPUT_DIR`.
4. Embed - Replace each `<!-- {{...IMAGE: ...}} -->` placeholder with `<img src="<plan-name>/<file>.png" alt="...">`, keeping the existing `<figure>`/`<figcaption>`.
5. Report - List the images generated and the slots filled.

## Update

1. Identify targets - From the `USER_PROMPT`, determine which embedded `<img>` images to change.
2. Write instruction - Write an edit instruction describing the change, following the shared rules above.
3. Edit - Run `edit_gpt_image.py` with the existing PNG as input, overwriting it (the script backs up the original first).
4. Verify embed - Confirm the `<img>` still points at the updated file; update `src`/`alt`/`<figcaption>` if the change warrants it.
5. Report - List the images updated and what changed.
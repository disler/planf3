#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "python-dotenv>=1.0",
# ]
# ///
"""
Generate images using ChatGPT-Plus OAuth via the Codex Responses API.

The Codex Responses endpoint at https://chatgpt.com/backend-api/codex/responses
accepts ChatGPT-Plus OAuth bearer tokens (stored in OPENAI_API_KEY by
`python -m hermes_oauth_openai_codex login`) and routes through the
image_generation tool. Same path Hermes's plugins/image_gen/openai-codex/
uses, just self-contained.

Usage:
    python generate_gpt_image.py "prompt" output.png [options]

Examples:
    python generate_gpt_image.py "A sunset over mountains" sunset.png
    python generate_gpt_image.py "Company logo" logo.png --size 1024x1024 --quality high
    python generate_gpt_image.py "Wide cinematic shot" wide.png --size 1536x1024

Environment:
    OPENAI_API_KEY - ChatGPT-Plus OAuth bearer token (set by hermes-oauth-codex login)

Auth helpers, HTTP streaming, JWT-decoded headers, and auto-refresh live in
`_codex_common.py` in the same directory.
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path
from typing import Any

# Local sibling — both this script and edit_gpt_image.py share _codex_common.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _codex_common import (  # noqa: E402
    DEFAULT_REFRESH_SKEW_SECONDS,
    IMAGE_MODEL,
    post_streaming,
    read_token,
    refresh_if_needed,
)

VALID_QUALITY = ["auto", "low", "medium", "high"]
VALID_FORMATS = ["png", "jpeg", "webp"]
VALID_BACKGROUND = ["auto", "opaque"]

POPULAR_SIZES = [
    "auto",
    "1024x1024",
    "1536x1024",
    "1024x1536",
    "2048x2048",
    "2048x1152",
    "1152x2048",
    "3840x2160",
    "2160x3840",
]


def _build_responses_payload(
    *,
    prompt: str,
    size: str,
    quality: str,
) -> dict[str, Any]:
    """Build the Codex Responses request body for an image_generation call.

    Mirrors hermes plugins/image_gen/openai-codex/__init__.py:_build_responses_payload.
    """
    return {
        "model": "gpt-5.5",
        "store": False,
        "instructions": (
            "You are an assistant that must fulfill image generation requests by "
            "using the image_generation tool when provided."
        ),
        "input": [{
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": prompt}],
        }],
        "tools": [{
            "type": "image_generation",
            "model": IMAGE_MODEL,
            "size": size,
            "quality": quality,
            "output_format": "png",
            "background": "opaque",
            "partial_images": 1,
        }],
        "tool_choice": {
            "type": "allowed_tools",
            "mode": "required",
            "tools": [{"type": "image_generation"}],
        },
        "stream": True,
    }


def _request_image(token: str, *, prompt: str, size: str, quality: str) -> str:
    payload = _build_responses_payload(prompt=prompt, size=size, quality=quality)
    return post_streaming(token, payload)


def generate_gpt_image(
    prompt: str,
    output_path: str,
    model: str = IMAGE_MODEL,
    size: str = "1024x1024",
    quality: str = "medium",
    n: int = 1,
    output_format: str = "png",
    background: str = "opaque",
    refresh_skew_seconds: int = DEFAULT_REFRESH_SKEW_SECONDS,
) -> None:
    """Generate one or more images via ChatGPT-Plus OAuth + Codex Responses."""
    refresh_if_needed(skew_seconds=refresh_skew_seconds)
    token = read_token()

    effective_size = size if size != "auto" else "1024x1024"
    effective_quality = quality if quality != "auto" else "medium"
    effective_bg = "opaque" if background == "auto" else background

    print(f"Model:      {model}")
    print(f"Size:       {effective_size}")
    print(f"Quality:    {effective_quality}")
    print(f"Format:     {output_format}")
    print(f"Background: {effective_bg}")
    print(f"Count:      {n}")
    print(f"Prompt:     {prompt[:120]}{'...' if len(prompt) > 120 else ''}")
    print()
    print("Generating image via Codex Responses API...")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        print(f"  [{i + 1}/{n}] streaming...")
        b64 = _request_image(
            token,
            prompt=prompt,
            size=effective_size,
            quality=effective_quality,
        )
        target = out if n == 1 else out.with_name(f"{out.stem}_{i + 1}{out.suffix}")
        target.write_bytes(base64.b64decode(b64))
        print(f"  Saved: {target}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate images using ChatGPT-Plus OAuth (gpt-image-2)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("prompt", help="Text prompt describing the image")
    parser.add_argument("output", help="Output file path (e.g., output.png)")
    parser.add_argument(
        "--model",
        "-m",
        default=IMAGE_MODEL,
        help=f"Image model ID (default: {IMAGE_MODEL})",
    )
    parser.add_argument(
        "--size",
        "-s",
        default="auto",
        help=(
            "Image size WxH (default: auto → 1024x1024). Popular: "
            + ", ".join(POPULAR_SIZES)
            + ". Codex Responses accepts 1024x1024, 1536x1024, 1024x1536, etc."
        ),
    )
    parser.add_argument(
        "--quality",
        "-q",
        default="auto",
        choices=VALID_QUALITY,
        help="Quality tier (default: auto → medium)",
    )
    parser.add_argument(
        "--count",
        "-n",
        type=int,
        default=1,
        help="Number of images to generate (default: 1; suffixes _1, _2, ... when >1)",
    )
    parser.add_argument(
        "--format",
        "-f",
        default="png",
        choices=VALID_FORMATS,
        help="Output format hint (default: png — Codex Responses is png-only currently)",
    )
    parser.add_argument(
        "--background",
        default="auto",
        choices=VALID_BACKGROUND,
        help="Background mode (default: auto → opaque)",
    )
    parser.add_argument(
        "--refresh-skew-seconds",
        type=int,
        default=DEFAULT_REFRESH_SKEW_SECONDS,
        help=(
            "Refresh the OAuth token when its JWT exp is within this many seconds "
            f"(default: {DEFAULT_REFRESH_SKEW_SECONDS} = 48h). Set to 0 to disable."
        ),
    )

    args = parser.parse_args()

    try:
        generate_gpt_image(
            prompt=args.prompt,
            output_path=args.output,
            model=args.model,
            size=args.size,
            quality=args.quality,
            n=args.count,
            output_format=args.format,
            background=args.background,
            refresh_skew_seconds=args.refresh_skew_seconds,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
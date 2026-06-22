#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "python-dotenv>=1.0",
# ]
# ///
"""
Edit/compose images using ChatGPT-Plus OAuth via the Codex Responses API.

Pass one or more input images. With multiple inputs, gpt-image-2 composes them
into a single new image based on the instruction. Source images are passed as
input_image parts (data: URIs) alongside the text instruction.

Usage:
    python edit_gpt_image.py "edit instruction" output.png input.png [more.png ...] [options]

Examples:
    python edit_gpt_image.py "Add a rainbow in the sky" edited.png photo.png
    python edit_gpt_image.py "Make a group photo" group.png p1.png p2.png p3.png

Environment:
    OPENAI_API_KEY - ChatGPT-Plus OAuth bearer token (set by hermes-oauth-codex login)

Auth helpers, HTTP streaming, JWT-decoded headers, and auto-refresh live in
`_codex_common.py` in the same directory.
"""

from __future__ import annotations

import argparse
import base64
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Local sibling — both this script and generate_gpt_image.py share _codex_common.
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


def backup_if_exists(output_path: str) -> None:
    """Copy an existing output file into ./backup/ before it gets overwritten.

    Edits often target a path that already holds an image (sometimes the input
    itself), so back the original up first — losing it to an edit is silent and
    unrecoverable. backup/ self-ignores via a backup/.gitignore of "*".
    """
    out = Path(output_path)
    if not out.exists():
        return
    backup_dir = Path.cwd() / "backup"
    backup_dir.mkdir(exist_ok=True)
    gitignore = backup_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backup_dir / f"{out.stem}_{ts}{out.suffix}"
    counter = 1
    while dest.exists():
        dest = backup_dir / f"{out.stem}_{ts}_{counter}{out.suffix}"
        counter += 1
    shutil.copy2(out, dest)
    print(f"Backed up existing {output_path} -> {dest}")


def _file_to_data_uri(path: str) -> str:
    """Read an image file and return a data: URI suitable for input_image.image_url."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Input image not found: {path}")
    suffix = p.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "application/octet-stream")
    data = p.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _build_responses_payload(
    *,
    instruction: str,
    input_image_uris: list[str],
    size: str,
    quality: str,
) -> dict[str, Any]:
    """Build the Codex Responses payload for an edit/composition call.

    The input_image content parts are the Responses-API equivalent of the
    OpenAI `images.edit` SDK call's `image` parameter. Multiple input images
    enable composition (Hermes uses the same shape for multi-source edits).
    """
    content: list[dict[str, Any]] = [{"type": "input_text", "text": instruction}]
    for uri in input_image_uris:
        content.append({"type": "input_image", "image_url": uri})

    return {
        "model": "gpt-5.5",
        "store": False,
        "instructions": (
            "You are an assistant that must fulfill image editing / composition "
            "requests by using the image_generation tool when provided. Treat "
            "any input_image parts as the source images to edit or combine."
        ),
        "input": [{
            "type": "message",
            "role": "user",
            "content": content,
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


def edit_gpt_image(
    input_paths: list[str],
    instruction: str,
    output_path: str,
    model: str = IMAGE_MODEL,
    size: str = "1024x1024",
    quality: str = "medium",
    output_format: str = "png",
    background: str = "opaque",
    refresh_skew_seconds: int = DEFAULT_REFRESH_SKEW_SECONDS,
) -> None:
    """Edit/compose images via ChatGPT-Plus OAuth + Codex Responses."""
    refresh_if_needed(skew_seconds=refresh_skew_seconds)
    token = read_token()

    for p in input_paths:
        if not os.path.exists(p):
            raise FileNotFoundError(f"Input image not found: {p}")

    effective_size = size if size != "auto" else "1024x1024"
    effective_quality = quality if quality != "auto" else "medium"
    effective_bg = "opaque" if background == "auto" else background

    print(f"Model:      {model}")
    print(f"Inputs:     {', '.join(input_paths)}")
    print(f"Size:       {effective_size}")
    print(f"Quality:    {effective_quality}")
    print(f"Format:     {output_format}")
    print(f"Background: {effective_bg}")
    print(f"Prompt:     {instruction[:120]}{'...' if len(instruction) > 120 else ''}")
    print()
    print("Editing image via Codex Responses API...")

    input_uris = [_file_to_data_uri(p) for p in input_paths]
    payload = _build_responses_payload(
        instruction=instruction,
        input_image_uris=input_uris,
        size=effective_size,
        quality=effective_quality,
    )
    b64 = post_streaming(token, payload)

    backup_if_exists(output_path)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_bytes(base64.b64decode(b64))
    print(f"Saved: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Edit/compose images using ChatGPT-Plus OAuth (gpt-image-2)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("instruction", help="Edit/compose instruction")
    parser.add_argument("output", help="Output file path")
    parser.add_argument(
        "inputs",
        nargs="+",
        help="One or more input image paths (multiple = composition)",
    )
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
            "Image size WxH (default: auto → 1024x1024). "
            "Codex Responses accepts 1024x1024, 1536x1024, 1024x1536, etc."
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
        edit_gpt_image(
            input_paths=args.inputs,
            instruction=args.instruction,
            output_path=args.output,
            model=args.model,
            size=args.size,
            quality=args.quality,
            output_format=args.format,
            background=args.background,
            refresh_skew_seconds=args.refresh_skew_seconds,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
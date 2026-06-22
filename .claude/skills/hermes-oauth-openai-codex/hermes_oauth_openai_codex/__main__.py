"""Entry point for `python -m hermes_oauth_openai_codex`."""
from __future__ import annotations

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
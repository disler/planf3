"""Argparse CLI surface for hermes-oauth-codex.

Subcommands:
    login                Run the PKCE flow end-to-end.
    refresh              Refresh tokens using stored refresh_token.
    status [--json]      List credential-pool entries for this provider.
    logout               Remove one or all entries.
    whoami               Decode id_token JWT claims (no signature verify).
    path                 Print the resolved file paths.
    version              Print version and exit.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from typing import Any

from . import __version__, auth_json, login, planf3_env, refresh


def cmd_login(args: argparse.Namespace) -> int:
    login.run_login(
        primary_port=args.port or 1455,
        fallback_port=1457,
        do_token_exchange=not args.no_token_exchange,
        update_planf3_env=not args.no_planf3_env,
        open_browser=not args.no_browser,
        timeout_seconds=args.timeout,
    )
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    refresh.run_refresh(
        do_token_exchange=not args.no_token_exchange,
        update_planf3_env=not args.no_planf3_env,
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    entries = auth_json.list_pool_entries(auth_json_path_value=auth_json.auth_json_path())
    if args.json:
        print(json.dumps({"provider": auth_json.PROVIDER_KEY, "entries": entries}, indent=2, default=str))
    else:
        print(f"Provider: {auth_json.PROVIDER_KEY}")
        print(f"Path: {auth_json.auth_json_path()}")
        if not entries:
            print("  (no entries — run `hermes-oauth-codex login`)")
            return 0
        for e in entries:
            print(f"  - id={e.get('id')} label={e.get('label')!r}")
            print(f"      auth_type={e.get('auth_type')} source={e.get('source')}")
            print(f"      expires_at_ms={e.get('expires_at_ms')}")
            print(f"      last_status={e.get('last_status')}")
            print(f"      fingerprint={e.get('secret_fingerprint')}")
            if e.get("email"):
                print(f"      email={e.get('email')}")
            if e.get("organization_id"):
                print(f"      organization_id={e.get('organization_id')}")
    return 0


def cmd_logout(args: argparse.Namespace) -> int:
    if args.all:
        n = auth_json.remove_pool_entry(
            auth_json_path_value=auth_json.auth_json_path(),
            remove_all=True,
        )
        print(f"Removed {n} entries from {auth_json.PROVIDER_KEY}.")
    elif args.id:
        n = auth_json.remove_pool_entry(
            auth_json_path_value=auth_json.auth_json_path(),
            entry_id=args.id,
        )
        print(f"Removed {n} entries.")
    else:
        print("Specify --all or --id <hex6>.", file=sys.stderr)
        return 2
    return 0


def _decode_jwt_payload(jwt: str) -> dict[str, Any] | None:
    parts = jwt.split(".")
    if len(parts) < 2:
        return None
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except Exception:
        return None


def cmd_whoami(args: argparse.Namespace) -> int:
    raw = auth_json.load_raw_token_cache(auth_json.raw_token_path())
    if not raw or not raw.get("idToken"):
        print("No id_token in raw cache. Run `login` first.", file=sys.stderr)
        return 1
    claims = _decode_jwt_payload(raw["idToken"])
    if not claims:
        print("id_token present but not a parseable JWT.", file=sys.stderr)
        return 1
    print(json.dumps(claims, indent=2))
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    print(f"auth_json:  {auth_json.auth_json_path()}")
    print(f"raw_cache:  {auth_json.raw_token_path()}")
    print(f"planf3_env: {planf3_env.planf3_env_path()}")
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    print(f"hermes-oauth-codex {__version__}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hermes-oauth-codex",
        description="ChatGPT-Plus OAuth PKCE login for Hermes's auth.json shape.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("login", help="Run the PKCE flow end-to-end.")
    sp.add_argument("--port", type=int, default=None, help="Primary callback port (default 1455).")
    sp.add_argument("--timeout", type=int, default=300, help="Callback timeout seconds (default 300).")
    sp.add_argument("--no-planf3-env", action="store_true", help="Skip updating planf3 .env.")
    sp.add_argument("--no-token-exchange", action="store_true", help="Skip the id_token -> API key step.")
    sp.add_argument("--no-browser", action="store_true", help="Don't open the browser (URL printed for manual paste).")
    sp.set_defaults(func=cmd_login)

    sp = sub.add_parser("refresh", help="Refresh stored tokens.")
    sp.add_argument("--no-planf3-env", action="store_true", help="Skip updating planf3 .env.")
    sp.add_argument("--no-token-exchange", action="store_true", help="Skip the id_token -> API key step.")
    sp.set_defaults(func=cmd_refresh)

    sp = sub.add_parser("status", help="Show credential-pool entries for this provider.")
    sp.add_argument("--json", action="store_true", help="Machine-readable JSON output.")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("logout", help="Remove credential-pool entries.")
    grp = sp.add_mutually_exclusive_group(required=True)
    grp.add_argument("--all", action="store_true", help="Remove all entries for this provider.")
    grp.add_argument("--id", dest="id", help="Remove a specific entry by its 6-char hex id.")
    sp.set_defaults(func=cmd_logout)

    sp = sub.add_parser("whoami", help="Decode id_token JWT claims.")
    sp.set_defaults(func=cmd_whoami)

    sp = sub.add_parser("path", help="Print resolved file paths.")
    sp.set_defaults(func=cmd_path)

    sp = sub.add_parser("version", help="Print version and exit.")
    sp.set_defaults(func=cmd_version)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
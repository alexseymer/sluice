"""Interactive `sluice setup` flow."""

from __future__ import annotations

import argparse
import asyncio
import getpass
from pathlib import Path

from sluice.config import load_settings
from sluice.setup.envfile import upsert_env_file
from sluice.setup.github_oauth import (
    DeviceCode,
    GitHubAuthError,
    authorize_github,
    detect_github_repo_from_git,
    parse_github_repo,
)
from sluice.setup.matrix_provision import MatrixSetupError, provision_matrix


def _prompt(label: str, *, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    if value:
        return value
    if default is not None:
        return default
    return ""


def _prompt_secret(label: str) -> str:
    return getpass.getpass(f"{label}: ")


def _print_device_code(device: DeviceCode) -> None:
    print()
    print("Authorize Sluice on GitHub:")
    print(f"  1. Open {device.verification_uri}")
    print(f"  2. Enter code: {device.user_code}")
    print("  Waiting for approval...")
    print()


async def _setup_github(*, env_path: Path, client_id: str | None) -> dict[str, str]:
    print("\n=== GitHub ===")
    detected = detect_github_repo_from_git()
    repo_value = _prompt("Repository (owner/repo)", default=detected)
    owner, repo = parse_github_repo(repo_value)

    oauth_client_id = client_id or _prompt(
        "GitHub OAuth App client ID\n"
        "  (create an OAuth App at https://github.com/settings/developers,\n"
        "   enable Device Flow, callback can be http://127.0.0.1)"
    )
    if not oauth_client_id:
        raise GitHubAuthError("OAuth App client ID is required for device-flow setup")

    result = await authorize_github(
        client_id=oauth_client_id,
        owner=owner,
        repo=repo,
        on_user_code=_print_device_code,
    )
    print(f"GitHub OK as {result.login} → {result.owner}/{result.repo}")
    values = {
        "SLUICE_FORGE_BACKEND": "github",
        "SLUICE_GITHUB_OWNER": result.owner,
        "SLUICE_GITHUB_REPO": result.repo,
        "SLUICE_GITHUB_TOKEN": result.token,
        "SLUICE_GITHUB_OAUTH_CLIENT_ID": oauth_client_id,
    }
    upsert_env_file(env_path, values)
    return values


async def _setup_matrix(*, env_path: Path) -> dict[str, str]:
    print("\n=== Matrix ===")
    print(
        "Setup will log in as you, create a @sluice-bot user, and open a private room."
    )
    homeserver = _prompt("Homeserver URL", default="https://matrix.example.com")
    operator = _prompt("Your Matrix user (mxid or localpart)")
    password = _prompt_secret("Your Matrix password")
    if not operator or not password:
        raise MatrixSetupError("Operator user and password are required")

    print(
        "\nTo create the bot without open registration, paste Synapse's "
        "registration_shared_secret (homeserver.yaml)."
    )
    print("Leave blank to try open / token-based registration instead.")
    shared_secret = _prompt_secret("registration_shared_secret (optional)")
    registration_token = ""
    if not shared_secret:
        registration_token = _prompt(
            "Registration token (optional, if your server requires one)",
            default="",
        )
    bot_localpart = _prompt("Bot localpart", default="sluice-bot")

    result = await provision_matrix(
        homeserver=homeserver,
        operator_user=operator,
        operator_password=password,
        shared_secret=shared_secret or None,
        registration_token=registration_token or None,
        bot_localpart=bot_localpart or "sluice-bot",
    )
    print(f"Matrix OK — bot {result.bot_user_id} in room {result.room_id}")
    print(f"Accept the invite in your client as {result.allowed_sender}.")
    values = {
        "SLUICE_CHAT_BACKEND": "matrix",
        "SLUICE_MATRIX_HOMESERVER": result.homeserver,
        "SLUICE_MATRIX_USER_ID": result.bot_user_id,
        "SLUICE_MATRIX_ACCESS_TOKEN": result.bot_access_token,
        "SLUICE_MATRIX_ROOM_ID": result.room_id,
        "SLUICE_MATRIX_ALLOWED_SENDER": result.allowed_sender,
    }
    upsert_env_file(env_path, values)
    return values


async def run_setup_async(args: argparse.Namespace) -> int:
    env_path = Path(args.env_file)
    print(f"Writing credentials to {env_path.resolve()}")
    do_github = not args.matrix_only
    do_matrix = not args.github_only
    settings = load_settings()
    client_id = args.github_client_id or settings.github_oauth_client_id

    try:
        if do_github:
            await _setup_github(env_path=env_path, client_id=client_id)
        if do_matrix:
            await _setup_matrix(env_path=env_path)
    except (GitHubAuthError, MatrixSetupError) as exc:
        print(f"\nSetup failed: {exc}")
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled.")
        return 130

    print("\nSetup complete. Start Sluice with: sluice")
    return 0


def run_setup(args: argparse.Namespace) -> int:
    return asyncio.run(run_setup_async(args))


def add_setup_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "setup",
        help="Interactive setup: GitHub device login + Matrix bot/room provisioning",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to write credentials (default: .env)",
    )
    parser.add_argument(
        "--github-only",
        action="store_true",
        help="Only configure GitHub",
    )
    parser.add_argument(
        "--matrix-only",
        action="store_true",
        help="Only configure Matrix",
    )
    parser.add_argument(
        "--github-client-id",
        default=None,
        help="GitHub OAuth App client ID (Device Flow enabled)",
    )
    parser.set_defaults(handler=run_setup)

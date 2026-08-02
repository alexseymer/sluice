"""Interactive `sluice setup` flow."""

from __future__ import annotations

import argparse
import asyncio
import getpass
from pathlib import Path

from sluice.config import SluiceSettings, load_settings
from sluice.setup.envfile import upsert_env_file
from sluice.setup.github_oauth import (
    DeviceCode,
    GitHubAuthError,
    authorize_github,
    detect_github_repo_from_git,
    parse_github_repo,
    verify_github_token,
)
from sluice.setup.matrix_provision import (
    BotAlreadyExistsError,
    MatrixProvisionResult,
    MatrixSetupError,
    RegistrationDisabledError,
    localpart_from_mxid,
    provision_matrix,
    verify_matrix_bot,
)


def _prompt(label: str, *, default: str | None = None) -> str:
    shown = default.strip() if isinstance(default, str) else default
    if not shown:
        shown = None
    suffix = f" [{shown}]" if shown else ""
    value = input(f"{label}{suffix}: ").strip()
    if value:
        return value
    if shown is not None:
        return shown
    return ""


def _prompt_secret(label: str, *, saved: str | None = None) -> str:
    """Prompt for a secret; Enter keeps `saved` when provided."""
    if saved:
        value = getpass.getpass(f"{label} [saved — press Enter to keep]: ")
        return value if value else saved
    return getpass.getpass(f"{label}: ")


def _print_device_code(device: DeviceCode) -> None:
    print()
    print("Authorize Sluice on GitHub:")
    print(f"  1. Open {device.verification_uri}")
    print(f"  2. Enter code: {device.user_code}")
    print("  Waiting for approval...")
    print()


def _bot_localpart_default(user_id: str | None) -> str:
    if not user_id:
        return "sluice-bot"
    try:
        return localpart_from_mxid(user_id)
    except MatrixSetupError:
        return "sluice-bot"


def _matrix_values_from_result(
    result: MatrixProvisionResult,
    *,
    operator_password: str | None = None,
) -> dict[str, str]:
    values = {
        "SLUICE_CHAT_BACKEND": "matrix",
        "SLUICE_MATRIX_HOMESERVER": result.homeserver,
        "SLUICE_MATRIX_USER_ID": result.bot_user_id,
        "SLUICE_MATRIX_ACCESS_TOKEN": result.bot_access_token,
        "SLUICE_MATRIX_ROOM_ID": result.room_id,
        "SLUICE_MATRIX_ALLOWED_SENDER": result.allowed_sender,
    }
    if result.bot_password:
        values["SLUICE_MATRIX_BOT_PASSWORD"] = result.bot_password
    if operator_password:
        values["SLUICE_MATRIX_OPERATOR_PASSWORD"] = operator_password
    return values


async def _setup_github(
    *,
    env_path: Path,
    settings: SluiceSettings,
    client_id: str | None,
    force_auth: bool = False,
) -> dict[str, str]:
    print("\n=== GitHub ===")
    existing_owner = settings.github_owner
    existing_repo = settings.github_repo
    existing_token = settings.github_token
    detected = detect_github_repo_from_git()
    default_repo = (
        f"{existing_owner}/{existing_repo}"
        if existing_owner and existing_repo
        else detected
    )
    repo_value = _prompt("Repository (owner/repo)", default=default_repo)
    owner, repo = parse_github_repo(repo_value)

    if not force_auth and existing_token:
        reused = await verify_github_token(token=existing_token, owner=owner, repo=repo)
        if reused is not None:
            print(f"GitHub already authorized as {reused.login} → {owner}/{repo}")
            values = {
                "SLUICE_FORGE_BACKEND": "github",
                "SLUICE_GITHUB_OWNER": owner,
                "SLUICE_GITHUB_REPO": repo,
                "SLUICE_GITHUB_TOKEN": existing_token,
            }
            if client_id:
                values["SLUICE_GITHUB_OAUTH_CLIENT_ID"] = client_id
            upsert_env_file(env_path, values)
            return values
        print("Existing GitHub token is missing or invalid — starting device login.")

    oauth_client_id = _prompt(
        "GitHub OAuth App client ID\n"
        "  (create an OAuth App at https://github.com/settings/developers,\n"
        "   enable Device Flow, callback can be http://127.0.0.1)",
        default=client_id,
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


async def _setup_matrix(
    *,
    env_path: Path,
    settings: SluiceSettings,
    force: bool = False,
) -> dict[str, str]:
    print("\n=== Matrix ===")

    if (
        not force
        and settings.matrix_homeserver
        and settings.matrix_access_token
        and settings.matrix_room_id
    ):
        bot_id = await verify_matrix_bot(
            homeserver=settings.matrix_homeserver,
            access_token=settings.matrix_access_token,
            room_id=settings.matrix_room_id,
            expected_localpart=_bot_localpart_default(settings.matrix_user_id),
        )
        if bot_id:
            print(
                f"Matrix already configured — {bot_id} in {settings.matrix_room_id} "
                "(use --force-matrix-setup to redo)."
            )
            values = {
                "SLUICE_CHAT_BACKEND": "matrix",
                "SLUICE_MATRIX_HOMESERVER": settings.matrix_homeserver,
                "SLUICE_MATRIX_USER_ID": bot_id,
                "SLUICE_MATRIX_ACCESS_TOKEN": settings.matrix_access_token,
                "SLUICE_MATRIX_ROOM_ID": settings.matrix_room_id,
                "SLUICE_MATRIX_ALLOWED_SENDER": settings.matrix_allowed_sender or "",
            }
            if settings.matrix_bot_password:
                values["SLUICE_MATRIX_BOT_PASSWORD"] = settings.matrix_bot_password
            if settings.matrix_operator_password:
                values["SLUICE_MATRIX_OPERATOR_PASSWORD"] = settings.matrix_operator_password
            upsert_env_file(env_path, values)
            return values
        print("Saved Matrix credentials are incomplete or invalid — continuing setup.")

    print(
        "Setup will log in as you, ensure the bot user exists, and open a private room."
    )
    print("Press Enter to keep values shown in [brackets].")
    homeserver = _prompt(
        "Homeserver URL",
        default=settings.matrix_homeserver or "https://matrix.example.com",
    )
    operator = _prompt(
        "Your Matrix user (mxid or localpart)",
        default=settings.matrix_allowed_sender,
    )
    password = _prompt_secret(
        "Your Matrix password",
        saved=settings.matrix_operator_password,
    )
    if not operator or not password:
        raise MatrixSetupError("Operator user and password are required")

    bot_localpart = _prompt(
        "Bot localpart",
        default=_bot_localpart_default(settings.matrix_user_id),
    )

    print(
        "\nIf the homeserver has registration closed, paste Synapse's "
        "registration_shared_secret from homeserver.yaml."
    )
    print("Leave blank to reuse an existing bot via password/token instead.")
    shared_secret = _prompt_secret("registration_shared_secret (optional)") or None
    registration_token: str | None = None
    if not shared_secret:
        registration_token = (
            _prompt(
                "Registration token (optional)",
                default="",
            )
            or None
        )

    bot_password = settings.matrix_bot_password
    existing_token = settings.matrix_access_token
    existing_room = settings.matrix_room_id

    try:
        result = await provision_matrix(
            homeserver=homeserver,
            operator_user=operator,
            operator_password=password,
            shared_secret=shared_secret,
            registration_token=registration_token,
            bot_localpart=bot_localpart or "sluice-bot",
            existing_bot_token=existing_token,
            existing_room_id=existing_room,
            bot_password=bot_password,
        )
    except (BotAlreadyExistsError, RegistrationDisabledError) as exc:
        print(f"\n{exc}")
        if not shared_secret:
            print(
                "Provide the Synapse registration_shared_secret to create the bot, "
                "or log into an existing bot account."
            )
            shared_secret = _prompt_secret("registration_shared_secret (optional)") or None
        bot_password = _prompt_secret(
            "Existing bot password (leave blank to paste a token instead)",
            saved=settings.matrix_bot_password,
        )
        token_override = None
        if not bot_password and not shared_secret:
            token_override = _prompt(
                "Bot access token",
                default=settings.matrix_access_token,
            )
            if not token_override:
                raise MatrixSetupError(
                    "Need registration_shared_secret, bot password, or access token."
                ) from exc
        result = await provision_matrix(
            homeserver=homeserver,
            operator_user=operator,
            operator_password=password,
            shared_secret=shared_secret,
            registration_token=None,
            bot_localpart=bot_localpart or "sluice-bot",
            existing_bot_token=token_override or existing_token,
            existing_room_id=existing_room,
            bot_password=bot_password or None,
        )

    print(f"Matrix OK — bot {result.bot_user_id} in room {result.room_id}")
    print(f"Accept the invite in your client as {result.allowed_sender}.")
    values = _matrix_values_from_result(result, operator_password=password)
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
            await _setup_github(
                env_path=env_path,
                settings=settings,
                client_id=client_id,
                force_auth=args.force_github_auth,
            )
        if do_matrix:
            await _setup_matrix(
                env_path=env_path,
                settings=settings,
                force=args.force_matrix_setup,
            )
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
    parser.add_argument(
        "--force-github-auth",
        action="store_true",
        help="Re-run GitHub device login even if an existing token still works",
    )
    parser.add_argument(
        "--force-matrix-setup",
        action="store_true",
        help="Re-run Matrix prompts even if saved bot credentials still work",
    )
    parser.set_defaults(handler=run_setup)

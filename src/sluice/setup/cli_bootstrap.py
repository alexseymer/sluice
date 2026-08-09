"""Matrix-assisted primary CLI setup during `sluice setup`."""

from __future__ import annotations

from sluice.adapters.matrix_chat import MatrixChatAdapter
from sluice.config import SluiceSettings
from sluice.setup.cli_runtime import (
    SPECS,
    bootstrap_ai_clis,
    configured_cli_path,
    ensure_runtime_paths,
    is_backend_authenticated,
)


class PrimaryCliSetupError(RuntimeError):
    """Primary CLI could not be installed or authenticated."""


def matrix_is_configured(settings: SluiceSettings) -> bool:
    return bool(
        settings.matrix_homeserver
        and settings.matrix_room_id
        and settings.matrix_access_token
    )


def build_matrix_chat(settings: SluiceSettings) -> MatrixChatAdapter:
    return MatrixChatAdapter(
        homeserver=settings.matrix_homeserver or "",
        room_id=settings.matrix_room_id or "",
        access_token=settings.matrix_access_token or "",
        user_id=settings.matrix_user_id,
        allowed_sender=settings.matrix_allowed_sender,
        store_path=settings.data_dir / "matrix-setup-store",
        sync_timeout_ms=settings.matrix_sync_timeout_ms,
    )


async def primary_cli_already_ready(settings: SluiceSettings) -> bool:
    backend_id = settings.primary_backend_id()
    spec = SPECS.get(backend_id)
    if spec is None:
        return False
    home = settings.resolved_cli_home_dir
    ensure_runtime_paths(home)
    return await is_backend_authenticated(
        backend_id=backend_id,
        spec=spec,
        home=home,
        configured_path=configured_cli_path(settings, backend_id),
    )


async def setup_primary_cli(
    *,
    settings: SluiceSettings,
    force: bool = False,
) -> None:
    """Install and sign in the primary CLI agent over Matrix."""
    if not matrix_is_configured(settings):
        raise PrimaryCliSetupError("Matrix is not configured — run Matrix setup first.")

    primary = settings.primary_backend_id()
    if not force and await primary_cli_already_ready(settings):
        print(f"Primary CLI ({primary}) is already signed in.")
        return

    print("\n=== Primary CLI agent ===")
    print(
        f"Next we'll prove Matrix ↔ CLI works by signing in {primary!r} in your chat room."
    )
    print("Accept the room invite in your Matrix client if you have not already.")
    print("Watch the room for login prompts — this may take a few minutes.\n")

    chat = build_matrix_chat(settings)
    await chat.start()
    try:
        await bootstrap_ai_clis(
            settings=settings,
            chat=chat,
            home=settings.resolved_cli_home_dir,
            backend_ids=[primary],
            intro=(
                f"Sluice setup — signing in your primary CLI agent ({primary}).\n"
                "(Install + subscription login — no metered chat API.)"
            ),
            outro=(
                f"Primary CLI ({primary}) setup finished. "
                "Start Sluice with `sluice` — any other enabled agents will sign in here too."
            ),
        )
    finally:
        await chat.stop()

    if not await primary_cli_already_ready(settings):
        raise PrimaryCliSetupError(
            f"Primary CLI ({primary}) is still not signed in. "
            "Re-run setup or say `/cli-auth` in Matrix after starting Sluice."
        )

    print(f"Primary CLI OK — {primary} is signed in via Matrix.")

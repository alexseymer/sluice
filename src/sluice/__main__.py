"""CLI entrypoint for Sluice."""

from __future__ import annotations

import argparse
import asyncio

import structlog

from sluice import __version__
from sluice.config import load_settings
from sluice.core.app import SluiceApp
from sluice.core.chat_loop import run_chat_loop

log = structlog.get_logger()


async def _run() -> int:
    settings = load_settings()
    app = SluiceApp(settings)
    await app.start()
    log.info(
        "sluice_ready",
        chat=settings.chat_backend,
        forge=settings.forge_backend,
        ai_backend=settings.ai_backend,
        chat_running=app.chat.is_running,
        next_jour_fixe=str(app.jour_fixe.next_scheduled_at()),
    )
    try:
        await run_chat_loop(app)
    finally:
        await app.stop()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="sluice", description="AI work orchestrator")
    parser.add_argument("--version", action="version", version=f"sluice {__version__}")
    parser.parse_args()

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
    )

    try:
        raise SystemExit(asyncio.run(_run()))
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()

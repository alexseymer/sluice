"""CLI entrypoint for Sluice."""

from __future__ import annotations

import argparse
import asyncio

import structlog

from sluice import __version__
from sluice.config import load_settings
from sluice.core.app import SluiceApp
from sluice.core.chat_loop import run_chat_loop
from sluice.core.dispatch_loop import run_dispatch_loop
from sluice.core.forge_sync import run_forge_sync_loop
from sluice.core.jour_fixe_scheduler import run_jour_fixe_scheduler
from sluice.setup.cli import add_setup_parser

log = structlog.get_logger()


async def _run_daemon() -> int:
    settings = load_settings()
    app = SluiceApp(settings)
    await app.start()
    log.info(
        "sluice_ready",
        chat=settings.chat_backend,
        forge=settings.forge_backend,
        ai_backends=sorted(app.backends.keys()),
        chat_running=app.chat.is_running,
        next_jour_fixe=str(app.jour_fixe.next_scheduled_at()),
    )
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(run_jour_fixe_scheduler(app), name="jour-fixe-scheduler")
            tg.create_task(run_dispatch_loop(app), name="dispatch-loop")
            tg.create_task(run_forge_sync_loop(app), name="forge-sync")
            tg.create_task(run_chat_loop(app), name="chat-loop")
    finally:
        await app.stop()
    return 0


def _run_daemon_cmd(_args: argparse.Namespace) -> int:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
    )
    try:
        return asyncio.run(_run_daemon())
    except KeyboardInterrupt:
        return 130


def main() -> None:
    parser = argparse.ArgumentParser(prog="sluice", description="AI work orchestrator")
    parser.add_argument("--version", action="version", version=f"sluice {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Start the Sluice daemon (default)")
    run_parser.set_defaults(handler=_run_daemon_cmd)
    add_setup_parser(subparsers)

    args = parser.parse_args()
    handler = getattr(args, "handler", None)
    if handler is None:
        # `sluice` with no subcommand starts the daemon (back-compat).
        raise SystemExit(_run_daemon_cmd(args))
    raise SystemExit(handler(args))


if __name__ == "__main__":
    main()

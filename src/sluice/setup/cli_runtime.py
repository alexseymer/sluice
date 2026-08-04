"""Install and authenticate AI coding CLIs inside the Sluice host/container."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import structlog

from sluice.adapters.chat import ChatAdapter, IncomingMessage, OutgoingMessage
from sluice.config import SluiceSettings

log = structlog.get_logger()

_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/+=]{3,128}$")

SendFn = Callable[[str], Awaitable[None]]
WaitFn = Callable[[float], Awaitable[IncomingMessage]]


@dataclass(frozen=True)
class CliSpec:
    backend_id: str
    binary: str
    install_command: str
    auth_kind: str  # "link" | "link_and_code" | "none"
    login_argv: tuple[str, ...]
    status_argv: tuple[str, ...] | None = None
    authenticated_marker: str | None = None  # substring that means logged in
    unauthenticated_marker: str | None = None


SPECS: dict[str, CliSpec] = {
    "cursor": CliSpec(
        backend_id="cursor",
        binary="agent",
        install_command="curl -fsSL https://cursor.com/install | bash",
        auth_kind="link",
        login_argv=("login",),
        status_argv=("status",),
        unauthenticated_marker="not logged in",
    ),
    "agy": CliSpec(
        backend_id="agy",
        binary="agy",
        install_command="curl -fsSL https://antigravity.google/cli/install.sh | bash",
        auth_kind="link_and_code",
        login_argv=("auth", "login"),
        status_argv=None,
    ),
    "claude_code": CliSpec(
        backend_id="claude_code",
        binary="claude",
        install_command="curl -fsSL https://claude.ai/install.sh | bash",
        auth_kind="link",
        login_argv=(),  # first interactive use usually triggers auth
        status_argv=None,
    ),
    "codex": CliSpec(
        backend_id="codex",
        binary="codex",
        install_command=(
            "curl -fsSL https://deb.nodesource.com/setup_22.x | bash - "
            "&& apt-get install -y nodejs "
            "&& npm install -g @openai/codex"
        ),
        auth_kind="none",
        login_argv=(),
    ),
}


def local_bin_dir(home: Path) -> Path:
    return home / ".local" / "bin"


def ensure_runtime_paths(home: Path) -> None:
    """Create persistent home layout used by CLI installers and credentials."""
    home.mkdir(parents=True, exist_ok=True)
    local_bin_dir(home).mkdir(parents=True, exist_ok=True)
    (home / ".gemini" / "antigravity-cli").mkdir(parents=True, exist_ok=True)
    (home / ".cursor").mkdir(parents=True, exist_ok=True)


def cli_env(home: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    bin_dir = str(local_bin_dir(home))
    path = env.get("PATH", "")
    if bin_dir not in path.split(os.pathsep):
        env["PATH"] = f"{bin_dir}{os.pathsep}{path}" if path else bin_dir
    env["HOME"] = str(home)
    env["GEMINI_FORCE_FILE_STORAGE"] = "true"
    env["NO_OPEN_BROWSER"] = "1"
    # Headless / Docker: avoid GUI keyring for Google auth persistence.
    env.setdefault("BROWSER", "echo")
    return env


def resolve_binary(spec: CliSpec, home: Path, configured_path: str | None = None) -> str | None:
    candidates: list[str] = []
    if configured_path:
        candidates.append(configured_path)
    candidates.append(str(local_bin_dir(home) / spec.binary))
    candidates.append(spec.binary)
    for candidate in candidates:
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
        found = shutil.which(candidate, path=cli_env(home).get("PATH"))
        if found:
            return found
    return None


def extract_first_url(text: str) -> str | None:
    match = _URL_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip(").,;\"'")


def looks_like_auth_code(text: str) -> bool:
    candidate = text.strip().split()[0] if text.strip() else ""
    if not candidate or candidate.startswith("/"):
        return False
    return bool(_CODE_RE.match(candidate))


def agy_token_path(home: Path) -> Path:
    return home / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"


async def _run_shell(command: str, *, env: dict[str, str], timeout: float) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        with contextlib.suppress(ProcessLookupError):
            await proc.wait()
        return 124, "install timed out"
    output = (stdout or b"").decode("utf-8", errors="replace")
    return proc.returncode or 0, output


async def install_cli(spec: CliSpec, *, home: Path, timeout: float = 600.0) -> tuple[bool, str]:
    env = cli_env(home)
    if resolve_binary(spec, home) is not None:
        return True, f"{spec.binary} already installed"
    log.info("cli_install_start", backend=spec.backend_id, command=spec.install_command)
    code, output = await _run_shell(spec.install_command, env=env, timeout=timeout)
    if code != 0:
        log.warning(
            "cli_install_failed",
            backend=spec.backend_id,
            code=code,
            output=output[-800:],
        )
        return False, output[-800:] or f"install failed with code {code}"
    if resolve_binary(spec, home) is None:
        return False, f"install finished but {spec.binary!r} not found on PATH"
    log.info("cli_install_ok", backend=spec.backend_id)
    return True, "installed"


async def _read_until_url(
    proc: asyncio.subprocess.Process,
    *,
    timeout: float,
) -> tuple[str | None, str]:
    assert proc.stdout is not None
    buffer = ""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return None, buffer
        try:
            chunk = await asyncio.wait_for(proc.stdout.read(256), timeout=remaining)
        except TimeoutError:
            return None, buffer
        if not chunk:
            return extract_first_url(buffer), buffer
        buffer += chunk.decode("utf-8", errors="replace")
        url = extract_first_url(buffer)
        if url:
            return url, buffer


async def is_cursor_authenticated(binary: str, home: Path) -> bool:
    env = cli_env(home)
    proc = await asyncio.create_subprocess_exec(
        binary,
        "status",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    stdout, _ = await proc.communicate()
    text = (stdout or b"").decode("utf-8", errors="replace").lower()
    if "not logged in" in text or "not authenticated" in text:
        return False
    return bool(proc.returncode == 0 and text.strip())


async def is_agy_authenticated(home: Path) -> bool:
    path = agy_token_path(home)
    return path.is_file() and path.stat().st_size > 0


async def authenticate_cursor(
    *,
    binary: str,
    home: Path,
    send: SendFn,
    timeout: float,
) -> bool:
    if await is_cursor_authenticated(binary, home):
        await send("Cursor Agent CLI is already signed in.")
        return True

    env = cli_env(home)
    proc = await asyncio.create_subprocess_exec(
        binary,
        "login",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    url, captured = await _read_until_url(proc, timeout=min(120.0, timeout))
    if url is None:
        proc.kill()
        await send(
            "Cursor login did not print a URL.\n"
            f"Output so far:\n{captured[-500:] or '(empty)'}"
        )
        return False

    await send(
        "Sign in to Cursor Agent (open this link in a browser on any device):\n"
        f"{url}\n\n"
        "I'll wait until the CLI reports you're logged in."
    )

    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if proc.returncode is not None:
            break
        if await is_cursor_authenticated(binary, home):
            if proc.returncode is None:
                proc.kill()
            await send("Cursor Agent is signed in.")
            return True
        await asyncio.sleep(3)

    if await is_cursor_authenticated(binary, home):
        await send("Cursor Agent is signed in.")
        return True

    if proc.returncode is None:
        proc.kill()
    await send("Cursor login timed out — run `/cli-auth` later or recreate the container.")
    return False


async def authenticate_agy(
    *,
    binary: str,
    home: Path,
    send: SendFn,
    wait_for_message: WaitFn,
    timeout: float,
) -> bool:
    if await is_agy_authenticated(home):
        await send("Antigravity (`agy`) is already signed in.")
        return True

    env = cli_env(home)
    proc = await asyncio.create_subprocess_exec(
        binary,
        "auth",
        "login",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    url, captured = await _read_until_url(proc, timeout=min(120.0, timeout))
    if url is None:
        proc.kill()
        await send(
            "agy login did not print a URL.\n"
            f"Output so far:\n{captured[-500:] or '(empty)'}"
        )
        return False

    await send(
        "Sign in to Antigravity / `agy`:\n"
        f"1. Open {url}\n"
        "2. Finish Google sign-in in the browser\n"
        "3. Reply here with the verification / authorization code\n\n"
        "Waiting for your code…"
    )

    try:
        message = await wait_for_message(timeout)
    except TimeoutError:
        if proc.returncode is None:
            proc.kill()
        await send("Timed out waiting for the agy verification code.")
        return False

    code = message.text.strip().split()[0]
    if not looks_like_auth_code(code):
        if proc.returncode is None:
            proc.kill()
        await send(
            f"That doesn't look like a verification code ({code!r}). "
            "Re-run `/cli-auth` when you have the code."
        )
        return False

    assert proc.stdin is not None
    proc.stdin.write(f"{code}\n".encode())
    await proc.stdin.drain()
    proc.stdin.close()

    try:
        await asyncio.wait_for(proc.wait(), timeout=60)
    except TimeoutError:
        proc.kill()
        await send("agy login hung after the code was sent.")
        return False

    if await is_agy_authenticated(home):
        await send("Antigravity (`agy`) is signed in.")
        return True

    rest = ""
    if proc.stdout is not None:
        rest = (await proc.stdout.read()).decode("utf-8", errors="replace")
    await send(
        "agy login did not persist credentials. "
        f"Exit code {proc.returncode}. Output:\n{(captured + rest)[-600:]}"
    )
    return False


def configured_cli_path(settings: SluiceSettings, backend_id: str) -> str | None:
    mapping = {
        "cursor": settings.cursor_cli_path,
        "agy": settings.agy_cli_path,
        "claude_code": settings.claude_code_cli_path,
        "codex": settings.codex_cli_path,
    }
    return mapping.get(backend_id)


async def bootstrap_ai_clis(
    *,
    settings: SluiceSettings,
    chat: ChatAdapter,
    home: Path | None = None,
) -> None:
    """Install enabled CLIs and complete Matrix-assisted login when needed."""
    if not settings.cli_bootstrap_enabled:
        log.info("cli_bootstrap_skipped", reason="disabled")
        return

    home_path = home or settings.resolved_cli_home_dir
    ensure_runtime_paths(home_path)
    timeout = float(settings.cli_auth_timeout_seconds)

    async def send(text: str) -> None:
        if chat.is_configured and getattr(chat, "is_running", False):
            await chat.send(OutgoingMessage(text=text))
        else:
            log.info("cli_bootstrap_notice", text=text[:200])

    async def wait_for_message(wait_timeout: float) -> IncomingMessage:
        waiter = getattr(chat, "wait_for_message", None)
        if not callable(waiter):
            raise RuntimeError("Chat adapter cannot wait for a reply (need Matrix)")
        return await waiter(timeout_seconds=wait_timeout)

    enabled = settings.enabled_backend_ids()
    await send(
        "Preparing AI coding CLIs for: "
        + ", ".join(enabled)
        + "\n(Install + subscription login — no metered chat API.)"
    )

    for backend_id in enabled:
        spec = SPECS.get(backend_id)
        if spec is None:
            await send(f"Unknown backend {backend_id!r} — skipping install.")
            continue

        if spec.auth_kind == "none" and backend_id == "codex":
            # Codex install needs root apt/npm; skip auto-install in the slim image.
            binary = resolve_binary(spec, home_path, configured_cli_path(settings, backend_id))
            if binary is None:
                await send(
                    "Codex is enabled but not auto-installed in this image. "
                    "Install `codex` into PATH or drop it from SLUICE_AI_BACKENDS."
                )
            continue

        ok, detail = await install_cli(spec, home=home_path)
        if not ok:
            await send(f"Failed to install {backend_id}: {detail[:400]}")
            continue

        binary = resolve_binary(spec, home_path, configured_cli_path(settings, backend_id))
        if binary is None:
            await send(f"{backend_id}: binary still missing after install.")
            continue

        if spec.auth_kind == "link" and backend_id == "cursor":
            await authenticate_cursor(
                binary=binary,
                home=home_path,
                send=send,
                timeout=timeout,
            )
        elif spec.auth_kind == "link_and_code" and backend_id == "agy":
            drain = getattr(chat, "drain_pending_messages", None)
            if callable(drain):
                drain()
            await authenticate_agy(
                binary=binary,
                home=home_path,
                send=send,
                wait_for_message=wait_for_message,
                timeout=timeout,
            )
        elif backend_id == "claude_code":
            await send(
                "Claude Code is installed. If it asks you to log in on first use, "
                "we'll surface that in Matrix on the next jour fixe turn."
            )

    await send("CLI bootstrap finished. You can start a jour fixe with `/jour-fixe`.")
    drain = getattr(chat, "drain_pending_messages", None)
    if callable(drain):
        drain()

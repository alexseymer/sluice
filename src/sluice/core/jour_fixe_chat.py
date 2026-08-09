"""Conversational AI facilitator for Matrix chat (jour fixe and casual ask mode)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import httpx
import structlog

from sluice.adapters.backend import BackendAdapter
from sluice.models.plan import PlanTask

log = structlog.get_logger()


class ChatMode(StrEnum):
    """Conversation style for facilitator prompts."""

    JOUR_FIXE = "jour_fixe"
    CASUAL = "casual"


_SYSTEM_PROMPT = """You are Sluice's coordinator in Matrix — a calm, practical partner
for a solo builder. You brainstorm, set direction, and escalate; forge issues/PRs are
where execution is tracked.

Session arc (guide gently, do not lecture):
1. Status quo — where we stand; what went wrong or changed since the last meeting
2. Discussion — how to deal with those issues (tradeoffs, clarifying questions)
3. Convergence — a clear implementation direction the human can agree to

Rules:
- Reply in natural language only (no JSON, no markdown code fences, no slash-command lists).
- When something substantial is unclear, ask rather than guessing — one or two focused
  questions, then wait for direction.
- Keep replies concise — a few short paragraphs at most.
- Do not invent tasks as a bullet backlog mid-session; save structured planning for the end.
- When the human seems ready to wrap up, briefly confirm the direction and invite them to
  say they are done so Sluice can summarize the plan.
- Do not mention internal UUIDs, env vars, or implementation details of Sluice itself.
"""

_CASUAL_SYSTEM_PROMPT = """You are Sluice's coordinator in Matrix — a helpful partner for a
solo builder. This is normal chat (ask mode): answer questions, discuss ideas, explain
tradeoffs, and help think through problems in plain conversation.

Rules:
- Reply in natural language only (no JSON, no markdown code fences unless genuinely helpful).
- Be conversational and direct — not robotic, and do not list slash commands unless asked.
- You are NOT in a jour fixe planning session unless the human explicitly started one.
- If they want to turn discussion into forge issues for approval, mention `/jour-fixe` once
  when it fits — do not nag about commands every message.
- When something substantial is unclear, ask focused questions rather than guessing.
- Keep replies concise — a few short paragraphs at most.
- Do not invent internal UUIDs, env vars, or implementation details of Sluice itself.
"""

_FACILITATOR_PROMPTS: dict[ChatMode, str] = {
    ChatMode.JOUR_FIXE: """Transcript so far:
{transcript}

Latest human message:
{latest}

Respond as the jour fixe facilitator.
""",
    ChatMode.CASUAL: """Conversation so far:
{transcript}

Latest message:
{latest}

Respond naturally as the coordinator.
""",
}


def system_prompt_for(mode: ChatMode) -> str:
    if mode is ChatMode.CASUAL:
        return _CASUAL_SYSTEM_PROMPT
    return _SYSTEM_PROMPT

NO_BACKEND_REPLY = (
    "I can listen and take notes, but I need a signed-in AI coding CLI for conversation. "
    "Sluice installs the backends listed in SLUICE_AI_BACKENDS on startup and asks you "
    "to finish login over Matrix (no metered chat API). "
    "Check container logs, reply to any pending auth prompt, or say `/cli-auth`. "
    "You can still describe the work and say you're done for a draft plan."
)

_CLI_MISSING_HINT = (
    "I can't reach the AI coding CLI from this container yet. "
    "On startup Sluice installs the backends in SLUICE_AI_BACKENDS and posts "
    "login links here (Cursor: open the link; agy: open the link and reply with "
    "the verification code). Say `/cli-auth` to retry. "
    "Coding-task dispatch uses the same subscription CLIs."
)


@dataclass(frozen=True)
class JourFixeLlmSettings:
    """Optional OpenAI-compatible chat API for Matrix conversation."""

    base_url: str | None = None
    api_key: str | None = None
    model: str = "gpt-4o-mini"

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)


def format_transcript(turns: list[tuple[str, str]]) -> str:
    """Render (role, text) turns for prompts."""
    if not turns:
        return "(no messages yet)"
    lines: list[str] = []
    for role, text in turns:
        label = "Human" if role == "human" else "Assistant"
        lines.append(f"{label}: {text}")
    return "\n".join(lines)


def extract_facilitator_reply(output: str) -> str:
    """Trim CLI noise and return a chat-sized reply."""
    text = output.strip()
    if not text:
        return ""
    # Prefer the last non-empty block if the CLI echoed the prompt.
    blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    if not blocks:
        return text
    reply = blocks[-1] if len(blocks) > 1 else text
    if len(reply) > 4000:
        reply = reply[-4000:].lstrip()
    return reply


def _chat_messages(turns: list[tuple[str, str]], *, mode: ChatMode) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt_for(mode)}
    ]
    for role, text in turns:
        messages.append(
            {
                "role": "user" if role == "human" else "assistant",
                "content": text,
            }
        )
    return messages


async def facilitate_via_llm(
    *,
    settings: JourFixeLlmSettings,
    turns: list[tuple[str, str]],
    latest_human: str,
    mode: ChatMode = ChatMode.JOUR_FIXE,
) -> str | None:
    """Call an OpenAI-compatible /chat/completions endpoint."""
    del latest_human  # already included in turns
    assert settings.is_configured
    base = settings.base_url.rstrip("/")  # type: ignore[union-attr]
    url = f"{base}/chat/completions"
    payload = {
        "model": settings.model,
        "messages": _chat_messages(turns, mode=mode),
        "temperature": 0.4,
    }
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        log.warning("jour_fixe_llm_http_error", error=str(exc))
        return None

    if response.status_code >= 400:
        log.warning(
            "jour_fixe_llm_http_status",
            status=response.status_code,
            body=response.text[:300],
        )
        return None

    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        log.warning(
            "jour_fixe_llm_bad_payload",
            keys=list(data) if isinstance(data, dict) else None,
        )
        return None
    reply = str(content).strip()
    return reply or None


async def facilitate_via_cli(
    *,
    backend: BackendAdapter,
    turns: list[tuple[str, str]],
    latest_human: str,
    worktree: Path,
    mode: ChatMode = ChatMode.JOUR_FIXE,
) -> tuple[str | None, str | None]:
    """Ask the configured AI CLI. Returns (reply, user_facing_error)."""
    worktree.mkdir(parents=True, exist_ok=True)
    facilitator = _FACILITATOR_PROMPTS[mode]
    prompt = facilitator.format(
        transcript=format_transcript(turns),
        latest=latest_human,
    )
    # Include system guidance in the CLI prompt body.
    full_prompt = f"{system_prompt_for(mode)}\n\n{prompt}"
    task = PlanTask(title="jour-fixe-chat", description=full_prompt)
    result = await backend.dispatch(task, worktree=worktree)
    if not result.success or not (result.output or "").strip():
        log.warning(
            "jour_fixe_chat_dispatch_failed",
            backend_id=result.backend_id,
            error=result.error,
        )
        err = result.error or ""
        if "CLI not found" in err or "No such file" in err:
            return None, _CLI_MISSING_HINT
        if mode is ChatMode.CASUAL:
            return None, (
                "I couldn't get a reply from the AI backend just now. "
                "Try again in a moment, or say `/cli-auth` if login is pending."
            )
        return None, (
            "I couldn't get a reply from the AI backend just now. "
            "Say a bit more, or tell me when you're done and I'll draft the plan "
            "from what we have."
        )
    reply = extract_facilitator_reply(result.output)
    if not reply:
        log.warning("jour_fixe_chat_empty_reply", backend_id=result.backend_id)
        return None, None
    return reply, None


async def facilitate_turn(
    *,
    turns: list[tuple[str, str]],
    latest_human: str,
    worktree: Path,
    backend: BackendAdapter | None = None,
    llm: JourFixeLlmSettings | None = None,
    mode: ChatMode = ChatMode.JOUR_FIXE,
) -> tuple[str | None, str | None]:
    """Return (assistant_reply, user_facing_error). Subscription CLIs only."""
    del llm  # Kept for call-site compatibility; metered APIs are intentionally unused.
    if backend is not None:
        return await facilitate_via_cli(
            backend=backend,
            turns=turns,
            latest_human=latest_human,
            worktree=worktree,
            mode=mode,
        )

    return None, NO_BACKEND_REPLY

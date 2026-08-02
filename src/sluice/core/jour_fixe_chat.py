"""Conversational AI facilitator for active jour fixe sessions."""

from __future__ import annotations

from pathlib import Path

import structlog

from sluice.adapters.backend import BackendAdapter
from sluice.models.plan import PlanTask

log = structlog.get_logger()

_FACILITATOR_PROMPT = """You are Sluice's jour fixe facilitator — a calm, practical partner
for a short working meeting over chat.

Session arc (guide gently, do not lecture):
1. Status quo — where we stand; what went wrong or changed since the last meeting
2. Discussion — how to deal with those issues (tradeoffs, clarifying questions)
3. Convergence — a clear implementation direction the human can agree to

Transcript so far:
{transcript}

Latest human message:
{latest}

Rules:
- Reply in natural language only (no JSON, no markdown code fences, no slash-command lists).
- Ask at most one or two clarifying questions when something important is unclear.
- Keep replies concise — a few short paragraphs at most.
- Do not invent tasks as a bullet backlog mid-session; save structured planning for the end.
- When the human seems ready to wrap up, briefly confirm the direction and invite them to
  say they are done so Sluice can summarize the plan.
- Do not mention internal UUIDs, env vars, or implementation details of Sluice itself.
"""

NO_BACKEND_REPLY = (
    "I can listen and take notes, but I need an AI backend configured to talk this through "
    "with you. Set SLUICE_PLANNER_BACKEND (or SLUICE_DEFAULT_BACKEND / SLUICE_AI_BACKENDS), "
    "then we can have a real conversation. You can still describe the work and say you're "
    "done when you want a draft plan."
)


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


async def facilitate_turn(
    *,
    backend: BackendAdapter,
    turns: list[tuple[str, str]],
    latest_human: str,
    worktree: Path,
) -> str | None:
    """Ask the configured AI CLI for the next facilitator reply."""
    worktree.mkdir(parents=True, exist_ok=True)
    prompt = _FACILITATOR_PROMPT.format(
        transcript=format_transcript(turns),
        latest=latest_human,
    )
    task = PlanTask(title="jour-fixe-chat", description=prompt)
    result = await backend.dispatch(task, worktree=worktree)
    if not result.success or not result.output.strip():
        log.warning(
            "jour_fixe_chat_dispatch_failed",
            backend_id=result.backend_id,
            error=result.error,
        )
        return None
    reply = extract_facilitator_reply(result.output)
    if not reply:
        log.warning("jour_fixe_chat_empty_reply", backend_id=result.backend_id)
        return None
    return reply

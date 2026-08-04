"""Conversational AI facilitator for active jour fixe sessions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
import structlog

from sluice.adapters.backend import BackendAdapter
from sluice.models.plan import PlanTask

log = structlog.get_logger()

_SYSTEM_PROMPT = """You are Sluice's jour fixe facilitator — a calm, practical partner
for a short working meeting over chat.

Session arc (guide gently, do not lecture):
1. Status quo — where we stand; what went wrong or changed since the last meeting
2. Discussion — how to deal with those issues (tradeoffs, clarifying questions)
3. Convergence — a clear implementation direction the human can agree to

Rules:
- Reply in natural language only (no JSON, no markdown code fences, no slash-command lists).
- Ask at most one or two clarifying questions when something important is unclear.
- Keep replies concise — a few short paragraphs at most.
- Do not invent tasks as a bullet backlog mid-session; save structured planning for the end.
- When the human seems ready to wrap up, briefly confirm the direction and invite them to
  say they are done so Sluice can summarize the plan.
- Do not mention internal UUIDs, env vars, or implementation details of Sluice itself.
"""

_FACILITATOR_PROMPT = """Transcript so far:
{transcript}

Latest human message:
{latest}

Respond as the jour fixe facilitator.
"""

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


def _chat_messages(turns: list[tuple[str, str]]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM_PROMPT}]
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
) -> str | None:
    """Call an OpenAI-compatible /chat/completions endpoint."""
    del latest_human  # already included in turns
    assert settings.is_configured
    base = settings.base_url.rstrip("/")  # type: ignore[union-attr]
    url = f"{base}/chat/completions"
    payload = {
        "model": settings.model,
        "messages": _chat_messages(turns),
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
) -> tuple[str | None, str | None]:
    """Ask the configured AI CLI. Returns (reply, user_facing_error)."""
    worktree.mkdir(parents=True, exist_ok=True)
    prompt = _FACILITATOR_PROMPT.format(
        transcript=format_transcript(turns),
        latest=latest_human,
    )
    # Include system guidance in the CLI prompt body.
    full_prompt = f"{_SYSTEM_PROMPT}\n\n{prompt}"
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
) -> tuple[str | None, str | None]:
    """Return (assistant_reply, user_facing_error). Subscription CLIs only."""
    del llm  # Kept for call-site compatibility; metered APIs are intentionally unused.
    if backend is not None:
        return await facilitate_via_cli(
            backend=backend,
            turns=turns,
            latest_human=latest_human,
            worktree=worktree,
        )

    return None, NO_BACKEND_REPLY

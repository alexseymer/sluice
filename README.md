# Sluice

[![CI](https://github.com/alexseymer/sluice/actions/workflows/ci.yml/badge.svg)](https://github.com/alexseymer/sluice/actions/workflows/ci.yml)
[![Docker](https://github.com/alexseymer/sluice/actions/workflows/docker.yml/badge.svg)](https://github.com/alexseymer/sluice/actions/workflows/docker.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GHCR](https://img.shields.io/badge/container-ghcr.io%2Falexseymer%2Fsluice-2496ED?logo=docker&logoColor=white)](https://github.com/alexseymer/sluice/pkgs/container/sluice)

**Sluice** lets solo builders run CLI coding agents over Matrix — brainstorm and escalate with one coordinator in chat, execute against forge issues/PRs, on generous subscription tokens without terminal babysitting.

Forge issues/PRs are the source of truth for execution. Matrix is where you and the coordinator set direction and handle escalations: when the coordinator hits a substantial question it can't resolve alone, it asks in Matrix rather than guessing. Approve/reject still gates forge filing; day-to-day chat is discussion → adjustments → directions.

Hosting is wherever a slim Linux with those CLIs fits (Docker Compose is the easy path; a VM, VPS, Pi, or bare metal works the same idea). Budget pacing across Claude Code, Codex, Cursor, Agy, and others is a supporting mechanism so subscription windows aren't burned in one burst — not the product itself.

## Status

**Phase 1 is complete** and runnable via **Docker Compose** (or any slim Linux host). The full loop works: cron-triggered jour fixe → conversational planning with a coordinator CLI → `/approve` to file GitHub issues → background dispatch with dependency ordering → Matrix escalation when stuck → budget pacing and backend failover → forge sync when issues close.

| Component | Status |
|-----------|--------|
| Matrix chat + jour fixe commands | ✅ |
| Conversational coordinator (subscription CLIs) | ✅ |
| Escalation to Matrix (`/retry`, `/skip`, direction) | ✅ |
| Docker / slim-Linux CLI install + Matrix login (`/cli-auth`) | ✅ |
| Orchestrator issue shaping + worker/reviewer loop | ✅ |
| GitHub issues + dependency links | ✅ |
| AI backends (Claude Code, Cursor, Agy, Codex) | ✅ |
| Budget probing + fallback failover | ✅ |
| Interactive `sluice setup` wizard | ✅ |
| Signal / Telegram / GitLab / OneDev | 🔜 planned |

See [`docs/prd.md`](docs/prd.md) for the product spec, [`STRATEGY.md`](STRATEGY.md) for positioning, and [`ROADMAP.md`](ROADMAP.md) for what's next.

## Why

CLI coding agents already have generous subscription tokens, but they don't collaborate over Matrix without you babysitting terminals. Metered chat-API agent stacks burn budget differently; Sluice rides the CLIs you already pay for, keeps work on the forge, and uses Matrix as the control and direction channel with one coordinator.

## How it works

Sluice is **issue-driven**: forge issues are the backbone of the plan. A daily jour fixe in Matrix becomes shaped issues, you approve before anything runs, then worker and reviewer CLI agents execute each issue in dependency order. When something substantial is unclear mid-flight, the coordinator escalates in Matrix instead of guessing.

![Sluice issue-driven workflow (Phase 1)](docs/assets/sluice-workflow-phase1.png)

**Chat with coordinator → AI shapes issues → You approve → Worker/Reviewer loop → Escalate if stuck → Issue done**

### 1. Jour fixe chat

You meet the coordinator in Matrix on a schedule (or on demand with `/jour-fixe`). A facilitator — your configured AI coding CLI (subscription) — helps you talk through status quo, problems, and how to handle them. This is brainstorming and direction, not execution.

On Docker (or similar), `sluice setup` signs in your **primary** CLI agent over Matrix. On daemon start, Sluice installs and authenticates any **additional** backends listed in `SLUICE_AI_BACKENDS` via Matrix (`/cli-auth` to retry).

### 2. AI shapes issues

When you say you're done, the **orchestrator** (primary CLI agent) reads the full transcript and shapes it into forge-ready issues:

- Groups related work into one issue when it ships together (not one micro-issue per bullet)
- Splits only when work is genuinely independent
- Writes **acceptance criteria** so a reviewer can verify completion
- Sets **dependency links** — what must finish before what, and what can run in parallel

Sluice posts the shaped plan in Matrix for your review (`/plan` to see it again).

### 3. `/approve` checkpoint

Nothing is filed or executed until you reply **`/approve`**. Use **`/reject`** to discard and start over. This gate keeps the orchestrator's shaped issues under human control before any specialist agents run.

### 4. Issue execution loop

On approval, issues are filed on GitHub. For each **ready** issue (all blockers completed):

1. **Worker** CLI agent implements the issue in an isolated worktree
2. **Reviewer** CLI agent checks the output against acceptance criteria
3. If review fails, the worker revises — loop until approved or `SLUICE_MAX_REVIEW_ITERATIONS`
4. If the worker hits a substantial question (or review still fails after max iterations), Sluice **escalates in Matrix** — reply with guidance, `/retry`, or `/skip`

**Sequential:** issue 2 stays blocked until issue 1 is complete and passes review.

**Parallel:** independent issues (e.g. 3 and 4 with the same blockers but not depending on each other) dispatch concurrently.

Sluice paces dispatches across backends to stay within subscription budgets and fails over when quota or fallback-model degradation is detected.

### 5. Issue completed

When an issue passes review, Sluice marks it complete and closes the GitHub issue. You get a notification in Matrix. Forge sync also picks up issues closed manually on GitHub.

Outside jour fixe, use `/status`, `/plan`, `/cli-auth`, `/retry`, `/skip`, and `/help` in Matrix.

### Configuration

| Variable | Role |
|----------|------|
| `SLUICE_AI_BACKENDS` | CLIs to install/auth and the worker pool |
| `SLUICE_ORCHESTRATOR_BACKEND` | Primary agent that shapes issues (defaults to `SLUICE_PLANNER_BACKEND`) |
| `SLUICE_REVIEWER_BACKEND` | Second agent for per-issue review loops |
| `SLUICE_MAX_REVIEW_ITERATIONS` | Max worker/reviewer cycles per issue (default `3`) |
| `SLUICE_CLI_BOOTSTRAP_ENABLED` | Install + Matrix-auth CLIs on daemon start |

Without `SLUICE_REVIEWER_BACKEND`, Sluice falls back to single-agent dispatch per issue.

## Privacy

Sluice is privacy-first by design on the chat layer specifically — no third-party SaaS relay of your conversations, self-hostable end-to-end. See [`SECURITY.md`](SECURITY.md) for details and current caveats (e.g. Telegram's lack of E2E for bot chats).

## Getting started (Docker)

Docker Compose is the recommended bring-up; the same app runs on any slim Linux host with the CLIs available. The image is built on GitHub Actions and published to GHCR (`ghcr.io/alexseymer/sluice`). Prefer pulling the published image; for local image iteration use `docker compose build` then `docker compose up -d --force-recreate --pull never`.

```bash
# 1. Create env file (secrets stay on the host, mounted into the container)
cp .env.example .env

# 2. If the package is private, log in once:
#    echo YOUR_GITHUB_TOKEN | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin

# 3. Interactive setup (pulls the image, then runs the wizard)
docker compose run --rm sluice setup

# 4. Run the daemon
docker compose up -d

# Logs
docker compose logs -f sluice
```

After setup (or any `.env` change), recreate so Compose injects the new variables:

```bash
docker compose up -d --force-recreate
```

To refresh to the newest published image:

```bash
docker compose pull
docker compose up -d --force-recreate
```

`sluice setup` runs in order: **Matrix** (bot + room), **primary CLI login** in that room (proves Matrix ↔ agent works), then **GitHub** device flow for the forge. Additional CLIs in `SLUICE_AI_BACKENDS` sign in over Matrix when the daemon starts (or via `/cli-auth`). Existing `.env` values are offered as defaults; valid saved credentials skip re-auth.

### Local development (optional)

For tests and hacking on the Python package without Docker:

```bash
pip install -e ".[dev]"
ruff check src tests
pytest
sluice setup   # same wizard; still writes .env
```

See [`AGENTS.md`](AGENTS.md) for project layout and agent notes.

## License

MIT — see [`LICENSE`](LICENSE).

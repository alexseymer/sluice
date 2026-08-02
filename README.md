# Sluice

[![CI](https://github.com/alexseymer/sluice/actions/workflows/ci.yml/badge.svg)](https://github.com/alexseymer/sluice/actions/workflows/ci.yml)
[![Docker](https://github.com/alexseymer/sluice/actions/workflows/docker.yml/badge.svg)](https://github.com/alexseymer/sluice/actions/workflows/docker.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GHCR](https://img.shields.io/badge/container-ghcr.io%2Falexseymer%2Fsluice-2496ED?logo=docker&logoColor=white)](https://github.com/alexseymer/sluice/pkgs/container/sluice)

**Sluice** paces your AI coding CLI usage (Claude Code, Codex, Cursor, Agy, and others) across the day so you stay under subscription rate limits — instead of bursting through your quota in one session and getting silently downgraded to a weaker fallback model, or paying overage rates on metered API billing.

You talk to Sluice once a day (or on whatever cadence you set) in a short **jour fixe** — a chat session where you discuss what needs doing. Sluice turns that into a dependency-ordered plan, files it as issues on your Git forge of choice (GitHub today; GitLab and OneDev planned), and works through the backlog throughout the day, scheduling AI CLI calls to stay within each tool's budget. You get pinged with status, blockers, and anything that needs a decision — over Matrix today (Signal and Telegram planned), all privacy-first.

## Status

**Phase 1 is complete** and runnable via **Docker Compose**. The full loop works: cron-triggered jour fixe → conversational planning → `/approve` to file GitHub issues → background dispatch with dependency ordering → budget pacing and backend failover → forge sync when issues close.

| Component | Status |
|-----------|--------|
| Matrix chat + jour fixe commands | ✅ |
| Conversational jour fixe (CLI or LLM API) | ✅ |
| Planner → dependency-ordered tasks | ✅ |
| GitHub issues + dependency links | ✅ |
| AI backends (Claude Code, Cursor, Agy, Codex) | ✅ |
| Budget probing + fallback failover | ✅ |
| Interactive `sluice setup` wizard | ✅ |
| Signal / Telegram / GitLab / OneDev | 🔜 planned |

See [`docs/prd.md`](docs/prd.md) for the product spec and [`ROADMAP.md`](ROADMAP.md) for what's next.

## Why

AI coding subscriptions have usage windows. Burn through them in a burst and you either get downgraded to a weaker model without much warning, or start paying metered rates. Sluice treats "AI coding capacity" as a schedulable, rate-limited resource — like a build farm schedules CI jobs — so you get consistent throughput without babysitting it.

## How it works

1. **Jour fixe** — a conversational Matrix chat that starts from status quo and problems since last time, then discusses how to handle them. Messages go through your configured AI CLI (on the host) or an OpenAI-compatible LLM API (recommended in Docker).
2. **Plan** — when you say you're done, Sluice summarizes the discussion into a dependency-ordered task plan for your approval.
3. **Issues** — approved tasks are filed on GitHub, with explicit dependency links.
4. **Scheduling** — Sluice dispatches unblocked tasks to AI CLI backends throughout the day, respecting each one's budget/rate limits and failing over when quota or fallback-model degradation is detected.
5. **Check-ins** — async dispatch notifications over Matrix; `/status`, `/plan`, and `/help` work outside jour fixe.

Set `SLUICE_JOUR_FIXE_LLM_*` (OpenAI-compatible chat API) for Matrix conversation when running in Docker — Linux containers cannot execute Windows Cursor/Claude CLIs. Optionally set `SLUICE_PLANNER_BACKEND` for CLI-based planning/dispatch on hosts where those tools exist.

## Privacy

Sluice is privacy-first by design on the chat layer specifically — no third-party SaaS relay of your conversations, self-hostable end-to-end via Docker. See [`SECURITY.md`](SECURITY.md) for details and current caveats (e.g. Telegram's lack of E2E for bot chats).

## Getting started (Docker)

Sluice is meant to run as a container. The image is built on GitHub Actions and
published to GHCR (`ghcr.io/alexseymer/sluice`). Compose only pulls — no local build.

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

`sluice setup` asks for minimal input (repo, a GitHub OAuth App client ID with Device Flow enabled, Matrix homeserver + your login, and ideally Synapse's `registration_shared_secret`). Existing `.env` values are offered as defaults; a still-valid GitHub token skips device login.

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

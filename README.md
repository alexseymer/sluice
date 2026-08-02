# Sluice

**Sluice** paces your AI coding CLI usage (Claude Code, Codex, Cursor, Agy, and others) across the day so you stay under subscription rate limits — instead of bursting through your quota in one session and getting silently downgraded to a weaker fallback model, or paying overage rates on metered API billing.

You talk to Sluice once a day (or on whatever cadence you set) in a short **jour fixe** — a chat session where you discuss what needs doing. Sluice turns that into a dependency-ordered plan, files it as issues on your Git forge of choice (GitHub, GitLab, or OneDev), and works through the backlog throughout the day, scheduling AI CLI calls to stay within each tool's budget. You get pinged with status, blockers, and anything that needs a decision — over Signal, Telegram, or Matrix, all privacy-first.

## Status

Phase 1 scaffold in place — Python package, core interfaces, stub adapters, and Docker Compose. Adapters are not yet wired to real services. See [`docs/prd.md`](docs/prd.md) for the full product spec, and [`ROADMAP.md`](ROADMAP.md) for what's being built first.

## Why

AI coding subscriptions have usage windows. Burn through them in a burst and you either get downgraded to a weaker model without much warning, or start paying metered rates. Sluice treats "AI coding capacity" as a schedulable, rate-limited resource — like a build farm schedules CI jobs — so you get consistent throughput without babysitting it.

## How it works (planned)

1. **Jour fixe** — a scheduled chat session where you and Sluice discuss upcoming work.
2. **Plan** — Sluice breaks the discussion into dependency-ordered tasks.
3. **Issues** — tasks get filed on your Git forge, with explicit dependency links.
4. **Scheduling** — Sluice dispatches unblocked tasks to your AI CLI backends throughout the day, respecting each one's budget/rate limits.
5. **Check-ins** — async updates over Signal, Telegram, or Matrix; you can query status or interrupt at any time outside the jour fixe.

## Privacy

Sluice is privacy-first by design on the chat layer specifically — no third-party SaaS relay of your conversations, self-hostable end-to-end via Docker. See [`SECURITY.md`](SECURITY.md) for details and current caveats (e.g. Telegram's lack of E2E for bot chats).

## Getting started

```bash
# Install
pip install -e ".[dev]"

# Interactive setup (GitHub device login + Matrix bot/room provisioning)
sluice setup

# Run the daemon
sluice

# Or via Docker
docker compose up --build
```

`sluice setup` asks for minimal input (repo, a one-time GitHub OAuth App client ID with Device Flow enabled, Matrix homeserver + your login, and ideally Synapse's `registration_shared_secret`). It exchanges tokens itself, creates `@sluice-bot`, opens a private room, and writes credentials into `.env`. You can still copy `.env.example` and fill values by hand if you prefer.

See [`AGENTS.md`](AGENTS.md) for project layout and development commands.

## License

MIT — see [`LICENSE`](LICENSE).

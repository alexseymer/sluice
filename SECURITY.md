# Security & Privacy

Sluice is built to be self-hosted and privacy-first, particularly on the human-facing chat layer. This document lays out what that means concretely, and where the current limits are.

## Chat backends

- **Signal** — integrated via `signal-cli` (or an equivalent self-hosted bridge) run locally alongside Sluice. No message content is relayed through a third-party SaaS.
- **Matrix** — connects as a bot user to a homeserver you control or trust; end-to-end encrypted rooms are supported where the homeserver allows it.
- **Telegram** — included for reach/convenience, but is **not** a privacy-equivalent option. Telegram retains message data server-side by default, and Secret Chats (Telegram's E2E mode) are not available to bots, so bot conversations are never end-to-end encrypted on Telegram regardless of configuration.

If privacy is your priority, use Signal or Matrix. Telegram is opt-in and documented as the weaker option, not a default.

## Data handling

- No analytics, telemetry, or crash reporting is sent anywhere by default.
- State (plans, schedules, chat history relevant to task context, budget tracking) is stored only in your own datastore (a container volume you control) — never synced to a third party.
- The only external parties that ever see task/code content are: (a) your chosen chat protocol's own infrastructure, (b) your Git forge, and (c) the AI CLI backends you've already chosen to trust with your code.

## Secrets

- Git forge tokens, messaging credentials, and AI CLI auth are supplied via environment variables or a mounted secrets file — never hardcoded, never committed, never logged.
- See `.env.example` for the full list of expected variables (values are placeholders only).
- Logs are scrubbed/redacted by default; if you find a secret leaking into logs, please open an issue.

## Reporting a vulnerability

This project is early-stage and doesn't yet have a formal disclosure process. In the meantime, please open a GitHub issue with as much detail as you're comfortable sharing publicly, or flag it directly to the repo owner if it's sensitive.

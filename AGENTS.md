# AGENTS.md

## Cursor Cloud specific instructions

### Current repository state

Sluice is in **Phase 1** — a runnable Python package with core interfaces and Docker
Compose bring-up. The Matrix chat adapter and GitHub forge adapter are implemented;
plan approval in chat files issues on `/approve`. Claude Code adapter remains a stub.

### Project layout

```
src/sluice/
  adapters/     # Protocol interfaces + implementations (matrix, github, CLI backends)
  core/         # Jour fixe, planner, dependency graph, scheduler, budget manager
  models/       # Pydantic domain models
  setup/        # Interactive `sluice setup` (GitHub device flow, Matrix provisioning)
  store/        # SQLite persistence
  config.py     # Settings via env vars (prefix: SLUICE_)
  __main__.py   # CLI entrypoint
tests/
docker-compose.yml
Dockerfile
.env.example
```

### Commands

```bash
# Install (editable)
pip install -e ".[dev]"

# Lint
ruff check src tests

# Test
pytest

# First-run credentials (writes .env)
sluice setup

# Run locally
sluice

# Docker
docker compose up --build
```

### Environment baseline

- Python 3.12 (`python3`, `pip3`) — no `python` alias; use `python3`.
- Node.js 22, GNU Make 4.3.
- Docker may need to be installed for `docker compose up` (not pre-installed on all VMs).

### Cloud environment (`.cursor/environment.json`)

On VM boot, Cursor runs the `install` script from `.cursor/environment.json` after
pulling the latest changes. It is idempotent and guards for whichever Python manifests
exist (`requirements.txt`, `requirements-dev.txt`, `pyproject.toml`). Agents should not
need to reinstall manually unless dependencies change mid-run.

### Phase 1 implementation order (from ROADMAP.md)

1. ~~Matrix chat adapter~~ (done)
2. ~~GitHub forge adapter~~ (done)
3. ~~Plan approval in chat~~ (done)
4. ~~AI CLI backends (Claude Code, Cursor, agy)~~ (done)
5. Jour fixe scheduler integration (cron-triggered sessions)
6. ~~Budget tracking wired to SQLite store~~ (done)

AI CLI backends: Claude Code (`claude`), Cursor (`agent`), and Antigravity (`agy`).
Enable via `SLUICE_AI_BACKENDS=claude_code,cursor,agy`. Tasks can set `backend_id`
or Sluice picks the first backend with budget headroom.

### Secrets

All credentials via `SLUICE_*` env vars — see `.env.example`. Never log or commit secrets.

### Pull requests

Use **`ManagePullRequest`** to create and update PRs — not `gh pr create` / `gh pr edit`
(the cloud installation token lacks PR/issue API scopes). Commit, push, then
`create_pr` / `update_pr`. Standard PRs should note assignee **`alexseymer`** in the body
or summary for manual assignment on GitHub. See `.cursor/rules/pull-requests.mdc`.

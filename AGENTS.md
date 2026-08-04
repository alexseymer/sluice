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
  setup/        # Interactive `sluice setup` + runtime CLI install/Matrix auth
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
# --- Preferred: Docker (pull published GHCR image) ---
cp .env.example .env
# docker login ghcr.io   # only if the package is private
docker compose run --rm sluice setup
docker compose up -d
docker compose pull && docker compose up -d --force-recreate
docker compose logs -f sluice

# --- Dev (host Python) ---
pip install -e ".[dev]"
ruff check src tests
pytest

# --- Dev image (optional; normal users should pull, not build) ---
docker build -t sluice:local .
```

### Environment baseline

- **Runtime:** Docker / Docker Compose (primary).
- Python 3.12 (`python3`, `pip3`) for local tests — no `python` alias on Cloud VMs; use `python3`.
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
Enable via `SLUICE_AI_BACKENDS=cursor,agy` (or include `claude_code` / `codex`).
On Docker start, Sluice installs enabled Linux CLIs under `/data/home` and posts
subscription login links to Matrix (Cursor: open the link; `agy`: open the link and
reply with the verification code). Retry with `/cli-auth`. Jour fixe uses those CLIs
only — no metered chat API. Tasks can set `backend_id` or Sluice picks the first
backend with budget headroom.

### Secrets

All credentials via `SLUICE_*` env vars — see `.env.example`. Never log or commit secrets.

### MCP servers (`.cursor/mcp.json`)

Project MCP config is committed (no secrets). Servers:

| Server | Purpose | Requirements |
|--------|---------|--------------|
| `github` | Issues/PRs/repos via official GitHub MCP | Docker + `GITHUB_PERSONAL_ACCESS_TOKEN` in the environment |
| `git` | Local git operations on this repo | Node/`npx` |
| `fetch` | HTTP fetch for docs/APIs | Node/`npx` |

Set a PAT (repo + issues scopes as needed) before starting Cursor:

```bash
# Windows PowerShell
$env:GITHUB_PERSONAL_ACCESS_TOKEN = "ghp_..."

# bash
export GITHUB_PERSONAL_ACCESS_TOKEN=ghp_...
```

Then reload Cursor (Settings → Tools & MCP → green dots). Do not put PATs in `.cursor/mcp.json`.

### Pull requests

Use **`ManagePullRequest`** to create and update PRs — not `gh pr create` / `gh pr edit`
(the cloud installation token lacks PR/issue API scopes). Commit, push, then
`create_pr` / `update_pr`. Standard PRs should note assignee **`alexseymer`** in the body
or summary for manual assignment on GitHub. See `.cursor/rules/pull-requests.mdc`.

# AGENTS.md

## Cursor Cloud specific instructions

### Current repository state (read this first)

This repo is in the **early design phase** and is currently **documentation-only**. There is
no runnable code yet. The tracked files are only:

- `README.md`, `ROADMAP.md`, `SECURITY.md`, `docs/prd.md`, `LICENSE`, `.gitignore`

There are **no** dependency manifests (`requirements.txt` / `pyproject.toml` / `package.json`),
**no** build system, **no** tests, and **no** app entrypoint. As stated in `README.md`, the
project is "Not yet runnable." Consequently there is currently nothing to lint, test, build, or
run, and no service to start.

### Intended product (per `docs/prd.md`)

"Sluice" is planned as a **Python application** deployed as a **Docker container**, orchestrated
via `docker compose up` (PRD FR24). The planned stack: a Python core (jour-fixe manager, planner,
dependency-graph engine, scheduler/budget manager) plus a state datastore (SQLite or Postgres),
with pluggable adapters for Git forges (GitHub/GitLab/OneDev), AI CLI backends
(Claude Code/Cursor/Agy/Codex), and chat backends (Signal/Matrix/Telegram). None of this is
implemented yet — treat `docs/prd.md` and `ROADMAP.md` as intent, not current behavior.

### Environment baseline (already present on the VM)

- Python 3.12 (`python3`, `pip3`) — note there is no `python` alias; use `python3`.
- Node.js 22, GNU Make 4.3.
- **Docker is NOT installed.** When the planned Docker Compose stack lands, Docker must be
  installed before `docker compose up` will work (it is intentionally not part of the startup
  update script today, since there is nothing to run yet).

### When code lands (guidance for future agents)

- The startup update script guards for Python manifests: it installs from `requirements.txt`
  and/or `pyproject.toml` if/when they appear, and is a safe no-op until then. Extend it once the
  real dependency/build tooling is chosen.
- Expect the run command to become `docker compose up` per the PRD; revisit Docker installation
  and service startup at that point.

# Roadmap

This roadmap mirrors the phasing in [`docs/prd.md`](docs/prd.md) and the tracks in [`STRATEGY.md`](STRATEGY.md). It's public and will change as we learn things — treat it as a snapshot of current intent, not a promise.

## Strategy tracks

| Track | Intent | Status |
|-------|--------|--------|
| **Matrix ↔ CLI bridge** | Coordinator plans, escalates, and takes direction in Matrix | ✅ core; polish ongoing |
| **Forge task backbone** | Issues/PRs as source of truth (GitHub today) | ✅ GitHub; GitLab/OneDev next |
| **Opinionated coordinator** | One orchestrator plans, assigns, gates, escalates | ✅; multi-agent rooms later |
| **Safety & auditability** | Human gates, isolation, trustable trail | ✅ `/approve`/`/reject` + escalation |

**Not working on:** external-tool setup as primary product; host choice as the product; competing as a metered chat-API stack.

## Where we are

**Phase 1 is complete.** Sluice runs end-to-end: Matrix coordinator sessions, GitHub issue filing on `/approve`, background dispatch with dependency ordering, Matrix escalation when stuck, budget pacing as a supporting mechanism, and forge sync when issues close. Docker Compose is the documented bring-up; any slim Linux host with CLI agents works in principle.

**Phase 2 is mostly done.** Four AI CLI backends ship (Claude Code, Cursor, Agy, Codex) with heuristic budget probing, quota detection, and fallback-model failover.

**Next up:** scheduling refinements from real-world budget data, multi-forge support, and additional chat backends.

## Phase 1 — Core loop (Matrix + forge + coordinator) ✅

- [x] Jour fixe scheduler (cron-triggered sessions + timeout handling)
- [x] Conversational coordinator over Matrix (subscription CLIs)
- [x] Planner: conversation → dependency-ordered issue list
- [x] Orchestrator shapes jour fixe into best-practice GitHub issues
- [x] GitHub adapter: create/update/link issues
- [x] Plan approval flow → file issues on `/approve`
- [x] Escalation to Matrix when worker/reviewer cannot proceed (`/retry`, `/skip`, free-text direction)
- [x] AI CLI backend adapters (Claude Code, Cursor, Agy, Codex)
- [x] Budget tracking with SQLite (supporting pacing mechanism)
- [x] Background dispatch loop (dependency-aware + parallel ready issues)
- [x] Worker + reviewer loop per issue
- [x] Forge sync (closed issues → mark tasks complete)
- [x] Matrix chat backend (Signal remains a stub)
- [x] Interactive `sluice setup` wizard
- [x] Docker Compose bring-up (GHCR image on `main`)

## Phase 2 — Multi-backend (mostly complete)

- [x] Cursor / Agy / Codex adapters
- [x] Fallback-model detection + scheduler failover
- [x] Budget probing beyond cautious defaults
- [ ] Scheduling refinements once real budget data exists
- [ ] Per-task `backend_id` assignment UX in jour fixe / plan review

## Phase 3 — Multi-forge

- [ ] GitLab adapter
- [ ] OneDev adapter
- [ ] Forge abstraction hardening based on what Phase 1/2 actually needed

## Phase 4 — Multi-chat & polish

- [ ] Signal adapter (stub exists; raises `NotImplementedError`)
- [ ] Telegram adapter (documented as lower-privacy, see `SECURITY.md`)
- [x] Basic status/query chat commands (`/status`, `/plan`, `/help`) outside jour fixe
- [ ] Ad-hoc mid-day requests (mini-planning session vs. backlog queue)
- [ ] Multi-agent Matrix rooms (still one coordinator owns routing)
- [ ] Dashboards or richer reporting, if still wanted

## Open questions

Tracked as issues — see the [issues list](https://github.com/alexseymer/sluice/issues) tagged `question`. Key ones from the PRD:

1. Do Cursor/Agy/Codex expose any usable quota/usage signal, or does Sluice need to estimate budgets heuristically?
2. How reliably can silent fallback-model downgrade be detected per backend?
3. Should dependency inference happen automatically from jour fixe conversation, or should it always be explicit?
4. What's the task-to-backend assignment policy when multiple backends could run a task?
5. How does an ad-hoc mid-day request (outside jour fixe) get handled — mini-planning session, or queued to backlog?

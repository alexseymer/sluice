# Roadmap

This roadmap mirrors the phasing in [`docs/prd.md`](docs/prd.md). It's public and will change as we learn things — treat it as a snapshot of current intent, not a promise.

## Where we are

**Phase 1 is complete.** Sluice runs end-to-end via Docker Compose: cron-triggered jour fixe sessions, conversational planning over Matrix, GitHub issue filing on `/approve`, background dispatch with dependency ordering, budget pacing, and forge sync when issues close.

**Phase 2 is mostly done.** Four AI CLI backends ship (Claude Code, Cursor, Agy, Codex) with heuristic budget probing, quota detection, and fallback-model failover across backends.

**Next up:** scheduling refinements from real-world budget data, multi-forge support, and additional chat backends.

## Phase 1 — Core loop (single forge, single chat) ✅

Jour fixe → plan → GitHub issues → dispatch to AI CLI backends → budget tracking → Matrix chat.

- [x] Jour fixe scheduler (cron-triggered sessions + timeout handling)
- [x] Conversational jour fixe chat (AI CLI pass-through or OpenAI-compatible LLM API)
- [x] Planner: conversation → dependency-ordered task list (LLM + heuristic fallback)
- [x] GitHub adapter: create/update/link issues
- [x] Plan approval flow in chat → file issues on `/approve`
- [x] AI CLI backend adapters (Claude Code, Cursor, Agy, Codex)
- [x] Basic time-window budget tracking with SQLite persistence
- [x] Background dispatch loop (dependency-aware scheduling + completion notifications)
- [x] Forge sync (poll GitHub for closed issues → mark tasks complete)
- [x] Matrix chat backend (Signal remains a stub)
- [x] Interactive `sluice setup` wizard (GitHub device flow, Matrix provisioning)
- [x] Docker Compose bring-up (GHCR image published on `main`)

## Phase 2 — Multi-backend (mostly complete)

- [x] Cursor adapter
- [x] Agy adapter
- [x] Codex adapter
- [x] Fallback-model detection (heuristic output parsing per backend + scheduler failover)
- [x] Budget probing beyond cautious defaults until quota errors are observed
- [ ] Scheduling refinements once real budget data exists across backends (smarter pacing, per-task backend assignment policy)
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
- [ ] Dashboards or richer reporting, if still wanted at this point

## Open questions

Tracked as issues, not resolved here — see the [issues list](https://github.com/alexseymer/sluice/issues) tagged `question`. Key ones from the PRD:

1. Do Cursor/Agy/Codex expose any usable quota/usage signal, or does Sluice need to estimate budgets heuristically? *(Currently heuristic probing + output parsing.)*
2. How reliably can silent fallback-model downgrade be detected per backend? *(Regex heuristics exist; accuracy TBD in production.)*
3. Should dependency inference happen automatically from jour fixe conversation, or should it always be explicit? *(LLM planner infers; heuristic fallback chains numbered items.)*
4. What's the task-to-backend assignment policy when multiple backends could run a task? *(First backend with budget headroom; failover on quota/fallback.)*
5. How does an ad-hoc mid-day request (outside jour fixe) get handled — mini-planning session, or queued to backlog?

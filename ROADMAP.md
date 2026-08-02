# Roadmap

This roadmap mirrors the phasing in [`docs/prd.md`](docs/prd.md). It's public and will change as we learn things — treat it as a snapshot of current intent, not a promise. Each phase links to a tracking issue where the actual breakdown lives.

## Phase 1 — Core loop (single backend, single forge, single chat)
Jour fixe → plan → GitHub issues → dispatch to one AI CLI backend → basic budget tracking → Matrix or Signal chat.

- [ ] Jour fixe scheduler + chat session flow
- [ ] Planner: conversation → dependency-ordered task list
- [x] GitHub adapter: create/update/link issues
- [x] Plan approval flow in chat → file issues on approve
- [ ] One AI CLI backend adapter (candidate: Claude Code, given documented CLI/output format)
- [ ] Basic time-window budget tracking for that backend
- [x] One chat backend (Matrix — Signal stub remains)
- [x] Docker Compose bring-up

## Phase 2 — Multi-backend
- [ ] Cursor adapter
- [ ] Agy adapter
- [ ] Codex adapter
- [ ] Fallback-model detection (per backend, since this likely differs)
- [ ] Scheduling refinements once real budget data exists across backends

## Phase 3 — Multi-forge
- [ ] GitLab adapter
- [ ] OneDev adapter
- [ ] Forge abstraction hardening based on what Phase 1/2 actually needed

## Phase 4 — Multi-chat & polish
- [ ] Telegram adapter (documented as lower-privacy, see `SECURITY.md`)
- [ ] Status/query commands outside jour fixe
- [ ] Dashboards or richer reporting, if still wanted at this point

## Open questions

Tracked as issues, not resolved here — see the [issues list](https://github.com/alexseymer/sluice/issues) tagged `question`. Key ones from the PRD:

1. Do Cursor/Agy/Codex expose any usable quota/usage signal, or does Sluice need to estimate budgets heuristically?
2. How is silent fallback-model downgrade detected per backend?
3. Should dependency inference happen automatically from jour fixe conversation, or should it always be explicit?
4. What's the task-to-backend assignment policy when multiple backends could run a task?
5. How does an ad-hoc mid-day request (outside jour fixe) get handled — mini-planning session, or queued to backlog?

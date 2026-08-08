# PRD: Sluice — Matrix ↔ CLI coordinator for forge-backed work

**Status:** Draft v0.2
**Owner:** [you]
**Last updated:** 2026-08-08

---

## 1. Summary

**Sluice** is a Python application that lets a solo builder run CLI coding agents over Matrix without babysitting terminals. Forge issues/PRs are the source of truth for execution. Matrix is where the builder and **one coordinator** CLI agent brainstorm, set direction, and handle escalations — when the coordinator hits a substantial question it can't resolve alone, it asks in Matrix rather than guessing. Approve/reject gates forge filing; day-to-day chat is discussion → adjustments → directions.

Sluice rides **subscription** coding CLIs (Cursor, Agy, Codex, Claude Code, and others), not metered chat APIs. Hosting is secondary: always a slim Linux with those CLIs (Docker Compose is the easy path; VM/VPS/Pi/bare metal are fine). Budget pacing across backends is a supporting mechanism so subscription windows aren't burned in one burst.

---

## 2. Problem Statement

- CLI coding agents already have generous subscription tokens, but they don't collaborate over Matrix without the human babysitting terminals.
- Solo builders want to set direction once and check in asynchronously, while dependency ordering and forge audit trails stay coherent.
- Metered chat-API agent stacks (OpenClaw-class) compete on a different cost model; Sluice is for people who already pay for coding CLIs.
- Bursting through a subscription window still causes silent downgrade or overage — pacing helps, but it is not the primary product story.
- Existing orchestration tools often assume Slack/SaaS relays rather than a privacy-respecting, self-hostable chat channel.

---

## 3. Goals

1. Give the solo builder a Matrix channel with **one coordinator** for brainstorming, direction, and escalation.
2. Keep forge issues/PRs as the backlog and audit trail for execution.
3. Translate jour-fixe discussion into dependency-aware issues, gated by human `/approve` / `/reject`.
4. Dispatch work to subscription CLI backends with dependency ordering; escalate substantial questions to Matrix instead of guessing.
5. Pace CLI usage as a supporting mechanism to stay under subscription limits and avoid fallback/overage where possible.
6. Stay self-hostable on slim Linux (Compose-first docs; host choice is not the product).

## 4. Non-Goals (v1)

- Not making external-tool setup a primary product goal.
- Not treating host choice (Docker / VM / VPS / Pi / bare metal) as the product.
- Not competing as a metered chat-API agent stack.
- Not a general-purpose CI/CD system — it schedules AI-driven dev work, not builds.
- Not a replacement for the AI CLI tools themselves.
- Not multi-agent Matrix rooms yet (one coordinator owns routing; multi-agent rooms later).
- No multi-tenant/team mode in v1 — single human, single Sluice instance.

---

## 5. Users / Personas

**Primary persona: Solo builder** who pays for one or more AI coding CLI subscriptions and wants to clear (or run) their backlog over Matrix — brainstorm and escalate with a coordinator in chat, execute against forge issues/PRs — without babysitting worker terminals or burning metered API budget.

---

## 6. Core Concepts

| Concept | Description |
|---|---|
| **Coordinator** | The single orchestrating CLI agent that plans, gates work, and escalates substantial questions to Matrix. |
| **Jour fixe** | A scheduled recurring session where the human and coordinator discuss upcoming work via Matrix. |
| **Escalation** | When the coordinator/worker cannot resolve a substantial question alone, it asks in Matrix (`/retry`, `/skip`, or free-text direction). |
| **Plan** | The dependency-ordered breakdown of jour-fixe discussion into discrete, issue-sized units of work. |
| **Issue** | A unit of work filed on the connected Git forge — source of truth for execution. |
| **Backend** | An AI CLI tool adapter (Cursor, Agy, Codex, Claude Code, ...) with its own rate-limit/quota model. |
| **Budget window** | Supporting usage allowance for a backend (pacing mechanism, not the primary product). |
| **Dependency graph** | DAG of issues, derived from explicit links or inferred from jour-fixe discussion. |

---

## 7. Functional Requirements

### 7.1 Jour Fixe & Planning
- FR1: System supports a configurable recurring schedule (cron-like) for jour fixe sessions.
- FR2: At jour fixe time, system proactively messages the human on their configured chat channel to start the session.
- FR3: During jour fixe, the human and coordinator converse about desired work; the coordinator asks clarifying questions rather than guessing.
- FR4: At the end of jour fixe (explicit close command or timeout), the system generates a structured plan: list of tasks, estimated size/complexity, proposed dependencies.
- FR5: Human can review and approve/amend the plan before issues are created (configurable: auto-approve vs. require explicit confirmation).

### 7.2 Issue Management
- FR6: System creates issues on the configured Git forge(s) via a common abstraction (create, update, label, link dependencies, close).
- FR7: Dependency relationships are represented using each forge's native mechanism where available, with a forge-agnostic internal DAG as source of truth.
- FR8: System can detect and surface circular dependencies before scheduling.
- FR9: Issue status is synced bidirectionally — if a human or AI closes/comments on an issue directly on the forge, Sluice picks that up on its next poll/webhook.

### 7.3 Scheduling & Execution
- FR10: System maintains a per-backend budget model as a supporting pacing mechanism.
- FR11: System spreads ready (unblocked) issues across the day/week to stay under each backend's budget when possible.
- FR12: Before dispatching a task, system checks the dependency graph and only dispatches issues whose blockers are marked done.
- FR13: System dispatches a task to a backend by invoking that backend's CLI (isolated worktree), capturing output, logs, and resulting diffs/commits.
- FR14: On backend failure, quota exhaustion, or unexpected fallback-model detection, system reschedules or fails over, and notifies the human if the delay is significant.
- FR14b: On substantial ambiguity or exhausted review iterations, system escalates to Matrix and waits for guidance / `/retry` / `/skip` rather than guessing.
- FR15: Task-to-backend assignment can be manual or automatic (budget headroom / failover).
- FR16: Completed work is committed/pushed per the forge's normal flow, with the corresponding issue updated/closed.

### 7.4 Human Communication
- FR17: System supports Matrix as the primary chat backend; Signal and Telegram remain planned.
- FR18: Human can query status at any time, including pending escalations.
- FR19: Human can send interrupts and mid-flight direction outside the jour fixe cadence.
- FR20: System sends proactive notifications for: plan ready for review, task completed, escalation needed, task blocked/failed, budget exhausted, dependency conflict.

### 7.5 AI Backend Adapters
- FR21: Each backend is a pluggable adapter (dispatch task, check budget/quota, detect fallback-model, cancel/kill).
- FR22: Adapters run each task in an isolated environment (worktree) to avoid cross-task interference.
- FR23: New backends can be added without changes to the core scheduler.

### 7.6 Deployment & Ops
- FR24: Documented bring-up via `docker compose up`; runnable on any slim Linux with CLI agents.
- FR25: All credentials supplied via environment variables or mounted secrets — never hardcoded or logged.
- FR26: System persists state so it survives restarts.

---

## 8. Non-Functional Requirements

### 8.1 Privacy (chat layer) — critical
- NFR1: **Signal**: integrate via `signal-cli` (or equivalent self-hosted bridge) — planned.
- NFR2: **Matrix**: connect as a bot user to a homeserver the human controls or trusts; support E2E-encrypted rooms.
- NFR3: **Telegram**: documented as weaker privacy; included later for convenience, not as the baseline.
- NFR4: No message/task/code content sent beyond: chat protocol, Git forge, and chosen AI CLIs.
- NFR5: No analytics/telemetry by default; if added later, opt-in and documented.
- NFR6: Local state stored only in the human's datastore (volume), not synced elsewhere.
- NFR7: Secrets never appear in logs.

### 8.2 Reliability
- NFR8: Scheduler must be crash-safe — restart must not lose in-flight or queued work.
- NFR9: Budget tracking is conservative when used — prefer under-using a quota over risking fallback/overage.

### 8.3 Extensibility
- NFR10: Git forge and AI backend abstractions are plugin-based.

### 8.4 Security
- NFR11: Tokens and CLI auth scoped to least privilege where possible.
- NFR12: Task execution sandboxing prevents AI actions outside the assigned repo/worktree.

---

## 9. High-Level Architecture

```
                        ┌─────────────────────────┐
                        │   Chat Abstraction       │
                        │ (Matrix today; Signal /  │
                        │  Telegram planned)       │
                        └───────────┬─────────────┘
                                    │
                        ┌───────────▼─────────────┐
                        │      Sluice Core         │
                        │  - Coordinator / jour    │
                        │    fixe + escalation     │
                        │  - Planner               │
                        │  - Dependency graph      │
                        │  - Scheduler / budget    │
                        │  - State store           │
                        └───────┬───────────┬──────┘
                                │           │
                  ┌─────────────▼───┐   ┌───▼─────────────┐
                  │ Git Forge        │   │ AI Backend       │
                  │ (issues/PRs SoT) │   │ (subscription    │
                  │ GitHub today;    │   │  CLIs)           │
                  │ GitLab/OneDev    │   │                  │
                  │ planned          │   │                  │
                  └──────────────────┘   └──────────────────┘
```

---

## 10. Key Open Questions

1. **Budget introspection**: Do Cursor/Agy/Codex expose usable quota APIs, or stay heuristic?
2. **Fallback-model detection**: How reliable is silent-downgrade detection per backend?
3. **Dependency inference**: Auto-infer from conversation vs always explicit?
4. **Multi-backend assignment policy**: Headroom, affinity, round-robin, or human default?
5. **Ad-hoc mid-day requests**: Mini-planning session vs backlog until next jour fixe?
6. **OneDev API maturity**: Issue linking parity with GitHub/GitLab?

---

## 11. Success Metrics

Aligned with [`STRATEGY.md`](../STRATEGY.md):

- **Unattended issue completion rate** — % of forge issues closed by Sluice without opening a coding CLI
- **Plan → merge latency** — time from approve to merged PR / closed issue
- **Coordinator-routed throughput** — issues completed per day/week under the coordinator loop
- **Human gate interventions** — `/reject`, mid-flight redirects, or manual forge overrides per week
- **Review-pass rate** — % of worker outputs accepted by reviewer on first pass

Supporting: near-zero unplanned fallback/overage events for a defined workload baseline.

---

## 12. Suggested Phasing

**Phase 1 — Core loop (done):** Matrix ↔ coordinator, GitHub issues, CLI backends, approve gate, escalation, budget pacing as support.

**Phase 2 — Multi-backend polish:** Scheduling refinements from real budget data; per-task backend UX.

**Phase 3 — Multi-forge:** GitLab and OneDev.

**Phase 4 — Multi-chat & polish:** Signal/Telegram; richer status; multi-agent Matrix rooms later.

---

## 13. Risks

| Risk | Mitigation |
|---|---|
| AI CLI tools change auth/output formats | Thin adapters; version-pin where possible |
| Workers guess instead of escalating | Prompt + `ESCALATE:` protocol + review-exhaustion → Matrix |
| Dependency graph errors | Require human `/approve` before issue creation |
| Privacy goals conflict with Telegram | Document as opt-in/lower-privacy; Matrix default |

---

*End of draft. Ready for review — flag any section to expand, cut, or re-scope.*

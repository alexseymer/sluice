# PRD: Sluice — AI Work Orchestrator

**Status:** Draft v0.1
**Owner:** [you]
**Last updated:** 2026-08-01

---

## 1. Summary

**Sluice** is a Python application, deployed as a Docker container, that acts as a scheduling and coordination layer between a human and one or more AI coding CLI tools (Cursor, Agy, Codex, Claude Code, and others). Instead of the human driving each AI session interactively, the human meets the system once per day (or on a configurable cadence) in a "jour fixe" session to discuss and prioritize work. Sluice then converts that discussion into a dependency-aware task plan, files issues on a Git forge (GitHub, GitLab, or OneDev), and executes the plan by dispatching work to the underlying AI CLI tools throughout the day — deliberately pacing and spreading requests, like a sluice gate controlling flow, to stay under subscription rate/token limits and avoid being silently downgraded to a weaker fallback model or incurring expensive pay-as-you-go API overages.

The human's only touchpoint outside the jour fixe is a privacy-respecting chat channel (Signal, Telegram, or Matrix), used for status updates, approvals, and urgent interrupts.

---

## 2. Problem Statement

- AI coding subscriptions (Cursor, Claude Code, Codex, etc.) have usage windows/quotas. When exhausted, tools either fall back to a weaker model (silently degrading quality) or force the user onto metered API billing, which is significantly more expensive.
- Developers using these tools interactively tend to burst usage in short high-intensity sessions, which is exactly the pattern that triggers rate limiting or fallback.
- There's no existing tool that treats "AI coding capacity" as a schedulable, rate-limited resource to be budgeted across a day/week, the way a build farm schedules CI jobs.
- Humans don't want to babysit the AI all day; they want to set direction once and check in periodically, while trusting that dependency ordering (e.g., "don't start the API client task before the schema task is merged") is respected automatically.
- Existing orchestration/agent-framework tools are not privacy-first with respect to the human-facing communication channel — many assume Slack/webhooks through third-party SaaS with full message retention.

---

## 3. Goals

1. Let a human define a scope of work once per cadence (jour fixe), without needing to manually chunk it into rate-limit-safe pieces.
2. Automatically translate discussed work into Git issues with explicit dependency links.
3. Execute issues over time across multiple AI CLI backends, respecting each backend's own usage limits/windows, and pause/resume/reschedule work to avoid fallback-model degradation or overage billing.
4. Respect issue dependency graphs — never dispatch a task whose blockers aren't done.
5. Give the human a lightweight, asynchronous way to monitor and steer progress via Signal, Telegram, or Matrix, without exposing conversation content to third parties beyond what each protocol itself requires.
6. Be self-hostable via a single Docker container (+ minimal supporting services), so the human retains full control over data.

## 4. Non-Goals (v1)

- Not a general-purpose CI/CD system — it doesn't replace build pipelines, only schedules AI-driven dev work.
- Not a replacement for the AI CLI tools themselves — it drives them, doesn't reimplement them.
- Not aiming to support every Git forge on day one beyond an abstraction that makes adding new ones straightforward — GitHub, GitLab, and OneDev are the initial three.
- Not building a custom LLM or model router — model/tool selection is about *when and how much* to call each CLI, not picking the "best" model per task.
- No multi-tenant/team mode in v1 — single human, single Sluice instance.

---

## 5. Users / Personas

**Primary persona: Solo developer or small-team lead** who pays for multiple AI coding subscriptions (e.g., Cursor + Claude Code) and wants to extract maximum throughput from fixed-cost plans without tripping rate limits, while staying hands-off during the day.

---

## 6. Core Concepts

| Concept | Description |
|---|---|
| **Jour fixe** | A scheduled recurring session (e.g., daily 9am) where the human and Sluice discuss upcoming work via chat. Output: a prioritized task list. |
| **Plan** | The dependency-ordered breakdown of jour-fixe discussion into discrete, issue-sized units of work. |
| **Issue** | A unit of work filed on the connected Git forge, with metadata: dependencies, estimated effort/token budget, assigned AI backend, status. |
| **Backend** | An AI CLI tool adapter (Cursor, Agy, Codex, Claude Code, ...) with its own rate-limit/quota model. |
| **Budget window** | The tracked usage allowance for a given backend (e.g., "Claude Code: X messages per 5-hour window", "Cursor: Y premium requests per month"). |
| **Schedule slot** | A time-boxed allocation during which Sluice is permitted to dispatch work to a specific backend. |
| **Dependency graph** | DAG of issues, derived from explicit links (e.g., "blocks"/"blocked by") set during planning or inferred from the jour-fixe discussion. |

---

## 7. Functional Requirements

### 7.1 Jour Fixe & Planning
- FR1: System supports a configurable recurring schedule (cron-like) for jour fixe sessions.
- FR2: At jour fixe time, system proactively messages the human on their configured chat channel to start the session.
- FR3: During jour fixe, the human and AI converse conversationally about desired work; the AI asks clarifying questions as needed (scope, priority, constraints).
- FR4: At the end of jour fixe (explicit close command or timeout), the system generates a structured plan: list of tasks, estimated size/complexity, proposed dependencies.
- FR5: Human can review and approve/amend the plan before issues are created (configurable: auto-approve vs. require explicit confirmation).

### 7.2 Issue Management
- FR6: System creates issues on the configured Git forge(s) via a common abstraction (create, update, label, link dependencies, close).
- FR7: Dependency relationships are represented using each forge's native mechanism where available (e.g., GitHub task lists/"Depends on", GitLab issue links, OneDev issue dependencies), with a forge-agnostic internal DAG as source of truth.
- FR8: System can detect and surface circular dependencies before scheduling.
- FR9: Issue status is synced bidirectionally — if a human or AI closes/comments on an issue directly on the forge, Sluice picks that up on its next poll/webhook.

### 7.3 Scheduling & Execution
- FR10: System maintains a per-backend budget model (requests/tokens per time window), configurable per subscription plan, refreshed on a rolling or fixed-window basis.
- FR11: System computes a dispatch schedule that spreads ready (unblocked) issues across the day/week to stay under each backend's budget, prioritizing avoiding fallback-model triggers over pure throughput.
- FR12: Before dispatching a task, system checks the dependency graph and only dispatches issues whose blockers are marked done.
- FR13: System dispatches a task to a backend by invoking that backend's CLI (in an isolated execution context — see 7.5), capturing output, logs, and resulting diffs/commits.
- FR14: On backend failure, quota exhaustion, or unexpected fallback-model detection, system reschedules the task to a later slot or a different capable backend, and notifies the human if the delay is significant.
- FR15: Task-to-backend assignment can be manual (human specifies in jour fixe) or automatic (system picks based on task type, backend availability, and budget headroom).
- FR16: Completed work is committed/pushed per the forge's normal flow (e.g., branch + PR/MR), with the corresponding issue updated/closed.

### 7.4 Human Communication
- FR17: System supports Signal, Telegram, and Matrix as chat backends from v1, via a common messaging abstraction.
- FR18: Human can query status ("what's in progress", "what's blocked", "show today's schedule") at any time, not just during jour fixe.
- FR19: Human can send interrupts (pause all work, cancel a specific issue, reprioritize) outside the jour fixe cadence.
- FR20: System sends proactive notifications for: plan ready for review, task completed, task blocked/failed, budget exhausted for a backend, dependency conflict detected.

### 7.5 AI Backend Adapters
- FR21: Each backend (Cursor, Agy, Codex, Claude Code, ...) is implemented as a pluggable adapter behind a common interface (dispatch task, check budget/quota status, detect fallback-model condition, cancel/kill running task).
- FR22: Adapters run each task in an isolated environment (e.g., ephemeral container or worktree) to avoid cross-task interference.
- FR23: New backends can be added without changes to the core scheduler (plugin/adapter pattern).

### 7.6 Deployment & Ops
- FR24: Entire system runs via `docker compose up` (Sluice + any required datastore, e.g., SQLite/Postgres for state).
- FR25: All credentials (Git forge tokens, messaging tokens/keys, CLI auth) are supplied via environment variables or a mounted secrets file — never hardcoded or logged.
- FR26: System persists state (plans, schedules, budgets, issue cache) so it survives container restarts.

---

## 8. Non-Functional Requirements

### 8.1 Privacy (chat layer) — critical
- NFR1: **Signal**: integrate via `signal-cli` (or equivalent self-hosted bridge) run locally in the container/stack — no third-party SaaS relay of message content.
- NFR2: **Matrix**: connect as a bot user to a homeserver the human controls or trusts (self-hosted preferred); support E2E-encrypted rooms.
- NFR3: **Telegram**: acknowledged as the weakest-privacy option of the three (Telegram retains server-side data by default, no E2E in normal chats); documented clearly as such, and Secret Chats are not bot-API compatible so cannot be used for bot conversations. Included for convenience/reach, not as the privacy baseline.
- NFR4: No message content, task content, or code is sent to any third-party service beyond: (a) the chosen chat protocol's own infrastructure, (b) the Git forge, (c) the AI CLI backends themselves (which the human has already chosen to trust with code).
- NFR5: No analytics, telemetry, or crash reporting phones home by default; if added later, must be opt-in and documented.
- NFR6: Local state (plans, chat history, budgets) stored only in the human's own datastore (container volume), not synced elsewhere.
- NFR7: Secrets never appear in logs; logs are redacted/scrubbed by default.

### 8.2 Reliability
- NFR8: Scheduler must be crash-safe — a Sluice restart mid-task must not lose track of in-flight or queued work.
- NFR9: Budget tracking must be conservative — prefer under-using a quota over risking a fallback/overage event, with a configurable safety margin (e.g., stop at 85% of window).

### 8.3 Extensibility
- NFR10: Git forge abstraction and AI backend abstraction are both plugin-based, so GitHub/GitLab/OneDev and Cursor/Agy/Codex/Claude Code (and future tools) all implement the same interface.

### 8.4 Security
- NFR11: Git forge tokens and CLI auth are scoped to least privilege where the platform allows it.
- NFR12: Task execution sandboxing prevents an AI-generated action from affecting anything outside its assigned repo/worktree.

---

## 9. High-Level Architecture

```
                        ┌─────────────────────────┐
                        │   Chat Abstraction       │
                        │ (Signal / Telegram /     │
                        │  Matrix adapters)        │
                        └───────────┬─────────────┘
                                    │
                        ┌───────────▼─────────────┐
                        │      Sluice Core    │
                        │  - Jour fixe manager       │
                        │  - Planner                 │
                        │  - Dependency graph engine │
                        │  - Scheduler / budget mgr  │
                        │  - State store (SQLite/PG) │
                        └───────┬───────────┬────────┘
                                │           │
                  ┌─────────────▼───┐   ┌───▼─────────────┐
                  │ Git Forge        │   │ AI Backend       │
                  │ Abstraction      │   │ Abstraction      │
                  │ (GitHub/GitLab/  │   │ (Cursor/Agy/     │
                  │  OneDev)         │   │  Codex/Claude    │
                  │                  │   │  Code, ...)      │
                  └──────────────────┘   └──────────────────┘
```

All components run inside one Docker Compose stack; each adapter is a plugin implementing a shared interface so new forges/backends can be added independently.

---

## 10. Key Open Questions

1. **Budget introspection**: Do Cursor/Agy/Codex expose any usage/quota API or CLI flag? If not, budgets may need to be estimated heuristically (token/request counting) or configured manually based on known plan limits — worth a short spike before committing to auto-scheduling accuracy claims.
2. **Fallback-model detection**: For tools that silently downgrade rather than error, how do we detect it (parsing CLI output/model banner, response quality heuristics)? This may differ per backend and needs per-adapter research.
3. **Dependency inference**: Should the planner infer dependencies from natural conversation, or should the human always explicitly state them during jour fixe? (Affects planning UX and error risk.)
4. **Multi-backend task assignment**: When a task could run on any of several backends, what's the assignment policy — cost/quota headroom, task-type affinity, round robin, or human-specified default?
5. **Concurrent jour fixe interrupts**: If the human wants to add scope mid-day outside jour fixe, does that spawn a mini-planning session or just queue as unplanned/backlog until next jour fixe?
6. **OneDev API maturity**: Confirm OneDev's REST API covers issue linking/dependencies to the same degree as GitHub/GitLab before treating all three as equally first-class.

---

## 11. Success Metrics

- Zero (or near-zero) unplanned fallback-model or overage events per week, for a defined workload baseline.
- % of jour-fixe-planned tasks completed within the following cadence period without manual re-scheduling.
- Reduction in human active interaction time per day (target: interaction limited to jour fixe + occasional async check-ins).
- No dependency-violation incidents (a task started before its blocker completed).

---

## 12. Suggested Phasing

**Phase 1 — Core loop, single backend, single forge, single chat:**
Jour fixe → plan → GitHub issues → dispatch to one AI CLI backend (whichever has the best-documented interface, e.g., Claude Code) → basic budget tracking → Matrix or Signal chat.

**Phase 2 — Multi-backend:**
Add Cursor, Agy, Codex adapters; add fallback-model detection; refine scheduling algorithm.

**Phase 3 — Multi-forge:**
Add GitLab and OneDev adapters behind the existing abstraction.

**Phase 4 — Multi-chat & polish:**
Add Telegram and remaining chat backend(s); harden privacy/security; add dashboards/status queries.

---

## 13. Risks

| Risk | Mitigation |
|---|---|
| AI CLI tools change auth/output formats, breaking adapters | Isolate each tool behind a thin adapter interface; version-pin CLI tools where possible |
| No reliable way to detect quota fallback for some tools | Start conservative (time-based budgets only) until detection is validated per tool |
| Dependency graph errors cause bad execution order | Require explicit human approval of the plan before issue creation in v1 |
| Privacy goals conflict with Telegram's architecture | Document Telegram as opt-in/lower-privacy tier; default recommendation is Signal or Matrix |

---

*End of draft. Ready for review — flag any section to expand, cut, or re-scope.*

---
name: Sluice
last_updated: 2026-08-08
---

# Sluice Strategy

## Target problem

CLI coding agents already have generous subscription tokens, but they don't collaborate over Matrix without you babysitting terminals.

## Our approach

Forge issues/PRs are the source of truth for execution. Matrix is where the solo builder and one coordinator CLI agent brainstorm, set direction, and handle escalations — when the coordinator hits a substantial question it can't resolve alone, it asks in Matrix rather than guessing. Approve/reject still gates forge filing; day-to-day chat is discussion → adjustments → directions, so work runs without babysitting worker terminals or burning metered API budgets.

## Who it's for

**Primary:** Solo builder - They're hiring Sluice to clear (or run) their backlog with CLI coding agents over Matrix, without babysitting terminals or burning metered API budget.

## Key metrics

- **Unattended issue completion rate** - % of forge issues closed by Sluice without opening a coding CLI
- **Plan → merge latency** - time from approve to merged PR / closed issue
- **Coordinator-routed throughput** - issues completed per day/week under the coordinator loop
- **Human gate interventions** - `/reject`, mid-flight redirects, or manual forge overrides per week
- **Review-pass rate** - % of worker outputs accepted by reviewer on first pass

## Tracks

### Matrix ↔ CLI bridge

Reliable chat so the coordinator can plan, escalate, and take direction in Matrix without the user opening worker terminals.

_Why it serves the approach:_ Collaboration and unblockings live in conversation; work product lives on the forge.

### Forge task backbone

Issues/PRs as source of truth across GitHub / GitLab / OneDev.

_Why it serves the approach:_ The forge — not chat memory — is the backlog and audit trail.

### Opinionated coordinator

One orchestrator plans, assigns, gates work, and escalates substantial questions to Matrix (multi-agent rooms later; one coordinator owns routing).

_Why it serves the approach:_ Opinionation keeps solo-builder collaboration coherent.

### Safety & auditability

Human gates, isolation, and a trail the solo builder can trust.

_Why it serves the approach:_ Self-hostable collaboration only works if the human stays in control of what ships.

## Not working on

- Making external-tool setup a primary product goal
- Treating host choice (Docker / VM / VPS / Pi / bare metal) as the product — it's always a slim Linux with CLI agents
- Competing as a metered chat-API agent stack (OpenClaw-class); Sluice rides subscription CLI agents instead

## Marketing

**One-liner:** Sluice lets solo builders run several CLI coding agents over Matrix — brainstorm and escalate with a coordinator in chat, execute against forge issues/PRs, on generous subscription tokens without terminal babysitting.

**Key message:** Matrix is the control and direction channel with one coordinator. The forge is where work is tracked. Hosting is wherever a slim Linux fits.

# Prompts — Fort GBUS Counter-Drone Decision Aid

*Draft 1, written by Claude Code for student review and editing.*

## Files

| File | Used by | Purpose |
|---|---|---|
| `shared.txt` | All three agents | Common context, the fixed process, rules for every agent, data conventions |
| `analyst.txt` | Analyst | Role, step-by-step procedure, constraints, output |
| `reviewer.txt` | Reviewer | Independent check, comparison checklist, verdict rules |
| `safety.txt` | Safety agent | Control-room information, advice categories, forward-only rule |
| `tools.md` | All (becomes tool schemas in code) | Tool descriptions, who can use what, output structures |

Each agent's system prompt = `shared.txt` + its role file. The shared part is identical for
all three, which also makes it a good candidate for prompt caching (lower cost per run).

## Rules for editing these prompts

1. **Keep them general.** Never mention a specific event, time, or answer. When a run fails,
   fix it with a general rule that would also work on an event the agents have never seen.
2. **Explain the why** where a rule might be misapplied.
3. **Every change gets a new version** in the table below, and the run log records which
   version each run used. This is how the "failure found and fixed" is shown.

## Versions

| Version | Date | Files changed | Change | Why |
|---|---|---|---|---|
| v1 | 2026-11-18 | all | First draft | — |

## Review checklist (for the student)

- Does each role match how you would want a real analyst, reviewer, or safety officer to
  think?
- Is anything missing that an experienced counter-drone operator would check?
- Is any rule stated too rigidly, or too loosely?
- Does the safety agent's advice give the control room what it needs, in the right order?

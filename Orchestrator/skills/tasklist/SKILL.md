---
name: tasklist
description: Author a TASKS.md work list from a goal, PRD, or spec — in the canonical format the /orchestrate deterministic runner executes. Use when the user runs /tasklist or asks to "create a task list", "break this down into tasks", "scaffold TASKS.md", "turn this PRD/goal into tasks", or "plan the build". Works in any repo.
---

# /tasklist — author a runnable TASKS.md

Turn a goal (or a PRD / spec / design doc) into a `TASKS.md` at the repo root,
written in the exact format the `/orchestrate` runner consumes. The output is a
**plan**, not implementation — you decompose and sequence; you do not build.

The canonical format is defined in **`task-format.md`** (next to this file). Read
it first and follow it exactly; the notes below are how to *author well* within
it.

## Steps

1. **Get the goal and the source of truth.** Use the user's `/tasklist` argument
   as the goal. If they point at a doc (a PRD, spec, README, issue), read it —
   it is the substance of the tasks. If the goal is vague or missing key scope,
   ask 2–3 sharp clarifying questions before decomposing (target platforms,
   must-haves vs nice-to-haves, hard constraints). Don't invent scope.

2. **Detect the project's gate and constraints** (they go in the header, and the
   runner executes the gate verbatim):
   - Inspect the repo for the real commands: test runner, typecheck, lint,
     formatter, e2e (e.g. read `package.json` scripts, `Makefile`, CI workflow).
   - Compose the **Gate** from what actually exists and must pass (e.g.
     `npm test`, `npx tsc -b`, `npm run lint`). If a category is per-task (e.g.
     UI tasks also run e2e), say so in the Gate line.
   - If the project has a **formatter** (e.g. `npm run format:check`, `cargo fmt`,
     `ruff format`, `gofmt`), add it as the optional **Format check** line — the
     coder runs it before the gate to auto-fix style. Omit the line entirely if
     there is no formatter; the runner is language-agnostic and just skips it.
   - Derive **Standing constraints** from the project's own rules (CLAUDE.md,
     architecture docs, obvious invariants). If none are discoverable, ask the
     user for 2–4, or omit the section rather than invent.
   - If the repo has no test/lint tooling yet, make the very first task set it
     up, and let its Gate be minimal until then.

3. **Decompose into milestones and tasks.**
   - Group work into `## M<n> — <name>` milestones that build on each other
     (infrastructure → core → surface → hardening → ship is a common spine).
   - Each task is **one coherent, reviewable unit** — a few files and a clear
     Accept, not "build the whole frontend". If a task needs more than a
     paragraph to describe, split it (use `T-NNNa` / `T-NNNb`).
   - Set `after:` to the real prerequisites so the DAG is honest — the runner
     uses it for eligibility and ordering. No cycles.
     Before writing TASKS.md, validate the DAG: (1) **Cycle check** — trace each
     task's `after:` chain; if any task is reachable from itself the runner will
     loop forever. (2) **Reachability check** — every task ID in an `after:` field
     must exist in the list; a missing reference silently blocks that task forever.
   - Choose `coder:` per task: the stronger model for cross-cutting design or
     tricky tasks, the cheaper model for mechanical ones. Default to the
     project's convention if one exists.
   - **Mark human gates with `[BLOCKED BY = <reason>]`** in the heading (see
     `task-format.md` §3). Any task needing a human decision — a visual/taste
     checkpoint, a sign-off, an external unblock — must carry this tag so the
     runner force-stops and never self-approves it. Put one at the end of a
     milestone when you want the run to halt there for review rather than roll
     into the next milestone.

4. **Write Accept criteria that a reviewer can mechanically check.** Every clause
   should be verifiable from the diff or by running something: "test X asserts
   Y", "command Z exits 0", "file present and used", "property holds over N
   seeds". Reject vague criteria ("works well", "is fast") — rewrite them as an
   observable check. This is the single most important quality bar: the whole
   loop's correctness rests on Accept being checkable.

5. **Write the header** (Orchestrator protocol + Gate + Standing constraints +
   Statuses legend) per `task-format.md`, then the milestones and tasks. Include
   a short intro naming the source-of-truth doc(s), and optionally a
   "Deliberately deferred" section at the end for explicit out-of-scope items.

6. **Write `TASKS.md` to the repo root.** Then summarize: how many milestones and
   tasks, the dependency spine, and the first few eligible tasks. Tell the user
   they can build it out with `/orchestrate all` (or a subset).

## Guardrails
- **Plan only.** Do not implement, install, or commit as part of `/tasklist`
  unless the user asks — produce the file and stop.
- **Don't pad the count.** Fewer, well-scoped tasks beat many stub tasks. Every
  task must be real work with a real Accept.
- **Keep it self-contained.** A task body + the header pointers must be enough
  for a coder with no other context to implement it — sub-agents don't share
  memory.
- **If a target `TASKS.md` already exists**, don't clobber it — show what you'd
  add/change and confirm, or append new milestones.
- **Validate the DAG before writing:** confirm no cycles and no `after:` references
  to nonexistent task IDs.

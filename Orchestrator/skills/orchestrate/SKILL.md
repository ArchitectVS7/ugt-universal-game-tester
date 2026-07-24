---
name: orchestrate
description: Deterministically build out TASKS.md via the plan→code→review→gate→commit loop, using the Workflow engine (control flow in code, not model judgment, so it will not drift or stop early). Use when the user runs /orchestrate or asks to "run the task list", "do all the tasks", "build out TASKS.md", or "run the orchestrator". Pass scope as an argument.
---

# /orchestrate — deterministic task-list runner

This is a **user-global, repo-agnostic** runner. It executes the task loop as a **Workflow**, not as a model-driven skill loop. The determinism is the entire point: the order, the plan→code→review→gate→commit sequence, the per-stage model pinning, and the "keep going until the list is dry" decision all live in JavaScript (`orchestrate-tasks.js`, next to this file). The model only fills in the content of each stage — it never decides whether to continue, so it cannot drift over many tasks or misread "do all of them" and stop early. Nothing is hard-coded to a project: the **gate command, source-of-truth pointers, and standing constraints are read from the target repo's `TASKS.md` header** at launch.

**Roles / models (pinned in the script):** Planner = Opus (overridable per-run via `args.planModel`, e.g. `"fable"`) · Coder = Opus · Reviewer + Gate + Commit = Sonnet. The Select stage (parsing TASKS.md for the next eligible task) is a small Sonnet extraction — the only model touchpoint in the control flow; the `while` loop, not the model, decides continuation.

**Failure policy:** review + gate must both pass. On failure: one normal Opus fix round, then one MAX-effort Opus fix round, then **halt** and report — the repo is left at the last green commit with the failing task's changes uncommitted for review. Never bypasses a check.

## What to do when invoked

1. **Parse the argument into a scope:**
   - empty, `all`, or `*` → `"all"` (every eligible TODO, in dependency order, until the list is dry)
   - one or more task IDs (e.g. `T-303 T-304`) → an array: `["T-303","T-304"]`
   - a milestone label (e.g. `M3`) → the string `"M3"`

2. **Launch the workflow** (this is the required Workflow opt-in — do not re-implement the loop inline):

   Pass `scriptPath` as the **absolute** path to this skill's own `orchestrate-tasks.js` (resolve `~` to the home directory — e.g. `/Users/<you>/.claude/skills/orchestrate/orchestrate-tasks.js`), and run it against the current repo's working directory:

   ```
   Workflow({
     scriptPath: "~/.claude/skills/orchestrate/orchestrate-tasks.js",   // pass the resolved absolute path
     args: { scope: <parsed scope> }
   })
   ```

   If the user asked for a different planner model (e.g. "plan with Fable"), add `planModel: "fable"` to `args`. Only the Plan stage is affected; Code/Review/Gate/Commit stay pinned.

   If a `graphify-out/` directory exists at the target repo root, add `treeIgnore: ["graphify-out/"]` to `args` — a post-commit graphify hook regenerates that directory asynchronously and can leave it dirty between tasks; without this the runner's dirty-tree precondition halts before doing any work.

   It runs in the background and per task: sets the task IN-PROGRESS, plans (Opus), codes (Opus), reviews + gates (Sonnet) with the escalate-then-halt ladder, then on green commits `T-NNN: <title>` with the TASKS.md status flip to DONE **in the same commit**, and finally pushes the branch at the end of the run.

3. **Relay the result** the workflow returns: the list of `completed` task IDs, or — if it halted — the `stoppedAt` task and the `reason`. Do not paraphrase a halt as success.

## Notes
- The gate is **whatever the target repo's `TASKS.md` header declares** on its `**Gate (every task):**` line (plus any per-category note, e.g. "UI tasks also run e2e"). The runner reads it at launch — if that line is missing it stops immediately and asks you to add one (see the `tasklist` skill's format). An optional `**Format check:**` header line names a formatter the coder runs before the gate; absent, the step is skipped.
- Because every task commits before the next begins, an interruption (usage limit, halt) is safe and **resumable**: just run `/orchestrate` again and it picks up the next eligible TODO from TASKS.md.
- **Human input gates halt the run.** A task whose heading carries `[BLOCKED BY = <reason>]` (or a legacy CHECKPOINT that says it must halt / never be self-approved) is detected in code: the runner does the task's automated preparation, commits it with status `BLOCKED(<reason>)` — never `DONE`, never a fabricated approval — and **stops**. Relay the `stoppedAt` task and reason as a halt (not success); only the user flips a gate task to DONE. This is also the reliable way to stop a run at a milestone boundary.
- To cap spend on a long run, the caller can pass a token budget (e.g. a "+500k" directive); the loop stops cleanly when the remaining budget gets low.
- This does not change TASKS.md's protocol — TASKS.md remains the canonical work list and rule source; this skill just executes it deterministically.

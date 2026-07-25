# Orchestrator — a deterministic task-list build loop (bonus feature)

A pair of Claude Code skills that turn a goal into a runnable work list and then
**build it out task-by-task on autopilot** — planning, coding, reviewing, gating,
and committing each task in dependency order until the list is dry.

This folder is a **shareable bonus** bundled with UGT. It is not part of the UGT
framework itself and has no dependency on it — the two skills work in *any* git
repository. They're included here because this is the workflow UGT's own
integrations are built with, and it's genuinely useful on its own.

- `skills/tasklist/` — **`/tasklist`**: author a `TASKS.md` work list from a goal,
  PRD, or spec, in the exact format the runner consumes.
- `skills/orchestrate/` — **`/orchestrate`**: execute that `TASKS.md`
  deterministically via the Workflow engine (control flow lives in JavaScript, not
  model judgment).

---

## Why this exists

If you hand a coding agent "do all the tasks in this list," it tends to drift: it
reorders work, skips the review step when it's confident, declares victory early,
or quietly bypasses a failing check. The failure isn't the model's coding — it's
that the model is also being trusted to run the *control flow* (what's next, did it
pass, keep going or stop).

The Orchestrator takes that control flow away from the model and puts it in code:

- **The loop is JavaScript.** A `while` loop — not the model — decides whether to
  continue. It runs every eligible task in dependency order and only stops when the
  list is dry, a task fails the gate after escalation, or a human gate is hit.
- **The model only fills in stage content.** Plan the task, write the code, review
  the diff, run the gate, write the commit. It never decides *whether* to advance.
- **Checks are sacred.** Review **and** gate must both pass. Failures escalate
  (normal Opus fix → max-effort Opus fix → max-effort Fable fix) and then
  **halt** — no `--no-verify`, no deleting
  tests, no narrowing scope to dodge a red.
- **Every task commits before the next starts.** So an interruption (usage limit,
  a halt, you closing the laptop) is always safe and resumable — just run
  `/orchestrate` again and it picks up the next eligible task.

The result is a build loop you can point at a 40-task list and walk away from,
that leaves the repo either fully built or stopped at a clearly-reported red — never
in a silently-broken "looks done" state.

---

## Requirements

- **Claude Code** with the Workflow (multi-agent orchestration) engine available —
  `/orchestrate` launches a Workflow, which spawns sub-agents per stage.
- A **git repository** at your working-directory root. Every task is a commit.
- A project **gate** you can express as shell commands (tests, typecheck, lint,
  e2e — whatever must pass). `/tasklist` detects it for you; you confirm it.
- Optional but recommended: a `gh` CLI logged in, if you want per-task CI evidence
  (the runner pushes each commit and waits for the branch's CI to go green before
  starting the next task; with no CI configured it simply skips that wait).

---

## Install

These are **user-global** Claude Code skills — they live in `~/.claude/skills/`
and are then available as `/tasklist` and `/orchestrate` in every repo you open.

Copy the two skill folders out of this bundle into your Claude skills directory:

```bash
mkdir -p ~/.claude/skills
cp -R "Orchestrator/skills/tasklist"    ~/.claude/skills/tasklist
cp -R "Orchestrator/skills/orchestrate" ~/.claude/skills/orchestrate
```

Restart Claude Code (or start a new session) so it picks up the new skills. Type
`/` and you should see `tasklist` and `orchestrate` in the list.

> The `orchestrate` skill resolves the absolute path to its own
> `orchestrate-tasks.js` at launch, so it must live next to `SKILL.md` inside the
> skill folder — keep the folder intact when you copy it.

---

## The two-step workflow

### Step 1 — author the list: `/tasklist`

Run `/tasklist` with your goal (or point it at a PRD/spec/design doc). It will:

1. Read your source-of-truth doc, asking 2–3 sharp clarifying questions if the
   scope is vague.
2. **Detect your project's gate** — it inspects `package.json` scripts, a
   `Makefile`, CI workflows, etc. to find the real test/typecheck/lint/e2e
   commands, and derives **Standing constraints** from your `CLAUDE.md` / architecture
   docs.
3. Decompose the work into **milestones** (`M0`, `M1`, …) each holding **tasks**,
   with an honest `after:` dependency DAG, a `coder:` model per task, and a
   mechanically-checkable **Accept** line for each.
4. Write `TASKS.md` to your repo root and summarize the milestones, the dependency
   spine, and the first eligible tasks.

`/tasklist` **plans only** — it writes the file and stops. It won't implement,
install, or commit. Read the file, tweak anything, then move to step 2.

Examples:

```
/tasklist Build a REST API for the widget service per docs/SPEC.md
/tasklist Add offline mode to the mobile app
```

### Step 2 — build it out: `/orchestrate`

Run `/orchestrate` with a scope. It launches the Workflow and, per task, runs the
full loop, committing each task before moving to the next:

```
/orchestrate all            # every eligible task, dependency order, until dry
/orchestrate T-303 T-304    # only these specific tasks
/orchestrate M3             # only tasks under the M3 milestone
```

When it finishes it reports the list of **completed** task IDs, or — if it stopped
— the task it **stopped at** and **why**.

---

## What one task looks like (the loop)

For each task the runner executes these stages, each as an isolated sub-agent with
a pinned model:

| Stage      | Model         | Job |
|------------|---------------|-----|
| **Select** | Sonnet (low)  | Read `TASKS.md`, return the next eligible task. The *only* model touchpoint in control flow — it only extracts; the `while` loop decides continuation. |
| **Plan**   | Opus\*        | Produce a concrete implementation plan from the task block + the header's source-of-truth pointers. |
| **Code**   | Opus (Fable on the final fix round) | Edit the repo per the plan; add the tests the task requires. |
| **Review** | Sonnet        | Check the working diff against the task's **Accept** criteria and the Standing constraints. |
| **Gate**   | Sonnet (low)  | Run the project gate commands verbatim; pass only if every command exits 0. |
| **Commit** | Sonnet        | Commit `T-NNN: <title>` and flip the task's status to DONE **in the same commit**. |

\* The planner model is overridable per run (see "Plan with a different model"
below); all other stages stay pinned.

**Preconditions and verification are enforced in code, not left to the model:**

- It refuses to start a task on a **dirty working tree** (an interrupted task's
  uncommitted edits are a human decision — finish or discard — so it halts).
- After committing, it **verifies the commit actually landed** (tree clean AND HEAD
  is this task's commit) before advancing. A silent no-op can't drift the protocol.
- With CI configured, it **pushes each commit and waits for CI to go green** before
  the next task starts.

---

## Failure policy — escalate, then halt

Review **and** gate must both pass. On a failure the runner does **not** give up
immediately and does **not** bypass the check:

1. One **normal** Opus fix round → re-check.
2. One **max-effort** Opus fix round → re-check.
3. One **max-effort** Fable fix round → re-check.
4. Still failing → **HALT.** The repo is left at the last green commit, with the
   failing task's changes **uncommitted** for your review, and the run reports
   `stoppedAt` + the reason.

It never uses `--no-verify`, never deletes or weakens tests, and never narrows
scope to dodge a red. A halt is reported as a halt — never paraphrased as success.

---

## Human gates — stopping for a decision the model can't make

Some work needs a human: a visual/taste checkpoint, a sign-off, an external
unblock. Mark such a task by adding **`[BLOCKED BY = <reason>]`** to its heading:

```markdown
### T-099 · CHECKPOINT — visual review of M1 — `status: TODO` · `coder: sonnet` · `after: T-098` · `[BLOCKED BY = Human Gate]`
Regenerate the screenshot gallery into `docs/gallery/m1/` (committed). Then the
run halts for the human to review hand-feel against the rubric.
**Accept:** (human-checked) gallery committed; human explicitly approved.
```

When the runner reaches a gate task it:

1. Does the task's **automated preparation** (regenerate the artifact, run the
   gate) so you have something concrete to review.
2. Commits that work with status **`BLOCKED(<reason>)`** — *never* `DONE`, and
   never with a fabricated "user approved" note.
3. **Halts the whole run.** Only you can later flip the task to `DONE`.

This is detected by a deterministic regex on the heading, so the model can't
rationalize it away. Put a gate task at the end of a milestone whenever you want the
run to stop there for review instead of rolling into the next milestone.

---

## The `TASKS.md` format (in brief)

`TASKS.md` lives at the repo root and has two parts. It is a per-project working file —
if you are using the Orchestrator within a shared framework repo, add `TASKS.md` to that
repo's `.gitignore` so it stays on disk but out of the shared surface. The full spec is in
[`skills/tasklist/task-format.md`](skills/tasklist/task-format.md); the short version:

**Header** (written once) — an Orchestrator protocol blurb, then the two lines the
runner reads at launch:

```markdown
**Gate (every task):** `npm test` and `npm run lint` both exit 0.

**Format check (optional):** `npm run format:check`

**Standing constraints** (the reviewer enforces on every task):
- Public API changes require a changelog entry.
- No new runtime dependencies without a note in the task body.
```

The **Format check** line is optional: name a formatter (`cargo fmt`, `ruff
format`, `gofmt -w .`, …) and the coder runs it before the gate to auto-fix style;
omit the line and the step is skipped. See "Adapting to your stack" below.

**Task entries** — an `###` heading with inline metadata, a one-paragraph body, and
an **Accept** line:

```markdown
### T-001 · Project scaffold — `status: TODO` · `coder: opus` · `after: —`
Initialize the package, test runner, and lint config.
**Accept:** `npm test` runs (0 tests ok); `npm run lint` exits 0; CI workflow present.
```

- **`status:`** ∈ `TODO` / `IN-PROGRESS` / `DONE` / `BLOCKED(reason)` — the runner
  flips this.
- **`after:`** — comma-separated prerequisite IDs (or `—`) forming the dependency
  DAG. A task is eligible when it's `TODO` and every `after:` id is `DONE`.
- **`coder:`** — which model implements it (`opus` / `sonnet` / `fable`).
- **`**Accept:**`** — mechanically checkable criteria. This is the single most
  important quality bar: the whole loop's correctness rests on Accept being
  verifiable from the diff or by running something. Reject "works well"; write
  "test X asserts Y" / "command Z exits 0".

The gate command and standing constraints are **read from your `TASKS.md` header**
at launch — nothing is hardcoded to a project. That's why the same runner works on
any repo: author a compliant `TASKS.md` (with `/tasklist`), then `/orchestrate`.

---

## Resumability & long runs

- **Interruptions are safe.** Because every task commits before the next begins, a
  usage-limit stop, a halt, or a killed session leaves the repo at a clean commit.
  Re-run `/orchestrate` and it resumes from the next eligible task. A task that was
  mid-flight (`IN-PROGRESS`, clean tree) is preferred on resume so it's finished,
  not orphaned.
- **Cap the spend.** Pass a token budget (a `+500k`-style directive) and the loop
  stops cleanly at a task boundary when the remaining budget runs low.

---

## Adapting to your stack

The runner is deliberately language-agnostic: **your real checks live in the
`TASKS.md` header you write**, not in the script. The runner reads the gate,
format check, standing constraints, and source-of-truth pointers from that header
at launch and briefs every sub-agent with them, so pointing it at a Python, Rust,
Go, or any other repo needs **no edits to the script** — just a `TASKS.md` whose
header names that project's real commands. Still, a few things are worth knowing:

- **The gate is the contract.** Whatever you put on `**Gate (every task):**` is run
  verbatim and must all exit 0. Make it your actual test / typecheck / lint / e2e
  commands. This is the one thing that *must* be right for a given repo.
- **Formatting is now config-driven.** Earlier versions hardcoded a JS
  `npm run format:check` pre-gate pass; this bundled copy reads it from the
  optional `**Format check:**` header line instead. Name your formatter there
  (`cargo fmt`, `ruff format`, `gofmt -w .`, …) or omit the line — either way no
  JS/npm toolchain is assumed.
- **CI evidence assumes GitHub + `gh`.** After each commit the runner pushes and
  waits for the branch's CI to go green before the next task. It uses the `gh` CLI
  and `.github/workflows/*.yml`. With no `gh`, no GitHub, or no workflows, it
  cleanly reports **no CI** and continues — your **local gate still runs and still
  halts on failure**. On GitLab/Bitbucket/local-only repos you simply get no
  *remote* CI gate; nothing breaks. (You can also skip the push-and-poll wait for a
  run — see below.)
- **`git` is required.** Every task is a commit; that's the resumability mechanism.

In short: to run this on a new stack, author a `TASKS.md` with `/tasklist` (it
detects your gate and formatter for you) and go. The only reason to touch
`orchestrate-tasks.js` is a personal preference like the commit trailer.

## Handy variations

**Plan with a cheaper/different model** — only the Plan stage changes; Code /
Review / Gate / Commit stay pinned. Ask, e.g., "run /orchestrate all but plan with
Fable," and it passes `planModel: "fable"` through.

**Repos with a post-commit artifact generator** — if a hook re-dirties an output
directory after each commit (e.g. a `graphify-out/` regeneration), that would trip
the dirty-tree precondition. The skill detects a `graphify-out/` directory and
passes `treeIgnore: ["graphify-out/"]` automatically; for other generated dirs,
mention it and the same knob applies. (graphify itself is a separate, optional
skill — it is not part of this bundle, and without it every graphify reference
here is simply inert: the planner's existence check finds no `graphify-out/`
and moves on.)

**Skip remote CI for one run** — when CI can't produce a verdict (billing block,
runners offline) or is deliberately disabled, the run can skip the push-and-poll CI
wait. This does **not** weaken the local gate — every task still runs the full gate
and still halts on failure.

---

## File map

```
Orchestrator/
├── README.md                          ← you are here (the user manual)
└── skills/
    ├── tasklist/
    │   ├── SKILL.md                    the /tasklist command
    │   └── task-format.md             the canonical TASKS.md format spec
    └── orchestrate/
        ├── SKILL.md                    the /orchestrate command (launches the Workflow)
        ├── README.md                   the runner's own reference notes
        └── orchestrate-tasks.js        the Workflow engine — the deterministic loop
```

---

## Credits

Both skills author their commits with a personal `Co-Authored-By` trailer. If you
adopt them, edit that trailer in `skills/orchestrate/orchestrate-tasks.js` (search
for `Co-Authored-By`) to your own preferred attribution.

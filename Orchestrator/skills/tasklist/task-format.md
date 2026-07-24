# TASKS.md format

The canonical, project-agnostic format for a `TASKS.md` work list that the
`/orchestrate` deterministic runner can execute. Keep the file at the **repo
root**, named exactly `TASKS.md`.

A `TASKS.md` has two parts: a **header** (protocol + gate + constraints, written
once) and a sequence of **milestones** each containing **task entries**.

---

## 1. Header

```markdown
# <Project> — Master Task List

<1–3 sentence intro: what this list builds, and pointers to the source of truth
(a PRD, design doc, spec) if one exists.>

## Orchestrator protocol

1. **Check out** the first task with `status: TODO` whose `after:` tasks are all DONE. Set it `IN-PROGRESS`.
2. **Plan** — hand the coder the task block plus the pointers named in the intro. Nothing else.
3. **Code** — implement per the plan and the Standing constraints.
4. **Review** — check the diff against the task's **Accept** criteria (written to be mechanically checkable).
5. On pass: run the gate, commit as `<ID>: <title>`, set `status: DONE`, update this file in the same commit. On fail: one fix round, then escalate, then halt.

**Gate (every task):** <the exact commands that must all exit 0 — e.g. `npm test`, `npx tsc -b`, lint. Name any extra per-category gate, e.g. UI tasks also run e2e.>

**Format check (optional):** <a single formatter / format-check command the coder runs before the gate to auto-fix style, so formatting never burns a gate fix round — e.g. `npm run format:check`, `cargo fmt`, `ruff format`, `gofmt -w .`. Omit this whole line if the project has no formatter.>

**Standing constraints** (the reviewer enforces on every task):
- <project-wide invariant #1>
- <project-wide invariant #2>

Statuses: `TODO` | `IN-PROGRESS` | `DONE` | `BLOCKED(reason)`

---
```

The **Gate** and **Standing constraints** are project-specific and must be real,
runnable commands / checkable rules for the target repo — the runner executes
the gate verbatim and the reviewer enforces the constraints. The **Format check**
is optional and equally project-specific: the coder runs it (verbatim) before the
gate to auto-fix style; leave the line out entirely when the project has no
formatter and the runner simply skips that step — nothing about the runner assumes
a JS/npm toolchain.

---

## 2. Milestones

Group tasks under milestone headings. The milestone label (the `M<n>` token) is
usable as an `/orchestrate` scope filter.

```markdown
## M0 — Infrastructure
## M1 — <name>
```

---

## 3. Task entry

Each task is an `###` heading with inline metadata, a body, and an **Accept**
line:

```markdown
### T-001 · CI for the monorepo — `status: TODO` · `coder: opus` · `after: —`
One paragraph describing the work concretely: what to build, where, and which
files/modules are in scope. This paragraph is the "task block" handed verbatim
to the planner and coder.
**Accept:** mechanically checkable criteria — the reviewer must be able to verify
each one from the diff or by running something. Prefer "X file present and green",
"test Y asserts Z", "command W exits 0" over vague goals.
```

### Required fields (in the heading, in this order)

| Field | Form | Meaning |
|-------|------|---------|
| **ID** | `T-NNN` (zero-padded, unique) | Stable id; used verbatim in the commit subject `T-NNN: <title>`. Sub-tasks may use `T-NNNa`, `T-NNNb`. |
| **Title** | text after `· ` | Short human title; becomes the rest of the commit subject. |
| **status** | `` `status: TODO` `` | One of TODO / IN-PROGRESS / DONE / BLOCKED(reason). The runner flips this. |
| **coder** | `` `coder: opus` `` | Which model implements it (opus / sonnet / fable). Tasks with cross-cutting design decisions are usually the stronger model. |
| **after** | `` `after: T-101, T-102` `` | Comma-separated prerequisite IDs, or `—` / `none`. Defines the dependency DAG that gates eligibility. |

### Optional field — the human input gate `[BLOCKED BY = …]`

Add `[BLOCKED BY = <reason>]` to a task heading to make it a **hard human gate**.
When the runner selects a gate task it does the automated preparation the body
describes (regenerate an artifact, run the gate), commits that work with status
**`BLOCKED(<reason>)`** — *never* `DONE` — and then **halts the entire run**.
Only a human may later flip it to `DONE`. The runner will never self-approve it,
and because the halt is unconditional it also stops a run from sailing past a
milestone boundary into the next milestone's first task.

```markdown
### T-099 · CHECKPOINT — visual review of M1 — `status: TODO` · `coder: sonnet` · `after: T-098` · `[BLOCKED BY = Human Gate]`
Regenerate the screenshot gallery into `docs/gallery/m1/` (committed). Then the
run halts for the human to review hand-feel against the rubric.
**Accept:** (human-checked) gallery committed; human explicitly approved.
```

- **Detection is by tag**, in code — a `[BLOCKED BY = …]` anywhere in the heading
  triggers the gate (the reason is whatever follows `=`; `:` also works). Legacy
  tasks that only say "CHECKPOINT … never self-approved … halt the run" in prose
  are still caught, but new tasks should use the explicit tag.
- **The gate task's own automated deliverable still runs** — the artifact is
  produced and committed, so the human has something concrete to review.
- **Accept criteria for a gate task belong to the human.** The runner does *not*
  machine-review them (a clause like "user explicitly approved" is unsatisfiable
  unattended); only the technical **Gate** must pass before the BLOCKED commit.
- Use it for: visual/taste checkpoints, sign-offs, anything requiring a human
  decision, and as a deliberate stop at the end of a milestone.

### Body + Accept
- **Body** — one paragraph (occasionally a short list). Self-contained: a coder
  with only this paragraph + the header pointers should know what to build.
- **`**Accept:**`** — the acceptance criteria. This is the reviewer's checklist,
  so every clause must be **verifiable**, not aspirational.

---

## 4. Rules the runner relies on

- **Eligibility** — a task is runnable when its `status: TODO` and every `after:`
  id is `DONE`. Order within that is file order (top to bottom).
- **No cycles** — `after:` must form a DAG; never point a task at a later task
  that depends back on it.
- **DONE is append-only truth** — mark `DONE` only when the gate passed and the
  work is committed. On completion, append a short `**Delivered (<date>):**`
  note to the entry (what shipped, any deliberate scope boundary).
- **BLOCKED carries a reason** — `BLOCKED(waiting on external API keys)`. A task
  tagged `[BLOCKED BY = <reason>]` (see §3) is force-stopped by the runner: it is
  committed `BLOCKED(<reason>)` and the run halts; only a human resumes it.
- **Optional trailing section** — a "Deliberately deferred" list at the bottom
  records out-of-scope items so they don't get re-scoped in.

---

## 5. Minimal template

```markdown
# Widgets — Master Task List

Build the widget service per docs/SPEC.md.

## Orchestrator protocol
1. Check out the first `status: TODO` task whose `after:` are all DONE; set IN-PROGRESS.
2. Plan → 3. Code → 4. Review vs **Accept** → 5. Gate, commit `<ID>: <title>`, set DONE, update this file in the same commit.

**Gate (every task):** `npm test` and `npm run lint` both exit 0.

**Format check (optional):** `npm run format:check`

**Standing constraints:**
- Public API changes require a changelog entry.
- No new runtime dependencies without a note in the task body.

Statuses: `TODO` | `IN-PROGRESS` | `DONE` | `BLOCKED(reason)`

---

## M0 — Foundation

### T-001 · Project scaffold — `status: TODO` · `coder: opus` · `after: —`
Initialize the package, test runner, and lint config.
**Accept:** `npm test` runs (0 tests ok); `npm run lint` exits 0; CI workflow present.

### T-002 · Widget model + store — `status: TODO` · `coder: opus` · `after: T-001`
Define the `Widget` type and an in-memory CRUD store with typed errors.
**Accept:** unit tests cover create/read/update/delete and the not-found error path; types exported from the package entry.
```

# /orchestrate — deterministic task-list runner

Builds out a `TASKS.md` work list by running a **plan → code → review → gate →
commit** loop, one task at a time, until the list is dry or a task fails the gate
after escalation. It is a **Workflow** (deterministic JavaScript control flow),
not a model-driven skill loop — so it does not drift over many tasks and does not
misread "do all of them" and stop early. The model only fills in the content of
each stage; the `while` loop, not the model, decides whether to continue.

## Files
- `SKILL.md` — the `/orchestrate` command: parses the scope arg and launches the
  workflow.
- `orchestrate-tasks.js` — the workflow engine (the loop). Referenced by
  `scriptPath` from the skill.

## Usage
```
/orchestrate all            # every eligible TODO, dependency order, until dry
/orchestrate T-303 T-304    # just these tasks
/orchestrate M3             # tasks under the M3 milestone
```

## Roles & models (pinned in the script)
| Stage | Model | Job |
|-------|-------|-----|
| Select | Sonnet (low) | read `TASKS.md`, return the next eligible TODO — the only model touchpoint in control flow; it only *extracts* |
| Plan | Opus | produce the implementation plan from the task block + pointers |
| Code | Opus | edit the repo per the plan |
| Review | Sonnet | check the diff against the task's **Accept** criteria |
| Gate | Sonnet (low) | run the gate commands; pass only if all exit 0 |
| Commit | Sonnet | commit `T-NNN: <title>` + flip status to DONE in the same commit |

## Failure policy — escalate then halt
Review **and** gate must both pass. On failure: one normal Opus fix round → one
MAX-effort Opus fix round → **halt**. On halt the repo is left at the last green
commit with the failing task's changes uncommitted for review, and the run
reports `stoppedAt` + the reason. Checks are never bypassed.

## Resumability
Every task commits before the next begins, so an interruption (usage limit, halt)
is safe: re-run `/orchestrate` and it picks up the next eligible TODO from
`TASKS.md`. Pass a token budget (a "+500k"-style directive) to cap a long run;
the loop stops cleanly when the remaining budget gets low, mid-task boundaries
respected.

## The TASKS.md it consumes
The full authoring spec lives in **`../tasklist/task-format.md`** (use the
`/tasklist` skill to generate a compliant file). In brief, per task it relies on:
- `### T-NNN · <Title> — ` `status: …` · `coder: …` · `after: …`` heading
- `status:` ∈ TODO / IN-PROGRESS / DONE / BLOCKED(reason)
- `after:` — comma-separated prerequisite IDs (or `—`) forming a DAG
- a one-paragraph body (the "task block")
- a `**Accept:**` line of mechanically checkable criteria
- `## M<n> — …` milestone headings (used as scope filters)
- a header with the **Gate** command and **Standing constraints**

## Portability
This is a **user-global, repo-agnostic** runner (`~/.claude/skills/orchestrate/`).
Nothing is tuned to a specific project — at launch it reads three things from the
target repo's `TASKS.md` header and briefs every sub-agent with them:
- the **gate command** (the `**Gate (every task):**` line — run verbatim)
- the **standing constraints** (the reviewer enforces them)
- the **source-of-truth pointers** (the intro docs)

So on any repo: run `/tasklist` to author a compliant `TASKS.md` (its header
carries the gate + constraints for that project), then `/orchestrate`. No
per-repo edits to the script.

The two remaining assumptions are conventions of the format itself: `TASKS.md`
lives at the working-directory root, and the task headings use the fields below.
The Select stage is an LLM reading the file, so it tolerates reasonable variation
— but the commit subject, scope filtering, and Accept extraction rely on them.
The commit trailer is the user's personal `Co-Authored-By` line.

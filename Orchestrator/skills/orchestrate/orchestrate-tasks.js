export const meta = {
  name: 'orchestrate-tasks',
  description:
    'Deterministically run the plan -> code -> review -> gate -> commit loop over TASKS.md. Control flow is code, not model judgment: it runs every eligible task in dependency order and never stops early unless a task fails the gate after escalation.',
  whenToUse:
    'Invoked by the /orchestrate command to build out TASKS.md. Pass args.scope = "all" | ["T-303","T-304"] | "M3".',
  phases: [
    { title: 'Select', detail: 'pick the next eligible TODO from TASKS.md' },
    { title: 'Plan', detail: 'planner (opus unless overridden via args.planModel)' },
    { title: 'Code', detail: 'Opus coder edits the repo (Fable on the final fix round)', model: 'opus' },
    { title: 'Review', detail: 'Sonnet reviewer vs acceptance criteria', model: 'sonnet' },
    { title: 'Gate', detail: 'run the project gate from the TASKS.md header', model: 'sonnet' },
    { title: 'Commit', detail: 'commit + flip TASKS.md status', model: 'sonnet' },
  ],
};

// ---------------------------------------------------------------------------
// This runner is repo-agnostic. The gate command, the source-of-truth pointers,
// and the standing constraints are read ONCE from the target repo's TASKS.md
// header (see the tasklist skill's task-format.md) — nothing is hard-coded to a
// particular project. Sub-agents have isolated context, so the derived
// `briefing` below is their whole standing brief.
// ---------------------------------------------------------------------------

// ---- structured-output schemas ----
const CONFIG = {
  type: 'object',
  additionalProperties: false,
  properties: {
    gate: {
      type: 'string',
      description:
        'the exact command(s) on the header "**Gate (every task):**" line, verbatim, including any per-category note (e.g. "UI tasks also run e2e")',
    },
    constraints: {
      type: 'string',
      description: 'the Standing constraints block, condensed to a sentence or two',
    },
    pointers: {
      type: 'string',
      description: 'the intro source-of-truth docs/pointers, or empty if none',
    },
    format: {
      type: 'string',
      description:
        'the exact command on the header "**Format check" line (verbatim), which the coder runs before the gate to auto-fix style; empty if the header declares no such line (many non-JS projects will not)',
    },
  },
  required: ['gate'],
};
const NEXT_TASK = {
  type: 'object',
  additionalProperties: false,
  properties: {
    id: { type: ['string', 'null'], description: 'e.g. "T-303", or null if no eligible task' },
    title: { type: 'string' },
    block: { type: 'string', description: 'the full task block, verbatim' },
    accept: { type: 'string', description: 'the **Accept:** acceptance criteria line(s)' },
    isUi: { type: 'boolean', description: 'true if this is an M3/UI task or its coder builds packages/ui' },
    resuming: {
      type: 'boolean',
      description: 'true iff the chosen task was ALREADY IN-PROGRESS (a resume of an interrupted run), not a fresh TODO',
    },
  },
  required: ['id'],
};
const REVIEW = {
  type: 'object',
  additionalProperties: false,
  properties: {
    pass: { type: 'boolean' },
    findings: { type: 'array', items: { type: 'string' } },
  },
  required: ['pass'],
};
const GATE = {
  type: 'object',
  additionalProperties: false,
  properties: {
    pass: { type: 'boolean' },
    output: { type: 'string', description: 'tail of failing output when pass=false' },
  },
  required: ['pass'],
};
const CISTATE = {
  type: 'object',
  additionalProperties: false,
  properties: {
    state: {
      type: 'string',
      enum: ['no-ci', 'pending', 'success', 'failure', 'push-failed'],
      description:
        'no-ci = no workflows configured; pending = a run is still queued/in_progress; success = every run concluded success; failure = a run concluded non-success; push-failed = git push failed',
    },
    output: { type: 'string', description: 'brief detail: failing run names/conclusions, or the push error' },
  },
  required: ['state'],
};
const TREE = {
  type: 'object',
  additionalProperties: false,
  properties: {
    clean: { type: 'boolean' },
    files: { type: 'array', items: { type: 'string' } },
    head: { type: 'string', description: 'subject line of git log -1 (the current HEAD commit)' },
  },
  required: ['clean'],
};
const MILESTONE_IDS = {
  type: 'object',
  additionalProperties: false,
  properties: {
    ids: { type: 'array', items: { type: 'string' }, description: 'every task ID under the matched heading, in file order' },
  },
  required: ['ids'],
};

// The workflow script has no shell of its own, so every git observation is a
// tiny read-only agent. `treeState` is the protocol's load-bearing invariant
// probe: it reports whether the working tree is clean (ignoring known infra like
// the orchestrator's own lock file) and what HEAD is, so the loop can refuse to
// build on a dirty tree and can verify a commit actually landed.
// Repos with post-commit artifact generators (e.g. a graphify hook that re-dirties
// its output dir after every commit) can pass args.treeIgnore = ['graphify-out/']
// so hook-generated dirt is neither a halt condition nor swept into task commits.
// Normalize args: some launch paths deliver the args value as a JSON-encoded
// string rather than an object — accept both.
const ARGS = (() => {
  if (args && typeof args === 'object') return args;
  if (typeof args === 'string') {
    try {
      const parsed = JSON.parse(args);
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
      return {};
    }
  }
  return {};
})();
const TREE_IGNORE = [
  '.claude/scheduled_tasks.lock',
  ...(Array.isArray(ARGS.treeIgnore) ? ARGS.treeIgnore : []),
];
async function treeState(ignore = TREE_IGNORE) {
  // Deterministic filter: dirty paths under an ignored prefix are stripped by an
  // exact grep the probe agent must run verbatim (prefix semantics enforced by
  // the regex, not by the agent's judgment).
  const pattern = ignore.map((p) => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
  return agent(
    `Run this EXACT command: \`git status --porcelain | grep -vE '^.. (${pattern})' || true\` — the grep strips ignorable infra paths (${ignore.join(', ')}); do not second-guess it. ` +
      `Also run \`git log -1 --format=%s\`. Return clean=true iff the first command printed NOTHING; files=the printed (non-ignorable) dirty paths, empty if clean; head=the HEAD commit's subject line. Change nothing.`,
    { phase: 'Select', model: 'sonnet', effort: 'low', schema: TREE, agentType: 'general-purpose' },
  );
}

// ---- scope ----
const scope = ARGS.scope ? ARGS.scope : 'all';
// Planner model is overridable per-run (e.g. args.planModel = 'fable'); all other stages stay pinned.
const planModel = ARGS.planModel ? ARGS.planModel : 'opus';

// Resolve scope to a concrete task-ID set ONCE, up front, so the loop can check
// Select's answer in code rather than trusting the model to honor a milestone
// label as a boundary. `scopeIds` is null only for the unrestricted 'all' case;
// an explicit ID-list scope is already concrete and passes through unchanged.
let scopeIds = null;
if (Array.isArray(scope)) {
  scopeIds = scope;
} else if (scope !== 'all') {
  const resolved = await agent(
    `Read TASKS.md. Find the milestone heading matching "${scope}" (e.g. a line like "## ${scope} — ..."). ` +
      `List the ID of every task ("### T-NNN ..." entry) that appears under that heading, up to (not including) the next "## " heading. Return ids = that list, in file order. Do not modify anything.`,
    { phase: 'Select', model: 'sonnet', effort: 'low', schema: MILESTONE_IDS, agentType: 'general-purpose' },
  );
  scopeIds = resolved && Array.isArray(resolved.ids) ? resolved.ids : [];
  if (!scopeIds.length) {
    log(`No tasks found under scope "${scope}" — check the milestone heading name. Nothing to do.`);
    return { completed: [], stoppedAt: null, reason: 'empty-scope' };
  }
}
const scopeText = scopeIds
  ? `only these task IDs, taken in dependency order: ${scopeIds.join(', ')}`
  : 'any eligible task, in the order they appear in TASKS.md';

async function pushBranch() {
  await agent('Run `git push` and report the result. If it fails, report the error verbatim.', {
    phase: 'Commit',
    model: 'sonnet',
    effort: 'low',
    agentType: 'general-purpose',
  });
}

const completed = [];
let guard = 0;

log(
  `Orchestrating TASKS.md — scope: ${Array.isArray(scope) ? scope.join(', ') : scope}` +
    (scopeIds ? ` (resolved -> ${scopeIds.join(', ')})` : '') +
    ` — tree-ignore: ${TREE_IGNORE.join(', ')}`,
);

// ---- read the project's gate + pointers + constraints ONCE from the header ----
phase('Select');
const config = await agent(
  'Read the HEADER of TASKS.md (everything above the first task entry). Return: `gate` = the exact command(s) on the "**Gate (every task):**" line, verbatim, including any per-category note; `constraints` = the "Standing constraints" condensed to a sentence or two; `pointers` = the intro source-of-truth docs, or empty; `format` = the exact command on the "**Format check" line verbatim (a formatter the coder runs before the gate), or empty if there is no such line. Do not modify anything.',
  { phase: 'Select', model: 'sonnet', effort: 'low', schema: CONFIG, agentType: 'general-purpose' },
);
if (!config || !config.gate || !config.gate.trim()) {
  log('No "Gate (every task)" line found in the TASKS.md header — add one (see the tasklist format) and re-run.');
  return { completed: [], stoppedAt: null, reason: 'missing-gate' };
}
const briefing =
  'The repo root is the working directory. ' +
  (config.pointers && config.pointers.trim() ? `Source of truth: ${config.pointers}. ` : '') +
  'Obey the "Orchestrator protocol" and "Standing constraints" in TASKS.md' +
  (config.constraints && config.constraints.trim() ? ` — in particular: ${config.constraints}` : '') +
  '.';

// The pre-gate format pass is config-driven (repo-agnostic): the coder runs
// whatever formatter the TASKS.md header's "**Format check:**" line declares, so
// style failures are auto-fixed before they can reach the gate. If the header
// has no such line (e.g. a project with no formatter, or a non-JS toolchain), the
// step is simply omitted — nothing about a JS/npm stack is assumed here.
const formatStep =
  config.format && config.format.trim()
    ? `Before returning, run \`${config.format.trim()}\` from the repo root and fix anything it flags — formatting failures must never reach the gate. `
    : '';

while (guard++ < 200) {
  if (budget.total && budget.remaining() < 60_000) {
    log(`Budget nearly spent (~${Math.round(budget.remaining() / 1000)}k left) — stopping cleanly after ${completed.length} task(s).`);
    break;
  }

  // ---- PRECONDITION: never start work on a dirty tree. An interrupted task
  // that coded but did not commit leaves its edits here; this invariant is what
  // makes two tasks' changes physically unable to intermingle in shared files.
  // A dirty tree = human decision (finish/commit or discard), so HALT rather
  // than build on top of it. (A CLEAN tree with a dangling IN-PROGRESS task is a
  // different case, handled by the resume-aware SELECT below.)
  const pre = await treeState();
  if (!pre.clean) {
    log(
      `HALT: working tree is dirty before selecting the next task (${(pre.files || []).join(', ') || 'unknown files'}). ` +
        `An interrupted task left uncommitted edits — commit or discard them, then re-run. Nothing was built on top.`,
    );
    if (completed.length) await pushBranch();
    return { completed, stoppedAt: null, reason: 'dirty-tree-precondition' };
  }

  // ---- SELECT (the one mechanical model touchpoint; the while-loop, not the
  // model, decides whether to continue). Resume an interrupted task before
  // starting a new one, so a dangling IN-PROGRESS is finished, not orphaned. ----
  phase('Select');
  const task = await agent(
    `Read TASKS.md. Pick the task to work next, restricted to ${scopeText}: PREFER the FIRST task whose status is IN-PROGRESS (a resume of an interrupted run); otherwise the FIRST task whose status is TODO and whose every \`after:\` dependency is already DONE. ` +
      `Return: id, title, the full task block verbatim (block), its acceptance criteria (accept), isUi, and resuming=true iff the chosen task was already IN-PROGRESS. If no such task exists, return id=null. Do not modify anything.`,
    { phase: 'Select', model: 'sonnet', effort: 'low', schema: NEXT_TASK, agentType: 'general-purpose' },
  );
  if (!task || !task.id) {
    log('No eligible tasks remain — run complete.');
    break;
  }
  // HARD BOUNDARY: code, not model discipline, enforces scope. If Select drifts
  // past a milestone/ID-list boundary (its instruction is prose, not a
  // guarantee), refuse to proceed rather than silently working outside scope.
  if (scopeIds && !scopeIds.includes(task.id)) {
    log(`Scope exhausted: next eligible task is ${task.id}, outside scope "${Array.isArray(scope) ? scope.join(', ') : scope}". Stopping.`);
    break;
  }
  log(`> ${task.id} — ${task.title}${task.resuming ? ' (resuming)' : ''}`);

  // ---- HUMAN-GATE DETECTION (code, not model judgment). A task carrying an
  // `[BLOCKED BY = <reason>]` input-gate tag (or a legacy CHECKPOINT that says it
  // must halt / never be self-approved) is a HUMAN GATE: the runner prepares any
  // artifact the task defines, commits it with status BLOCKED (NEVER DONE), and
  // HALTS the run. Only a human may later flip it to DONE. This is a hard stop
  // regardless of scope — it is the mechanism that keeps a run from sailing past
  // a milestone boundary and self-approving a review it cannot perform. The
  // detection is a deterministic regex over the verbatim task block so it cannot
  // be softened by a model rationalizing the prose away.
  const headingLine = typeof task.block === 'string' ? task.block.split('\n', 1)[0] : '';
  const gateTag = headingLine.match(/\[\s*BLOCKED\s+BY\s*[:=]\s*([^\]\n]+?)\s*\]/i);
  // Legacy fallback: a task whose TITLE is a CHECKPOINT (matched on the heading
  // line only, so a normal task merely *discussing* a checkpoint in its body is
  // not misfired). New tasks should carry the explicit [BLOCKED BY = …] tag.
  const legacyCheckpoint = /\bCHECKPOINT\b/i.test(headingLine);
  const isGate = Boolean(gateTag) || legacyCheckpoint;
  const gateReason = gateTag ? gateTag[1].trim() : legacyCheckpoint ? 'awaiting user review' : '';
  if (isGate) log(`  ${task.id} is a HUMAN GATE (${gateReason}) — will prepare, commit BLOCKED, and HALT (never self-approved).`);

  // Only flip a fresh TODO into IN-PROGRESS; a resumed task already is.
  if (!task.resuming) {
    await agent(`In TASKS.md, set ${task.id} status to IN-PROGRESS. Change nothing else. Do NOT commit.`, {
      phase: 'Select',
      model: 'sonnet',
      effort: 'low',
      agentType: 'general-purpose',
    });
  }

  // ---- PLAN (Opus) ----
  phase('Plan');
  const planRaw = await agent(
    `You are the PLANNER for ${task.id}. ${briefing}\n\nTask block:\n${task.block}\n\n` +
      `If graphify-out/graph.json exists in the repo root, first run \`graphify query "<question about the area this task touches>"\` (or \`explain\`/\`path\`) to orient before planning — it's a structural map, not a source of truth, so still ground the plan in the real spec/source files. Then start your output with exactly one line \`GRAPHIFY: <the query you ran>\` or \`GRAPHIFY: none — <why it wasn't applicable, e.g. no graph present, or the task is trivial/self-contained>\`, followed by a blank line. ` +
      `Then produce a concrete implementation plan: the exact files to touch, the approach, the tests to add, and how each acceptance criterion will be satisfied. Read only what you need to plan well. Output the plan as text for the coder — do NOT write code yourself.`,
    { phase: 'Plan', model: planModel, agentType: 'general-purpose' },
  );
  // Pull the leading GRAPHIFY tag (if the planner followed the instruction) into a
  // short label for the Commit stage's metric line; plain-code parse, not a model call.
  const graphifyMatch = typeof planRaw === 'string' ? planRaw.match(/^GRAPHIFY:\s*(.+)$/m) : null;
  const graphifyTag = graphifyMatch ? graphifyMatch[1].trim().slice(0, 160) : 'untagged';
  const plan = planRaw;

  // ---- CODE (Opus) ----
  phase('Code');
  await agent(
    `You are the CODER for ${task.id}. ${briefing}\n\nTask block:\n${task.block}\n\nImplementation plan:\n${plan}\n\n` +
      `Implement it now by editing the repo. Add the tests the task requires. Never bypass or weaken a check. ${formatStep}Do NOT commit. When done, briefly summarize what you changed.`,
    { phase: 'Code', model: 'opus', agentType: 'general-purpose' },
  );

  // ---- REVIEW + GATE with escalate-then-halt ----
  // attempt 0: review+gate on the initial code.
  // attempt 1: one normal Opus fix round, then re-check.
  // attempt 2: one MAX-effort Opus fix round, then re-check.
  // still failing -> halt (never leave a broken tree).
  const gatePrompt =
    `You are the GATE for ${task.id}. From the repo root run the project gate: ${config.gate}. ` +
    (task.isUi
      ? 'This is a UI/surface task, so ALSO run any per-category gate the gate spec names for such tasks (e.g. e2e). '
      : '') +
    `Return pass=true ONLY if every command exits 0. Run every command in the FOREGROUND and wait for it to exit — never launch background runs and never report while a command is still executing; give long commands (full test suites, e2e) up to 10 minutes each. If a command genuinely exceeds that, return pass=false with output naming exactly which command timed out — never guess a verdict from partial output. On any failure return pass=false with the failing output (tail). Do not fix anything.`;
  const reviewPrompt =
    `You are the REVIEWER for ${task.id}. ${briefing}\n\nAcceptance criteria:\n${task.accept}\n\n` +
    `Inspect the working diff (\`git status\`, \`git diff\`). Check each acceptance criterion mechanically and verify the Standing constraints. Return pass=true only if EVERY criterion is met; otherwise pass=false with specific findings.`;

  let ok = false;
  let report = '';
  let attemptsUsed = 0;
  // Escalation ladder: fix round 1 = Opus, fix round 2 = Opus at max effort,
  // fix round 3 = Fable at max effort (the TASKS.md protocol's final escalation).
  for (let attempt = 0; attempt < 4 && !ok; attempt++) {
    attemptsUsed = attempt + 1;
    if (attempt > 0) {
      phase('Code');
      await agent(
        `You are the CODER fixing ${task.id} (fix round ${attempt}). ${briefing}\n\nThe review and/or gate failed:\n${report}\n\n` +
          `Diagnose the ROOT cause and fix it — never bypass a check (no --no-verify, no narrowing scope, no deleting tests). ${formatStep}Do NOT commit.`,
        {
          phase: 'Code',
          model: attempt >= 3 ? 'fable' : 'opus',
          effort: attempt >= 2 ? 'max' : undefined,
          agentType: 'general-purpose',
        },
      );
    }
    // Review and gate are independent read-only checks over the same tree —
    // run them concurrently; each attempt's wall time is max() not sum().
    phase('Review');
    // A HUMAN GATE has no automatable acceptance Review — its acceptance is the
    // human's, and its criteria ("user explicitly approved") are unsatisfiable in
    // an unattended run. Running that Review would FAIL every attempt and burn the
    // fix ladder trying to "make it pass" — the exact failure that once let a
    // checkpoint get self-approved. So for gate tasks only the TECHNICAL gate must
    // pass; the human is the reviewer.
    const [review, gate] = await parallel([
      () =>
        isGate
          ? Promise.resolve({ pass: true, findings: [] })
          : agent(reviewPrompt, {
              phase: 'Review',
              model: 'sonnet',
              schema: REVIEW,
              agentType: 'general-purpose',
            }),
      () =>
        agent(gatePrompt, {
          phase: 'Gate',
          model: 'sonnet',
          effort: 'low',
          schema: GATE,
          agentType: 'general-purpose',
        }),
    ]);
    // BOTH dying with no result is the usage-limit signature: further fix
    // rounds would die too and burn the ladder. Halt resumably instead.
    if (!review && !gate) {
      log(
        `HALT at ${task.id}: reviewer and gate agents both died with no result (usage-limit signature). ` +
          `${task.id}'s coded work is left in the tree — resume this run once the limit resets.`,
      );
      if (completed.length) await pushBranch();
      return { completed, stoppedAt: task.id, reason: 'agents-died (likely usage limit) — resume this run' };
    }
    // agent() returns null when a subagent dies on a terminal API error (e.g.
    // usage limit) — treat that as a failed check, not a crash, so the
    // escalate-then-halt ladder handles it.
    const reviewPass = Boolean(review && review.pass);
    const gatePass = Boolean(gate && gate.pass);
    ok = reviewPass && gatePass;
    report =
      `REVIEW: ${isGate ? 'skipped (human gate — human is the reviewer)' : reviewPass ? 'pass' : review ? (review.findings || []).join(' | ') : 'reviewer agent died (no result)'}\n` +
      `GATE: ${gatePass ? 'pass' : gate ? gate.output || 'failed' : 'gate agent died (no result)'}`;
    log(`  ${task.id} attempt ${attempt + 1}: review ${isGate ? '—' : reviewPass ? 'ok' : 'x'} · gate ${gatePass ? 'ok' : 'x'}`);
  }

  if (!ok) {
    log(`HALT at ${task.id} after escalation. Repo left at the last green commit; ${task.id} changes are uncommitted for your review.`);
    if (completed.length) await pushBranch();
    return { completed, stoppedAt: task.id, reason: report };
  }

  // ---- HUMAN GATE: prepare-then-BLOCK, then HALT (never DONE, never self-approved) ----
  // The technical gate passed and any artifact the task defines is in the tree.
  // Commit it with status BLOCKED(<reason>) and an HONEST note that claims no
  // human action occurred, then stop the whole run. Only a human flips it to DONE.
  if (isGate) {
    phase('Commit');
    await agent(
      `Commit ${task.id} as a HUMAN GATE stop — the run halts here and this task is NOT complete. ` +
        `In TASKS.md set ${task.id} status to exactly \`BLOCKED(${gateReason})\` — it must NOT be DONE. ` +
        `Add a one-paragraph "**Prepared (<today>):**" note describing ONLY what the automated step actually produced (artifacts, tests, files) and stating plainly that the task now awaits: ${gateReason}. ` +
        `CRITICAL — you did NOT perform, witness, or obtain any human review, approval, sign-off, or visual check. Do NOT write that a user/reviewer looked at, reviewed, or approved anything, and do NOT invent an approving quote — that is a fabrication and is forbidden. Describe only the machine work you can see in the diff. ` +
        `End the note with the exact line \`Orchestration: graphify=${graphifyTag} · attempts=${attemptsUsed}/4 · HUMAN-GATE HALT.\` (verbatim) on its own line. ` +
        `Because this task began from a clean working tree, ALL current changes belong to it — run \`git add -A\` then \`git reset ${TREE_IGNORE.join(' ')}\`. ` +
        `Commit with first line "${task.id}: ${task.title}" and end the message with this trailer on its own line:\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>\nDo NOT push. Do NOT run tests or ANY background command — the gate already verified this tree. Perform the TASKS.md edit and git commands synchronously, confirm the new commit hash with \`git log -1\`, then return.`,
      { phase: 'Commit', model: 'sonnet', agentType: 'general-purpose' },
    );
    const gpost = await treeState();
    if (!gpost.clean || !(gpost.head || '').startsWith(`${task.id}:`)) {
      log(
        `HALT: gate task ${task.id} did not commit cleanly (tree ${gpost.clean ? 'clean' : 'dirty'}, HEAD "${gpost.head || '?'}"). ` +
          `Its prepared work is left for your review.`,
      );
      await pushBranch();
      return { completed, stoppedAt: task.id, reason: 'gate-commit-not-verified' };
    }
    log(
      `HUMAN GATE at ${task.id}: prepared and committed BLOCKED(${gateReason}). ` +
        `Run HALTED — this task is NOT done and was NOT self-approved. Only you can flip it to DONE.`,
    );
    await pushBranch();
    return { completed, stoppedAt: task.id, reason: `human-gate: ${gateReason}` };
  }

  // ---- COMMIT + mark DONE (same commit, per protocol) ----
  phase('Commit');
  await agent(
    `Commit ${task.id}. In TASKS.md set ${task.id} status to DONE and add a one-paragraph "**Delivered (<today>):**" note summarizing what shipped and any deliberate scope boundary, ending with the exact line \`Orchestration: graphify=${graphifyTag} · attempts=${attemptsUsed}/4.\` (verbatim — this is a machine-parsed metric, do not paraphrase it) on its own line. ` +
      `Because this task began from a clean working tree, ALL current changes belong to it — do NOT hand-pick hunks. Stage everything except ignorable infra: run \`git add -A\` then \`git reset ${TREE_IGNORE.join(' ')}\`. ` +
      `Commit with first line "${task.id}: ${task.title}" and end the message with this trailer on its own line:\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>\nDo NOT push. ` +
      `Do NOT run tests and do NOT launch ANY background command — the gate has already verified this tree. Perform the TASKS.md edit and the git commands synchronously, confirm the new commit hash with \`git log -1\`, and only then return.`,
    { phase: 'Commit', model: 'sonnet', agentType: 'general-purpose' },
  );

  // ---- POST-COMMIT VERIFICATION: the commit step is the one place a silent
  // no-op or partial stage would drift the protocol undetected. Assert the
  // commit actually landed — tree clean AND HEAD is this task's commit — before
  // moving on. Otherwise HALT with the work left for review.
  const post = await treeState();
  if (!post.clean || !(post.head || '').startsWith(`${task.id}:`)) {
    log(
      `HALT: after committing ${task.id}, tree is not clean or HEAD ("${post.head || '?'}") does not start with "${task.id}:". ` +
        `The commit did not land as required — ${task.id}'s work is left uncommitted for your review.`,
    );
    if (completed.length) await pushBranch();
    return { completed, stoppedAt: task.id, reason: 'commit-not-verified' };
  }

  completed.push(task.id);
  log(`DONE ${task.id} (${completed.length} this run).`);

  // ---- PUSH + CI EVIDENCE (TASKS.md header rule: the CI run on the branch's
  // most recent pushed commit must be green before the next task starts).
  //
  // args.skipCi opts OUT of the remote CI verification for one run. It does NOT
  // weaken the local gate — every task still runs the TASKS.md gate command and
  // still halts on failure; this only skips pushing and polling `gh run list`.
  // Use it when remote CI cannot produce a verdict (billing/quota block, runners
  // offline) or when per-push CI is deliberately disabled to control cost. The
  // branch is left unpushed here; the end-of-run pushBranch() still runs.
  // NB: read ARGS, not the raw `args` global — args may arrive JSON-encoded.
  if (ARGS.skipCi) {
    log(`CI verification skipped (ARGS.skipCi) after ${task.id}; commit is local, push deferred to end of run.`);
    continue;
  }
  // Pushing per task also bounds how far the branch can drift if the run dies.
  // Push once, then let THIS loop drive the polling in short bounded steps. A
  // single agent won't reliably hold a 40-min sleep/poll loop — it checks once,
  // sees "in_progress", and returns — so the control flow owns the wait instead.
  // Each poll is a fresh, cache-distinct (indexed) agent, so a resumed run
  // re-checks CI live rather than replaying a stale "pending" verdict.
  const push = await agent(
    `Run \`git push\` and report the result. If the push FAILED, return state="push-failed" with the error in output. ` +
      `If the push succeeded, run \`gh workflow list\`. If NO workflows are configured (empty list / no CI), return state="no-ci". ` +
      `Otherwise run \`git rev-parse HEAD\`, then \`gh run list --commit <that sha> --json name,status,conclusion\`: ` +
      `if the list is EMPTY, first check whether any configured workflow can actually trigger for THIS branch — read the \`on:\` triggers in .github/workflows/*.yml and compare against \`git branch --show-current\`; if none apply to a push of this branch (e.g. CI fires only on main / pull_request), return state="no-ci" with a note in output; ` +
      `if a workflow DOES cover this branch but its run has not registered yet, return state="pending" — never treat an empty list as success; ` +
      `if any run is still queued or in_progress return state="pending"; if any run completed with a non-success conclusion return state="failure" with the run names/conclusions in output; if the list is non-empty and every run concluded "success" return state="success". Do not fix anything.`,
    { phase: 'Commit', model: 'sonnet', effort: 'low', schema: CISTATE, agentType: 'general-purpose', label: `push+ci:${task.id}` },
  );
  let ciState = push ? push.state : null;
  let ciOut = push ? push.output || '' : 'push/ci agent died';
  // ~90s sleep per poll * 30 ≈ 45 min ceiling before we call it a timeout.
  for (let i = 0; ciState === 'pending' && i < 30; i++) {
    const poll = await agent(
      `CI poll #${i + 1}. First run \`sleep 90\`. Then run \`git rev-parse HEAD\` and \`gh run list --commit <that sha> --json name,status,conclusion\`: ` +
        `if the list is EMPTY, check whether any workflow in .github/workflows/*.yml can trigger for the current branch (\`git branch --show-current\`) — if none apply return state="no-ci" with a note, otherwise return state="pending" (never success); if any run is still queued or in_progress return state="pending"; if any run completed with a non-success conclusion return state="failure" with details in output; if the list is non-empty and every run concluded "success" return state="success". Do not push, commit, or fix anything.`,
      { phase: 'Commit', model: 'sonnet', effort: 'low', schema: CISTATE, agentType: 'general-purpose', label: `ci-poll#${i + 1}:${task.id}` },
    );
    ciState = poll ? poll.state : 'pending';
    ciOut = poll ? poll.output || ciOut : ciOut;
  }
  if (ciState !== 'success' && ciState !== 'no-ci') {
    const detail =
      ciState === 'pending'
        ? 'timed out waiting for CI (still in_progress after ~45 min of polling)'
        : ciState === 'push-failed'
          ? `push failed: ${ciOut}`
          : ciState === 'failure'
            ? `CI failed: ${ciOut}`
            : `ci-evidence agent died: ${ciOut}`;
    log(
      `HALT after ${task.id}: ${detail}. ${task.id} is committed locally; per the CI-evidence rule the next task must not start until the pushed commit is green.`,
    );
    return { completed, stoppedAt: task.id, reason: `ci-evidence: ${detail}` };
  }
}

if (completed.length) await pushBranch();
return { completed };

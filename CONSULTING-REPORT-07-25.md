# UGT Multi-Domain Consulting Report — 2026-07-25

> Four independent domain reviews commissioned simultaneously: a novice AI-assisted coder, a power user
> of AI orchestration tooling, a working game developer evaluating pre-alpha UAT fit, and a senior
> full-stack developer performing an alpha-readiness audit. Reviews were conducted in parallel with no
> cross-contamination. This document consolidates findings, highlights cross-domain agreement, explores
> disagreements, and triages output by priority.

---

## Executive Summary

UGT is a methodologically serious, well-documented game testing framework whose core design decisions — transport-only adapters, fail-closed ladder gates, deterministic control flow in JavaScript rather than model judgment, and the commit-as-invariant pattern — hold up under scrutiny from all four domains. The Orchestrator is a genuine contribution that power users will recognize as more trustworthy than comparable tools. However, three concrete defects must be resolved before this ships to an alpha audience: game-specific logic hardcoded in the supposedly game-agnostic `verifier.py` (a direct violation of the framework's own M1 rule), `SafeEvaluator`'s silent-zero behavior on missing keys (a structural path to vacuous green), and `playwright`/`stable-baselines3` in unconditional `install_requires` (a multi-hundred-MB first impression before a user has done anything). Beyond those, the highest-value changes are: remove or relocate `TASKS.md` from the repo root (it references gitignored files and will confuse alpha testers), update the CLI labels and `ugt init` template to reflect the current tier model (RL is demoted, LLM playtest is the balance tier), and add a single "what adapter for my game type?" decision page that bridges the Orchestrator-built project into UGT onboarding. The documentation architecture is stronger than most projects of this scope, with one conspicuous gap: there is no arrival document for a user who has just finished an Orchestrator build cycle and wants to start testing.

---

## Section 1 — Novice AI-Assisted Coder Review

*Persona: non-engineer, enthusiastic about Claude-assisted coding, wants to use the Orchestrator to build a project and then test it with UGT.*

### 1.1 First Impression (README)

The value proposition — three tiers, "real game not a re-implementation," pip install — lands within the first paragraph. The ASCII architecture diagram in the README is a genuine orientation tool. The stumbling block: the word "adapter" appears before it is defined, and for a non-engineer it carries no inherent meaning. A single parenthetical on first use ("a thin translation layer between UGT and your game") would prevent the reader from spending their first five minutes trying to understand what is being adapted from what.

### 1.2 Orchestrator Onboarding

The best-written document in the bundle. The "Why this exists" section in `Orchestrator/README.md` does something rare: it names the *problem* precisely ("the model is also being trusted to run the control flow") before introducing the solution. The install is two commands. The two-step flow (`/tasklist` → `/orchestrate`) is legible even to a novice.

The one anxiety point: `/tasklist` asks the user to confirm the "gate" (the commands that must pass for every task), but a user who has just started their project may have no tests yet and no idea what a gate command looks like. The doc would benefit from one sentence acknowledging this: "If you don't have tests yet, your gate can be as simple as `python -m py_compile *.py`; the point is that it must be a real check the runner can evaluate."

### 1.3 The Orchestrator → UGT Transition

The most significant documentation gap for this user. After `/orchestrate all` finishes, there is no document that says "your project is built — here's how you start testing it with UGT." The information exists scattered across `README.md`, `UGT-USER-MANUAL.md`, and `PLAN-FORWARD.md`, but nothing packages it as an arrival experience. A short "You just finished a build cycle — now what?" section at the bottom of `Orchestrator/README.md`, or a new `GETTING-STARTED.md` that links Orchestrator output to UGT onboarding, would close this gap entirely.

### 1.4 LESSONS.md

Section A (the nine core methodology rules) reads like earned wisdom: each rule is stated cleanly, and the evidence behind it is specific ("a TypeScript bridge for a space-trading sim shipped with no combat"). A novice will find this reassuring rather than academic. Section B (the LLM playtest pre-flight) is dense on a first read — eleven checklist items with nested sub-cases — but the right decision was made to put it in a separate section the reader can defer. The most powerful credibility signal in the whole repository is **P10**, which documents getting a lesson wrong (the anti-repetition-rule attempt), correcting it the same day, and keeping both the mistake and the correction in the record. That is not something a system trying to look good would do, and it earns disproportionate trust.

### 1.5 The Worked Example (harness-game)

The `examples/harness-game/` directory is the best orientation tool in the repo, but it is pointed to too late. It appears in the README's "Where to go next" section after three other documents. It should be the *first* recommended read for any new user, since it is dependency-free, runnable in minutes, and shows the complete methodology end-to-end. One sentence missing from the example's README: an explanation of what R3 catches that R1 cannot (specifically, the random-walk nature of the exploit-hunter and why same-seed determinism matters). Without that sentence, a user may treat R3 as a longer R1 rather than a qualitatively different tier.

### 1.6 Gaps

- **Cost visibility**: The LLM playtest costs approximately $0.75 for 100 actions (mentioned once in the USER-MANUAL at section 9b). This number is reassuringly cheap, but it needs to appear earlier — ideally in the README's tier table or the Orchestrator → UGT transition guidance.
- **`TASKS.md` is not a template**: The root `TASKS.md` is a live SpacerQuest integration file. A non-engineer landing on the repo will read it as a model for their own project, not as an internal artifact. It should be removed from the root or clearly marked as an internal example.
- **No adapter decision guide**: A user whose game runs in a browser and another whose game runs as a Python subprocess both have the same first question: "which engine type do I choose?" The README and USER-MANUAL both answer this, but a single one-page decision guide or flowchart ("Is your game a browser game? → `engine.type: browser`. Headless subprocess? → `engine.type: simulation`. Live server? → `engine.type: real_server`") would eliminate the need to read 90 pages to answer a five-second question.

### 1.7 What Delights

- **M2 (dual validation)**: Framing "finding a real game bug" as a successful test outcome is counterintuitive and correct. It reframes the whole activity.
- **The Orchestrator failure policy**: Escalate → halt (never `--no-verify`, never deletes tests) is the thing a non-engineer most needs to know before trusting an AI to build their project. The explanation is unusually honest about what the system will and won't do.
- **P10's self-correction**: Keeping a corrected mistake in the lessons registry is the kind of intellectual honesty that makes this feel like a system designed by someone who has actually run it.

---

## Section 2 — Power User AI Orchestration Review

*Persona: daily user of Hermes, OpenClaw, and similar multi-agent orchestration tooling. Peer review, looking under the hood.*

### 2.1 The Determinism Claim

The claim holds where it matters most. The `while` loop in `orchestrate-tasks.js` owns continuation unconditionally: the budget check, the scope boundary assertion (`scopeIds.includes(task.id)`), and the post-commit tree verification (`HEAD.startsWith(task.id + ':')`) are all code. The commit-as-invariant is the real innovation — most orchestrators trust the commit agent to report success; this one uses a `treeState` probe to assert the commit actually landed before advancing. That closes the silent no-op failure mode that burns runs in most comparable systems.

The boundary that remains model-dependent: the Select stage's DAG evaluation. The Select agent must read every predecessor task's status, confirm all `after:` IDs are DONE, and nominate an eligible task — but the code never independently verifies this. If Select nominates T-301 while T-201 is IN-PROGRESS, the scope check won't catch it. For five-task lists this is fine; for a 40-task branchy DAG, a model misreading a status field violates the dependency contract silently. A code-level pre-check — read TASKS.md directly, assert all `after:` IDs have `status: DONE` before Code begins — would close this.

### 2.2 Select Stage Design

The structured output schema (`NEXT_TASK` with `id: string | null`) handles the two primary failure modes: early termination (null when tasks remain) and invalid IDs (caught by the scope check). What it doesn't handle: a valid task ID whose dependencies aren't satisfied. The `resuming` boolean in the schema is also model-reported, not code-verified — a model returning `resuming: false` on a genuine IN-PROGRESS task would re-execute a task that was already in flight.

### 2.3 Failure Policy

The documented failure policy (two fix rounds: normal Opus, max Opus) does not match the code. The actual loop is `attempt < 4`, yielding three fix rounds: Opus (normal), Opus (max), Fable (max). The meta.phases array confirms the Fable escalation at round three, but neither the README nor the SKILL.md mentions it.

The real-world TASKS.md demonstrates the divergence: T-401 shows `attempts=2/4` in its machine metric while T-501 shows `attempts=2/4` but its Delivered note says "(fix round 3)" — the model-generated narrative and the code-counted metric contradicted each other in the same committed file. `attemptsUsed` is trustworthy; prose Delivered notes are not.

The Fable escalation at round three is a good call that Hermes and OpenClaw don't make — genuinely trying a different model family at last resort has empirical value over cranking effort on the same model. But users reading the docs will be surprised by what they get.

### 2.4 Human Gates

The anti-self-approval design is the most carefully-thought-out piece in the whole system. Skipping Review entirely for gate tasks (injecting `{ pass: true }` in code rather than running the review agent) prevents the fix ladder from burning fix rounds trying to satisfy "user explicitly approved" — which is unsatisfiable unattended. Most tools leave this open; this one solved it.

One fragility: `headingLine = task.block.split('\n', 1)[0]` assumes the Select agent returns the task block verbatim with the heading line first and no preamble. A leading blank line or a "Here is the task:" prefix breaks the regex and causes a human gate to silently execute as a normal task. Parsing the gate marker from the raw TASKS.md file rather than from the model-returned block would eliminate this dependency.

### 2.5 CI Integration

The `sleep 90` inside the poll agent burns agent startup overhead as the unit of time. The eligibility check — whether any `.github/workflows/*.yml` matches the current branch — is a probabilistic model judgment over structured YAML where a false `no-ci` verdict silently skips the remote gate. The 30-poll ceiling (~45 minutes) is not exposed as a configurable knob. CI suites that run longer will hit the ceiling on every run.

### 2.6 The TASKS.md Format as a DSL

Compared to Temporal workflow DSL or GitHub Actions YAML, the prose-with-inline-metadata format gains: human editability without tooling, co-located documentation, and a living audit log synchronized with git history (Delivered notes appended in the same commit that marks DONE). The SpacerQuest TASKS.md demonstrates this at real scale — the T-301 Delivered note recording the `inv_dice_bounds` correction and the shipyard parity gap is exactly the structured finding that would otherwise be lost in a chat transcript.

What you give up: no static validation at write time (DAG cycles won't surface until a task never becomes eligible), no per-task configuration (timeout, retry policy, model override are run-level only), and no expression of parallel execution in the DSL despite the Workflow engine supporting `parallel()`. Two tasks with no shared state and no `after:` relationship run sequentially by design — a meaningful throughput cost on large lists.

### 2.7 What's Genuinely Novel

The commit-as-invariant pattern deserves to be copied by other orchestrators. The dirty-tree precondition physically prevents two tasks from intermingling uncommitted changes. Budget-aware stopping at a task boundary is cleaner than mid-task abort. The human gate anti-self-approval logic is a solved problem here that most tools leave open.

### 2.8 What's Missing

- Static DAG validation in `/tasklist` (cycle detection, unreachable-task detection before runtime)
- Code-level verification that selected task's `after:` prerequisites are actually DONE
- Per-task timeouts (a coder on a hard task has no ceiling)
- A rollback or stash path when halt leaves uncommitted changes — currently the user manually `git checkout .`
- Fix-round count in docs must match the code (2 documented, 3 actual)

---

## Section 3 — Game Developer UAT Review

*Persona: working indie game developer evaluating UGT as a pre-alpha UAT tool. Zero tolerance for AI slop.*

### 3.1 The Verify Tier

Authoring `feature-map.yaml` assertions is low-friction for behaviors expressable as state deltas — roughly one line per claim, and failed assertions show `before`/`after` state, which makes debugging fast.

Two concrete defects undercut the tier:

**Defect A — game-specific logic in `verifier.py`**: Lines 73–76 contain a fuel check hardcoded in the "game-agnostic" core verifier:

```python
_fuel = (current_state.get("ship") or {}).get("fuel", 999)
idle_action = 4 if _fuel < 100 else 0
```

This executes when no feature precondition is met. For any game where action 4 is not an idle action, the verifier will issue it silently, contaminating before/after state snapshots. This directly violates M1 (never reimplement game logic in the framework) and is a real defect that will produce incorrect verify results on non-space-trading games.

**Defect B — `SafeEvaluator` silent zero on missing keys**: `formula_evaluator.py` line 92 silently returns `0` for any state path that doesn't exist. If your bridge never emits `inventory` but your assertion references `state.player.inventory.count`, the evaluator reads it as `0` and the assertion `state.player.inventory.count > 0` fails vacuously — or, worse, `state.player.inventory.count == 0` passes vacuously. No warning is emitted. This is a structural path to the exact failure mode LESSONS.md names O2 (no vacuous passes) — discovered three separate times in real runs — and it is unguarded in the core evaluator.

`NOT_REACHED` results are also ambiguous between "precondition expression is wrong" and "game cannot reach this state in the turn budget," with no distinction in the report.

### 3.2 The Exploit-Hunter

The hunter is useful proportionally to the quality of invariants you write — and the framework ships with zero built-in ones. Every predicate is yours. If you write predicates covering numeric floors, monotonicity, terminal-state stability, and same-seed determinism, the hunter will find edge cases your hand-testing missed and will catch post-terminal mutations. The deduplication logic (findings keyed by `(kind, name, action_name, message[:80])`) prevents a single broken invariant from flooding the report. The same-seed determinism check in R3 is something no QA intern would run, and it catches a class of bugs that only surfaces at scale.

What it does not do: discover new bug classes you did not anticipate. A QA intern playing 100 random sessions will notice visual corruption, floating enemies, audio dropouts. The hunter checks exactly what you told it to check, at the granularity of your state dict, at the speed of a subprocess call.

### 3.3 The LLM Playtest Tier

Section B of LESSONS.md (P1–P11) documents what happens without the preflight: two multi-hour balance batches on a card game reported 92.6% and 89.8% while the LLM played blind — one because the guide was truncated past the core mechanics, one because the state normalizer silently discarded half the game's fields including `echo`, which is "half the game's ratified core mechanic." Zero violations, zero bugs, a confident win rate — and permanently unpoolable data.

Once the preflight passes, the output is genuinely useful. The contradiction detector (auto-flagging when an action produces no material state change N consecutive times while the LLM expected one) catches silent game refusals without requiring the LLM to notice. The `action_log` with `reasoning` and `expected_outcome` per step is a legible record of how a competent player read your game. Bug reports include a 10-step reproduction sequence, full before/after state, and terminal text — enough to reproduce most findings manually.

One post-incident design note: the `diagnose` action originally reset the entire episode, destroying campaign progress on persistent-campaign games. The `diagnose_resets_episode: false` knob exists because a run erased 310 turns of valid play. Check that knob before the first run on any game with persistent state.

### 3.4 Setup Cost and Pre-Alpha Maintenance

A subprocess bridge for a headless game is 4–8 hours of work if your game has a clean reset and a deterministic step function. The `ugt.config.yaml` is 30–60 minutes for a simple game. The `feature-map.yaml` is fast to write once you know your state surface.

For a rapidly-changing pre-alpha game, maintenance is real: every state field rename breaks assertions. The strategy guide needs re-verification against the running game after each feature change (P6 explicitly warns that guide claims written from source code were falsified by live probes). Budget 1–2 hours per significant iteration just to keep the harness accurate.

### 3.5 What UGT Explicitly Does Not Cover

Visual fidelity, animation feel, audio, onboarding clarity. `PLAN-FORWARD.md` names human/frontend UAT as a fourth tier that "caught things no engine-level tier can see by construction." This is not a gap the framework pretends to fill.

### 3.6 Pre-Alpha UAT Verdict

This shifts effort earlier and changes its shape. Initial setup costs more than running a manual smoke test. A green ladder means your pre-UAT session with real testers is spent on behavior automation cannot see — visuals, feel, onboarding — rather than hunting crashes and broken state transitions. For a mechanically complex game, that is a real benefit. For a simple game, the setup cost may not pay off until R2 or later.

---

## Section 4 — Senior Full-Stack Developer Alpha-Readiness Review

*Persona: technical supervisor auditing readiness for a closed alpha group of small independent developers.*

### 4.1 Tech Stack Fitness

Python + Gymnasium + Playwright is the right conceptual framework. The problem is packaging: `playwright` and `stable-baselines3` sit in unconditional `install_requires`, which means `pip install -e .` on a fresh machine triggers a PyTorch pull plus browser binary acquisition. For a small indie dev on a Windows gaming rig with a slow connection, this is the first impression. Playwright also requires `playwright install chromium` after the pip step — a step not mentioned anywhere in `README.md`'s Install section. This will silently fail the first time anyone attempts `engine.type: browser`.

**Fix:** Move `playwright` to a `[browser]` optional extra. Move `stable-baselines3` to a `[rl]` or `[train]` optional extra. The base `pip install -e .` should pull only `numpy`, `gymnasium`, and `pyyaml`. Add `playwright install chromium` explicitly under the `[browser]` install block in the README.

### 4.2 Folder Structure

`ugt/core/`, `ugt/adapters/`, `ugt/utils/` is clean and correctly layered — adapters are transport-only by design (the `NotImplementedError` convention in `BaseAdapter` is good discipline), core holds tier logic, utils holds parsing. Nothing is in the wrong layer.

`Orchestrator/` at root is defensible given the README positions it as a bonus feature, but the main `README.md` does not mention it at all. A first-time visitor to the repo will find an unexplained `Orchestrator/` directory alongside a game testing framework. One sentence in the main README ("the `Orchestrator/` folder is a bonus Claude Code build-loop tool, not part of UGT") resolves this.

### 4.3 setup.py

Not a blocker. The Python 3.14 classifier is aspirational rather than tested — drop it or validate it. "Development Status :: 4 - Beta" misrepresents a closed alpha; "3 - Alpha" is the honest choice.

### 4.4 Documentation Architecture

This is one of the stronger aspects of the project. The pointer graph is explicit: README states its purpose, links each of the other four docs, and tells users when to read each. LESSONS.md is identified as canonical and wins any disagreement. For a small team, this is coherent architecture.

The one gap: `PLAYTEST-DESIGN.md` is linked as "design spec" but reads as an implementation journal that is sometimes ahead of the code and sometimes behind. Its header should clarify in one sentence whether it describes current behavior or intended future behavior.

### 4.5 The `integrations/` Gitignore Decision

Smart. The framework being game-agnostic is the point, and per-game scripts in the shared repo would erode that positioning. `examples/` (especially `harness-game`, dependency-free, full ladder) adequately substitutes.

### 4.6 Legacy RL Path — The Real Tech Debt Signal

The demoted RL path is not the problem. The problem is that `ugt init` writes a template whose inline comments call RL "Phase 2" and LLM playtest "Phase 3." The CLI `add_parser` labels read `[Phase 2] Train a reinforcement learning policy agent`. This directly contradicts the USER-MANUAL, which states the LLM playtester is now the balance tier. A user who runs `ugt init` and reads the scaffolded config will build their integration in the wrong order.

Fix: update the `ugt init` template comments and CLI `[Phase N]` labels to reflect the current model. This is a 30-minute edit.

### 4.7 TASKS.md at Root

Must be removed or relocated before alpha. It is a live SpacerQuest integration file referencing `integrations/spacerquest/` — a gitignored directory. An alpha tester who clones the repo and sees this will assume it is framework documentation, find references to files that don't exist, and be confused about what to do. Either move it to disk-only (`integrations/spacerquest/TASKS.md`, gitignored per the existing convention) or gitignore `TASKS.md` at the framework level and document in the Orchestrator README that TASKS.md is a per-project working file.

### 4.8 No-Test-Suite Policy

Valid for this context. The `examples/harness-game/` ladder scripts exercise the real integration points — adapter I/O, GateRunner accumulator, InvariantSuite reuse across rounds, `first_divergence` replay — in a way that a pytest fixture suite would not. Correct call.

### 4.9 Deployment Readiness

After the install_requires and Playwright step fixes, `pip install -e .` plus `ugt --help` is adequate. The `harness-game` dependency-free example should be more prominently called out in the README as the recommended first step.

One gap: there is no way to verify the LLM playtest is wired before spending API credits. A `ugt smoke-test --provider anthropic` that confirms the API key and model reachability would be valuable. Not a blocker.

### 4.10 Summary: Ready vs. Not Ready

**Ready to ship:** verify tier, smoke-test, exploit-hunter, `trial.py` scaffold, all three adapters, LLM playtester core (repeat-block guard, contradiction detector, terminal recall, RevealTracker, multi-run aggregation are production-quality), examples, Orchestrator.

**Not ready without fixes:** unconditional `playwright`/`stable-baselines3` in install_requires; missing `playwright install` step in README; TASKS.md at root; RL-as-Phase-2 framing in `ugt init` and CLI labels.

---

## Cross-Domain Synthesis

### Repeat Findings (appear in two or more domains)

**[Repeat ×4] `TASKS.md` should not be at the repo root**
All four reviews flagged this independently. The senior dev calls it a deployment blocker (references gitignored files). The novice calls it a template confusion risk. The power user notes its Delivered notes expose the model/code divergence in attemptsUsed. The game dev doesn't reference it directly but would be equally confused. This is the single most consistently flagged item across all domains.

**[Repeat ×3] Setup/install friction**
The senior dev (unconditional install_requires + missing Playwright step), the novice (no cost visibility, no decision guide for adapter type), and the game dev (4–8 hours setup cost disclosure, no playtest dry-run before API spend) all independently arrive at the same theme: the friction between "cloning the repo" and "running the first meaningful test" is under-documented and over-heavy.

**[Repeat ×3] The Orchestrator → UGT transition gap**
The novice names it directly (no arrival document). The game dev reaches the same conclusion via the setup cost framing (what do you do after `/orchestrate all` finishes?). The senior dev notes the Orchestrator isn't mentioned in the main README at all, so the connection is invisible in the opposite direction as well. Three domains independently found that the two components — Orchestrator and UGT — are not stitched together for a user who wants to use both.

**[Repeat ×2] The RL "Phase 2" framing needs updating**
The senior dev and the game dev both note that `ugt init` and CLI labels still call RL "Phase 2" while the documentation has clearly demoted it. The senior dev prescribes a 30-minute fix. The game dev calls it a trust issue ("a user following the docs in order will do the wrong thing").

**[Repeat ×2] `SafeEvaluator` silent-zero is a hollow-green risk**
The game dev identifies this as the main unguarded path to vacuous pass. The senior dev confirms O2 (no vacuous passes) is a genuine design commitment but that this structural gap undercuts it. Both flag it as something that must be fixed before alpha because it affects every game onboarding.

**[Repeat ×2] Docs vs. code divergence in the Orchestrator**
The power user (documented 2 fix rounds vs. 3 actual, prose Delivered notes drift from machine metrics) and the senior dev (CLI labels contradict the USER-MANUAL) both find the same failure pattern: the prose layer of the system drifts from what the code does. The power user's observation is the more precise one: `attemptsUsed` is reliable; model-generated narrative is not.

**[Repeat ×2] The hardcoded game logic in `verifier.py`**
The game dev identifies lines 73–76 as a direct M1 violation. The senior dev notes it as "the kind of defect that produces incorrect results on non-space-trading games." Two domains with different angles arriving at the same code defect independently increases confidence this is real.

---

## Areas of Disagreement

**The exploit-hunter's value ceiling**

The game dev is skeptical: "not better than an attentive QA intern" — the hunter only checks what you told it to check and discovers nothing new. The power user and senior dev are more favorable, noting the same-seed determinism check and the deduplication logic as genuinely useful. The resolution is that both are correct at different levels: the hunter's value is proportional to the quality of invariants the user writes, and for a first-time user who writes weak invariants, the game dev's skepticism applies. For an experienced user with a strong invariant set, the power user's assessment applies. The doc should acknowledge this dependency explicitly.

**The no-test-suite policy**

The senior dev considers the ladder-scripts-as-tests approach valid for this context. The game dev and power user don't directly address it, but the game dev's frustration with the `SafeEvaluator` silent-zero suggests that some unit coverage on the evaluator internals would have caught that defect earlier. The right call is probably: the ladder scripts are the right integration test strategy; a small set of unit tests on `SafeEvaluator` and `FeatureMap` parsing would complement rather than compete with them.

**PLAYTEST-DESIGN.md's scope**

The senior dev wants a clearer header (spec vs. current behavior). The novice doesn't mention it. The power user implicitly treats the implemented behavior in `playtester.py` as the reference rather than the spec doc. The right outcome is a one-sentence clarification in the PLAYTEST-DESIGN.md header, not a rewrite — the design spec's value is as a design record, not as a current-behavior description.

---

## Triage

### Critical — Blockers Before Alpha

| # | Finding | Domain(s) |
|---|---------|-----------|
| C1 | Game-specific fuel logic in `verifier.py` lines 73–76 (M1 violation; produces incorrect verify results on any non-space-trading game) | Game dev, Senior dev |
| C2 | `SafeEvaluator` silent-zero on missing state keys (structural path to vacuous green; undermines O2) | Game dev, Senior dev |
| C3 | `playwright` and `stable-baselines3` in unconditional `install_requires` (multi-hundred-MB first impression, wrong for this audience) | Senior dev |
| C4 | `playwright install chromium` step missing from README Install section (silent failure on first browser engine attempt) | Senior dev |
| C5 | `TASKS.md` at repo root references gitignored `integrations/spacerquest/`; will actively mislead alpha testers | All domains |

### High Value — Pre-Alpha Quality Improvements

| # | Finding | Domain(s) |
|---|---------|-----------|
| H1 | Update `ugt init` template and CLI `[Phase N]` labels: RL is demoted, LLM playtest is the balance tier | Senior dev, Game dev |
| H2 | Fix documented fix-round count (README says 2, code does 3: Opus normal, Opus max, Fable max); document the Fable escalation explicitly | Power user |
| H3 | Add code-level DAG verification before Code stage: assert all `after:` IDs are DONE, independent of model judgment | Power user |
| H4 | Add an Orchestrator → UGT transition document (or section): "you just finished a build cycle — here's how to start testing" | Novice, Game dev |
| H5 | Move `harness-game` recommendation to the top of README's "Where to go next"; add one sentence about what R3 catches that R1 cannot | Novice, Senior dev |
| H6 | Add a "what adapter for my game?" decision guide (one page or flowchart; browser / simulation / real_server decision tree) | Novice |
| H7 | Clarify `NOT_REACHED` in verify output: distinguish "precondition expression wrong" from "state unreachable in turn budget" | Game dev |

### Secondary — Meaningful But Not Blocking

| # | Finding | Domain(s) |
|---|---------|-----------|
| S1 | Add `PLAYTEST-DESIGN.md` header clarifying whether it is current behavior or aspirational spec | Senior dev |
| S2 | Human gate regex: parse the `[BLOCKED BY]` marker from raw TASKS.md rather than from model-returned task block | Power user |
| S3 | Static DAG validation in `/tasklist`: cycle detection and unreachable-task detection before runtime | Power user |
| S4 | CI poll: expose 30-poll ceiling as a configurable knob; fix eligibility check from probabilistic model judgment to code-level YAML parse | Power user |
| S5 | Add one sentence to Orchestrator README acknowledging users with no tests yet ("your gate can be as simple as `python -m py_compile *.py`") | Novice |
| S6 | `setup.py`: drop Python 3.14 classifier (untested); change "Beta" status to "Alpha" | Senior dev |
| S7 | Add one-sentence mention of `Orchestrator/` in main README ("bonus Claude Code build-loop tool, not part of UGT") | Senior dev, Novice |
| S8 | Expose per-task timeouts (no ceiling on a coder agent for a hard task) | Power user |
| S9 | Document that LLM playtest costs ~$0.75/100 actions in README tier table, not only in the USER-MANUAL | Novice |
| S10 | `diagnose_resets_episode: false` should be called out in onboarding for any game with persistent state | Game dev |

### Nice to Have — Post-Alpha Improvements

| # | Finding | Domain(s) |
|---|---------|-----------|
| N1 | `ugt smoke-test --provider anthropic` to verify API key and model reachability before spending credits | Senior dev, Game dev |
| N2 | Parallel task execution in TASKS.md DSL (two independent tasks currently run sequentially despite Workflow engine supporting `parallel()`) | Power user |
| N3 | Rollback/stash path when halt leaves uncommitted changes (currently: manual `git checkout .`) | Power user |
| N4 | HTML coverage report (`coverage-report.html`) generated from the JSON (already in framework backlog per PLAN-FORWARD.md) | Senior dev |
| N5 | `ugt init --with-feature-map` to scaffold starter `feature-map.yaml` alongside config (already in framework backlog) | Novice, Game dev |
| N6 | "What R3 catches that R1 cannot" explanation in `harness-game/README.md` | Novice |
| N7 | Verify test suite for `SafeEvaluator` and `FeatureMap` (unit-level complement to ladder integration tests) | Game dev |

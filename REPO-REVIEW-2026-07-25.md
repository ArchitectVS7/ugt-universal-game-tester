# Repository Review — 2026-07-25

Pre-alpha sanity check and follow-on work, conducted in a single Claude Code
session against `claude/repo-sanity-check-alpha-rmpucf`. Written for local
review after pull.

**Scope as requested:** *"Any loose ends, unverified claims, shaky ideas,
inefficient code… the system is not meant for public use but I am ready to
share with a small group of developers for alpha testing."*

**Disposition:** this is a working note, not shared doc surface. Delete it once
you've read it (there's precedent — `CONSULTING-REPORT-07-25.md` was removed
the same way in `57201bf`).

---

## Executive summary

Two genuine bugs were found, both of which would have blocked alpha testers on
their first command. Neither was in the original sanity-check scope — they
surfaced while verifying other work.

| # | Bug | Impact before fix | Status |
|---|---|---|---|
| 1 | `cli.py` imported `stable_baselines3` unconditionally at module load | **The entire `ugt` CLI failed to import** on the documented base install (`pip install -e .`). Not just `train`/`evaluate` — `init`, `verify`, `smoke-test`, `playtest`, everything. | Fixed (`d76057b`) |
| 2 | No `pyproject.toml` | `pip install -e .` crashed with `AttributeError: install_layout` against Debian/Ubuntu system pip. The documented quickstart was unrunnable without a venv. | Fixed (`2ac8f98`) |

Everything else found was documentation drift, stale claims, or scope
questions — real but not blocking.

**Current state:** CLI verified working end-to-end from a clean install. The
three-tier model (verify / exploit-hunter / playtest) is intact and unaffected
by the RL removal. Three new planned examples added as PRD + TASKS.md only.

---

## 1. The two real bugs (detail)

### 1.1 — CLI totally broken on a base install

`ugt/cli.py` had `from ugt.core.trainer import train_agent` at module scope.
`trainer.py` had `from stable_baselines3 import PPO, DQN, A2C` at module scope.
`stable_baselines3` was only ever in the optional `[rl]` extra.

Net effect: anyone following `README.md`'s own install line and then running
*any* `ugt` command got a `ModuleNotFoundError` traceback. Verified failing
before the change, verified fixed after.

This is the single most important thing found in this session. It had nothing
to do with whether RL "worked" — it was pure import hygiene, and it made the
documented onboarding path dead on arrival.

### 1.2 — `pip install -e .` broken on Debian/Ubuntu

With a `setup.py` and no `pyproject.toml`, pip's choice of install codepath is
context-dependent:

- **In a venv** → modern PEP 660 `build_editable` path → works.
- **Against Ubuntu's system pip** → falls back to legacy `setup.py develop` →
  `easy_install` → collides with a Debian-only distutils patch (the extra
  `--install-layout` option) that isn't populated on that legacy path →
  `AttributeError: install_layout`, before any project code runs.

Fixed with a three-line `pyproject.toml` declaring `[build-system]`, which pins
pip to the modern path in both contexts. Verified: the exact command that
crashed now succeeds, installs a real `ugt` console script on `PATH`, and runs
`ugt smoke-test` from an arbitrary directory with no `PYTHONPATH` workaround.

**Note for alpha:** this is why the earlier part of the session could only
verify the zero-install `examples/harness-game/` path end-to-end. Now the
whole quickstart is verifiable.

---

## 2. Original sanity-check findings

| # | Finding | Disposition |
|---|---|---|
| 1 | Cost claim `$0.75 per 100 actions` was unattributed and wrong for the model implied | **Fixed.** Both figures now shown with model name and "as of July 2026": `$0.75` (claude-haiku-4-5, $1/$5 per MTok) and `$3–4` (claude-opus-4-8, $5/$25 per MTok). Original figure was correct — for Haiku, which is what long runs actually used. Restored rather than discarded. |
| 2 | ~19 internal game codenames in `playtester.py` comments ("the hacking RPG", plus `L-002`/`L-009`/`RESULTS.md L-017` tracking refs and a `the_breadcrumb` log filename) | **Fixed.** Genericized to "a terminal RPG" etc.; internal tracking codes removed. These referenced private integrations alpha testers have no context for. |
| 3 | `examples/harness-game/ugt.config.yaml` fails `UgtConfig` validation | **Not a bug — no action.** Intentional (engine-first, no `engine.type`). Already has a clear 10-line explanatory comment. Worth mentioning in your alpha brief. |
| 4 | No unit tests anywhere | **Open — see §5.** Framework is covered by the harness-game ladder (integration-level), but `SafeEvaluator`, `UgtConfig`, `FeatureMap` have zero unit coverage. |
| 5 | `realclient.py` was entirely game-specific | **Fixed** (`cb31712`). Was a complete implementation for one private BBS space-trading game (rank ladder, cargo contracts, shipyard upgrades, `/api/character` shape) sitting in framework code and hard-imported by `env.py`. Stripped to a generic transport skeleton; `_read_state()` now raises `NotImplementedError` with guidance, `ACTION_HANDLERS` starts empty. Also made its import lazy so `requests`/`python-socketio` aren't needed unless you use `real_server`. |

**Verified clean, no action needed:** `SafeEvaluator` blocks all injection
(import/eval/exec/`__class__`/arbitrary calls — checked by AST inspection);
`.gitignore` correctly excludes `.env`, `models/`, `logs/`, `results/`,
`integrations/`, `Dev/`, `CLAUDE.md`, `TASKS.md`; `mock-game` and
`browser-game` configs validate; all five harness-game ladder rungs pass
(spike 13/13, smoke 10/10, R1 5/5, R2 4/4, R3 5/5); `LESSONS.md`,
`PLAN-FORWARD.md`, `PLAYTEST-DESIGN.md` contain no internal project names.

---

## 3. RL removal (`d76057b`)

Removed on your call that it never fully worked. This was already demoted in
favor of the LLM playtester; this removes it rather than leaving dead code.

**Deleted:** `ugt/core/trainer.py`, `ugt/core/evaluator.py`;
`train`/`evaluate`/`dashboard` subcommands; `[rl]` and `[dashboard]` extras;
the *required* `reward_profiles` config section (previously forced on every
game, including ones that never trained); `training.*` validation.

**Kept, adjusted:** `UniversalGameEnv` — still used by `ugt smoke-test`, now a
thin state/action wrapper that always returns reward `0.0`.

**Confirmed unaffected:** `verify`, exploit-hunter, and `playtest` all drive an
adapter directly and never touched `UniversalGameEnv` or `reward_profiles`. The
three-tier model is fully intact.

**Docs:** `UGT-USER-MANUAL.md` went 1118 → 843 lines (removed the ~180-line
Phase 2 section, the reward-profile authoring subsection, RL callouts, config
blocks, four RL-only troubleshooting entries; renumbered §8–12 → §8–11 and
fixed a stale `see §9` cross-ref). README, `examples/mock-game/README.md`, and
all three example configs cleaned. Final grep sweep: zero remaining traces.

**Deliberately left alone:** `LESSONS.md`'s M5 rule (*"Verify ≠ Train ≠
Play"*). It's general methodology — a verifier passing doesn't prove real play
works — not documentation of the removed CLI feature. The manual explicitly
defers to LESSONS.md as canonical for that wording.

---

## 4. New planned examples (`551df34`, `c4911d7`, `1bdf205`)

Three examples added under `examples/`, each pairing a `game/` folder (built by
`/orchestrate` from a `TASKS.md`) with an `integration/` folder (the UGT side).
**PRD + TASKS.md only — no code written yet.** Each is independently buildable
with `/orchestrate all`.

Deliberately three different adapter types, one per example:

| Example | Stack | Adapter | Why |
|---|---|---|---|
| `dice` | React | `browser` (Playwright) | D6 dice-pool war-game duel; 7 allocation presets, deterministic bonus dice, seeded RNG for replay |
| `escape-room` | Node.js | `simulation` (subprocess) | 10 rooms, all content in `rooms.csv`/`objects.csv`; one `executeCommand()` serves both a human CLI and the machine bridge |
| `sokoban` | Godot | hand-written TCP adapter | Follows `harness-game`'s engine-first precedent — Godot's frame loop doesn't suit blocking stdio, and no built-in `engine.type` fits |

**Review process:** each example was reviewed by an independent sub-agent, fixed,
then re-reviewed by *fresh* sub-agents with no memory of the first round. Both
rounds returned "adequate with minor fixes" across all three, with round-2
issues materially narrower than round-1 — real convergence, not just agreement.

Issues found and fixed across the two rounds: gate-sequencing bugs (tasks gated
on a `feature-map.yaml` that didn't exist yet — in *both* `dice` and
`escape-room`), a `bonus_dice` range that couldn't represent stacked bonuses, an
ambiguous Reinforcements rule, two unautomatable "manual playthrough" Accept
criteria, an unaddressed GUT/import-cache gap, an understated TCP-framing task
(`StreamPeerTCP` has no `readline()`), an unspecified fixture schema, and a
self-contradicting Standing constraint.

**`.gitignore` note:** the blanket `TASKS.md` rule would have silently dropped
all six new example task lists. Added a scoped `!examples/**/TASKS.md`
exception and verified with `git add --dry-run`. Easy to reintroduce if someone
later "cleans up" the gitignore — worth knowing.

---

## 5. Open items for alpha

Ranked by what I'd actually brief testers on.

1. **No unit tests.** Coverage is integration-level (the harness-game ladder)
   only. `SafeEvaluator`, `UgtConfig`, `FeatureMap` have none. Not a blocker —
   but say so upfront so testers don't assume a safety net that isn't there.
2. **`ugt verify` doesn't support `real_server`.** Raises `ValueError`. Already
   documented in `PLAN-FORWARD.md`'s backlog; re-flagging because a tester with
   a live server will hit it immediately.
3. **`realclient.py` is now a skeleton, not a working adapter.** Anyone using
   `engine.type: real_server` must implement `_read_state()` and populate
   `ACTION_HANDLERS` themselves. This is correct (it can't ship game-specific
   logic) but it's a real onboarding cost — flag it rather than letting someone
   discover it mid-integration.
4. **`harness-game`'s config intentionally fails validation.** Documented in
   the file, but easy to trip over. One line in the brief covers it.
5. **The three new examples are unbuilt.** They're plans, not runnable code.
   If a tester expects working examples, `harness-game` / `mock-game` /
   `browser-game` are the runnable ones.
6. **Sokoban is the riskiest of the three.** Hard dependency on a local
   `godot4` binary with no zero-dep fallback — flagged as a Standing constraint
   in both its TASKS.md files and its README after review.

---

## 6. What was actually verified vs. assumed

Being explicit, since "verified" is doing real work in this report.

**Directly executed and confirmed:**
- `ugt` CLI imports and runs (failing before `d76057b`, passing after)
- `pip install -e .` against system pip (failing before `2ac8f98`, passing after)
- `ugt init` → template validates
- `ugt smoke-test` end-to-end against `mock-game`
- `ugt verify` against `mock-game` → 5/6 PASSED, 1 NOT_REACHED (expected — the
  win-condition precondition isn't reached in the default drive)
- `mock-game` and `browser-game` configs validate; `harness-game` fails as designed
- `ugt` console script resolves on `PATH` and runs from an arbitrary directory
- Grep sweeps for RL traces and internal codenames → zero remaining
- **Full harness-game ladder, re-run after the RL removal** — all five rungs
  green: spike 13/13, smoke 10/10, R1 5/5, R2 4/4, R3 5/5 (including the
  exploit-hunter's random-pressure pass and the byte-identical same-seed replay)

**Read and reasoned about, not executed:**
- `ugt playtest` was never executed (needs an API key and spend). Its code path
  was read; it has no RL coupling.
- The three new examples are plans — nothing to execute yet.

---

## 7. Commit index

All on `claude/repo-sanity-check-alpha-rmpucf`. `1a1c7f1` and earlier are
already on `main`.

| Commit | What |
|---|---|
| `d151b4c` | Cost estimate fix; strip internal codenames from `playtester.py` |
| `cb31712` | Restore Haiku cost figure alongside Opus; gut game-specific `realclient.py`; lazy-import it in `env.py` |
| `551df34` | Add three planned examples (PRD + TASKS.md); `.gitignore` exception |
| `c4911d7` | Round-1 review fixes across all three examples |
| `1bdf205` | Round-2 fixes after independent re-review |
| `1a1c7f1` | README: "running it conversationally" section with sample prompts |
| `d76057b` | **Remove the legacy RL path entirely** (also fixes the CLI import bug) |
| `2ac8f98` | **Add `pyproject.toml`** (fixes `pip install -e .` on Debian/Ubuntu) |

---

## 8. Suggested next steps

1. Decide on the alpha brief — items 1–4 in §5 are the ones testers will hit first.
2. Decide whether the three planned examples get built before or after alpha.
   They demonstrate the Orchestrator→UGT pipeline, which is a strong onboarding
   story, but they're currently promises.
3. Consider unit tests for `SafeEvaluator` / `UgtConfig` / `FeatureMap` — the
   ladder covers integration, but those three are pure functions with clear
   contracts and would be cheap to cover.
4. Delete this file once read.

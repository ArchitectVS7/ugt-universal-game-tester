# Tarot-war × UGT — results log

Commit-traceable record of every ladder round run against the **real** tarot-war React
game over the browser adapter. A round is only "green" if it was **run live** against the
Vite dev server and printed its own `ROUND n MET — n/n` footer; nothing here is inferred.
This file is the source of truth; the narrative history lives in [README.md](README.md).

Game: `/Users/vs7/Dev/Games/tarot-war`, branch `main` (`61f1c1a` at this audit).
Driver: `ugt/adapters/playwright.py::PlaywrightAdapter` (+ `SeededTarotAdapter` in
`verify_round3.py`) → the game's `src/ugt-hooks.ts`
(`window.__GET_STATE__` / `__SEND_ACTION__` / `__RESET_GAME__(seed)`). The hooks are
transport only — they call the exact `useGameState` callbacks the UI buttons receive.

## Rounds

| Round | Date | Script | Result (live) | Findings | UGT commit | Game commit |
|---|---|---|---|---|---|---|
| R1 | 2026-07-07 | `verify_round1.py` | **22/22** (twice back-to-back) — one full playable loop: seeded reset, info access, setup pickers through real handlers, player turn + Oracle in-turn, UI auto-advance, 2nd cycle, same-seed determinism (fingerprint + 3-round replay), full classic game terminates (161 rounds, 3 wars, 2 Towers) with all 44 cards conserved | TW-R1 (live) | (pre-RESULTS) | (pre-RESULTS) |
| R2 | 2026-07-07 | `verify_round2.py` | **12/12** — all three modes to completion under per-dispatch invariants, effect coverage with exact accounting, log round-stamping, hard-AI same-seed determinism, reset preserving mode/difficulty | TW-R6, TW-R8 (live) | (pre-RESULTS) | (pre-RESULTS) |
| R3 | 2026-07-07 | `verify_round3.py` | **7/7 — LADDER COMPLETE.** `ExploitHunter`: 3 seeded episodes (classic 400 steps / endless / survival), phase-aware policy picking mode+difficulty through real pickers + probing refusal paths (mid-game pickers, unmapped id 99), 12 invariants over 418 steps, zero findings, same-seed episode-0 replay byte-identical | — | (pre-RESULTS) | (pre-RESULTS) |
| L-001 audit | 2026-07-21 | (all three) | vacuous-check audit — see below | 1 tester defect (empty-traj determinism guard), fixed | `a69d805`+ | `61f1c1a` |
| L-005 | 2026-07-21 | `ugt playtest` (ollama) | **30/30 actions** — LLM (gemma4:26b) drove 30 real `play_round` dispatches through `__SEND_ACTION__` into the game's own handlers; game progressed to round 30 (p1 22 / Oracle 46, warPile conserved to 0); 0 bugs, 0 invariant violations; `playtest-report.json` produced. R1 re-run after = 22/22 (unaffected). | none (balance-tier wired + smoke-run) | (this branch) | `61f1c1a` |

## Findings registry (migrated from README — R1: 22/22 · R2: 12/12 · R3: 7/7, all 8 findings closed 2026-07-07)

- **TW-R1 (critical) — FIXED & VERIFIED LIVE.** Every war round duplicated the two tied
  cards and inflated the winner's score by +2: war-resolution reset `warDepth` to 0 before
  the claim-phase skip-check, so the claim re-awarded the already-claimed cards. First live
  observation: seed 20260707, round 4 (`empress ×4`). Pinned by
  `warConservation.test.ts`; verified live over a full 161-round game.
- **TW-R2 (major) — FIXED.** Endless skipped the total-exhaustion check → a 0-deck/0-discard
  player made the reducer draw `undefined` and push it into the winner's discard (silent
  corruption). Total-exhaustion check now runs in every mode; exhaustion game-over now logs.
  Pinned in `warConservation.test.ts`.
- **TW-R3 (tooling/game fix) — DONE.** No seed seam existed (unseeded `Math.random()` in
  `shuffleArray`, war tie-breakers, card-effect discard picks, Oracle flavor). Added
  `seededRandom.ts` (mulberry32) and routed all nine call sites; `__RESET_GAME__(seed)`
  seeds it. Pinned by `seededRandom.test.ts`; verified live.
- **TW-R4 (minor) — CLOSED: root-caused to TW-R2.** A one-off `gameModes.tsx` flake, chain
  demonstrated link-by-link (undefined draw → recycled into AI look-ahead →
  `card.power` TypeError). Severed at link 1 by TW-R2; 0 failures across 85 soak runs.
- **TW-R5 (minor) — FIXED.** `ActiveEffect` ids used `Date.now()` (collisions + non-determinism);
  now `<source>-<playerId>-r<round>`. No consumer reads them; determinism hygiene. Pinned by
  `effectDeterminism.test.ts`.
- **TW-R6 (major, found in R2) — FIXED & VERIFIED LIVE.** Every REVEAL/PRE_COMBAT/EFFECT log
  entry was stamped with the PREVIOUS round (reducer incremented `currentRound` after effects
  ran) → GameBoard's "Magical Effects" panel showed nothing from round 2 on. 86 mis-stamped
  entries seen live. Round number now stamped at the top of resolution. Pinned by
  `logRoundStamps.test.ts`.
- **TW-R7 (bug, was a design question) — FIXED & VERIFIED LIVE.** The World's instant victory
  triggered on `deck+hand <= 7`, ignoring the discard pile (which recycles). Count now
  includes discard, per the card's own text. Pinned by `effectDeterminism.test.ts`.
- **TW-R8 (major, found in R2) — FIXED & VERIFIED LIVE.** The World set `gamePhase='finished'`
  mid-pipeline but the round kept resolving (opponent effect, claim +2, war). Resolution now
  stops the moment an effect ends the game; interrupted cards return to owners' discards
  (census intact). Pinned in `warConservation.test.ts`.
- **Observation (design):** in classic mode `score` is cumulative cards claimed while the win
  is opponent total-exhaustion, so the winner can finish with the LOWER score (seen 178–179).

Baseline: tarot-war's own suite stays green — 434 pre-integration, **448 after the trial's
pinning tests**. Action ids in `ugt.config.yaml` must stay in lockstep with the dispatch
table in `src/ugt-hooks.ts`.

---

## L-001 audit — vacuous-check sweep (2026-07-21)

**Task:** audit all three tarot-war ladder scripts for the DDD/Pond vacuous-check failure
class, using `ExploitHunter.run()` (`ugt/core/exploit_hunter.py:81-140`) as the
reference-good pattern (real `before`/`after` into every invariant; an invariant exception
becomes a violation, not a silent pass — `exploit_hunter.py:126-134`). Every `ck(...)` in
R1/R2/R3 was walked against that yardstick.

### Instrumentation dispositioned — trajectory + stats fields populated on every branch

The task's *first* named concern: whether `SeededTarotAdapter`'s `reset()`/`step()`
overrides (`verify_round3.py:58-114`) actually populate every field the same-seed comparison
(`trajectories_match`) and the stats-reading `ck(...)` calls (the per-episode
finished/capped loop) consume — on **every** branch, including the game-over step, a
mid-game picker refusal, and the `UNMAPPED_ID` (99) refusal the policy fires on purpose
(`:135`). Read end to end:

- **`reset()` (`:69-91`):** the `self.stats.append({...})` at `:83-90` is unconditional and
  initializes all six keys later code reads (`seed`, `steps`, `max_round`, `finished`,
  `final: None`, `traj: []`). Every episode has a well-formed stats slot before its first
  step.
- **`step()` (`:93-114`):** **no** early return, **no** `if terminated:`/`if not info.ok:`
  guard. After `super().step()` (`:94`), lines `:96-98` update `steps`/`max_round`/`finished`
  unconditionally, `:99-101` set `final`, and the `st["traj"].append((...))` at `:102-113`
  runs on **every** path before the single `return` at `:114`. Consequently:
  - a **finished** step still records its tuple and sets `st["finished"]` at `:98` — the
    exact field the per-episode `ck` reads (`:342`) to count completed games;
  - a **refused** step — the mid-game picker (`:137`) and the unmapped-id probe (`:135`),
    both `info.ok=False` — still appends a tuple, so refusals are recorded identically in the
    primary and replay runs; that is what makes both the unmapped-id-probe coverage check
    (`:356`) and the exact same-seed compare well-defined.

**One nuance pinned:** the tuple and `final` read the projection by subscript
(`state["player1"]["score"]`, `:101`/`:106-108`) rather than `.get`. Safe because the game
returns the **full** board projection even for a refused action (only material state is left
unchanged), and `inv_ready` (`:171-176`) independently asserts `player1`/`player2` present on
every step; were the projection ever to drop them, the subscript would raise and the outer
`try/except` (`:383-386`) converts that to a FAIL — fail-closed, not a silent swallow. **The
exact comparison made** is element-wise tuple equality (the `x != y` divergence scan inside
`trajectories_match`) over the 14-field tuple (`:102-113`) for every recorded step.
**Conclusion: no defect** — the instrumentation records on all branches; recorded here
because the task required a cited disposition of the subclass, not a silent assumption.

### Disposition — one finding, fixed (shared with warzones)

**FOUND (tester defect, fixed here): the R3 same-seed determinism check was vacuous on an
empty trajectory.** Old `verify_round3.py:353-362` used
`same_len and divergence is None`, which is `True` for two **empty** trajectories
(`len([]) == len([])`, `next(zip([], []), None) is None`) — reporting "N steps identical"
while comparing **zero** driven steps (the DDD-R3-stitching / Pond-vacuous-green class).
Masked in this configuration by a non-empty episode 0 and by the sibling
`not replay_report.findings` conjunct, but the trajectory-equality predicate itself was
unguarded and would false-pass on any empty trajectory from a non-crash cause.

**Fix:** extracted the named, importable predicate `trajectories_match(first, second)`,
which FAILS on empty input, and re-used it at `verify_round3.py:373` (keeping
`not replay_report.findings` as a distinct guard). No check added/removed → live MET count
stays **7/7**. The in-repo good exemplar already using this discipline is this same game's
R2: `verify_round2.py:375` (`len(run1) >= 10 and run1 == run2`).

**Regression artifact:** `integrations/tarot-war/determinism_selftest.py` (style of
`integrations/pond/pc6_ordering_selftest.py`). Feeds empty/empty, identical, diverging,
unequal-length, and half-empty pairs through `trajectories_match`, and runs the **exact old
inline predicate** on empty/empty to prove it returned `True` (would have passed wrongly).
Runs clean: `Tarot-war determinism self-test PASSED (6/6 cases)`.

### Per-`ck` disposition (line numbers in the delivered files — `verify_round3.py` post-fix, `verify_round1/2.py` unchanged from `a69d805`)

All checks read the live `__GET_STATE__` projection this run; the gate is fail-closed (an
uncaught exception adds a FAIL: R1 `verify_round1.py:339`, R2 `:385`, R3
`verify_round3.py:386`).

**`verify_round1.py` (22/22) — one full playable loop.**

| Line(s) | Check | Reads / can fail because |
|---|---|---|
| 142 | fresh seeded game | live phase/deck/score/log all-at-once |
| 148 | seed honored | live `s0.seed == seed` — proves the driven seed applied |
| 157 | board fields present | live `missing` list |
| 160 | documented defaults | live `mode==classic & difficulty==medium` |
| 163 | played-cards + log readable | live structural read |
| 169-173 | difficulty picker | live `info.ok` + `aiDifficulty` transitions through the real handler |
| 175-179 | mode picker | live `info.ok` + `gameMode` transitions |
| 185 | play_round starts battle | live phase→resolving, round==1 |
| 189 | both cards drawn | live `lastPlayedCards` non-null + deckCount<22 |
| 193 | Oracle chose in-turn | live `player2.currentCard` + Oracle log line |
| 198 | round 1 resolved | live result log + score/tower/stalemate |
| 206 | auto-advance cycles | live `wait_phase("playing")` result — no tester input |
| 215 | cycle 2 resolves round 2 | live phase + round==2 + result log |
| 222 | cards conserved (2 rounds) | live census, `not dupes` |
| 235 | mid-game picker refused | live `not info.ok` + difficulty unchanged + error present |
| 245 | same seed → same decks | two live seeded resets, fingerprint compare |
| 267 | 3-round replay identical | two live `replay(3)` traces compared |
| 303 | classic game terminates | live `finished` + winner ∈ {p1,p2} after driving to completion |
| 310 | war exercised | live `wars>0` accumulated over the driven game (honest inconclusive-FAIL if 0) |
| 312 | cards conserved (whole game) | live `first_violation is None`, set only from live census |
| 323 / 333 | play_round after game-over is a no-op | live `not info.ok & term & "reset"` — **or honest FAIL** `:333` "game never finished — not exercised" |
| 328 / 334 | reset after game-over | live fresh-setup + fingerprint — **or honest FAIL** `:334` |

**Minor (recorded, deliberately NOT changed — protects R1 non-regression).** `:221`
computes `conserved = not dupes and sum(census.values()) + warCardCount >= 40`, but the
`ck` at `:222-223` asserts only `not dupes` — the `>= 40` total-conservation aspect of
`conserved` is a **dead variable**. This is a *weakening* (the check verifies less), **not a
false pass**: whole-game total conservation is independently gated by G4 `:312` (`first_violation
is None`, which flags any id seen >2) and by R2's `census_total_conserved` tracker
(`verify_round2.py:156-159`, exact `-2 × towers` accounting). Nothing is hidden, so R1 is
left byte-unchanged to preserve its 22/22 count. (If revisited, either assert `conserved`
in the `ck`, or delete the dead sub-expression — a follow-up, out of scope here.)

**`verify_round2.py` (12/12) — every mode to completion.**

- `InvariantTracker.feed` (`:122-169`) is fed the real `state` from every `ad.step()`
  (`:191`, `:212`) — mirrors the ExploitHunter contract; violations are appended strings.
- `:249`, `:285`, `:306` (classic/survival/endless terminate): each reads live
  `gamePhase=='finished'` + winner + mode-specific evidence (loser-cardless/World,
  SURVIVAL/ENDLESS log) after driving the mode to completion; `and not t.violations`.
- `:268`, `:286`, `:307` per-dispatch invariants clean — each is downstream of a
  drive-to-completion that produced dispatches, so not vacuous.
- `:334-341` coverage (`wars`/`towers`/`moves`/`recycles`): each is `count > 0 and
  census_clean`. The `census_clean` flag alone would be vacuously true, but it is **always
  ANDed with a live `> 0` accumulator** (`:329-332`), so a coverage class that never fired
  FAILS — the positive-count-AND-clean-flag pattern, not a vacuous pass.
- `:346` log stamping reads live `stamp_mismatches`.
- `:372` reset preserves difficulty (live); `:374` **the good exemplar** —
  `len(run1) >= 10 and run1 == run2` guards emptiness before equality (the discipline the
  R3 fix now matches).

**`verify_round3.py` (7/7) — ExploitHunter R3.** Uses the reference driver directly; every
invariant (`inv_ready`…`inv_softlock`, `:171-266`) gets the real `before`/`after`.
- `:171-176` `inv_ready` is fail-closed (missing projection → violation string).
- `:217-220` `inv_war_pile` uses `after.get("warCardCount", 0)`; confirmed safe — the game
  emits it every projection (`tarot-war/src/ugt-hooks.ts:121`
  `warCardCount: s.warCards?.length ?? 0`; `gameLogTotal: s.gameLog.length` at `:130` is
  unconditional).
- Gate: `:328-330` requires `episodes == EPISODES and total_steps > 0` **before** `:332-335`
  `not report.findings`; `:345-346` ≥2 finished + `:347-350` capped-still-progressing read live
  per-episode stats; `:352-355` action coverage + `:356-359` unmapped-id-probed read live
  `action_counts` (the `> 0` requirement forces the refusal path to actually have fired).
- `:373-377` determinism — **the fixed check** (was the vacuous one; see above).

### Reviewed and left unchanged (non-defects, recorded for the trail)

- **`conserved` dead variable (R1 `:221`)** — documented above; a weakening, not a false
  pass, independently gated; left unchanged to protect R1's count.
- **`census_clean`/coverage flags (R2)** — non-vacuous because always ANDed with a live
  `> 0` count.
- **Defensive `.get("warCardCount", 0)` (R3)** — safe; key unconditionally emitted (grep
  above).

---

## L-005 — LLM balance-playtest tier wired (2026-07-21)

**Task:** wire tarot-war for `ugt playtest` (the "is it a good game?" tier). No new drive mode:
tarot-war already uses `engine.type: browser` → `PlaywrightAdapter`, which `playtest_game()`
supports directly. Added a `playtest:` section to `ugt.config.yaml` (key_state_paths /
summary_paths / budgets, `win_path`/`loss_path` deliberately omitted — `winner` is a STRING
set for EITHER player, so `bool(winner)` would report a "win" whenever anyone won; matches
DDD / Nexus-Dominion precedent) and wrote `strategy-guide.md` (war-card mechanic, setup-first
picker flow, the three modes, and the Magical Effects panel per TW-R6).

**Run (live):** `ugt playtest --config integrations/tarot-war/ugt.config.yaml
--strategy-guide integrations/tarot-war/strategy-guide.md --provider ollama` (gemma4:26b,
`--max-actions 30`) against the real Vite server on :5173 (LISTEN PID verified as the correct
tarot-war vite). Completed in 1210s: **30/30 actions, all `action_id:play_round`** — real
`__SEND_ACTION__` dispatches through the game's own `useGameState` handlers, not no-op waits.
Game advanced to round 30 (p1 score +22, Oracle +46, `warPile` conserved back to 0). **0
potential bugs, 0 invariant violations, 0 novel behaviors.** Report at
`results/playtest-report.json` (`summary.actions_taken == 30`, `action_counts ==
{"action_id:play_round": 30}`). R1 re-run immediately after = **22/22** (config change is a
single additive top-level key; R1 builds its own config shim).

**⚠️ Channel-substitution disclosure (not silently reinterpreting the accept line).** The
task's accept text says "≥20 actions via `press_key`/`type_text`." Tarot-war is a
button-based React game with **no keyboard handlers** — `press_key`/`type_text` would land as
silent no-ops (and the contradiction detector would correctly flag them). The honest,
non-vacuous live-UI channel for this browser game is **`action_id` mode** (the default
`playtest_game` selects for `engine.type: browser`), which dispatches through
`__SEND_ACTION__` into the exact real UI handlers. So this run drove `action_id`; treat
"press_key/type_text" as the schema's generic browser-input clause, whose real-handler
equivalent here is `action_id`. A contrived `press_key` run would have been vacuous.

**Model-competence observation (data, not a task failure):** gemma4:26b played only
`play_round` for all 30 steps — it never exercised the mode/difficulty pickers (which apply
only in `setup`, and step 1 already left setup). The ≥20-real-dispatch bar is met; a deeper
balance verdict (varying difficulty to compare Oracle strength, probing effect resolution)
wants a stronger model / the anthropic provider, which stays credit-gated.

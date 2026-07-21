# Warzones × UGT — results log

Commit-traceable record of every ladder round run against the **real** warzones Phaser
game over the browser adapter. A round is only "green" if it was **run live** against the
Vite dev server and printed its own `ROUND n MET — n/n` footer; nothing here is inferred.
This file is the source of truth; the narrative history lives in [README.md](README.md).

Game: `/Users/vs7/Dev/Games/warzones/warzones-game`, branch `main` (`5d3f743` at this audit).
Driver: `ugt/adapters/playwright.py::PlaywrightAdapter` (+ `SeededWarzonesAdapter` in
`verify_round10.py`) → the game's `src/ugt-hooks.ts`
(`window.__GET_STATE__` / `__SEND_ACTION__` / `__RESET_GAME__(seed)`).

## Rounds

| Round | Date | Script | Result (live) | Findings | UGT commit | Game commit |
|---|---|---|---|---|---|---|
| R1 | 2026-07-06 | `verify_round1.py` | **23/23** — one full turn cycle: player acts, all HUD info accessible, bots act, cycle repeats; probes surfaced WZ-R1/R2/R4 | WZ-R1, WZ-R2, WZ-R4 | (pre-RESULTS) | (pre-RESULTS) |
| R2 | 2026-07-07 | `verify_round2.py` | **12/12** — 3 clean cycles: real buy AND sell through TradingScene's own handlers (credit/cargo/stock deltas == quotes), a survived mid-run combat (salvage exact, hull persists, pirate removed), per-action invariants | WZ-R8 | (pre-RESULTS) | (pre-RESULTS) |
| R3 | 2026-07-07 | `verify_round10.py` | **6/6** — `ExploitHunter` (first browser outing): 3 seeded episodes × 400 steps, 11 invariants after every step, all 12 hook actions attempted, same-seed episode-0 replay byte-identical | WZ-R9 | (pre-RESULTS) | (pre-RESULTS) |
| L-001 audit | 2026-07-21 | (all three) | vacuous-check audit — see below | 1 tester defect (empty-traj determinism guard), fixed | `a69d805`+ | `5d3f743` |

> R3 is named `verify_round10.py` for historical reasons (the "ten-turn" gate); it is the
> R3 exploit-hunter rung.

## Findings registry (migrated from README — R1: 23/23 · R2: 12/12 · R3: 6/6, ladder complete 2026-07-07)

- **WZ-R1 (critical) — FIXED & VERIFIED LIVE.** Any pirate encounter destroyed the run
  (three compounding bugs: `CombatScene.init` `{botId}` vs `{enemy}`; `exitToMap()` →
  `BootScene`; player death → BootScene). Fixed to route combat back to `GalaxyMapScene`
  and death to `DefeatScene`. Verified: fought, returned, bot removed, salvage credited,
  hull damage persisted.
- **WZ-R2 (critical) — FIXED & VERIFIED LIVE.** `TradingScene` never launched. Added the
  `#btn-trade` HUD button (+`T`) enabled at a port; both exits return to the map.
- **WZ-R3 (major, OPEN):** `ContractScene` never launched (scoped out of v0.8).
- **WZ-R4 — FIXED.** New games were `Date.now()`-seeded only; `launchNewGame`/
  `__FAST_RESET__` now accept a fixed seed. Same-seed reproduction verified live.
- **WZ-R5 (minor) — FIXED & VERIFIED LIVE.** "Turn ended." was stamped with the NEXT
  turn; now logged before the increment. Pinned by `turn-end-stamp.test.ts`.
- **WZ-R6 (major) — FIXED.** Scene re-entry: `GalaxyMapScene.shutdown()` never wired;
  `DOMHUD` stacked duplicate listeners each entry. Fixed (SHUTDOWN subscription +
  idempotent handlers).
- **WZ-R7 (minor) — FIXED & VERIFIED LIVE.** Combat/bot randomness escaped `SeededRandom`
  in four sites (flee roll, `CombatSystem` seed, bot-turn RNG, personality roll), making
  same-seed runs flaky. Per-encounter/per-bot seeding threaded through. Pinned by
  `combat-rng-seam.test.ts`. Two back-to-back R2 runs now byte-identical.
- **WZ-R8 (critical, found in R2) — FIXED & VERIFIED LIVE.** The commodity registry was
  never populated in the running game (only tests called `registerCommodity`); the
  commodities tab rendered zero rows — the entire player-facing economy loop was
  unreachable. Fixed via `commodities.json` + `loadCommodities()` from `BootScene`.
  Pinned by `commodity-loading.test.ts`. Verified live.
- **WZ-R9 (major, found in R3) — FIXED & VERIFIED LIVE.** A successful flee never marked
  combat resolved (only scheduled `exitToMap` 3s later), so ATTACK still re-engaged during
  the window — a rules hole + wall-clock race. Fix: flee sets `combatResolved = true` with
  `CombatOutcome.Fled` before the delayed exit. Verified live: flee ×5 in R3, same-seed
  400-step replay stayed byte-identical.

Baseline: warzones' own unit suite stays green (2,414/2,414 post-fix). Action ids in
`ugt.config.yaml` must stay in lockstep with `src/ugt-hooks.ts`.

---

## L-001 audit — vacuous-check sweep (2026-07-21)

**Task:** audit all three warzones ladder scripts for the DDD/Pond vacuous-check failure
class (a check that reports clean without ever measuring the thing it claims to verify),
using `ExploitHunter.run()` (`ugt/core/exploit_hunter.py:81-140`) as the reference-good
pattern — that loop passes the real `before`/`after` from `adapter.step()` into every
invariant, and an exception inside an invariant becomes a violation string, not a silent
pass (`exploit_hunter.py:126-134`). Every `ck(...)` in R1/R2/R3 was walked and compared to
that yardstick.

### Instrumentation dispositioned — trajectory + stats fields populated on every branch

The task's *first* named concern: whether `SeededWarzonesAdapter`'s `reset()`/`step()`
overrides (`verify_round10.py:51-97`) actually populate every field the same-seed
comparison (`trajectories_match`) and the stats-reading `ck(...)` calls (the per-episode
loop that classifies full vs legitimate-early-end) consume — on **every** branch,
including an episode-terminating step and a refused action. Read end to end:

- **`reset()` (`:62-78`):** the `self.stats.append({...})` at `:69-77` is unconditional —
  nothing branches before it — and initializes all seven keys later code reads (`seed`,
  `start_turn`, `max_turn`, `steps`, `terminated`, `final_scenes`, `traj: []`). Every
  episode therefore has a well-formed stats slot before its first step.
- **`step()` (`:80-97`):** there is **no** early return, **no** `if terminated:` guard, and
  **no** `if not info.ok:` guard anywhere in the body. After `super().step()` (`:81`)
  supplies the real `state`/`terminated`/`info`, lines `:83-86` update
  `steps`/`max_turn`/`terminated`/`final_scenes` unconditionally, and the
  `st["traj"].append((...))` at `:88-96` runs on **every** path before the single `return`
  at `:97`. Consequently:
  - a **terminating** step (VictoryScene/DefeatScene) still records its trajectory tuple and
    flips `st["terminated"]` at `:85` — the exact field the per-episode `ck` reads (`:306`)
    to classify a legitimate early end;
  - a **refused** action (`info.ok=False` — e.g. end_turn with no AP, an unreachable warp)
    still appends a tuple, so refusals are recorded identically in the primary and replay
    runs; that is what makes the same-seed compare an exact step-for-step equality rather
    than order-dependent.

Every field inside the tuple (`:88-96`) is read through `.get(...)` or an `or {}` guard, so
a missing projection key yields `None` (a comparable value), not a `KeyError`; the tuple is
always 7-wide, so `trajectories_match` never compares ragged rows. **The exact comparison
made** is element-wise tuple equality (the `x != y` divergence scan inside
`trajectories_match`) over `(action_id, turnNumber, credits, hull, discoveredCount,
botsAlive, sorted(scenes))` for every recorded step. **Conclusion: no defect** — the
instrumentation records on all branches; recorded here because the task required a cited
disposition of the subclass, not a silent assumption.

### Disposition — one finding, fixed

**FOUND (tester defect, fixed here): the R3 same-seed determinism check was vacuous on an
empty trajectory.** Old `verify_round10.py:314-323` computed
`same_len = len(first["traj"]) == len(second["traj"])` and
`divergence = next((… if x != y), None)`, then passed on
`same_len and divergence is None`. For two **empty** trajectories `len([]) == len([])` is
`True` and `next(zip([], []), None)` is `None`, so the equality half of the check reported
"400 steps identical" while comparing **zero** driven steps — the exact class DDD's R3
stitching bug and Pond's vacuous-green belong to. It was masked in this configuration only
because a non-empty episode 0 makes the trajectory non-empty, and an all-crash episode is
caught by the sibling `not replay_report.findings` conjunct; but the trajectory-equality
predicate itself was unguarded and would false-pass the moment a trajectory was empty for a
non-crash reason (0-step config, conditional recording, a future refactor).

**Fix:** extracted a named, importable predicate `trajectories_match(first, second)` that
returns `(False, "empty trajectory — nothing compared …")` on empty input, and re-uses it
at the call site (`not replay_report.findings` kept as a distinct guard). No check was
added or removed → the live MET count stays **6/6**. Compare the in-repo good exemplar
already using this discipline: tarot-war `verify_round2.py:375`
(`len(run1) >= 10 and run1 == run2`).

**Regression artifact:** `integrations/warzones/determinism_selftest.py` (style of
`integrations/pond/pc6_ordering_selftest.py` — synthetic input, no game/browser). It feeds
empty/empty, identical, diverging, unequal-length, and half-empty pairs through
`trajectories_match`, and additionally runs the **exact old inline predicate** on
empty/empty to prove it returned `True` — i.e. that the old version would have passed
wrongly. Runs clean: `Warzones determinism self-test PASSED (6/6 cases)`.

### Per-`ck` disposition (line numbers in the delivered files — `verify_round10.py` post-fix, `verify_round1/2.py` unchanged from `a69d805`)

All checks below read values produced by driving the **real** game this run (live
`__GET_STATE__` projection deltas), can fail on a real regression, and are fail-closed
(the gate returns 0 only when `passed == total`; an uncaught exception adds a FAIL, R1
`verify_round1.py:284`, R2 `:401`, R3 `verify_round10.py:347`).

**`verify_round1.py` (23/23) — one turn cycle.**

| Line(s) | Check | Reads / can fail because |
|---|---|---|
| 117 | reset reaches GalaxyMapScene | live `s0.ready` + `scenes` |
| 120 | seed honored | live `s0.seed == SEED` — proves the game applied the driven seed (not a literal-vs-literal compare) |
| 128 | HUD fields present | live `missing` list over the projection |
| 130 | galaxy to spec | live `sectorCount==100 & botsAlive==8` |
| 133 | fog initialized | live `fog.discoveredCount==1` + exits |
| 136 | event log readable | live `isinstance(eventLog, list)` |
| 137 | ports exist | live `portCount>0` |
| 143 | scan spends AP | live `info.ok` + AP delta `s1<ap0` |
| 151 | warp moves player | live `info.ok` + sector delta |
| 153 | warp spends 1 AP | live `AP == before-1` |
| 155 | fog advances | live `discoveredCount >= before` |
| 158 | warp logged | live `WarpComplete` events |
| 165 | end_turn advances | live `turnNumber == before+1` |
| 167 | AP refreshes | live `AP > before` |
| 171 | bots ticked | live `survived_ticks == alive_before` delta |
| 174 | bots acted | live `moved_or_spent>0 or BotAction>0` |
| 176 | TurnEnd logged | live event count |
| 187 | cycle 2 warp+end | live `info_w.ok` + turn delta |
| 190 | cycle 2 bots ticked | live delta |
| 201 | same seed → same galaxy | two live seeded resets, `fp_first==fp_second` |
| 220 / 226+230 | trading reachable (F2) | honest inconclusive-**FAIL** (`ck(..., False)`) if no port in 12 warps; else live `opened`/`returned` |
| 275 / 278 | combat resolves (F3) | honest inconclusive-**FAIL** if no fight; else live `resolved_run` |

The F2/F3 inconclusive branches (`:220`, `:278`) are the opposite of vacuous — an
un-exercised path is scored `False`, not skipped.

**`verify_round2.py` (12/12) — three clean cycles + economy + combat.**

- The `Invariants` class (`:46-88`) mirrors the ExploitHunter contract exactly: it is fed
  the real `s` from `ad.step()` on every action via `step()` (`:135-140`) and appends
  violation strings — no silent path.
- `:341` `cycles >= MIN_CYCLES` and `:343` `ap_refreshes == cycles` read live counters
  incremented from real turn deltas (`:327-328`); a zero-progress run fails here.
- `:345` `not inv.violations` is **downstream** of the `cycles>=3` gate, which requires ≥3
  real `end_turn` steps, each counted in `inv.steps`; it cannot be vacuously green on zero
  steps. Detail prints `inv.steps` actions checked.
- `:354` BUY / `:364` SELL assert against **live** `info` fields captured from the trade
  handlers (`good_buy`/`good_sell` require `b["ok"]` where `ok = paid == unitPrice` etc.);
  no clean trade ⇒ the `next(... , None)` yields `None` ⇒ the check reports the failing
  attempts and FAILS. Not vacuous.
- `:372` trade round-trip on the map; `:378` mid-run combat survived; `:383/:386/:389`
  salvage/hull/bot-removal all read live combat + map deltas.

**`verify_round10.py` (6/6) — ExploitHunter R3.** Uses the reference driver directly, so
every invariant (`inv_ap`…`inv_softlock`, `:129-226`) receives the real `before`/`after`.
Fail-closed reads worth naming:
- `:130-132`, `:167-172`, `:180-182`, `:186-187` (AP/cargo/hull/scene): a **missing** field
  returns a violation string (`"… missing from state"` / `"state not ready"`), not a
  silent pass — reference-good.
- `:214-216` `inv_eventlog` and `:218-220` `inv_war`-style monotonic checks use
  `.get(key, 0)`; a vanished key would default-to-benign. Confirmed safe: the game emits
  the key on every projection — `warzones-game/src/ugt-hooks.ts:172`
  `eventLogTotal: state.eventLog?.events?.length ?? null` and `:131` `sectorCount` /
  `:168` `portCount` are always present (`inv_world` at `:208-209` additionally asserts the
  literal `sectorCount == 100`, fail-closed).
- Gate checks: `:289-291` requires `report.episodes == EPISODES and report.total_steps > 0`
  **before** `:293-296` `not report.findings`, so a zero-step run cannot launder an empty
  findings list past the gate. `:311` ≥2 full cycles and `:313` every episode accounted
  read live per-episode `max_turn - start_turn`. `:318` action-coverage reads live
  `report.action_counts`.
- `:334-335` determinism — **the fixed check** (was the vacuous one; see above).

### Reviewed and left unchanged (non-defects, recorded for the trail)

- **Defensive `.get(key, 0)` in monotonic invariants** (R3 `inv_eventlog`; R2 cargo guard):
  safe because the game unconditionally emits the keys (grep above) and each is paired with
  either a stronger literal assertion (`sectorCount == 100`) or a step-count-bearing gate.
- **F2/F3 "inconclusive" outcomes** score `False`, never skip — the honest-fail pattern the
  task wants, not a widened denominator.

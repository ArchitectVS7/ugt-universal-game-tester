# SpacerQuest (Rimward) Trial Ladder — Master Task List

Build the missing R1/R2/R3 rungs of UGT's standardized trial ladder
(spike → smoke → R1 playability → R2 full spine → R3 exploit-hunter, per
`UGT-USER-MANUAL.md`) against `integrations/spacerquest/` — the only
non-paused integration that has never been run through it. Closest built
analogues to copy the shape of: `integrations/nexus-dominion/` and
`integrations/ddd/` (both drive a real subprocess-harness game through
`ugt/core/trial.py`'s `GateRunner`/`InvariantSuite`/`first_divergence`
scaffold — the exact game-agnostic pieces this list reuses, not
reimplements). Source of truth for what already exists and what T-1604
already proved: `integrations/spacerquest/HANDOFF.md`,
`integrations/spacerquest/README.md`, `integrations/spacerquest/ugt.config.yaml`,
`integrations/spacerquest/feature-map.yaml`.

**Important scope note:** unlike ddd/nexus-dominion, this integration does
**not** need a new custom harness adapter. `rimward_gym_bridge.py` (already
in-repo) + the generic `ugt.adapters.subprocess.SubprocessAdapter` already
satisfy `BaseAdapter` in full (`connect`/`reset`/`step(action_id)`/`close`)
and were proven at volume in the T-1604 campaign (2026-07-17): `ugt smoke-test`
PASS, `ugt verify` 9/9 features, RL train/eval VALID, 71,107 actions logged
with 0 `ActionBlocked` / 0 protocol errors. "Building the harness" here means
adding the three missing round scripts plus a shared invariants module that
drive that *existing, already-validated* adapter through the standardized
ladder shape — not new transport code. `smoke_spacerquest_adapter.py` already
covers the spike tier (raw wire, no adapter class in between); nothing in
this list touches or duplicates it.

## Orchestrator protocol

1. **Check out** the first task with `status: TODO` whose `after:` tasks are all DONE. Set it `IN-PROGRESS`.
2. **Plan** — hand the coder the task block, plus the pointers named in this intro and in the task body. Nothing else.
3. **Code** — implement per the plan and the Standing constraints.
4. **Review** — check the diff against the task's **Accept** criteria (written to be mechanically checkable by actually running the script).
5. On pass: run the gate, commit as `T-NNN: <title>`, set `status: DONE`, update this file in the same commit. On fail: one fix round with the coder, then escalate, then halt.

**Gate (every task):** from the UGT repo root, with `node` on PATH and the SpacerQuest protocol bin built once (`npm --prefix ../SpacerQuest run build -w @spacerquest/sim`, or from the SpacerQuest repo `npm run build -w @spacerquest/sim`): `python3 -m py_compile integrations/spacerquest/*.py ugt/core/*.py` exits 0, **and** the task's own new/changed script exits 0 and prints its round's `MET` footer. **There is no pytest/unittest suite in this repo (per CLAUDE.md) — the ladder scripts themselves are the tests.** From M3 onward, additionally re-run every earlier round script named in the task's `after:` chain and require it still reports `MET` (no regressions as later rounds land).

**Standing constraints** (the reviewer enforces on every task):
- **Never reimplement game logic** in a script or invariant predicate — every check reads state back from the real wire and compares; it never re-derives a rule (e.g. the exact credit cost of a jump). An action the engine doesn't advertise is never fabricated.
- **A failed check or invariant violation is DATA** — record it as a `[FINDING]`, let the gate report `NOT MET`, and say so plainly in the Delivered note. Never soften an assertion, narrow a denominator, or delete a check to force a pass.
- **No vacuous passes** — every assertion must be able to fail (no comparing a value to itself, no asserting against a collection that's empty by construction).
- **Reuse `ugt/core/trial.py` exactly as-is** (`GateRunner`, `InvariantSuite`, `first_divergence`) — do not fork or duplicate that scaffold per-game.
- **The existing bridge is the adapter for every round.** Construct `ugt.adapters.subprocess.SubprocessAdapter` directly against `integrations/spacerquest/ugt.config.yaml` via `ugt.utils.config_parser.UgtConfig` (mirroring how `ddd`/`nexus-dominion`'s round scripts construct their own harness adapters directly, bypassing `engine.type` CLI dispatch). If a round genuinely needs a capability the bridge doesn't expose, name that gap explicitly in the task's Delivered note rather than quietly writing new adapter code.
- **Any real SpacerQuest defect a round surfaces is a finding to file, not to route around** — record it in the Delivered note and, if upstream code needs a fix, say so explicitly (per this repo's dual-validation convention); do not weaken the check that found it.

Statuses: `TODO` | `IN-PROGRESS` | `DONE` | `BLOCKED(reason)`

---

## M1 — Shared invariants module

### T-101 · SpacerQuest invariant predicates — `status: DONE` · `coder: opus` · `after: —`
Create `integrations/spacerquest/invariants.py`, mirroring the shape of `integrations/nexus-dominion/invariants.py`: a list of FLAT per-step predicates with signature `(before, after, command, result) -> str | None`, operating on the bridge's normalized state dict (see `rimward_gym_bridge.py:315-352` `Bridge._state()` and `ugt.config.yaml`'s `observation_space` for the exact field names: `day`, `phaseDay`, `eraVeteran`, `credits`, `debt`, `fuel`, `maxFuel`, `diceLeft`, `boardCount`, `blockedFromLegal`, `protocolErrors`, `victory`, etc.). Cover at minimum: (a) **financial sanity** — `credits`/`debt`/`fuel` are never negative and `fuel` never exceeds `maxFuel`; (b) **calendar monotonicity** — `day` never decreases and `phaseDay` stays in `{0, 1}`; (c) **protocol parity** — `blockedFromLegal` and `protocolErrors` never increase within an episode (this promotes `feature-map.yaml`'s end-of-run `parity_no_blocked_from_legal` check into a per-step invariant that catches a regression the instant it happens, not just at the end); (d) **era monotonicity** — `eraVeteran` (0/1) never flips 1→0 within one episode (Tour One resolution is one-way, per `rimward_gym_bridge.py`'s own `terminated` comment); (e) **dice bounds** — `diceLeft` stays within `[0, 5]` (the dawn hand size confirmed by `smoke_spacerquest_adapter.py`). Export `ALL_FLAT_PREDICATES` as a list, exactly like the nexus-dominion module, so `verify_round1/2/3.py` and `InvariantSuite.to_hunter_invariants()` in `ugt/core/trial.py` can consume it identically across every tier.
**Accept:** `integrations/spacerquest/invariants.py` exists and exports `ALL_FLAT_PREDICATES` as a list of callables matching `(before, after, command, result) -> Optional[str]`; each predicate carries a one-line docstring naming the invariant it checks; running `python3 -c "import sys; sys.path.insert(0,'integrations/spacerquest'); from ugt.core.trial import InvariantSuite; from invariants import ALL_FLAT_PREDICATES; InvariantSuite(ALL_FLAT_PREDICATES)"` from the repo root raises no error; no predicate re-derives a game rule (only reads and compares state).

**Delivered (2026-07-24):** Shipped `integrations/spacerquest/invariants.py` with eight FLAT per-step predicates over the signature `(before, after, command, result) -> str | None`: `inv_no_negative_resources` + `inv_fuel_within_tank` for financial sanity, `inv_day_monotonic` + `inv_phaseday_binary` for calendar monotonicity, `inv_blocked_from_legal_non_increasing` + `inv_protocol_errors_non_increasing` for protocol parity, `inv_era_one_way` for the one-way Tour One flag, and `inv_dice_bounds` for the `[0, 5]` dawn-hand ceiling — all exported as `ALL_FLAT_PREDICATES`, each with a one-line docstring, each reading and comparing state fields already computed by the bridge's `_state()` rather than re-deriving any game rule. Deliberate scope boundary: unlike `nexus-dominion/invariants.py`, this module has no `full_state_violations` counterpart — the Rimward bridge's wire only exposes the normalized flat dict (no decoded `GameState`), so a second, deeper predicate layer would have to invent structure the bridge doesn't actually report, which the module's own docstring calls out explicitly rather than fabricating it. Note that `integrations/` is gitignored per this repo's shareable-surface convention, so this file lives on disk but is intentionally outside the tracked commit; the only tracked change in this commit is this TASKS.md status flip.
Orchestration: graphify=none — no graphify-out/graph.json in the repo root. · attempts=1/4.

---

## M2 — Round 1: playability gate

### T-201 · verify_round1.py — one full day-loop campaign + invariants + determinism — `status: DONE` · `coder: opus` · `after: T-101`
Write `integrations/spacerquest/verify_round1.py` following the shape of `integrations/nexus-dominion/verify_round1.py` / `integrations/ddd/verify_round1.py`: import `GateRunner`/`InvariantSuite`/`first_divergence` from `ugt.core.trial`, `UgtConfig` from `ugt.utils.config_parser`, and `SubprocessAdapter` from `ugt.adapters.subprocess`, constructed directly against `integrations/spacerquest/ugt.config.yaml` (its fixed `training.seed: 42` is what `SubprocessAdapter.connect()` passes to the bridge via `UGT_SEED`). Drive a scripted action-id sequence covering the core day-to-day loop a first session would take (sign a contract, buy fuel, travel toward it, end the day, pay down debt — reuse the action ids named in `ugt.config.yaml`'s `action_space`) across **multiple in-game days** (≥8–10, landing at least one full within-day dice-exhaustion rollover), running the T-101 `InvariantSuite` after every step (zero violations required). Check: (1) `reset()` gives a sane baseline (day 1, phase rolls DAWN→DAY, dice dealt, credits/debt/fuel within the ranges `ugt.config.yaml`'s `observation_space` declares); (2) the scripted campaign completes with **zero** invariant violations and zero `blockedFromLegal`/`protocolErrors`; (3) **determinism** — connect two *separate* `SubprocessAdapter` instances (two fresh node subprocesses, so each bridge's internal episode counter starts at 0 and both resolve the identical `BASE_SEED + 0` seed), drive both through the *identical* scripted action-id sequence, and compare the two resulting state-dict streams with `first_divergence` (must be `None`); (4) at least one real day-boundary rollover (`day` N→N+1, dice/board refreshed) is observed and asserted.
**Accept:** `python3 integrations/spacerquest/verify_round1.py` exits 0 and prints `ROUND 1 MET`; the script uses `ugt.core.trial.GateRunner`/`InvariantSuite`/`first_divergence` (no duplicated accumulator logic); zero invariant violations across the full scripted run; the determinism check runs two independently-connected adapter instances and asserts `first_divergence(stream_a, stream_b) is None`; the script runs standalone via `python3 integrations/spacerquest/verify_round1.py` from the repo root (node on PATH, SpacerQuest sim built).

**Delivered (2026-07-24):** Shipped `integrations/spacerquest/verify_round1.py`, built entirely on `ugt.core.trial.GateRunner`/`InvariantSuite`/`first_divergence` against the existing `SubprocessAdapter`/`rimward_gym_bridge.py` pairing — no new transport code. A fixed scripted campaign (`LOOP` = sign_contract → buy_fuel_max → travel_contract → pay_debt → end_day, repeated, plus an `EXHAUST` block of six `explore`s that drains all 5 dice before a die-free `pay_debt` and `end_day`) runs ~10–11 in-game days from a single `reset()`, with the T-101 `InvariantSuite` swept after every step. Four gated checks land: (1) baseline sanity — day 1, phaseDay DAY, 5 dice, and every `observation_space`-mapped field inside its declared `[min,max]` (read generically off the config, not hardcoded); (2) zero invariant violations across the whole run plus wire-level `blockedFromLegal`/`protocolErrors` both ending at 0; (3) a real day N→N+1 rollover (dice refreshed to 5, ≥9 days elapsed) *and* a within-day dice-exhaustion state (`diceLeft==0` while still `phaseDay==DAY`) observed before that day rolls; (4) determinism — two independently-connected `SubprocessAdapter` instances (two fresh node subprocesses, each resolving `BASE_SEED+0`) driven through the identical script produce a byte-identical state-dict stream per `first_divergence`. One behavior surfaced as an explicit observation rather than a finding: the bridge does not auto-roll on dice exhaustion (die-free actions like `pay_debt` stay legal at `diceLeft==0` until an explicit `end_day`) — confirmed expected since the wire stays clean and no invariant fires. Deliberate scope boundary, matching T-101: `integrations/` is gitignored per this repo's shareable-surface convention, so `verify_round1.py` and its run artifacts live on disk but only this TASKS.md status flip is tracked in this commit.
Orchestration: graphify=none — no graphify-out/graph.json in the repo root; I grounded the plan directly in the bridge, config, trial.py, and an empirical probe run. · attempts=1/4.

---

## M3 — Round 2: full spine

### T-301 · verify_round2.py — every mode reachable to a real outcome — `status: TODO` · `coder: opus` · `after: T-201`
Write `integrations/spacerquest/verify_round2.py` exercising **every one of the 20 action ids** (0–19) in `ugt.config.yaml`'s `action_space` at least once, each with its own named check reading a genuine post-action state delta — go beyond `feature-map.yaml`'s 9 Phase-1 assertions (extend, don't duplicate them): reach and resolve at least one **Combat** encounter (drive travel/explore until the engine's own encounter trigger fires — do not force it artificially — and record which stance(s) among talk/run/fight actually became reachable in the run, rather than assuming all three fire), a **Storylet** resolution (`storylet_first`), a **Hangout** visit (`visit_hangout`), a **Crew** hire (`crew_hire`), a **Shipyard** purchase beyond repair (`shipyard_buy`) and a repair (`shipyard_repair`), an **Explore** outcome — POI/derelict/salvage/fragment/contraband (`explore`, repeated enough times to observe at least one non-empty outcome), the **forfeit_cargo** escape hatch, and either a full debt payoff (`pay_debt` to `debt == 0`) or the era flip itself (`eraVeteran` 0→1, Tour One resolved) if reachable within a bounded day/step budget you choose and document. If the era flip is not reachable within that budget, record it as an explicit named gap in the script's own output and in the Delivered note — never a silent skip (per this repo's rule against narrowing scope quietly). Run the T-101 `InvariantSuite` after every step throughout (zero violations required, as in R1). Re-run `verify_round1.py` at the end of the script and require it still reports `MET`.
**Accept:** `python3 integrations/spacerquest/verify_round2.py` exits 0 and prints `ROUND 2 MET`; every action id 0–19 was driven at least once with its own named check on a real state delta (never a bare "it didn't crash"); zero invariant violations across the run; any action id whose real effect could not be reached within the documented budget is an explicit `[FINDING]`/gap in both the script's output and the Delivered note; `python3 integrations/spacerquest/verify_round1.py` still exits 0 after this task lands.

---

## M4 — Round 3: exploit-hunter + determinism

### T-401 · verify_round3.py — exploit-hunter walk + same-seed replay — `status: TODO` · `coder: opus` · `after: T-301`
Write `integrations/spacerquest/verify_round3.py` using `ugt.core.exploit_hunter.ExploitHunter` directly against a fresh `SubprocessAdapter`/`rimward_gym_bridge.py` pairing (mirroring `integrations/nexus-dominion/verify_round3.py`'s structure). Build `invariants = InvariantSuite(ALL_FLAT_PREDICATES).to_hunter_invariants()` from the T-101 module; pass `action_ids=list(range(20))` — the **full** vocabulary, deliberately NOT the RL `training.action_subset` (R3 fuzzes everything, per this repo's exploit-hunter convention); use the hunter's default uniform-random policy unless it proves too shallow to reach interesting states, in which case a light documented heuristic is acceptable latitude (same as ddd/nexus-dominion's R3 scripts took). Choose an episode/step volume proportionate to `MAX_DAYS`/`MAX_ACTIONS_PER_DAY` (bridge defaults 45/30) and document the actual numbers used. Assert zero `HuntReport` findings (`kind="invariant"` or `"crash"`); any that surface are `[FINDING]`s to report — and, per this repo's dual-validation convention, likely real upstream SpacerQuest defects to flag, not to paper over. Add a same-seed replay determinism check mirroring T-201's approach but for the hunter tier: build two fresh `SubprocessAdapter` + `ExploitHunter(..., seed=<same value>)` pairs (each its own subprocess, so each starts at episode 0 with the identical `BASE_SEED + 0` game seed AND the identical hunter policy-RNG seed), run `hunter.run(episodes=1, steps_per_episode=<N>)` once on each, and compare the two full state-dict streams with `first_divergence` (must be `None`). Re-run `verify_round1.py` and `verify_round2.py` at the end and require both still report `MET`.
**Accept:** `python3 integrations/spacerquest/verify_round3.py` exits 0 and prints `ROUND 3 MET`; it drives `ugt.core.exploit_hunter.ExploitHunter` against the real bridge/adapter over a documented episode × step volume (state the actual numbers in the Delivered note); zero unresolved invariant/crash findings (any real finding found during development is either fixed upstream in SpacerQuest, with that fix named, or explicitly recorded as open — never silenced); the same-seed replay check asserts `first_divergence(...) is None` between two independently-run hunter passes; `verify_round1.py` and `verify_round2.py` both still exit 0 after this task lands.

---

## M5 — Docs + resume doorway

### T-501 · Record the ladder result in HANDOFF.md / README.md — `status: TODO` · `coder: sonnet` · `after: T-401`
Update `integrations/spacerquest/HANDOFF.md` with a new dated section recording the full ladder result — spike/smoke inherited as already-proven from T-1604, plus R1/R2/R3 pass counts and any findings filed, in the same style every other integration's `HANDOFF.md` uses. Update `integrations/spacerquest/README.md` to document the run recipe for the three new scripts in ladder order, matching the `ddd`/`nexus-dominion` README shape. Do not alter or remove the existing T-1604 four-phase results already recorded in either file — this is additive only.
**Accept:** `HANDOFF.md` has a new dated section naming all three round results (pass/fail counts) and any findings filed, with pointers to the new scripts; `README.md` documents the exact commands to run spike → smoke → R1 → R2 → R3 in order; no existing T-1604 content in either file was altered or removed.

---

## Deliberately deferred (do not scope-creep into this list)
The LLM playtest tier (a T8.2-equivalent balance/strategy pass) — an explicit follow-on once R3 is green, not part of building the ladder itself. The Andromeda-region expansion content and any other upstream game feature work — entirely out of scope of a test harness.

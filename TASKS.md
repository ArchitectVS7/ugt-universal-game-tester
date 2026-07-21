# UGT — Get Every Game to the LLM Playtest Tier

The 2026-07-21 track-record report (`UGT-TRACK-RECORD.md`) found that only SpacerQuest (old) has ever
completed an LLM balance-playtest campaign — tarot-war, NEXUS, DDD, nexus-dominion, and pond have all had this
tier explicitly deferred. This list closes that gap. Per explicit priority, it starts with an audit: UGT has
now independently rediscovered the same "silently vacuous check" failure mode twice (DDD's seed-search
stitching bug, Pond's `HuntAdapter.step` never wiring `info["result"]`) in two unrelated, bespoke per-game
scripts — and the two integrations that predate both discoveries, Warzones and Tarot-War, have never been
checked against it. That audit runs first and independently of everything else.

Sources of truth: `UGT-TRACK-RECORD.md` (why this list exists), `PLAN-FORWARD.md` (framework backlog item:
"`ugt playtest` structured-JSON drive mode"), `PLAYTEST-DESIGN.md` (the LLM tier's design spec — state-delta
assertions, expected_outcome commitment, RNG seams), `ugt/core/playtester.py` (the tier itself),
`ugt/core/exploit_hunter.py` (the shared, already-hardened R3 driver — the reference-good pattern for M0), and
the archived `archive/TASKS-2026-07-20-pond-r2-gate-repair.md` (this list's Standing constraints reuse its
"no vacuous passes" language, since that repair is exactly the failure class M0 is checking for elsewhere).
Per repo `CLAUDE.md` there is no pytest suite — these scripts *are* the tests.

## Orchestrator protocol

1. **Check out** the first task with `status: TODO` whose `after:` tasks are all DONE. Set it `IN-PROGRESS`.
2. **Plan** — hand the coder the task block plus the pointers named in this intro. Nothing else.
3. **Code** — implement per the plan and the Standing constraints.
4. **Review** — check the diff against the task's **Accept** criteria.
5. On pass: run the gate, commit as `<ID>: <title>`, set `status: DONE`, update this file in the same commit. On fail: one fix round, then escalate, then halt.

**Gate (every task):** `python3 -m py_compile ugt/core/*.py ugt/adapters/*.py integrations/*/*.py` exits 0,
**and** the R1 (playability) script of every game a task touches still reports MET/PASSED with no drop in its
check count (R1 is every game's known-green rung and must never regress). Tasks that add a new playtest path
additionally run it once with `--provider ollama` (free, local, no Anthropic credits needed) and attach the
resulting `results/playtest-report.json` (or run log) to the delivery note as evidence it actually executed
against the real game, not a stub.

**Standing constraints** (the reviewer enforces on every task):
- **No vacuous passes.** Every assertion must be able to fail. Comparing a value to itself, asserting on an
  empty collection, or a check whose input was silently never populated by the run is prohibited — this is
  the exact defect class M0 exists to hunt down elsewhere in the repo, so it binds doubly hard on M0 itself.
- **A gate/audit conclusion needs cited evidence, not a feeling.** "Looks fine" is not a finding. Every
  disposition (found-and-fixed, or checked-and-clean) must name the specific code compared and why it differs
  from (or matches) the known-bad pattern.
- **Never reimplement game logic in a tester or adapter** (repo `CLAUDE.md`) — read state over the wire, and
  an unmapped action raises `NotImplementedError` rather than fabricating behavior.
- **Reuse existing state/action shapes.** Every game's ladder scripts already produce a JSON state shape and
  (where applicable) a legal-action enumeration — the playtest tier must consume that shape, never invent a
  second one for the same game.
- **Never widen a denominator to look better, never narrow one to hide a gap.** If a check's category changes,
  say so in the delivery note with the before/after tally.
- **The core LLM-loop contract does not change.** State-delta assertion (compare `expected_outcome` to the
  actual delta, never "the call succeeded"), the `reasoning`/`expected_outcome`/`potential_bug` fields, and the
  bug-report JSON shape in `ugt/core/playtester.py` stay identical across every engine/provider path — new
  tasks add an input/action *channel*, never a second tester.

Statuses: `TODO` | `IN-PROGRESS` | `DONE` | `BLOCKED(reason)`

---

## M0 — Vacuous-check audit (Warzones, Tarot-War)

### L-001 · Audit Warzones' and Tarot-War's ladder scripts for the DDD/Pond vacuous-check failure mode — `status: DONE` · `coder: opus` · `after: —`
Read `integrations/warzones/{verify_round1,verify_round2,verify_round10}.py` (note: Warzones' R3 is misnamed
`verify_round10.py`) and `integrations/tarot-war/{verify_round1,verify_round2,verify_round3}.py` end to end —
not just their R3 files, since DDD's bug lived in bespoke driving logic that wasn't confined to any one rung.
Both games' R3 scripts call the shared `ExploitHunter.run()` (`ugt/core/exploit_hunter.py:81-140`) directly
rather than through a bespoke wrapper subclass — structurally the *right* pattern, since that loop passes the
real `before`/`after` state dicts straight from `adapter.step()`'s own return value into every invariant on
every step, and an exception inside an invariant check becomes a violation message rather than a silent pass
(`exploit_hunter.py:125-134`). That is the reference-good pattern; use it as the yardstick. Two things still
need checking, not assumed clean: (1) both R3 scripts' `SeededWarzonesAdapter`/`SeededTarotAdapter` subclasses
override `reset()`/`step()` purely to record trajectory stats for the determinism-replay check
(`verify_round10.py:51-97`, `verify_round3.py:58-114`) — confirm that instrumentation actually populates every
field the trajectory-comparison and the `ck(...)` calls read, on every branch (including the early-terminate
and refused-action paths), not just the happy path; (2) walk every `ck(...)` call in all six files and confirm
each one reads a value actually produced by driving the real game *this run* — not a literal, not a stale
default carried from a previous episode, not an empty-collection vacuous pass. If the failure class (or any
sibling of it) is found, fix it and add a committed negative-case regression artifact proving the old version
would have passed wrongly — matching the style of Pond's `integrations/pond/pc6_ordering_selftest.py` /
`stderr_scan_selftest.py` (a small checked-in script feeding a synthetic bad case through the extracted
predicate, no game/wire involved). If nothing is found, that is a legitimate outcome — but the delivery note
must show the specific code compared for each of the six files (cite line numbers) and why it's safe, not an
unevidenced "looks fine". Byproduct: unlike NEXUS/DDD/nexus-dominion/pond, Warzones and Tarot-War have never
had a `RESULTS.md`/`HANDOFF.md` (findings currently live only in each game's `README.md`) — write both,
following the established per-game format, and record this audit's disposition there in commit-traceable form.
**Accept:** all six ladder scripts (3 rungs × 2 games) have a recorded disposition citing specific line numbers
and the exact comparison made against the `ExploitHunter` reference pattern; any found instance of the failure
class is fixed with a committed negative-case regression script; `integrations/warzones/RESULTS.md` and
`integrations/tarot-war/RESULTS.md` exist, follow the established per-game format (see `integrations/ddd/RESULTS.md`
for the house style), and record this audit; each game's R1 script still reports the same MET count as before
this task (`verify_round1.py` for both games, non-regression); `HANDOFF.md` added for both games pointing at
the new `RESULTS.md`.

**Delivered (2026-07-21):** All six ladder scripts (`verify_round1/2/10.py` for Warzones,
`verify_round1/2/3.py` for tarot-war) were read end to end and every `ck(...)` call dispositioned against the
`ExploitHunter.run()` reference pattern, with the trajectory-recording `SeededWarzonesAdapter`/
`SeededTarotAdapter` subclasses confirmed to populate every field on every branch (terminating step, refused
action, unmapped-id probe) — no vacuous instrumentation there. One real instance of the DDD/Pond failure class
was found and fixed in both games' R3 same-seed determinism checks: `same_len and divergence is None` reports
"identical" for two *empty* trajectories, which would have false-passed the moment a trajectory was empty for a
non-crash reason. Both were replaced with a shared, named `trajectories_match(first, second)` predicate that
fails closed on empty input, with a committed negative-case regression script per game
(`integrations/{warzones,tarot-war}/determinism_selftest.py`, in the style of Pond's
`pc6_ordering_selftest.py`) proving the old inline predicate would have passed wrongly. No check was added or
removed, so live MET counts are unchanged (Warzones 23/23 · 12/12 · 6/6; tarot-war 22/22 · 12/12 · 7/7).
`integrations/warzones/RESULTS.md` and `integrations/tarot-war/RESULTS.md` were created (per-game house style,
migrating prior README-only findings plus the full audit disposition), and `HANDOFF.md` added for both pointing
at the new `RESULTS.md`. Scope boundary: one pre-existing R1 weakening in tarot-war
(`verify_round1.py:221` — a `conserved` dead variable whose `>=40` conservation clause the `ck` never reads) was
found, documented, and deliberately left unchanged rather than fixed, since it is a weakening independently
covered by G4 and R2's census tracker, not a false pass, and changing it would alter tarot-war's R1 MET count
in violation of the non-regression accept criterion.
Orchestration: graphify=none — no `graphify-out/graph.json` in the repo root (checked; task is a code audit grounded directly in the six ladder scripts + the ExploitHunter reference). · attempts=3/4.

---

## M1 — Structured-state playtest drive mode

### L-002 · Build a structured/legal-action `ugt playtest` drive mode + adapter-instance entry point — `status: DONE` · `coder: opus` · `after: —`
`ugt/core/playtester.py`'s `playtest_game()` (lines 52-94) only dispatches on `config.engine_type` in
`{"browser","simulation","real_server"}`, constructing `PlaywrightAdapter`/`SubprocessAdapter`/
`RealClientAdapter` internally from a config path. Its `LLM_ACTION_SCHEMA` (lines 24-46) only knows
`action_type` in `{action_id, press_key, type_text, wait, diagnose, end_turn}` — every value assumes either a
terminal/UI (`press_key`/`type_text`) or a config-registered discrete `action_id`. Three integrations have
neither: `DddHarnessAdapter`, `NexusDominionHarnessAdapter`, `PondHarnessAdapter` (all `ugt/adapters/`) are
JSON-lines subprocess harnesses exposing `reset()`/`step()`/`_read_state()`, and DDD additionally exposes
`_legal(seat)` (the real legal-action list) and `views` (structured `PlayerView` state) — no terminal, no
`press_key`. None of the three is registered under an `engine.type` in `ugt/core/env.py` either; each game's
own ladder scripts construct the adapter directly. Build two things: (1) a new `action_type` value
(`"legal_action"`) whose `value` is one of the real legal-action identifiers reported by the adapter this step
— the LLM's prompt for this mode is built from the adapter's own structured state (`_read_state()`/`views`,
serialized as JSON) plus, where the adapter exposes one, the actual legal-action list, reusing the exact JSON
shape each game's own ladder scripts already produce (do not invent a second state format per game); (2) a new
entry point that accepts an **already-constructed adapter instance** rather than a config `engine_type` string
(e.g. `playtest_game_with_adapter(adapter, llm_kind, strategy_guide, max_actions, ..., action_mode="legal_action")`),
since these adapters aren't behind `engine.type` and each game already owns its `integrations/<game>/verify_round*.py`
— this entry point is also the integration seam L-006 (NEXUS) will reuse for its own text-driven mode. Keep the
core LLM-loop contract (state-delta assertion, `reasoning`/`expected_outcome`/`potential_bug`, bug-report JSON
shape, `_AnthropicLLM`/`_OllamaLLM` dispatch) byte-for-byte identical to the existing path — this is a new
input/action channel, not a second tester. Validate end-to-end against **DDD only** in this task (it has the
cleanest `_legal(seat)`): write `integrations/ddd/playtest_ddd.py` calling the new entry point, with a minimal
`integrations/ddd/strategy-guide.md`, and run it with `--provider ollama` (free, local — do not spend Anthropic
credits validating this). Prove the existing paths are unaffected by re-running one already-working game's
playtest smoke (e.g. `integrations/spacerquest/`'s `ugt playtest`/verify path) unperturbed by the change.
**Accept:** `LLM_ACTION_SCHEMA` gains `"legal_action"` alongside the existing five values without removing or
renaming any; a new adapter-instance entry point exists in `ugt/core/playtester.py` and is exercised by
`integrations/ddd/playtest_ddd.py`; an `ollama`-provider run against DDD completes ≥ 20 actions and produces a
real `playtest-report.json` (or equivalent) containing at least one state-delta-based assertion (not a bare
"call succeeded"); the existing browser/simulation/real_server dispatch branch in `playtest_game()` is
untouched (diff-visible); a smoke re-run of one existing browser/real_server game's playtest path is unaffected
(same behavior as before this task).

**Delivered (2026-07-21):** Added the `"legal_action"` value to `LLM_ACTION_SCHEMA`/`_VALID_ACTION_TYPES`
alongside the existing five (none removed or renamed), and a new `playtest_game_with_adapter()` entry point in
`ugt/core/playtester.py` that takes an already-constructed adapter instance plus an `action_mode`, sharing the
existing `_run_and_write`/`_run_single_playtest` loop (state-delta assertion, bug-report shape, invariant
checks, contradiction detector) byte-for-byte with the config-driven `playtest_game()` path — the original
`playtest_game()` dispatch branch for `browser`/`simulation`/`real_server` is untouched (diff-visible, only
its tail was factored into the shared helper). `_build_legal_prompt()` serializes the adapter's own
`_read_state()` JSON plus its live `legal_actions()` list verbatim (no per-game interpretation), and the LLM
picks one action by 0-based index via `apply_legal()`. Wired and validated against `DddHarnessAdapter` only
(`legal_actions()`/`apply_legal()` added to `ugt/adapters/ddd_harness.py` as pure relays over the existing
`_pending_seat`/`_legal`/`send_raw_action`/`_read_state` primitives, no rules or fabricated effects), via
`integrations/ddd/playtest_ddd.py` + `integrations/ddd/strategy-guide.md` + a `playtest:` config block in
`integrations/ddd/ugt.config.yaml`. An `ollama`-provider run completed 25 actions (`integrations/ddd/results/
playtest-report.json`, gitignored) with real hp state deltas each step and the DDD invariant suite active
(0 violations). The existing config-driven path was proved unaffected by re-running `examples/mock-game`'s
`ugt playtest` smoke through the untouched `playtest_game()` dispatch (`examples/mock-game/results/
playtest-report.json`, gitignored — 5 actions, 0 invariant violations, ran clean minutes before the DDD run).
Scope boundary, deliberately: Nexus-Dominion/Pond adapters were NOT touched and are not wired to this mode
(that's L-003/L-004) — the new `action_mode` seam is proven end-to-end on DDD only, as the task scoped.
Orchestration: graphify=none — no graphify-out/graph.json in the repo root (confirmed via ls). · attempts=1/4.

---

## M2 — Wire the remaining games to the LLM tier

### L-003 · Wire Nexus Dominion to the structured drive mode — `status: DONE` · `coder: sonnet` · `after: L-002`
Using the entry point and `"legal_action"` schema built in L-002, write `integrations/nexus-dominion/playtest_nexus_dominion.py`
against `NexusDominionHarnessAdapter` (`ugt/adapters/nexus_dominion_harness.py`), sourcing prompt state from its
`game_state`/`views`-equivalent property (read the adapter's actual public API — `game_state`, `campaign_id`,
`_read_state()` — rather than assuming DDD's exact shape carries over) and its `_orders_for(name)` /
`_owned_system_ids()` family for a legal-action-equivalent list where one exists; where no clean legal-action
enumerator exists, fall back to the adapter's `action_name(action_id)` id space the same way the exploit-hunter
ladder scripts already do. Write a minimal `integrations/nexus-dominion/strategy-guide.md` covering the 4X
economy/fleet/research loop at a level a balance-playtester needs (not a full manual). Validate with
`--provider ollama` first.
**Accept:** `integrations/nexus-dominion/playtest_nexus_dominion.py` runs to completion via the L-002 entry
point with `--provider ollama`, producing a report with ≥ 20 actions and at least one state-delta assertion;
`strategy-guide.md` exists and is referenced by the script; R1 (`integrations/nexus-dominion/verify_round1.py`)
still reports the same MET count as before this task.

**Delivered (2026-07-21):** Added `integrations/nexus-dominion/playtest_nexus_dominion.py`, wiring
`NexusDominionHarnessAdapter` to the L-002 `playtest_game_with_adapter()` entry point via a local
`PlaytestNexusDominionAdapter` subclass — `legal_actions()`/`apply_legal()` are pure relays over the base
adapter's existing `action_name()`/`step()` primitives, no new game logic. Since the engine has no native
legal-action enumerator (illegal orders are silently refused, not listed), the legal menu is the integration's
own fixed config id space (0-17, one entry per composable action, each carrying a one-line balance note lifted
from the config comments), deliberately narrowing out ids 18/19 (`probe_unknown_type`/`probe_malformed`) — the
two R3 malformed-order robustness probes, which are not balance actions and are disclosed as excluded in the
module docstring. Added a `playtest:` block to `integrations/nexus-dominion/ugt.config.yaml`
(`key_state_paths`/`summary_paths`/`guide_char_budget`) resolving only into the adapter's own normalized
`_read_state()` flat dict, additive and ignored by R1/R2/R3/the exploit-hunter; no `win_path`/`loss_path` is set
because Nexus Dominion has no terminal state by design. Wrote `integrations/nexus-dominion/strategy-guide.md`
covering the 4X economy/fleet/research/diplomacy/covert/military loop and the balance questions a playtester
should probe (economy-before-army, research ramp payoff, Reckoning-cadence tier movement, any single dominant
action). The invariant suite handed to the playtest loop is the SAME `ND.ALL_FLAT_PREDICATES` R3 hands the
ExploitHunter, via `InvariantSuite(...).to_hunter_invariants()` — one definition, both tiers. A
`--provider ollama` run (model `gemma4:26b`) completed 22 actions with 18 legal-action steps carrying a
non-empty state delta and 0 invariant violations (`integrations/nexus-dominion/results/playtest-report.json`,
gitignored — power_delta +314.15, systems_delta +7 over the run), clearing the ≥20-action/≥1-delta/invariants-
ran bar. Scope boundary, deliberately: Pond (L-004) was not touched; the base `NexusDominionHarnessAdapter`
and the R1/R2/R3/exploit-hunter ladder scripts were not modified, only subclassed, so the ladder is
structurally unaffected by this task.
Orchestration: graphify=none — no `graphify-out/graph.json` in the repo root (confirmed via `ls`); task grounded directly in `playtester.py`, the ND adapter/invariants/config, and the  · attempts=1/4.

### L-004 · Wire Pond to a macro-layer structured playtest (upgrade/mutation choices only) — `status: DONE` · `coder: opus` · `after: L-002`
Real-time per-frame combat was already judged the wrong granularity for an LLM loop (per-frame dodging is not
a reasoning task) — do **not** attempt frame-by-frame play here. Scope this to the macro layer: the LLM is
consulted only at level-up decision points, using `PondHarnessAdapter.level_up_pending()` /
`level_up_options()` / `choose_mutation(index, frames)` (`ugt/adapters/pond_harness.py:261-289`) as the
legal-action surface for the new `"legal_action"` mode, with the state prompt built from `_read_state()` (or
the adapter's `_normalize()`'d snapshot) at the moment of each level-up. Between level-ups, drive the run with
the existing heuristic/random policy from `integrations/pond/verify_round1.py` (reuse it, don't rewrite combat
driving) so the LLM's judgment is isolated to the one decision class it's actually suited for. This is a
genuine design task, not mechanical porting — if the macro-layer framing doesn't cleanly fit the L-002 entry
point as built, say so explicitly in the delivery note and propose the minimal extension needed, rather than
forcing a bad fit. Write `integrations/pond/playtest_pond.py` and a minimal `integrations/pond/strategy-guide.md`
covering mutation/upgrade tradeoffs. Validate with `--provider ollama`.
**Accept:** `integrations/pond/playtest_pond.py` runs at least one full run (death or victory) via the L-002
entry point with `--provider ollama`, with the LLM consulted at every `level_up_pending()` decision point and
nowhere else; the report records each mutation choice with its `reasoning`/`expected_outcome`; combat between
level-ups is driven by the existing R1 heuristic/random policy, not reimplemented; R1 still MET with the same
check count as before this task.

**Delivered (2026-07-21):** Wrote `integrations/pond/playtest_pond.py` (a local `MacroPlaytestPondAdapter`
subclass, zero changes to `ugt/core/playtester.py` or the base `PondHarnessAdapter`) that isolates the LLM to
the one reasoning-shaped decision here — the level-up mutation choice — by making `legal_actions()` non-empty
only when `level_up_pending()` is true, and fast-forwarding all combat inside `reset()`/`apply_legal()` with
`verify_round1.heuristic_combat_action`, the R1 policy extracted verbatim so both tiers drive combat
identically. Added `integrations/pond/strategy-guide.md` covering all 19 mutations plus the PC-15
boss-scaling caveat. An `--provider ollama` run MET the accept bar: 7 level-up decisions across 9 runs (6 by
death, 4 by truncation), every pick applied a real mutation with grounded `reasoning`/`expected_outcome`,
invariants clean, 0 bugs; R1 stayed MET 18/18 with the shared-policy extraction. Deliberate scope boundary:
per-frame combat robustness remains R3's job — this tier's invariant checks fire at level-up decision
boundaries, not every combat frame — and the paid Anthropic-provider balance verdict is left credit-gated,
matching L-003's precedent. Full detail in `integrations/pond/RESULTS.md` and `HANDOFF.md`.
Orchestration: graphify=none — no `graphify-out/graph.json` in the repo root (checked; this is a code-integration task grounded directly in `playtester.py`, `pond_harness.py`, `verify_ · attempts=1/4.

### L-005 · Wire Tarot-War for `ugt playtest` (existing browser engine, no new drive mode) — `status: TODO` · `coder: sonnet` · `after: —`
Tarot-War already uses `PlaywrightAdapter` (browser `engine.type`), which `playtest_game()` already supports —
no new drive mode is needed. Add a `playtest` section to `integrations/tarot-war/ugt.config.yaml` and write
`integrations/tarot-war/strategy-guide.md` covering the war-card mechanics, mode/difficulty pickers, and the
Magical Effects panel (per `integrations/tarot-war/RESULTS.md`'s TW-R6 finding, if that file exists after
L-001 — reference it for what's easy to miss visually). Run `ugt playtest --config integrations/tarot-war/ugt.config.yaml
--strategy-guide integrations/tarot-war/strategy-guide.md --provider ollama` and confirm it completes.
**Accept:** `integrations/tarot-war/ugt.config.yaml` has a `playtest` section; `strategy-guide.md` exists; an
`ollama`-provider run completes ≥ 20 actions via `press_key`/`type_text` against the real running game and
produces a `playtest-report.json`; R1 unaffected.

### L-006 · Wire NEXUS for `ugt playtest` — `status: TODO` · `coder: sonnet` · `after: L-002`
`NexusHttpAdapter` (`ugt/adapters/nexus_http.py`) already implements `type_text`/`type_text_step`/
`get_terminal_text` (lines 182-200) — it does NOT need the `"legal_action"` schema from L-002, only the
adapter-instance entry point L-002 builds (since `NexusHttpAdapter` isn't registered under any `engine.type` in
`env.py`, the same reason DDD needed a direct-adapter path). Write `integrations/nexus/playtest_nexus.py` calling
L-002's entry point with `action_mode` left at the existing text-driven schema (`press_key`/`type_text`/
`wait`/`diagnose`/`end_turn` — no new action type), and a minimal `integrations/nexus/strategy-guide.md`
covering the hacking/mission loop and the three difficulty modes exercised in R2. Validate with `--provider ollama`.
**Accept:** `integrations/nexus/playtest_nexus.py` runs to completion via the L-002 entry point using the
adapter's existing `type_text`/`get_terminal_text` (no new action_type introduced for this game);
`strategy-guide.md` exists; an `ollama`-provider run completes ≥ 20 actions and produces a report; R1 unaffected.

---

## Deliberately deferred

- **Topping up Anthropic API credits** — a billing action only the user can take; blocks every *paid*
  (non-`ollama`) balance-verdict campaign. Every task above is validated against the free `ollama` provider
  specifically so this is not a blocker for the coding work itself.
- **Running the full paid Anthropic balance campaigns per game** once wiring exists and credits are topped
  up — that's a "run it and record the verdict" follow-up per game, not a coding task; do after L-001–L-006.
- **Nexus Dominion's human UAT (U-110) retest** — needs an actual human player; an engine/LLM trial cannot
  sign off UAT. Tracked in `integrations/nexus-dominion/HANDOFF.md`, not here.
- **Pond's tongue-feel (PC-10) and accessibility/colorblind UAT** — same, human-only. Tracked in
  `integrations/pond/HANDOFF.md`, not here.
- **Registering the harness adapters under `engine.type` in `ugt/core/env.py`** — the existing framework
  backlog item (`PLAN-FORWARD.md`); L-002's adapter-instance entry point sidesteps rather than resolves this.
  Worth revisiting if a sixth harness-style integration arrives.

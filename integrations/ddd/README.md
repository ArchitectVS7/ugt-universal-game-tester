# DDD integration (real engine, subprocess harness adapter)

Drives the **real** DDD deterministic dueling card game (`../../../DDD`, engine at
`DDD/packages/engine`) through its JSON-lines **harness**
(`DDD/packages/harness/bin/harness.mjs`) via
`ugt/adapters/ddd_harness.py::DddHarnessAdapter` — never a re-implementation of the
game (the `sim_bridge` lesson).

DDD is a two-player deterministic card duel (30 HP, focus 0–5, hand ≤7, 40-card
COMPETITIVE / 25-card TUTORIAL decks, three zones HAND/GRAVEYARD/DECK, no exile). The
harness is a zero-dependency subprocess server: one JSON request per line on stdin,
one response per line on stdout, in order. The adapter spawns it and drives five ops:

| Op | Adapter method | Purpose |
|---|---|---|
| `create` | `reset(seed)` | fresh match (matchId `m1,m2,…`), two PlayerViews, initial `stateHash` |
| `legal` | `_legal(seat)` | the legal `Action`s for one seat |
| `act` | `step(action_id)` | apply one action → events + updated views + hash, or a `RULES_ERROR` (state unchanged) |
| `targets` | `fill_targets(seat, action)` | a commit's graveyard-target candidates — the ONLY wire route to them (`legal` always reports `targets: []`, engine D-A) |
| `replay` | `replay_current()` | re-simulate the recorded action log and verify determinism |

The adapter contains **NO game logic**: it only figures out which seat the engine
is waiting on (MULLIGAN → un-mulliganed seat; SELECTION → uncommitted seat) and
picks an action for the requested `action_id` **from the harness's own legal list**.
Every state fact is read back from the views. The two `probe_*` ids are the sole
exception — they send deliberately illegal actions so refusals can be asserted
state-inert, and are flagged so an *accepted* probe becomes a finding.

> **Waves.** `engine.enabledWaves` must name **all three** keys
> (`stanceEcho`, `chainsPredictions`, `typeTriangle`). A missing key is not a default —
> the engine reads it as `undefined` → falsy, so you silently play a *different game*.
> The adapter now refuses an under-specified wave set. This is how D16's type triangle
> sat switched off through the whole superseded 2026-07-11 run.

Action ids (`ugt.config.yaml`, in lockstep with `DddHarnessAdapter._select`):

| id | name | id | name |
|---|---|---|---|
| 0 | `commit_first` | 7 | `pass` |
| 1 | `commit_random` | 8 | `mulligan_keep` |
| 2 | `commit_last` | 9 | `mulligan_full` |
| 3 | `commit_with_targets` | 10 | `concede` |
| 4 | `commit_no_targets` | 11 | `probe_illegal` |
| 5 | `commit_with_prediction` | 12 | `probe_garbage` |
| 6 | `commit_modal` | | |

Every id is **structural** — it picks among the actions the *harness* enumerated (and,
for targets, among the candidates the harness's own `targets` op returned). No id reads
card costs, rules, or content. An id whose preferred class is absent in the current
phase falls back to another legal non-CONCEDE action, so the whole vocabulary is
driveable in every phase.

`CONCEDE` is filtered out of every id **except** `10 concede`, so a stochastic policy
can never throw a match by accident. Ids **11/12 are the only ones that leave the legal
list** — deliberately, so the engine's refusal paths can be asserted state-inert; they
are flagged `info["probe"]` so an *accepted* probe becomes a finding.

## Prerequisites

- **node ≥ 24** on `PATH` (the harness runs on node v24.x).
- The **DDD repo present at `/Users/vs7/Dev/Games/DDD`** with its dependencies
  installed so `@ddd/engine` resolves from the repo root (the adapter runs the
  harness with `cwd` = the DDD repo root inferred from the harness path).
- **Nothing to start manually.** Unlike the NEXUS/SpacerQuest servers, the harness
  is a subprocess the adapter spawns and tears down itself.
- Overrides: `DDD_HARNESS_PATH` (harness entry) and `DDD_HARNESS_CWD` (working
  dir) env vars take precedence over the config.

## Run

From the UGT repo root:

```bash
python3 integrations/ddd/spike_ddd.py          # 10/10 raw-protocol harness checks
python3 integrations/ddd/smoke_ddd_adapter.py  #  5/5 through the BaseAdapter contract
python3 integrations/ddd/verify_round1.py      # ROUND 1 — one full match + determinism
python3 integrations/ddd/verify_round2.py      # ROUND 2 — the full content spine
python3 integrations/ddd/verify_round3.py      # ROUND 3 — ExploitHunter + refusal battery
```

What each proves:

- **`spike_ddd.py`** — speaks raw JSON lines to the harness (NO adapter) and
  asserts the contract the adapter is built on: `create`/`legal`/`act`/`replay`
  shapes; `RULES_ERROR` on illegal moves (COMMIT_PASS while a card is affordable →
  `PASS_NOT_ALLOWED`; MULLIGAN in SELECTION → `WRONG_PHASE`) with an **unchanged**
  state hash; `PARSE_ERROR` on a malformed line **and loop survival**; `UNKNOWN_OP`
  with id preserved; same-seed determinism (identical initial hash / different
  matchId, and a byte-identical scripted-match hash stream).
- **`smoke_ddd_adapter.py`** — drives the harness **through `DddHarnessAdapter`** so
  the BaseAdapter contract itself is exercised: `connect` spawns a live process,
  `reset` returns a normalized ONGOING state, `step(1)` returns a proper
  `(state, terminated, truncated, info)` 4-tuple with a valid self-selected action,
  `_read_state` returns the normalized dict (the hook the `ExploitHunter` probes),
  clean `close`.
- **`verify_round1.py`** — plays a **whole match to a terminal result** through the
  real engine under the `commit_random` policy, running the DDD invariant suite
  (`invariants.py`) after **every** action. Then it proves same-seed determinism
  (byte-identical `stateHash` stream across two runs, non-vacuous) and re-verifies
  the recorded log with the harness's own `replay`.
- **`verify_round2.py`** — the **full content spine**: every wave configuration, both
  formats, all four decks (mirrors + crosses), every terminal arm the wire reaches,
  and **all 36 shipped cards actually committed**. Proves graveyard targets fire over
  the wire (with a `commit_no_targets` control that must fire *zero*, so the check
  cannot pass vacuously) and asserts D16 **differentially** — the same seed run with
  the triangle ON and OFF, where a countered first combat must gain the counterer
  exactly +4 power and move nothing else.
- **`verify_round3.py`** — the **robustness tier**: UGT's real `ExploitHunter` over the
  whole 13-id vocabulary, plus a refusal battery that provokes 9 `RulesError` arms and
  asserts every one is **state-inert** (refusing is not enough — the hash must not
  move). Adds `hash-moves-iff-applied`, `probe-refused`, **fog-of-war** (the opponent
  view must never leak a hidden field *over the wire*), and no-soft-lock.

## Invariants (`invariants.py`)

Pure predicates `(before, after, command, result) -> str | None` over the adapter's
normalized state, reused in both the scripted rounds (`SUITE.check_command`) and the
R3 `ExploitHunter` tier (`build_suite().to_hunter_invariants()`):
`inv_hash_present`, `inv_hp_bounds`, `inv_focus_bounds`, `inv_hand_cap`,
`inv_card_conservation`, `inv_turn_monotonic`, `inv_no_error_on_legal`,
`inv_legal_nonempty_while_ongoing`.

Two notes on their scope, both learned the hard way:
- **`inv_card_conservation` is a conservation LAW** (the per-seat zone total never
  changes across a step), not a hard-coded `== 40`. The absolute total is
  format-relative — COMPETITIVE 40, TUTORIAL 25 — so the literal form reported a
  violation on every step of every tutorial match while the game was behaving
  correctly. Scripts that know their format assert the absolute figure themselves.
- **`inv_no_error_on_legal` is scoped to non-probe actions.** Its premise ("the adapter
  only sends actions from the engine's own legal list") is deliberately false for
  `probe_illegal`/`probe_garbage`; R3's `inv_probe_refused` asserts the opposite for
  those (an *accepted* probe is the finding).

## Test ladder (test → fix upstream → re-test)

Full commit-traceable log, with every finding and its pinning test: **[RESULTS.md](RESULTS.md)**.

| Round | Script(s) | Gate |
|---|---|---|
| Spike | `spike_ddd.py` | **PASSED (2026-07-12): 10/10** raw-protocol checks (incl. the new `targets` op). |
| Smoke | `smoke_ddd_adapter.py` | **PASSED (2026-07-12): 5/5** through the BaseAdapter contract. |
| R1 | `verify_round1.py` · `invariants.py` | **PASSED (2026-07-12): 11/11** live. One full `commit_random` match to a **WIN via KNOCKOUT** (24 plies / turn 11); sweep CLEAN both runs; 40-card conservation; same-seed replay byte-identical; harness self-replay re-verifies. |
| R2 | `verify_round2.py` | **PASSED (2026-07-12): 26/26** live. 12-match corpus / 348 plies: every wave config, both formats, all four decks (mirrors + crosses), 4 terminal arms, **36/36 shipped cards played**, graveyard targets fire (19 `CARD_RETURNED`) with a zero-firing control, D16 asserted differentially (+4 exactly), D2 in all 20 combats, both determinism oracles. |
| R3 | `verify_round3.py` | **PASSED (2026-07-12): 31/31** live, **zero findings**. Real `ExploitHunter`, 8 ep × 60 steps over the full 13-id vocabulary; 9 RulesError arms provoked and **14/14 probes state-inert**; hash-moves-iff-applied; fog-of-war clean over the wire; no soft-lock; same-seed episode-0 replay byte-identical. |

⚠️ **The 2026-07-11 R1 run is SUPERSEDED.** It was green against the *wrong game*: the
config named two of the three `enabledWaves` keys, so D16's type triangle was silently
OFF and combo chains + Rare predictions were never driven. See `RESULTS.md` D-F2.

Two DDD defects found and fixed upstream (DDD `61125b64`, each with a pinning test in
DDD's own suite): the harness could not express graveyard targets (**D-F1**), and
`create` accepted a `MatchConfig` that `replay` would refuse (**D-F2**).

A failed check is DATA: findings print inline, fail the gate, and are fixed
upstream in DDD with a pinning test — never tolerated here.

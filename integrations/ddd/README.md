# DDD integration (real engine, subprocess harness adapter)

Drives the **real** DDD deterministic dueling card game (`../../../DDD`, engine at
`DDD/packages/engine`) through its JSON-lines **harness**
(`DDD/packages/harness/bin/harness.mjs`) via
`ugt/adapters/ddd_harness.py::DddHarnessAdapter` — never a re-implementation of the
game (the `sim_bridge` lesson).

DDD is a two-player deterministic card duel (30 HP, focus 0–5, hand ≤7, 40-card
decks, three zones HAND/GRAVEYARD/DECK, no exile). The harness is a zero-dependency
subprocess server: one JSON request per line on stdin, one response per line on
stdout, in order. The adapter spawns it and drives four ops:

| Op | Adapter method | Purpose |
|---|---|---|
| `create` | `reset(seed)` | fresh match (matchId `m1,m2,…`), two PlayerViews, initial `stateHash` |
| `legal` | `_legal(seat)` | the legal `Action`s for one seat |
| `act` | `step(action_id)` | apply one action → events + updated views + hash, or a `RULES_ERROR` (state unchanged) |
| `replay` | `replay_current()` | re-simulate the recorded action log and verify determinism |

The adapter contains **NO game logic**: it only figures out which seat the engine
is waiting on (MULLIGAN → un-mulliganed seat; SELECTION → uncommitted seat) and
picks a **legal** action for the requested `action_id` from the harness's own legal
list. It **never concedes** and never sends an illegal action. Every state fact is
read back from the views.

Action ids (`ugt.config.yaml`, in lockstep with `DddHarnessAdapter._select`):
`0 commit_first` · `1 commit_random` · `2 pass` · `3 mulligan_keep` ·
`4 mulligan_full`. An id whose preferred class is absent in the current phase falls
back to another legal non-CONCEDE action, so the whole vocabulary is driveable in
every phase.

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
python3 integrations/ddd/smoke_ddd_adapter.py  # 5/5 through the BaseAdapter contract
python3 integrations/ddd/verify_round1.py      # ROUND 1 — one full match + determinism
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
  (`invariants.py`) after **every** action: HP/focus bounds, hand cap, **exact
  40-card conservation per seat**, turn monotonicity, no `RULES_ERROR` on a
  self-selected legal action, ≥1 legal action while ONGOING. Then it proves
  same-seed determinism (byte-identical `stateHash` stream across two runs,
  non-vacuous) and re-verifies the recorded log with the harness's own `replay`.

## Invariants (`invariants.py`)

Pure predicates `(before, after, command, result) -> str | None` over the adapter's
normalized state, reused in both the scripted rounds (`SUITE.check_command`) and the
R3 `ExploitHunter` tier (`build_suite().to_hunter_invariants()`):
`inv_hash_present`, `inv_hp_bounds`, `inv_focus_bounds`, `inv_hand_cap`,
`inv_card_conservation`, `inv_turn_monotonic`, `inv_no_error_on_legal`,
`inv_legal_nonempty_while_ongoing`.

## Test ladder (test → fix upstream → re-test)

| Round | Script(s) | Gate |
|---|---|---|
| Spike | `spike_ddd.py` | **PASSED (2026-07-11): 10/10** raw-protocol checks against the live harness. |
| Smoke | `smoke_ddd_adapter.py` | **PASSED (2026-07-11): 5/5** through the BaseAdapter contract. |
| R1 | `verify_round1.py` · `invariants.py` | **PASSED (2026-07-11): 11/11** live. One full `commit_random` match to a **WIN via KNOCKOUT** (44 plies / turn 21); invariant sweep CLEAN across every step of both runs; exact 40-card conservation each seat; no RULES_ERROR on any sent action; same-seed replay byte-identical (45-hash stream) + non-vacuous; harness self-replay re-verifies. **Zero findings** → DDD repo untouched. |

A failed check is DATA: findings print inline, fail the gate, and are fixed
upstream in DDD with a pinning test — never tolerated here.

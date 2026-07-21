# DDD — a two-player deterministic dueling card game

> **FULL LADDER COMPLETE AND GREEN** as of the 2026-07-12 evening re-run vs DDD commit
> `0eb0df83` (zero open R3 findings). **LLM playtest tier newly validated 2026-07-21**
> (commit `7fc6f72`, "L-002") — call this out prominently: `HANDOFF.md`/`RESULTS.md`
> (both last touched 2026-07-12) still say the playtest tier is "NOT done" /
> "credit-gated" / "not yet wired". **That claim is now FALSE.** See "LLM playtest"
> below, and correct `HANDOFF.md`/`RESULTS.md` to match next time either is touched.

DDD is a two-player deterministic dueling card game: 30 HP per seat, a 0–5 focus
resource, a 7-card hand cap, a 40-card COMPETITIVE deck or a 25-card TUTORIAL deck,
three zones (HAND / GRAVEYARD / DECK — no exile), and three optional waves
(`stanceEcho`, `chainsPredictions`, `typeTriangle`).

## Transport/adapter

Drives the **real** DDD engine (`DDD/packages/engine`) through its JSON-lines
**harness** (`DDD/packages/harness/bin/harness.mjs`) via
`ugt/adapters/ddd_harness.py::DddHarnessAdapter` — never a re-implementation of the
game (the `sim_bridge` lesson). The harness is a zero-dependency subprocess server
(one JSON request per line on stdin, one response per line on stdout, in order); the
adapter spawns it and tears it down itself, so there is no server to start manually.

The adapter drives a 13-id **structural** action vocabulary — every id picks among
the actions the harness itself enumerated as legal, never among card names or costs:

| id | name | id | name |
|---|---|---|---|
| 0 | `commit_first` | 7 | `pass` |
| 1 | `commit_random` | 8 | `mulligan_keep` |
| 2 | `commit_last` | 9 | `mulligan_full` |
| 3 | `commit_with_targets` | 10 | `concede` |
| 4 | `commit_no_targets` | 11 | `probe_illegal` |
| 5 | `commit_with_prediction` | 12 | `probe_garbage` |
| 6 | `commit_modal` | | |

Ids 11/12 are the only ones that deliberately leave the legal list, to prove the
engine's refusal paths are state-inert; an *accepted* probe is itself a finding.

## Ladder result (exact numbers)

| Round | Gate |
|---|---|
| Spike | **10/10** |
| Smoke | **5/5** |
| R1 | **11/11** |
| R2 | **26/26** |
| R3 | **32/32** — zero open findings |

## Headline findings (both fixed upstream, both pinned)

- **D-F1** — `legalTargets` was never exposed over the wire, permanently inerting 7 of
  the 40 shipped cards. Fixed in DDD `61125b64` with a pinning test.
- **D-F2** — `create()` accepted a `MatchConfig` that `replay` would refuse. Consequence:
  the **2026-07-11 R1 run is SUPERSEDED** — it silently ran with the `typeTriangle`
  wave OFF the entire time. Fixed in DDD `61125b64` with a pinning test.

## Characterizations (one closed, one corrected)

- **D-C1 (closed)** — "Focus economy doesn't bind" was closed by DDD's T6.5 re-price;
  R3 now provokes `INSUFFICIENT_FOCUS` live.
- **D-C2 (partially refuted — correcting the record here)** — "`@ddd/ai` never fills
  targets" was **FALSE**. Only `@ddd/sim`'s random policies skip target-filling;
  `@ddd/ai` does fill targets (`packages/ai/src/eval/candidate.ts:45`, tiers 2+3).

## LLM playtest (new, 2026-07-21)

As of commit `7fc6f72` ("L-002"), a structured/legal-action playtest drive mode is
built and **validated end-to-end** against `DddHarnessAdapter`: a new
`playtest_game_with_adapter()` entry point in `ugt/core/playtester.py`, driven here by
`playtest_ddd.py` + `strategy-guide.md`. A live ollama run completed **25 actions, 0
invariant violations**. This closes the "credit-gated"/"not yet wired" status that
`HANDOFF.md`/`RESULTS.md` still carry from 2026-07-12 — this tier is no longer pending.

Run it with:

```bash
python3 integrations/ddd/playtest_ddd.py
```

## How to run (full ladder, from the UGT repo root)

```bash
python3 integrations/ddd/spike_ddd.py          # 10/10 raw-protocol harness checks
python3 integrations/ddd/smoke_ddd_adapter.py  #  5/5 through the BaseAdapter contract
python3 integrations/ddd/verify_round1.py      # R1 — one full match + determinism
python3 integrations/ddd/verify_round2.py      # R2 — the full content spine
python3 integrations/ddd/verify_round3.py      # R3 — ExploitHunter + refusal battery
python3 integrations/ddd/playtest_ddd.py       # LLM playtest (L-002 drive mode)
```

Supporting files:
- **`invariants.py`** — shared predicates (`inv_hash_present`, `inv_hp_bounds`,
  `inv_focus_bounds`, `inv_hand_cap`, `inv_card_conservation`, `inv_turn_monotonic`,
  `inv_no_error_on_legal`, `inv_legal_nonempty_while_ongoing`), imported by every
  `verify_round*.py` script and by `playtest_ddd.py`.
- **`ugt.config.yaml`** — drives action ids, observation mappings, and the `playtest`
  config block.

## Prerequisites

- **node ≥ 24** on `PATH` (the harness runs on node v24.x).
- The **DDD repo present at `/Users/vs7/Dev/Games/DDD`** with its dependencies
  installed so `@ddd/engine` resolves from the repo root.
- Overrides: `DDD_HARNESS_PATH` (harness entry) and `DDD_HARNESS_CWD` (working dir)
  env vars take precedence over the config.

## Folder hygiene

Nothing is archived here. All 12 tracked files (`HANDOFF.md`, `README.md`,
`RESULTS.md`, `invariants.py`, `playtest_ddd.py`, `smoke_ddd_adapter.py`,
`spike_ddd.py`, `strategy-guide.md`, `ugt.config.yaml`, `verify_round1.py`,
`verify_round2.py`, `verify_round3.py`) are load-bearing and current — this pass is a
**content currency fix** (correcting the stale playtest-tier status), not a
decluttering job.

## Where to go next

- **`HANDOFF.md`** — the resume-here doorway with full current state.
- **`RESULTS.md`** — the commit-traceable findings log (every finding, its pinning
  test, and its fix commit).
- No `archive/` directory exists for this integration — there is nothing superseded
  to move there.

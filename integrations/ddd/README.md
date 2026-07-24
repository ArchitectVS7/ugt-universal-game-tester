# DDD — a two-player deterministic dueling card game

> **FULL LADDER COMPLETE AND GREEN** as of the 2026-07-12 evening re-run vs DDD commit
> `0eb0df83` (zero open R3 findings). **LLM playtest tier wired 2026-07-21 (L-002/L-007)
> and extensively exercised through L-013 (2026-07-22)**: fixed-opponent matchup batches
> (gemma4:26b then Haiku 4.5) reproduce a Blitzblade-over-Swarm win-rate asymmetry that
> does not move with a stronger model — pointing away from "the LLM just plays Swarm
> badly" and toward the deck or the graveyard-recursion mechanic itself. Cause is still
> undetermined; see "LLM playtest" below. **LLM re-runs are PAUSED pending explicit user
> go** (L-011) — do not spend another balance batch without it.

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

## LLM playtest (wired 2026-07-21, exercised through L-013 2026-07-22)

A structured/legal-action playtest drive mode is built and validated end-to-end against
`DddHarnessAdapter`: a `playtest_game_with_adapter()` entry point in
`ugt/core/playtester.py`, driven here by `playtest_ddd.py` (single-run) and
`playtest_ddd_matchup.py` (fixed-opponent matchup mode, added L-012) +
`strategy-guide.md`. Full detail and corrections chain in `RESULTS.md` L-007..L-013;
condensed:

- **L-007** — tier wired; ollama run, 25 actions, 0 invariant violations.
- **L-008** — first multi-run batch (92.6% seat-0 win rate) — later found **CONFOUNDED**
  by seat/turn-order, not comparable to DDD's own T6.2 (36%).
- **L-009** — root-caused L-008 as **blind play**: 3 harness defects (no card identity in
  prompt, a god-view leak, unfilled targets) found and fixed before any further batch.
- **L-010** — seat-swapped pooled batch (Haiku 4.5): Blitzblade 89.8% win rate.
- **L-011** — root-caused L-010 as **rules-blind**: the adapter dropped public
  echo/chain state and the guide taught no triangle/stance rules; both fixed. A stance
  design recommendation was filed to the DDD repo. **LLM re-runs PAUSED pending explicit
  user go** — the pause is still in effect.
- **L-012** — a **fixed-opponent matchup** smoke test (LLM plays one seat vs. DDD's own
  tier1/2/3 AI, not self-play) reproduces the Blitzblade-over-Swarm asymmetry; cause
  (deck / pilot / mechanic) undetermined.
- **L-013** — Haiku 4.5 re-run of the same matchup design: Blitzblade's win rate improves
  with model strength (2W–4L → 3W–3L), **Swarm's does not move at all** (0/15 wins across
  both models) — shifts hypothesis weight away from pure pilot skill, still unresolved
  against `apps/probe`'s own GREEN parity gates. Tracked as DDD's own T6.2/T6.3, not a
  UGT-side item.

Run a single-seat smoke run with:

```bash
python3 integrations/ddd/playtest_ddd.py
```

Or the fixed-opponent matchup mode (see `RESULTS.md` L-012 before running — this is the
mode the PAUSED note above applies to):

```bash
python3 integrations/ddd/playtest_ddd_matchup.py
```

## How to run (full ladder, from the UGT repo root)

```bash
python3 integrations/ddd/spike_ddd.py          # 10/10 raw-protocol harness checks
python3 integrations/ddd/smoke_ddd_adapter.py  #  5/5 through the BaseAdapter contract
python3 integrations/ddd/verify_round1.py      # R1 — one full match + determinism
python3 integrations/ddd/verify_round2.py      # R2 — the full content spine
python3 integrations/ddd/verify_round3.py      # R3 — ExploitHunter + refusal battery
python3 integrations/ddd/playtest_ddd.py       # LLM playtest, single-run (L-002 drive mode)
python3 integrations/ddd/playtest_ddd_matchup.py --runs N  # fixed-opponent matchup batch (L-012)
```

Supporting files:
- **`invariants.py`** — shared predicates (`inv_hash_present`, `inv_hp_bounds`,
  `inv_focus_bounds`, `inv_hand_cap`, `inv_card_conservation`, `inv_turn_monotonic`,
  `inv_no_error_on_legal`, `inv_legal_nonempty_while_ongoing`), imported by every
  `verify_round*.py` script and by `playtest_ddd*.py`.
- **`ugt.config.yaml`** — drives action ids, observation mappings, and the `playtest`
  config block.
- **`analyze_playtest_batch.py`** — win-rate/CI analyzer over a batch's pooled JSON
  artifacts (added during the L-008..L-010 balance-batch work).
- **`archive_batch.py`** — files a completed batch's raw artifacts under
  `results/batch-<label>/` (added L-013, after an early run clobbered a same-named
  artifact from a different seat/model cell).

## Prerequisites

- **node ≥ 24** on `PATH` (the harness runs on node v24.x).
- The **DDD repo present at `/Users/vs7/Dev/Games/DDD`** with its dependencies
  installed so `@ddd/engine` resolves from the repo root.
- Overrides: `DDD_HARNESS_PATH` (harness entry) and `DDD_HARNESS_CWD` (working dir)
  env vars take precedence over the config.

## Folder hygiene

Nothing is archived here. Every tracked file (`HANDOFF.md`, `README.md`, `RESULTS.md`,
`invariants.py`, `playtest_ddd.py`, `playtest_ddd_matchup.py`, `analyze_playtest_batch.py`,
`archive_batch.py`, `smoke_ddd_adapter.py`, `spike_ddd.py`, `strategy-guide.md`,
`ugt.config.yaml`, `verify_round1.py`, `verify_round2.py`, `verify_round3.py`) is
load-bearing and current — there is nothing superseded to move out of this folder.

## Where to go next

- **`HANDOFF.md`** — the resume-here doorway with full current state.
- **`RESULTS.md`** — the commit-traceable findings log (every finding, its pinning
  test, and its fix commit).
- No `archive/` directory exists for this integration — there is nothing superseded
  to move there.

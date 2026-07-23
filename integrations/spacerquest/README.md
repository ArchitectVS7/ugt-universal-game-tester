# SpacerQuest (Rimward redesign) — UGT integration

**Status: CURRENT, ACTIVE integration.**

> **Disambiguation — read this first.** This folder (`integrations/spacerquest/`) is **Rimward** — a
> brand-new, unrelated restart of SpacerQuest built against a new design. There used to be a second folder,
> `integrations/spacerquest_old/`, for a **different, retired game** (the 1991-BBS-style Museum Edition) —
> it was **deleted from this repo on 2026-07-21**, entirely superseded by this Rimward rebuild. Its history
> (trial-ladder results, the Gate-C balance verdict, the `sim_bridge.ts` cautionary tale) lives on in
> `Dev/PLAN-FORWARD-spacerquest.md` and `Dev/UGT-TRACK-RECORD.md`, not as a live integration folder.

## What this is

Rimward is a space-trader day-loop roguelite: dice-driven day phases (travel / trade / explore /
shipyard / crew / storylets / combat), a Merchant Guild debt marker driving pressure, and "Tour One" as
the first campaign era. It has no relation to the old Museum Edition's rank ladder or Socket.IO server.

## Transport / adapter

`ugt.config.yaml` declares `engine.type: simulation`. UGT's generic `SubprocessAdapter` spawns
`rimward_gym_bridge.py` (the config's `engine.entry`), which speaks Gym-style
`{"command":"step","action_id":N}` on its own stdin/stdout. The bridge in turn spawns and speaks to the
game's own compiled `node protocol-stdio.js` binary over the **T-1003 stdio protocol** — a line-delimited
JSON day-loop wire (`new-game` / `start-day` / `legal-actions` / `apply-action` / `end-day`).

The bridge is **transport-only** — it contains no game logic. All 20 action ids are STRUCTURAL: each one
selects among the `LegalActionSpec`s that the engine's own `legal-actions` enumerator advertises, so an
`ActionBlocked` response from a bridge-formed action is a real parity defect, not a bridge bug.

A separate script, `smoke_spacerquest_adapter.py`, drives the raw Rimward wire directly with no Gym layer
in between, as an independent proof that the protocol itself round-trips correctly.

## Ladder-status caveat

This integration predates the newer per-game trial-ladder script convention used by `ddd`,
`nexus-dominion`, and `pond` — there are **no `verify_round1.py` / `verify_round2.py` / `verify_round3.py`
files here**. Instead it was validated by running UGT's four classic CLI phases directly
(`smoke-test` → `verify` → `train` → `evaluate`), all recorded on 2026-07-17 (T-1604 campaign) in the
inline results table in `HANDOFF.md`:

| Phase | Result |
| --- | --- |
| `ugt smoke-test` | PASS |
| `ugt verify` (Phase 1) | **9/9 features PASSED (100%)** against `feature-map.yaml` — `sign_contract`, `buy_fuel`, `travel`, `pay_debt`, `end_day`, `forfeit_cargo`/anti-soft-lock, `explore`, wait-is-inert, `parity_no_blocked_from_legal` |
| `ugt train` (Phase 2a) | PPO, 32,768 timesteps at ~600 fps over the real wire |
| `ugt evaluate` (Phase 2b) | **VALID** — trained mean **+124.0** vs random **−8.4**, entropy 0.76, no policy collapse |

## Headline findings

1. **71,107 total actions** logged across all phases with **0 ActionBlocked-from-legal** and
   **0 protocol errors** — the structural parity guarantee held at volume.
2. A first evaluation attempt (full 20-action table, 4k→32k steps) **DID collapse** to all-`wait` and was
   correctly flagged **INVALID** by UGT's own collapse detector — kept on record as evidence the detector
   works, not swept aside. The fix was adding `training.action_subset` (Gate-1: restrict the RL policy to
   the trader macro-vocabulary — `travel_contract` / `buy_fuel_max` / `sign_contract` / `pay_debt` /
   `end_day`), after which the evaluation became valid and decisively above random.

No other game-side defects have been found yet.

## What's not done

- **LLM playtest tier: NOT run.** There is no playtest script or `strategy-guide.md` in this folder yet —
  this is an open gap, not a completed tier.
- **No `RESULTS.md` exists yet.** Findings content currently lives inline in `HANDOFF.md`'s T-1604 table
  rather than in a dedicated findings log — look there, not for a separate file.

## How to run

See `HANDOFF.md` for the full run recipe (building the protocol bin, then `smoke-test` / `verify` /
`train` / `evaluate` against `ugt.config.yaml` / `feature-map.yaml`), plus:

```sh
python3 integrations/spacerquest/smoke_spacerquest_adapter.py   # independent raw-wire check
```

## Where to go next

- **`HANDOFF.md`** — the resume-here doorway: full run recipe, protocol details, and the T-1604 results
  table.
- **`RESULTS.md`** — does not exist yet (see above); until it does, findings live in `HANDOFF.md`.
- **`archive/`** — does not exist yet; there is no historical material to move out of this folder (all
  tracked files here are current per the last repo survey).

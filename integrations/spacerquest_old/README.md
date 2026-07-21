# SpacerQuest (Museum Edition) — ARCHIVED, ON HOLD since 2026-07-09

> **DISAMBIGUATION — read this first.** This folder is the retired, ON-HOLD original
> SpacerQuest integration (a 1991-BBS-style text/ANSI-terminal game). It is **unrelated in
> content** to `integrations/spacerquest/` (a brand-new restart against a from-scratch
> redesign called **Rimward**), despite the near-identical directory name. **Do not resume
> this integration without first checking whether `integrations/spacerquest/` (Rimward) has
> superseded SpacerQuest entirely.**

## What the game was

SpacerQuest (the museum-edition original) is a 1991-BBS-style text/ANSI-terminal space
trader: cargo hauling, forced combat encounters, ship upgrades, and rank progression up to
a 10,000-score "Conqueror" win. It has no HANDOFF.md or RESULTS.md in this folder (none was
ever committed for this integration), so this README is the only place inside the folder
that tells its history — read the two eras below before touching anything here.

## Two distinct eras lived in this one folder

### Era 1 — "Gate-1" (~2026-07-03/04): the discredited simulation bridge

`engine.type: simulation`, driven via a headless Node/TS `sim_bridge.ts` subprocess that
reimplemented game logic instead of driving the real game. This is the literal cautionary
tale cited in the root `CLAUDE.md` ("the tester must drive the real running game, never a
re-implementation of it") — the bridge had no combat and broken upgrades, so every RL agent
trained against it learned the wrong game.

An RL train/evaluate campaign was run against this bridge across 5 reward profiles
(trader / explorer / warrior / balanced / speedrun, via PPO), and was later demoted
project-wide after a well-documented collapse (see root `CLAUDE.md` and
`Dev/PLAN-FORWARD-spacerquest.md` for the full root-cause writeup).

The 16 one-off `*.log` / `*.status` / `*.out` files produced by that campaign have been
moved to `integrations/spacerquest_old/archive/` as part of this cleanup pass — they were
raw run outputs, not documentation. Look there for the historical logs
(`all5_*`, `gate1_*`, `gate1b_*`, `gate1c_*`).

### Era 2 — "Phase 0-2 real-server pivot" (~2026-07-05/06): the valid, current-methodology approach

`engine.type: real_server`, driven via `RealClientAdapter` (Socket.IO for auth/screens/combat
+ HTTP for navigation/structured state) against the **live** `spacerquest-web` server. This
is the correct approach per current UGT methodology.

Ladder-equivalent status, reconstructed from `Dev/PLAN-FORWARD-spacerquest.md` (the durable
full history, see below) and the scripts' own docstrings, since no `RESULTS.md` was ever
committed for this era either:

- `spike_realclient.py` — 7/7 checks passed.
- `smoke_realclient_adapter.py` + `verify_dod.py` (Phase-0 Definition of Done) — built and
  passing.
- `run_exploit_hunter.py` (Phase-1 robustness tier) — built and run live.
- `run_llm_playtest.py` (Phase-2 LLM balance tier) — notable as **the only UGT game
  integration where the LLM playtest tier actually completed a run**. It drove a "Gate-C
  balance verdict" (per root `CLAUDE.md`): 7 findings fixed-and-reverified-closed by
  2026-07-06, and 2 further findings filed whose resolution status at hold-time is not
  captured anywhere in this folder.

## Config disambiguation (important)

- `ugt.config.yaml` — the **retired** sim-bridge/simulation-engine config (Era 1), kept only
  for history. `ugt.realserver.config.yaml`'s own header comment calls it exactly that.
- `ugt.realserver.config.yaml` — the **actually-used, operative** config for the real_server
  path (exploit-hunter + LLM playtest, Era 2).

Do not try to run `ugt.config.yaml` expecting it to hit the live server — it won't.

## Where the full history lives

The durable full narrative — the complete SpacerQuest-era plan and history, verbatim from
the former root `PLAN-FORWARD.md` — lives in **`Dev/PLAN-FORWARD-spacerquest.md`**. Read
that file for the complete story; this README only summarizes it.

## How to run (Era 2, the valid path, if ever resumed)

```
spike_realclient.py -> smoke_realclient_adapter.py -> verify_dod.py -> run_exploit_hunter.py -> run_llm_playtest.py
```

using `ugt.realserver.config.yaml` and `strategy-guide.md`.

## Files present but not run (retired Era 1 artifacts, kept in place)

These remain in this folder (this cleanup pass only moves stray `.md`/`.log`/`.status`/`.out`
files, not `.ts`/`.json`/`.sh` files), but are retired/historical, not the live path:

- `sim_bridge.ts` — the discredited reimplementation bridge, root `CLAUDE.md`'s cautionary
  tale, superseded by `RealClientAdapter`; kept in place, not run.
- `package.json`, `package-lock.json` — npm manifest for `sim_bridge.ts`; retired with it.
- `run-all5.sh`, `run-eval.sh` — Gate-1 campaign launch scripts; retired with the bridge.

## Other references

- No `HANDOFF.md` or `RESULTS.md` exist for this integration (unusual versus other
  integrations in this repo) — this README is the closest equivalent doorway/history for
  now.
- `archive/` — the 16 moved one-off `*.log`/`*.status`/`*.out` files from the Era 1 RL
  campaign; raw historical run output, not documentation.
- `Dev/PLAN-FORWARD-spacerquest.md` — the full, durable SpacerQuest-era plan/history.

# Nexus Dominion integration

UGT trial for **Nexus Dominion**, a single-player 4X space-empire "digital
boardgame" (Tauri 2 + React 19, LCARS UI, pure-TS deterministic engine). The
player competes against 99 bot empires across 250 systems in 10 sectors, with
a 17-phase cycle pipeline driving each turn. There is no win/loss terminal
state by design — episodes end by cycle cap, and 10 achievement milestones
exist in place of endings.

## Status

**FULL LADDER GREEN** as of 2026-07-16 (game commit `1851ddd`):
**spike 11/11 · smoke 6/6 · R1 12/12 · R2 17/17 · R3 43/43**, zero R3
findings, same-seed replay byte-identical. This was game #6 in the UGT
portfolio.

**LLM playtest tier newly wired and validated 2026-07-21** (commit `557eea5`,
"L-003") — this postdates the 2026-07-16 ladder docs. `HANDOFF.md` and
`RESULTS.md` still carry the older "credit-gated, pending" line for the
playtest tier; that line is now out of date and superseded by the section
below.

**Start with `HANDOFF.md`** for the full resume-here state. `RESULTS.md` is
the commit-traceable findings log. Historical material (the pre-build
feasibility study) lives in `archive/`.

## Transport / adapter

Engine-first JSON-lines subprocess harness — the same pattern used for DDD.
`NexusDominionHarnessAdapter` (`ugt/adapters/nexus_dominion_harness.py`)
spawns the game's own `ugt-harness.mjs` subprocess and drives the real engine
headless in Node via `processCycle`. There is no browser and no live server
involved; the harness code itself lives in the nexus-dominion repo, not in
UGT.

## Files

| File | Role |
|---|---|
| `HANDOFF.md` | resume-here: status, run recipe, key facts, open items |
| `RESULTS.md` | findings log (10 defects fixed upstream) + characterizations |
| `ugt.config.yaml` | engine + action vocabulary (lockstep with the adapter), now incl. a `playtest:` block |
| `strategy-guide.md` | LLM playtester strategy guide (added with L-003) |
| `invariants.py` | flat per-step predicates + full-state cross-ref checks |
| `spike_nexus_dominion.py` | raw JSON-lines protocol contract (11 checks) |
| `smoke_nexus_dominion_adapter.py` | same path via `BaseAdapter` (6 checks) |
| `verify_round1.py` | playability gate — one campaign + invariants + save/load (12) |
| `verify_round2.py` | full spine — all order types to real outcomes (17) |
| `verify_round3.py` | exploit-hunter + refusal/garbage battery + replay (43) |
| `playtest_nexus_dominion.py` | LLM playtester drive script (L-003) |
| `archive/FEASIBILITY.md` | pre-build go/no-go study, superseded now the trial is complete |

The adapter (`ugt/adapters/nexus_dominion_harness.py`) and the game-side
harness (`nexus-dominion/src/harness/`, `nexus-dominion/harness/`) live in
their respective repos.

## Run the ladder (from the UGT repo root; node >=24)

```bash
for s in spike_nexus_dominion smoke_nexus_dominion_adapter \
         verify_round1 verify_round2 verify_round3; do
  python3 integrations/nexus-dominion/$s.py || break
done
```

No server to start — the adapter spawns the harness subprocess. Exit 0 +
`… MET — N/N` per round means the gate passed.

## Run the LLM playtester

```bash
python3 integrations/nexus-dominion/playtest_nexus_dominion.py
```

Drives the game via a legal-action selection mode using a
`PlaytestNexusDominionAdapter` (a pure-relay subclass of the harness adapter),
plus the `playtest:` block added to `ugt.config.yaml` and the new
`strategy-guide.md`. Validated live with `--provider ollama`: 22 actions
taken, 18 state-delta steps, 0 invariant violations.

## Headline findings

10 defects found and fixed upstream, all pinned to commits, game suite
1109 -> 1137 green (full detail in `RESULTS.md`):

- **ND-3 (CRITICAL)** — `createNewCampaign` left `cosmicOrder` tiers empty, so
  NO empire resolved anything for the first 10 cycles. Near-certain
  contributor to the game's failed U-110 human UAT.
- **ND-2** — built units were never attached to a fleet; the player's whole
  military was an invisible ghost roster.
- **ND-P2** — syndicate/covert state was never constructed in real campaigns,
  dead-ending 3 order types and 2 achievements.
- **ND-5** — the atomicity clone silently dropped wormhole/black-register
  purchases and shared mutable slot objects across cycle snapshots.
- **ND-7** — player covert ops were a divergent stub with zero effect.
- **ND-8** — a garbage item/op id crashed the whole cycle commit.
- **ND-P1 (app-side)** — the real App ranked Reckonings on an always-empty
  power-history window.

Recorded-not-gated design characterizations, parked for a deferred balance
pass: propose-pact auto-accepts, transit time is a flat 10 cycles ignoring
distance/wormholes, colonisation is instant, and achievements are ~100-cycle
milestones (unreachable in short campaigns).

## Open / next

U-110 human UAT retest remains on the **game's** critical path (unreadable
star map, no onboarding, no turn-structure indication — visual/UX findings a
subprocess-engine trial can't see on its own; ND-3 was the one reachable
symptom from this tier, and it's now fixed). If the game churns further under
remediation, re-pin the trial to a new commit and re-run the ladder, as was
done for DDD.

# Nexus Dominion — UGT integration HANDOFF (resume here)

**Status (2026-07-16): full ladder GREEN — spike 11/11 · smoke 6/6 · R1 12/12 ·
R2 17/17 · R3 43/43.** 10 defects found + fixed upstream (see `RESULTS.md`).
Game suite 1137 green, tsc clean, build green.

## What this is

Game #6. An **engine-first JSON-lines subprocess** trial (the DDD pattern), not
a browser trial — Nexus Dominion's engine is pure TS with a single atomic
entrypoint (`processCycle`) and no `window` hooks, so the harness drives the
real engine headless in Node.

- **Game-side harness** (in the nexus-dominion repo, committed there):
  - `src/harness/harness-core.ts` — pure dispatch core (ops:
    create/commit/state/save/load), typechecked + vitest-covered
    (`harness-core.test.ts`). Zero game logic; player orders pass to
    `processCycle` verbatim. `stateHash` normalizes campaign id/timestamps.
  - `harness/ugt-harness.mjs` + `ts-resolve-hook.mjs` — bare-node (>=24) stdio
    shell. `npm run ugt-harness`.
- **UGT-side**:
  - `ugt/adapters/nexus_dominion_harness.py` — transport-only adapter,
    20-action vocabulary composing ORDERS from structural state reads.
  - this directory — `ugt.config.yaml`, `invariants.py`, and the ladder
    scripts.

## Run it (from the UGT repo root; node >=24, nexus-dominion deps installed)

```bash
python3 integrations/nexus-dominion/spike_nexus_dominion.py
python3 integrations/nexus-dominion/smoke_nexus_dominion_adapter.py
python3 integrations/nexus-dominion/verify_round1.py
python3 integrations/nexus-dominion/verify_round2.py
python3 integrations/nexus-dominion/verify_round3.py   # [base_seed] [episodes] [steps]
```

No server to start — the adapter spawns the harness subprocess itself. The
harness path defaults to `/Users/vs7/Dev/Games/nexus-dominion/harness/ugt-harness.mjs`;
override with `NEXUS_DOMINION_HARNESS_PATH` / `NEXUS_DOMINION_HARNESS_CWD`.

## Key facts for the next session

- **No terminal state.** Episodes end by `max_cycles` truncation; there is no
  win/loss. Achievements are milestones (lowest threshold ~100 cycles).
- **Silent-skip order contract.** A bad player order is dropped and the cycle
  still commits. R3's whole garbage battery rests on this; ND-1/ND-8 were
  violations of it (orders that threw and aborted the commit).
- **Two caller-owned accumulators.** `powerHistory` (push each empire's score
  after every committed cycle) and `botAccumulated` are threaded by the caller,
  not the engine. The harness owns both and carries them through save/load. This
  is exactly where ND-P1 lived (the App got it wrong).
- **Determinism.** mulberry32 re-derived per cycle from `seed + currentCycle`;
  the only nondeterministic fields are `campaign.id`/`createdAt`/`lastSavedAt`,
  which `stateHash` normalizes out. Same-seed replay is byte-identical.
- **Full PRD scale is cheap:** ~6–8 ms/cycle raw at 100 empires.

## Open / next

1. **LLM balance playtester tier** (credit-gated, pending — same gap as the
   other engine-first integrations). Would drive the `press_key`-less structured
   order interface; a JSON-order drive mode already exists (this adapter is it).
2. **Design-pass items** the trial characterized but did not gate (see
   `RESULTS.md`): propose-pact auto-accept, flat transit time, instant
   colonisation, idle rank-climb (U-110 finding 4 residual). These belong to the
   game's deferred M4.1 balance pass.
3. **U-110 human retest** stays on the *game's* critical path — the engine trial
   cannot sign it off (its findings are visual/UX). ND-3 was the one U-110
   symptom reachable through the engine and is fixed.
4. If the game churns (M1.5 → U-110 remediation), **pin the trial to a commit
   and re-run** the ladder on movement, as with DDD.

## Findings quick index (all fixed upstream, pinned)

ND-3 inert-first-10-cycles (crit) · ND-2 orphan units (maj) · ND-2b unit-id
collision · ND-1 move-fleet aborts cycle · ND-P2 syndicate/covert never
constructed (maj) · ND-5 clone drops wormholes/purchases + shares slots (maj) ·
ND-6 research gates unenforced · ND-7 player covert ops effectless (maj) ·
ND-8 unknown item/op crashes cycle · ND-P1 App ranks Reckonings on empty
history (maj). Commits: `1f0bff3`, `c05466e`, `271690a`, `1851ddd`.

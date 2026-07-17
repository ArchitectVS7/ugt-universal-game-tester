# Nexus Dominion — UGT Trial Results (findings log)

Game #6. Engine-first JSON-lines subprocess trial (the DDD pattern). All rounds
run at **full PRD scale (250 systems / 10 sectors / 100 empires)** unless noted.
The game has no win/loss terminal state by design, so episodes end by cycle cap.

**Ladder status (against nexus-dominion `1851ddd`):**

| Round | Result | What it proves |
|---|---|---|
| Spike | **11/11** | raw create/commit/state/save/load contract; atomic aborts; same-seed determinism (initial + scripted + save/load/continue) |
| Smoke | **6/6** | same path through `NexusDominionHarnessAdapter` (reset/step/close, 20-action vocab, truncation) |
| R1 playability | **12/12** | core loop playable through the wire; invariants + state integrity over 25 cycles; Reckoning cadence; save/load exact |
| R2 full spine | **17/17** | all 15 order types to real observed outcomes; combat/syndicate/covert/wormhole/pact/installation/research; achievement-ledger consistency |
| R3 exploit-hunter | **43/43** | full 20-order vocab × 240 cycles, zero findings; protocol + garbage battery; full-state integrity every step; same-seed replay byte-identical |

nexus-dominion suite through the trial: **1109 → 1137 green**, tsc clean, build
green at every commit.

---

## Findings — 10 defects fixed upstream, all pinned

Traceable to nexus-dominion commits. Every fix ships with a pinning test; the
pre-existing 1,109-test suite missed all of these because the engine tests
hand-build `GameState` (with a populated `cosmicOrder`, `syndicate`, `covert`,
etc.) — the trial is the first thing to drive `createNewCampaign → processCycle`
end to end and to send bad input over the serialization boundary.

### ND-3 (critical) — the game was inert for its first 10 cycles
`createNewCampaign` left `time.cosmicOrder.tiers` **empty**. `getResolutionOrder`
iterates tier members, so with empty tiers **no empire resolved anything** — no
player orders, no bot actions, no economy — until the first Nexus Reckoning at
cycle 10 populated the tiers. A valid claim at cycle 1 committed with zero
effect; galaxy-wide income was 0 until cycle 11. Almost certainly a contributor
to the **U-110 human UAT failure** ("60 empty COMMIT clicks", "nothing indicates
the turn structure"). Fix: seed the Cosmic Order at creation via
`computeCosmicOrder(empires)`. — `1f0bff3`

### ND-2 (major) — built units never joined a fleet
Completed builds entered `state.units` but **no fleet ever received them**.
Maintenance, combat, and movement all resolve unit ownership *through* fleets, so
every unit ever built was invisible to every downstream system (77 orphan units
by cycle 25 in a 100-empire campaign; the player's whole military was a ghost
roster). Fix: attach completed units to a fleet at the build system (else any
owned fleet, else a deterministic garrison fleet). — `1f0bff3`

### ND-2b — same-cycle same-type unit id collision
Two fighters completing on the same cycle shared a unit-map key and silently
overwrote each other. Ids now carry a completion index. — `1f0bff3`

### ND-1 — a malformed `move-fleet` order aborted the whole cycle
Missing `details` destructured `undefined`, threw, and aborted the entire cycle
commit — while every *other* malformed order was silently skipped. Now skips like
the rest. — `1f0bff3`

### ND-P2 (major) — syndicate & covert never existed in real campaigns
Nothing ever constructed `state.syndicate` or `state.covert`; every reader is
guarded (`if (state.syndicate)` / `if (state.covert)`), so **all three
syndicate/covert orders and both cycle phases were permanently dead** in real
play, and the shadow-throne / stealth-sovereign achievements were unreachable.
Fix: `createNewCampaign` seeds the Syndicate as an empty background institution
(SYNDICATE-SYSTEM §2) and a per-empire covert state. — `c05466e`

### ND-5 (major) — `deepCloneState` dropped/shared state
The per-cycle atomicity clone silently **dropped `galaxy.wormholes` and
`ownedBlackRegisterItems`** (a built wormhole vanished the next cycle, leaving
its adjacency edges as permanent free links and allowing infinite re-purchase;
black-register purchases evaporated after one cycle), and **shared slot objects**
between clones (an installation completing in cycle N mutated the cycle N-1
snapshot — a Tier-1 atomicity hazard). All three fixed in the clone. — `c05466e`

### ND-6 — research tier gates declared but never enforced
`DOCTRINE_TIER` (1) and `SPECIALIZATION_TIER` (3) existed as constants but were
never checked — a tier-0 empire could pick a doctrine and a tier-2 empire a
specialization (confirmed live at tier 2 over the wire). Both gates now enforced.
— `c05466e`

### ND-7 (major) — the player's covert ops were a divergent, effectless copy
`launch-covert-op` was a **second implementation**: a flat 200-agent cost, a
private 70% dice roll, and a success that applied **no effect at all**
(`// apply effects logic...` was a comment). It now routes through
`queueCovertOp → processCovertCycle` (the same pipeline the bots use), gaining
op-specific costs, the real dual-roll with detection modifiers, reputation
consequences, and **actual effect application** — steal-credits now steals
credits (pinned by a differential test vs a same-seed pass baseline). — `271690a`

### ND-8 — unknown black-register item / covert op type crashed the cycle
Found by R3's garbage-order battery: an unknown `itemId` /
`opType` dereferenced an undefined registry entry (`def.minRank` /
`def.agentCost`), threw, and aborted the whole cycle commit (the ND-1 class).
Both validation lookups now return not-purchasable / not-queueable. — `1851ddd`

### ND-P1 (App-side, major) — Reckonings ranked on an empty history
`processCycle` only *reads* `powerHistory` (the caller maintains it — the
`integration.test.ts` contract). `App.tsx` instead re-pointed its ref at
`result.state.powerHistory`, which **nothing ever fills**, and never pushed
scores — so the real app ranked every Nexus Reckoning on an **empty** rolling
window (falling back to instantaneous `powerScore`) and dropped history across
save/load. The App now pushes each empire's score per committed cycle and
carries both accumulators inside saved state. Pinned by an App jsdom test.
— `271690a`

---

## Characterizations (recorded, not gated)

These are design facts the trial surfaced and *respects* rather than failing on —
they belong to the deferred balance pass, not the robustness ladder:

- **propose-pact auto-accepts.** `propose-pact` calls `proposePact → acceptPact`
  in the same commit with no bot-consent step — pacts form unilaterally.
- **`calculateTransitTime` is a flat 10 cycles**, ignoring distance and
  wormholes (a known deviation, acknowledged in CODING-PLAN). Fleets still
  arrive; the timing is just uniform.
- **Instant colonisation** — claim-system resolves within the committed cycle
  rather than taking N cycles (acknowledged deviation).
- **Achievements are ~100-cycle milestones.** The lowest threshold
  (market-overlord, 12 systems) is out of reach in a 30-cycle campaign at PRD
  scale; zero achievements in early game is by design, not a bug.
- **Perf, first full-scale measurement:** ~6–8 ms per cycle raw at 100 empires,
  ~22 ms through the adapter incl. full-state refresh. The PRD's 1 s release
  target holds with ~100× headroom. (Material for the still-TODO T-401.)

## What this trial does NOT cover

An engine-first trial **cannot sign off the failed U-110 UAT** — its findings
(unreadable star map, no onboarding, no turn-structure indication) are
visual/UX and invisible to a subprocess harness. ND-3 is the one U-110 symptom
this trial could reach through the engine (empty commits genuinely did nothing);
the rest remain on the human retest's critical path. What the trial delivers
instead is the PRD's own specified-but-unbuilt "Simulation" test tier
(`docs/prd.md:564`) and the first full-scale per-cycle performance measurement.

The **LLM balance playtester** tier (does the galaxy produce good *games*?) is
not run here — it is credit-gated and pending, as for the other engine-first
integrations.

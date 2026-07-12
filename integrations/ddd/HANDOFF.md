# DDD × UGT — resume here

**Status (2026-07-12): the ladder is COMPLETE and green.**
`spike 10/10 · smoke 5/5 · R1 11/11 · R2 26/26 · R3 31/31` — zero open findings.

- What it does + how to run it: **[README.md](README.md)**
- What was found, fixed and pinned: **[RESULTS.md](RESULTS.md)**
- Game: `/Users/vs7/Dev/Games/DDD`, branch `feat/d16-type-triangle`
- UGT commits `00aaa33` (re-baseline + R2), `9ff38b1` (R3) · DDD commit `61125b64` (both fixes)

## Re-run everything (no server to start — the adapter spawns the harness)

```bash
# from the UGT repo root; needs node >= 24 and DDD deps installed
for s in spike_ddd smoke_ddd_adapter verify_round1 verify_round2 verify_round3; do
  python3 integrations/ddd/$s.py || break
done
```

## The one thing to know before touching this

**`engine.enabledWaves` must name all three keys** (`stanceEcho`, `chainsPredictions`,
`typeTriangle`). A missing key is **not a default** — the engine reads it as
`undefined` → falsy, so you silently play a *different game*. That is exactly how
D16's type triangle sat switched off through the entire (now superseded) 2026-07-11
R1 run. The adapter now refuses an under-specified wave set, and DDD's `create` now
refuses one too.

## What is NOT done

1. **LLM balance-playtest tier** — the tier that judges *"is this a good game?"* rather
   than *"does it work?"*. This is DDD's **T8.2**, credit-gated, and the natural home
   for the focus-economy finding (D-C1). `DddHarnessAdapter` has no
   `press_key`/`get_terminal_text` — the harness is structured JSON, not a terminal —
   so a playtester would drive `legal`/`act` directly rather than a screen.
2. **DDD T6.3's conformance audit #2** (fresh read-only rulebook-vs-engine pass). The
   R1 half of that task is met; the audit half is untouched.
3. **DDD T6.0(c)** — `@ddd/ai` and `@ddd/sim` still never call `legalTargets`, so the
   AI ladder and balance sim keep playing 7 Swarm cards blank. Filed in DDD's
   `TASKS.md`; not fixed here because it moves published balance numbers.

## Open findings against DDD

None blocking. One recorded characterization: **the Focus economy never binds**
(RESULTS.md D-C1) — turn-1 focus already covers the most expensive card in the pack,
so cost is not a decision. That is DDD's own open **T6.5**.

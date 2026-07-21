# Warzones × UGT — resume here

**Status: the trial ladder is COMPLETE and green** — `R1 23/23 · R2 12/12 · R3 6/6`
(2026-07-07, `ExploitHunter`'s first browser-game outing). **L-001 audit done
(2026-07-21):** the three ladder scripts were swept for the DDD/Pond vacuous-check class;
one tester defect found and fixed — the R3 same-seed determinism check was vacuous on an
empty trajectory (`same_len and divergence is None` is `True` for empty/empty). Fixed via
the extracted `trajectories_match` predicate, pinned by a synthetic negative-case selftest.
No game-side change; live MET counts unchanged.

- What it does + how to run it: **[README.md](README.md)**
- What was found, fixed and the full L-001 per-`ck` disposition: **[RESULTS.md](RESULTS.md)**
- Game: `/Users/vs7/Dev/Games/warzones/warzones-game`, branch `main` (`5d3f743` at audit)
- Driver: `PlaywrightAdapter` (+ `SeededWarzonesAdapter`) → game's `src/ugt-hooks.ts`

## Re-run everything

```bash
# 1. Start the real game (Vite dev server on :3000)
cd ../warzones/warzones-game && npm run dev
# 2. Verify the LISTEN PID on :3000 is YOUR vite (stale-server lesson):
lsof -nP -iTCP:3000 -sTCP:LISTEN
# 3. From the UGT repo root:
python3 integrations/warzones/verify_round1.py        # 23/23 one turn cycle
python3 integrations/warzones/verify_round2.py        # 12/12 economy + combat + invariants
python3 integrations/warzones/verify_round10.py       # 6/6 ExploitHunter R3 (misnamed "round10")

# Regression artifact — no server needed:
python3 integrations/warzones/determinism_selftest.py # 6/6 vacuous-guard negative cases
```

## The one thing to know before touching this

R3 lives in **`verify_round10.py`** (the "ten-turn" gate), not `verify_round3.py`. The
same-seed determinism check now routes through `trajectories_match`, which **fails on an
empty trajectory** — do not "simplify" it back to `len(a)==len(b) and next(...) is None`;
that is the vacuous form L-001 removed (pinned against by `determinism_selftest.py`).

## Open findings against warzones

- **WZ-R3 (major, OPEN):** `ContractScene` never launched — scoped out of v0.8. Everything
  else (WZ-R1/R2/R4/R5/R6/R7/R8/R9) is fixed, verified live, and pinned in the game's suite.

## What is NOT done

- **LLM balance-playtest tier** (`ugt playtest`) — the "is it a good game?" tier — has not
  been run against warzones (credit-gated).

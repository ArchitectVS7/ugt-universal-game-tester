# Tarot-war × UGT — resume here

**Status: the trial ladder is COMPLETE and green** — `R1 22/22 · R2 12/12 · R3 7/7`
(2026-07-07, all 8 findings closed). **L-001 audit done (2026-07-21):** the three ladder
scripts were swept for the DDD/Pond vacuous-check class; one tester defect found and fixed
— the R3 same-seed determinism check was vacuous on an empty trajectory
(`same_len and divergence is None` is `True` for empty/empty). Fixed via the extracted
`trajectories_match` predicate, pinned by a synthetic negative-case selftest. No game-side
change; live MET counts unchanged. (One recorded, deliberately-unchanged R1 weakening — the
`conserved` dead variable at `verify_round1.py:221`; see RESULTS.md.)

- What it does + how to run it: **[README.md](README.md)**
- What was found, fixed and the full L-001 per-`ck` disposition: **[RESULTS.md](RESULTS.md)**
- Game: `/Users/vs7/Dev/Games/tarot-war`, branch `main` (`61f1c1a` at audit)
- Driver: `PlaywrightAdapter` (+ `SeededTarotAdapter`) → game's `src/ugt-hooks.ts` (transport only)

## Re-run everything

```bash
# 1. Start the real game (Vite dev server on :5173)
cd ../tarot-war && npm run dev
# 2. Verify the LISTEN PID on :5173 is YOUR vite (stale-server lesson):
lsof -nP -iTCP:5173 -sTCP:LISTEN
# 3. From the UGT repo root:
python3 integrations/tarot-war/verify_round1.py       # 22/22 one full playable loop
python3 integrations/tarot-war/verify_round2.py       # 12/12 every mode to completion
python3 integrations/tarot-war/verify_round3.py       # 7/7 ExploitHunter R3

# Regression artifact — no server needed:
python3 integrations/tarot-war/determinism_selftest.py # 6/6 vacuous-guard negative cases
```

## The one thing to know before touching this

The R3 same-seed determinism check now routes through `trajectories_match`, which **fails
on an empty trajectory** — do not "simplify" it back to `len(a)==len(b) and next(...) is
None`; that is the vacuous form L-001 removed (pinned against by `determinism_selftest.py`).
R2's `verify_round2.py:375` (`len(run1) >= 10 and run1 == run2`) is the same discipline and
is the in-repo exemplar.

## Open findings against tarot-war

None. All 8 findings (TW-R1…R8) are fixed, verified live, and pinned in the game's own
suite (448 tests green). One design observation recorded (classic winner can hold the lower
score) — a balance note for the LLM-playtest tier, not a defect.

## What is NOT done

- **LLM balance-playtest tier** (`ugt playtest`) — the "is it a good game?" tier — has not
  been run against tarot-war (credit-gated).

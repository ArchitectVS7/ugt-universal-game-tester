# DDD × UGT — resume here

**Status (2026-07-21): the ladder is COMPLETE and green, and the LLM playtest tier
(T8.2) is now wired + run.** `spike 10/10 · smoke 5/5 · R1 11/11 · R2 26/26 · R3
32/32` — zero open ladder findings. `playtest_ddd.py` (ollama/gemma4:26b, 40 actions,
legal-action drive mode): PLAYTEST MET, 40/40 steps with a genuine state delta, 0
invariant violations, 0 bugs flagged. See RESULTS.md **L-007** for the run + a UGT
core bug found and fixed along the way (`playtester.py`'s display-only-verb check
crashed on the non-string `value` that `legal_action` mode uses).

**Status (2026-07-12, evening re-run vs DDD `0eb0df83`): the ladder is COMPLETE and green.**
`spike 10/10 · smoke 5/5 · R1 11/11 · R2 26/26 · R3 32/32` — zero open findings.
The re-run absorbed DDD's T6.0/T6.5/D17 changes: R2's D16 pin moved to the re-ratified
**+5** (D17), and R3 provoked **`INSUFFICIENT_FOCUS`** for the first time — the Focus
economy now binds, closing D-C1. One tester stitching defect found + fixed in
`verify_round3.py` (see RESULTS.md, re-run section).

- What it does + how to run it: **[README.md](README.md)**
- What was found, fixed and pinned: **[RESULTS.md](RESULTS.md)**
- Game: `/Users/vs7/Dev/Games/DDD`, branch `feat/d16-type-triangle`
- UGT commits `00aaa33` (re-baseline + R2), `9ff38b1` (R3), this session (re-run) · DDD commits `61125b64` (D-F1/D-F2), `0eb0df83` (re-run baseline)

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

1. ~~**LLM balance-playtest tier**~~ **WIRED + RUN 2026-07-21** (L-007): `playtest_ddd.py`
   drives DDD via `action_mode="legal_action"` (no `press_key`/`get_terminal_text` on
   `DddHarnessAdapter` — the harness is structured JSON, not a terminal). PLAYTEST MET
   on a 40-action ollama/gemma4:26b run (40/40 steps with a state delta, 0 invariant
   violations, 0 bugs). Deeper/longer runs for an actual T6.2 balance verdict are the
   only thing still open here — see RESULTS.md L-007.
2. **DDD T6.3's conformance audit #2** (fresh read-only rulebook-vs-engine pass). The
   R1 half of that task is met; the audit half is untouched.
3. ~~**DDD T6.0(b)/(c)**~~ **RESOLVED upstream** (DDD `7a246d74`, T6.0 DONE):
   `randomPolicy` and tier-1 random now fill a random legal target subset, the
   balance instruments were re-priced (`effectValue` reachability discount), and the
   ladder floors re-pinned against the armed baseline. The honest skilled-play
   matchup is Blitzblade ~36% — still red, owned by DDD T6.2.

## Open findings against DDD

None. D-C1 (**the Focus economy never binds**) is **CLOSED** as of the `0eb0df83`
re-run — T6.5 re-priced the pack (costs 0–4) and R3 provoked a live, state-inert
`INSUFFICIENT_FOCUS` refusal over the wire. Whether cost is now an *interesting*
decision (not merely a reachable constraint) is the LLM-playtest tier's question.

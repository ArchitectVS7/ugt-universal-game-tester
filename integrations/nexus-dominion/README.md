# Nexus Dominion integration

UGT trial for **Nexus Dominion** (single-player 4X space-empire "digital
boardgame"; Tauri 2 + React 19, pure-TS deterministic engine). Engine-first
JSON-lines subprocess trial — the DDD pattern.

**Start with `HANDOFF.md`** (resume-here doorway). `RESULTS.md` is the
commit-traceable findings log. `FEASIBILITY.md` is the original go/no-go study.

## Files

| File | Role |
|---|---|
| `HANDOFF.md` | resume-here: status, run recipe, key facts, open items |
| `RESULTS.md` | findings log (10 defects fixed upstream) + characterizations |
| `FEASIBILITY.md` | the pre-build go/no-go study |
| `ugt.config.yaml` | engine + 20-action vocabulary (lockstep with the adapter) |
| `invariants.py` | 10 flat per-step predicates + full-state cross-ref checks |
| `spike_nexus_dominion.py` | raw JSON-lines protocol contract (11 checks) |
| `smoke_nexus_dominion_adapter.py` | same path via `BaseAdapter` (6 checks) |
| `verify_round1.py` | playability gate — one campaign + invariants + save/load (12) |
| `verify_round2.py` | full spine — all 15 order types to real outcomes (17) |
| `verify_round3.py` | exploit-hunter + refusal/garbage battery + replay (43) |

The adapter (`ugt/adapters/nexus_dominion_harness.py`) and the game-side harness
(`nexus-dominion/src/harness/`, `nexus-dominion/harness/`) live in their
respective repos.

## Run (from the UGT repo root; node >=24)

```bash
for s in spike_nexus_dominion smoke_nexus_dominion_adapter \
         verify_round1 verify_round2 verify_round3; do
  python3 integrations/nexus-dominion/$s.py || break
done
```

No server to start — the adapter spawns the harness subprocess. Exit 0 +
`… MET — N/N` per round means the gate passed.

## Status

Full ladder green against nexus-dominion `1851ddd`:
**spike 11/11 · smoke 6/6 · R1 12/12 · R2 17/17 · R3 43/43**, zero R3 findings.
10 game defects found + fixed upstream (see `RESULTS.md`). Next tier: LLM
balance playtester (credit-gated, pending).

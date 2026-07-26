# Tiny Escape Room — UGT integration

Drives `../game` (Node.js, JSON-lines over stdio) through UGT's built-in
**`simulation`** engine. No adapter code: `engine.type: simulation` +
`entry: ../game/src/bridge.js` is handled entirely by `SubprocessAdapter`,
which runs `.js` entries with `node`. This is the most CLI-native of the three
examples.

## Run it

```bash
# from the repo root
cd examples/escape-room/game && npm test && cd -      # game suite: 85/85

cd examples/escape-room/integration
ugt smoke-test --config ugt.config.yaml                                   # wiring
ugt verify --config ugt.config.yaml --feature-map feature-map.yaml        # Tier 1 — 6/6
python3 ../../../examples/escape-room/integration/exploit_hunt.py         # Tier 2 — 6/6
```

Recorded results (2026-07-25, against the game at 85/85 green):

| Tier | Command | Result |
|---|---|---|
| 0 | `ugt smoke-test` | PASSED, 5/5 steps |
| 1 | `ugt verify` | **6/6 PASSED, 0 FAILED, 0 NOT_REACHED** |
| 2 | `exploit_hunt.py` | **TIER 2 MET — 6/6 checks**, 2 seeds x 160 steps, 0 findings |
| 3 | `ugt playtest` | guide written, **run not yet performed** — see below |

## Files

| File | Role |
|---|---|
| `ugt.config.yaml` | `engine.type: simulation`; 41 actions, **generated** from `node ../game/src/bridge.js --actions` so ids cannot drift from the CSVs |
| `feature-map.yaml` | Tier 1 — F1–F6 as one continuous playthrough of the real flag chain |
| `exploit_hunt.py` | Tier 2 — random walks + invariants + negative control + determinism |
| `strategy-guide.md` | Tier 3 — the briefing an LLM playtester reads |

## Tier 3 is written but not run

`ugt playtest` bills a real Anthropic API call per action. The guide is
committed and the wiring is ready, but the run itself was deliberately left for
a human to trigger:

```bash
ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md --max-actions 40
```

Its acceptance (per `TASKS.md` T-005) is that the report shows either
`escaped: true` or an honest "insufficient actions" outcome — not a silent
stall.

## Findings

Things this integration surfaced that are worth knowing. None block the ladder;
the first is the one with teeth.

**1. `ugt verify` exits 0 even when features FAIL.** `handle_verify`
(`ugt/cli.py`) only calls `sys.exit(1)` on an *exception* — a run reporting
`1 FAILED` still exits 0. Verified directly: inverting F6's assertion produced
`[FAIL] game.reaching_r10_sets_escaped` and `Coverage: 5/6 ... 1 FAILED`, and
the shell still saw exit 0. Every example's `TASKS.md` gate is phrased "`ugt
verify` … exits 0 with 0 FAILED features", so **a gate that checks only the
exit code passes a red run**. Until it's fixed, gate on the `failed` count in
`results/coverage-report.json`, not on `$?`.

**2. Observation aggregators are list-only.** The integration PRD proposed
mapping `flags_set_count`, but `flags` is a dict and `count` only applies to
lists (`ugt/core/env.py::get_value_by_path`) — it would have silently read 0
forever, a mapped field that is always a lie. `escaped` is mapped instead, so
all four observation fields are real.

**3. The assertion language has no `len()` and no `in`.** So "the inventory
shrank by one" is not directly expressible. Rather than weaken F5, it is
asserted through a behavioural consequence: the engine leaves state *entirely*
untouched on a refusal, so issuing `use_cog_bronze` (which consumes) then
`drop_cog_bronze` and finding `moves_taken` advanced by only 1 across both
proves the cog left the inventory. Adding `len` to the evaluator's `SAFE_FUNCS`
would be a one-line, safe improvement, but it was left out of this branch: the
Tier-1 gate runs through the installed `ugt` console script, so a core change
here could not have been honestly verified as part of this work.

**4. Random play cannot solve this game, by design.** The Tier-2 walk reached
only **9 distinct states across 61 steps** — a uniform random policy almost
never advances a 7-link flag chain. That is a property of the genre, not a
defect, and it is the clearest illustration in this repo of why the tiers are
not interchangeable: Tier 2 proves the game never *breaks* under nonsense
input, while only Tier 1 (scripted) and Tier 3 (an LLM that reads
`strategy-guide.md`) can show it is *completable*. The exploit hunt asserts its
own non-vacuity for this reason.

## Notes on the feature map

`ugt verify` does not navigate to satisfy preconditions — it only steps
action 0 when nothing is eligible, and here action 0 is `go_north`, a real
move. The map is therefore written as one continuous playthrough split into six
assertions, relying on two runner behaviours documented in the file's header:
features run sorted by `(priority, definition order)` — so all six are
`critical` to preserve file order — and `MAX_TASKS_PER_TURN = 3`, so no feature
may depend on a precondition that only an earlier feature *in the same turn*
sets.

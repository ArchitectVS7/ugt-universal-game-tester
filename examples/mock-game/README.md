# Example: `mock-game` — the simplest `simulation` integration

**MockSimulatorGame** is the smallest possible UGT integration: a self-contained
Python game (`sim_game.py`) wired through the built-in **`simulation` engine
type**, so it runs through the bare `ugt` CLI (no per-game ladder scripts). It's
the place to learn the config shape and the three CLI tiers before anything else.

Its economy is deterministic; a seeded `enemy.credits` random walk (driven by
`UGT_SEED`) shows how a bridge earns reproducibility — two runs with the same seed
are byte-identical.

> Want the **full trial ladder** (spike → smoke → R1 → R2 → R3, exploit-hunter,
> determinism) driven engine-first through a harness adapter? See the sibling
> `../harness-game`. This example is deliberately the minimal CLI-wired path.

## Files

| File | Role |
|---|---|
| `sim_game.py` | The whole game AND its subprocess bridge (newline-delimited JSON on stdin/stdout). Reads `UGT_SEED`. |
| `ugt.config.yaml` | `engine.type: simulation`; observation space, action space. |
| `feature-map.yaml` | The correctness assertions `ugt verify` checks (state deltas per action). |
| `strategy-guide.md` | The briefing the LLM playtester reads (tier 3). |

## Run it (from this folder)

```bash
# Tier 0 — wiring sanity (5 random steps)
ugt smoke-test --config ugt.config.yaml

# Tier 1 — correctness (drives the feature map, writes results/coverage-report.json)
ugt verify --config ugt.config.yaml --feature-map feature-map.yaml --max-turns 60

# Tier 3 — LLM playtest (needs `pip install -e ".[playtest]"` and ANTHROPIC_API_KEY)
ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md --max-actions 30
```

(`ugt <cmd>` and `python3 -m ugt.cli <cmd>` are equivalent.)

Expected `verify` result: **5/6 PASSED, 1 NOT_REACHED**. The NOT_REACHED one is
`game.win_condition` — its precondition (`credits >= 450`) isn't reached inside the
default drive, which is exactly what the NOT_REACHED status is for (feature not
exercised ≠ feature failed). Raise `--max-turns` or lower the precondition to reach it.

## Notes

- **Reproducibility:** `UGT_SEED=7 python3 sim_game.py` fed the same commands twice
  yields identical `enemy.credits` trajectories; a different seed diverges. The core
  economy is deterministic regardless, so the feature-map assertions are stable.

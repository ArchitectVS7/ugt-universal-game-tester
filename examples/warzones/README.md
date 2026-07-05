# Warzones — UGT Integration Example

This example demonstrates UGT controlling the **Warzones** game via the subprocess adapter, using the existing pure-Python simulation from `warzones-ml/sim/`.

## Architecture

```
UGT CLI → SubprocessAdapter → sim_bridge.py → warzones-ml/sim/ (game engine)
```

`sim_bridge.py` is a thin JSON-over-stdin/stdout wrapper that:
1. Imports the Warzones sim modules (`turn_manager`, `combat`, `victory`) directly
2. Translates UGT IPC commands into sim function calls
3. Returns flattened game state matching the `ugt.config.yaml` observation mappings

**No sim code is modified.** The bridge adds the `warzones-ml/` directory to `sys.path` at startup.

## Dependency

This example requires the `warzones-ml/sim/` package to be present at `../../../warzones/warzones-ml/sim/` relative to this directory. The path is resolved automatically by `sim_bridge.py`.

## Observation Space

The 10-element observation vector matches the bespoke `WarzonesSimEnv`:

| Index | Field | Description |
|---|---|---|
| 0 | `turn` | Current turn number |
| 1 | `player.credits` | Player's credit balance |
| 2 | `player.ap` | Player's action points |
| 3 | `player.sectors_owned` | Sectors controlled by player |
| 4 | `enemy.sectors_owned` | Sectors controlled by enemies |
| 5 | `player.hull` | Player ship hull HP |
| 6 | `player.max_hull` | Player ship max hull HP |
| 7 | `enemy.bots_alive` | Number of living bots |
| 8 | `game_over` | 1.0 if game has ended |
| 9 | `player_won` | 1.0 if player won |

## Reward Formulas

The UGT config uses **simplified** reward formulas that approximate the bespoke reward functions. The bespoke `WarzonesSimEnv` uses delta tracking (comparing current vs. previous observation), conditional bonuses, and milestone sets — none of which can be expressed in UGT's declarative formula strings.

This is an intentional trade-off: the UGT agent may not match bespoke performance, but it proves the universal framework works.

## Usage

```bash
# Smoke test
python3 -m ugt.cli smoke-test --config examples/warzones/ugt.config.yaml

# Train (short run)
python3 -m ugt.cli train --config examples/warzones/ugt.config.yaml --profile aggro

# Evaluate
python3 -m ugt.cli evaluate --config examples/warzones/ugt.config.yaml \
  --profile aggro --model ./examples/warzones/models/ppo_aggro_final --episodes 10
```

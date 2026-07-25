# Dice Duel — Integration PRD (UGT side)

**One-liner:** Drive `../game` through UGT's **browser** adapter (Playwright)
and run the full three-tier ladder against it — the state/action contract is
fixed by `../game/PRD.md`.

**Why this example exists:** Show the `browser` engine type end-to-end
against a *new* game (not the browser-game doc stub), including a feature map
with real assertions and a determinism check under random play.

## Adapter type: `browser`

Same transport as `examples/browser-game`: Playwright loads the built Vite
bundle statically served (`serve.py`-style), waits for `window.__GET_STATE__`,
and drives actions via `window.__SEND_ACTION__`. No adapter-side game logic —
every rule stays in `../game/src/engine.js` (UGT rule M1).

## State contract (must match `../game/PRD.md` exactly)

```
player.force_strength   int 0-20
player.bonus_dice       int 0-4
enemy.force_strength    int 0-20
enemy.bonus_dice        int 0-4
round_number             int 0-12
battle_over             bool
winner                  null | "player" | "enemy" | "draw"
```

## Action contract

`action_space.size: 7`, one action per allocation preset (0 = all-attack …
6 = all-defense), matching `../game/PRD.md`'s `__SEND_ACTION__` mapping
exactly.

## Files to produce

- `ugt.config.yaml` — `engine.type: browser`, `entry` pointing at the served
  bundle, observation/action mappings above, `evaluation.victory_key: winner`.
- `feature-map.yaml` — see Feature Map Coverage Plan below.
- `strategy-guide.md` — Tier-3 briefing: the ruleset, the 7 allocation
  choices, and the win condition, written for an LLM playtester with no other
  context (per `LESSONS.md` §B conventions).
- `serve.py` (or reuse `examples/browser-game/serve.py`'s pattern) — static
  file server for the built bundle.

## Feature map coverage plan (Tier 1 — `ugt verify`)

| ID | Assertion | Precondition |
|---|---|---|
| F1 | All-attack preset (action 0) can reduce `enemy.force_strength` | none |
| F2 | All-defense preset (action 6) reduces net damage taken vs. an all-attack round | none |
| F3 | `player.bonus_dice` reflects Morale surge when `player.force_strength > enemy.force_strength`, isolated from the other two bonus rules | `player.force_strength > enemy.force_strength AND player.force_strength > 10 AND round_number != 2` |
| F4 | Reinforcements bonus applies exactly at `round_number == 2` (pre-round-3) and not before/after, isolated from the other two bonus rules | `round_number == 2 AND player.force_strength <= enemy.force_strength AND player.force_strength > 10` |
| F5 | `battle_over` becomes `true` and `winner` is set when either side's FS reaches 0 | drive to a decisive round |
| F6 | Round-12 cap yields `battle_over: true`, `winner: "draw"` if neither side is at 0 | run 12 rounds with balanced allocations |

## Trial ladder plan

- `ugt smoke-test` — 5 random actions round-trip through the adapter without
  error.
- `ugt verify` — F1-F6 above via `feature-map.yaml`.
- Exploit-hunter (Tier 2) — random allocation walk for 30+ rounds, asserting
  invariants: `0 ≤ force_strength ≤ 20` always, `round_number` never
  decreases, `winner` only set once `battle_over` is true. Same-seed replay
  must match byte-for-byte (proves the game's RNG discipline from its PRD
  holds).
- `ugt playtest` — Tier 3, using `strategy-guide.md`, judges whether the
  7-preset allocation choice produces interesting strategic tension or a
  dominant strategy.

## Acceptance criteria

- All ladder steps above pass against a built `../game` bundle.
- `feature-map.yaml` covers F1-F6 with 100% PASSED on a clean run.
- Exploit-hunter finds zero invariant violations across ≥100 random-action
  steps, two seeds.

# Tarot War — playtest strategy guide (action_id drive mode)

You are balance-playtesting Tarot War, a two-player card-battle: YOU (player1) vs
the **Oracle** (player2, the AI). Each round both sides reveal a card; the higher
`power` wins the round and claims both cards. `score` = cumulative cards claimed.

## How to answer
- Respond with `action_type="action_id"` and `value` = one of these action NAMES only:
  `play_round`, `set_ai_easy`, `set_ai_medium`, `set_ai_hard`,
  `set_mode_classic`, `set_mode_survival`, `set_mode_endless`, `wait`.
- Never invent an action name or press keys — only the names above dispatch.

## Setup-first flow (the key gotcha)
- The mode/difficulty pickers (`set_ai_*`, `set_mode_*`) apply **ONLY while
  `phase == "setup"`**. Pick a mode AND a difficulty FIRST, then call `play_round`.
- Calling a picker mid-game is REFUSED (`info.ok=false`, state unchanged) — that is
  correct, not a bug. Do not repeat a refused picker; move on to `play_round`.
- When `phase == "finished"`, `play_round` is a no-op and the game auto-resets to a
  fresh `setup` episode. `EPISODE_RESET` in the recent-actions log is NORMAL, not a bug.
- Use `wait` sparingly — it just re-reads state.

## The war-card mechanic
- A **tie** in `power` triggers a "war": extra cards are staked (`warPile`/`warDepth`
  rise) and a tie-breaker resolves who claims the whole pile. Watch that wars resolve
  and that cards are conserved (nothing vanishes or duplicates).

## Modes
- **classic** — play until one side is card-exhausted; opponent exhaustion = win.
  NOTE (recorded): because `score` counts cards claimed but the win is exhaustion,
  the WINNER can finish with the LOWER score — expected.
- **survival** — endurance variant.
- **endless** — the deck recycles from the discard pile, so play continues.

## The Magical Effects panel (watch this — TW-R6)
Some cards fire effects. They surface in three places in state:
`globalEffects`, each player's `activeEffects`, and `gameLog` entries of
`type: "effect"` (each round-stamped). These are easy to miss visually and were once
invisible due to a round-stamp bug (now FIXED). WATCH them after an effect card
resolves. If an effect card resolves but the panel stays empty, or an effect log
entry looks stamped with the wrong round, flag it via `potential_bug`.

## What a balance-playtester probes
- Does raising difficulty (`set_ai_hard` vs `set_ai_easy`) actually make the Oracle
  stronger — does its win rate visibly change? Play a game at each and compare.
- Do wars resolve fairly and conserve cards (`warPile` should return to 0)?
- Do card effects actually fire when their cards resolve?
- Is any mode a soft-lock (a game that never reaches `finished`)?

Vary mode and difficulty across the run so you exercise the whole game, then play
enough `play_round` steps to reach real outcomes. Flag anything that looks off via
`potential_bug` — a suspected balance or correctness issue is data, not a failure.

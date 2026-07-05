# MockSimulatorGame — Strategy Guide

This guide is for the LLM playtest agent. Read it before choosing actions.

## Win Condition

Accumulate **500 credits** within **20 turns**. The game ends in victory when
`player.credits >= 500`. If 20 turns pass without reaching 500 credits, the game
ends in defeat.

## Core Loop

1. **Invest while you have AP.** Each `invest_credits` costs 2 AP and gains 50 credits.
   With 10 AP per turn, you can invest 5 times per turn (+250 credits/turn).
2. **End the turn when AP runs low.** `end_turn` restores AP to 10.
3. **Repeat.** You need ~500 credits, starting from 100. That's ~2 turns of investing.

## Action Vocabulary

| Action ID | Name | Effect |
|-----------|------|--------|
| 0 | wait | No-op. Does nothing. Wastes a step. |
| 1 | invest_credits | Costs 2 AP, gains 50 credits. Triggers victory at credits >= 500. |
| 2 | end_turn | Restores AP to 10, increments turn counter. |

## What Good State Looks Like

- `player.credits` increasing each time you invest
- `player.ap` decreasing by 2 per invest, returning to 10 after end_turn
- `turns_elapsed` incrementing by 1 each end_turn
- `victory: true` when credits reach 500

## Bug Signatures

- **Credits unchanged after invest_credits** — the invest action is broken
- **AP unchanged after invest_credits** — cost is not being applied
- **AP not restored after end_turn** — end_turn is broken
- **turns_elapsed not incrementing** — turn counter is broken
- **victory never fires** — win condition check is broken
- **Negative credits or AP** — arithmetic error in game logic

## Notes for the Agent

- Prefer `invest_credits` over `wait` unless AP is 0
- Call `end_turn` when AP < 2 (can't invest anyway)
- If you see `defeat: true` in state, the game has ended — stop and flag it
- If you invest but credits don't change, flag it as a potential bug immediately

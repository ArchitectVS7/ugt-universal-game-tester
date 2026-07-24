# BrowserExampleGame (Credit Clicker) — Strategy Guide

This is the tier-3 (LLM playtest) briefing for the browser version of the credit
clicker. It is the same game as `examples/mock-game`, driven through a real
headless browser via the `window.__GET_STATE__` / `__SEND_ACTION__` hooks in
`index.html`.

## Win / loss condition

- **Win:** accumulate **500 credits**. `victory` becomes true the moment
  `player.credits >= 500`.
- **Loss:** 20 turns pass without reaching 500 credits (`defeat` becomes true).

## Core loop

1. **Invest while you have AP.** Each `invest_credits` costs 2 AP and gains 50
   credits. With 10 AP per turn you can invest 5 times (+250 credits/turn).
2. **End the turn when AP runs low.** `end_turn` restores AP to 10.
3. **Repeat.** From 100 credits you need ~2 turns of investing to reach 500.

## Action vocabulary

| Action | Effect |
|---|---|
| wait | No-op. Wastes a step. |
| invest_credits | −2 AP, +50 credits. Triggers victory at credits ≥ 500. |
| end_turn | Restores AP to 10, increments the turn counter. |

## What good state looks like

- `player.credits` rising with each invest; `player.ap` dropping by 2, resetting
  to 10 after `end_turn`
- `victory: true` once credits reach 500

## Bug signatures (flag these)

- Credits unchanged after `invest_credits` while AP was available — economy broken
- AP not restored after `end_turn` — turn logic broken
- `turns_elapsed` not incrementing on `end_turn`
- `victory` never firing despite credits ≥ 500 — win check or the state hook is broken
- The rendered page (Credits / AP / Status) not matching `__GET_STATE__` — a
  render/state divergence, exactly the kind of wire bug a browser tester exists to
  catch (`LESSONS.md` M8)

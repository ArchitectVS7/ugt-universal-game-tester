# DDD — playtest strategy guide (legal-action drive mode)

DDD is a two-player deterministic dueling card game. You drive whichever seat the
engine is currently waiting on; each step you are shown that seat's structured
state plus the exact list of LEGAL ACTIONS the engine will accept. Pick ONE by its
index number.

## How to answer
- Respond with `action_type="legal_action"` and `value` set to the NUMBER (index)
  of the action you want from the LEGAL ACTIONS list. Nothing else is a valid move.
- Never invent an action that is not in the list — only the numbered options are legal.

## Reading the state
- `p0` and `p1` are the two seats. `pendingSeat` is the seat you are acting for now.
- Per seat: `hp` (0–30, you win by taking the OPPONENT to 0), `focus` (0–5, the
  resource that pays for cards), `handCount`, `deckCount`, `stance`, `committedKind`.
- `phase` is `MULLIGAN` first (decide your opening hand), then repeated `SELECTION`
  steps (commit a card or pass), and `resultKind` is `ONGOING` until the match ends.

## What the legal actions mean
- `MULLIGAN` with `full:false` — keep your hand (usually correct); `full:true` —
  redraw everything (only if the hand is unplayable).
- `COMMIT_SELECTION` — play a card this round; this is your main way to deal damage
  and pressure the opponent's HP. Prefer committing a card when you can afford one.
- `COMMIT_PASS` — commit nothing this round (only when no card is worth playing).
- `CONCEDE` — forfeit. Do NOT pick this; you are here to play the match out.

## Goal
Play the match to a real result. Reduce the opponent seat's `hp` toward 0 by
committing cards each SELECTION step. Keep the mulligan unless the hand is dead.
Watch for anything that looks wrong (HP or focus out of range, a card vanishing, an
action that changes nothing) and flag it via `potential_bug`.

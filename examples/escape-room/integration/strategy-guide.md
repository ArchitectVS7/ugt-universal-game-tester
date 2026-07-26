# Tiny Escape Room — player briefing

You are playing a text adventure. You start locked in a prison cell and win by
reaching the courtyard outside. Nothing here is timed, nothing can kill you, and
no action can put the game into an unwinnable state — so exploring costs you
only moves.

## What you can do

Every action is one of these verbs, applied to a direction or an object:

| Verb | Meaning |
|---|---|
| `go <north\|south\|east\|west>` | Move to the adjoining room, if there is an exit and you are allowed through |
| `look` | Re-read the current room's description |
| `inventory` | List what you are carrying |
| `take <object>` | Pick an object up (only if it is here and portable) |
| `drop <object>` | Put a carried object down |
| `examine <object>` | Read an object's description — this is where most hints are |
| `use <object>` | Apply an object's special verb (unlock, light, turn, fit, read) |

An action that cannot apply right now — walking into a wall, taking something
that isn't here, using something you aren't carrying — is simply refused. It
changes nothing at all, not even your move count. Refusals are free; they are
how you find the edges of the world.

## How progress actually works

The world is gated by **flags** — invisible switches that get set when you take
or use the right thing. A locked room stays shut until its flag is set, and an
object's `use` is refused until its own prerequisite flag is set. So the game is
one chain: each step unlocks the next.

Two consequences worth internalising:

- **`examine` everything you find.** Descriptions tell you what an object is
  *for*. It costs a move and never fails.
- **If a `use` is refused, you are missing a prerequisite, not using it wrong.**
  Go find the thing that sets the flag it wants, then come back.

Some objects are **consumed** when used — they leave your inventory and cannot
be reused. That is never a mistake; nothing needs to be used twice.

## What you can see

**Two channels, and they say different things.**

The **game text** is the prose the game prints back at you — the room you just
entered and its exits, what is lying there, an object's description when you
examine it, and the line it prints when a `use` succeeds or is refused. This is
where the puzzle actually lives. A refusal usually tells you *why* it was
refused, and that sentence names what you are missing. Read it.

You see the last few lines of that text, newest at the bottom. It scrolls, so
anything you want to keep, you have to act on.

The **state** is the structured summary, and it includes:

- `current_room` — which room you are in
- `inventory` — the objects you are carrying
- `flags` — every flag in the game and whether it is set. **This is your
  progress bar.** A flag flipping to `true` is the only reliable signal that you
  advanced; if you take an action and no flag changed and you did not move, you
  learned something but changed nothing.
- `moves_taken`, `rooms_visited`
- `escaped` — `true` only when you have won

## Winning

Reach the courtyard. The prison is roughly linear: the cell block leads to a
furnace level, which leads up to a clockwork gallery, which leads to the gate.
Each level is shut off until you have done the thing the previous one was
hiding. You will need light before you can work in the dark parts, and the outer
gate needs more than a key.

There is no score. Escaping in fewer moves is better, but escaping at all is the
objective.

## A note on how to play well

Sweep each new area before moving on: `look` to see what is here, then `examine`
and `take` what is portable. The room text lists both the exits and the objects
present, so one `look` usually tells you everything the room has.

When a `use` is refused, read the refusal — it is written to tell you what is
missing. "The wick is bone dry, without oil it will never catch" is the game
saying *find oil*, not *this was the wrong idea*.

When you get stuck, re-read your `flags`. The one still `false` that is blocking
you names what you need, and some object you have already walked past is what
sets it. Going back for it is normal — this prison is not long, and moves are
the only thing you spend.

You do not need to re-examine something you have already read. You were told its
description once and it does not change.

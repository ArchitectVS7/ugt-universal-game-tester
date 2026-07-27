# Sokoban Mini — player briefing

You are playing a Sokoban puzzle. Push every crate onto a target. Three levels,
one after another, and the third one finishes the game.

Nothing can kill you, nothing is timed, and no move can lose the game — the only
cost of a mistake is the moves it takes to undo it. **But some mistakes cannot be
undone by moving**, and knowing which is the whole skill. Read on.

## What you can see

The board is drawn in the classic Sokoban legend, one line per row:

```
#   wall — you cannot enter it, and a crate cannot be pushed into it
@   you
$   a crate that is NOT yet on a target
.   an empty target, waiting for a crate
*   a crate already on a target — this one is DONE, leave it alone
+   you, standing on an empty target
(space)  plain floor
```

Row 0 is the top line; column 0 is the leftmost character. `up` decreases the
row, `down` increases it, `left` decreases the column, `right` increases it.

Your own position arrives as two numbers in that same frame: **`player_x` is the
column** and **`player_y` is the row.** Both count from zero, on the board
exactly as drawn above — so the character in row `player_y`, column `player_x`
is your own `@` or `+`.

Count the `$` and the `.` before you move. Every `$` needs to reach a `.`, and
the number of each is always equal.

## The one rule that matters

**You push. You cannot pull.** Walking into a crate pushes it one cell in the
direction you are already walking — and only if the cell *directly beyond the
crate* is free floor or an empty target. If that far cell is a wall, or another
crate, the whole move is refused and nothing happens at all.

Everything below follows from that single rule.

- **To push a crate in some direction, you have to be standing on the opposite
  side of it.** So before pushing, ask whether you can actually get to that side.
  A crate flat against a wall can never be pushed *away* from that wall, because
  the square you would have to stand on is inside the wall.
- **A crate in a corner is dead forever.** Two walls meet, both remaining push
  directions are blocked, and no sequence of moves anywhere on the board will
  ever free it. If a corner is not a target, pushing a crate into it has lost you
  that crate permanently.
- **A crate against a wall can only slide along that wall.** If there is no
  target on that wall, it is nearly as dead as a cornered one.
- **Two crates side by side block each other** along the line joining them.

## How to actually play

1. **Pick one crate and decide where it is going, before you touch it.** Trace
   the route it will take and check you can stand behind it at every push.
2. **Walk around the board freely.** Moving through empty floor costs nothing but
   a move, and there is no move limit. Get to the right side of a crate rather
   than pushing it from whichever side you happen to be on.
3. **Do the crate whose route is most fragile first.** A crate you finish early
   becomes a `*` — a permanent obstacle that can block another crate's route or
   the corridor you need to walk through. Placing the awkward one first is
   usually cheaper than placing the easy one and then discovering you have walled
   yourself off.
4. **Never push a crate towards a wall or a corner unless a target is on it.**
   This is the single most common way to lose a level.

## When a move does nothing

If the board comes back **exactly** as it was, your move was refused — you
walked into a wall, or tried to push a crate into a wall or another crate. The
move counter does not even advance. Repeating it will be refused again for the
same reason. Read the board, work out what blocked you, and pick a different
direction.

## When you are stuck: reload

Action `reload` restores the current level to its starting layout. It is the R
key a human presses, and it is the correct move — not a failure — the moment you
can see a crate is dead. **A cornered crate cannot be recovered any other way.**
Reloading costs you only the progress on the level you are standing in; the
earlier levels you have already solved stay solved.

If you notice a crate is unrecoverable, reload *immediately*. Every move spent
shuffling around a dead board is wasted, and the level cannot be completed.

## Advancing

When the last crate lands on the last target, the level is solved and the board
you see still shows the finished level. **Your next move happens on the next
level** — so expect the board to change shape completely, with the crates and
targets in new places, right after a successful finish. That is not a bug and
your move was not lost; it was applied in the new level.

Solve the third level and the game is over.

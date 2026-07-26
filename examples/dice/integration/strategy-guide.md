# Dice Duel — player briefing

Two armies, 8 force strength each. Every round you split **6 dice** between
Attack and Defense, both sides resolve simultaneously, and damage is applied.
Reduce the enemy to 0 force strength to win.

## Your move

Each turn you pick exactly one allocation. There are seven:

| Action | Attack dice | Defense dice |
|---|---|---|
| `a6_d0` | 6 | 0 |
| `a5_d1` | 5 | 1 |
| `a4_d2` | 4 | 2 |
| `a3_d3` | 3 | 3 |
| `a2_d4` | 2 | 4 |
| `a1_d5` | 1 | 5 |
| `a0_d6` | 0 | 6 |

One action resolves a whole round — both sides act. You cannot pass, and there
is no other kind of move.

## The rules that decide the outcome

**Attack dice deal damage; Defense dice prevent it — at two-for-one.** Damage
to you = (enemy attack hits) − 2 × (your defense hits), floored at 0. Each of
your defense hits cancels TWO of their attack hits, so a defense die is not a
weaker attack die; it is worth more per die on the turn it is needed. Neither is
free — the six dice are all you get.

**Bonus dice are deterministic.** They are granted at the start of a round
based on the state at that moment, with no randomness in *whether* they fire:

- **Morale surge** — if your force strength is higher than the enemy's, you get
  **+1 Attack die**.
- **Dug in** — if your force strength is at or below 4 (half), you get
  **+1 Defense die**.
- **Reinforcements** — **once only, at the start of round 3**, each side gets
  **+2 dice**, added to whichever pool that side allocated the most to that
  round. A tie splits toward Attack.

These stack. Entering round 3 while ahead and above half strength gives you
+2 reinforcements and +1 morale together.

**The battle ends after round 12, and the cap DECIDES IT ON POINTS.** If neither
side has been reduced to 0 by then, **the side with the higher force strength
wins**. Only an exact tie is a `"draw"`. Surviving the cap one point ahead is a
full win, identical to a knockout.

## What you can see

- `player.force_strength` / `enemy.force_strength` — 0 to 8
- `player.bonus_dice` / `enemy.bonus_dice` — the bonus dice granted this round
- `round_number` — 0 to 12
- `battle_over`, `winner` — `null` until it ends, then `"player"`, `"enemy"` or
  `"draw"`

## How to play well

**All-out attack is a losing line.** It looks strongest and it is not: against
the AI it wins about 43% while a balanced `a3_d3` wins about 58%. The reason is
the two-for-one block — six attack dice average two hits, and two of the enemy's
defense hits erase all of them. Feeding an opponent's defense is how you waste a
round.

**Play the margin, not the knockout.** Because the cap decides on points, force
strength is a SCORE, not just a life bar. Being 2 ahead on round 11 is a winning
position and you should protect it; going all-in from ahead risks converting a
win into a loss. Most battles are now decided at the cap rather than by a
knockout, so the question every round is "does this allocation improve my
margin?" — not "can I kill them this round?".

**The right allocation depends on the position, and it genuinely changes.** From
behind, you need swing, so weight attack and accept the risk. From ahead, weight
defense and run the clock — the cap pays you. Level, `a3_d3` is usually correct.
There is no single allocation that is right all game; if you find yourself
picking the same one every round, you are misplaying.

Watch the interaction between the bonuses and your own health. Falling to half
strength (4) hands you a free defense die, which makes holding a slim lead
cheaper — that is now a real comeback tool rather than a way to stall.

Round 3 is the single biggest swing in the game: the +2 goes to whichever pool
you loaded most heavily *that round*, so what you choose there is amplified.

There is no score beyond the result. A win on points is a win.

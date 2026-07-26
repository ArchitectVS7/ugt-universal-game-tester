# Dice Duel — player briefing

Two armies, 20 force strength each. Every round you split **6 dice** between
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

**Attack dice deal damage; Defense dice prevent it.** More attack means the
enemy loses more force strength this round; more defense means you lose less.
Neither is free — the six dice are all you get.

**Bonus dice are deterministic.** They are granted at the start of a round
based on the state at that moment, with no randomness in *whether* they fire:

- **Morale surge** — if your force strength is higher than the enemy's, you get
  **+1 Attack die**.
- **Dug in** — if your force strength is at or below 10 (half), you get
  **+1 Defense die**.
- **Reinforcements** — **once only, at the start of round 3**, each side gets
  **+2 dice**, added to whichever pool that side allocated the most to that
  round. A tie splits toward Attack.

These stack. Entering round 3 while ahead and above half strength gives you
+2 reinforcements and +1 morale together.

**The battle ends after round 12.** If neither side has been reduced to 0 by
then, the result is a **draw** — not a win for whoever is ahead. Your `winner`
field will read `"draw"`.

## What you can see

- `player.force_strength` / `enemy.force_strength` — 0 to 20
- `player.bonus_dice` / `enemy.bonus_dice` — the bonus dice granted this round
- `round_number` — 0 to 12
- `battle_over`, `winner` — `null` until it ends, then `"player"`, `"enemy"` or
  `"draw"`

## How to play well

The round cap is the thing most players underestimate. **A draw is not a
consolation result — it is the default outcome unless you force a decision.**
Ending round 12 with the enemy on 1 force strength scores exactly the same as
ending it with the enemy on 19. If you intend to win, you need damage early and
often; defense buys you rounds you may not have to spare.

Watch the interaction between the bonuses and your own health. Falling to half
strength hands you a free defense die, which makes turtling cheap — and turtling
is precisely what runs the clock out into a draw. Staying ahead on force
strength instead keeps feeding you the extra attack die that closes a battle.

Round 3 is the single biggest swing in the game: the +2 goes to whichever pool
you loaded most heavily *that round*, so what you choose there is amplified.

There is no score beyond the result. A win is a win; a draw is not one.

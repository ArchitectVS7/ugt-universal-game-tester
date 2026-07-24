# Foraging Run — Strategy Guide (LLM playtest tier)

This is the tier-3 artifact: the briefing an LLM balance-playtester reads before
choosing actions. It is included to show the *shape* of a strategy guide and to
embody `LESSONS.md` §B — **teach the RULES that create the skill, not just the
list of actions** (P6). A guide that only names the buttons produces a pilot that
goes through the motions.

## Win / loss condition

- **Win:** reach `location >= 4` while `hp > 0`. Arrival is checked after every
  action, so the run ends in victory the moment you step onto location 4 alive.
- **Loss:** `hp` hits 0, OR the `day` counter passes 12 before you arrive.

## The core tension (this is the skill)

Every `travel` costs **2 supplies** and has a **1-in-3 chance of an ambush (−2 hp)**.
You start with 6 supplies and 10 hp — not enough to travel 4 times and absorb bad
luck. So the real game is *managing the supply/hp buffer against travel risk*:

- `forage` is your supply engine (+1..4), but 1-in-4 forages costs 1 hp.
- `trade` converts 2 coins → 3 supplies (you start with 3 coins — one safe trade).
- `rest` converts 1 supply → 2 hp: your only healing. Bank hp before a travel leg.
- `end_day` is pure upkeep (−1 supply) and moves you toward the day-12 deadline —
  it never helps you win, so spend days only when you must.

A competent line: forage/trade until you have a comfortable supply buffer, `rest`
if hp drops to ~4, then `travel` toward location 4 — healing between legs rather
than gambling the whole trip on one health bar.

## What good state looks like

- `supplies` staying above ~4 while you still have travelling to do
- `hp` kept off the floor (rest before it reaches 2–3, not after)
- `location` climbing toward 4; `day` well under 12 when you arrive

## Bug signatures (flag these)

- `supplies` or `hp` going **negative** — arithmetic/clamp bug
- `location` **decreasing**, or `day` running **backward**
- A run reported as **both** `won` and `lost`
- Any action changing state **after** the run is already over (should be a no-op)
- `travel` succeeding with `supplies < 2` (it should refuse and no-op)

> These bug signatures are exactly the invariants the ladder asserts in
> `invariants.py` — a real LLM run is a second, adversarial check on the same
> properties from a reasoning player's point of view.

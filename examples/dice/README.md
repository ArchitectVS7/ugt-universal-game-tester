# Dice Duel

A tiny two-army war game. Both sides have 20 force strength, and each round you split six dice between attack and defense. More attack does more damage, more defense takes less. Both sides resolve at the same time, and whoever drops the other to zero wins. There's a hard cap of twelve rounds, and if nobody has won by then it's a draw.

It's built in React, and it's here because it's the **browser** example — the one where UGT drives a real page in a headless browser instead of talking to a subprocess. The game exposes three functions on `window` and UGT calls them. That's the whole contract.

## Running it

You need node, plus playwright and a chromium binary if you want UGT to drive it.

```bash
cd game
npm install
npm run build          # produces dist/, which is gitignored
```

To play it yourself, `npm run dev` and open the page. To let UGT drive it, serve the build:

```bash
cd ../integration
python3 serve.py       # http://localhost:8080
```

Then just ask Claude to run the dice tests. I don't type the commands — "run the dice ladder and show me what you get" does the job, and Claude reads the output and tells me what actually matters. What each tier does lives in [`integration/README.md`](integration/README.md).

## How it got built

I asked for a PRD first, then had Claude turn that into a TASKS.md the orchestrator could climb. Seven tasks. I opened a session in `game/` and let it run — scaffold, then the dice math, then round resolution, then win conditions, then the AI opponent, then the UI, and last the three `window` hooks UGT needs. Every task is its own commit, and the notes in TASKS.md are Claude's, written as it went.

Two things I'd carry into the next one:

**Spelling out the bonus dice rules precisely in the PRD paid off.** There are three of them — an extra attack die when you're ahead, an extra defense die at half strength or below, and both sides get two extra dice at the start of round three. Because I wrote down exactly when each one fires, the tests could later check them one at a time instead of guessing at a lump sum. Vague rules in a PRD turn into code you can't test.

**Putting the UGT hooks last was a mistake.** It meant the game got built and then had a testing seam bolted on at the end. It worked out, but that task ended up the biggest in the list and its commit message came out mangled. Next time I'd have the hooks land early, right after the state model, so everything after is built against something already observable.

## What testing has turned up so far

The interesting one is a balance problem, not a bug. **Draws dominate.** On the seed the game ships with, we tried 205 different action sequences — every fixed strategy plus two hundred aggressive random ones — and not one got the enemy below 1 force strength before the twelve-round cap. Across a dozen other seeds playing pure attack every round, only two produced an actual knockout. So the round limit is deciding most matches, not the combat.

That isn't automatically wrong — it depends whether "most fights end inconclusively" is the feel I want. But it's exactly the sort of thing you don't notice by reading the code, and it's the reason this process exists. It's on the list to tune.

Smaller one worth knowing: because of how the page reports its state, UGT never sees the battle as finished and keeps sending moves into a completed match. Harmless — a finished battle ignores them — but it's now checked rather than assumed.

More will land here as we run the remaining tiers. The full technical write-up, including the findings that are only useful to Claude, stays in [`integration/README.md`](integration/README.md).

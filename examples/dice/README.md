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

Actually you don't even need the server running for the ladder — every rung starts its own and shuts it down after, on a random port so it can't collide with anything. The `serve.py` above is only if you want to poke at the page yourself.

Then just ask Claude to run the dice tests. I don't type the commands — "run the dice ladder and show me what you get" does the job, and Claude reads the output and tells me what actually matters. There are five rungs: a **spike** that pokes the raw page hooks with no test framework involved, a **smoke** run that does the same thing through UGT's adapter, then **R1** (one full battle), **R2** (every allocation, both ways a battle can end), and **R3** (a couple hundred random moves with everything double-checked after each one). What each rung actually asserts lives in [`integration/README.md`](integration/README.md).

## How it got built

I asked for a PRD first, then had Claude turn that into a TASKS.md the orchestrator could climb. Seven tasks. I opened a session in `game/` and let it run — scaffold, then the dice math, then round resolution, then win conditions, then the AI opponent, then the UI, and last the three `window` hooks UGT needs. Every task is its own commit, and the notes in TASKS.md are Claude's, written as it went.

Two things I'd carry into the next one:

**Spelling out the bonus dice rules precisely in the PRD paid off.** There are three of them — an extra attack die when you're ahead, an extra defense die at half strength or below, and both sides get two extra dice at the start of round three. Because I wrote down exactly when each one fires, the tests could later check them one at a time instead of guessing at a lump sum. Vague rules in a PRD turn into code you can't test.

**Putting the UGT hooks last was a mistake.** It meant the game got built and then had a testing seam bolted on at the end. It worked out, but that task ended up the biggest in the list and its commit message came out mangled. Next time I'd have the hooks land early, right after the state model, so everything after is built against something already observable.

## What testing has turned up so far

The interesting one is a balance problem, not a bug. **Draws dominate.** On the seed the game ships with, we tried 205 different action sequences — every fixed strategy plus two hundred aggressive random ones — and not one got the enemy below 1 force strength before the twelve-round cap. Across a dozen other seeds playing pure attack every round, only two produced an actual knockout. So the round limit is deciding most matches, not the combat.

That isn't automatically wrong — it depends whether "most fights end inconclusively" is the feel I want. But it's exactly the sort of thing you don't notice by reading the code, and it's the reason this process exists.

### The twelve-turn question

I want to log this one as a discussion point rather than just a fix, because the interesting part is the fork, not the answer.

When a game keeps ending in draws you've got two levers, and they're not the same decision. You can **change the limit** — make it sixteen rounds and let fights breathe. Or you can **keep the limit and rebalance around it** — more damage per hit, less starting strength, whatever makes twelve rounds enough. The second one is harder and it's the one I'd pick.

Here's the thing though: nobody ever asked *why twelve*. It came out of the PRD because I put it there, and I put it there because it sounded about right. That's a totally normal way for a number to get into a game, and it's worth being honest that it happened. If the twelve is arbitrary then changing it is free and the whole conversation is short. But once you've built and tested against it, that number has started to mean something — the round-three reinforcement rule is positioned relative to it, the AI's behavior is tuned inside it, and the pacing people would feel is built on it. Arbitrary numbers stop being arbitrary the moment other things lean on them.

So I'm going to **hold the twelve and rebalance the combat instead**. Partly because I think a fixed, short match length is actually the better game — it makes every round matter and it means a match can't drag. But mostly, honestly, because it exercises the part of this process I want to demonstrate. Moving the limit is a one-character edit that proves nothing. Rebalancing means going into the mechanics, changing them deliberately, re-running the ladder, and seeing whether the numbers moved the way I predicted. That's the loop I actually want on display here.

### Which brings up: where do your balance numbers live?

Before touching anything I had Claude go look at whether the game's mechanics are actual variables or magic numbers scattered through the code. This is the thing I'd check on any project, and it's usually bad news.

It wasn't, this time. Every balance-relevant number in Dice Duel is a named, exported, commented constant sitting in one file — the round cap, the starting strength, what a die has to roll to hit, the half-strength threshold, how many reinforcement dice you get and which round they arrive, the size of the dice pool, and the allocation table itself. Nothing is buried inline. That means a rebalance is genuinely a matter of changing a couple of values and re-running the tests, which is exactly where you want to be.

If I'm being picky, they're constants in the engine file rather than a separate config, so a designer who doesn't write code still can't touch them without opening source. For a game this size that's fine. For anything bigger I'd pull them into their own file early, because the moment balancing means "find the number in the logic" you stop iterating on balance and start being afraid of it.

The general lesson, and it's one I've learned the expensive way more than once: **decide where your tuning knobs live before you need to turn them.** Retrofitting that is miserable.

### Two things the ladder caught that the earlier tests didn't

Once we built the proper spike/smoke rungs, both turned up something within minutes that the config-driven tests had never touched.

The **spike found that sending a nonsense action throws an error** instead of being politely ignored. That's not wrong exactly — the engine validates its input and refuses rather than guessing, which is good practice — but the other two example games both do the opposite and just hand back the current state. Three games, two different answers, and dice's PRD never said which it should be. Nothing gets corrupted either way, so it's a contract question rather than a bug, but it's the kind of inconsistency that bites whoever writes the next client.

The **smoke rung found that UGT never sees the battle end.** The page reports a `battle_over` flag, but UGT looks for a field called `terminated`, so as far as the test harness is concerned the match runs forever. Harmless in itself — a finished battle ignores input — but R3 then measured what it actually costs: in a 120-step random walk, only about **11 steps land on a live battle**. The other ninety percent are hammering a match that's already over. So the robustness testing had been running at roughly a tenth of the coverage I thought it was.

## Fix #1 — letting the harness see the battle end

I called this a one-line fix. It wasn't, and the way it wasn't is the interesting part.

The obvious move is to add a `terminated` field to what the page reports. Turns out that breaks things in a subtle way: UGT strips that field out when you take a step, but *not* when you reset, so the two would start handing back differently-shaped data and everything comparing one to the other would quietly go wrong. The actual fix was to change what the *action* function returns — it now hands back a small wrapper `{state, terminated, truncated, info}` instead of the bare state. UGT already prefers that shape; the game just wasn't using it. Reading state and resetting are untouched.

That's still a small change. But it landed on seven of the game's own tests, because they were pinning the old shape — which is exactly what you want tests to do. Updated them, added a new one that specifically checks the wrapper and that `terminated` actually flips when the battle ends, and the suite went from 156 to 157.

**Then the harness itself went red, in the best possible way.** The smoke rung had an assertion saying "UGT reports terminated=False the whole way through" — it was *pinning the bug*, honestly, because at the time that was the true behavior. Fixing the game made that assertion fail. Flipped it round to assert the fixed behavior instead, and left a note in the code saying it used to be inverted, because that's a nice illustration of a test doing its job.

**And it caught a second thing I wouldn't have predicted.** One of the entries in the feature map — the one checking that a finished battle ignores further input — started failing too. Not because the game broke. Because UGT *resets the game after any test step that ends the match*, which is completely correct behavior, and that reset had never been firing. That entry had only ever worked because the bug hid the end of the battle from the harness. So a test was passing for a reason that had nothing to do with what it claimed to check. I deleted it and left the explanation where it used to be. The property is still covered — better, actually, since R1 checks it, R2 checks it for all seven moves, and the invariants check it after literally every command.

The payoff, measured rather than assumed: robustness coverage went from **9% of the step budget landing on a live battle to 60%, with zero wasted steps**, because episodes now end when the battle does and start a fresh one. Ten complete battles per seed instead of one battle and a hundred-odd swings at a corpse.

## Fix #2 — the rebalance

Held the twelve rounds, as promised, and moved the combat instead.

First I had Claude build a little measuring instrument — `game/tools/balance_sweep.mjs` — that plays the same battle across a pile of seeds with four different player strategies and reports how games actually *end*. It talks straight to the engine rather than through a browser, because a retune means running it dozens of times. Baseline came back at **13% decisive, 87% draws**. Even all-out attack only converted 30%.

Then we swept candidate values rather than picking one and hoping. Seven combinations. Lowering starting strength helped steadily; making dice hit more often helped too but ended battles around round 7, which makes the twelve-round structure nearly pointless in the *other* direction. Landed on **starting strength 20 → 12** (and the "dug in" threshold 10 → 6, since it's meant to be half). That leaves the "a die showing 5 or 6 is a hit" rule alone, which matters because that one's written into the PRD as a rule players read, where starting strength is just a number.

Result: **13% decisive → 50%**, and an aggressive player now converts about 90% of the time. Two constants changed, `MAX_ROUNDS` untouched.

### What the rebalance cost, which is the bit worth reading

**Sixteen of the game's own tests broke.** Not a surprise, and mostly not a problem — a golden-value test is *supposed* to break when you change balance, that's the entire job. But the sixteen split into two very different groups, and the split is the lesson.

Some were tests that genuinely encode balance: "seed *vanguard*, all-out attack, player wins round 8 at strength 7". Those have to be recomputed by hand every time, and that's fine — that's the price of having them, and they're the reason I know the retune did what I meant rather than something else.

The rest were tests that had simply *hardcoded* the number. A table of "at strength 20 the AI does this, at 11 it does that", written as literals, when the AI's actual rule is a formula over the starting strength. Those didn't need rethinking, just rewriting in terms of the constant — and now they'll survive the next retune untouched. **Same lesson as before, one level down: it isn't enough for the game to keep its tuning knobs in one place if the tests reach past them and grab the raw number.**

One test needed more than a new number. The "both sides destroy each other simultaneously" case used a seed that no longer produces that outcome — so it would have kept passing while quietly testing something else entirely. Swept for a seed that still does, and swapped it. Another one was checking a player victory on a seed that now resolves the other way; same treatment. Those two are the dangerous kind, because nothing goes red, the test just stops meaning what its name says.

The good news I wasn't expecting: **the AI's difficulty formula scaled correctly on its own.** It computes defense from the starting strength rather than a baked-in 20, so it retuned itself. That's the earlier "all the balance numbers are real constants" claim actually being *tested*, which is different from being true on inspection.

### Then the test harness broke too, in a useful way

Three rungs went red. The spike and R1 were asserting "the battle starts 20 v 20" — hardcoded, exactly the sin I'd just finished pointing at in the game's tests. Fixed properly: the harness now reads the constants out of the game's own source, so the next retune needs no edit on this side either. And one invariant had been checking strength stays within 0–20 while the real ceiling was now 12 — a bound eight points too loose, which is a check that had quietly stopped being able to fail.

R2 broke for a much better reason. Its "this battle ends in a draw at the round cap" case used the default seed — **and the retune worked well enough that the default seed doesn't draw any more.** It resolves on round 8 now. Had to go find a seed that still reaches the cap so that arm keeps getting tested. A test failing because your fix succeeded is a good day.

### What's still wrong, filed not fixed

The retune fixed draws. It did **not** fix strategic depth, and running the sweep made that obvious in a way I hadn't seen before: all-out attack wins 35 games out of 60, a balanced allocation wins **1**. So the choice you make every round isn't really a trade-off, it's just a question with a right answer, and the right answer is always "attack".

That's a deeper problem than the draw rate and it isn't a constant you can turn. It comes from the damage model — your defense hits subtract from their attack hits — which means two cautious players converge on nothing happening. Fixing it properly means changing how damage works, which is a design decision and a different day's work. Logged in the integration notes and in R2's output so it can't get quietly forgotten.

More will land here as we keep going. The full technical write-up, including the findings that are only useful to Claude, stays in [`integration/README.md`](integration/README.md).

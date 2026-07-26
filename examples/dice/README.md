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

## How we settled the depth problem — and the lesson I'm taking to every other project

This is the part I'd want someone else to read.

The depth problem wasn't a number I could turn, so there was nothing to test my way out of. It was a design call: change how damage works, or don't. Normally that's where I'd pick whichever fix sounded most convincing, build it, and find out in a week. I've got projects that have been in that loop for over a year.

Instead we did three things, in order.

**Got independent opinions.** Two reviewers, same prompt, separate context, neither able to see the other's answer. I used two different models here, but the axis doesn't have to be the model — "game designer" and "competitive card player", or "full-stack dev" and "casual mobile gamer", would work the same way. Getting several angles on a problem has always been how I iterate, and it turns out it's mostly a prompting habit rather than anything you build. Both were told to argue with the premise, not just answer the question — and both did, correcting something I'd got wrong in how I framed it.

**Synthesised on agreement.** Where two independent reviewers land in the same place with different reasoning, that's the strongest signal you can get without running anything. They agreed it was structural, agreed no constant could fix it, both proved it with the AI taken out of the loop entirely, and both independently spotted that the PRD had gone stale. All of that I could just bank. What they *disagreed* on was the actual fix — and each had proposed one the other never tested. That disagreement is what needed measuring.

**Simulated everything before writing a line of game code.** This was the first time I'd asked for this and it's the bit I'll reuse forever. We generated six variants of the engine — every combination of the two proposed rule changes — patched straight out of the real source rather than reimplemented, and ran **3.15 million battles in 50 seconds.** Before touching the game. No edits, no test churn, nothing to unpick if the answer came back "none of these."

Three things came out of it that no amount of arguing would have:

- **The fix that looked best was the worst one.** It equalised every strategy's win rate, which reads like balance until you look closer — the whole strategy grid came back a flat wall of 0.50. It didn't remove the dominant strategy, it removed the *decision*. Choosing well became worth half what it's worth in the shipped game. Its own author's numbers said so; they were just read as success.
- **The other fix's first step, on its own, makes things worse** — because the game's only real decision today is "attack, or turtle for a draw", and killing draws deletes half of that before the replacement exists.
- **Sample size was the whole ballgame.** At 200 games the losing fix looked like the winner. At 5,000 it collapsed. One reviewer had already been burned by exactly this and warned us — its own first pass called a dominant strategy "not dominant" in 33 of 42 configs, and every one reversed at higher counts. **If I'd run the 200 games I originally asked for, I'd have shipped the wrong fix.**

The rig got checked before we trusted it, too: one reviewer had predicted, blind and in advance, that a particular variant would produce ~79% draws. The simulation returned 81%. That's what made the rest of the table believable.

**The real lesson isn't about dice.** You can't simulate a branching narrative game end to end — but you can absolutely simulate its combat maths, its XP curve, its drop tables, its economy loop. Those are pure functions sitting inside games that aren't. Sweep the subsystem, not the story. Data instead of best-guess-then-fix-for-a-month is an enormous saving in time, in tokens, and in the specific misery of discovering three weeks later that the plausible fix was wrong.

Written up properly as [`LESSONS.md` §D](../../LESSONS.md) so it applies to every game we test, not just this one.

## Fix #3 — the change itself, and what it cost

Three edits, all in `engine.js`: a defense hit now cancels **two** attack hits (`DEFENSE_BLOCK = 2`), the round-12 cap **decides on force strength** instead of drawing, and starting strength went 12 → 8 to bring knockouts back. Twelve rounds still held.

What it bought, measured on the shipped engine rather than the simulation: decisive rate 50% → **91%**, and the thing that was actually broken — all-out attack now **loses** at 216 wins in 500 while a balanced allocation **wins 289**. The peak moved from a corner to the middle. Choosing well is worth 0.131 where it used to be worth 0.000.

Then the bill came in, and it's the same shape as last time but bigger.

**Seven game tests broke**, splitting the same two ways: real goldens that got recomputed by hand, and tests that had hardcoded a number where the rule is a formula. Two were the dangerous kind *again* — the "both sides destroy each other" case had drifted onto a seed that no longer does that, for the second retune running. It's now got a comment saying so, because twice is a pattern.

**The harness caught something I'm glad it caught.** R1 failed on two checks that isolate the bonus-dice rules. Not a bug — at starting strength 8 both sides drop under the "dug in" threshold by round 3, so "+2 means reinforcements alone" stopped being true. The rung was refusing to certify an isolation that no longer isolated, which is precisely correct behaviour, and the fix was to find a line where the windows still exist rather than to loosen the assertion.

**R2 grew.** The cap deciding on points is a genuinely new way for a battle to end, so R2 went from two terminal arms to three — knockout, points decision, exact-tie draw — and from 10 checks to 14. There's a rule in our lessons file that says if a gate returns its old check count after the game gained a system, it never tested the system. That's this.

**And it found a real hole in the harness.** The first ladder run after the change came back almost entirely green — against a **stale build**. The tests drive the compiled bundle, nothing checked the bundle was newer than the source, and it cheerfully reported `12v12` in a passing line while the source said 8. So the ladder was certifying code I wasn't shipping. There's now a freshness check that refuses to serve a `dist/` older than `src/`, and I made it fail on purpose before believing it. Same class of mistake as the stale-server one we already had a rule for, one layer up.

The player briefing needed rewriting too, and that one would have been expensive to miss: it still taught "the cap is a draw, so race for the kill", which after this change is *actively wrong advice*. An LLM playtester reading it would have played the old game badly and I'd have blamed the model.

Suite back to 157/157, ladder green at 19 · 9 · 12 · 14 · 11, `ugt verify` 4/4.

## The thing that keeps happening: testing the game keeps improving the tester

I want to flag a pattern, because it's turned up in nearly every session and it wasn't something I planned for.

Every time we point UGT at one of these games, we find something wrong with **UGT**, not just with the game. Not as a side effect either — the game is the thing that exposes it. This file alone has: a browser adapter that couldn't see a battle end, a feature-map entry that only passed because of that bug, a harness asserting a bound eight points too loose, a gate certifying a stale build, and a rung whose premise quietly expired. All of those are tester defects, surfaced by a dice game that fits in one file.

The best example landed today. I asked a sanity-check question — *is the "exploit hunter" actually hunting exploits, or is it just checking the boxes we drew for it?* — and the answer was: just the boxes. It had exactly two detectors, crashes and whatever invariants a human had written for that specific game. It never searched for anything. And the proof was sitting right here: **dice passed that rung 11/11 for weeks while one allocation strictly dominated every other and the game's only decision was meaningless.** Green the whole time. That's not a subtle miss, that's the headline problem in the game, and the tier named after finding exploits didn't have a shape for it.

So two things changed. It's now called an **invariant fuzzer**, which is what it actually is — random input against an oracle. The old name was quietly making promises. And every game now inherits a floor of framework-owned checks that need no configuration at all: fields that only ever go up (the farmable-resource smell), states the game can return to forever, actions that never do anything, same-input-different-output, and runs that barely move. They report rather than fail, because "is this a counter or a resource?" is a question for a person, not a verdict.

Ran it against the card game as a second opinion and it immediately flagged three things, all correct: two graveyard counters that genuinely only go up (fine — cards don't come back), and two actions that never change state (also fine — they're deliberate illegal-input probes). No noise, and each one obvious to disposition. That's the bar I wanted.

**And this is why I picked three games in three different genres on three different transports.** Dice is React in a browser, the escape room is Node over a subprocess, sokoban is Godot over TCP. It isn't variety for its own sake. Every one of them stresses a different part of the tester, and each keeps handing back a defect the others couldn't have shown me. A browser bug doesn't surface in a subprocess harness. The stale-build hole only exists because browser games ship a compiled bundle. If I'd built three versions of the same thing I'd have found roughly a third as much.

The tests are getting better because the games are getting tested. I'd rather ship one genuinely strong UGT off the back of three small honest games than a big one that's never been argued with.

More will land here as we keep going. The full technical write-up, including the findings that are only useful to Claude, stays in [`integration/README.md`](integration/README.md).

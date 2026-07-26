# Tiny Escape Room

A ten-room text adventure. You start in a holding cell and you're trying to get out through the courtyard gate. Along the way there's an iron key, a lantern with a dry wick, a flask of oil, a valve wheel, a bronze cog, a ledger and a skeleton key — and they only work in one order, because each one is gated on something the previous one set. Eight links in the chain. There's no combat, no monsters, no timer, and no way to lose. You either escape or you're still wandering.

The whole adventure is two CSV files. Rooms in one, objects in the other. You write a new adventure by editing spreadsheets, not code — that was the point of building it this way.

It's here because it's the **subprocess** example, the one where UGT talks to a Node process over stdin and stdout in newline-delimited JSON. No browser, no sockets, no compiled bundle. It's the simplest transport of the three and it's the one where the least can go wrong, which turned out to matter later.

## Running it

Just node, nothing else. No dependencies at all — the CSV parser is about forty lines that came with the game.

```bash
cd game
npm test               # 85 tests
npm start              # play it yourself
```

Playing it yourself is worth doing once. It's a real text adventure — `take lantern`, `go north`, `use valve wheel`, `look`, `inventory` — and the puzzle chain is genuinely a puzzle. The walkthrough is 26 moves if you know exactly what you're doing.

For the tests, I ask Claude to run the escape-room ladder rather than typing anything. Five rungs: a **spike** that talks to the raw pipes with no test framework in the way, a **smoke** run that does the same thing through UGT's adapter, then **R1** (one complete escape), **R2** (every action, every object, every locked door from both sides), and **R3** (a couple hundred random moves with everything re-checked after each one). What each rung actually asserts is in [`integration/README.md`](integration/README.md).

## How it got built

Same shape as the dice game: a PRD first, then a TASKS.md the orchestrator could climb, then I opened a session in `game/` and let it run. Five tasks — scaffold, the CSV loader, the actual adventure content, the command engine, and the human CLI. Every task its own commit.

Two things I'd carry forward:

**Writing the content format down as a table before writing any code was the best decision in this one.** Every column in `objects.csv` is a rule — `use_requires_flag`, `use_sets_flag`, `use_consumes`, `take_sets_flag`. Once those existed, the puzzle chain was just data, and the engine never needed to know that a lantern needs oil. It also meant the tests could later derive what they were checking from the CSV instead of hardcoding it, which paid off in a way I'll get to.

**Validating the content at load time was worth more than I expected.** The loader refuses to start if an exit points at a room that doesn't exist, or if a door is gated on a flag that no object ever sets. That's a whole category of broken adventure that simply can't ship. I'd put that in anything content-driven from now on — it's about thirty lines and it catches the mistakes you actually make while authoring.

## What testing turned up

Here's the awkward bit. **This game had been "tested" for a while and it wasn't really on the ladder at all.**

It had passing results — the config-driven `ugt verify` reported 6 of 6 features green, and there was a hand-written fuzzing script that came back clean over two seeds and 320 steps. All true, all still true. But it was the only one of the three examples that had never had a spike, never had a proper smoke rung, and had nothing at all in the "R2" slot. It had arrived at roughly the right place by a different road, and nobody had noticed it was the odd one out.

So we built the five rungs properly. That took a session, and it found a lot more than I'd have guessed for a game with no combat and no randomness.

### The smoke test was passing on a frozen game about half the time

This is the one I'd tell someone else about.

UGT's built-in smoke test sends five random actions and checks the wiring's alive. Fine for most games. This game has 41 actions, and from the starting cell only **six** of them do anything — you can go north, look, check your inventory, and poke at the two things in the room. Everything else is "you can't do that here", and this engine is deliberate about refusals costing *nothing*: not a move, not a counter, not a byte of state.

So five random actions leave the game completely frozen about 45% of the time, and the smoke test prints "fully operational" anyway. I ran it three times in a row to check and the state never moved in two of them.

Nothing was broken. That's what makes it bad — a green light that means "the pipe is open" while looking exactly like a green light that means "the game works". The new smoke rung drives five moves I know are good and fails if any of them does nothing. And the 45% is computed inside the rung rather than written in a comment, so it stays honest if the content changes.

**This isn't an escape-room problem.** Any game with a big action space where most actions are context-gated has the same hole, and that's most adventure games, most RPGs, most strategy games.

### Random play can't finish this game, and that's fine

The random-input rung reached **nine distinct states and two of the ten rooms** in sixty moves. Never escaped. Never got close.

That's not a defect, it's arithmetic — a uniform random policy is not going to walk an eight-link dependency chain in the right order. But it's the clearest illustration I've got of why these tiers aren't interchangeable. The random tier proves the game doesn't *break* when you feed it nonsense. It cannot tell you the game is *completable*. Only the scripted rungs and, later, an LLM reading the strategy guide can do that.

The rung now prints its own reach every run, so nobody can read a green R3 as "the game works".

### The gap was R2, and it was bigger than I thought

The old feature-map playthrough touched **17 of 41 actions**. The other 24 had never been driven by anything at all: every `examine`, every `drop`, `look`, `inventory`, `go_south`, and all three red herrings.

That last group is the interesting one. There are objects in this game whose entire job is to be useless — a torn map scrap, a rusted helmet, a stone mural. Untested content that's supposed to do nothing is indistinguishable from content that's broken. You'd never find out.

R2 now issues all 41 and checks what each one actually does. The check I'm most pleased with is take → drop → **re-take** on every portable object, because a `drop` that quietly *deleted* the item would look identical to a working one if you only checked the inventory afterwards. And it now proves every locked door from both sides — the same command refused before you have the prerequisite and accepted after, for all five gated objects, where the old feature map could only manage that for the lantern.

That rung runs 552 commands and passes 47 checks.

### The two bugs that were already found, and had nothing pinning them

While the game was being built, the machine-facing bridge turned up two defects that only exist at the wire level. One where a whole batch of piped input got answered even after a shutdown command. And a worse one where the process wouldn't exit while the parent was still holding the pipe open — which is exactly how UGT runs it, so every test run would have hung forever.

Both were fixed at the time. Neither had a test guarding them. They were written down in a commit note and that was it.

The spike now checks both, and checks the second one the way it actually broke, with the pipe deliberately left open. That's the argument for having a spike rung at all: it's the only place that talks to the raw wire, and wire bugs don't show up anywhere else.

### I was wrong before the game was

R1 went red the first time I ran it, on an invariant I'd written myself: "if you've escaped, you must be standing in the courtyard". But the courtyard has an exit going back south, and escaping is *sticky* by design — the PRD says so. You can walk back inside and the flag stays true. So two of my own invariants were contradicting each other, and the game was right. It now checks the *transition* — you can only ever become escaped in the courtyard — which is compatible with stickiness and still catches winning from the wrong room.

(R2's first run went red on a bad assertion of mine too, a miscount. Detail's in the integration notes; it isn't interesting twice.)

The lesson is already in our rules file: **suspect your own test before you suspect the game.** The failure I *want* is the game being wrong. The failure I keep getting first is me.

## What this fed back into UGT

Three things, and this is the part of the process I actually care about — the game is the instrument, and what it measures is the tester.

**`ugt verify` reported failures and then exited zero.** If a feature failed, the report said so — `passed 5, failed 1` — and the shell still saw success. Every example's build gate is worded "exits 0 with 0 failures", so a gate checking the exit code was waving red runs through. I confirmed it by inverting an assertion and watching it happen rather than taking an earlier note's word for it. **Fixed.** Before believing the fix I ran the negative control (inverted assertion → exit 1, clean map → exit 0) and then re-ran every integration in the repo that has a feature map, to find out whether anything had been quietly red all along. Nothing had — all three were genuinely green. That was worth knowing either way.

**The smoke test's random probe is the wrong instrument for a game like this.** Five random actions out of 41, when only six do anything from the opening cell, means a ~45% chance of proving nothing. The new smoke rung fixes it for the escape room by driving a known-good script, but the general problem belongs to UGT and it's now written up as a rule so the next game inherits the warning instead of rediscovering it.

**And the seed question turned out to be a design flaw, not an escape-room quirk.** My first instinct was to write "this game has no seeds, that's fine" in a comment here and move on. That's wrong, and it's wrong in a way worth spelling out: UGT decided whether episodes were independent samples by checking whether a seed list *happened to be present in the config*. Absent meant two opposite things. Either "this game is deterministic and one playthrough is the honest sample" — true here — or "I forgot to configure seeds and I'm about to publish a win rate whose denominator is eight and whose real sample size is one." Identical in the config file, identical in the report.

So the game now **declares** what it is — `deterministic`, `per_episode`, or `uncontrolled` — and UGT **proves the declaration against the running game** before spending anything. Declare deterministic and it checks two resets really do replay identically. Declare seeded and it checks two seeds really do diverge *and* that one seed reproduces itself, because a reset hook returning random state would pass the first test and be equally broken. It even refuses a probe that never moves the state, since "identical" proves nothing if nothing happened.

The bit I'd underline: **that proof already existed, in the dice game's own playtest script.** It had been sitting there for a week doing its job perfectly for exactly one game, which meant every other game in the portfolio had no such check and nobody had noticed. Anything you'd end up writing into every integration belongs in the framework instead, keyed off a declaration the game makes. That's the difference between universal and configurable, and configurable is the one that's actually achievable.

The pattern from the dice write-up holds. **Pointing the tester at a game keeps finding things wrong with the tester** — and a game with no combat, no randomness and no way to lose still found three. Different transports and different genres stress different parts of it; the browser game found bugs a subprocess game structurally cannot, and this one found a probe design that a four-action puzzle would never have embarrassed.

## Where it's up to

Ladder green at 27 · 12 · 17 · 47 · 10, game suite 85/85.

The LLM tier is wired and the briefing is written, but hasn't been run — that one costs real money per action, so it waits for a deliberate decision rather than happening as a side effect. The local free rehearsal comes first, same as the dice game.

When it does run, it's measuring **competence, not balance**: did the model escape, and in how many moves against the 26-move optimum. There's no win rate to quote here and the config now says so out loud.

The full technical write-up, including the findings that are only useful to Claude, stays in [`integration/README.md`](integration/README.md).

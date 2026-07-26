# Tiny Escape Room

A ten-room text adventure. You start in a holding cell and you're trying to get out through the courtyard gate. Along the way there's an iron key, a lantern with a dry wick, a flask of oil, a valve wheel, a bronze cog, a ledger and a skeleton key — and they only work in one order, because each one is gated on something the previous one set. Eight links in the chain. There's no combat, no monsters, no timer, and no way to lose. You either escape or you're still wandering.

The whole adventure is two CSV files. Rooms in one, objects in the other. You write a new adventure by editing spreadsheets, not code — that was the point of building it this way.

It's here because it's the **subprocess** example, the one where UGT talks to a Node process over stdin and stdout in newline-delimited JSON. No browser, no sockets, no compiled bundle. It's the simplest transport of the three and it's the one where the least can go wrong, which turned out to matter later.

## Running it

Just node, nothing else. No dependencies at all — the CSV parser is about forty lines that came with the game.

```bash
cd game
npm test               # 104 tests
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

That rung runs 570 commands and passes 56 checks.

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

The pattern from the dice write-up holds. **Pointing the tester at a game keeps finding things wrong with the tester** — and a game with no combat, no randomness and no way to lose has now found four. Different transports and different genres stress different parts of it; the browser game found bugs a subprocess game structurally cannot, and this one found a probe design that a four-action puzzle would never have embarrassed, plus a reset path that threw away the opening screen for *every* subprocess game, not just this one.

## Where it's up to

Ladder green at 30 · 12 · 18 · 56 · 10, game suite 104/104, `ugt verify` 6/6. All five rungs were re-run from scratch on 2026-07-26 rather than taken from the table — the numbers in it had drifted by one in three places, because the pre-flight had added tests to the game and a check to R1 after the table was written. Worth knowing that a results table goes stale silently: it doesn't fail, it just quietly stops being true. Then they were re-run *again* after the fixes below.

The local free rehearsal has now been run, and it's the interesting part.

**The pilot got lost.** Thirty actions on the local model, and it opened the iron door and then spent its last twelve moves in the storeroom trying to walk north through a wall. Four rooms out of ten, no escape. Its own reasoning gives it away — it kept saying things like "I am currently in R04 (Guard Corridor)", and R04 is the Storeroom. It had the room codes and it had the prose, and it never reliably joined them up.

Some of that is just a small local model, and I can't tell how much from the outside. But two things are asymmetries I could measure directly, by running the same commands through the human CLI and through the wire and diffing what came back:

**It starts blind.** A human's first screen is the cell description — the room, the exits, the map scrap lying there. Over the wire, `reset` sends state and no prose at all, so the pilot's text panel is empty on its first decision. It has to spend a move on `look` to see the room it woke up in, and nothing tells it to.

**It never learns the room's name.** The state says `current_room: "R04"`. A human is never shown a room code in their life — they're shown "Storeroom", every time they walk in. So the one field that's supposed to say where you are says it in an internal id, and the name is only in prose that scrolls.

Both are the same shape as the big finding from the pre-flight — the wire client seeing less than the person does — which is mildly annoying given that's exactly what that audit was for. It checked whether the narration channel existed. It didn't check whether the channel was *complete*. That's the lesson I'd actually keep: **"is there a channel" and "does the channel carry everything" are two different audits, and passing the first one feels exactly like passing both.**

Both are now fixed. Reset sends the opening room, and the state carries the room's name next to its id. There's a new invariant that checks the id and the name against the CSV on every single move, so they can't quietly drift apart again, and I checked the fixes were load-bearing by deleting them and confirming ten tests went red.

**Then I ran the same thirty actions again, and it's a different game.** Every room correctly named in the reasoning. Auto-flagged bugs went from two to zero. It got through the iron door and two rooms deeper, and then it did the thing I actually wanted to see: it tried to light the lantern, got told the wick was dry, and worked out on its own that it needed to go and find oil. That's the game's authored refusal text doing its job on a machine player, which is the whole reason the narration channel matters.

It still didn't escape in thirty moves — but the walkthrough is twenty-six, so thirty was never really a fair budget. I gave it a hundred, which is the local ceiling, and it got **six of the eight locks open and eight of the ten rooms** in fifty-nine moves. Through the iron door, lantern lit, steam vented, cog in hand, ledger read, hour learned.

Then it stopped one step short, and where it stopped is the most interesting thing this game has told me yet.

**Every object in this game explained itself when it refused you. Every locked door didn't.** The objects had authored refusal text in the CSV — *"The wick is bone dry. Without oil it will never catch"* tells you exactly what to go and find, and that's why it got six locks open. Doors all shared one line: *"The way is shut. You are missing something you'd need to pass."* There was no column in `rooms.csv` to say anything more specific, so a door literally could not tell you what it wanted.

It finished standing in the clock room, holding the cog, already knowing the hour — both halves of the answer — hammering the blocked door instead of using the cog on the clock in front of it. It wasn't starved: it had everything. But the door was what it kept asking, and the door was the one thing in this game that never answered. It even read the two refusals correctly and separately: it worked out that a listed-but-blocked exit is a lock rather than a wall. It just had nowhere to take that.

I nearly filed that as "doors are meant to be mute, objects carry the teaching" and moved on. That was wrong, and tracing the map properly is what showed it.

**Three of the four doors were already fine** — the *room* description carries the hint. The corridor says a banded iron door blocks the way north. The furnace room says steam hisses up the shaft you want to climb. The antechamber says the gate is shut fast. Only the clockwork gallery lied: it described the north stair as simply climbing away, then refused it with no reason. One door out of four, not a design philosophy.

So doors now say what kind of lock they are. There's a new column for it, and the loader **refuses to start** if a locked door doesn't have one — same trick as the existing content validation, which is turning out to be the best thing in this game. It also refuses hint text on a door that isn't locked, because that text could never be shown and dead content is the thing I keep finding.

**Then tracing the chain turned up something that had been wrong the whole time.** The antechamber was locked behind the clock *and* the skeleton key needed the clock — the same lock twice. Which meant you could never stand at the gate and just *try* the key, so the key's best line — *"The key turns a quarter and stops. Something heavier than a lock is holding this gate."* — could never be seen by anybody. That's the line that sends you looking for the bolt. It was written, it was good, and it was unreachable.

The fiction already said which way round it should be: *"the drawn bolt lets the key turn at last"* — the bolt is part of the gate, not the stair. So the stair is open now and the chain finally reads: reach the gate, it wants a key; find the key, something heavier is holding it; find the bolt, the clock drives it. Four beats, each naming the next. Twenty-six moves, same as before.

**Two more things fell out of the same trace, and both are worse than the door was.**

`objects.csv` has a `use_verb` column — `unlock`, `light`, `turn`, `fit`, `read`. The engine never read it. It only checked the column wasn't empty. So the game had been carefully authoring a verb for every object and then refusing to accept any of them: `read ledger` got you *"I don't understand that."* Exactly the thing you flagged — a person types the obvious word and the game says no. Those verbs are real commands now, each on the object that declares it.

And puzzles had no geography at all. `use` checked that you held the thing and that the prerequisite was met, and never once checked where you were standing. **You could unlock the banded iron door from inside your cell, two rooms away, and the game would tell you the door swings open while you sat on the bunk.** A key belongs at its door now. The lantern and the ledger don't — you light a lamp in your hand and you read a book anywhere — which felt like the right line to draw.

The nice part: the walkthrough I'd committed weeks ago already did every puzzle in its proper room. The geography was always the intent. The engine just never asked.

### And then it got out

Same model, same hundred moves, after those three fixes. **It escaped.** All eight locks, all ten rooms, out through the courtyard gate in thirty moves against a twenty-six move optimum.

The run before this one stalled at six of eight while already holding both things it needed. So this isn't the model having a better day — it's the same model doing the same job with a game that finally answers when you knock on a door.

I'm not going to quote the thirty as a score. It's a local model, and the rule I set for myself is that free local runs prove the plumbing and paid runs produce numbers. What it does prove is the thing I actually wanted: a player who knows nothing except what the game tells them can finish it. That was not true this morning.

One last thing from the log, and it's a nice one. The pilot got hold of the oil flask and tried to `use` it on the lantern. Seven times. There's no such command — taking the flask is what gives you the oil, and it's the *lantern* you use. UGT threw the invented action away rather than quietly running the nearest real one, and the repeat guard cut the loop off deterministically instead of asking the model again. That's all working as designed. But it's also the single most natural thing a person would type, and the one place in the chain where the game has no verb for what the player is picturing. I haven't decided if that's worth an authored refusal. It's on the list.

Nothing measured before those fixes is poolable with anything after. I kept both runs, because the pair is the finding.

When the paid tier does run, it's measuring **competence, not balance**: did the model escape, and in how many moves against the 26-move optimum. There's no win rate to quote here and the config now says so out loud.

The full technical write-up, including the findings that are only useful to Claude, stays in [`integration/README.md`](integration/README.md).

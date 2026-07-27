# Sokoban Mini

Push crates onto targets. Three levels, one box then two then three, four directions and an R to start the level over. You can't die, there's no timer, and the only number the game keeps is how many moves you took. If you wedge a box into a corner you reload the level and try again — which sounds like the most obvious sentence in this file, and it's in here because the game didn't actually do it until the tester asked for it. That's further down.

It's built in Godot, and it's here because it's the **custom** example — the one where UGT has no built-in adapter and you write your own. Dice is a browser page, the escape room is a Node process on a pipe, and neither of those shapes fits a game engine: Godot isn't a web page, and its frame loop can't sit blocking on stdin the way a script can. So the game opens a TCP socket, polls it once per frame, and the harness dials in. About a hundred and fifty lines on each side.

That's the case I wanted a worked example of, because it's the one UGT can't do for you. The other two examples are mostly config; this one is the pattern you copy when the framework has no adapter for your engine.

## Running it

You need a Godot 4 binary called `godot4` on your PATH. That's the whole dependency list, and it's also the first thing that broke — Homebrew installs it as `godot`, the task list expected `godot4`, and the very first run died on a name mismatch before touching a line of game code. It's a symlink to fix:

```bash
ln -s "$(command -v godot)" /usr/local/bin/godot4
```

Then:

```bash
cd game
godot4 --headless --editor --path . --quit     # regenerates the import cache on a fresh clone
godot4 --headless --path . -s tests/run_tests.gd   # 99 tests, ~17s (see below)
SOKOBAN_SKIP_SLOW_TESTS=1 godot4 --headless --path . -s tests/run_tests.gd   # ~0.7s, drops one search
godot4 --path .                                # play it yourself, arrow keys or WASD
```

For the ladder I don't type anything — "run the sokoban ladder and show me the footers" does it. Five rungs: a **spike** that talks to the raw socket with no adapter class involved, a **smoke** run that does the same round trip through the adapter, then **R1** (level 1 solved for real), **R2** (all three levels through to the end, plus deliberate no-op probes), and **R3** (240 random steps across two seeds with every invariant re-checked after each one). No rung needs a server started by hand — each one spawns its own Godot, waits for it, and reaps it. What each rung asserts is in [`integration/README.md`](integration/README.md).

## How it got built

Same as the other two: a PRD, then a TASKS.md the orchestrator could climb, then I opened a session in `game/` and let it run. Eight tasks — scaffold, test runner, level format, the move rules, the three levels, human input, and the machine bridge.

The interesting part happened *before* the run, though, and it's the one I'd carry to every project.

**The task list added a dependency the PRD never asked for.** I had Claude review the task list before starting it, and the review found GUT in the gate line and in T-001. GUT — Godot Unit Test — is a real, well-established, MIT-licensed Godot addon, and there's nothing wrong with it; I use this example to make a point about *how it got there*, not about the framework. Nobody had asked for it. The PRD mentioned testing exactly zero times, so the task list filled the hole with the most plausible thing it knew, and did it with no source, no version and no license note.

That hole ends badly in one of two directions. Either the coder stops mid-run to go and vendor a hundred files of someone else's addon, or — worse — it writes something GUT-shaped itself to keep moving, and a stand-in test framework that always exits 0 makes **every gate in the file vacuously green**. Replaced with a forty-line runner specified in full in the task, plus a shell script that writes a deliberately failing test and checks the runner actually exits non-zero. A runner that small is only trustworthy with a negative control.

The real lesson isn't about GUT at all. **If your PRD doesn't say how the thing gets verified, the task list will decide for you, and it'll decide in whatever direction is most plausible rather than whatever you'd have picked.** The PRD has a "Verification" section now, and "no third-party Godot addons" is an explicit non-goal — a deliberate call for a three-level demo, not a judgement on the addon.

**The same review found the tasks in an order that couldn't fail honestly.** Level authoring came before the move rules, so its "prove each level is solvable" acceptance had no engine to run against — the old task admitted it, calling itself "a structural check, not an executed one". A bad level would sail through its own gate and then surface later as a *rules-engine* failure, sending three rounds of debugging at `try_move()` while the actual defect sat in a text file. Authoring moved after the rules, and it now replays a committed `solutions.json` through the real engine. Deferred failures always land on the wrong task.

**And I got the scope boundary wrong at first.** All three example games originally carried their UGT bridge inside their own PRD and task list — a "hooks required" section, a task to build the machine-facing surface, constraints written against what the harness expected. That's backwards. The integration is a separate job, usually a separate repo, often a separate person. Bundling them here was a teaching convenience that quietly taught the wrong thing, so the game docs now describe only the game and everything wire-shaped lives in `integration/`.

## What testing turned up

### The readiness check was breaking the thing it was checking

This is my favourite one out of the whole example set.

The bridge accepts **one client at a time**. The first version of the process launcher waited for boot the obvious way — dial the port in a loop until something answers. Which consumed the single connection slot. The real client then arrived while the bridge was busy re-accepting and got `ConnectionResetError`.

What made it nasty is how it presented. Not as a bug — as **flakiness**. The spike passed and the smoke test failed, run after run, and the reason was that the spike happened to shell out to `lsof` in between, which gave the bridge just enough time to recover. So the symptom depended on the timing of an unrelated diagnostic command.

Readiness is now read out of the OS socket table without connecting at all, and exactly one real connection gets made. **A liveness check that consumes the resource it's checking is not a liveness check** — and because it fails on timing, it'll look like a flaky test rather than a broken one, which is how it earns weeks of being ignored.

### Two of my own checks could never have failed

I asked for a self-audit — "there should be no shortcuts in the test process" — and it found two green checks that were decorative. Both had been passing since the day I wrote them.

**"The solution actually moves boxes"** compared the box-on-target count with `>=` against the previous one. That's true after *any* move, including standing still against a wall. It could not go red. Proven rather than argued: a walk that goes right and left along an empty row, never touching a box, satisfies the old version and fails the new one.

**"A blocked box push is refused"** was worse, because it was testing something real — just not the thing its name said. It probed for "any direction that does nothing" and took the first hit. On level 1 the player starts with a wall directly beneath them, so it found `down` every time. A wall. It had been re-testing the wall check while reporting the box-push check as covered, in **both** R1 and R2. The blocked push is now constructed deliberately: line up, push the box left once and *assert that push was accepted* so the setup is real, then push again into the wall and require the entire state to be unchanged.

The general rule I keep relearning: **a green you have never seen go red is not evidence.** Both of these looked completely fine in the output. The only reason they got caught is that somebody went looking on purpose.

### There was nowhere to put things that were odd but not wrong

The rungs originally hand-rolled their own pass/fail counters instead of using UGT's gate runner. That's not a style problem. It meant anything the run noticed that wasn't a hard failure had two options: force it into a FAIL it didn't deserve, or drop it. In a repo whose whole thesis is *a failed check is data*, that's a missing capability, and I'd previously written it off as code duplication.

All five rungs use the gate runner now, which brings back the findings channel — and it paid for itself on the very next run.

### The wire couldn't see the boxes — and then it could

R1 raised this one on every single run: the state the game reported had the player's position, how many boxes were on targets, and the move count. **It never said where the boxes were.** So a push that didn't happen to cross a target was completely invisible to a black-box tester. "A box moved" could only ever be evidenced in the same breath as "a box reached a target", which put a hard ceiling on what that check could prove — and is exactly why it was easy to get wrong in the first place.

I left it as a live finding rather than a document footnote precisely so it couldn't get quietly forgotten, and that worked: it's fixed now. The state carries a `grid` — the player-facing ASCII picture, one string per row, the same legend the game draws on screen. R1 now proves "a box moved" on its own terms: the box goes from one cell to another while the on-target count stays at zero, which the old contract had no way to say.

Two things I'd carry from it. **Reading the game's own render isn't re-implementing the game** — the harness looks at a picture the game drew, which is what a human does; parsing the level file to work out where the walls are would have been the other thing entirely, and that's the line I care about. And the fix came out of the LLM tier prep rather than the ladder, because a model needs to be told no less than a human at the keyboard, and a human can see the boxes.

The broader habit still stands, and it's the reason this got fixed rather than lived with: work out what you genuinely **can't observe** while you're still poking the raw protocol, before you write a confident-looking assertion around a blind spot.

### The PRD promised a retry that didn't exist

Same session, and this one's a real bug in the game rather than in the wire.

Getting ready to let a model play, I asked what it should do when it wedges a box. A human presses R. So I went looking for R, and there wasn't one — `main.gd` bound the four arrows and WASD and nothing else. The PRD says in as many words that a player can always retry. Nobody had implemented it, every test suite was green, and eighty-four passing tests had never asked.

It took a machine player to notice, because a machine player *has* to have an answer to "now what" — a wedged box ends its episode, so the missing capability is fatal rather than annoying. A human just sighs and quits to the menu.

Both sides got it: the wire has action 4, the keyboard has R, and both go through one shared dispatch on the board so they can't drift into meaning different things. **The general shape: designing for the machine player audits the human one.** The tester didn't find this by running, it found it by being specified.

### The game keeps one number and shows it to nobody

Then I went to let a model play it, and the first question of the checklist — *what
does a human actually see?* — turned up something I'd never noticed in hours of
playing my own game.

The PRD says "no scoring beyond move count". That's the whole scoring system: how
many moves you took. And the game **never displays it.** There's no move counter on
screen, no level number, no "solved!" — the scene is coloured rectangles with no
text in it anywhere. So the one number the game keeps, the player never sees.

It's not a bug in the sense the R key was, because nobody ever wrote down that
there should be a HUD. It's more interesting than a bug: it's a thing that only
becomes visible when you have to write out, explicitly, what information the player
has. I'd been reading the move count off the debug output for days and had stopped
noticing it wasn't on the screen.

Left as a decision rather than fixed — that's a call about the game, not the
tester. What I did fix is the tester's half: the model doesn't get told the move
count either, because a player doesn't. That also happens to be the number I'm
scoring it against, and letting a pilot watch its own metric measures something
other than the game.

### The model can read the rules and can't find the crate

The local run is the free one — it's not measuring the game, it's proving the
plumbing carries what a player sees. The plumbing is fine. The board arrives, in
the panel a player looks at, correctly aligned.

The model, though, is out of its depth, and the *shape* of how it fails is the
useful bit. Over thirty moves it talked about crates sixty-seven times, about
pushing thirty times, about targets thirty-three times — it clearly read the
briefing and understood the game. It moved a crate **zero times**, on a level you
can finish in six moves. And when it stated where things were: its own position,
right every single time; the crate's position, **wrong twenty-one times out of
thirty**.

That split is not random, and it's the finding. Its own position is *handed to it as
two numbers*. Everything else it has to find by counting characters in a row of
ASCII. So it's been given a coordinate system for exactly one object in the world
and asked to place the rest into it by eye, which is precisely the thing a
text-only reader is worst at and a human with a screen never has to do at all.

There are two honest fixes and they go opposite ways: take the numbers away so
everything comes off the board, or put row and column markers on the board so a
reader can count the way a person points. I filed both instead of picking, because
the evidence that would decide it — does the error rate actually drop — needs a
model that can localise at all, and that's the paid run. Choosing now would bake my
guess into the instrument and then measure it.

### Small ones, each of which cost a red run

- **A move counter I was wrong about twice.** I had written down that `moves_taken` starts over when you advance a level, so the "it only ever goes up" invariant got scoped to a single level. It doesn't start over — the counter runs for the whole session, and the game's own test suite says so explicitly. The invariant was *narrower* than the truth, which is the sneaky kind of wrong: it never fired, so it never argued with the note, and both sat there agreeing with each other through a green ladder. The real boundary is that a reload rewinds it to exactly zero and nothing else may take it backwards, which is what it now asserts. **Two artifacts written from one wrong belief will corroborate each other forever.**
- **A no-op check has to compare the whole state.** "The player didn't move" is far too weak for a blocked push — a transport bug can leave the position alone and still tick the move counter. Blocked moves and illegal action ids now both require the entire state dict to come back byte-identical.
- **Two scripts only worked because UGT was installed on my machine.** They put their own directory on the path but not the repo root, so on a bare clone they'd have died instantly with `ModuleNotFoundError`. Found by deliberately running the ladder in a venv with nothing installed — worth doing once per example, and it only takes a minute.
- **Ports are ephemeral and the launcher refuses to attach.** Not the fixed port the PRD specified. Two runs can't collide, and a bridge left over from an earlier build can never be mistaken for the one under test. This repo has already lost an entire campaign to a stale server answering on the expected port.

## What this fed back into UGT

The pattern from the other two examples holds here: pointing the tester at a game keeps finding things wrong with **the tester**.

**Two of UGT's own shared pieces were only ever exercised by a throwaway demo.** The gate runner and the divergence finder — the fail-closed footer, the findings channel, the same-seed replay comparison — were used by exactly one example game that existed to demonstrate them, and by nothing that was actually testing anything. Sokoban hand-rolled around them, which is the honest signal that they weren't pulling their weight. Now all five rungs go through one fail-closed path, and the duplication is gone.

**Letting a model play it found two more tester bugs, both of which quietly stole the model's moves.**

The first is my favourite kind: a limit set for one game silently taxing another.
The local model's replies were capped at 256 tokens. The JSON the tester asks for
puts the *action* first and the explanation after it — so a reply that runs long
gets cut mid-sentence, the JSON won't parse, and the tester throws the whole thing
away and substitutes a do-nothing move. The model had already decided. The cap
deleted the decision.

Why it showed up here and not on the other two games: reasoning about a grid is
wordy. "The player is at (4, 2) and the crate is at (3, 2), so moving left will…"
is simply longer than "attack-weighted, the enemy is at half strength". A dice game
never reached the ceiling. A puzzle game reaches it in the first thirty moves. And
nothing in the summary counts it, so it costs you budget invisibly. Fixed both
ways — a bigger ceiling, and the tester now recovers the action from the truncated
prefix rather than binning it. It refuses to recover an action name the game
doesn't declare, so it can't invent a move, and I checked that by feeding it a
made-up one.

The second is subtler and I like it more on reflection. This game hides two state
fields from the model on purpose — the move count, and the raw board (it gets the
board as a picture instead). The tester has a detector that flags "the state
changed in a way the model didn't predict", which is a good signal for spotting
hidden mechanics. It was comparing against **every** field, including the two the
model is never shown. So every successful move got logged as the model failing to
predict something it had been deliberately denied.

Here it happened to be harmless, because there's a noise filter that ignores fields
changing on nearly every step and both of these did. That's luck, not correctness —
a hidden field that changed on *half* the steps would sit under that filter and get
counted against the model forever. Fixed, and I'd flag the general rule: **if you
deliberately hide something from an agent, nothing downstream may score it on
knowing that thing.**

Worth separating those two, because they're different animals. The first changed
what the model *receives*, so runs before and after it can't be compared. The second
changed only what gets *written down*, so they can. I've seen that distinction
skipped and it invalidates a batch either way — once by pooling across a real change,
once by throwing away a perfectly good comparison out of caution.

**And sokoban is the clean case for the seeding question** that the escape room turned up. This game has no randomness at all: three fixed levels, no generation, no hidden state. Every episode is the same three puzzles in the same order. So however many you run, the honest sample size is one. UGT used to infer that from whether a seed list *happened to be in the config*, which meant "deliberately deterministic" and "I forgot to configure seeds" looked identical. The game declares `deterministic` out loud now, and UGT proves the declaration against the running game before spending anything — including checking that the probe it uses actually moves the state, because "two resets matched" proves nothing if nothing happened. The probe here is `left`, the first move of level 1's committed solution, so it can't bounce off a wall.

## Where it's up to

**As of 2026-07-26**, ladder green at **18 · 11 · 14 · 15 · 7**, game suite **99/99**. Re-run from scratch rather than copied out of the table — the rule in this repo is that a number in a README is evidence about one commit, and a results table doesn't fail when it goes stale, it just quietly stops being true. Which it did: this section used to read `14 · 9 · 12 · 13 · 7` and `84/84`, both true when written, both wrong the moment the wire gained a field and the ladder grew checks to cover it. Two rungs got bigger, and per our own rule that's the point — a gate that returns its old count after the contract changed never tested the change.

Fail-closed is demonstrated on *these* scripts, not assumed from an older run: inverting R1's box-reached-a-target predicate gives `ROUND 1 NOT MET — 13/14 checks passed` and exit 1, and I compared the checksum afterwards to be sure the file went back exactly as it was. Every rung also feeds its invariant suite a deliberately corrupted transition and requires it to complain, because a suite that's never been seen to fail is decoration.

**The LLM tier is built and the local stage has run.** That was the gap I cared
about, because this is the only one of the three examples inside a game engine. A
browser page and a subprocess had both been shown to carry a model's decisions; a
Godot frame loop over a socket hadn't, and *"can a language model play a game
running in a real engine"* is a different question from *"can a harness step it."*

**The answer is yes, and it is specifically the transport that's been proven.** The
model reads a real board, aligned, in the panel a player looks at; it chooses legal
moves; it never broke one of the nine invariants across a hundred and sixty actions
of trying. That's the whole job of the free local stage and it's done.

What the local stage did *not* do is tell me anything about whether the puzzles are
good, because the model never pushed a crate. That's the expected shape of a
stage-one result rather than a disappointment — the free stage proves the wiring and
is forbidden from producing a number, and this is a clean illustration of why: any
figure from it would be a fact about a small local model's ASCII indexing, not about
sokoban.

Four directions, three levels and an R is about the smallest surface that question
can be asked on — no economy, no combat, no hidden state, nothing to read but a grid.
Which is exactly why it's a fair test of the transport: there was nothing else for a
failure to hide behind.

**Stage two, on a paid model, is the open item, and it's now a spending decision
rather than a blocked one.** Everything before it is done: the briefing, the driver,
the fourteen-point checklist worked through and written down, four things it caught
fixed. Two of those four were bugs in the tester rather than the game.

What it'll measure when it runs is **competence, not balance**: solved or not, and moves against the committed 73-move reference. I called that 73 an *optimum* first, in three places, and I hadn't earned it. There was no solver anywhere in this repo, and what the level tests actually pinned was that each committed sequence solves its level, contains no no-op moves, and doesn't win before its own last action. Not that it's the shortest one that could. By the time I looked, the word had already leaked out of a delivery note and into the scorer's own printed label, where "1.37× optimum" reads as a verdict on the puzzles as much as on the pilot. So I retracted it — a claim with nothing behind it comes out, even when it's probably true.

**Then I went and earned it back.** The right place for that turned out not to be the tester: minimality is a claim about the *levels*, so it belongs to the game, and a solver living in the harness would be a second copy of the rules sitting next to the one it's supposed to be checking. `game/tests/test_solution_optimality.gd` breadth-first-searches each level for its true shortest solution and asserts the committed sequence matches — and the transition function it searches with is `board.gd::try_move()` itself, not a re-implementation of pushing. All three sequences came back optimal on the first run: **6, 23, 44**. Which is the outcome I expected, and is exactly why it was worth doing properly rather than asserting; the interesting part isn't the answer, it's that a level author can no longer quietly break it.

It isn't free. Level 3's reachable space is **772,948 states** and searching it through the real engine takes about **16 seconds**, so the game's suite went from 0.4 s to 16.5 s. That's a ~35× regression on a suite I run constantly, so there's an opt-out — `SOKOBAN_SKIP_SLOW_TESTS=1` drops that one search and nothing else, and even then the case still asserts the recorded length, so a padded `solutions.json` is red either way. Opt-*out*, never opt-in: no script, gate or ladder sets it, so the default is always the real thing.

And the scorer still prints "the committed reference". That's deliberate now rather than leftover: the number is a proven minimum, but "1.37× optimum" still reads as a verdict on the level design and not just on the pilot, and only the second is what this tier measures. The control that keeps the word out of the instrument stayed in. It may live in prose, where a reader can see what proves it; it may not be a label on a scoreline.

There's no win rate to quote — the game has no randomness at all, so every episode is the same three puzzles in the same order and the honest sample size is one however many you run. The config already says `seeding: deterministic` out loud for exactly that reason.

The full technical write-up, including the findings only useful to Claude, stays in [`integration/README.md`](integration/README.md).

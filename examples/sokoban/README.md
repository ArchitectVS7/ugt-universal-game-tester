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
godot4 --headless --path . -s tests/run_tests.gd   # 89 tests
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

### Small ones, each of which cost a red run

- **A move counter I was wrong about twice.** I had written down that `moves_taken` starts over when you advance a level, so the "it only ever goes up" invariant got scoped to a single level. It doesn't start over — the counter runs for the whole session, and the game's own test suite says so explicitly. The invariant was *narrower* than the truth, which is the sneaky kind of wrong: it never fired, so it never argued with the note, and both sat there agreeing with each other through a green ladder. The real boundary is that a reload rewinds it to exactly zero and nothing else may take it backwards, which is what it now asserts. **Two artifacts written from one wrong belief will corroborate each other forever.**
- **A no-op check has to compare the whole state.** "The player didn't move" is far too weak for a blocked push — a transport bug can leave the position alone and still tick the move counter. Blocked moves and illegal action ids now both require the entire state dict to come back byte-identical.
- **Two scripts only worked because UGT was installed on my machine.** They put their own directory on the path but not the repo root, so on a bare clone they'd have died instantly with `ModuleNotFoundError`. Found by deliberately running the ladder in a venv with nothing installed — worth doing once per example, and it only takes a minute.
- **Ports are ephemeral and the launcher refuses to attach.** Not the fixed port the PRD specified. Two runs can't collide, and a bridge left over from an earlier build can never be mistaken for the one under test. This repo has already lost an entire campaign to a stale server answering on the expected port.

## What this fed back into UGT

The pattern from the other two examples holds here: pointing the tester at a game keeps finding things wrong with **the tester**.

**Two of UGT's own shared pieces were only ever exercised by a throwaway demo.** The gate runner and the divergence finder — the fail-closed footer, the findings channel, the same-seed replay comparison — were used by exactly one example game that existed to demonstrate them, and by nothing that was actually testing anything. Sokoban hand-rolled around them, which is the honest signal that they weren't pulling their weight. Now all five rungs go through one fail-closed path, and the duplication is gone.

**And sokoban is the clean case for the seeding question** that the escape room turned up. This game has no randomness at all: three fixed levels, no generation, no hidden state. Every episode is the same three puzzles in the same order. So however many you run, the honest sample size is one. UGT used to infer that from whether a seed list *happened to be in the config*, which meant "deliberately deterministic" and "I forgot to configure seeds" looked identical. The game declares `deterministic` out loud now, and UGT proves the declaration against the running game before spending anything — including checking that the probe it uses actually moves the state, because "two resets matched" proves nothing if nothing happened. The probe here is `left`, the first move of level 1's committed solution, so it can't bounce off a wall.

## Where it's up to

**As of 2026-07-26**, ladder green at **18 · 9 · 14 · 15 · 7**, game suite **89/89**. Re-run from scratch rather than copied out of the table — the rule in this repo is that a number in a README is evidence about one commit, and a results table doesn't fail when it goes stale, it just quietly stops being true. Which it did: this section used to read `14 · 9 · 12 · 13 · 7` and `84/84`, both true when written, both wrong the moment the wire gained a field and the ladder grew checks to cover it. Two rungs got bigger, and per our own rule that's the point — a gate that returns its old count after the contract changed never tested the change.

Fail-closed is demonstrated on *these* scripts, not assumed from an older run: inverting R1's box-reached-a-target predicate gives `ROUND 1 NOT MET — 13/14 checks passed` and exit 1, and I compared the checksum afterwards to be sure the file went back exactly as it was. Every rung also feeds its invariant suite a deliberately corrupted transition and requires it to complain, because a suite that's never been seen to fail is decoration.

**The LLM tier still hasn't been run here, and it's the next thing.** Dice and the escape room have both had a model driving them; this one hasn't, and that's the gap I actually care about closing, because it's the only one of the three inside a game engine. A browser page and a subprocess have both been proven to carry a model's decisions. A Godot frame loop over a socket has not, and *"can a language model play a game running in a real engine"* is a different question from *"can a harness step it."*

Preparing for it has already paid for itself twice over without a single model call — the `grid` field and the missing R key both came out of asking "what would a player see, and what could a player do?" — but the run itself is genuinely not done. What's missing is a briefing, a driver script (this is a `custom` engine, so the CLI can't dispatch it), the context budgets, and the pre-flight checklist. That list is written out in [`integration/README.md`](integration/README.md) so it's a task rather than a vibe.

Four directions, three levels and an R is about the smallest surface that question can be asked on — no economy, no combat, no hidden state, nothing to read but a grid and a box count. If it can't work here it won't work anywhere, and if it does work it's the transport that's been proven rather than the puzzle.

What it'll measure when it runs is **competence, not balance**: solved or not, and moves against the committed 73. There's no win rate to quote — the game has no randomness at all, so every episode is the same three puzzles in the same order and the honest sample size is one however many you run. The config already says `seeding: deterministic` out loud for exactly that reason.

The full technical write-up, including the findings only useful to Claude, stays in [`integration/README.md`](integration/README.md).

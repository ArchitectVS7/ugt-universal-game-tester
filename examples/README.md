# Example Games — built with the Orchestrator, tested with UGT

The purpose of these simple games is to demonstrate both the orchestrate skill and the UGT process. I asked Opus to brainstorm a few game types that could be built using the orchestrator, tested with UGT, and had different tech stacks and game types. From it's list I picked three, modified to my liking, and prompted Opus to create each example game's [`game/PRD.md`](game/PRD.md) 

If you were to make a PRD for a game yourself, I would suggest multiple iterations, such as performing simulated focus groups, identifying target audience, doing soft market research, and finding the just right tech stack based on your intended platform. I would clear context and do an adverserial review of the document, even changing models such as copying over to Gemini and ChatGPT. Watch out for bloat, triage features that are 'must have' for the game, and 'nice to have' that can be pushed off until after beta testing, or even after release as an expansion, as you may find yourself running away with too many features all at once. You want something cohesive, playable, engaging. 

[`game/TASKS.md`](game/TASKS.md) In the Orchestrator skills folder is a second folder called 'tasklist' which is used to create a task lost that is compatible with the 'orchestrate' skill. While you can absolute type **/tasklist** followed by a prompt or use the slash command **/tasklist create** to open an interface to create a task list, over the course of many projects I simply prompted Claude to do this. Something like "Create a TASKS.md based on PRD.md that is compatible with the 'orchestrate' skill with tiered milestones" is surprisingly adequate.

For each example game I started a new session in the 'game' folder and simply syped **/orchestrate all**. The system climbed through the list as written, updating as it went. The state you see the TASKS.md files in now is after completion, which includes Claude's comments as it went. Each task also has it's own commit. 

The 'integration' folder in each game is where the UGT harness lives. Typically the game is going to be it's own repository. You do **not** want to continue to bundle your games inside of your local UGT folder! The game gets its own repo. For example my setup looks something like this:

dev/                            # parent directory of all my projects
├── games/                      # All my game repos
│   ├── _UGT                    # Underscore in front of UGT keeps this folder on top
│   │   ├──  examples           # Shipped with repo, where you are now
│   │   └── integrations        # Where my live UGT harnesses go per game
│   │        └── SpacerQuest    # UGT test harness and lesson learned files for my local game    
│   ├── SpacerQuest             # Example local game repo

I used .gitignore to exclude my local 'integrations' folder from being committed to the repository.

After prompting Claude to make the integrations, next was getting each game's base UGT system up and running. The entire process looks something like this:

**First, make the game prove itself before you test it.** Every one of these games has its own test suite, and I make Claude run it and show me the result before we write a single line of harness. Escape-room came back 85/85, sokoban 84/84, dice 156/156. This feels like a wasted step until the one time it isn't — a harness built on top of a game that's already broken doesn't measure the game, it measures the breakage, and you'll spend an hour blaming the test harness. Same deal with extra tools and dependencies, make sure the thing you need is actually installed. Sokoban's entire ladder depends on a Godot game engine, and Homebrew installs it under a different name than the task list expected, so the very first run died on a name mismatch rather than anything real.

**Then learn the actual wire, not the PRD.** This is the step I'd skip if I were in a hurry, and it's the one that pays. I have Claude drive the raw protocol by hand and just *print what comes back* — the real state dict, the real action list, what happens when you send something illegal. Every single game had a gap between what the PRD described and what the wire actually did. Dice's PRD suggested tracking a field that turned out to be unmappable. Sokoban's PRD never mentioned testing at all, which is how a whole test framework got invented out of thin air by the task list. And if the game will hand you its contract directly, take it — escape-room's bridge has a flag that dumps its own action table, and generating the config from that beat transcribing 41 action ids by hand and getting one wrong.

While you're in there, figure out what you genuinely *can't* see. Sokoban's wire reports how many boxes are on targets but never where the boxes are. That means "a box moved" is only observable when it crosses a target — which quietly puts a ceiling on what one of the tests can ever prove. Much better to know that up front than to write a confident-looking assertion around a blind spot.

**Pick the transport.** If the game runs in a browser or as a subprocess, UGT already has an adapter and you just write config. If it's anything else — a game engine's frame loop, a socket, a live server — it's a `custom` type and you write a small adapter yourself. If you're going custom, have Claude write the process lifecycle first: something that starts the game, waits for it to actually be listening, and kills it afterward. Everything else imports that, so getting it right once saves you from six copies of the same spawn logic.

**Now the ladder proper, five rungs, in order.** The *spike* pokes the raw protocol with no adapter class at all — right message shapes, illegal actions do nothing, a message split across two writes still parses, the same actions replay the same way, clean shutdown with nothing left running. The *smoke* run does the same round trip but through the adapter, and proves it cleans up after itself. Then *invariants*: the properties that must hold after every single command, written once and shared by the rest of the ladder so the scripted tests and the random ones can't quietly disagree about what "correct" means. *R1* drives one full loop of the game to a real outcome and checks those invariants after every command. *R2* does every level or mode back to back, plus deliberate "this should do nothing" probes. *R3* turns the invariant-fuzzer loose — a couple hundred random steps across two seeds, illegal inputs thrown in, invariants checked the whole way, and a same-seed replay that has to come back byte-identical.

I run all of these by prompting rather than typing commands. Something like "run the sokoban ladder and show me the footers" is enough, and Claude will run the rungs, read the output, and tell me what broke. That matters more than it sounds, because the interesting part isn't the pass/fail line, it's Claude noticing *why* something passed.

**The part that actually determines whether any of this is worth anything:** every check has to be capable of failing. Not "looks reasonable" — actually demonstrated. Have Claude break an assertion on purpose and confirm the gate goes red and exits non-zero. I got burned by this on sokoban twice in one night. One check compared a counter with `>=` when it needed `>`, which made it true on literally any move, so it could never fail. Another one claimed to test "pushing a box into a wall" but was actually finding a plain wall next to the player and testing that instead — it had been passing all along while testing nothing of the sort. Both looked completely fine in the output. A green you've never seen go red is not evidence, it's decoration.

A few smaller rules that came out of getting them wrong:

- **A "nothing happened" check has to compare the whole state**, not just the one field you were thinking about. A bug can leave the player standing still and still tick the move counter.
- **No manual steps anywhere in the ladder.** If a rung needs you to start a server by hand first, it can't run while you're asleep, which defeats most of the point.
- **Never let a test attach to something that's already running.** If a stale copy of the game is sitting on the port from an earlier build, your run goes green against the wrong code and tells you nothing. Make it refuse and complain instead.
- **Probe the game, don't read its data files** to decide what's true. If the harness parses the level layout to figure out where the walls are, it's re-implementing the rules it's supposed to be testing.
- **Try it once with nothing installed.** That's how we found two sokoban scripts that only worked because UGT happened to already be installed on my machine — on a fresh clone they'd have failed instantly.
- **Keep somewhere to put things that are weird but not failures.** UGT's gate runner has a findings channel for exactly this. Without it, anything odd either gets forced into a FAIL it doesn't deserve or quietly disappears.

**And expect the tests to find things in the tooling, not just the game.** Along the way this run turned up that `ugt verify` exits 0 even when features fail — so any gate checking only the exit code will happily pass a red run. Dice turned out to be nearly undrawable-proof: 205 different attack sequences on the shipped seed and the enemy never dropped below 1 HP, so the round cap decides basically every match rather than the combat doing it. Neither of those is something you'd catch by reading the code. That's the whole reason this process exists — and honestly, finding them is the good outcome, not an interruption.



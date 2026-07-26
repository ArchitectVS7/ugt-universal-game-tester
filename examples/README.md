# Example Games — built with the Orchestrator, tested with UGT

Three games, three tech stacks, three ways of talking to a tester. **The numbers below were re-run on 2026-07-26, not carried forward from an earlier session** — and the same goes for every README they link to. A results table doesn't fail when it goes stale, it just quietly stops being true.

| | Game | Stack | Transport | Game suite | Ladder | LLM tier |
|---|---|---|---|---|---|---|
| [**dice**](dice/README.md) | Dice Duel — allocate six dice between attack and defense, twelve rounds | React + Vite | `browser` (Playwright) | 162/162 | 19 · 9 · 12 · 14 · 13 | local stages done; paid run is a credit decision |
| [**escape-room**](escape-room/README.md) | Tiny Escape Room — ten rooms, an eight-link chain of locks | Node.js | `simulation` (stdio) | 104/104 | 30 · 12 · 18 · 56 · 10 | local pilot **escaped**; paid run not started |
| [**sokoban**](sokoban/README.md) | Sokoban Mini — push three levels' worth of crates onto targets | Godot 4 | `custom` (TCP, hand-written adapter) | 89/89 | 18 · 11 · 14 · 15 · 7 | local stage done — transport proven, model below the floor; paid run not started |

The ladder column is spike · smoke · R1 · R2 · R3, which the rest of this file explains. Each game's own README is a build diary; each `integration/README.md` is the technical write-up, with the per-rung tables and the findings.

The purpose of these simple games is to demonstrate both the orchestrate skill and the UGT process. I asked Opus to brainstorm a few game types that could be built using the orchestrator, tested with UGT, and had different tech stacks and game types. From it's list I picked three, modified to my liking, and prompted Opus to create each example game's `game/PRD.md` (dice's is [here](dice/game/PRD.md)).

If you were to make a PRD for a game yourself, I would suggest multiple iterations, such as performing simulated focus groups, identifying target audience, doing soft market research, and finding the just right tech stack based on your intended platform. I would clear context and do an adverserial review of the document, even changing models such as copying over to Gemini and ChatGPT. Watch out for bloat, triage features that are 'must have' for the game, and 'nice to have' that can be pushed off until after beta testing, or even after release as an expansion, as you may find yourself running away with too many features all at once. You want something cohesive, playable, engaging. 

`game/TASKS.md` ([dice's](dice/game/TASKS.md)) In the Orchestrator skills folder is a second folder called 'tasklist' which is used to create a task lost that is compatible with the 'orchestrate' skill. While you can absolute type **/tasklist** followed by a prompt or use the slash command **/tasklist create** to open an interface to create a task list, over the course of many projects I simply prompted Claude to do this. Something like "Create a TASKS.md based on PRD.md that is compatible with the 'orchestrate' skill with tiered milestones" is surprisingly adequate.

For each example game I started a new session in the 'game' folder and simply syped **/orchestrate all**. The system climbed through the list as written, updating as it went. The state you see the TASKS.md files in now is after completion, which includes Claude's comments as it went. Each task also has it's own commit. 

The 'integration' folder in each game is where the UGT harness lives. Typically the game is going to be it's own repository. You do **not** want to continue to bundle your games inside of your local UGT folder! The game gets its own repo. For example my setup looks something like this:

```
dev/                            # parent directory of all my projects
├── games/                      # All my game repos
│   ├── _UGT                    # Underscore in front of UGT keeps this folder on top
│   │   ├──  examples           # Shipped with repo, where you are now
│   │   └── integrations        # Where my live UGT harnesses go per game
│   │        └── SpaceTrader    # UGT test harness and lesson learned files for my space trading game
│   ├── SpaceTrader             # Example local game repo (a space trading game)
```

I used .gitignore to exclude my local 'integrations' folder from being committed to the repository.

After prompting Claude to make the integrations, next was getting each game's base UGT system up and running. The entire process looks something like this:

**First, make the game prove itself before you test it.** Every one of these games has its own test suite, and I make Claude run it and show me the result before we write a single line of harness. At that point escape-room came back 85/85, sokoban 84/84, dice 156/156 — baselines from *before* any harness existed, which is why they're all smaller than the numbers in the table above; testing the games grew every suite. This feels like a wasted step until the one time it isn't — a harness built on top of a game that's already broken doesn't measure the game, it measures the breakage, and you'll spend an hour blaming the test harness. Same deal with extra tools and dependencies, make sure the thing you need is actually installed. Sokoban's entire ladder depends on a Godot game engine, and Homebrew installs it under a different name than the task list expected, so the very first run died on a name mismatch rather than anything real.

**Then learn the actual wire, not the PRD.** This is the step I'd skip if I were in a hurry, and it's the one that pays. I have Claude drive the raw protocol by hand and just *print what comes back* — the real state dict, the real action list, what happens when you send something illegal. Every single game had a gap between what the PRD described and what the wire actually did. Dice's PRD suggested tracking a field that turned out to be unmappable. Sokoban's PRD never mentioned testing at all, which is how a whole test framework got invented out of thin air by the task list. And if the game will hand you its contract directly, take it — escape-room's bridge has a flag that dumps its own action table, and generating the config from that beat transcribing 41 action ids by hand and getting one wrong.

While you're in there, figure out what you genuinely *can't* see. Sokoban's wire reported how many boxes were on targets but never where the boxes were, which meant "a box moved" was only observable when it crossed a target — a quiet ceiling on what one of the tests could ever prove. Much better to know that up front than to write a confident-looking assertion around a blind spot.

And write it down somewhere that keeps arguing with you, because a known blind spot is a thing you can *fix*. That one got raised on every single sokoban R1 run rather than filed in a document, and it's fixed now: the game hands over the same ASCII picture it draws on screen, so the harness can see a box move without needing it to land on a target. Reading a render the game produced is not re-implementing the game — parsing the level file to work out where the walls are would have been.

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

**And expect the tests to find things in the tooling, not just the game.** Along the way this run turned up that `ugt verify` exited 0 even when features failed — so any gate checking only the exit code would happily pass a red run. Dice turned out to be nearly undrawable-proof: 205 different attack sequences on the shipped seed and the enemy never dropped below 1 strength, so the round cap was deciding basically every match rather than the combat doing it. Neither of those is something you'd catch by reading the code. Both are fixed — the CLI exits non-zero now, and dice went through two rebalances to get to 91% decisive matches — and that's the whole reason this process exists. Finding them is the good outcome, not an interruption.

## The tier that asks whether the game is any good

Everything above answers *does it break*. There's one more tier, and it's the one I care most about: point a language model at the running game, give it a briefing, and let it play. That's what catches "this works perfectly and nobody would enjoy it".

The rule we settled on is **two stages, local first**. Stage one runs on a model on my own machine, costs nothing, and is not measuring the game at all — it's proving the *plumbing*, that the model can see what a player sees and act on it. Only stage two, on a paid model, is allowed to produce a number anyone quotes. That distinction sounds pedantic until you notice how the failure works: a run comes back clean — thirty actions, no crashes, a confident-looking result — while the model was playing half-blind the whole time because something quietly dropped information it needed. Nothing in the output tells you. So there's a checklist you work through and write down *before* spending anything.

It has earned its keep on every game we've pointed it at, and never once by finding a model problem:

- **The escape room was going to be played with no text.** It's a text adventure; the bridge was dropping every word of narration. Room descriptions, what you can see, and — worst — the authored refusals, which are how the game tells you what to do next. The tester would have shown an empty panel, silently, forever.
- **The state was handing over the puzzle's skeleton.** The wire listed all eight internal flags by name, so a model could read in the opening cell that there's a clock to set from an hour it must learn. A human infers that from prose, hundreds of moves later. Redacted, and then the *game* had to prove it announces every unlock in words, because removing a signal is only safe if the replacement is really there.
- **Dice's model couldn't see the battle log** — the running commentary a human reads down the side, which is the only place the game says whether your last choice worked. There's a hook for exactly that and we'd simply never written it, so it returned an empty string.
- **And UGT told a model a rule that wasn't true.** A guard rail warns before it blocks a repeated action, and its warning text was hardcoded from back when the ceiling was always three. Dice sets it high on purpose, because repeating an allocation is often correct play. The model read "this is a hard rule, not a suggestion", believed it, and switched away from the move its own briefing calls best. Nothing had been blocked. **Everything in the prompt is under test, not just the briefing you wrote.**
- **The guard rail then made a whole game unplayable.** Same rail, sokoban: it blocks the third identical move in a row, and pushing a crate five squares along a row *is* five identical moves. The game's own committed solution has runs of five and six. So on the default setting the model was physically prevented from playing the answer, and each override spent a turn doing nothing. The check that catches this now reads the game's solution file rather than a number I typed, so authoring a longer push re-checks it by itself.
- **A token limit was eating the model's turns.** The local model's reply is capped, the reply format puts the *action* first and the explanation after, so a long explanation gets cut mid-sentence and the whole thing fails to parse — and the tester substituted a do-nothing move. **Four of thirty turns, 13% of the budget, silently deleted**, with no counter anywhere reporting it. It showed up on the puzzle game and not the other two because reasoning about a grid is simply wordier than reasoning about dice.
- **And the tester was marking the model down for not predicting things it had been forbidden to see.** Sokoban deliberately hides two fields from the model. The detector that flags "the state changed unexpectedly" was comparing against all fields including those two, so every successful move counted as a failure to predict. If you hide something from an agent, nothing downstream may score it on knowing that thing.

Every one of those was found for free, on a local model, before a paid call. Which is the whole argument for the staging. Half of them were bugs in the tester rather than in the games.

**Where each game is up to.** Escape-room's local pilot now escapes the game. Dice ran both its local stages clean and is waiting on a credit decision. Sokoban's local stage is done too, and it's the interesting one: it's the only example living inside a game engine, so it's the only place the question *can a model play through a frame loop* gets answered. It can — the board arrives, the moves land, nothing broke in a hundred and sixty actions.

What the sokoban run did *not* do is tell me anything about the puzzles, because the local model never pushed a single crate. It read the briefing fine and talked about crates constantly; it just couldn't reliably work out *where* one was in a seven-by-five block of ASCII. Its own position it got right every time — and that's handed to it as two numbers. Everything else it has to find by counting characters.

That's a clean example of what the free stage is for and what it can't do. The plumbing is proven. The game is unmeasured. Any number from that run would be a fact about a small model's ASCII indexing, which is exactly why the free stage isn't allowed to produce one.



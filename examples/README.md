# Example: `dice` — Dice Duel (D6 dice pool war game)

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


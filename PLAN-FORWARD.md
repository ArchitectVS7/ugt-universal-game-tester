# UGT — Plan Forward (START HERE)

> **New session? Read this file, then `LESSONS.md`.** This is the durable, framework-level handover: the
> direction, the repeatable process, and the cross-game backlog.
>
> The concrete, per-game status ledger (which specific games have climbed which rungs, their open findings,
> and the game-specific next steps) is kept **internal** in `Dev/STATUS.md` — it names upstream projects and
> is not part of the shareable surface.

---

## The bigger picture (why any of this matters)

UGT is a **Universal Game Tester**: a framework that drives real games with autonomous agents to find bugs,
probe balance, and validate behavior. **The methodology is the product** — each game integration both tests
that game AND stress-tests the methodology, which is then reused on the next game.

The principles that methodology is built on — every one learned the hard way — live in **`LESSONS.md`**, the
canonical cross-game registry (§A core methodology, §B the mandatory LLM-playtest pre-flight audit, §C
operational discipline, §D the mechanics bake-off for deciding a *design* change with data before writing any
code). They are not restated here; read that file. The one worth stating up front, because
everything else follows from it:

> **Play the game with the game.** The tester must drive the *real* running game, never a re-implementation of
> it. An early simulation bridge slowly became a partial copy of the game it was meant to test (it dropped
> combat entirely) — every agent trained against it learned a *different game*. A harness that reimplements the
> game is testing itself. This is why every adapter contains zero game logic, and an unmapped action raises
> `NotImplementedError` by design rather than fabricating behavior.

---

## Where we are — multiple integrations, three transport paradigms

The **trial ladder** (below) has been run to completion against a range of games spanning three transport
paradigms:

- **Simulation / stdio bridge** — JSON over stdin/stdout to a headless subprocess the game exposes.
- **Browser / Playwright** — driving a real web frontend through `window.__GET_STATE__` / `__SEND_ACTION__`
  hooks the game itself exposes.
- **Subprocess JSON-lines harness** — a purpose-built harness wrapping an engine's own deterministic core
  (used for TypeScript card/strategy engines and a Godot title), plus a plain-HTTP variant driving a live
  server's test routes.

Tech stacks exercised so far include TypeScript engines (deck-building card, 4X/strategy), browser games
(React/Phaser), a Godot bullet-hell roguelike, and Python simulations. The game-agnostic scaffold that every
integration reuses is `ugt/core/trial.py` (`GateRunner`, `InvariantSuite`, `first_divergence`).

**Every integration to date has surfaced game bugs that were fixed upstream** — the dual-validation payoff
(LESSONS M2). The current per-game ledger, with real pass counts and open items, is kept in the internal
status ledger (`Dev/STATUS.md` — not part of the shared surface).

---

## The trial ladder (the repeatable process)

Each new game climbs the same ladder; every rung is a fail-closed gate script in `integrations/<game>/`:

1. **Spike** (`spike_<game>.py`) — prove the raw protocol round-trips headlessly (auth/create → act → read
   state). Empirically pins protocol facts that would otherwise bite later.
2. **Smoke** (`smoke_<game>_adapter.py`) — the same path through the `BaseAdapter` contract
   (`connect`/`reset`/`step`/`close`).
3. **R1 — playability gate** (`verify_round1.py`) — scripted "one full loop" of the core game under
   per-command invariants.
4. **R2 — full spine** (`verify_round2.py`) — every major mode/system driven to a real outcome (e.g. a win),
   still under invariants.
5. **R3 — invariant-fuzzer** (`verify_round3.py` / `ugt/core/invariant_fuzzer.py`) — random+heuristic walks with
   the same invariants asserted after every step, plus determinism checks (same-seed replay must be
   byte-identical). Findings are structured and read, not counted.

The shared skeleton is `ugt/core/trial.py` (`GateRunner`, `InvariantSuite` — one predicate definition reused
by both the scripted rounds and the hunter — and `first_divergence` for replay compare). Everything
game-specific (predicates, probes, policies, state normalization) stays in the game's `integrations/<game>/`
files.

The ladder answers *"does the game work / does it break?"* (tiers 1–2 of the three-tier model). The third
tier — the **LLM balance playtester** (`ugt playtest`, spec in `PLAYTEST-DESIGN.md`) — answers *"is the game
good?"*. **Before running it on any game, work through `LESSONS.md` §B (P1–P17)** — the pre-flight
information-integrity audit that two balance batches paid for the hard way.

---

## Next steps (framework-level)

The game-specific next steps live in the internal status ledger (`Dev/STATUS.md`, not part of the shared
surface); this document keeps only the cross-game, framework-level priorities:

1. **Land the LLM balance tier as a first-class, repeatable batch.** The playtester is wired and
   smoke-validated on several games, but the CI-gated, seat/turn-order-controlled batch that produces a
   *trustworthy* balance verdict — with a confidence interval, compared against the game's own gate — is the
   maturity step. Read `LESSONS.md` §B before spending any batch.
2. **Formalize human/frontend UAT as an explicit fourth doorway.** It has only been tracked ad hoc for the
   engine-first games, and in every case it caught things — visual readability, onboarding, animation feel — no
   engine-level tier can see by construction. Every integration's `HANDOFF.md` should carry a UAT status line
   the same way it carries ladder status.
3. **Rebuild the regression floor the sample games used to provide** — see "The regression gap" below. This
   is the one item with a deadline attached to it: it should land *before* the next `ugt/core/` change, not
   after, because right now a core change has nothing in-repo to break against.
4. **Build the teaching artifact: one complete spec-to-tuned-game chain.** Needs its own session — see "The
   teaching artifact" below.

---

## The teaching artifact (needs its own session — 2026-07-27)

**The decision:** the three sample games are no longer bundled inside this repo. On 2026-07-27 (`7b759b8`)
`examples/{dice,escape-room,sokoban}` were moved out to their own sibling repositories, to be published as a
GitHub **organization** alongside UGT and the Orchestrator skill: the framework, the skill as a bonus, and
some sample games built with `/orchestrate` and tested with UGT — each taken or left independently.

**Two reasons, both real.** The in-repo layout taught the *wrong pattern*: in real use a game owns its own
repository and the harness lives in `integrations/<game>/` here, but `examples/<game>/{game,integration}/`
put both under one tree, and that was the first thing a reader saw. And shipping games inside the framework
forces them on someone who only wants the tester.

**The third reason is the one that needs work, not just a move.** Both the dice game and the escape room
were played end-to-end by the owner and are *thin* — technically functional, no payoff. The dice game is
point-and-click with numbers changing on screen and flavour text about forces clashing; the escape room's
own channel check proved the transport and measured nothing about the game. They demonstrate the process
and reward nobody. If a reader follows the chain and builds one of these, what they get at the end has to be
worth having.

**Root cause, and it is not the games.** Getting the dice game running took substantial back-and-forth and
real creative input to solve problems the spec never anticipated — which means **the initial PRD was
incredibly thin**. A teaching artifact whose first link is a PRD that cannot actually carry a build is
teaching the wrong lesson twice.

**What to build, when the session comes:**
- **A genuinely complete PRD** — thick enough that `/tasklist` can derive a real `TASKS.md` from it and
  `/orchestrate` can build it without the creative rescue the dice game needed. The PRD is the artifact
  under test here; if it needs rescuing, it is not done.
- **A game with actual payoff.** Candidates raised: Yahtzee with real dice, checkers, Pac-Man. Alternatively
  the existing dice game may get there with short delays, animations, sound effects and real dice graphics —
  it is the *feel* that is missing, not the rules. Decide by playing, not by reasoning about it.
- **The full chain, documented as one arc:** PRD → `/tasklist` → `TASKS.md` → `/orchestrate` → a built game →
  UGT ladder (spike/smoke/R1/R2/R3) → LLM playtest → a *tuning* pass driven by what the playtest found.
  The tuning leg is the part no current example shows end to end, and it is the payoff of the whole method.
- **Ship the PRD as the entry point.** The most useful thing to leave a reader may be exactly this: a
  complete PRD plus "now run `/tasklist` on it, then `/orchestrate` it" — something they build themselves
  rather than read.

## The regression gap (opened 2026-07-27 by the same move)

Moving the samples out removed UGT's only in-repo end-to-end check, so this needs an answer before the next
core change. **How the examples were actually used** — the honest version, since the docs claimed more than
the practice delivered:

- **One live implementation per `engine.type`** (browser / simulation / custom-TCP), so a change to shared
  `ugt/core/` code got exercised across all three transports rather than only the one in front of us. This
  was the real value, and it is a *coverage* property, not a regression-suite property.
- **They caught genuine framework bugs.** `6ffa58a` — `SubprocessAdapter.reset()` recorded no narration, so
  the LLM tier's first decision was made with an empty terminal panel for *every* simulation-engine game;
  found by driving the escape room. `700c46c` — the same pre-flight found a wire-only defect on the game
  side (narration discarded at the bridge) that an in-process suite could not see.
- **They forced generalization.** `694eb9d` moved the seeding probe out of one game's integration script into
  `ugt/core/seeding.py` — a per-game habit became a framework guarantee because a second and third game
  needed it.
- **But the "re-run all three ladders on any core change" rule was aspirational.** Only 4 of the last 40
  commits touched both `ugt/` and `examples/`. It was a real practice, unevenly applied — worth saying
  plainly so the replacement is designed for what we actually did.

**Options, roughly in order of preference:**
1. **A small conformance fixture per `engine.type`, in-repo and deliberately boring.** Explicitly a *test
   double*, not a demo game, and labelled as such so it never gets mistaken for the teaching artifact. This
   does **not** violate "never test a re-implementation of the game" — that rule governs *adapters*, which
   must hold no game logic. A fixture is not standing in for a real game; it exercises the transport.
2. **CI that clones the three sibling repos and runs their ladders.** Keeps real games in the loop; costs a
   network dependency and couples the framework's gate to repos that can drift.
3. **Accept manual re-runs against the siblings.** Cheapest, and the least likely to actually happen.

---

## Framework backlog (cross-game, not game-specific)

Revisit when an item actually blocks the current game, not on a schedule:

### ⭐ TRUE exploit hunting — the one genuinely missing tier

**Status: not built. Deliberately named here so it is not mistaken for something we already have.**

The robustness tier (`ugt/core/invariant_fuzzer.py`, renamed from `ExploitHunter` on 2026-07-26 — see
LESSONS M10) drives *random* actions against an oracle. It has no notion of reward, score or progress, so it
can only ever **stumble into** a degenerate line and have a check notice. It never goes looking. The generic
checks added alongside the rename (`ugt/core/generic_checks.py`) raise the floor — they detect the *shapes* of
degenerate play with no per-game config — but detection is not search.

**The gap, concretely.** The original RL tier died because agents farmed reward without playing the game.
Nothing in UGT today would find that class again on purpose. The proof is in-repo: a browser dice game held R3
green at 11/11 for weeks while one allocation strictly dominated every other and the game's only decision was
meaningless. It took two independent design reviews plus a 3.15M-battle simulation (LESSONS §D) to surface —
no tier did it.

**What a real exploit hunter would entail.** Roughly in order of cost:

1. **A search policy instead of a random one.** The single biggest change. Coverage- or novelty-driven
   (reward the agent for reaching *unseen* states, à la Go-Explore / curiosity search) rather than
   reward-driven — critically, this needs **no game-specific reward function**, which is what made the RL tier
   unmaintainable. Novelty is computable from the state hashes the fuzzer's `Trace` already records.
2. **An objective to maximize, discovered rather than declared.** The generic checks already identify
   candidate "resource-like" fields (monotone-growth). Feed those back in: once a field is nominated, search
   for the action sequence that maximizes it per unit time. That closes the loop from *detect* to *exploit*.
3. **Cycle exploitation, not just cycle detection.** `check_state_cycles` finds that a loop exists. The
   hunter's job is to ask whether any loop is **net-profitable** — return to a near-identical state with a
   resource strictly higher. That is the formal definition of a farm, and it is game-agnostic.
4. **Replay minimization.** A 400-step exploit nobody can read is not a finding. Delta-debug the sequence down
   to the shortest prefix that still reproduces the gain (standard ddmin), so the output is a 6-step repro a
   designer can act on.
5. **A budget-bounded runner.** Search is unbounded by nature; this tier needs a wall-clock/step ceiling and
   must report what it did NOT cover (LESSONS: no silent caps).

**Design constraints learned the hard way, which any implementation must honour:**
- **No reward engineering per game.** The moment this needs a hand-written reward it becomes the RL tier that
  already failed. Novelty and self-discovered resource fields are the way through.
- **Findings must be reproducible.** Same seed, same sequence, byte-identical — the determinism discipline R3
  already enforces.
- **Observations, not verdicts, for anything dispositional** (LESSONS M10). "This loop gains 3 gold/turn" is a
  fact; "this is an exploit" is a design judgement belonging to the user.
- **It answers a THIRD question.** Correctness (`ugt verify`) / robustness (invariant fuzzer) / balance (LLM
  playtester) / **gameability (this)**. Do not bolt it onto the fuzzer and re-blur the name we just fixed.

**Cheapest first step if picked up:** a novelty-driven policy is a drop-in — `InvariantFuzzer` already accepts
`policy=`, and `Trace` already carries the state hashes it would need. That alone, with no other change, turns
random walking into directed exploration and is worth measuring before building anything larger.


- **Config-driven CLI path for the trial ladder** — the per-game `verify_round*.py` scripts construct
  adapters directly; several adapters aren't registered under an `engine.type` in `env.py`. Worth a look now
  that every integration hand-rolls its own ladder scripts, and the direct-adapter playtest entry point was
  added specifically to sidestep this rather than solve it.
- **Browser feature map + screen detection** — `press_key`/`type_text` action syntax in `feature-map.yaml`,
  plus `detect_screen()`/`waitForScreen()` (needed for `ugt verify` to cover browser titles).
- **`ugt verify` doesn't support `engine.type: "custom"`** — by construction (there is no adapter for it to
  dispatch); low priority, since those integrations assert the same invariants in their ladder scripts.
- **Desktop adapter** — `pyautogui` or a computer-use API for non-browser, non-terminal games.
- **HTML coverage report** — human-readable `coverage-report.html` generated from the JSON.
- **`ugt init --with-feature-map`** — scaffold a starter `feature-map.yaml` alongside `ugt.config.yaml`.

---

## Key references

| Thing | Where |
|---|---|
| Cross-game lessons registry (methodology + LLM pre-flight audit + operational discipline) | `LESSONS.md` |
| Onboard a new game + methodology | `UGT-USER-MANUAL.md` |
| Bridge contract, config keys, troubleshooting (lookup) | `UGT-REFERENCE.md` |
| LLM playtest design spec (tier 3) | `PLAYTEST-DESIGN.md` |
| Trial-ladder scaffold | `ugt/core/trial.py` (+ `ugt/core/invariant_fuzzer.py` for R3) |
| Framework overview + install | `README.md` |
| Per-game status ledger + game-specific next steps (**internal**) | `Dev/STATUS.md` |
| Superseded / historical docs (**internal**; why + where content went) | `Dev/README.md` |

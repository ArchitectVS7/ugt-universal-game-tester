# UGT — Universal Game Tester: User Manual

> **Purpose of this document:** A practical, end-to-end guide for plugging a new game into UGT,
> teaching it the rules, and running the three test phases in the correct order.
>
> **What this is not:** a tutorial on any single testing technique. You need to understand your
> game's state, actions, and win condition — UGT handles the rest.

---

## Methodology & Hard-Won Lessons (read before onboarding a new game)

> **Canonical source: [`LESSONS.md`](LESSONS.md).** That file is the cross-game lessons registry — every rule
> here plus the LLM-playtest pre-flight audit (section B), the operational discipline rules (section C), and
> the mechanics bake-off (section D), each with its evidence and source. Read it before onboarding a game,
> before advancing a ladder rung, and before any LLM playtest run. New lessons go there, not here.

The nine core rules, as one-line index entries only — **the full text and the evidence behind each live in
`LESSONS.md` §A**, the single canonical copy; if a line below ever disagrees with LESSONS, LESSONS wins:

- **M1 · Drive the REAL game, never a re-implementation.** If your adapter contains game *rules*, you're
  testing the adapter, not the game. (A simulation bridge that quietly dropped combat is the founding lesson.)
- **M2 · Dual validation** — finding a real game bug and pausing to fix it upstream is a success, not a
  distraction.
- **M3 · Failed tests are data** — record negative results so the next session doesn't re-learn them.
- **M4 · Prove learnability cheaply** before spending compute.
- **M5 · Verify ≠ Train ≠ Play** — a verifier crutch (extra credits, perfect nav) doesn't prove reachability
  under real play.
- **M6 · Reward realized outcomes, not activity** — express play styles as reward *weights*, not by hiding
  actions.
- **M7 · Right tool per question** — correctness → verify; robustness → invariant-fuzzer; balance → LLM
  playtester. Don't force one agent to answer all three.
- **M8 · Test over the wire** — a green in-process suite cannot see serialization-boundary bugs.
- **M9 · Audit your own findings** before citing them; record corrections rather than deleting them.

> The tier model below is the current shape: keep the phase *order* (cheap correctness first), and pick
> the agent per the "right tool per question" rule (M7) above.

---

## The Three-Tier Testing Model

**Run these in order. Each tier depends on the previous one being healthy.**

| Tier | Command / mechanism | Question answered | Output file |
|------|---------------------|--------------------|-------------|
| **1. Verify** | `ugt verify` | Does each game feature work correctly? (correctness) | `results/coverage-report.json` |
| **2. Invariant-fuzzer** | `ugt/core/invariant_fuzzer.py` — R3 of the trial ladder | Does the game break under random/heuristic pressure? (robustness) | printed `[FINDING]`s + the round's PASS/FAIL footer |
| **3. LLM playtest** | `ugt playtest` | Is the game *good*? Does it feel right to a reasoning player? (balance/judgment) | `results/playtest-report.json` |

> **Why order matters:** tier 3 verdicts on a game that still crashes under tier 2 are noise, and tier 2 on a
> game whose features don't even work under tier 1 is a waste of a random walk. Tier 1 is cheap (minutes); do
> it first.
>
> Use `ugt smoke-test` before Tier 1 as a quick sanity check that the bridge is responding.

### The trial ladder (how integrations actually run Tiers 1–2)

In practice, every real integration (see `integrations/<game>/`) climbs a standardized **trial ladder** of
fail-closed gate scripts rather than the bare CLI commands — five rungs, each with its own exit criteria:

| Rung | Script | What it proves | Exit criteria |
|---|---|---|---|
| **Spike** | `spike_<game>.py` | The raw protocol round-trips headlessly (create/auth → act → read state back) | Every raw-protocol check passes; no protocol quirk left unresolved before writing the adapter |
| **Smoke** | `smoke_<game>_adapter.py` | The same round-trip works through UGT's `BaseAdapter` contract | Same checks pass via `connect()`/`reset()`/`step()`/`close()`, not the raw protocol directly |
| | | *⚠️ Not the same as `ugt smoke-test` (§5, a CLI wiring check) and not the same as the LLM tier's local **channel check** (`LESSONS.md` §B P12). Three things, one word — always name the rung.* | |
| **R1 — playability** | `verify_round1.py` | One scripted full loop of the core game, invariants checked after every command | Every invariant holds across the whole loop; the loop reaches a real, meaningful state change (not a no-op); same-seed reproducible |
| **R2 — full spine** | `verify_round2.py` | Every major mode/system driven to a real outcome (e.g. an actual win), still under invariants | Every mode reaches a genuine terminal outcome under the same invariants; the check count (denominator) is disclosed honestly — no vacuous passes, none silently narrowed or widened |
| **R3 — invariant-fuzzer** | `verify_round3.py` | Random/heuristic walks (`ugt/core/invariant_fuzzer.py`) asserting the SAME invariants after every step, across multiple seeded episodes | Zero invariant violations/crashes across every episode and step; every action in the vocabulary exercised at least once; a same-seed replay is byte-identical (determinism) |

The game-agnostic skeleton lives in `ugt/core/trial.py`: `GateRunner` (the `[PASS]`/`[FAIL]` accumulator,
`[FINDING]` registry, and the fail-closed "ROUND N MET — p/t" footer), `InvariantSuite` (one predicate
definition reused by both the scripted rounds and the invariant-fuzzer, so the tiers can't drift apart), and
`first_divergence` (replay compare). Everything game-specific — predicates, probes, policies, state
normalization — stays in the game's `integrations/<game>/` files. A failed check is DATA: findings print
inline, fail the gate, and get fixed upstream in the game.

> **Worked example:** `sokoban/integration/` is a complete implementation of this whole ladder —
> a small deterministic Godot game driven engine-first over a TCP socket through a transport-only adapter,
> with all five rungs (`spike_sokoban.py` … `verify_round3.py`) runnable in one command. It is the fastest
> way to see the ladder, the invariant-suite reuse across R1/R2/R3, and the invariant-fuzzer + determinism
> check in action. Read its `README.md` first — including its "Corrections to this harness" section, which
> records two assertions that were vacuous in the first version and how they were caught.

### What happens once R3 passes

R3 answers "does it work / does it break" — it does **not** answer "is it good." A green ladder is the
*prerequisite* for the next tier, not the end of testing:

1. **Tier 3 — LLM playtest** (`ugt playtest`, §6 below). An LLM plays through a realistic input channel
   (keypresses, typed terminal commands, or a legal-action list for harness-style games with no terminal)
   and judges balance/strategy, producing `results/playtest-report.json` with state-delta-based bug reports.
   Only makes sense once the ladder is green — balance verdicts on a game that still crashes are noise.
2. **Human / frontend UAT** — a real person plays the actual UI. Not yet CLI-automated by UGT, but the
   established next step after a clean LLM playtest: things like visual readability, animation feel,
   onboarding clarity, and accessibility that no automated tier can see by construction (an engine-level or
   LLM-driven test can confirm the mechanics work; only a human can confirm the game *reads* well). Every
   integration's `HANDOFF.md` should carry a UAT status line once this tier is reached.

### When a balance finding turns out to be a *design* question — run a bake-off

Sooner or later a tier will hand you a finding that no constant can fix: *"aggression isn't a trade-off, it's
just the right answer."* At that point you are choosing between candidate **rule changes**, and the usual
instinct — pick the most plausible one, implement it, find out later — is what turns a month into a year.

Don't guess and don't argue it. **`LESSONS.md` §D** is the full procedure; the short version:

1. **Get independent opinions.** Same prompt, isolated context, two or more reviewers. Vary the reviewer, not
   the question — different models, or different personas (game designer vs. competitive player vs. casual
   player). Tell each to challenge the framing, not just answer it. Just ask for this in a prompt; there is no
   command.
2. **Synthesize on agreement.** What independent reviewers converge on is the strongest signal you can get
   without running anything. Bank that; the disagreement is what needs measuring.
3. **Simulate every candidate before writing any code.** Copy the shipped engine, patch it at named anchors
   (assert each anchor matched exactly once *and* changed something), and sweep. A deterministic engine is
   usually pure and dependency-free, so this needs no edit, no migration, and no test rewrite.
4. **Validate the rig on a prediction it did not produce**, then read metrics that separate *balanced* from
   *deep* — regret of the naive strategy, best-response vector, dead options, value of deciding per turn,
   interior mass. **Win rate cannot tell a flat game from a rich one.**
5. **Use enough samples.** Small `n` reverses conclusions; see §D7 before picking a number.

This does **not** require a fully simulable game. Narrative and multi-branch games resist end-to-end
simulation, but their mechanical subsystems — combat resolution, XP curves, drop tables, economy loops, NPC
disposition — are nearly always pure functions you can sweep in isolation. Sweep the subsystem, not the story.

Worked example, with the numbers and the rig: `dice/README.md` and `LESSONS.md` §D.

---


> **Two documents, two jobs.** This is the **manual** — the path you walk once, in order, to get your
> game under test. Its companion **[`UGT-REFERENCE.md`](UGT-REFERENCE.md)** is the lookup half: the
> adapter contract, every `ugt.config.yaml` key, and troubleshooting. You do not read the reference;
> you search it. Split out on 2026-07-27 because one 900-line file was serving both purposes and doing
> neither well.

## 1. What UGT Does

UGT runs three tiers of testing against a game, each answering a different question (see "The Three-Tier
Testing Model" above for the full table and exit criteria):

| Tier | Tool | Question answered | Time |
|------|------|--------------------|------|
| **1. Verify** | `ugt verify` | Does each feature work? (correctness) | ~minutes |
| **2. Invariant-fuzzer** | R3 of the trial ladder | Does the game break under pressure? (robustness) | ~minutes |
| **3. Playtest** | `ugt playtest` | Does the game feel right to a reasoning agent? (balance) | ~30 min |

All three tiers share the same `ugt.config.yaml` and bridge protocol. Once your bridge is written, all three
are available.

---

## 2. How It Works (The Big Picture)

```
┌─────────────────────────────────────────────────────────────┐
│                        ugt.config.yaml                       │
│      (observation space, action space, seed)                 │
└──────────────────────────┬──────────────────────────────────┘
                           │ read by
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     UGT Python Core                          │
│                    cli.py (ugt command)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐ │
│  │  verifier.py │  │ invariant_fuzzer│  │  playtester.py     │ │
│  └──────┬───────┘  └──────┬───────┘  └─────────┬──────────┘ │
│         │                 │                     │            │
│  ┌──────▼─────────────────▼─────────────────────▼──────────┐ │
│  │            an adapter (BaseAdapter subclass)              │ │
│  └──────────────────────────┬────────────────────────────── ┘ │
└─────────────────────────────┼───────────────────────────────┘
                              │ one adapter per engine.type
              ┌───────────────┴──────────────────┐
              │                                  │
              ▼                                  ▼
  ┌───────────────────────┐        ┌────────────────────────────┐
  │  SubprocessAdapter    │        │  PlaywrightAdapter          │
  │  (headless sim games) │        │  (browser / frontend games) │
  │  JSON over stdin/out  │        │  window.__GET_STATE__ etc.  │
  └──────────┬────────────┘        └──────────────┬─────────────┘
             │                                    │
             ▼                                    ▼
  ┌──────────────────────┐         ┌──────────────────────────┐
  │  Your game's bridge  │         │  Your game's frontend     │
  │  (sim_bridge.py/ts)  │         │  (served at localhost)    │
  └──────────────────────┘         └──────────────────────────┘
```

UGT never imports your game code directly. It talks to your game through a **bridge** — a thin wrapper that translates UGT's standard protocol into your game's API. You write the bridge; UGT handles everything else.

The diagram shows the two engine types this manual walks through (`simulation` and `browser`) — the two
that `env.py` dispatches for you. Anything else (a live server over HTTP, a TCP socket to a game engine's
frame loop, a JSON-lines harness) declares `engine.type: custom` and supplies its own transport-only
`BaseAdapter` subclass, which the integration's own ladder scripts construct directly; the scripts in
`sokoban/integration/` show that shape end to end.

---

## 3. Installation

```bash
# From the UGT directory:
pip install -e .

# Verify installation:
ugt --help

# For browser (UI) testing, install Playwright browsers:
pip install playwright
playwright install chromium
```

---

## The step between: connect your game

Installing UGT does not yet let it *see* your game. Before any tier below will run, your game needs a
**bridge** — a small transport layer that hands UGT a state dict and accepts an action. That is the one
piece that is genuinely specific to your project, and it is written up in full, with copy-paste templates
for both built-in transports, in **[`UGT-REFERENCE.md` §1 — Connecting Your Game](UGT-REFERENCE.md)**.
Its companion **§2** covers writing the `ugt.config.yaml` that tells UGT what your state fields and
actions mean.

Do those two, then come back here and start with Verify. Everything from this point assumes a working
bridge and a validating config.

**One rule that is not negotiable, repeated here because it is the failure this whole framework was
rebuilt around:** the bridge is a *transport*, never a re-implementation. It opens the connection, sends
an action, reads state back. An action it cannot map raises `NotImplementedError` naming the action —
it does not fabricate behaviour. A harness that reimplements the game is testing itself.

---

## 4. Phase 1 — Verify (Correctness Testing)

`ugt verify` drives your game through a feature map — a YAML file listing every testable behavior — and checks that each feature's state change is what you declared. Run this before playtesting.

### 4a. Writing a Feature Map

Create `feature-map.yaml` alongside your `ugt.config.yaml`. Each entry names an action (by the action name from your config), states what must be true after it runs, and optionally defines a precondition.

```yaml
# feature-map.yaml
game: "MyGame"
version: "1.0"

features:
  - id: economy.invest_increases_credits
    description: "Investing increases the player credit balance"
    action: "invest_credits"          # name from action_space.actions in your config
    assertion: "state.player.credits > before.player.credits"
    priority: critical                # critical | major | minor
    precondition: "state.player.ap >= 2"  # optional: skip if not met

  - id: game.end_turn_advances_counter
    description: "Ending the turn increments the turn counter"
    action: "end_turn"
    assertion: "state.turns_elapsed > before.turns_elapsed"
    priority: critical

  - id: game.win_condition
    description: "Reaching 500 credits triggers victory"
    action: "invest_credits"
    assertion: "state.victory == True"
    priority: critical
    precondition: "state.player.credits >= 450 and state.player.ap >= 2"
```

**Assertion syntax:**
- `state.X` — the game state *after* the action
- `before.X` — the game state *before* the action
- Operators: `>`, `<`, `==`, `!=`, `>=`, `<=`, `and`, `or`, `not`
- Action names must exactly match the `name:` fields in `action_space.actions` in your config

**Priority values:**
- `critical` — game cannot function without this; tested first
- `major` — core gameplay loop; always tested
- `minor` — edge case or optional content; tested when time allows

**Action sequences:** Use a YAML list when a feature requires multiple steps:
```yaml
  - id: traders.buy_then_sell
    action:
      - "buy_fuel"
      - "sell_fuel"
    assertion: "state.credits != before.credits"
    priority: major
```

### 4b. Running `ugt verify`

```bash
cd your-game/
ugt verify --config ugt.config.yaml --feature-map feature-map.yaml
# Options:
#   --max-turns 50     how many turns to drive the game (default: 50)
#   --output path.json custom output path (default: results/coverage-report.json)
```

### 4c. Reading the Coverage Report

`results/coverage-report.json`:

```json
{
  "game": "MyGame",
  "total_features": 6,
  "passed": 4,
  "failed": 1,
  "not_reached": 1,
  "coverage_pct": 66.7,
  "results": {
    "economy.invest_increases_credits": {
      "status": "PASSED",
      "delta": { "player.credits": "+50", "player.ap": "-2" }
    },
    "economy.invest_costs_ap": {
      "status": "FAILED",
      "error": "Assertion failed: state.player.ap < before.player.ap",
      "before": { "player": { "credits": 100, "ap": 10 } },
      "after":  { "player": { "credits": 150, "ap": 10 } }
    },
    "game.win_condition": {
      "status": "NOT_REACHED",
      "note": "precondition never met in 50 turns"
    }
  }
}
```

- **PASSED** — the assertion held; the feature works as declared
- **FAILED** — the assertion did not hold; there is a bug or your assertion is wrong
- **NOT_REACHED** — the precondition was never met; either the feature is unreachable in the test window or the precondition expression is wrong

### 4d. Troubleshooting Verify

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| All features `NOT_REACHED` | Preconditions never satisfied | Check state path spelling; log `current_state` during a smoke-test |
| `FeatureMapError: action 'invest_credits' not found` | Action name mismatch | Check the exact `name:` value in your config's `action_space.actions` |
| Assertion always FAILED but state looks right | State path typo in assertion | Compare the `before` and `after` fields in the report to spot the actual path |
| `game.win_condition` NOT_REACHED | Credits don't reach 450 in 50 turns | Increase `--max-turns` or check if the precondition is achievable |
| Verifier crashes with `RuntimeError` | Bridge connection issue | Run `ugt smoke-test` first to confirm the bridge is working |

---

## 5. Quick Sanity Check — `ugt smoke-test`

The smoke test verifies that your bridge responds correctly before you write a feature map. Takes ~10
seconds, requires no model or feature map.

```bash
cd your-game/
ugt smoke-test --config ugt.config.yaml
```

**What it tests:** bridge connectivity, state dict structure, observation vector mapping. It does NOT test
whether game features behave correctly — use `ugt verify` for that.

**Expected output on success:**
```
[*] Starting connection smoke test for project: MyGame
[+] Connection established! Initial observation vector: [100.  10.   0.   0.]
[*] Running 5 steps with random action commands to verify action space and state mapping...
  [Step 1] Action ID: 2 | Obs: [100.  10.   1.   0.] | Terminated: False
  ...
[+] Smoke test passed successfully! Adapter communication and state mappings are fully operational.
```

**What to fix if it fails:**
- `Connection failed` / `Failed to spawn subprocess` — check your `engine.entry` command; run it manually first
- `Invalid JSON response` — your bridge is printing non-JSON to stdout; redirect debug output to stderr
- `observation_space.shape does not match` — number of `mappings:` entries doesn't equal `shape:`
- `Terminated: True` on step 1 — `reset()` isn't actually starting a fresh game

---

## 6. Phase 2 — Playtest (LLM Player)

`ugt playtest` runs an LLM agent through your game. Unlike the scripted verifier, the LLM player reads the game state and reasons about what to do next — it can find bugs that no scripted test would look for, because it plays like a real player would.

### Run this tier in TWO STAGES — local first, paid second

**Never spend an API call proving the plumbing works.** The local stage costs nothing, so it is where you iterate; the paid stage is where you measure. Full rule and its evidence: `LESSONS.md` §B **P12**.

**Stage 1 — local, free, iterate hard.** Point the playtester at a local Ollama model:

```bash
# requires ollama running at localhost:11434 — no API key
ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md \
  --provider ollama --model gemma4:26b --max-actions 30
```

Drive a few basic game actions first, then a **30-action channel check** (up to 100 if the loop is long) — *called a "channel check" and not a "smoke test" on purpose: that word already names `ugt smoke-test` (§5) and ladder rung 2, neither of which proves anything this stage proves.* This is where you write and rewrite the strategy guide and the prompting *for this specific game*: run → read the logged `reasoning` → fix the guide → run again. Keep going until the pilot cleanly processes the basic game loop. Work the whole §B audit here — P1–P8 are all findable for free, because they are defects in what the pilot can **see**, not in how well it thinks.

**Stop at ~100 actions.** Past roughly 200 local calls the run is not merely slow — the decisions get measurably worse than Haiku's. **Bad decisions do not equate to good tests.** A long local run buys degraded play, not more evidence, and any balance number read off it is noise. Local proves the *channel*; never quote it as a result.

> One asymmetry worth knowing: on a local model the P7 competence grep is a **positive signal only**. If the reasoning names your core mechanics, the channel is proven. If it does not, that is ambiguous — starvation and a weak model look identical from outside. Re-check on the paid run before closing any P1/P2/P6 finding.

**Stage 2 — paid, measure.** Once stage 1 loops cleanly, switch to Anthropic. **Haiku is the working default**: fast and cheap enough to re-run after every fix.

```bash
ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md \
  --provider anthropic --model claude-haiku-4-5-20251001 --max-actions 100
```

**Then expect to iterate on the game as often as on the harness.** That loop turns around far faster than human testing, and that is the point: **the goal is for the first human UAT to be already relatively bug-free**, so a person's time goes on feel, readability and onboarding — the things no automated tier can see — instead of on defects a free 30-action local run would have caught.

### 6a. Writing a Strategy Guide

Create `strategy-guide.md` alongside your config. This is the single most important input: a 1–3 page document that teaches the LLM how your game works.

Include:
- **Win condition** — exactly what state causes the game to end in victory
- **Core loop** — what a competent player does on a typical turn
- **Action vocabulary** — what each action does, when to use it
- **What broken looks like** — describe observable symptoms of bugs (credits unchanged after purchase, screen not changing, etc.)

Two working examples ship, and they are deliberately different shapes:
`escape-room/integration/strategy-guide.md` (a puzzle game — teaches how to read refusals, and
says plainly what the state will *not* tell you) and `dice/integration/strategy-guide.md` (a
combat game — teaches the scoring rules that create skill, while withholding the opponent's closed-form
policy so the run measures play rather than exploitation of a leaked answer).

### 6b. Running `ugt playtest`

> **Persistent-state games:** Set `diagnose_resets_episode: false` in your config before the first LLM
> playtest run. By default the `diagnose` action resets the episode — in a game with persistent campaign
> state this will erase progress mid-run. (This knob exists because a real run erased 310 turns of valid
> play before the option was added.)
>
> Add to `ugt.config.yaml`:
> ```yaml
> playtest:
>   diagnose_resets_episode: false
> ```

```bash
# Requires: pip install 'ugt[playtest]' and ANTHROPIC_API_KEY
export ANTHROPIC_API_KEY=sk-ant-...

cd your-game/
ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md
# Options:
#   --max-actions 100    number of LLM actions to take (default: 100)
#   --output path.json   custom output path (default: results/playtest-report.json)
```

**Cost note:** Each action is one Anthropic API call with ~512 tokens output. At July 2026 pricing:
- **claude-haiku-4-5** ($1/$5 per MTok input/output): ~**$0.75 per 100 actions** — recommended for long exploratory runs
- **claude-opus-4-8** ($5/$25 per MTok input/output): ~**$3–4 per 100 actions** — higher-quality judgment, shorter runs

Both figures include input context growth across the run. Pass `--model claude-haiku-4-5` to use Haiku. For a first run, use `--max-actions 30` to verify it's working before committing to a full run.

### 6c. Reading the Playtest Report

`results/playtest-report.json`:

```json
{
  "game": "MyGame",
  "total_actions": 100,
  "potential_bugs": [
    {
      "step": 23,
      "description": "Credits unchanged after invest_credits despite having AP — economy system may be broken",
      "state": { "player": { "credits": 100, "ap": 8 } }
    }
  ],
  "novel_behaviors": [],
  "action_log": [
    {
      "step": 1,
      "action_type": "action_id",
      "action": "invest_credits",
      "reasoning": "Have 10 AP and need credits — invest to advance toward win condition",
      "expected": "credits increase by 50",
      "state_delta": { "player.credits": "+50", "player.ap": "-2" }
    }
  ]
}
```

- **`potential_bugs`** — states where the LLM observed something unexpected. Read each one and verify manually.
- **`novel_behaviors`** — actions the LLM marked as exercising something outside your feature map. Consider adding these to your `feature-map.yaml`.
- **`action_log`** — full history of what the agent did and why. The `reasoning` field shows the agent's intent; `state_delta` shows what actually changed.

**Browser game note:** Full browser play (with `press_key` and `type_text` flows, screen detection, and `waitForScreen`) is a future enhancement. The current scaffold works fully for simulation/subprocess games.

---

## 7. Frontend UI Testing (Browser Games)

The browser adapter drives your game's actual frontend through a real Chromium browser (headless). This tests:
- That the JS hooks respond correctly
- That state rendering doesn't break after sequences of actions
- That there are no soft-locks (states where the game stops accepting actions)
- That the game doesn't crash on unusual-but-legal action sequences

**Step 1: Expose the JS hooks in your frontend** (see Section 4b).

**Step 2: Configure your game as a browser engine:**

```yaml
engine:
  type: "browser"
  entry: "http://localhost:8080"   # URL where your game is served
  step_delay_ms: 50               # ms to wait per step if no __STEP_COMPLETE__ flag
```

**Step 3: Start your game's dev server, then smoke-test:**

```bash
# Terminal 1: start your game
npm run dev

# Terminal 2: run the smoke test
cd path/to/your/game
ugt smoke-test --config ugt.config.yaml
```

The smoke test drives 5 random actions through the browser and confirms the hooks are wired correctly. Watch both terminals: your game server's logs will show exactly which requests UGT is triggering.

**Step 4: Run a random-play UI stress test:**

There is no dedicated "UI stress test" command — use the invariant-fuzzer (Tier 2 of the trial ladder,
`ugt/core/invariant_fuzzer.py`) directly against your browser adapter. It drives random/heuristic actions
through the real UI and re-checks your invariants after every step, which is exactly what a UI stress pass
needs: many different action sequences, not a single scripted path. See "The trial ladder" section above for
how R3 wires this up (`verify_round3.py` in a real integration; `sokoban/integration/verify_round3.py` for
a complete worked example — swap its TCP adapter for a `PlaywrightAdapter` and it drives your browser
game the same way).

**What to look for:**
- Any episode that terminates with 0 steps (crashed on step 1)
- Episodes that hit the step cap every time but never show a `player_won` or loss signal (soft-lock)
- Errors in your game server's terminal that correspond to specific action IDs

**For headful debugging** (to actually see the browser during testing), edit `playwright.py` line 26 temporarily:

```python
self.browser = self.playwright.chromium.launch(headless=False)  # see the browser
```

This lets you watch UGT play your game in real time. Useful when diagnosing why specific actions seem to have no effect.

**Performance note:** The soft-reset hook (`window.__RESET_GAME__()`) reduces episode reset time from ~15 seconds to <50ms. Always implement it. Without it, 100 episodes = over 25 minutes just in resets.

---


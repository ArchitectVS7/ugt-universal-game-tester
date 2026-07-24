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
operational discipline). They are not restated here; read that file. The one worth stating up front, because
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
(LESSONS M2). The current per-game ledger, with real pass counts and open items, is in `Dev/STATUS.md`.

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
5. **R3 — exploit-hunter** (`verify_round3.py` / `ugt/core/exploit_hunter.py`) — random+heuristic walks with
   the same invariants asserted after every step, plus determinism checks (same-seed replay must be
   byte-identical). Findings are structured and read, not counted.

The shared skeleton is `ugt/core/trial.py` (`GateRunner`, `InvariantSuite` — one predicate definition reused
by both the scripted rounds and the hunter — and `first_divergence` for replay compare). Everything
game-specific (predicates, probes, policies, state normalization) stays in the game's `integrations/<game>/`
files.

The ladder answers *"does the game work / does it break?"* (tiers 1–2 of the three-tier model). The third
tier — the **LLM balance playtester** (`ugt playtest`, spec in `PLAYTEST-DESIGN.md`) — answers *"is the game
good?"*. **Before running it on any game, work through `LESSONS.md` §B (P1–P11)** — the pre-flight
information-integrity audit that two balance batches paid for the hard way.

---

## Next steps (framework-level)

The game-specific next steps live in `Dev/STATUS.md`. The cross-game, framework-level priorities:

1. **Land the LLM balance tier as a first-class, repeatable batch.** The playtester is wired and
   smoke-validated on several games, but the CI-gated, seat/turn-order-controlled batch that produces a
   *trustworthy* balance verdict — with a confidence interval, compared against the game's own gate — is the
   maturity step. Read `LESSONS.md` §B before spending any batch.
2. **Formalize human/frontend UAT as an explicit fourth doorway.** It has only been tracked ad hoc for the
   engine-first games, and in every case it caught things — visual readability, onboarding, animation feel — no
   engine-level tier can see by construction. Every integration's `HANDOFF.md` should carry a UAT status line
   the same way it carries ladder status.

---

## Framework backlog (cross-game, not game-specific)

Revisit when an item actually blocks the current game, not on a schedule:

- **Config-driven CLI path for the trial ladder** — the per-game `verify_round*.py` scripts construct
  adapters directly; several adapters aren't registered under an `engine.type` in `env.py`. Worth a look now
  that every integration hand-rolls its own ladder scripts, and the direct-adapter playtest entry point was
  added specifically to sidestep this rather than solve it.
- **Browser feature map + screen detection** — `press_key`/`type_text` action syntax in `feature-map.yaml`,
  plus `detect_screen()`/`waitForScreen()` (needed for `ugt verify` to cover browser titles).
- **`ugt verify` doesn't support `engine.type: "real_server"`** — low priority; the ladder scripts cover it.
- **Desktop adapter** — `pyautogui` or a computer-use API for non-browser, non-terminal games.
- **HTML coverage report** — human-readable `coverage-report.html` generated from the JSON.
- **`ugt init --with-feature-map`** — scaffold a starter `feature-map.yaml` alongside `ugt.config.yaml`.

---

## Key references

| Thing | Where |
|---|---|
| Cross-game lessons registry (methodology + LLM pre-flight audit + operational discipline) | `LESSONS.md` |
| Onboard a new game + methodology | `UGT-USER-MANUAL.md` |
| LLM playtest design spec (tier 3) | `PLAYTEST-DESIGN.md` |
| Trial-ladder scaffold | `ugt/core/trial.py` (+ `ugt/core/exploit_hunter.py` for R3) |
| Framework overview + install | `README.md` |
| Per-game status ledger + game-specific next steps (**internal**) | `Dev/STATUS.md` |
| Superseded / historical docs (why + where content went) | `Dev/README.md` |

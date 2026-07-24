# UGT examples

Three self-contained, dependency-light examples, each demonstrating a different
part of UGT's methodology against a tiny throwaway game. None is tied to any real
product — they exist to be read and run.

| Example | Transport | Demonstrates | Runnable with |
|---|---|---|---|
| [`harness-game`](harness-game/) | subprocess **JSON-lines harness** (engine-first) | The **full trial ladder** — spike → smoke → R1 → R2 → R3, exploit-hunter, same-seed determinism — driven through a transport-only adapter. | Python only (zero deps) |
| [`mock-game`](mock-game/) | built-in **`simulation`** engine | The simplest CLI-wired integration: `ugt verify` / `ugt playtest`, config + feature map + strategy guide, seeded reproducibility. | `pip install -e .` |
| [`browser-game`](browser-game/) | built-in **`browser`** engine (Playwright) | The same game as a real web page, driven through `window` hooks — a feature map is transport-agnostic. | `+ playwright` |

## Where to start

1. **`harness-game`** — read its `README.md`, then run the five rungs in one line:
   ```bash
   for s in spike_foraging smoke_foraging_adapter verify_round1 verify_round2 verify_round3; do
     python3 examples/harness-game/$s.py || break
   done
   ```
   This is the fastest way to see the current methodology end to end: an engine
   that owns all the rules, an adapter that owns none of them, and a fail-closed
   ladder that asserts invariants after every step and proves determinism.

2. **`mock-game`** — the minimal `ugt.config.yaml` + `feature-map.yaml` +
   `strategy-guide.md`, wired to the CLI. Copy this shape to onboard a real game.

3. **`browser-game`** — the same game through a headless browser, showing the
   transport swap.

## The one rule every example is built to teach

**The adapter drives the real game; it never re-implements it.** In each example
the game's rules live in exactly one place (`engine.py`, `sim_game.py`, or the
page's `__SEND_ACTION__`), and the UGT adapter only moves state and actions across
the wire. That is rule **M1** in `../LESSONS.md`, and the reason the retired
`sim_bridge`-style example (a bridge that grew its own copy of a game's logic) was
removed in favor of `harness-game`.

## See also

- `../UGT-USER-MANUAL.md` — full onboarding walkthrough and the trial-ladder methodology
- `../LESSONS.md` — the cross-game lessons registry (read before any test run)
- `../PLAYTEST-DESIGN.md` — the LLM balance-playtester tier spec

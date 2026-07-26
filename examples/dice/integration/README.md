# Dice Duel — UGT integration

Drives `../game` (React + Vite) through UGT's built-in **`browser`** engine:
headless Chromium via Playwright, calling the `window.__GET_STATE__` /
`__SEND_ACTION__` / `__RESET__` hooks the game exposes. No adapter code and no
game logic on this side.

## Run it

```bash
# one-time
pip install -e ".[browser]" && playwright install chromium
cd examples/dice/game && npm install && npm run build   # dist/ is gitignored

# terminal 1
cd examples/dice/integration && python3 serve.py        # http://localhost:8080

# terminal 2
cd examples/dice/integration
ugt smoke-test --config ugt.config.yaml                                # Tier 0
ugt verify --config ugt.config.yaml --feature-map feature-map.yaml     # Tier 1
```

`exploit_hunt.py` needs no server running — it spawns and reaps its own on a
free port:

```bash
python3 examples/dice/integration/exploit_hunt.py                      # Tier 2
```

Recorded results (2026-07-25, game suite 156/156 green):

| Tier | Command | Result |
|---|---|---|
| 0 | `ugt smoke-test` | PASSED, 5/5 steps |
| 1 | `ugt verify` | **5/5 PASSED, 0 FAILED, 0 NOT_REACHED** |
| 2 | `exploit_hunt.py` | **TIER 2 MET — 8/8 checks**, 2 seeds x 120 steps, 0 findings |
| 3 | `ugt playtest` | guide written, **run not yet performed** (bills real API credits) |

## Where the PRD's six features live

All six are covered, but not all in `feature-map.yaml` — two of them are not
expressible in that model, so they are asserted in `exploit_hunt.py` instead.

| PRD | Rule | Where | Why |
|---|---|---|---|
| F1 | Attack reduces enemy force | feature map | |
| F2 | All-defense takes less damage than all-attack | **exploit_hunt.py** | comparison **between two rounds**; a feature only sees before/after of its own action list |
| F3 | Morale surge (+1 when ahead) | feature map | isolated at round 4 |
| F4 | Reinforcements (+2 at round 3) | feature map | isolated via the enemy, which has no other bonus that round |
| F5 | Reaching 0 force sets a decisive winner | **exploit_hunt.py** | **unreachable on the default seed** — see Findings |
| F6 | Round-12 cap forces a draw | feature map | |

The feature map adds a sixth of its own — `battle.concluded_battle_is_inert` —
because the adapter cannot see termination (Finding 2), so UGT keeps sending
actions into a finished battle and the harness depends on that being harmless.

## Findings

**1. A knockout is unreachable on the game's default seed — and draws dominate
generally.** This is a balance observation, not a bug, but it is the most
interesting thing this integration found. On the shipped default seed
(`'dice-duel'`), **205 action sequences** — 5 fixed policies plus 200
aggression-biased random ones — could not get the enemy below **1** force
strength inside the 12-round cap. Every single one ended `winner: "draw"`.
Widening to numeric seeds under pure all-attack, only **2 of 12** produced a
knockout. So even maximal aggression usually cannot finish a battle, and the
round cap, not the combat, decides most games. If the intended feel is
"decisive battles", either damage is too low or 12 rounds is too few. The
strategy guide tells the pilot this explicitly, so a Tier-3 playtest measures
skill rather than rediscovering the cap.

**2. `terminated` is always False for this game.** The browser hook returns a
bare projected state (by design — `ugtHooks.js` D14), so `PlaywrightAdapter`
takes its "legacy mode" path and reads lifecycle fields off the state dict:
`state.pop("terminated", False)`. Dice's contract exposes `battle_over`, not
`terminated`, so UGT never sees the battle end and keeps stepping a concluded
battle. Harmless here — a finished battle is inert, now asserted — but any
browser game whose terminal flag isn't literally named `terminated` has the
same blind spot, and an episode-based tier would run full-length empty episodes.

**3. `engine.reset_command` is silently ignored whenever `__RESET_GAME__`
exists.** In `PlaywrightAdapter.reset()`, the soft-reset branch runs first and
`reset_command` is only consulted in the `else`. Since the documented hook
contract tells games to expose `__RESET_GAME__`, any game that follows the
contract can never use `reset_command` — which is exactly what would have let
this integration pick a seed and test F5 through `ugt verify`. Configuring it
produces no error and no effect.

**4. `ugt verify` exits 0 even when features FAIL.** Same as recorded in
`examples/escape-room/integration/README.md` — `handle_verify` only exits
non-zero on an exception. Gate on the `failed` count in
`results/coverage-report.json`, not on `$?`.

## Notes

`feature-map.yaml` is one continuous battle split into five assertions, because
`ugt verify` resets once and never again. It relies on features running sorted
by `(priority, definition order)` — hence all `critical` — and on
`MAX_TASKS_PER_TURN = 3`. The file header documents both.

`exploit_hunt.py` spawns `serve.py` on an **ephemeral** port rather than 8080,
so a stale server left on 8080 cannot silently substitute its own bundle for
the one under test.

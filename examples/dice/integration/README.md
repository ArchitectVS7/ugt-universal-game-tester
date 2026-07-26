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
```

Every rung spawns and reaps its own server on an **ephemeral** port, so nothing
needs starting first and a stale server on :8080 can never be mistaken for the
bundle under test:

```bash
for s in spike_dice smoke_dice_adapter verify_round1 verify_round2 verify_round3; do
  python3 examples/dice/integration/$s.py || break
done
```

`ugt verify` still works too, and still needs a server:

```bash
cd examples/dice/integration && python3 serve.py &
ugt verify --config ugt.config.yaml --feature-map feature-map.yaml
```

Recorded results (2026-07-26, game suite 156/156 green):

| Rung | Script | Result |
|---|---|---|
| 1 | `spike_dice.py` | **SPIKE MET — 17/17** (+1 finding) |
| 2 | `smoke_dice_adapter.py` | **SMOKE MET — 8/8** (+1 finding) |
| 3 | `verify_round1.py` | **ROUND 1 MET — 12/12** |
| 4 | `verify_round2.py` | **ROUND 2 MET — 10/10** (+1 finding) |
| 5 | `verify_round3.py` | **ROUND 3 MET — 10/10** (+1 finding) |
| — | `ugt verify` (Tier 1, CLI) | 5/5 PASSED, 0 FAILED |
| — | `ugt playtest` (Tier 3) | guide written, **not run** (bills API credits) |

`exploit_hunt.py` is gone: R3 absorbed its random walks and determinism check,
and R2 took its defense-vs-attack A/B and its knockout drive, which are
content-spine claims and belong there. Invariants now live once in
`invariants.py` (`InvariantSuite`), shared by R1/R2 (`check_command`) and R3
(`to_hunter_invariants`), so the scripted and random tiers cannot drift.

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

**1. The spike found something four tiers of CLI testing never touched.**
`__SEND_ACTION__` **throws** a `RangeError` on an out-of-range or ill-typed
action id, where `escape-room` and `sokoban` both return current state
unchanged. `engine.js` does this deliberately — "validate, throwing rather than
coercing" — and state is *not* corrupted (verified across `-1, 7, 999, null,
'x', 1.5, undefined`: all rejected, all left the battle byte-identical, game
still usable afterwards). So it is a contract divergence, not a bug. But dice's
PRD never specifies hook-level behaviour, and a black-box client has to wrap
calls in `try/except` for this game and not the other two. Worth settling one
way across all three. Neither `ugt smoke-test` nor the feature map could ever
have found this: both only ever send ids drawn from the declared action space.

**2. The termination gap, now quantified.** The smoke rung asserts it and R3
measures the cost: in a 120-step random episode **only ~11 steps (9%) land on a
live battle**. The rest hammer a concluded one, because `PlaywrightAdapter`
reads `state.pop("terminated")` while the hooks expose `battle_over`, so UGT
never sees the match end and the episode never resets. The invariants do still
cover those steps — "a concluded battle stays inert" is a real property — but
the effective exploration budget is a tenth of the nominal step count. Adding
`terminated` to the hook payload is a one-line game change and would multiply
R3's useful coverage. This generalises: ANY browser game whose terminal flag
is not literally named `terminated` has the same blind spot.

**3. A knockout is unreachable on the game's default seed — and draws dominate
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

**4. `engine.reset_command` is silently ignored whenever `__RESET_GAME__`
exists.** In `PlaywrightAdapter.reset()`, the soft-reset branch runs first and
`reset_command` is only consulted in the `else`. Since the documented hook
contract tells games to expose `__RESET_GAME__`, any game that follows the
contract can never use `reset_command` — which is exactly what would have let
this integration pick a seed and test F5 through `ugt verify`. Configuring it
produces no error and no effect.

**5. `ugt verify` exits 0 even when features FAIL.** Same as recorded in
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

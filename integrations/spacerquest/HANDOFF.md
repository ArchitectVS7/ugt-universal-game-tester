# SpacerQuest (Rimward) — UGT integration handoff

This integration points UGT at the **Rimward redesign** of SpacerQuest through the
T-1003 **stdio protocol** — the line-delimited-JSON day-loop wire the SpacerQuest
sim exposes at `packages/sim/dist/protocol-stdio.js` — and it runs through
**UGT's own CLI phases** (smoke-test → verify → train → evaluate), not a
side-channel driver.

## What changed from the old, now-deleted `spacerquest_old/`

`integrations/spacerquest_old/` used to drive the **retired Museum-Edition**
`spacerquest-web` Socket.IO server (via `ugt/adapters/realclient.py`) and its rank
ladder (LIEUTENANT … GIGA_HERO). That server was the **quarantined legacy game**,
not Rimward. The folder was **deleted from this repo on 2026-07-21** — entirely
superseded by this Rimward integration; its history is preserved in
`Dev/PLAN-FORWARD-spacerquest.md` and `Dev/UGT-TRACK-RECORD.md`, not as live code.

Rimward has no Socket.IO server. It plays headlessly through a **pure protocol
core** (`packages/sim/src/protocol.ts` → `handleMessage`) wrapped by a stdio
transport shell (`protocol-stdio.ts`). The message set is a **day loop**, not a
Gym `step(action_id)`:

| request                                   | response                                             |
| ----------------------------------------- | ---------------------------------------------------- |
| `{"type":"new-game","seed":N}`            | `{"type":"state-summary","summary":{…}}` (day 1 DAWN)|
| `{"type":"start-day"}`                     | `{"type":"state-summary",…}` (DAWN → DAY, rolls dice)|
| `{"type":"legal-actions"}`                 | `{"type":"legal-actions","legalActions":{…}}`        |
| `{"type":"apply-action","action":{…}}`     | `{"type":"action-result","summary":{…},"events":[…]}`|
| `{"type":"end-day"}`                      | `{"type":"state-summary",…}` (DAY → next DAWN)       |

Full schema: SpacerQuest repo `packages/sim/PROTOCOL.md`.

## How UGT drives it: `rimward_gym_bridge.py`

UGT's generic `SubprocessAdapter` speaks a Gym-style
`{"command":"step","action_id":N}` wire. **`rimward_gym_bridge.py`** is the
transport shim between the two wires: UGT spawns the bridge (the config's
`engine.entry`), and the bridge spawns/speaks to the node protocol bin:

```
ugt CLI ▶ UniversalGameEnv ▶ SubprocessAdapter ──Gym wire──▶ rimward_gym_bridge.py ──Rimward wire──▶ node protocol-stdio.js
```

Like every UGT adapter (the ddd_harness lesson), the bridge contains **no game
logic**: every action id is STRUCTURAL — it selects among the LegalActionSpecs
the engine's own `legal-actions` enumerator advertised, filling parameters only
from the domains each spec declares. An `ActionBlocked` coming back from a
bridge-formed action is therefore a real parity defect (`blockedFromLegal`,
asserted 0 by the feature map's `parity_no_blocked_from_legal`).

Episodes (for the RL phases): terminated when the engine's own era leaves
`TOUR_ONE` (Tour One resolved; `victory` = resolved with the Guild marker paid),
truncated at `UGT_MAX_DAYS` (default 45). Each `reset` re-seeds deterministically
(`UGT_SEED + episode`).

Set `SPACERQUEST_UGT_LOG` to a path and the bridge appends one JSON line per
applied action — the auditable action-count evidence trail.

## Run recipe (all four UGT phases)

```sh
# From the SpacerQuest repo — build the protocol bin once:
npm run build -w @spacerquest/sim          # (or: npx tsc -b)

# From the UGT repo root:
export SPACERQUEST_UGT_LOG="$PWD/integrations/spacerquest/results/ugt-actions.jsonl"
python3 -m ugt.cli smoke-test --config integrations/spacerquest/ugt.config.yaml --profile rimward
python3 -m ugt.cli verify     --config integrations/spacerquest/ugt.config.yaml \
    --feature-map integrations/spacerquest/feature-map.yaml --max-turns 60
python3 -m ugt.cli train      --config integrations/spacerquest/ugt.config.yaml --profile rimward
python3 -m ugt.cli evaluate   --config integrations/spacerquest/ugt.config.yaml \
    --profile rimward --model integrations/spacerquest/models/ppo_rimward_final --episodes 5

# Raw-wire smoke (no Gym layer — speaks the Rimward wire directly):
python3 integrations/spacerquest/smoke_spacerquest_adapter.py
```

Override the bin path with `SPACERQUEST_STDIO_BIN` and the seed with `UGT_SEED`.

## T-1604 campaign results (2026-07-17)

| Phase | Result |
| --- | --- |
| `ugt smoke-test` | PASS — connection + obs/action mapping over the real wire |
| `ugt verify` (Phase 1) | **9/9 features PASSED (100%)** — `results/coverage-report.json` |
| `ugt train` (Phase 2a) | PPO 32,768 timesteps over the wire (~600 fps), model saved |
| `ugt evaluate` (Phase 2b) | **VALID** — trained mean **+124.0** vs random **−8.4**, entropy 0.76, no collapse (`results/rimward_eval_summary.json`) |
| Action log (all phases) | **71,107 actions**, **0 ActionBlocked from legal picks**, **0 protocol errors** (`results/ugt-actions-summary.json`) |

Note `results/INVALID_rimward_eval_summary.json`: the first eval (full 20-action
table, 4k→32k steps) collapsed to all-`wait` and UGT's collapse detector
correctly flagged it INVALID — kept as evidence the detector works. The fix was
UGT's own Gate-1 `training.action_subset` (see ugt.config.yaml), after which the
eval is valid and decisively above random.

The in-repo campaign harness (SpacerQuest `packages/sim/src/protocol-campaign.ts`,
12,000-action 6-seed sweep, machine-checked invariants + determinism) is the
SpacerQuest-side counterpart; both drive the same `handleMessage` core. Findings
report: SpacerQuest `docs/playtests/T-1604-ugt-campaign.md`.

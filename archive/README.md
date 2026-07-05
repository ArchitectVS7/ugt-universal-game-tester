# Archive — superseded documents

These docs are kept for history but no longer reflect the current direction. **Do not follow them as plans.**
See `../PLAN-FORWARD.md` (start here) and the memory note `architecture-pivot-real-server` for the current state.

| File | Date | Why archived |
|---|---|---|
| `GATE-1-LEARNABILITY-SPEC.md` | 2026-07-03 | The RL learnability smoke test. **Gate 1 was run and PASSED** (PPO can learn a reachable trade loop), but it ran against the `sim_bridge.ts` re-implementation, which we later found omits combat and mis-handles upgrades — i.e. it certified a *different game* than the real one. The whole bridge-based RL-training approach is retired in favor of driving the real server. The learnability *idea* (prove an agent can beat random cheaply before scaling) survives as reusable methodology in the User Manual. |
| `UNIVERSAL-ML-TESTER-ASSESSMENT.md` | 2026-05-24 | The original "turn the Warzones prototype into a universal tester" vision. Superseded by reality and by the more accurate `../ASSESSMENT-AND-FIX-ROADMAP.md` (2026-06-29), which correctly predicted the scope we landed on. |
| `WALKTHROUGH.md` | 2026-05-24 | Early "we successfully built and verified UGT" walkthrough. Rosy and pre-dates every hard lesson (RL collapse, verify≠train, combat-not-in-bridge, the real-client pivot). Kept only as origin history. |

**Still-active docs (NOT archived):** `../ASSESSMENT-AND-FIX-ROADMAP.md` (accurate critical review), `../AGENT-PLAYTEST-FRAMEWORK.md`
(LLM playtest spec — relevant to the Phase-2 balance tier), `../UGT-USER-MANUAL.md` (onboarding a new game),
`../DEV-CHECKLIST.md` (UGT framework build status).

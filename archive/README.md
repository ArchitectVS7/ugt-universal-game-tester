# Archive — superseded documents

These docs are kept for history but no longer reflect the current direction. **Do not follow them as plans.**
See `../PLAN-FORWARD.md` (start here) and the memory note `architecture-pivot-real-server` for the current state.

| File | Date | Why archived |
|---|---|---|
| `GATE-1-LEARNABILITY-SPEC.md` | 2026-07-03 | The RL learnability smoke test. **Gate 1 was run and PASSED** (PPO can learn a reachable trade loop), but it ran against the `sim_bridge.ts` re-implementation, which we later found omits combat and mis-handles upgrades — i.e. it certified a *different game* than the real one. The whole bridge-based RL-training approach is retired in favor of driving the real server. The learnability *idea* (prove an agent can beat random cheaply before scaling) survives as reusable methodology in the User Manual. |
| `UNIVERSAL-ML-TESTER-ASSESSMENT.md` | 2026-05-24 | The original "turn the Warzones prototype into a universal tester" vision. Superseded by reality and by the more accurate `../ASSESSMENT-AND-FIX-ROADMAP.md` (2026-06-29), which correctly predicted the scope we landed on. |
| `WALKTHROUGH.md` | 2026-05-24 | Early "we successfully built and verified UGT" walkthrough. Rosy and pre-dates every hard lesson (RL collapse, verify≠train, combat-not-in-bridge, the real-client pivot). Kept only as origin history. |
| `ASSESSMENT-AND-FIX-ROADMAP.md` | 2026-06-29 | Consolidated 2026-07-05. Correctly diagnosed the RL collapse (still good evidence/history), but its Phase C/D/E fix roadmap (self-play, action masking, sparse reward) targets making **RL trustworthy for balance** — a goal the project abandoned when RL was demoted to the exploit-hunter/robustness role. Phase A (collapse detection, seeding) is done and recorded in `PLAN-FORWARD.md`. |
| `AGENT-PLAYTEST-FRAMEWORK.md` | 2026-07-01 (approx.) | Consolidated 2026-07-05. Got the RL/LLM division of labor backwards (cast the LLM as correctness-only, RL as the balance judge — the opposite of current direction) and specced a separate TypeScript `ugt-harness` tool that was never built. Still-valid design content (state-delta assertions, RNG seams, the LLM action contract, bug-report shape) was extracted and corrected into `../PLAYTEST-DESIGN.md`. |
| `DEV-CHECKLIST.md` | 2026-07-04 | Consolidated 2026-07-05. Framework build-status log; its "Phase 1/2/3" numbering collided with `PLAN-FORWARD.md`'s own Phase 0/1/2 (different meanings for the same word). Completed-work record is superseded by `PLAN-FORWARD.md`; its still-open "Future Work" items were folded into `PLAN-FORWARD.md`'s "Framework backlog" section. |

**Still-active docs (NOT archived):** `../UGT-USER-MANUAL.md` (onboarding a new game), `../PLAYTEST-DESIGN.md`
(LLM playtest spec — Phase 2 balance tier).

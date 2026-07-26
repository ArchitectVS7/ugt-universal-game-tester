/**
 * bridge.js — machine-facing JSON-lines front end for UGT's SubprocessAdapter.
 *
 * Translation layer only: maps a numeric action_id to a (verb, objectId |
 * direction) pair and calls engine.executeCommand(). It never re-implements a
 * rule (see src/engine.js).
 *
 * The protocol below is fixed by PRD.md and cannot change independently — the
 * integration side is written against this exact shape. Recorded here verbatim
 * so T-006 implements it without drift:
 *
 *   {"command": "reset"}
 *     -> {"state": {...}}
 *   {"command": "step", "action_id": N}
 *     -> {"state": {...}, "terminated": bool, "truncated": bool, "info": {}}
 *   {"command": "close"}
 *     -> clean process exit
 *
 * State shape:
 *   {
 *     "current_room": "R05",
 *     "inventory": ["key_brass", "lantern"],
 *     "flags": {"has_brass_key": true, "found_map": false},
 *     "moves_taken": 14,
 *     "rooms_visited": 6,
 *     "escaped": false
 *   }
 *
 * `escaped` becomes true the moment the player successfully enters R10;
 * `terminated` in the step response mirrors it.
 *
 * Deterministic action-id assignment (built once at startup from the CSVs, so
 * it is stable for the whole run):
 *   0=north, 1=south, 2=east, 3=west, 4=look, 5=inventory
 * then, for each row of objects.csv in file order, append in this per-object
 * order: take (if takeable), drop (if takeable), examine, use (if use_verb set).
 * An action invalid in the current context is a no-op that still returns state.
 *
 * TODO(T-006): implement the action table + the stdin/stdout JSON-lines loop.
 */

export {};

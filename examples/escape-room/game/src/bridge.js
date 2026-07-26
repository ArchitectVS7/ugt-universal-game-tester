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
 * Two invariants a reader must not break:
 *
 * 1. **stdout is a protocol channel.** Nothing but exactly one JSON line per
 *    command ever goes there — no banner, no farewell, no debug print. The
 *    adapter treats any non-JSON line as a hard error. Diagnostics go to stderr.
 * 2. **No rule lives here.** The action table is the engine's
 *    (`buildActionTable`), `terminated` is a read of the engine-owned latching
 *    `state.escaped`, and an invalid action_id is not *refused* by a rule the
 *    bridge invents — it is simply never dispatched. An in-context refusal
 *    (`use` on something not held, `take` on something not here) is the
 *    engine's, and already mutates nothing at all, including `moves_taken`.
 *
 * The game has no randomness, so the adapter's `UGT_SEED` environment variable
 * is deliberately ignored: the same action sequence always replays identically.
 */

import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

import {
  buildActionTable,
  createGame,
  executeCommand,
  getState,
  loadContent,
} from './engine.js';

/**
 * Apply one decoded protocol message to a session.
 *
 * Pure dispatch: it decides *nothing* about the world, only which engine call
 * (if any) a message maps to.
 *
 * @param {unknown} message the parsed JSON line
 * @param {{content: object, actions: ReadonlyArray<object>, game: object}} session
 *   mutable session — `reset` replaces `session.game`; `content`/`actions` are
 *   built once at startup and never rebuilt
 * @returns {{response: object|null, close: boolean}} `response` is the single
 *   line to write (null = write nothing); `close` ends the loop
 */
export function handleCommand(message, session) {
  const command =
    message !== null && typeof message === 'object' ? message.command : undefined;

  if (command === 'reset') {
    session.game = createGame(session.content);
    // PRD's reset shape is exactly one key — no terminated/truncated/info.
    return { response: { state: getState(session.game) }, close: false };
  }

  if (command === 'step') {
    const id = message.action_id;
    const known = Number.isInteger(id) && id >= 0 && id < session.actions.length;
    // An unknown / ill-typed / missing id is never dispatched: no engine call,
    // no move consumed, current state returned unchanged.
    const state = known
      ? executeCommand(session.game, session.actions[id].verb, session.actions[id].arg).state
      : getState(session.game);

    return {
      response: {
        state,
        terminated: state.escaped, // mirrors the engine's latching flag
        truncated: false, // no timers or step caps in this game (PRD non-goals)
        info: {}, // frozen by PRD: nothing is smuggled in here
      },
      close: false,
    };
  }

  if (command === 'close') return { response: null, close: true };

  // Always answer something, so a client is never left blocking on readline.
  return { response: { error: `Unknown command: ${command}` }, close: false };
}

/**
 * Run the stdin/stdout JSON-lines loop over the real content.
 *
 * @param {{input?: NodeJS.ReadableStream, output?: NodeJS.WritableStream}} [streams]
 * @returns {import('node:readline').Interface}
 */
export function runBridge({ input = process.stdin, output = process.stdout } = {}) {
  const content = loadContent();
  const session = {
    content,
    // Built ONCE, here — never inside the reset path (PRD: "stable across the
    // whole run").
    actions: buildActionTable(content),
    // An implicit initial reset, so a `step` arriving before any `reset` reads
    // a fresh game instead of crashing.
    game: createGame(content),
  };

  // `output` is deliberately NOT handed to readline: it would echo input and
  // print prompts onto the protocol stream. Responses are written by hand.
  const rl = createInterface({ input, crlfDelay: Infinity });

  // A whole pipe-full of input arrives as one chunk, and readline emits every
  // buffered line from it before rl.close() takes effect — so `close` needs an
  // explicit latch, or trailing lines would still be answered after it.
  let closed = false;

  rl.on('line', (line) => {
    if (closed) return;

    const text = line.trim();
    if (text === '') return; // blank lines are ignored, not answered

    let message;
    try {
      message = JSON.parse(text);
    } catch (err) {
      // Never a stdout line for garbage input — that would corrupt the stream.
      process.stderr.write(`bridge: ignoring unparseable line (${err.message})\n`);
      return;
    }

    const { response, close } = handleCommand(message, session);
    if (response !== null) output.write(`${JSON.stringify(response)}\n`);
    // `close` gets no response line: the adapter still does a blocking read
    // after sending it, and takes EOF on our stdout as the answer. That read
    // has no timeout, so the process MUST actually end — closing the readline
    // interface alone does not, because the open stdin pipe keeps the event
    // loop alive. Releasing the input handle is what lets Node drain stdout and
    // exit 0 on its own (an explicit process.exit() here could truncate a
    // response still queued on the stdout pipe).
    if (close) {
      closed = true;
      rl.close();
      input.pause();
      input.destroy?.();
    }
  });

  // No farewell on close, and no process.exit() — a pending pipe write can be
  // truncated by an explicit exit. Ending the interface lets Node drain and
  // exit 0 on its own.
  return rl;
}

/* Only start a session when run as a program — importing this module (the unit
 * tests do) must have no side effects. */
const invokedDirectly =
  process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href;

if (invokedDirectly) {
  if (process.argv.includes('--actions')) {
    // One-shot dump, not part of the protocol: lets the integration side
    // generate ugt.config.yaml's action_space straight from the CSVs.
    process.stdout.write(`${JSON.stringify(buildActionTable(), null, 2)}\n`);
  } else {
    runBridge();
  }
}

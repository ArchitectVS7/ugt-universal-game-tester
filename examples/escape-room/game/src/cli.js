/**
 * cli.js — human-facing REPL front end (T-005).
 *
 * Translation layer only. This file turns a typed line into a
 * `(verb, arg)` pair and hands it to `executeCommand()`, then prints whatever
 * comes back. It contains NO rule: every refusal string, every gate check,
 * every puzzle effect and the `escaped` transition itself belong to
 * `src/engine.js`. An unknown verb is dispatched to the engine unchanged so the
 * engine — the single owner of refusal text — answers it; the CLI never writes
 * its own "I don't understand".
 *
 * It also contains NO content: no room, object or flag name appears here. The
 * only literals are this front end's own chrome — the banner, the prompt, the
 * `help` verb listing, `You escape!` and `Goodbye.`.
 *
 * Direction vocabulary is not duplicated either: the bare-direction shorthand
 * ("just type `n`") asks the engine via `normalizeDirection()`.
 */

import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

import {
  createGame,
  describeRoom,
  executeCommand,
  normalizeDirection,
} from './engine.js';

/**
 * The eight PRD verbs, as shown by `help`. This is front-end chrome (how the
 * player is told to type), not a rule table — the CLI does not validate against
 * it, it dispatches everything to the engine.
 */
const HELP_LINES = [
  'Commands:',
  '  look                 describe the room again',
  '  go <direction>       move (north/south/east/west, or just n/s/e/w)',
  '  take <object>        pick something up',
  '  drop <object>        put something down',
  '  inventory            list what you are carrying (also: inv, i)',
  '  examine <object>     look at something closely',
  '  use <object>         use something you are carrying',
  '  help                 show this list',
  '',
  'Press Ctrl+D to quit.',
];

const BANNER = 'Tiny Escape Room';
const HINT = 'Type `help` for commands. Ctrl+D to quit.';
const ESCAPE_BANNER = 'You escape!';
const FAREWELL = 'Goodbye.';

/** Articles stripped from the front of an argument. Parsing, not vocabulary. */
const ARTICLES = new Set(['the', 'a', 'an']);

/**
 * Parse one typed line into something dispatchable.
 *
 * Purely textual work — it never inspects game state and never decides whether
 * a command is legal:
 * - blank line            → `null` (caller just reprompts)
 * - `help`                → `{kind: 'help'}` (the one verb the engine doesn't know)
 * - a bare direction      → `{verb: 'go', arg: <canonical direction>}`
 * - anything else         → `{verb, arg}` verbatim, **including nonsense verbs**,
 *   so the engine gets to issue the refusal.
 *
 * @param {string} line
 * @returns {null | {kind: 'help'} | {verb: string, arg: string}}
 */
export function parseInput(line) {
  const input = typeof line === 'string' ? line.trim() : '';
  if (input === '') return null;

  const match = /^(\S+)\s*([\s\S]*)$/.exec(input);
  const verb = match[1].toLowerCase();
  let arg = match[2].trim();

  if (arg === '') {
    const dir = normalizeDirection(verb);
    if (dir !== null) return { verb: 'go', arg: dir };
  }

  if (verb === 'help') return { kind: 'help' };

  const spaceAt = arg.indexOf(' ');
  if (spaceAt !== -1 && ARTICLES.has(arg.slice(0, spaceAt).toLowerCase())) {
    arg = arg.slice(spaceAt + 1).trim();
  }

  return { verb, arg };
}

/**
 * Start the interactive loop over the real content.
 *
 * @param {{input?: NodeJS.ReadableStream, output?: NodeJS.WritableStream}} [streams]
 * @returns {import('node:readline').Interface}
 */
export function runRepl({ input = process.stdin, output = process.stdout } = {}) {
  const game = createGame();
  const rl = createInterface({ input, output, prompt: '> ' });
  const say = (text) => output.write(`${text}\n`);

  let escaped = false;

  say(BANNER);
  say(HINT);
  say('');
  say(describeRoom(game));

  rl.prompt();

  rl.on('line', (line) => {
    if (escaped) return; // buffered input after the escape is ignored, not replayed

    const parsed = parseInput(line);
    if (parsed === null) {
      rl.prompt();
      return;
    }

    if (parsed.kind === 'help') {
      for (const helpLine of HELP_LINES) say(helpLine);
      rl.prompt();
      return;
    }

    let state = null;
    try {
      const result = executeCommand(game, parsed.verb, parsed.arg);
      say(result.message);
      state = result.state;
    } catch (err) {
      // Never crash out of a session on a bad line: report and keep playing.
      say(err.message);
    }

    // `escaped` is engine-owned and latching; the CLI only reads it.
    if (state !== null && state.escaped) {
      escaped = true;
      say('');
      say(ESCAPE_BANNER);
      say(`Moves taken: ${state.moves_taken}. Rooms visited: ${state.rooms_visited}.`);
      rl.close();
      return;
    }

    rl.prompt();
  });

  rl.on('close', () => {
    say(FAREWELL);
  });

  return rl;
}

/* Only start a session when run as a program — importing this module (the unit
 * tests do) must have no side effects. */
const invokedDirectly =
  process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href;

if (invokedDirectly) runRepl();

/**
 * T-005 — the human CLI.
 *
 * Two halves:
 * - `parseInput` unit tests: pure text → dispatch shape. Importing `cli.js`
 *   must be side-effect free (the entrypoint guard); if it ever starts a REPL,
 *   these tests hang, which is itself the check.
 * - End-to-end sessions that spawn the REAL `node src/cli.js` process and type
 *   at it over stdin exactly as a human would, then read stdout. No in-process
 *   shortcut, no direct `executeCommand()` call to stand in for a typed line —
 *   the point of this task's Accept is the typed-text path.
 *
 * No room, object or flag id is hardcoded here: the typed script is derived
 * from `content/walkthrough.json` plus the display names in the loaded CSVs,
 * and the expected refusal comes from the engine itself.
 */

import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

import {
  CONTENT_DIR,
  createGame,
  executeCommand,
  loadContent,
} from '../src/engine.js';
import { parseInput } from '../src/cli.js';

const CLI = fileURLToPath(new URL('../src/cli.js', import.meta.url));

const content = loadContent();
const walkthrough = JSON.parse(
  readFileSync(new URL('walkthrough.json', CONTENT_DIR), 'utf8'),
);

/** Whatever the ENGINE says to an unknown verb — never a literal copy of it. */
const UNKNOWN_VERB = executeCommand(createGame(), 'xyzzy', 'frobnitz').message;

/**
 * Run one CLI session: pipe `lines` at the real process, EOF, collect output.
 * EOF on the pipe is the player's Ctrl+D.
 */
function playSession(lines) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [CLI], {
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error(`CLI session did not exit; stdout so far:\n${stdout}`));
    }, 20000);

    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk) => {
      stdout += chunk;
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk;
    });
    child.on('error', (err) => {
      clearTimeout(timer);
      reject(err);
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({ code, stdout, stderr });
    });

    child.stdin.end(`${lines.join('\n')}\n`);
  });
}

describe('parseInput', () => {
  it('lowercases the verb and keeps the argument as typed', () => {
    assert.deepEqual(parseInput('GO North'), { verb: 'go', arg: 'North' });
  });

  it('treats a bare direction (long or short, any case) as go', () => {
    for (const typed of ['n', 'N', 'north', 'NORTH', ' w ']) {
      assert.deepEqual(
        parseInput(typed),
        { verb: 'go', arg: typed.trim().toLowerCase() === 'w' ? 'west' : 'north' },
        `bare direction ${JSON.stringify(typed)}`,
      );
    }
  });

  it('keeps a multi-word object argument intact', () => {
    assert.deepEqual(parseInput('take iron key'), { verb: 'take', arg: 'iron key' });
  });

  it('strips a leading article from the argument', () => {
    assert.deepEqual(parseInput('take the iron key'), { verb: 'take', arg: 'iron key' });
  });

  it('trims surrounding whitespace and yields an empty arg for a lone verb', () => {
    assert.deepEqual(parseInput('  look  '), { verb: 'look', arg: '' });
  });

  it('passes inventory aliases through for the engine to resolve', () => {
    assert.deepEqual(parseInput('inv'), { verb: 'inv', arg: '' });
    assert.deepEqual(parseInput('i'), { verb: 'i', arg: '' });
  });

  it('returns null for a blank line', () => {
    assert.equal(parseInput(''), null);
    assert.equal(parseInput('   '), null);
  });

  it('handles help itself — the one verb the engine does not know', () => {
    assert.deepEqual(parseInput('help'), { kind: 'help' });
    assert.equal(executeCommand(createGame(), 'help').message, UNKNOWN_VERB);
  });

  it('does not swallow an unknown verb — the engine owns the refusal', () => {
    assert.deepEqual(parseInput('xyzzy frobnicate'), {
      verb: 'xyzzy',
      arg: 'frobnicate',
    });
  });
});

describe('CLI session (spawned process, typed input)', () => {
  it('plays the walkthrough to "You escape!" as typed commands', { timeout: 30000 }, async () => {
    // Derive the typed script: directions alternate between the full word and
    // the bare shorthand so both parse paths are exercised; object steps use the
    // human-facing DISPLAY NAME from objects.csv, not the object_id.
    const lines = ['xyzzy the frobnitz', 'help', 'look'];
    let extrasDone = false;
    let goCount = 0;

    for (const step of walkthrough) {
      if (step.verb === 'go') {
        goCount += 1;
        lines.push(goCount % 2 === 0 ? step.object[0] : `go ${step.object}`);
        continue;
      }
      const name = content.objects.get(step.object).name;
      lines.push(`${step.verb} ${name}`);

      // Right after the first pickup, exercise the remaining verbs on an object
      // we are holding, then put it back where we found it.
      if (!extrasDone && step.verb === 'take') {
        extrasDone = true;
        lines.push('inv', `examine ${name}`, `drop ${name}`, `take ${name}`);
      }
    }

    const { code, stdout, stderr } = await playSession(lines);

    assert.equal(stderr, '', `CLI wrote to stderr:\n${stderr}`);
    assert.equal(code, 0);

    // Accept clause 1: the walkthrough, typed, reaches the escape banner.
    assert.match(stdout, /You escape!/);

    // Accept clause 2: gibberish is refused (in the engine's words) mid-session.
    assert.ok(
      stdout.includes(UNKNOWN_VERB),
      `expected the engine's unknown-verb refusal in the transcript:\n${stdout}`,
    );

    // Authored flavor text is actually printed, not swallowed: check the
    // success text of the walkthrough's final `use`.
    const lastUse = [...walkthrough].reverse().find((s) => s.verb === 'use');
    const flavor = content.objects.get(lastUse.object).useSuccessText;
    assert.ok(flavor.length > 0);
    assert.ok(stdout.includes(flavor), 'use_success_text was not printed');

    // `examine` renders the CSV description of the first object taken.
    const firstTake = walkthrough.find((s) => s.verb === 'take');
    assert.ok(stdout.includes(content.objects.get(firstTake.object).description));

    // Arrival in the exit room printed its authored room name + description.
    const escapeRoom = content.rooms.get(createGame().escapeRoom);
    assert.ok(stdout.includes(escapeRoom.name));
    assert.ok(stdout.includes(escapeRoom.description));

    // `help` and `inventory` produced their own output.
    assert.match(stdout, /Commands:/);
    assert.match(stdout, /You are carrying: /);

    // Ctrl+D / end of the session still says goodbye.
    assert.match(stdout, /Goodbye\.\n$/);
  });

  it('refuses unrecognized input without crashing', { timeout: 30000 }, async () => {
    const { code, stdout, stderr } = await playSession(['xyzzy']);

    assert.equal(stderr, '', `CLI wrote to stderr:\n${stderr}`);
    assert.equal(code, 0);
    assert.ok(stdout.includes(UNKNOWN_VERB));
    assert.doesNotMatch(stdout, /You escape!/);
    assert.match(stdout, /Goodbye\.\n$/);
  });

  it('starts by describing the start room without spending a move', { timeout: 30000 }, async () => {
    const { stdout } = await playSession(['inventory']);
    const startRoom = content.rooms.get(createGame().startRoom);

    assert.ok(stdout.includes(startRoom.description), 'opening room was not described');
    // A pristine `look` at startup must not have been dispatched as a command:
    // the room text appears exactly once for a session that never typed `look`.
    assert.equal(stdout.split(startRoom.description).length - 1, 1);
  });
});

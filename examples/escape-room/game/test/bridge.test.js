/**
 * T-006 — the machine bridge (JSON-lines).
 *
 * Two halves:
 * - `buildActionTable` unit tests: the deterministic id assignment PRD pins.
 *   Importing `bridge.js` must be side-effect free (the entrypoint guard); if
 *   it ever starts reading stdin, these tests hang, which is itself the check.
 * - Sessions that spawn the REAL `node src/bridge.js` and pipe JSON lines at it
 *   over stdin exactly as UGT's SubprocessAdapter does, then parse stdout. No
 *   in-process shortcut stands in for the piped protocol — that path IS this
 *   task's Accept.
 *
 * Nothing about the world is hardcoded here: every room id, object id, action
 * id, table length and step count is derived from the loaded CSVs and
 * `content/walkthrough.json`, so a content edit re-derives the expectations
 * instead of breaking them.
 */

import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

import {
  CONTENT_DIR,
  buildActionTable,
  createGame,
  getState,
  loadContent,
} from '../src/engine.js';
import { handleCommand } from '../src/bridge.js';

const BRIDGE = fileURLToPath(new URL('../src/bridge.js', import.meta.url));

const content = loadContent();
const actions = buildActionTable(content);
const walkthrough = JSON.parse(
  readFileSync(new URL('walkthrough.json', CONTENT_DIR), 'utf8'),
);

/** The action id for a (verb, arg) pair — never a hardcoded number. */
function idFor(verb, arg) {
  const id = actions.findIndex((a) => a.verb === verb && a.arg === arg);
  assert.ok(id >= 0, `no action for ${verb} ${JSON.stringify(arg)}`);
  return id;
}

/** The action id a walkthrough step maps to (`go` carries a direction). */
function idForStep(step) {
  return idFor(step.verb, step.object);
}

/**
 * Pipe `lines` at a real `node src/bridge.js`, close stdin, collect everything.
 * The protocol is strict request/response, so writing the whole script up front
 * and reading the responses back in order is safe.
 */
function runBridgeSession(lines) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [BRIDGE], { stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error(`bridge session did not exit; stdout so far:\n${stdout}`));
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
      const responses = stdout
        .split('\n')
        .filter((l) => l.trim() !== '')
        .map((l) => {
          try {
            return JSON.parse(l);
          } catch (err) {
            throw new Error(`non-JSON line on stdout: ${JSON.stringify(l)} (${err.message})`);
          }
        });
      resolve({ code, stdout, stderr, responses });
    });

    child.stdin.end(`${lines.map((l) => JSON.stringify(l)).join('\n')}\n`);
  });
}

/**
 * Same, but the parent NEVER closes stdin — UGT's SubprocessAdapter keeps its
 * stdin pipe open for the whole episode and relies on the `close` command (plus
 * a blocking, un-timed read) to end the process. A bridge that only stops
 * reading, without releasing the input handle, hangs the adapter forever here
 * while looking perfectly healthy to a test that sends EOF.
 */
function runBridgeSessionStdinOpen(lines) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [BRIDGE], { stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error('bridge did not exit on `close` while stdin stayed open'));
    }, 10000);

    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (c) => {
      stdout += c;
    });
    child.stderr.on('data', (c) => {
      stderr += c;
    });
    child.on('error', (err) => {
      clearTimeout(timer);
      reject(err);
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({ code, stdout, stderr });
    });

    child.stdin.write(`${lines.map((l) => JSON.stringify(l)).join('\n')}\n`);
    // Deliberately no child.stdin.end().
  });
}

const RESET = { command: 'reset' };
const CLOSE = { command: 'close' };
const step = (action_id) => ({ command: 'step', action_id });

describe('buildActionTable', () => {
  it('assigns 0-5 to the four directions, look and inventory, in PRD order', () => {
    assert.deepEqual(
      actions.slice(0, 6).map((a) => [a.verb, a.arg]),
      [
        ['go', 'north'],
        ['go', 'south'],
        ['go', 'east'],
        ['go', 'west'],
        ['look', null],
        ['inventory', null],
      ],
    );
  });

  it('appends per-object verbs in objects.csv file order, take/drop/examine/use', () => {
    // Rebuild the expectation from the PRD rule so this pins the ORDERING, not
    // the current content.
    const expected = [
      { verb: 'go', arg: 'north', name: 'go_north' },
      { verb: 'go', arg: 'south', name: 'go_south' },
      { verb: 'go', arg: 'east', name: 'go_east' },
      { verb: 'go', arg: 'west', name: 'go_west' },
      { verb: 'look', arg: null, name: 'look' },
      { verb: 'inventory', arg: null, name: 'inventory' },
    ];
    for (const obj of content.objects.values()) {
      if (obj.takeable) {
        expected.push({ verb: 'take', arg: obj.id, name: `take_${obj.id}` });
        expected.push({ verb: 'drop', arg: obj.id, name: `drop_${obj.id}` });
      }
      expected.push({ verb: 'examine', arg: obj.id, name: `examine_${obj.id}` });
      if (obj.useVerb !== null) {
        expected.push({ verb: 'use', arg: obj.id, name: `use_${obj.id}` });
      }
    }

    assert.deepEqual([...actions], expected);
  });

  it('gives a non-takeable object only examine, and an unusable object no use', () => {
    const fixed = [...content.objects.values()].find((o) => !o.takeable);
    assert.ok(fixed, 'content has no non-takeable object to check');
    assert.deepEqual(
      actions.filter((a) => a.arg === fixed.id).map((a) => a.verb),
      ['examine'],
    );

    const inert = [...content.objects.values()].find((o) => o.useVerb === null);
    assert.ok(inert, 'content has no object without a use_verb to check');
    assert.ok(!actions.some((a) => a.arg === inert.id && a.verb === 'use'));
  });

  it("uses the engine verb 'use', never the object's authored use_verb", () => {
    const usable = [...content.objects.values()].filter((o) => o.useVerb !== null);
    assert.ok(usable.length > 0);
    for (const obj of usable) {
      const entry = actions.find((a) => a.arg === obj.id && a.verb === 'use');
      assert.ok(entry, `no use action for ${obj.id}`);
      assert.equal(entry.verb, 'use');
      assert.notEqual(entry.verb, obj.useVerb); // e.g. 'unlock' is flavor, not a command
    }
  });

  it('is deterministic, frozen, within budget, and only names real objects', () => {
    assert.deepEqual([...buildActionTable()], [...buildActionTable()]);
    assert.ok(Object.isFrozen(actions));
    assert.ok(actions.every((a) => Object.isFrozen(a)));

    assert.ok(actions.length <= 60, `action space is ${actions.length}, PRD budget is 60`);

    for (const a of actions.slice(6)) {
      assert.ok(content.objects.has(a.arg), `action arg ${a.arg} is not an object_id`);
    }
    assert.equal(new Set(actions.map((a) => a.name)).size, actions.length);
  });
});

describe('bridge protocol (spawned process, piped JSON lines)', () => {
  it('escapes when the walkthrough is piped in as action_ids', { timeout: 30000 }, async () => {
    const lines = [RESET, ...walkthrough.map((s) => step(idForStep(s))), CLOSE];
    const { code, stdout, stderr, responses } = await runBridgeSession(lines);

    assert.equal(stderr, '', `bridge wrote to stderr:\n${stderr}`);
    assert.equal(code, 0);

    // Exactly one line per command, and `close` answers with nothing.
    assert.equal(responses.length, 1 + walkthrough.length);
    assert.equal(stdout.split('\n').filter((l) => l.trim() !== '').length, responses.length);

    // reset returns PRD's one-key shape and a pristine game.
    const [resetResponse, ...steps] = responses;
    assert.deepEqual(Object.keys(resetResponse), ['state']);
    assert.deepEqual(resetResponse.state, getState(createGame(content)));

    for (const [i, resp] of steps.entries()) {
      assert.deepEqual(
        Object.keys(resp),
        ['state', 'terminated', 'truncated', 'info'],
        `step ${i} response shape`,
      );
      assert.equal(resp.truncated, false);
      // The engine's narration rides in info.message. Asserted as NON-EMPTY
      // rather than as a literal: every accepted command in this walkthrough
      // produces authored text, and the bridge used to drop all of it.
      assert.equal(typeof resp.info.message, 'string');
      assert.ok(
        resp.info.message.length > 0,
        `step ${i} carried no narration`,
      );
      assert.equal(
        resp.terminated,
        i === steps.length - 1,
        `step ${i} terminated should only be true on the final step`,
      );
    }

    // Accept clause 1: the walkthrough reaches escaped: true.
    const final = steps.at(-1).state;
    assert.equal(final.escaped, true);
    assert.equal(final.current_room, [...content.rooms.keys()].at(-1));
    // Every walkthrough action actually succeeded — a silent refusal mid-run
    // would leave moves_taken short.
    assert.equal(final.moves_taken, walkthrough.length);
  });

  it('treats an unknown action_id as a no-op that still returns state', { timeout: 30000 }, async () => {
    // Take a couple of real steps first so the state isn't trivially initial.
    const realSteps = walkthrough.slice(0, 3).map((s) => step(idForStep(s)));
    const bogus = [
      step(actions.length), // one past the end
      step(-1),
      step(9999),
      step(1.5), // not an integer
      step('take'), // wrong type
      step(null),
      { command: 'step' }, // no action_id at all
    ];
    // `look` is the one action that is legal in every room, so the "still
    // works afterwards" probe can't be refused for a content reason.
    const lines = [RESET, ...realSteps, ...bogus, step(idFor('look', null)), CLOSE];
    const { code, stderr, responses } = await runBridgeSession(lines);

    assert.equal(stderr, '', `bridge wrote to stderr:\n${stderr}`);
    assert.equal(code, 0);
    assert.equal(responses.length, lines.length - 1); // close answers nothing

    const before = responses[realSteps.length].state; // last real step's state
    for (let i = 0; i < bogus.length; i += 1) {
      const resp = responses[realSteps.length + 1 + i];
      assert.deepEqual(
        resp.state,
        before,
        `bogus action ${JSON.stringify(bogus[i])} changed state`,
      );
      assert.equal(resp.terminated, false);
      // Never dispatched, so there is no engine narration to report — but the
      // key is still present, so a client never has to branch on its absence.
      assert.deepEqual(resp.info, { message: '' });
    }

    // The loop never desynced: a valid action still lands afterwards.
    const after = responses.at(-1).state;
    assert.equal(after.moves_taken, before.moves_taken + 1);
  });

  it('treats an out-of-context but valid action as a no-op (the engine refuses)', { timeout: 30000 }, async () => {
    // Derived, not hardcoded: something usable that isn't held at the start,
    // and something takeable that isn't in the start room.
    const startRoom = createGame(content).startRoom;
    const usable = [...content.objects.values()].find((o) => o.useVerb !== null);
    const elsewhere = [...content.objects.values()].find(
      (o) => o.takeable && o.startRoom !== startRoom,
    );
    assert.ok(usable && elsewhere, 'content lacks an out-of-context case to probe');

    const probes = [
      step(idFor('use', usable.id)), // not carried
      step(idFor('take', elsewhere.id)), // not in this room
      step(idFor('drop', elsewhere.id)), // not carried
      step(idFor('examine', elsewhere.id)), // not visible
    ];
    const lines = [RESET, ...probes, step(idForStep(walkthrough[0])), CLOSE];
    const { code, stderr, responses } = await runBridgeSession(lines);

    assert.equal(stderr, '', `bridge wrote to stderr:\n${stderr}`);
    assert.equal(code, 0);

    const initial = responses[0].state;
    for (let i = 0; i < probes.length; i += 1) {
      assert.deepEqual(
        responses[i + 1].state,
        initial,
        `refused action ${JSON.stringify(probes[i])} consumed state`,
      );
    }
    // Including the move counter: an in-fiction refusal costs nothing.
    assert.equal(responses[probes.length].state.moves_taken, 0);
    assert.equal(responses.at(-1).state.moves_taken, 1);
  });

  it('keeps reporting terminated after the escape (the flag latches)', { timeout: 30000 }, async () => {
    const lines = [
      RESET,
      ...walkthrough.map((s) => step(idForStep(s))),
      step(idFor('look', null)),
      step(idFor('inventory', null)),
      CLOSE,
    ];
    const { code, responses } = await runBridgeSession(lines);

    assert.equal(code, 0);
    for (const resp of responses.slice(-2)) {
      assert.equal(resp.terminated, true);
      assert.equal(resp.state.escaped, true);
    }
  });
});

describe('bridge determinism', () => {
  it('replays byte-identically across two separate processes', { timeout: 30000 }, async () => {
    const lines = [RESET, ...walkthrough.map((s) => step(idForStep(s))), CLOSE];
    const [a, b] = await Promise.all([runBridgeSession(lines), runBridgeSession(lines)]);

    assert.equal(a.stdout, b.stdout);
    assert.equal(a.code, 0);
    assert.equal(b.code, 0);
  });

  it('reset mid-session returns to the pristine state', { timeout: 30000 }, async () => {
    const half = walkthrough.slice(0, 5).map((s) => step(idForStep(s)));
    const lines = [RESET, ...half, RESET, CLOSE];
    const { code, responses } = await runBridgeSession(lines);

    assert.equal(code, 0);
    assert.deepEqual(responses.at(-1), responses[0]);
    assert.deepEqual(responses.at(-1).state, getState(createGame(content)));
  });
});

describe('bridge robustness', () => {
  it('exits cleanly on close and answers nothing after it', { timeout: 30000 }, async () => {
    const lines = [RESET, CLOSE, step(idFor('look', null))];
    const { code, stderr, responses } = await runBridgeSession(lines);

    assert.equal(code, 0);
    assert.equal(stderr, '');
    assert.equal(responses.length, 1); // the reset only
    assert.deepEqual(Object.keys(responses[0]), ['state']);
  });

  it('exits on close while the parent still holds stdin open', { timeout: 30000 }, async () => {
    // The adapter's close() sends {"command":"close"} and then does a BLOCKING,
    // un-timed read, taking EOF as the answer — so the process must really end,
    // and every queued response must still have flushed first.
    const lines = [RESET, ...walkthrough.map((s) => step(idForStep(s))), CLOSE];
    const { code, stdout, stderr } = await runBridgeSessionStdinOpen(lines);

    assert.equal(code, 0);
    assert.equal(stderr, '');

    const responses = stdout
      .split('\n')
      .filter((l) => l.trim() !== '')
      .map((l) => JSON.parse(l));
    assert.equal(responses.length, 1 + walkthrough.length, 'a queued response was truncated');
    assert.equal(responses.at(-1).state.escaped, true);
  });

  it('skips blank and malformed lines without crashing or answering', { timeout: 30000 }, async () => {
    // Written by hand: these are deliberately not valid JSON documents.
    const raw = ['', '   ', 'not json at all', '{"command": "reset"', JSON.stringify(RESET)];
    const child = spawn(process.execPath, [BRIDGE], { stdio: ['pipe', 'pipe', 'pipe'] });
    const result = await new Promise((resolve, reject) => {
      let stdout = '';
      let stderr = '';
      const timer = setTimeout(() => {
        child.kill('SIGKILL');
        reject(new Error('bridge did not exit'));
      }, 20000);
      child.stdout.setEncoding('utf8');
      child.stderr.setEncoding('utf8');
      child.stdout.on('data', (c) => {
        stdout += c;
      });
      child.stderr.on('data', (c) => {
        stderr += c;
      });
      child.on('close', (code) => {
        clearTimeout(timer);
        resolve({ code, stdout, stderr });
      });
      child.stdin.end(`${raw.join('\n')}\n`);
    });

    assert.equal(result.code, 0);
    const lines = result.stdout.split('\n').filter((l) => l.trim() !== '');
    assert.equal(lines.length, 1, `expected only the reset response:\n${result.stdout}`);
    assert.deepEqual(JSON.parse(lines[0]).state, getState(createGame(content)));
    // Garbage is reported off the protocol channel, never on it.
    assert.match(result.stderr, /unparseable/);
  });

  it('answers an unknown command and keeps going', { timeout: 30000 }, async () => {
    const lines = [{ command: 'bogus' }, RESET, CLOSE];
    const { code, responses } = await runBridgeSession(lines);

    assert.equal(code, 0);
    assert.deepEqual(responses[0], { error: 'Unknown command: bogus' });
    assert.deepEqual(Object.keys(responses[1]), ['state']);
  });

  it('answers a step that arrives before any reset', { timeout: 30000 }, async () => {
    const lines = [step(idFor('look', null)), CLOSE];
    const { code, responses } = await runBridgeSession(lines);

    assert.equal(code, 0);
    assert.equal(responses.length, 1);
    assert.equal(responses[0].state.moves_taken, 1);
    assert.equal(responses[0].state.current_room, createGame(content).startRoom);
  });

  it('dumps the action table for the integration config with --actions', { timeout: 30000 }, async () => {
    const out = await new Promise((resolve, reject) => {
      const child = spawn(process.execPath, [BRIDGE, '--actions'], {
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      let stdout = '';
      child.stdout.setEncoding('utf8');
      child.stdout.on('data', (c) => {
        stdout += c;
      });
      child.on('error', reject);
      child.on('close', (code) => resolve({ code, stdout }));
    });

    assert.equal(out.code, 0);
    assert.deepEqual(JSON.parse(out.stdout), [...actions]);
  });
});

describe('handleCommand (in process)', () => {
  it('never dispatches an unknown id to the engine', () => {
    const session = { content, actions, game: createGame(content) };
    const before = getState(session.game);
    const { response, close } = handleCommand({ command: 'step', action_id: 1e9 }, session);

    assert.equal(close, false);
    assert.deepEqual(response.state, before);
    assert.equal(response.terminated, false);
    assert.equal(response.truncated, false);
    assert.deepEqual(response.info, { message: '' });
  });

  it('replaces the game on reset but never rebuilds the action table', () => {
    const session = { content, actions, game: createGame(content) };
    handleCommand({ command: 'step', action_id: idFor('look', null) }, session);
    const first = session.game;

    handleCommand(RESET, session);
    assert.notEqual(session.game, first);
    assert.equal(session.actions, actions);
    assert.equal(getState(session.game).moves_taken, 0);
  });

  it('signals close with no response line', () => {
    const session = { content, actions, game: createGame(content) };
    assert.deepEqual(handleCommand(CLOSE, session), { response: null, close: true });
  });
});

describe('bridge narration (info.message)', () => {
  // Regression guard for a wire-only defect found 2026-07-26 by the LLM-tier
  // pre-flight audit: `handleCommand` called `executeCommand(...).state` and
  // discarded `.message`, so the engine's room descriptions, examine text and
  // authored success/refusal lines never crossed the wire. `src/cli.js` prints
  // them, so the human front end looked fine and the in-process suite was green
  // — a black-box client played a text adventure with no text.
  //
  // These assert the CHANNEL, not the prose. Wording lives in the CSVs and is
  // free to change; what must not change is that it arrives.

  it('carries the room description when you move', () => {
    const content = loadContent(CONTENT_DIR);
    const actions = buildActionTable(content);
    const session = { content, actions, game: createGame(content) };
    const north = actions.findIndex((a) => a.verb === 'go' && a.arg === 'north');

    const { response } = handleCommand({ command: 'step', action_id: north }, session);
    assert.ok(
      response.info.message.length > 20,
      'a successful move should narrate the room it arrived in',
    );
    assert.equal(
      response.info.message.includes(content.rooms.get(response.state.current_room).name),
      true,
      'the narration should name the room the state says we are in',
    );
  });

  it('carries an object description when you examine it', () => {
    const content = loadContent(CONTENT_DIR);
    const actions = buildActionTable(content);
    const session = { content, actions, game: createGame(content) };
    // Any object that starts in the opening room is examinable from the off.
    const start = createGame(content).startRoom;
    const here = [...content.objects.values()].find((o) => o.startRoom === start);
    const idx = actions.findIndex((a) => a.verb === 'examine' && a.arg === here.id);

    const { response } = handleCommand({ command: 'step', action_id: idx }, session);
    assert.equal(
      response.info.message,
      here.description,
      'examine should return the CSV description verbatim — this is where the hints live',
    );
  });

  it('carries the authored refusal text when a use is gated', () => {
    const content = loadContent(CONTENT_DIR);
    const actions = buildActionTable(content);
    const session = { content, actions, game: createGame(content) };
    // A gated object, used without its prerequisite and without holding it.
    const gated = [...content.objects.values()].find((o) => o.useVerb && o.useFailText);
    const idx = actions.findIndex((a) => a.verb === 'use' && a.arg === gated.id);

    const { response } = handleCommand({ command: 'step', action_id: idx }, session);
    assert.ok(
      response.info.message.length > 0,
      'a refused use should still say why — a silent refusal teaches nothing',
    );
  });
});

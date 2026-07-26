/**
 * T-004 — the engine's game state + `executeCommand()` rules.
 *
 * This is the EXECUTED counterpart to `content.test.js`: where that file walks
 * `content/walkthrough.json` against the constraints the CSV columns declare,
 * this one runs the same fixture through the real engine and asserts it reaches
 * `escaped: true`.
 *
 * Scope boundary: engine only. No free-text CLI parsing (T-005) and no
 * JSON-lines / action_id protocol (T-006) is exercised here — though the
 * wire-shape and determinism guards below pin the contract T-006 builds on.
 *
 * No room, object or flag id is hardcoded in the walkthrough test: ids come
 * from the loaded CSVs and from `game.startRoom` / `game.escapeRoom`. The small
 * fixture tests do name fixture ids, which is what `test/fixtures/valid/` is
 * for. Fixture CSV pairs live in `test/fixtures/<case>/{rooms,objects}.csv`;
 * keep that tree `.csv`-only, since `node --test` executes every `.js` under
 * `test/` as a test file — one-off content is built inline with parseContent().
 */

import { readFileSync } from 'node:fs';
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import {
  CONTENT_DIR,
  ContentError,
  createGame,
  executeCommand,
  getState,
  loadContent,
  parseContent,
  resolveObject,
} from '../src/engine.js';

const fixture = (name) => new URL(`fixtures/${name}/`, import.meta.url);

const ROOMS_HEADER =
  'room_id,name,description,exit_north,exit_south,exit_east,exit_west,entry_requires_flag,' +
  'entry_fail_text';
const OBJECTS_HEADER =
  'object_id,name,start_room,description,takeable,take_sets_flag,use_verb,' +
  'use_requires_flag,use_requires_room,use_sets_flag,use_consumes,use_success_text,use_fail_text';

const csv = (header, rows) => [header, ...rows].join('\n') + '\n';

/** A fresh game over the shared 3-room valid fixture. */
const validGame = () => createGame(loadContent(fixture('valid')));

const STATE_KEYS = [
  'current_room',
  'escaped',
  'flags',
  'inventory',
  'moves_taken',
  // Added 2026-07-26 with the PRD's state shape — the player-facing name of
  // current_room. This list is deliberately exact: a key appearing or vanishing
  // on the wire is a contract change, and it should have to be written down here
  // before it ships.
  'room_name',
  'rooms_visited',
];

describe('createGame', () => {
  it('derives the start and escape rooms from rooms.csv file order', () => {
    const content = loadContent(fixture('valid'));
    const ids = [...content.rooms.keys()];
    const game = createGame(content);
    assert.equal(game.startRoom, ids[0]);
    assert.equal(game.escapeRoom, ids[ids.length - 1]);
    assert.equal(game.currentRoom, game.startRoom);
  });

  it('accepts explicit start/escape overrides and rejects unknown rooms', () => {
    const content = loadContent(fixture('valid'));
    const game = createGame(content, { startRoom: 'R02', escapeRoom: 'R02' });
    assert.equal(game.currentRoom, 'R02');
    assert.equal(game.escapeRoom, 'R02');
    assert.throws(() => createGame(content, { startRoom: 'R99' }), ContentError);
    assert.throws(() => createGame(content, { escapeRoom: 'R99' }), ContentError);
  });

  it('opens with the PRD wire shape: every flag false, 1 room visited, 0 moves', () => {
    const content = loadContent(fixture('valid'));
    const state = getState(createGame(content));

    assert.deepEqual(Object.keys(state).sort(), STATE_KEYS);
    assert.deepEqual(Object.keys(state.flags).sort(), [...content.flags].sort());
    assert.ok(Object.values(state.flags).every((v) => v === false));
    assert.equal(state.moves_taken, 0);
    assert.equal(state.rooms_visited, 1);
    assert.equal(state.escaped, false);
  });

  it('seeds inventory from start_room = INV', () => {
    // The fixture's lantern starts held; the brass key starts in a room.
    const state = getState(validGame());
    assert.deepEqual(state.inventory, ['lantern']);
  });

  it('returns snapshots that are copies, not views into the game', () => {
    const game = validGame();
    const first = getState(game);
    first.inventory.push('bogus');
    first.flags.lantern_lit = true;
    first.current_room = 'R99';

    const second = getState(game);
    assert.deepEqual(second.inventory, ['lantern']);
    assert.equal(second.flags.lantern_lit, false);
    assert.equal(second.current_room, game.startRoom);
  });
});

describe('executeCommand — guards and refusals', () => {
  it('throws a TypeError when handed something that is not a game', () => {
    assert.throws(() => executeCommand(null, 'look'), TypeError);
    assert.throws(() => executeCommand({}, 'look'), TypeError);
  });

  it('refuses an unknown verb without touching state', () => {
    const game = validGame();
    const before = getState(game);
    const res = executeCommand(game, 'xyzzy', 'lantern');
    assert.equal(res.ok, false);
    assert.deepEqual(res.state, before);
  });

  it('refuses an unknown object without touching state', () => {
    const game = validGame();
    const before = getState(game);
    for (const verb of ['take', 'drop', 'examine', 'use']) {
      const res = executeCommand(game, verb, 'no such thing');
      assert.equal(res.ok, false, `${verb} of an unknown object must be refused`);
      assert.deepEqual(res.state, before, `${verb} refusal must change nothing`);
    }
  });

  it('counts a move only on success', () => {
    const game = validGame();
    assert.equal(executeCommand(game, 'look').state.moves_taken, 1);
    assert.equal(executeCommand(game, 'inventory').state.moves_taken, 2);
    assert.equal(executeCommand(game, 'inv').state.moves_taken, 3);
    assert.equal(executeCommand(game, 'nonsense').state.moves_taken, 3);
    assert.equal(executeCommand(game, 'go', 'up').state.moves_taken, 3);
  });

  it('matches objects by id or display name, case-insensitively', () => {
    const game = validGame();
    const byId = resolveObject(game, 'key_brass');
    assert.equal(resolveObject(game, 'KEY_BRASS'), byId);
    assert.equal(resolveObject(game, 'Brass Key'), byId);
    assert.equal(resolveObject(game, 'nope'), null);
    assert.equal(resolveObject(game, ''), null);
  });
});

describe('executeCommand — movement and locked-room entry', () => {
  it('refuses a direction with no exit', () => {
    const game = validGame();
    const before = getState(game);
    const res = executeCommand(game, 'go', 'south'); // start room has north only
    assert.equal(res.ok, false);
    assert.deepEqual(res.state, before);
  });

  it('refuses entry to a flag-gated room until the flag is set, then allows it', () => {
    const game = validGame();
    assert.equal(getState(game).current_room, game.startRoom);

    // Start -> corridor is ungated.
    assert.equal(executeCommand(game, 'go', 'north').ok, true);
    const atCorridor = getState(game);
    assert.equal(atCorridor.rooms_visited, 2);

    // Corridor -> vault is gated on has_brass_key, which we do not have.
    const refused = executeCommand(game, 'go', 'east');
    assert.equal(refused.ok, false);
    assert.equal(refused.state.current_room, atCorridor.current_room);
    assert.equal(refused.state.moves_taken, atCorridor.moves_taken);
    assert.equal(refused.state.rooms_visited, atCorridor.rooms_visited);
    assert.equal(refused.state.escaped, false);

    // Fetch the key (its take_sets_flag opens the gate), then come back.
    assert.equal(executeCommand(game, 'go', 'south').ok, true);
    const taken = executeCommand(game, 'take', 'key_brass');
    assert.equal(taken.ok, true);
    assert.equal(taken.state.flags.has_brass_key, true);
    assert.equal(executeCommand(game, 'go', 'north').ok, true);

    const entered = executeCommand(game, 'go', 'east');
    assert.equal(entered.ok, true);
    assert.equal(entered.state.current_room, game.escapeRoom);
    assert.equal(entered.state.rooms_visited, 3);
    assert.equal(entered.state.escaped, true);
  });

  it('latches escaped once set', () => {
    const game = validGame();
    for (const [verb, arg] of [
      ['go', 'north'],
      ['go', 'south'],
      ['take', 'key_brass'],
      ['go', 'north'],
      ['go', 'e'], // direction shorthand
    ]) {
      assert.equal(executeCommand(game, verb, arg).ok, true, `${verb} ${arg}`);
    }
    assert.equal(getState(game).escaped, true);
    const back = executeCommand(game, 'go', 'west');
    assert.equal(back.ok, true);
    assert.notEqual(back.state.current_room, game.escapeRoom);
    assert.equal(back.state.escaped, true);
  });
});

describe('executeCommand — use prerequisites', () => {
  it('refuses use until the required flag is set, with the authored fail text', () => {
    const content = loadContent(fixture('valid'));
    const game = createGame(content);
    const lantern = content.objects.get('lantern');
    const before = getState(game);

    const refused = executeCommand(game, 'use', 'lantern');
    assert.equal(refused.ok, false);
    assert.equal(refused.message, lantern.useFailText);
    assert.equal(refused.state.flags.lantern_lit, false);
    assert.ok(refused.state.inventory.includes('lantern'), 'a failed use keeps the item');
    assert.deepEqual(refused.state, before, 'a failed use consumes no state');

    assert.equal(executeCommand(game, 'take', 'key_brass').ok, true);

    const ok = executeCommand(game, 'use', 'lantern');
    assert.equal(ok.ok, true);
    assert.equal(ok.message, lantern.useSuccessText);
    assert.equal(ok.state.flags.lantern_lit, true);
    assert.ok(ok.state.inventory.includes('lantern'), 'use_consumes=false keeps the item');

    // Re-using a non-consuming object is allowed and idempotent.
    const again = executeCommand(game, 'use', 'lantern');
    assert.equal(again.ok, true);
    assert.equal(again.state.flags.lantern_lit, true);
  });

  it('refuses use of an object that is not held', () => {
    const game = validGame();
    const before = getState(game);
    const res = executeCommand(game, 'use', 'key_brass'); // still lying in the room
    assert.equal(res.ok, false);
    assert.deepEqual(res.state, before);
  });

  it('refuses use of an object with no use_verb', () => {
    const game = validGame();
    assert.equal(executeCommand(game, 'take', 'key_brass').ok, true);
    const before = getState(game);
    const res = executeCommand(game, 'use', 'key_brass'); // use_verb is empty
    assert.equal(res.ok, false);
    assert.deepEqual(res.state, before);
  });
});

describe('executeCommand — use_consumes', () => {
  // The shared fixture has no consuming object, so build one inline.
  const consumingContent = () =>
    parseContent(
      csv(ROOMS_HEADER, [
        'R01,Cell,A damp cell.,R02,,,,,',
        'R02,Vault,The vault stands open.,,R01,,,door_open,"The vault door is shut fast."',
      ]),
      csv(OBJECTS_HEADER, [
        'key_fragile,fragile key,R01,A thin key of soft metal.,true,,unlock,,,door_open,true,' +
          '"It turns once and shears off in the lock. The door opens.",It will not fit.',
      ]),
    );

  it('destroys the item on a successful use and still sets its flag', () => {
    const content = consumingContent();
    const game = createGame(content);

    assert.equal(executeCommand(game, 'take', 'key_fragile').ok, true);
    assert.deepEqual(getState(game).inventory, ['key_fragile']);

    const used = executeCommand(game, 'use', 'key_fragile');
    assert.equal(used.ok, true);
    assert.equal(used.message, content.objects.get('key_fragile').useSuccessText);
    assert.deepEqual(used.state.inventory, [], 'a consumed object leaves the inventory');
    assert.equal(used.state.flags.door_open, true);
  });

  it('does not drop the consumed item into the room — it cannot be re-taken or re-used', () => {
    const game = createGame(consumingContent());
    assert.equal(executeCommand(game, 'take', 'key_fragile').ok, true);
    assert.equal(executeCommand(game, 'use', 'key_fragile').ok, true);

    assert.equal(executeCommand(game, 'take', 'key_fragile').ok, false);
    assert.equal(executeCommand(game, 'examine', 'key_fragile').ok, false);
    assert.equal(executeCommand(game, 'use', 'key_fragile').ok, false);
    assert.ok(!executeCommand(game, 'look').message.includes('fragile key'));

    // The flag it set survives the object's destruction, so the gate stays open.
    const entered = executeCommand(game, 'go', 'north');
    assert.equal(entered.ok, true);
    assert.equal(entered.state.escaped, true);
  });
});

describe('a locked door says what kind of lock it is', () => {
  // Added 2026-07-26. Every gated room used to share one string, so a player
  // learned only that they had failed. Content authors the hint now, and the
  // engine's generic `locked` line is a fallback validate() forbids reaching.

  it('answers a blocked move with the room\'s authored entry_fail_text', () => {
    const content = parseContent(
      csv(ROOMS_HEADER, [
        'R01,Cell,A damp cell.,R02,,,,,',
        'R02,Vault,The vault.,,R01,,,door_open,"The vault door wants a key."',
      ]),
      csv(OBJECTS_HEADER, [
        'key,key,R01,A key.,true,,unlock,,,door_open,false,It turns.,',
      ]),
    );
    const game = createGame(content);
    const refused = executeCommand(game, 'go', 'north');

    assert.equal(refused.ok, false);
    assert.equal(refused.message, 'The vault door wants a key.');
  });

  it('every gated room in the shipped content authors its own hint', () => {
    // Content-derived: a new locked door is covered the moment it is authored.
    const content = loadContent();
    const gated = [...content.rooms.values()].filter((r) => r.entryRequiresFlag !== null);
    assert.ok(gated.length > 0, 'the game should still have locked doors');
    for (const room of gated) {
      assert.ok(
        room.entryFailText && room.entryFailText.length > 20,
        `room ${room.id} is gated but says nothing useful when it refuses you`,
      );
    }
  });
});

describe('a puzzle resolves where it lives', () => {
  // Added 2026-07-26: `use` checked held/usable/flag and never location, so the
  // banded iron door could be unlocked from inside the cell two rooms away —
  // and the game narrated "the door swings open" at you where you stood.

  it('refuses a place-bound object used in the wrong room, and changes nothing', () => {
    const content = parseContent(
      csv(ROOMS_HEADER, [
        'R01,Cell,A damp cell.,R02,,,,,',
        'R02,Corridor,A corridor.,,R01,,,,',
      ]),
      csv(OBJECTS_HEADER, [
        'key,key,R01,A key.,true,,unlock,,R02,door_open,false,It turns.,',
      ]),
    );
    const game = createGame(content);
    executeCommand(game, 'take', 'key');
    const before = getState(game);

    const refused = executeCommand(game, 'use', 'key');
    assert.equal(refused.ok, false);
    assert.deepEqual(refused.state, before, 'a wrong-place refusal must cost nothing');

    assert.equal(executeCommand(game, 'go', 'north').ok, true);
    const granted = executeCommand(game, 'use', 'key');
    assert.equal(granted.ok, true, 'the same call must work in the right room');
    assert.equal(granted.state.flags.door_open, true);
  });
});

describe('an object\'s authored use_verb is a real command', () => {
  // `use_verb` used to be decoration: the engine only null-checked the column,
  // so the game declared a verb per object, never accepted it, and never
  // printed it. `read ledger` answered "I don't understand that."

  it('accepts the verb the object declares', () => {
    const content = loadContent();
    const game = createGame(content);
    const ledger = [...content.objects.values()].find((o) => o.useVerb === 'read');
    assert.ok(ledger, 'the shipped content should still declare a `read` object');

    game.inventory.add(ledger.id);
    const res = executeCommand(game, 'read', ledger.id);
    // Refused for a missing prerequisite is fine — what matters is that the
    // verb REACHED the object rather than dying in the parser.
    assert.ok(
      !/^I don't understand/.test(res.message),
      `the parser swallowed an authored verb: ${res.message}`,
    );
  });

  it('refuses a verb that belongs to a different object', () => {
    const content = loadContent();
    const game = createGame(content);
    const lantern = [...content.objects.values()].find((o) => o.useVerb === 'light');
    assert.ok(lantern);

    game.inventory.add(lantern.id);
    const res = executeCommand(game, 'read', lantern.id);
    assert.equal(res.ok, false);
    assert.equal(res.state.flags[lantern.useSetsFlag], false, 'it must not fire the effect');
  });

  it('still refuses a verb no object declares, and names the vocabulary', () => {
    const game = validGame();
    const res = executeCommand(game, 'xyzzy', 'lantern');
    assert.equal(res.ok, false);
    assert.match(res.message, /use/, 'a dead end should point at the real verbs');
  });
});

describe('executeCommand — take / drop / examine / look / inventory', () => {
  it('refuses take of a non-takeable object and of one in another room', () => {
    const content = parseContent(
      csv(ROOMS_HEADER, [
        'R01,Cell,A damp cell.,R02,,,,,',
        'R02,Corridor,A long corridor.,,R01,,,,',
      ]),
      csv(OBJECTS_HEADER, [
        'slab,stone slab,R01,A slab bolted to the wall.,false,,,,,,false,,',
        'coin,copper coin,R02,A worn copper coin.,true,found_coin,,,,,false,,',
      ]),
    );
    const game = createGame(content);
    const before = getState(game);

    const bolted = executeCommand(game, 'take', 'slab');
    assert.equal(bolted.ok, false);
    assert.deepEqual(bolted.state, before);

    const elsewhere = executeCommand(game, 'take', 'coin'); // it is in R02
    assert.equal(elsewhere.ok, false);
    assert.deepEqual(elsewhere.state, before);
    assert.equal(elsewhere.state.flags.found_coin, false);
  });

  it('refuses take of something already held', () => {
    const game = validGame(); // the lantern starts in inventory
    const before = getState(game);
    const res = executeCommand(game, 'take', 'lantern');
    assert.equal(res.ok, false);
    assert.deepEqual(res.state, before);
  });

  it('drops into the current room, keeps the take flag, and allows a re-take', () => {
    const game = validGame();
    assert.equal(executeCommand(game, 'take', 'key_brass').ok, true);
    assert.equal(executeCommand(game, 'go', 'north').ok, true);

    const dropped = executeCommand(game, 'drop', 'key_brass');
    assert.equal(dropped.ok, true);
    assert.deepEqual(dropped.state.inventory, ['lantern']);
    assert.equal(dropped.state.flags.has_brass_key, true, 'flags are monotonic');

    assert.ok(executeCommand(game, 'look').message.includes('brass key'));
    const retaken = executeCommand(game, 'take', 'key_brass');
    assert.equal(retaken.ok, true);
    assert.deepEqual(retaken.state.inventory, ['key_brass', 'lantern']);

    // Dropping it again works; dropping it a third time (no longer held) is refused.
    assert.equal(executeCommand(game, 'drop', 'key_brass').ok, true);
    const notHeld = executeCommand(game, 'drop', 'key_brass');
    assert.equal(notHeld.ok, false);
    assert.equal(notHeld.state.moves_taken, retaken.state.moves_taken + 1);
  });

  it('examines a held object and one lying in the room, verbatim from the CSV', () => {
    const content = loadContent(fixture('valid'));
    const game = createGame(content);

    const held = executeCommand(game, 'examine', 'lantern');
    assert.equal(held.ok, true);
    assert.equal(held.message, content.objects.get('lantern').description);

    const onFloor = executeCommand(game, 'examine', 'brass key');
    assert.equal(onFloor.ok, true);
    assert.equal(onFloor.message, content.objects.get('key_brass').description);

    // Not visible: in another room.
    assert.equal(executeCommand(game, 'go', 'north').ok, true);
    assert.equal(executeCommand(game, 'examine', 'key_brass').ok, false);
  });

  it('look and inventory report the world without changing it', () => {
    const content = loadContent(fixture('valid'));
    const game = createGame(content);
    const room = content.rooms.get(game.startRoom);

    const looked = executeCommand(game, 'look');
    assert.equal(looked.ok, true);
    assert.ok(looked.message.includes(room.name));
    assert.ok(looked.message.includes(room.description));
    assert.ok(looked.message.includes('north'), 'look lists the exits that exist');
    assert.ok(looked.message.includes('brass key'), 'look lists objects in the room');
    assert.equal(looked.state.current_room, game.startRoom);
    assert.equal(looked.state.rooms_visited, 1);

    const inv = executeCommand(game, 'inventory');
    assert.equal(inv.ok, true);
    assert.ok(inv.message.includes('lantern'));

    const { moves_taken: _moves, ...restBefore } = looked.state;
    const { moves_taken: _moves2, ...restAfter } = inv.state;
    assert.deepEqual(restAfter, restBefore, 'look/inventory change nothing but the move count');
  });
});

describe('walkthrough fixture through executeCommand', () => {
  const content = loadContent();
  const walkthrough = JSON.parse(
    readFileSync(new URL('walkthrough.json', CONTENT_DIR), 'utf8'),
  );

  /** Run the authored walkthrough end to end, asserting every step succeeds. */
  function runWalkthrough() {
    const game = createGame(content);
    walkthrough.forEach((step, i) => {
      const room = getState(game).current_room;
      const res = executeCommand(game, step.verb, step.object);
      assert.equal(
        res.ok,
        true,
        `step ${i} (${step.verb} ${step.object}) in ${room} was refused: ${res.message}`,
      );
    });
    return game;
  }

  it('reaches escaped: true in the escape room', () => {
    const game = runWalkthrough();
    const state = getState(game);
    assert.equal(state.escaped, true);
    assert.equal(state.current_room, game.escapeRoom);
    assert.equal(state.moves_taken, walkthrough.length, 'every step must have counted');
  });

  it('leaves every use_consumes object it used out of the final inventory', () => {
    const state = getState(runWalkthrough());
    const consumed = walkthrough
      .filter((s) => s.verb === 'use' && content.objects.get(s.object)?.useConsumes)
      .map((s) => s.object);
    assert.ok(consumed.length > 0, 'the walkthrough must exercise use_consumes');
    for (const id of consumed) {
      assert.ok(!state.inventory.includes(id), `${id} was consumed and must not be held`);
    }
  });

  it('sets every flag the authored content defines', () => {
    const state = getState(runWalkthrough());
    for (const flag of content.flags) {
      assert.equal(state.flags[flag], true, `flag ${flag} should be set by the walkthrough`);
    }
  });

  it('is deterministic and JSON-serializable (no hidden randomness)', () => {
    const first = getState(runWalkthrough());
    const second = getState(runWalkthrough());
    assert.deepEqual(second, first);
    assert.deepEqual(JSON.parse(JSON.stringify(first)), first);
  });
});

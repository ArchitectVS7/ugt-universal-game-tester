/**
 * T-002 — CSV loader + validation.
 *
 * Fixture CSV pairs live in `test/fixtures/<case>/{rooms,objects}.csv`; keep
 * that tree `.csv`-only, since `node --test` executes every `.js` under
 * `test/` as a test file.
 */

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { ContentError, loadContent, parseContent } from '../src/engine.js';

const fixture = (name) => new URL(`fixtures/${name}/`, import.meta.url);

const ROOMS_HEADER =
  'room_id,name,description,exit_north,exit_south,exit_east,exit_west,entry_requires_flag,' +
  'entry_fail_text';
const OBJECTS_HEADER =
  'object_id,name,start_room,description,takeable,take_sets_flag,use_verb,' +
  'use_requires_flag,use_requires_room,use_sets_flag,use_consumes,use_success_text,use_fail_text';

/** Build rooms.csv text from data rows (header supplied unless overridden). */
const roomsCsv = (rows, header = ROOMS_HEADER) => [header, ...rows].join('\n') + '\n';
const objectsCsv = (rows, header = OBJECTS_HEADER) => [header, ...rows].join('\n') + '\n';

/** A minimal valid pair used as the base for inline mutation tests. */
const BASE_ROOM = 'R01,Cell,A damp cell.,,,,,,';
const BASE_OBJECT = 'key_brass,brass key,R01,A small brass key.,true,has_brass_key,,,,,false,,';

/** Assert `fn` throws a ContentError whose message matches every pattern. */
function assertContentError(fn, patterns) {
  let thrown;
  assert.throws(fn, (err) => {
    thrown = err;
    assert.ok(err instanceof ContentError, `expected ContentError, got ${err?.name}: ${err?.message}`);
    return true;
  });
  for (const pattern of patterns) {
    assert.match(thrown.message, pattern);
  }
  return thrown;
}

describe('loadContent — valid fixture pair', () => {
  it('loads clean', () => {
    const content = loadContent(fixture('valid'));
    assert.equal(content.rooms.size, 3);
    assert.equal(content.objects.size, 2);
  });

  it('maps exits and entry gates', () => {
    const { rooms } = loadContent(fixture('valid'));
    const r01 = rooms.get('R01');
    assert.equal(r01.exits.north, 'R02');
    assert.equal(r01.exits.south, null);
    assert.equal(r01.exits.east, null);
    assert.equal(r01.exits.west, null);
    assert.equal(r01.entryRequiresFlag, null);

    const r02 = rooms.get('R02');
    assert.equal(r02.exits.south, 'R01');
    assert.equal(r02.exits.east, 'R03');

    assert.equal(rooms.get('R03').entryRequiresFlag, 'has_brass_key');
  });

  it('keeps quoted fields containing commas verbatim', () => {
    const content = loadContent(fixture('valid'));
    assert.equal(content.rooms.get('R01').description, 'A damp cell, barely lit.');
    assert.equal(
      content.objects.get('lantern').useSuccessText,
      'The wick catches, and light spills out.',
    );
  });

  it('coerces typed columns', () => {
    const { objects } = loadContent(fixture('valid'));
    const key = objects.get('key_brass');
    assert.equal(key.takeable, true);
    assert.equal(key.takeSetsFlag, 'has_brass_key');
    assert.equal(key.useVerb, null);
    assert.equal(key.useRequiresFlag, null);
    assert.equal(key.useSetsFlag, null);
    assert.equal(key.useConsumes, false);
    assert.equal(key.useSuccessText, '');

    const lantern = objects.get('lantern');
    assert.equal(lantern.startRoom, 'INV');
    assert.equal(lantern.useVerb, 'light');
    assert.equal(lantern.useRequiresFlag, 'has_brass_key');
    assert.equal(lantern.useSetsFlag, 'lantern_lit');
    assert.equal(lantern.useConsumes, false);
    assert.equal(lantern.useFailText, 'Nothing happens.');
  });

  it('preserves CSV file order and collects the flag universe', () => {
    const content = loadContent(fixture('valid'));
    // Order is load-bearing: PRD's deterministic action_id assignment walks
    // objects.csv in file order (T-006).
    assert.deepEqual([...content.rooms.keys()], ['R01', 'R02', 'R03']);
    assert.deepEqual([...content.objects.keys()], ['key_brass', 'lantern']);
    assert.deepEqual(content.flags, new Set(['has_brass_key', 'lantern_lit']));
  });
});

describe('loadContent — invalid fixtures', () => {
  it('rejects a dangling exit', () => {
    assertContentError(() => loadContent(fixture('dangling-exit')), [
      /R02/,
      /exit_east/,
      /R09/,
    ]);
  });

  it('rejects an unreachable entry_requires_flag', () => {
    assertContentError(() => loadContent(fixture('unreachable-flag')), [
      /R03/,
      /has_silver_key/,
      /unreachable/i,
    ]);
  });

  it('rejects a duplicate room_id', () => {
    assertContentError(() => loadContent(fixture('duplicate-room-id')), [
      /duplicate/i,
      /room_id/,
      /R01/,
    ]);
  });

  it('rejects a duplicate object_id', () => {
    assertContentError(() => loadContent(fixture('duplicate-object-id')), [
      /duplicate/i,
      /object_id/,
      /lantern/,
    ]);
  });

  it('reports a missing content directory as a ContentError', () => {
    assertContentError(() => loadContent(fixture('no-such-fixture')), [/rooms\.csv/]);
  });
});

describe('parseContent — malformed input', () => {
  it('rejects a header with a renamed column', () => {
    const badHeader = ROOMS_HEADER.replace('entry_requires_flag', 'entry_flag');
    assertContentError(
      () => parseContent(roomsCsv([BASE_ROOM], badHeader), objectsCsv([BASE_OBJECT])),
      [/rooms\.csv/, /entry_requires_flag/, /entry_flag/],
    );
  });

  it('rejects a row with the wrong field count', () => {
    assertContentError(
      () => parseContent(roomsCsv([BASE_ROOM]), objectsCsv(['key_brass,brass key,R01'])),
      [/objects\.csv line 2/, /expected 13 fields/, /found 3/],
    );
  });

  it('rejects a non-boolean takeable value', () => {
    const row = BASE_OBJECT.replace(',true,has_brass_key', ',yes,has_brass_key');
    assertContentError(() => parseContent(roomsCsv([BASE_ROOM]), objectsCsv([row])), [
      /objects\.csv line 2/,
      /takeable/,
      /"yes"/,
    ]);
  });

  it('rejects an unterminated quoted field', () => {
    const row = 'R01,Cell,"A damp cell,,,,,,';
    assertContentError(() => parseContent(roomsCsv([row]), objectsCsv([BASE_OBJECT])), [
      /rooms\.csv line 2/,
      /unterminated/i,
    ]);
  });

  it('rejects an unreachable use_requires_flag', () => {
    const row =
      'lantern,lantern,R01,An oil lantern.,true,,light,has_silver_key,,lantern_lit,false,Lit.,Nothing.';
    assertContentError(
      () => parseContent(roomsCsv([BASE_ROOM]), objectsCsv([BASE_OBJECT, row])),
      [/lantern/, /has_silver_key/, /use_requires_flag/],
    );
  });

  // The playability rules, enforced as content rules (added 2026-07-26). A
  // locked door that cannot say what kind of lock it is leaves the player with
  // nowhere to go, and an LLM playtester demonstrated exactly that: it stalled
  // 20 moves at a door whose only message was "the way is shut".

  it('rejects a gated room with no entry_fail_text', () => {
    const rooms = [
      'R01,Cell,A damp cell.,R02,,,,,',
      'R02,Vault,The vault.,,R01,,,has_brass_key,',
    ];
    assertContentError(
      () => parseContent(roomsCsv(rooms), objectsCsv([BASE_OBJECT])),
      [/R02/, /entry_fail_text/, /locked door/],
    );
  });

  it('rejects entry_fail_text on a room that is not gated — it could never be shown', () => {
    const rooms = [
      'R01,Cell,A damp cell.,R02,,,,,',
      'R02,Vault,The vault.,,R01,,,,"Shut fast."',
    ];
    assertContentError(
      () => parseContent(roomsCsv(rooms), objectsCsv([BASE_OBJECT])),
      [/R02/, /entry_fail_text/, /never be shown/],
    );
  });

  it('rejects a use_requires_room that names no such room', () => {
    const row =
      'lantern,lantern,R01,An oil lantern.,true,,light,,R99,lantern_lit,false,Lit.,Nothing.';
    assertContentError(
      () => parseContent(roomsCsv([BASE_ROOM]), objectsCsv([BASE_OBJECT, row])),
      [/lantern/, /R99/, /use_requires_room/],
    );
  });

  it('rejects use gating on an object with no use_verb — the gate is unreachable', () => {
    const row =
      'rock,rock,R01,A rock.,true,,,has_brass_key,,,false,,';
    assertContentError(
      () => parseContent(roomsCsv([BASE_ROOM]), objectsCsv([BASE_OBJECT, row])),
      [/rock/, /use_verb/],
    );
  });

  it('rejects an unknown start_room', () => {
    const row = BASE_OBJECT.replace(',R01,', ',R99,');
    assertContentError(() => parseContent(roomsCsv([BASE_ROOM]), objectsCsv([row])), [
      /key_brass/,
      /R99/,
      /start_room/,
    ]);
  });

  it('accepts INV as a start_room', () => {
    const row = BASE_OBJECT.replace(',R01,', ',INV,');
    const content = parseContent(roomsCsv([BASE_ROOM]), objectsCsv([row]));
    assert.equal(content.objects.get('key_brass').startRoom, 'INV');
  });

  it('rejects content with no rooms', () => {
    assertContentError(() => parseContent(roomsCsv([]), objectsCsv([])), [/no rooms/i]);
  });

  it('reports every violation in a single error', () => {
    const rooms = roomsCsv([
      'R01,Cell,A damp cell.,R09,,,,,',
      'R02,Vault,The vault.,,R01,,,never_set,"Shut fast."',
    ]);
    const err = assertContentError(() => parseContent(rooms, objectsCsv([BASE_OBJECT])), [
      /R09/,
      /never_set/,
    ]);
    assert.match(err.message, /2 errors/);
  });
});

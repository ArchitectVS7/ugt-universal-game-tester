/**
 * T-003 — the authored adventure content.
 *
 * This is a STATIC content-integrity check, not a rules implementation. It
 * loads the real `content/rooms.csv` + `content/objects.csv` through the T-002
 * loader and walks `content/walkthrough.json` against the constraints the CSV
 * columns literally declare (exit targets, `entry_requires_flag`,
 * `takeable`, `use_requires_flag`, `use_consumes`) — nothing more. No game
 * rule is invented or duplicated here, and no content is copied into `.js`:
 * every id, flag and room comes from the loaded CSVs.
 *
 * T-004 re-verifies this same `content/walkthrough.json` fixture by actually
 * running it through `executeCommand()`; that is the executed check. This one
 * exists so authoring drift in the CSVs can't silently break the fixture.
 */

import { readFileSync } from 'node:fs';
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { CONTENT_DIR, INVENTORY_START, loadContent } from '../src/engine.js';

const DIRECTIONS = ['north', 'south', 'east', 'west'];
const START_ROOM = 'R01';
const ESCAPE_ROOM = 'R10';

const content = loadContent();
const walkthrough = JSON.parse(
  readFileSync(new URL('walkthrough.json', CONTENT_DIR), 'utf8'),
);

describe('authored content', () => {
  it('loads with 0 validation errors', () => {
    // loadContent() throws an aggregated ContentError on any violation, so
    // reaching this line at module scope already means a clean load.
    assert.ok(content.rooms.size > 0);
    assert.ok(content.objects.size > 0);
  });

  it('defines exactly 10 rooms, R01..R10', () => {
    assert.equal(content.rooms.size, 10);
    const expected = Array.from({ length: 10 }, (_, i) => `R${String(i + 1).padStart(2, '0')}`);
    assert.deepEqual([...content.rooms.keys()].sort(), expected);
  });

  it('defines at most 12 objects', () => {
    assert.ok(
      content.objects.size <= 12,
      `expected <= 12 objects, found ${content.objects.size}`,
    );
  });

  it('gates the escape room behind a reachable flag', () => {
    const escape = content.rooms.get(ESCAPE_ROOM);
    assert.ok(escape, `${ESCAPE_ROOM} must exist`);
    assert.ok(
      escape.entryRequiresFlag !== null,
      `${ESCAPE_ROOM} must have an entry_requires_flag (the final puzzle's flag)`,
    );
    assert.ok(content.flags.has(escape.entryRequiresFlag));
  });

  it('keeps the action space within the PRD budget of 60', () => {
    // PRD § UGT hooks: 4 movement + look + inventory, then per object in file
    // order: take/drop (if takeable), examine, use (if use_verb).
    let actions = 6;
    for (const obj of content.objects.values()) {
      if (obj.takeable) actions += 2;
      actions += 1;
      if (obj.useVerb !== null) actions += 1;
    }
    assert.ok(actions <= 60, `action space is ${actions}, expected <= 60`);
  });
});

describe('walkthrough fixture', () => {
  it('is a flat array of {verb, object} steps', () => {
    assert.ok(Array.isArray(walkthrough), 'walkthrough.json must be a flat array');
    assert.ok(walkthrough.length > 0);
    walkthrough.forEach((step, i) => {
      assert.equal(
        typeof step,
        'object',
        `step ${i} must be an object`,
      );
      assert.deepEqual(
        Object.keys(step).sort(),
        ['object', 'verb'],
        `step ${i} must have exactly the keys verb and object`,
      );
      assert.equal(typeof step.verb, 'string', `step ${i}: verb must be a string`);
      assert.equal(typeof step.object, 'string', `step ${i}: object must be a string`);
      assert.ok(
        ['go', 'take', 'use'].includes(step.verb),
        `step ${i}: unknown verb ${JSON.stringify(step.verb)}`,
      );
      if (step.verb === 'go') {
        assert.ok(
          DIRECTIONS.includes(step.object),
          `step ${i}: go target ${JSON.stringify(step.object)} is not a direction`,
        );
      } else {
        assert.ok(
          content.objects.has(step.object),
          `step ${i}: unknown object_id ${JSON.stringify(step.object)}`,
        );
      }
    });
  });

  it('traces from the start room to the escape room, satisfying every gate', () => {
    let room = START_ROOM;
    const flags = new Set();
    const inventory = new Set();
    // Object location per the CSVs: a room_id, or INVENTORY_START to start held.
    const location = new Map();
    for (const obj of content.objects.values()) {
      if (obj.startRoom === INVENTORY_START) inventory.add(obj.id);
      else location.set(obj.id, obj.startRoom);
    }

    walkthrough.forEach((step, i) => {
      const at = `step ${i} (${step.verb} ${step.object}) in ${room}`;

      if (step.verb === 'go') {
        const target = content.rooms.get(room).exits[step.object];
        assert.ok(target !== null, `${at}: no exit ${step.object}`);
        const next = content.rooms.get(target);
        if (next.entryRequiresFlag !== null) {
          assert.ok(
            flags.has(next.entryRequiresFlag),
            `${at}: ${target} requires flag ${next.entryRequiresFlag}, not yet set`,
          );
        }
        room = target;
        return;
      }

      const obj = content.objects.get(step.object);

      if (step.verb === 'take') {
        assert.ok(obj.takeable, `${at}: ${obj.id} is not takeable`);
        assert.ok(!inventory.has(obj.id), `${at}: ${obj.id} is already held`);
        assert.equal(
          location.get(obj.id),
          room,
          `${at}: ${obj.id} is not in this room`,
        );
        location.delete(obj.id);
        inventory.add(obj.id);
        if (obj.takeSetsFlag !== null) flags.add(obj.takeSetsFlag);
        return;
      }

      // step.verb === 'use'
      assert.ok(inventory.has(obj.id), `${at}: ${obj.id} is not held`);
      assert.ok(obj.useVerb !== null, `${at}: ${obj.id} is not usable`);
      if (obj.useRequiresFlag !== null) {
        assert.ok(
          flags.has(obj.useRequiresFlag),
          `${at}: use requires flag ${obj.useRequiresFlag}, not yet set`,
        );
      }
      if (obj.useSetsFlag !== null) flags.add(obj.useSetsFlag);
      if (obj.useConsumes) inventory.delete(obj.id);
    });

    assert.equal(room, ESCAPE_ROOM, 'the walkthrough must end in the escape room');
  });
});

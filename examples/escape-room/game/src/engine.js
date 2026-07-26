/**
 * engine.js — the single source of game rules.
 *
 * Every rule (flag check, exit lock, puzzle effect, escape transition) lives
 * here and nowhere else. `src/cli.js` and `src/bridge.js` are translation
 * layers only: they turn human text / a numeric action_id into an
 * `executeCommand()` call and render whatever comes back. Neither front end
 * may re-implement or shortcut a rule.
 *
 * All room/object/puzzle content comes from `content/rooms.csv` and
 * `content/objects.csv` — no room or object data is hardcoded in this file.
 *
 * Layout: T-002's content loader (parseContent/loadContent) first, then T-004's
 * game state and command rules (createGame/getState/resolveObject/
 * executeCommand) below the marked divider, alongside the derived-from-content
 * helpers the front ends need (describeRoom/normalizeDirection for the CLI,
 * buildActionTable for the bridge).
 */

import { readFileSync } from 'node:fs';
import path from 'node:path';

/** Directory holding the authored CSV content, resolved relative to this module. */
export const CONTENT_DIR = new URL('../content/', import.meta.url);

/** Thrown for any malformed / invalid authored content (never for a runtime bug). */
export class ContentError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ContentError';
  }
}

/**
 * Column contracts from PRD.md § "Content format". These are *schema* (column
 * names), not content — no room, object or puzzle data lives in this file.
 */
const ROOM_COLUMNS = [
  'room_id',
  'name',
  'description',
  'exit_north',
  'exit_south',
  'exit_east',
  'exit_west',
  'entry_requires_flag',
  // Shown when the player tries to enter while `entry_requires_flag` is unset.
  // A locked door that only says "you can't" teaches nothing; this is where a
  // door says what KIND of obstacle it is, so the player has somewhere to go
  // next. Required on any gated room (validated below) and forbidden on an
  // ungated one, where it could never be shown.
  'entry_fail_text',
];

const OBJECT_COLUMNS = [
  'object_id',
  'name',
  'start_room',
  'description',
  'takeable',
  'take_sets_flag',
  'use_verb',
  'use_requires_flag',
  // Where the puzzle physically IS. Empty means "anywhere", which is right for
  // something you do to the object itself (lighting a lantern, reading a
  // ledger) and wrong for something you do to the world (a key belongs at its
  // door). Without it the engine happily let you unlock a door two rooms away
  // while narrating "the door swings open" at you in your cell.
  'use_requires_room',
  'use_sets_flag',
  'use_consumes',
  'use_success_text',
  'use_fail_text',
];

const DIRECTIONS = ['north', 'south', 'east', 'west'];

/** `start_room` sentinel meaning "starts in the player's inventory". */
export const INVENTORY_START = 'INV';

/**
 * Split one physical CSV line into fields.
 *
 * Unquoted fields are trimmed; double-quoted fields are taken verbatim, with
 * `""` unescaping to a literal `"`. Embedded newlines are not supported (an
 * unterminated quote is an authoring error, not a continuation).
 */
function parseCsvLine(line, label, lineNo) {
  const fields = [];
  let i = 0;

  for (;;) {
    let field;
    let ws = i;
    while (ws < line.length && (line[ws] === ' ' || line[ws] === '\t')) ws += 1;

    if (line[ws] === '"') {
      i = ws + 1;
      let buf = '';
      for (;;) {
        if (i >= line.length) {
          throw new ContentError(
            `${label} line ${lineNo}: unterminated quoted field (missing closing '"')`,
          );
        }
        const ch = line[i];
        if (ch === '"') {
          if (line[i + 1] === '"') {
            buf += '"';
            i += 2;
            continue;
          }
          i += 1;
          break;
        }
        buf += ch;
        i += 1;
      }
      while (i < line.length && (line[i] === ' ' || line[i] === '\t')) i += 1;
      if (i < line.length && line[i] !== ',') {
        throw new ContentError(
          `${label} line ${lineNo}: unexpected text after a closing quote (found ${JSON.stringify(line.slice(i))})`,
        );
      }
      field = buf;
    } else {
      const start = i;
      while (i < line.length && line[i] !== ',') i += 1;
      field = line.slice(start, i).trim();
    }

    fields.push(field);
    if (i >= line.length) break;
    i += 1; // consume the separating comma
    if (i >= line.length) {
      fields.push(''); // trailing comma => one more empty field
      break;
    }
  }

  return fields;
}

/**
 * Parse CSV text into a header plus line-numbered rows.
 * Blank lines are ignored; a BOM and CRLF endings are tolerated.
 */
function parseCsv(text, label) {
  const clean = text.replace(/^\uFEFF/, '');
  const lines = clean.split(/\r\n|\n|\r/);

  let header = null;
  const rows = [];

  for (let idx = 0; idx < lines.length; idx += 1) {
    const line = lines[idx];
    const lineNo = idx + 1;
    if (line.trim() === '') continue;
    const values = parseCsvLine(line, label, lineNo);
    if (header === null) {
      header = values;
      continue;
    }
    rows.push({ values, line: lineNo });
  }

  if (header === null) {
    throw new ContentError(`${label} is empty (expected a header row)`);
  }
  return { header, rows };
}

/** Verify a parsed header matches the schema exactly (same names, same order). */
function checkHeader(header, expected, label) {
  const missing = expected.filter((c) => !header.includes(c));
  const unexpected = header.filter((c) => !expected.includes(c));
  const sameOrder =
    header.length === expected.length && header.every((c, i) => c === expected[i]);
  if (sameOrder) return;

  const parts = [];
  if (missing.length) parts.push(`missing column(s): ${missing.join(', ')}`);
  if (unexpected.length) parts.push(`unexpected column(s): ${unexpected.join(', ')}`);
  if (!parts.length) parts.push('columns are out of order');
  throw new ContentError(
    `${label} header mismatch — ${parts.join('; ')}. ` +
      `Expected exactly: ${expected.join(',')} (found: ${header.join(',')})`,
  );
}

/** Empty string => null, for the optional id/flag/verb columns. */
function orNull(value) {
  return value === '' ? null : value;
}

/** Strict `true`/`false` coercion; empty means false. Anything else is an error. */
function toBool(value, column, label, lineNo, errors) {
  const v = value.toLowerCase();
  if (v === '' || v === 'false') return false;
  if (v === 'true') return true;
  errors.push(
    `${label} line ${lineNo}: column ${column} must be true or false (found ${JSON.stringify(value)})`,
  );
  return false;
}

/** Map header-aligned values into a `{column: value}` record. */
function toRecord(header, values) {
  const record = {};
  for (let i = 0; i < header.length; i += 1) record[header[i]] = values[i];
  return record;
}

function mapRooms(parsed, label, errors) {
  const rooms = new Map();
  const firstLine = new Map();

  for (const { values, line } of parsed.rows) {
    if (values.length !== parsed.header.length) {
      errors.push(
        `${label} line ${line}: expected ${parsed.header.length} fields, found ${values.length}`,
      );
      continue;
    }
    const r = toRecord(parsed.header, values);
    const id = r.room_id;
    if (id === '') {
      errors.push(`${label} line ${line}: room_id is empty`);
      continue;
    }
    if (rooms.has(id)) {
      errors.push(
        `${label} line ${line}: duplicate room_id ${JSON.stringify(id)} (first defined at line ${firstLine.get(id)})`,
      );
      continue;
    }
    firstLine.set(id, line);
    rooms.set(id, {
      id,
      name: r.name,
      description: r.description,
      exits: {
        north: orNull(r.exit_north),
        south: orNull(r.exit_south),
        east: orNull(r.exit_east),
        west: orNull(r.exit_west),
      },
      entryRequiresFlag: orNull(r.entry_requires_flag),
      entryFailText: orNull(r.entry_fail_text),
      line,
    });
  }

  return rooms;
}

function mapObjects(parsed, label, errors) {
  const objects = new Map();
  const firstLine = new Map();

  for (const { values, line } of parsed.rows) {
    if (values.length !== parsed.header.length) {
      errors.push(
        `${label} line ${line}: expected ${parsed.header.length} fields, found ${values.length}`,
      );
      continue;
    }
    const r = toRecord(parsed.header, values);
    const id = r.object_id;
    if (id === '') {
      errors.push(`${label} line ${line}: object_id is empty`);
      continue;
    }
    if (objects.has(id)) {
      errors.push(
        `${label} line ${line}: duplicate object_id ${JSON.stringify(id)} (first defined at line ${firstLine.get(id)})`,
      );
      continue;
    }
    firstLine.set(id, line);
    objects.set(id, {
      id,
      name: r.name,
      startRoom: r.start_room,
      description: r.description,
      takeable: toBool(r.takeable, 'takeable', label, line, errors),
      takeSetsFlag: orNull(r.take_sets_flag),
      useVerb: orNull(r.use_verb),
      useRequiresFlag: orNull(r.use_requires_flag),
      useRequiresRoom: orNull(r.use_requires_room),
      useSetsFlag: orNull(r.use_sets_flag),
      useConsumes: toBool(r.use_consumes, 'use_consumes', label, line, errors),
      useSuccessText: r.use_success_text,
      useFailText: r.use_fail_text,
      line,
    });
  }

  return objects;
}

/**
 * Cross-file validation. Every violation is collected so an author sees the
 * whole list at once, then a single ContentError is thrown.
 */
function validate(rooms, objects, flags, errors) {
  if (rooms.size === 0) errors.push('rooms.csv defines no rooms');

  for (const room of rooms.values()) {
    for (const dir of DIRECTIONS) {
      const target = room.exits[dir];
      if (target !== null && !rooms.has(target)) {
        errors.push(
          `rooms.csv line ${room.line}: room ${JSON.stringify(room.id)} exit_${dir} targets unknown room ${JSON.stringify(target)}`,
        );
      }
    }
    if (room.entryRequiresFlag !== null && !flags.has(room.entryRequiresFlag)) {
      errors.push(
        `rooms.csv line ${room.line}: room ${JSON.stringify(room.id)} entry_requires_flag ${JSON.stringify(room.entryRequiresFlag)} is unreachable — no object sets it via take_sets_flag/use_sets_flag`,
      );
    }
    // A locked room MUST say what kind of lock it is. This is a playability
    // rule enforced as a content rule: the generic refusal tells a player only
    // that they failed, never what to go and do about it, and a door that
    // cannot be reasoned about is indistinguishable from a dead end.
    if (room.entryRequiresFlag !== null && room.entryFailText === null) {
      errors.push(
        `rooms.csv line ${room.line}: room ${JSON.stringify(room.id)} is gated on ${JSON.stringify(room.entryRequiresFlag)} but has no entry_fail_text — a locked door must tell the player what kind of obstacle it is`,
      );
    }
    // ...and an ungated room must not carry text that could never be shown.
    if (room.entryRequiresFlag === null && room.entryFailText !== null) {
      errors.push(
        `rooms.csv line ${room.line}: room ${JSON.stringify(room.id)} has entry_fail_text but no entry_requires_flag — that text can never be shown`,
      );
    }
  }

  for (const obj of objects.values()) {
    if (obj.startRoom !== INVENTORY_START && !rooms.has(obj.startRoom)) {
      errors.push(
        `objects.csv line ${obj.line}: object ${JSON.stringify(obj.id)} start_room ${JSON.stringify(obj.startRoom)} is not a known room_id (or ${JSON.stringify(INVENTORY_START)})`,
      );
    }
    if (obj.useRequiresFlag !== null && !flags.has(obj.useRequiresFlag)) {
      errors.push(
        `objects.csv line ${obj.line}: object ${JSON.stringify(obj.id)} use_requires_flag ${JSON.stringify(obj.useRequiresFlag)} is unreachable — no object sets it via take_sets_flag/use_sets_flag`,
      );
    }
    if (obj.useRequiresRoom !== null && !rooms.has(obj.useRequiresRoom)) {
      errors.push(
        `objects.csv line ${obj.line}: object ${JSON.stringify(obj.id)} use_requires_room ${JSON.stringify(obj.useRequiresRoom)} is not a known room_id`,
      );
    }
    // Gating columns on an object with no use_verb are dead: `use` refuses it
    // before any of them is read.
    if (obj.useVerb === null && (obj.useRequiresFlag !== null || obj.useRequiresRoom !== null)) {
      errors.push(
        `objects.csv line ${obj.line}: object ${JSON.stringify(obj.id)} has use gating but no use_verb — the gate can never be reached`,
      );
    }
  }

  if (errors.length > 0) {
    const plural = errors.length === 1 ? 'error' : 'errors';
    throw new ContentError(
      `Content validation failed (${errors.length} ${plural}):\n` +
        errors.map((e) => `- ${e}`).join('\n'),
    );
  }
}

/**
 * Parse + validate raw CSV text into the in-memory content model.
 *
 * Returns `{ rooms, objects, flags }` where:
 * - `rooms`: Map<roomId, {id, name, description, exits:{north,south,east,west},
 *   entryRequiresFlag, line}> — **insertion order is rooms.csv file order**
 * - `objects`: Map<objectId, {id, name, startRoom, description, takeable,
 *   takeSetsFlag, useVerb, useRequiresFlag, useSetsFlag, useConsumes,
 *   useSuccessText, useFailText, line}> — **insertion order is objects.csv file
 *   order**, which PRD's deterministic action_id assignment (T-006) relies on.
 *   Never sort these maps.
 * - `flags`: Set<string> of every flag any object can set (the flag universe
 *   used to initialize state in T-004 and to validate the gates here).
 *
 * @param {string} roomsText raw `rooms.csv` text
 * @param {string} objectsText raw `objects.csv` text
 * @throws {ContentError} on any malformed or invalid content
 */
export function parseContent(roomsText, objectsText) {
  const roomsParsed = parseCsv(roomsText, 'rooms.csv');
  checkHeader(roomsParsed.header, ROOM_COLUMNS, 'rooms.csv');
  const objectsParsed = parseCsv(objectsText, 'objects.csv');
  checkHeader(objectsParsed.header, OBJECT_COLUMNS, 'objects.csv');

  const errors = [];
  const rooms = mapRooms(roomsParsed, 'rooms.csv', errors);
  const objects = mapObjects(objectsParsed, 'objects.csv', errors);

  const flags = new Set();
  for (const obj of objects.values()) {
    if (obj.takeSetsFlag !== null) flags.add(obj.takeSetsFlag);
    if (obj.useSetsFlag !== null) flags.add(obj.useSetsFlag);
  }

  validate(rooms, objects, flags, errors);
  return { rooms, objects, flags };
}

/** Resolve a filename inside a content directory given as a URL or a string path. */
function resolveContentFile(contentDir, filename) {
  if (contentDir instanceof URL) return new URL(filename, contentDir);
  if (typeof contentDir === 'string' && contentDir.startsWith('file:')) {
    return new URL(filename, contentDir.endsWith('/') ? contentDir : `${contentDir}/`);
  }
  return path.join(contentDir, filename);
}

function readContentFile(contentDir, filename) {
  const target = resolveContentFile(contentDir, filename);
  try {
    return readFileSync(target, 'utf8');
  } catch (err) {
    const shown = target instanceof URL ? target.href : target;
    throw new ContentError(`Could not read ${filename} at ${shown}: ${err.message}`);
  }
}

/**
 * Load and validate `rooms.csv` + `objects.csv` into in-memory maps.
 * @param {URL|string} [contentDir] directory containing the CSV files
 * @returns {{rooms: Map, objects: Map, flags: Set<string>}}
 * @throws {ContentError}
 */
export function loadContent(contentDir = CONTENT_DIR) {
  const roomsText = readContentFile(contentDir, 'rooms.csv');
  const objectsText = readContentFile(contentDir, 'objects.csv');
  return parseContent(roomsText, objectsText);
}

/* -------------------------------------------------------------------------
 * T-004 — game state + the single command entry point.
 *
 * Everything below is rules. No room, object, flag or puzzle *content* appears
 * here: the start room and the escape room are derived from rooms.csv file
 * order (see createGame), every gate/effect is read off the loaded records, and
 * every object-specific string comes from the CSV columns. The engine's own
 * strings are deliberately generic refusals that name nothing in the world.
 * ---------------------------------------------------------------------- */

/** Free-text synonyms the front ends may pass straight through. */
const VERB_ALIASES = { inv: 'inventory', i: 'inventory' };
const DIRECTION_ALIASES = { n: 'north', s: 'south', e: 'east', w: 'west' };

/** Generic refusals — never name a specific room, object or puzzle. */
const REFUSALS = {
  // Names the vocabulary rather than just saying no: this game has seven verbs
  // and no way for a player to discover them by guessing, so a bare "I don't
  // understand that" is a dead end at exactly the moment someone is trying.
  unknownVerb:
    "I don't understand that. Try a direction, or one of: look, inventory, take, drop, examine, use.",
  noSuchObject: "You don't see that here.",
  noSuchDirection: 'That is not a direction.',
  noExit: "You can't go that way.",
  // Fallback only. A gated room is REQUIRED to author its own entry_fail_text
  // (see validate()), so this is what an ungated engine-level lock would say —
  // deliberately terse, because a door with nothing to teach should not pretend
  // otherwise.
  locked: 'The way is shut.',
  // The object is right, the place is not.
  wrongPlace: "Not here. Whatever this works on, it isn't in this room.",
  // e.g. `read lantern`, where `light` is the lantern's verb.
  wrongUseVerb: 'That is not what you do with it.',
  notHere: "You don't see that here.",
  notTakeable: "It won't budge.",
  alreadyHeld: 'You are already carrying it.',
  notHeld: "You aren't carrying that.",
  notUsable: "You can't use that.",
  nothingHappens: 'Nothing happens.',
  emptyInventory: 'You are carrying nothing.',
};

/**
 * Build a fresh, mutable game from loaded content.
 *
 * Authoring convention (PRD § Scope: "a single linear-with-branches flag chain
 * ending in one exit room"): the **first** row of `rooms.csv` is the start room
 * and the **last** row is the escape room. Deriving both from file order is
 * what keeps this file free of hardcoded room ids; an author moves the start or
 * the exit by reordering the CSV, not by editing code. Both can still be pinned
 * explicitly via `options` (used by tests/tools that need to be exact).
 *
 * @param {{rooms: Map, objects: Map, flags: Set<string>}} [content]
 * @param {{startRoom?: string, escapeRoom?: string}} [options]
 * @returns {object} the mutable game (pass it to executeCommand/getState)
 * @throws {ContentError} if an override names a room that doesn't exist
 */
export function createGame(content = loadContent(), options = {}) {
  const roomIds = [...content.rooms.keys()];
  if (roomIds.length === 0) throw new ContentError('Content defines no rooms');

  const pick = (override, fallback, label) => {
    if (override === undefined || override === null) return fallback;
    if (!content.rooms.has(override)) {
      throw new ContentError(`${label} ${JSON.stringify(override)} is not a known room_id`);
    }
    return override;
  };

  const startRoom = pick(options.startRoom, roomIds[0], 'startRoom');
  const escapeRoom = pick(options.escapeRoom, roomIds[roomIds.length - 1], 'escapeRoom');

  const inventory = new Set();
  const locations = new Map();
  for (const obj of content.objects.values()) {
    if (obj.startRoom === INVENTORY_START) inventory.add(obj.id);
    else locations.set(obj.id, obj.startRoom);
  }

  // Seed every flag in the universe as false so the flags key set is stable for
  // the whole run (UGT's observation mapping depends on that).
  const flags = new Map();
  for (const flag of content.flags) flags.set(flag, false);

  return {
    content,
    startRoom,
    escapeRoom,
    currentRoom: startRoom,
    inventory,
    locations,
    flags,
    visited: new Set([startRoom]),
    movesTaken: 0,
    escaped: false,
  };
}

/**
 * Snapshot the game in PRD.md's exact wire shape (§ "UGT hooks required").
 *
 * Freshly built and fully JSON-serializable on every call, so a caller can
 * mutate or stringify the result without touching the game. `inventory` is
 * serialized in objects.csv file order (not pickup order), so the same held set
 * always produces the same array.
 *
 * @param {object} game
 * @returns {{current_room: string, inventory: string[], flags: Object<string, boolean>,
 *   moves_taken: number, rooms_visited: number, escaped: boolean}}
 */
export function getState(game) {
  const inventory = [];
  for (const id of game.content.objects.keys()) {
    if (game.inventory.has(id)) inventory.push(id);
  }

  const flags = {};
  for (const [name, value] of game.flags) flags[name] = value;

  return {
    current_room: game.currentRoom,
    // The player-facing name of `current_room`, e.g. "Storeroom".
    //
    // `current_room` is an internal id (`R04`) that NO human is ever shown: the
    // CLI prints the room's name on every entry and every `look`. A machine
    // client reading only the id therefore had to reconstruct the name from
    // prose that scrolls, and an LLM playtester was observed binding the wrong
    // name to the right id ("R04 (Guard Corridor)" — R04 is the Storeroom) and
    // then walking into a wall for twelve moves. Added 2026-07-26.
    //
    // Derived, never authored: it is a read of the same `rooms.csv` column the
    // CLI prints, so it cannot drift from what a human sees.
    room_name: game.content.rooms.get(game.currentRoom).name,
    inventory,
    flags,
    moves_taken: game.movesTaken,
    rooms_visited: game.visited.size,
    escaped: game.escaped,
  };
}

/**
 * Resolve free text to an object record: exact `object_id` first, then a
 * case-insensitive match on `object_id` or display `name` (PRD § Content
 * format). Resolution is content-model work, so it lives here and the front
 * ends never need to read the CSVs themselves.
 *
 * @returns {object|null} the object record, or null if nothing matches
 */
export function resolveObject(game, text) {
  if (typeof text !== 'string') return null;
  const needle = text.trim();
  if (needle === '') return null;
  if (game.content.objects.has(needle)) return game.content.objects.get(needle);

  const lower = needle.toLowerCase();
  for (const obj of game.content.objects.values()) {
    if (obj.id.toLowerCase() === lower || obj.name.toLowerCase() === lower) return obj;
  }
  return null;
}

/** True when the object is in the current room (i.e. lying there, not held). */
function inRoom(game, obj) {
  return game.locations.get(obj.id) === game.currentRoom;
}

/** Objects lying in the current room, in objects.csv file order. */
function roomObjects(game) {
  const here = [];
  for (const obj of game.content.objects.values()) {
    if (inRoom(game, obj)) here.push(obj);
  }
  return here;
}

/**
 * Render the current room (name, description, exits, visible objects).
 *
 * Read-only view helper for the front ends — it mutates nothing and does not
 * count as a move, so `cli.js` can print the opening room before the player has
 * typed anything without inflating `moves_taken`. Rendering rooms is a
 * content-model concern, so it lives here rather than in a front end.
 */
export function describeRoom(game) {
  const room = game.content.rooms.get(game.currentRoom);
  const lines = [room.name, room.description];

  const exits = DIRECTIONS.filter((d) => room.exits[d] !== null);
  lines.push(exits.length ? `Exits: ${exits.join(', ')}.` : 'There are no exits.');

  const here = roomObjects(game);
  if (here.length) lines.push(`You can see: ${here.map((o) => o.name).join(', ')}.`);
  return lines.join('\n');
}

/**
 * Build the fixed discrete action table the machine front end indexes into
 * (PRD § "Fixed discrete action space").
 *
 * Assignment is deterministic and comes straight from the content model:
 *   0=north, 1=south, 2=east, 3=west, 4=look, 5=inventory
 * then, for each row of `objects.csv` **in file order**, append in this
 * per-object order: `take` (if `takeable`), `drop` (if `takeable`), `examine`
 * (always), `use` (if `use_verb` is set). Same CSVs always produce the same
 * ids, so the integration side's `ugt.config.yaml` action_space mapping stays
 * valid without hand-tuning; an author reorders `objects.csv` to change ids.
 *
 * This lives in the engine, not in `bridge.js`, for the same reason
 * `resolveObject`/`describeRoom`/`normalizeDirection` do: deciding *which verbs
 * an object supports* is a reading of the content model, i.e. a rule. The
 * bridge is left with nothing to do but index the returned array.
 *
 * The table is built once at startup and is stable for the whole run — it is
 * never rebuilt on `reset`, because content cannot change mid-process. Entries
 * (and the array) are frozen so a caller can't mutate the shared table.
 *
 * `verb` is always an engine verb: an object's `use_verb` column
 * (`unlock`/`light`/`turn`/…) is authored *flavor*, never a command, so a
 * usable object's entry is `use`. `name` is a human-readable label for the
 * integration's config, not a rule the engine consults.
 *
 * @param {{rooms: Map, objects: Map, flags: Set<string>}} [content]
 * @returns {ReadonlyArray<{verb: string, arg: string|null, name: string}>}
 */
export function buildActionTable(content = loadContent()) {
  const entries = [];
  const push = (verb, arg) => {
    entries.push(Object.freeze({ verb, arg, name: arg === null ? verb : `${verb}_${arg}` }));
  };

  for (const dir of DIRECTIONS) push('go', dir);
  push('look', null);
  push('inventory', null);

  for (const obj of content.objects.values()) {
    if (obj.takeable) {
      push('take', obj.id);
      push('drop', obj.id);
    }
    push('examine', obj.id);
    if (obj.useVerb !== null) push('use', obj.id);
  }

  return Object.freeze(entries);
}

function describeInventory(game) {
  const held = [];
  for (const obj of game.content.objects.values()) {
    if (game.inventory.has(obj.id)) held.push(obj.name);
  }
  return held.length ? `You are carrying: ${held.join(', ')}.` : REFUSALS.emptyInventory;
}

/* -- per-verb rules -------------------------------------------------------
 * Each handler returns {ok, message} and mutates the game ONLY when ok is
 * true. executeCommand owns the move counter and the state snapshot.
 * ---------------------------------------------------------------------- */

/**
 * Canonicalize free text to a compass direction, or null if it isn't one
 * (`n`/`s`/`e`/`w` and case are accepted).
 *
 * Read-only vocabulary helper: the direction words are engine vocabulary, so a
 * front end that needs to recognize a bare direction (`cli.js`'s "just type
 * `n`" shorthand) asks here instead of keeping its own copy of the list.
 *
 * @param {string} text
 * @returns {string|null} 'north' | 'south' | 'east' | 'west' | null
 */
export function normalizeDirection(text) {
  const raw = typeof text === 'string' ? text.trim().toLowerCase() : '';
  const dir = DIRECTION_ALIASES[raw] ?? raw;
  return DIRECTIONS.includes(dir) ? dir : null;
}

function doGo(game, arg) {
  const dir = normalizeDirection(arg);
  if (dir === null) return { ok: false, message: REFUSALS.noSuchDirection };

  const target = game.content.rooms.get(game.currentRoom).exits[dir];
  if (target === null) return { ok: false, message: REFUSALS.noExit };

  const next = game.content.rooms.get(target);
  if (next.entryRequiresFlag !== null && game.flags.get(next.entryRequiresFlag) !== true) {
    // The refusal flavor is authored content, not an engine string — same rule
    // the `use` gate already followed. validate() requires it to exist.
    return { ok: false, message: next.entryFailText || REFUSALS.locked };
  }

  game.currentRoom = target;
  game.visited.add(target);
  // Latching: once escaped, always escaped (the bridge mirrors it into
  // `terminated`; leaving the exit room afterwards never un-escapes you).
  if (target === game.escapeRoom) game.escaped = true;

  return { ok: true, message: describeRoom(game) };
}

function doTake(game, arg) {
  const obj = resolveObject(game, arg);
  if (obj === null) return { ok: false, message: REFUSALS.noSuchObject };
  if (game.inventory.has(obj.id)) return { ok: false, message: REFUSALS.alreadyHeld };
  if (!inRoom(game, obj)) return { ok: false, message: REFUSALS.notHere };
  if (!obj.takeable) return { ok: false, message: REFUSALS.notTakeable };

  game.locations.delete(obj.id);
  game.inventory.add(obj.id);
  if (obj.takeSetsFlag !== null) game.flags.set(obj.takeSetsFlag, true);

  return { ok: true, message: `Taken: ${obj.name}.` };
}

function doDrop(game, arg) {
  const obj = resolveObject(game, arg);
  if (obj === null) return { ok: false, message: REFUSALS.noSuchObject };
  if (!game.inventory.has(obj.id)) return { ok: false, message: REFUSALS.notHeld };

  game.inventory.delete(obj.id);
  game.locations.set(obj.id, game.currentRoom);
  // Flags are monotonic: dropping never clears a take_sets_flag. What you
  // learned by picking something up stays learned.

  return { ok: true, message: `Dropped: ${obj.name}.` };
}

function doExamine(game, arg) {
  const obj = resolveObject(game, arg);
  if (obj === null) return { ok: false, message: REFUSALS.noSuchObject };
  if (!game.inventory.has(obj.id) && !inRoom(game, obj)) {
    return { ok: false, message: REFUSALS.notHere };
  }
  return { ok: true, message: obj.description };
}

function doUse(game, arg) {
  const obj = resolveObject(game, arg);
  if (obj === null) return { ok: false, message: REFUSALS.noSuchObject };
  if (!game.inventory.has(obj.id)) return { ok: false, message: REFUSALS.notHeld };
  if (obj.useVerb === null) return { ok: false, message: REFUSALS.notUsable };

  // Place before prerequisite: "are you even standing at the thing" is the more
  // basic question, and answering it first means a player carrying a key around
  // is told where to go rather than what else to find.
  if (obj.useRequiresRoom !== null && game.currentRoom !== obj.useRequiresRoom) {
    return { ok: false, message: REFUSALS.wrongPlace };
  }

  if (obj.useRequiresFlag !== null && game.flags.get(obj.useRequiresFlag) !== true) {
    // The refusal flavor is authored content, not an engine string.
    return { ok: false, message: obj.useFailText || REFUSALS.nothingHappens };
  }

  if (obj.useSetsFlag !== null) game.flags.set(obj.useSetsFlag, true);
  // use_consumes destroys the object: it leaves the inventory without landing
  // in the room, so it can never be taken again.
  if (obj.useConsumes) game.inventory.delete(obj.id);

  // A non-consuming object may be re-used freely; the effect is idempotent
  // (the same flag is simply set true again).
  return { ok: true, message: obj.useSuccessText || REFUSALS.nothingHappens };
}

/**
 * Dispatch a verb that isn't one of the seven built-ins.
 *
 * `objects.csv` authors a `use_verb` per usable object — `unlock`, `light`,
 * `turn`, `fit`, `read`. Those used to be decoration: the engine only ever
 * asked whether the column was non-null and never read the value, so the game
 * declared a verb per object, never accepted it as a command, and never printed
 * it. Typing the most natural thing in the world — `read ledger` — answered
 * "I don't understand that."
 *
 * Now the authored verb IS a command, and only on the object that declares it:
 * `read ledger` works, `read lantern` does not (the lantern's verb is `light`).
 * That keeps the vocabulary content-driven — a new object with a new verb
 * teaches the parser a word, with no engine edit — while still refusing
 * nonsense pairings rather than silently treating every verb as `use`.
 *
 * @returns {{ok: boolean, message: string}}
 */
function doAuthoredVerb(game, name, arg) {
  let known = false;
  for (const o of game.content.objects.values()) {
    if (o.useVerb === name) {
      known = true;
      break;
    }
  }
  if (!known) return { ok: false, message: REFUSALS.unknownVerb };

  const obj = resolveObject(game, arg);
  if (obj === null) return { ok: false, message: REFUSALS.noSuchObject };
  if (obj.useVerb !== name) return { ok: false, message: REFUSALS.wrongUseVerb };
  return doUse(game, arg);
}

const HANDLERS = {
  look: (game) => ({ ok: true, message: describeRoom(game) }),
  inventory: (game) => ({ ok: true, message: describeInventory(game) }),
  go: doGo,
  take: doTake,
  drop: doDrop,
  examine: doExamine,
  use: doUse,
};

/**
 * Apply one command to the game. The ONLY entry point through which state may
 * change — `cli.js` and `bridge.js` translate their input into a call here and
 * render what comes back.
 *
 * Semantics:
 * - A refusal (`ok: false`) changes nothing at all, including `moves_taken`
 *   (PRD § Parser verbs: an inapplicable action "consumes no state"). This is
 *   what makes the bridge's invalid-action_id case a true no-op that still
 *   returns state.
 * - `moves_taken` increments on every successful command, movement or not.
 * - No randomness anywhere: the same command sequence from a fresh game always
 *   produces identical state (PRD § Acceptance criteria).
 *
 * @param {object} game a game from createGame()
 * @param {string} verb one of the PRD verbs (`inv`/`i` alias `inventory`)
 * @param {string} [arg] a direction (`n`/`s`/`e`/`w` accepted) or an object
 *   id / display name, matched case-insensitively
 * @returns {{ok: boolean, message: string, state: object}} `state` is a fresh
 *   snapshot in PRD's exact wire shape
 */
export function executeCommand(game, verb, arg) {
  if (game === null || typeof game !== 'object' || !(game.flags instanceof Map)) {
    throw new TypeError('executeCommand(game, verb, arg): game must come from createGame()');
  }

  const raw = typeof verb === 'string' ? verb.trim().toLowerCase() : '';
  const name = VERB_ALIASES[raw] ?? raw;
  const handler = Object.prototype.hasOwnProperty.call(HANDLERS, name)
    ? HANDLERS[name]
    : null;

  const result = handler === null
    ? doAuthoredVerb(game, name, arg)
    : handler(game, arg);

  if (result.ok) game.movesTaken += 1;

  return { ok: result.ok, message: result.message, state: getState(game) };
}

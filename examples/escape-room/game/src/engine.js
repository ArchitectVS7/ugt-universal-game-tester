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
 * T-002 implements loadContent(); T-004 implements
 * createGame()/executeCommand().
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

/**
 * Build a fresh game state from loaded content.
 */
export function createGame(...args) {
  void args;
  throw new Error('engine.createGame not implemented yet (T-004)');
}

/**
 * Apply one command to the game state and return the result.
 * The only entry point through which state may change.
 */
export function executeCommand(state, verb, arg) {
  void state;
  void verb;
  void arg;
  throw new Error('engine.executeCommand not implemented yet (T-004)');
}

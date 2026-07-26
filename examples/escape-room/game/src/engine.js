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
 * T-001 scaffold: signatures only. T-002 implements loadContent(),
 * T-004 implements createGame()/executeCommand().
 */

/** Directory holding the authored CSV content, resolved relative to this module. */
export const CONTENT_DIR = new URL('../content/', import.meta.url);

/**
 * Load and validate `rooms.csv` + `objects.csv` into in-memory maps.
 * @param {URL|string} [contentDir] directory containing the CSV files
 */
export function loadContent(contentDir = CONTENT_DIR) {
  void contentDir;
  throw new Error('engine.loadContent not implemented yet (T-002)');
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

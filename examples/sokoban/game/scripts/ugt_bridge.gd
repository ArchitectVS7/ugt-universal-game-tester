extends Node

## UGT TCP bridge (T-007) — the MACHINE front end.
##
## THIS FILE CONTAINS NO GAME RULE. Per the standing constraint in TASKS.md,
## every push / collision / win rule lives in exactly one place —
## `res://scripts/board.gd`'s `try_move()`. All this script may do is:
##   1. frame newline-delimited JSON off a TCP socket,
##   2. turn a wire `action_id` into an `int` and hand it to `board.try_move()`,
##   3. hand `board.get_state()` back out, verbatim.
## No direction vector, no wall/push check, no `boxes_on_target` arithmetic, no
## `is_solved()` reimplementation, and deliberately NO RANGE CHECK on
## `action_id` — `try_move()` documents an out-of-range direction as a silent
## no-op precisely so the wire value can be passed straight through. `terminated`
## is READ OUT of `get_state()["all_levels_solved"]`, never recomputed. A
## reviewer can grep this file for `Tile`, `WALL`, `Direction`, `moves_taken` or
## `is_solved` and should find no decision made on them.
##
## Wire protocol (PRD.md "UGT hooks required", matched exactly):
##   {"command": "reset"}                  -> {"state": {...}}
##   {"command": "step", "action_id": N}   -> {"state": {...}, "terminated": bool,
##                                             "truncated": bool, "info": {}}
##   {"command": "close"}                  -> no reply; the process exits cleanly
##                                            (the client observes EOF)
##
## Registered as an autoload, but INERT unless launched with `--ugt-bridge` (or
## `UGT_BRIDGE=1`) — a plain `godot4 --headless --path .` run must behave as if
## this file did not exist. Listens on `127.0.0.1:8910`, overridable with
## `--ugt-port=N` (also accepted as `--ugt-port N`), ONE connection at a time.
##
## `StreamPeerTCP` delivers raw bytes with no line framing, so a message can
## legitimately arrive split across two or more `_process()` polls — and two
## messages can arrive in one read. `feed_bytes()` below is the buffer that
## makes both cases correct; NEVER treat one socket read as one message.
##
## Errors are printed as returned data, never `push_error()` / `assert()`: a
## project run must leave stderr clean (T-001's Accept).

const Board := preload("res://scripts/board.gd")

const DEFAULT_HOST := "127.0.0.1"
const DEFAULT_PORT := 8910

const BRIDGE_FLAG := "--ugt-bridge"
const PORT_FLAG := "--ugt-port"
const ENV_FLAG := "UGT_BRIDGE"

## Line terminator, as a byte. The protocol is newline-delimited JSON.
const NEWLINE_BYTE := 10

## A client that never sends a `\n` must not be able to grow the read buffer
## without bound. Wire hygiene, not a rule.
const MAX_BUFFER_BYTES := 1 << 20

## Printed exactly once on a successful listen. `tools/tcp_smoke_check.py`
## (T-008) uses this line as the readiness signal — keep the text stable.
const READY_MESSAGE := "UGT bridge listening on %s:%d"

var _server: TCPServer = null
var _peer: StreamPeerTCP = null
var _rx: PackedByteArray = PackedByteArray()
var _board = null


# --------------------------------------------------------------------------
# Layer 1 — launch gate + port parsing (pure statics; the tests never touch OS)
# --------------------------------------------------------------------------


## True when the bridge should run. `args` is the full command line;
## `env_value` is `OS.get_environment("UGT_BRIDGE")` ("" when unset).
static func bridge_enabled(args: PackedStringArray, env_value: String) -> bool:
	for arg in args:
		if arg == BRIDGE_FLAG:
			return true
	var normalized := env_value.strip_edges().to_lower()
	return normalized == "1" or normalized == "true"


## Port from `--ugt-port=N` (PRD form) or `--ugt-port N` (two-token form).
## Anything non-numeric or outside 1..65535 falls back to `default_port` —
## `"abc".to_int()` is 0, which would otherwise become a silently wrong port.
static func port_from_args(args: PackedStringArray, default_port: int = DEFAULT_PORT) -> int:
	var raw := ""
	for i in range(args.size()):
		var arg := args[i]
		if arg.begins_with(PORT_FLAG + "="):
			raw = arg.substr(PORT_FLAG.length() + 1)
		elif arg == PORT_FLAG and i + 1 < args.size():
			raw = args[i + 1]
	raw = raw.strip_edges()
	if raw.is_empty() or not raw.is_valid_int():
		return default_port
	var port := raw.to_int()
	if port < 1 or port > 65535:
		return default_port
	return port


func _ready() -> void:
	# The documented invocation puts the flags after `--`, which Godot hands
	# back through get_cmdline_user_args(), so BOTH lists must be consulted.
	var args := PackedStringArray()
	args.append_array(OS.get_cmdline_args())
	args.append_array(OS.get_cmdline_user_args())

	if not bridge_enabled(args, OS.get_environment(ENV_FLAG)):
		set_process(false)
		return

	var port := port_from_args(args)
	var err := start_server(port)
	if err != OK:
		# Loud and fast: a silently deaf bridge would hang T-008 forever.
		print("UGT bridge: could not listen on %s:%d (error %d)" % [DEFAULT_HOST, port, err])
		get_tree().quit(1)
		return
	print(READY_MESSAGE % [DEFAULT_HOST, port])


# --------------------------------------------------------------------------
# Layer 2 — socket lifecycle
# --------------------------------------------------------------------------


## Starts listening. Returns an `Error` (`OK` on success). `port` 0 asks the OS
## for an ephemeral port — read it back with `local_port()`.
func start_server(port: int, host: String = DEFAULT_HOST) -> int:
	stop_server()
	var server := TCPServer.new()
	var err := server.listen(port, host)
	if err != OK:
		return err
	_server = server
	return OK


func local_port() -> int:
	return 0 if _server == null else _server.get_local_port()


func is_listening() -> bool:
	return _server != null and _server.is_listening()


func has_peer() -> bool:
	return _peer != null


func stop_server() -> void:
	_drop_peer()
	if _server != null:
		_server.stop()
		_server = null


## ONE tick of accept / read / dispatch. Public and frame-independent so the
## tests can drive the real socket path inside the synchronous runner — exactly
## the same discipline as T-006's `_on_direction_input(int)`.
func poll() -> void:
	if _server == null:
		return

	while _server.is_connection_available():
		var incoming := _server.take_connection()
		if incoming == null:
			break
		if _peer != null:
			# One connection at a time: refuse the extra one immediately rather
			# than queueing it, so a second client fails fast instead of hanging.
			incoming.disconnect_from_host()
			continue
		_peer = incoming
		_rx.clear()

	if _peer == null:
		return

	_peer.poll()

	# Read BEFORE judging the status: a client that writes and immediately
	# closes must still have its last message processed.
	var available := _peer.get_available_bytes()
	if available > 0:
		var result: Array = _peer.get_data(available)
		if result.size() == 2 and int(result[0]) == OK:
			for line in feed_bytes(result[1]):
				var outcome := handle_line(line)
				var response = outcome.get("response")
				if response != null:
					_write(response)
				if bool(outcome.get("close", false)):
					_shutdown()
					return

	var status := _peer.get_status()
	if status == StreamPeerTCP.STATUS_CONNECTING:
		return
	if status != StreamPeerTCP.STATUS_CONNECTED:
		# The client vanished without a `close`; keep listening for the next one.
		_drop_peer()


func _process(_delta: float) -> void:
	poll()


## Test seam: drive a caller-supplied board instead of loading `res://levels/`.
func set_board(board) -> void:
	_board = board


func _write(response: Dictionary) -> void:
	if _peer == null:
		return
	_peer.put_data((JSON.stringify(response) + "\n").to_utf8_buffer())


func _drop_peer() -> void:
	if _peer != null:
		_peer.disconnect_from_host()
		_peer = null
	_rx.clear()


## `close` command: hang up, stop listening, and end the process. The
## `is_inside_tree()` guard matters — the tests build a bridge with `.new()` and
## never add it to a tree, where `get_tree()` is null and quitting the test
## runner would be catastrophic.
func _shutdown() -> void:
	stop_server()
	if is_inside_tree():
		get_tree().quit(0)


# --------------------------------------------------------------------------
# Layer 3 — framing (buffer across polls, split on `\n`)
# --------------------------------------------------------------------------


## Appends `chunk` to the read buffer and returns every COMPLETE line it now
## holds, in order; a trailing partial line stays buffered for the next call.
## This is the whole answer to "one socket read is not one message".
func feed_bytes(chunk: PackedByteArray) -> Array:
	_rx.append_array(chunk)
	var lines: Array = []
	while true:
		var newline_at := -1
		for i in range(_rx.size()):
			if _rx[i] == NEWLINE_BYTE:
				newline_at = i
				break
		if newline_at < 0:
			break
		var line: String = _rx.slice(0, newline_at).get_string_from_utf8()
		_rx = _rx.slice(newline_at + 1)
		# strip_edges() also absorbs the `\r` of a CRLF-terminated line.
		lines.append(line.strip_edges())
	if _rx.size() > MAX_BUFFER_BYTES:
		# A peer that never terminates a line cannot be allowed to grow this
		# forever. Drop what it sent; the next `\n` resynchronises.
		_rx.clear()
	return lines


# --------------------------------------------------------------------------
# Layer 4 — protocol dispatch (board only; no socket)
# --------------------------------------------------------------------------


## Handles one framed line. Returns `{"response": Dictionary or null,
## "close": bool}` — pure, so every protocol case is testable without a socket.
func handle_line(line: String) -> Dictionary:
	var trimmed := line.strip_edges()
	if trimmed.is_empty():
		# Keepalive / stray newline: nothing to answer.
		return {"response": null, "close": false}

	# JSON.new().parse() rather than the JSON.parse_string() helper: the helper
	# pushes an engine error on bad input, so a garbage client would spray the
	# game's stderr. Returned data only — stderr stays clean (T-001's Accept).
	var json := JSON.new()
	if json.parse(trimmed) != OK:
		return _error("malformed JSON: %s" % trimmed.substr(0, 80))
	var parsed = json.data
	if typeof(parsed) != TYPE_DICTIONARY:
		return _error("expected a JSON object: %s" % trimmed.substr(0, 80))

	var command := str(parsed.get("command", ""))
	match command:
		"reset":
			var board = _ensure_board()
			board.reset_level()
			# Exactly the PRD's one-key reset reply — no `terminated`/`info`.
			return {"response": {"state": board.get_state()}, "close": false}
		"step":
			var board = _ensure_board()
			# The ONLY rule call in this file. No range check: `try_move()`
			# owns "an unknown direction is a no-op".
			board.try_move(_action_id_from(parsed))
			var state: Dictionary = board.get_state()
			var response := {
				"state": state,
				# Mirrored, never recomputed (PRD: "terminated mirrors
				# all_levels_solved").
				"terminated": state["all_levels_solved"],
				"truncated": false,
				"info": {},
			}
			return {"response": response, "close": false}
		"close":
			# The PRD's right-hand side of `close` is "Godot process exits
			# cleanly" — the client observes EOF, so no reply shape is invented.
			return {"response": null, "close": true}
		_:
			return _error("unknown command: %s" % command)


## Wire hygiene, NOT a rule: turn whatever arrived in `action_id` into an int.
##
## A missing / non-numeric / fractional value becomes -1, which `board.gd`
## documents as a silent no-op. It must NEVER be `int(value)`: GDScript's
## `int("up")` is 0, a perfectly legal UP move — a garbage wire value would then
## move the player. Out-of-RANGE integers (4, 99, -7) are passed through
## untouched, because deciding they are illegal is `try_move()`'s job.
func _action_id_from(message: Dictionary) -> int:
	if not message.has("action_id"):
		return -1
	var value = message["action_id"]
	match typeof(value):
		TYPE_INT:
			return value
		TYPE_FLOAT:
			# JSON has one number type, so a whole number can arrive as a float.
			return int(value) if value == floor(value) else -1
		_:
			return -1


## Error replies carry an `error` key and DELIBERATELY no `state` key, so an
## error can never be mistaken for a state response by a client that only looks
## at `state`. Reachable only for a malformed client — the PRD defines no error
## shape because a conforming client never produces one.
func _error(detail: String) -> Dictionary:
	return {"response": {"error": detail}, "close": false}


## The board this bridge drives, created on first use.
##
## Prefers the board the HUMAN front end is already playing (the "drive the real
## running game, never a shadow copy" discipline) and only falls back to its own
## instance when there is no scene — which is the case in the tests and under
## `-s` script runs.
func _ensure_board():
	if _board == null:
		_board = _board_from_current_scene()
	if _board == null:
		_board = Board.new()
	if _board.level_count() == 0:
		if not _board.load_levels_from_paths():
			# Returned data, printed — never push_error(): stderr must stay clean.
			print(
				(
					"UGT bridge: could not load levels — %s: %s"
					% [_board.error_code, _board.error_message]
				)
			)
	return _board


func _board_from_current_scene():
	if not is_inside_tree():
		return null
	var tree := get_tree()
	if tree == null or tree.current_scene == null:
		return null
	var scene := tree.current_scene
	if not ("board" in scene):
		return null
	return scene.board

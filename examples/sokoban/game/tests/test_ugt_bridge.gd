extends "res://tests/assertions.gd"
## T-007 — the UGT TCP bridge (`res://scripts/ugt_bridge.gd`).
##
## What this file proves, in four layers that mirror the script:
##   A. the launch gate + `--ugt-port` parsing (pure statics — `OS` is never
##      touched, so a test can assert on a command line that was never used);
##   B. FRAMING: a message split across two feeds still parses, two messages in
##      one feed both parse — "one socket read is not one message";
##   C. protocol dispatch against an injected fixture board (the PRD's exact
##      response shapes, and that an out-of-range / garbage `action_id` is a
##      silent no-op rather than an error or a crash);
##   D. the same acceptance criteria over a REAL TCP socket.
##
## The runner is SYNCHRONOUS: it calls each `test_*` method and reads `failures`
## the moment it returns. So there is deliberately no `await`, no signal, no
## `get_tree()` and no node added to a tree anywhere in this file — an `await`
## would return early and be scored green while still running. `Bridge.poll()`
## is public for exactly this reason: the socket cases pump it by hand instead
## of waiting for `_process()`. Every pump loop is bounded by a wall-clock
## deadline and asserts on it, so a broken bridge fails in ~2s rather than
## leaning on the runner's 60s watchdog.
##
## Fixtures are SMALL INLINE GRIDS (same discipline as `test_board.gd` /
## `test_human_input.gd`), never the shipped `res://levels/*.txt` — T-008 is the
## layer that drives the real levels over the wire. They are arrays of row
## strings joined by `_grid()` rather than triple-quoted literals, because
## GDScript keeps a multi-line string's indentation tabs.
##
## `Bridge` extends `Node`; every instance is created with `Bridge.new()`, never
## added to a tree, and freed in `after_each()` — `queue_free()` would never run
## outside a tree, and a leaked instance would leave a listening socket behind
## for the next case.

const Bridge := preload("res://scripts/ugt_bridge.gd")
const Board := preload("res://scripts/board.gd")

## 6x6 · player (2,2) · box (3,2) · target (3,3). Open room: all four
## directions are legal and RIGHT is a real push.
const ROOM := ["######", "#    #", "# @$ #", "#  . #", "#    #", "######"]

## 5x3 · player (1,1) · box (2,1) · target (3,1). RIGHT solves it in one move —
## and since it is the only level, that also sets `all_levels_solved`.
const ONE_BOX := ["#####", "#@$.#", "#####"]

## The PRD's state shape, sorted. Asserted as a SET (not a subset): an extra or
## renamed key is a protocol break for every downstream client.
const STATE_KEYS := [
	"all_levels_solved",
	"boxes_on_target",
	"boxes_total",
	"level_index",
	"level_solved",
	"moves_taken",
	"player_x",
	"player_y",
]

## PRD action ids, for readability in the cases below.
const UP := 0
const RIGHT := 3

## Ports are searched upward from here. 8910 (the real default) is deliberately
## NOT used: a live bridge or a stale process could own it, which would make
## this suite fail for a reason that has nothing to do with the code.
const TEST_PORT_BASE := 18910
const PORT_SEARCH_LIMIT := 40

## Wall-clock budget for any socket pump loop.
const PUMP_TIMEOUT_MS := 2000

var _bridges: Array = []
var _clients: Array = []


func after_each() -> void:
	for client in _clients:
		client.disconnect_from_host()
	_clients.clear()
	for bridge in _bridges:
		bridge.stop_server()
		bridge.free()
	_bridges.clear()


# --------------------------------------------------------------------------
# A. launch gate + port parsing
# --------------------------------------------------------------------------


func test_bridge_is_disabled_by_default() -> void:
	assert_false(Bridge.bridge_enabled(PackedStringArray(), ""), "no flag, no env")
	assert_false(Bridge.bridge_enabled(_args(["--headless", "--path", "."]), ""), "unrelated args")
	assert_false(Bridge.bridge_enabled(PackedStringArray(), "0"), "UGT_BRIDGE=0")
	assert_false(Bridge.bridge_enabled(PackedStringArray(), "no"), "UGT_BRIDGE=no")


func test_bridge_is_enabled_by_the_flag() -> void:
	assert_true(Bridge.bridge_enabled(_args(["--ugt-bridge"]), ""), "flag alone")
	# The real launch is `godot4 --headless --path . -- --ugt-bridge`; _ready()
	# concatenates the engine args and the user args, so the flag can be at any
	# position in the combined list.
	assert_true(
		Bridge.bridge_enabled(_args(["--headless", "--path", ".", "--ugt-bridge"]), ""),
		"flag after the engine args"
	)


func test_bridge_is_enabled_by_the_environment_variable() -> void:
	assert_true(Bridge.bridge_enabled(PackedStringArray(), "1"), "UGT_BRIDGE=1")
	assert_true(Bridge.bridge_enabled(PackedStringArray(), "true"), "UGT_BRIDGE=true")
	assert_true(Bridge.bridge_enabled(PackedStringArray(), "TRUE"), "UGT_BRIDGE=TRUE")


func test_port_defaults_to_8910() -> void:
	assert_eq(Bridge.DEFAULT_PORT, 8910, "the PRD's port")
	assert_eq(Bridge.port_from_args(_args(["--ugt-bridge"])), 8910, "no --ugt-port given")


func test_port_flag_equals_form() -> void:
	assert_eq(Bridge.port_from_args(_args(["--ugt-bridge", "--ugt-port=8911"])), 8911, "--ugt-port=N")


func test_port_flag_two_token_form() -> void:
	assert_eq(Bridge.port_from_args(_args(["--ugt-port", "8911"])), 8911, "--ugt-port N")


func test_invalid_port_falls_back_to_the_default() -> void:
	# `"abc".to_int()` is 0 — without the is_valid_int() guard this would
	# silently listen on an ephemeral port and T-008 could never find it.
	assert_eq(Bridge.port_from_args(_args(["--ugt-port=abc"])), 8910, "non-numeric")
	assert_eq(Bridge.port_from_args(_args(["--ugt-port=0"])), 8910, "port 0")
	assert_eq(Bridge.port_from_args(_args(["--ugt-port=99999"])), 8910, "out of range")
	assert_eq(Bridge.port_from_args(_args(["--ugt-port=-1"])), 8910, "negative")
	assert_eq(Bridge.port_from_args(_args(["--ugt-bridge", "--ugt-port"])), 8910, "flag, no value")


# --------------------------------------------------------------------------
# B. framing — the buffered `\n` splitter
# --------------------------------------------------------------------------


## THE task's second acceptance criterion, at the framing layer: one message,
## two feeds. (Case D2 repeats it over a real socket with two real writes.)
func test_message_split_across_two_feeds_parses() -> void:
	var bridge := _new_bridge()
	assert_eq(bridge.feed_bytes(_bytes('{"command":"re')), [], "no complete line yet")
	assert_eq(bridge.feed_bytes(_bytes('set"}\n')), ['{"command":"reset"}'], "line completes")


func test_two_messages_in_one_feed_both_parse() -> void:
	var bridge := _new_bridge()
	var lines: Array = bridge.feed_bytes(_bytes('{"command":"reset"}\n{"command":"close"}\n'))
	assert_eq(lines, ['{"command":"reset"}', '{"command":"close"}'], "both lines, in order")


func test_trailing_partial_line_is_retained() -> void:
	var bridge := _new_bridge()
	assert_eq(bridge.feed_bytes(_bytes("a\nb")), ["a"], "only the terminated line")
	assert_eq(bridge.feed_bytes(_bytes("\n")), ["b"], "the remainder completes later")


func test_crlf_line_ending_parses() -> void:
	var bridge := _new_bridge()
	assert_eq(bridge.feed_bytes(_bytes('{"command":"reset"}\r\n')), ['{"command":"reset"}'], "CRLF")


# --------------------------------------------------------------------------
# C. protocol dispatch (no socket)
# --------------------------------------------------------------------------


## THE task's first acceptance criterion, at the protocol layer: `reset` returns
## the PRD's exact state shape, under a single `state` key.
func test_reset_returns_the_prd_state_shape() -> void:
	var bridge := _new_bridge(ROOM)
	var outcome: Dictionary = bridge.handle_line('{"command":"reset"}')
	assert_false(outcome["close"], "reset does not close")
	var response: Dictionary = outcome["response"]
	assert_eq(_sorted(response.keys()), ["state"], "reset reply has exactly one key")
	var state: Dictionary = response["state"]
	assert_eq(_sorted(state.keys()), STATE_KEYS, "the PRD's 8 state keys, exactly")
	assert_eq(state["level_index"], 0, "level_index")
	assert_eq(state["player_x"], 2, "player_x")
	assert_eq(state["player_y"], 2, "player_y")
	assert_eq(state["boxes_on_target"], 0, "boxes_on_target")
	assert_eq(state["boxes_total"], 1, "boxes_total")
	assert_eq(state["moves_taken"], 0, "moves_taken")
	assert_false(state["level_solved"], "level_solved is a bool")
	assert_false(state["all_levels_solved"], "all_levels_solved is a bool")


func test_step_returns_the_prd_response_shape() -> void:
	var bridge := _new_bridge(ROOM)
	var response := _response(bridge, '{"command":"step","action_id":0}')
	assert_eq(
		_sorted(response.keys()), ["info", "state", "terminated", "truncated"], "the PRD's 4 keys"
	)
	assert_eq(_sorted(response["state"].keys()), STATE_KEYS, "state shape is unchanged by step")
	assert_false(response["terminated"], "mid-level: not terminated")
	assert_false(response["truncated"], "truncated is always false")
	assert_eq(response["info"], {}, "info is an empty dict")


func test_step_applies_the_move() -> void:
	var bridge := _new_bridge(ROOM)
	var state: Dictionary = _response(bridge, '{"command":"step","action_id":3}')["state"]
	assert_eq(state["player_x"], 3, "player moved right (pushing the box)")
	assert_eq(state["player_y"], 2, "same row")
	assert_eq(state["moves_taken"], 1, "a real move increments moves_taken")


## THE task's third acceptance criterion: an out-of-range `action_id` is a
## no-op, not an error and not a crash. Note what is asserted — a NORMAL 4-key
## step response with NO `error` key, and a byte-identical state.
func test_out_of_range_action_id_is_a_noop() -> void:
	var bridge := _new_bridge(ROOM)
	var before: Dictionary = _response(bridge, '{"command":"reset"}')["state"]
	for action_id in [4, 99, -1, -7, 2147483647]:
		var response := _response(bridge, '{"command":"step","action_id":%d}' % action_id)
		assert_false(response.has("error"), "action_id %d is not an error" % action_id)
		assert_eq(response["state"], before, "action_id %d left the state unchanged" % action_id)


## The `int("up") == 0` trap: a naive coercion would turn every garbage value
## into a legal UP move. Without this case that bug is invisible.
func test_garbage_action_id_is_a_noop() -> void:
	var bridge := _new_bridge(ROOM)
	var before: Dictionary = _response(bridge, '{"command":"reset"}')["state"]
	var messages := [
		'{"command":"step"}',
		'{"command":"step","action_id":"up"}',
		'{"command":"step","action_id":"0"}',
		'{"command":"step","action_id":null}',
		'{"command":"step","action_id":true}',
		'{"command":"step","action_id":1.5}',
		'{"command":"step","action_id":[3]}',
		'{"command":"step","action_id":{"dir":3}}',
	]
	for message in messages:
		var response := _response(bridge, message)
		assert_false(response.has("error"), "%s is not an error" % message)
		assert_eq(response["state"], before, "%s left the state unchanged" % message)


## A whole number can legitimately arrive as a JSON float — that one must still
## move, otherwise the previous case would be satisfied by rejecting everything.
func test_whole_float_action_id_still_moves() -> void:
	var bridge := _new_bridge(ROOM)
	var state: Dictionary = _response(bridge, '{"command":"step","action_id":3.0}')["state"]
	assert_eq(state["moves_taken"], 1, "3.0 is action id 3")
	assert_eq(state["player_x"], 3, "and it actually moved")


func test_terminated_mirrors_all_levels_solved() -> void:
	var bridge := _new_bridge(ONE_BOX)
	var response := _response(bridge, '{"command":"step","action_id":3}')
	assert_true(response["state"]["level_solved"], "the push solved the level")
	assert_true(response["state"]["all_levels_solved"], "it was the only level")
	assert_true(response["terminated"], "terminated mirrors all_levels_solved")
	# A further step on a frozen board must keep reporting terminated.
	var after := _response(bridge, '{"command":"step","action_id":0}')
	assert_true(after["terminated"], "still terminated after another step")


func test_reset_restores_the_start_state() -> void:
	var bridge := _new_bridge(ROOM)
	var first: Dictionary = _response(bridge, '{"command":"reset"}')["state"]
	_response(bridge, '{"command":"step","action_id":3}')
	_response(bridge, '{"command":"step","action_id":1}')
	var second: Dictionary = _response(bridge, '{"command":"reset"}')["state"]
	assert_eq(second, first, "reset reproduces the start state exactly")


func test_close_requests_shutdown_with_no_response() -> void:
	var bridge := _new_bridge(ROOM)
	var outcome: Dictionary = bridge.handle_line('{"command":"close"}')
	assert_true(outcome["close"], "close requests shutdown")
	assert_null(outcome["response"], "no reply — the client observes EOF")


func test_malformed_json_is_an_error_not_a_crash() -> void:
	var bridge := _new_bridge(ROOM)
	for line in ["{", "not json", "[1,2,3]", '"reset"', "null"]:
		var response := _response(bridge, line)
		assert_true(response.has("error"), "%s reports an error" % line)
		assert_false(response.has("state"), "%s carries no state key" % line)
	# The connection must not be poisoned by a bad line.
	var recovered := _response(bridge, '{"command":"reset"}')
	assert_eq(_sorted(recovered.keys()), ["state"], "a reset still works afterwards")


func test_unknown_command_is_an_error() -> void:
	var bridge := _new_bridge(ROOM)
	var response := _response(bridge, '{"command":"launch_missiles"}')
	assert_true(response.has("error"), "unknown command reports an error")
	assert_false(response.has("state"), "and carries no state key")


func test_blank_line_is_ignored() -> void:
	var bridge := _new_bridge(ROOM)
	for line in ["", "   ", "\t"]:
		var outcome: Dictionary = bridge.handle_line(line)
		assert_null(outcome["response"], "blank line gets no reply")
		assert_false(outcome["close"], "blank line does not close")


# --------------------------------------------------------------------------
# D. real TCP round trips
# --------------------------------------------------------------------------


## THE task's first acceptance criterion, over a real socket: connect, `reset`,
## one `step`, PRD shapes back.
func test_tcp_reset_then_step_round_trip() -> void:
	var bridge := _new_bridge(ROOM)
	var client = _connect(bridge)
	if client == null:
		return

	var reset_reply := _request(bridge, client, '{"command":"reset"}')
	if reset_reply.is_empty():
		return
	assert_eq(_sorted(reset_reply.keys()), ["state"], "reset reply over the wire")
	assert_eq(_sorted(reset_reply["state"].keys()), STATE_KEYS, "the PRD's 8 state keys")

	var step_reply := _request(bridge, client, '{"command":"step","action_id":%d}' % RIGHT)
	if step_reply.is_empty():
		return
	assert_eq(
		_sorted(step_reply.keys()), ["info", "state", "terminated", "truncated"], "step reply keys"
	)
	assert_eq(_sorted(step_reply["state"].keys()), STATE_KEYS, "step state keys")
	assert_eq(step_reply["state"]["moves_taken"], 1, "the move really happened")
	assert_false(step_reply["terminated"], "not terminated mid-level")


## THE task's second acceptance criterion: ONE message, TWO separate writes.
## The mid-way assertion that nothing has come back yet is the load-bearing
## part — it proves the bridge BUFFERED the fragment instead of mis-parsing it.
func test_tcp_message_split_across_two_writes() -> void:
	var bridge := _new_bridge(ROOM)
	var client = _connect(bridge)
	if client == null:
		return

	client.put_data('{"command":"step",'.to_utf8_buffer())
	for _i in range(10):
		bridge.poll()
		client.poll()
		OS.delay_msec(2)
	assert_eq(client.get_available_bytes(), 0, "half a message produces no reply")

	client.put_data(('"action_id":%d}\n' % RIGHT).to_utf8_buffer())
	var reply := _read_reply(bridge, client)
	if reply.is_empty():
		return
	assert_eq(
		_sorted(reply.keys()), ["info", "state", "terminated", "truncated"], "one clean reply"
	)
	assert_eq(reply["state"]["moves_taken"], 1, "the reassembled move was applied")
	assert_eq(reply["state"]["player_x"], 3, "and it was the RIGHT move, not garbage")


## THE task's third acceptance criterion, over the real transport: no error, no
## crash, no framing desync — the very next legal step still works.
func test_tcp_out_of_range_action_id_is_a_noop() -> void:
	var bridge := _new_bridge(ROOM)
	var client = _connect(bridge)
	if client == null:
		return

	var before := _request(bridge, client, '{"command":"reset"}')
	if before.is_empty():
		return

	var noop := _request(bridge, client, '{"command":"step","action_id":42}')
	if noop.is_empty():
		return
	assert_false(noop.has("error"), "out-of-range action_id is not an error")
	assert_eq(noop["state"], before["state"], "state unchanged over the wire")

	client.poll()
	assert_eq(client.get_status(), StreamPeerTCP.STATUS_CONNECTED, "connection survived")

	var legal := _request(bridge, client, '{"command":"step","action_id":%d}' % RIGHT)
	if legal.is_empty():
		return
	assert_eq(legal["state"]["moves_taken"], 1, "the next legal step still lands")


## "One connection at a time": the second client is hung up on, and the first
## one is unaffected.
func test_tcp_second_connection_is_refused() -> void:
	var bridge := _new_bridge(ROOM)
	var first = _connect(bridge)
	if first == null:
		return

	var second := StreamPeerTCP.new()
	_clients.append(second)
	second.connect_to_host("127.0.0.1", bridge.local_port())
	for _i in range(20):
		second.poll()
		bridge.poll()
		OS.delay_msec(2)
	second.put_data('{"command":"reset"}\n'.to_utf8_buffer())
	for _i in range(20):
		second.poll()
		bridge.poll()
		OS.delay_msec(2)
	# Hung up on, so it is not connected any more — and nothing was ever
	# answered on it. (Reading a closed socket is guarded: get_available_bytes()
	# on one logs an engine error, which would dirty the suite's stderr.)
	assert_ne(second.get_status(), StreamPeerTCP.STATUS_CONNECTED, "the second client is refused")
	if second.get_status() == StreamPeerTCP.STATUS_CONNECTED:
		assert_eq(second.get_available_bytes(), 0, "the second client is never served")

	var reply := _request(bridge, first, '{"command":"reset"}')
	if reply.is_empty():
		return
	assert_eq(_sorted(reply.keys()), ["state"], "the first client still round-trips")


func test_tcp_close_stops_the_server() -> void:
	var bridge := _new_bridge(ROOM)
	var client = _connect(bridge)
	if client == null:
		return
	client.put_data('{"command":"close"}\n'.to_utf8_buffer())
	# `_shutdown()` only calls get_tree().quit() when inside a tree — this
	# bridge never is, so the observable effect here is the socket teardown.
	var deadline := Time.get_ticks_msec() + PUMP_TIMEOUT_MS
	while bridge.is_listening() and Time.get_ticks_msec() < deadline:
		bridge.poll()
		client.poll()
		OS.delay_msec(2)
	assert_false(bridge.is_listening(), "close stops the server")
	assert_false(bridge.has_peer(), "close hangs up on the client")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


func _grid(rows: Array) -> String:
	var parts := PackedStringArray()
	for row in rows:
		parts.append(row)
	return "\n".join(parts)


func _args(values: Array) -> PackedStringArray:
	var args := PackedStringArray()
	for value in values:
		args.append(str(value))
	return args


func _bytes(text: String) -> PackedByteArray:
	return text.to_utf8_buffer()


## Dictionary.keys() order is insertion order; comparing it as a SET is what
## makes "exactly these keys" the assertion rather than "in this order".
func _sorted(values: Array) -> Array:
	var copy := values.duplicate()
	copy.sort()
	return copy


## A bridge with an inline fixture board injected (never `res://levels/`), or
## with no board at all when `rows` is empty. Freed by `after_each()`.
func _new_bridge(rows: Array = []) -> Node:
	var bridge = Bridge.new()
	_bridges.append(bridge)
	if not rows.is_empty():
		var board = Board.new()
		board.load_levels_from_texts([_grid(rows)])
		bridge.set_board(board)
	return bridge


## `handle_line()`'s response, asserted non-null so a case cannot silently pass
## on a missing reply.
func _response(bridge, line: String) -> Dictionary:
	var outcome: Dictionary = bridge.handle_line(line)
	var response = outcome.get("response")
	if typeof(response) != TYPE_DICTIONARY:
		assert_not_null(response, "expected a response for %s" % line)
		return {}
	return response


## Listens on the first free port at or above TEST_PORT_BASE. Never 8910.
func _listen(bridge) -> bool:
	for offset in range(PORT_SEARCH_LIMIT):
		if bridge.start_server(TEST_PORT_BASE + offset) == OK:
			return true
	assert_true(false, "could not bind any test port from %d" % TEST_PORT_BASE)
	return false


## Starts the bridge, connects a client, and pumps until the bridge has accepted
## it. Returns null (having already recorded a failure) if that never happens,
## so a caller can bail instead of hanging.
func _connect(bridge):
	if not _listen(bridge):
		return null
	var client := StreamPeerTCP.new()
	_clients.append(client)
	if client.connect_to_host("127.0.0.1", bridge.local_port()) != OK:
		assert_true(false, "connect_to_host failed")
		return null
	var deadline := Time.get_ticks_msec() + PUMP_TIMEOUT_MS
	while Time.get_ticks_msec() < deadline:
		client.poll()
		bridge.poll()
		if client.get_status() == StreamPeerTCP.STATUS_CONNECTED and bridge.has_peer():
			return client
		OS.delay_msec(2)
	assert_true(false, "the bridge never accepted the connection")
	return null


func _request(bridge, client, message: String) -> Dictionary:
	client.put_data((message + "\n").to_utf8_buffer())
	return _read_reply(bridge, client)


## Pumps both ends until one `\n`-terminated reply has arrived, then parses it.
## Returns {} (with a recorded failure) on timeout or unparseable output.
func _read_reply(bridge, client) -> Dictionary:
	var buffer := PackedByteArray()
	var deadline := Time.get_ticks_msec() + PUMP_TIMEOUT_MS
	while Time.get_ticks_msec() < deadline:
		bridge.poll()
		client.poll()
		# Only read a live socket: get_available_bytes() on a closed one logs an
		# engine error, which would dirty the suite's stderr.
		var available: int = (
			client.get_available_bytes()
			if client.get_status() == StreamPeerTCP.STATUS_CONNECTED
			else 0
		)
		if available > 0:
			var result: Array = client.get_data(available)
			if result.size() == 2 and int(result[0]) == OK:
				buffer.append_array(result[1])
		if buffer.size() > 0 and buffer[buffer.size() - 1] == 10:
			var text := buffer.get_string_from_utf8().strip_edges()
			var parsed = JSON.parse_string(text)
			if typeof(parsed) != TYPE_DICTIONARY:
				assert_true(false, "unparseable reply: %s" % text)
				return {}
			return parsed
		OS.delay_msec(2)
	assert_true(false, "no reply within %d ms" % PUMP_TIMEOUT_MS)
	return {}

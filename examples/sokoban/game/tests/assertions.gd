extends RefCounted
## Assertion helpers for the hand-written test runner (`res://tests/run_tests.gd`).
##
## Test scripts inherit these by path: `extends "res://tests/assertions.gd"`.
## Deliberately no `class_name` (no dependency on the editor's class registry)
## and deliberately NOT named `test_*.gd` (so the runner never discovers this
## file as a suite of its own).
##
## An assertion NEVER aborts the run: every helper only appends to `failures`.
## Do not add `assert()`, `push_error()`, `breakpoint` or `quit()` in here.

## Failure messages recorded during the current test method. The runner clears
## this before each method and reads it after.
var failures: PackedStringArray = PackedStringArray()

## Informational: how many assertions ran in the current test method.
var assert_count: int = 0


func assert_eq(actual, expected, msg: String = "") -> void:
	_record(_equal(actual, expected), msg, "expected %s, got %s" % [str(expected), str(actual)])


func assert_ne(actual, expected, msg: String = "") -> void:
	_record(
		not _equal(actual, expected),
		msg,
		"expected value != %s, got %s" % [str(expected), str(actual)]
	)


func assert_true(v, msg: String = "") -> void:
	# Strict: only the boolean `true` passes, not any truthy value.
	_record(typeof(v) == TYPE_BOOL and v, msg, "expected true, got %s" % str(v))


func assert_false(v, msg: String = "") -> void:
	_record(typeof(v) == TYPE_BOOL and not v, msg, "expected false, got %s" % str(v))


func assert_null(v, msg: String = "") -> void:
	_record(typeof(v) == TYPE_NIL, msg, "expected null, got %s" % str(v))


func assert_not_null(v, msg: String = "") -> void:
	_record(typeof(v) != TYPE_NIL, msg, "expected non-null, got null")


## Type-safe equality. GDScript raises on `==` between unrelated types (e.g.
## int vs String), which would spam engine errors from inside an assertion —
## mismatched types simply are not equal.
func _equal(a, b) -> bool:
	var type_a := typeof(a)
	var type_b := typeof(b)
	if type_a != type_b:
		var numeric := [TYPE_INT, TYPE_FLOAT]
		if not (numeric.has(type_a) and numeric.has(type_b)):
			return false
	return a == b


func _record(ok: bool, msg: String, detail: String) -> void:
	assert_count += 1
	if ok:
		return
	var text := detail if msg.is_empty() else "%s (%s)" % [msg, detail]
	# Keep failures single-line: the runner prints one line per case.
	failures.append(text.replace("\n", " ").replace("\r", " "))

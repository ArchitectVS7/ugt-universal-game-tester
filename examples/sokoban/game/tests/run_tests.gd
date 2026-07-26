extends SceneTree
## Hand-written headless test runner. Run as:
##   godot4 --headless --path . -s tests/run_tests.gd
##
## Contract (do not drift — every later task's Gate is judged by it):
##  - discovers every `res://tests/test_*.gd`, sorted by filename
##  - instantiates each and calls every `test_*` method in DECLARATION order,
##    honouring optional `before_each()` / `after_each()`
##  - assert helpers live in `res://tests/assertions.gd`; an assert records a
##    failure, it never aborts the run
##  - prints one line per case: `PASS <script>::<method>` or
##    `FAIL <script>::<method> — <msg>`
##  - prints a final `N passed, M failed` line
##  - exits 0 IF AND ONLY IF M == 0 and N > 0 (zero discovered tests exits 1)
##
## Deliberately not GUT or any other third-party addon — see PRD "Verification".

const TESTS_DIR := "res://tests"

## Safety net: if `_initialize()` is aborted by a fatal engine error the tree
## would otherwise idle forever and hang the Gate. See `_process()`.
const WATCHDOG_SECONDS := 60.0

var _finished := false
var _elapsed := 0.0


func _initialize() -> void:
	var passed := 0
	var failed := 0

	for file_name in _discover_test_scripts():
		var path := "%s/%s" % [TESTS_DIR, file_name]
		var script = load(path)
		# A script with a parse error still loads as a non-null GDScript that
		# cannot be instantiated — calling new() on it aborts this function.
		if script == null or not (script is GDScript) or not script.can_instantiate():
			failed += 1
			print("FAIL %s::<load> — could not load script %s (parse error?)" % [file_name, path])
			continue

		var instance = script.new()
		if instance == null:
			failed += 1
			print("FAIL %s::<new> — could not instantiate script" % file_name)
			continue

		for method_name in _test_methods(script):
			if _run_case(instance, method_name):
				passed += 1
				print("PASS %s::%s" % [file_name, method_name])
			else:
				failed += 1
				print("FAIL %s::%s — %s" % [file_name, method_name, _failure_message(instance)])

		if instance is Node:
			instance.free()

	print("%d passed, %d failed" % [passed, failed])

	# Exit 0 only when nothing failed AND something actually ran: a run that
	# discovers zero tests must be red, never a silent green.
	var exit_code := 0 if (failed == 0 and passed > 0) else 1
	_finished = true
	quit(exit_code)


## Only ever reached if `_initialize()` did not run to its `quit()` — i.e. a
## fatal engine error aborted it. Report red rather than hanging forever.
func _process(delta: float) -> bool:
	if _finished:
		return true
	_elapsed += delta
	if _elapsed >= WATCHDOG_SECONDS:
		print("FAIL <runner>::<watchdog> — run aborted before finishing")
		print("0 passed, 1 failed")
		_finished = true
		quit(1)
	return false


## Every `test_*.gd` directly under res://tests, sorted by filename.
func _discover_test_scripts() -> PackedStringArray:
	var found := PackedStringArray()
	var dir := DirAccess.open(TESTS_DIR)
	if dir == null:
		push_error("could not open %s" % TESTS_DIR)
		return found
	for file_name in dir.get_files():
		if file_name.begins_with("test_") and file_name.ends_with(".gd"):
			found.append(file_name)
	found.sort()
	return found


## `test_*` methods in declaration order, deduplicated (an overridden method
## can be reported twice) and deliberately NOT sorted.
func _test_methods(script: Script) -> PackedStringArray:
	var methods := PackedStringArray()
	for method in script.get_script_method_list():
		var method_name: String = method.get("name", "")
		if method_name.begins_with("test_") and not methods.has(method_name):
			methods.append(method_name)
	return methods


## Runs one case; returns true when it recorded no assertion failures.
func _run_case(instance, method_name: String) -> bool:
	if instance.get("failures") != null:
		instance.failures.clear()
	if instance.has_method("before_each"):
		instance.call("before_each")
	instance.call(method_name)
	if instance.has_method("after_each"):
		instance.call("after_each")
	return _failure_count(instance) == 0


func _failure_count(instance) -> int:
	var failures = instance.get("failures")
	if failures == null:
		return 0
	return failures.size()


func _failure_message(instance) -> String:
	var failures = instance.get("failures")
	if failures == null or failures.size() == 0:
		return "failed with no message"
	var message: String = failures[0]
	if failures.size() > 1:
		message += " (+%d more)" % (failures.size() - 1)
	return message

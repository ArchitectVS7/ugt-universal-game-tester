extends "res://tests/assertions.gd"
## Trivially passing test — proves the runner discovers, instantiates and
## reports. Keep this at exactly ONE test method with ONE assertion: it was the
## whole of T-002's `1 passed, 0 failed` gate line, and it stays minimal so it
## can never be the reason a later task's suite goes red. The Gate itself is
## exit 0 (`M == 0 and N > 0`), not a pinned total — real suites are added by
## T-003 onward.


func test_sanity_passes() -> void:
	assert_true(true, "sanity runner is alive")

extends "res://tests/assertions.gd"
## Trivially passing test — proves the runner discovers, instantiates and
## reports. Keep this at exactly ONE test method with ONE assertion: the
## project Gate pins the runner's output line `1 passed, 0 failed`.


func test_sanity_passes() -> void:
	assert_true(true, "sanity runner is alive")

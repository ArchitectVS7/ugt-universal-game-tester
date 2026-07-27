import json
import os
import time
from ugt.utils.formula_evaluator import SafeEvaluator
from ugt.utils.feature_map import FeatureMap, FeatureMapError

MAX_TASKS_PER_TURN = 3


def verify_game(config, feature_map, max_turns=50, output_path=None):
    """
    Phase 1: Correctness verification. Drives the game through each feature in the
    feature map, evaluates state-delta assertions, and produces coverage-report.json.

    Uses the adapter directly (not UniversalGameEnv) — no RL overhead needed here.
    Simulation/subprocess games are fully supported. Browser games work if their
    action space is enumerated in the config (press_key flows are a future extension).

    Returns the coverage report dict.
    """
    from ugt.adapters.subprocess import SubprocessAdapter
    from ugt.adapters.playwright import PlaywrightAdapter

    if config.engine_type == "browser":
        adapter = PlaywrightAdapter(config)
    elif config.engine_type == "simulation":
        adapter = SubprocessAdapter(config)
    else:
        raise ValueError(f"Unknown engine type: '{config.engine_type}'")

    project_dir = os.path.dirname(os.path.abspath(config.filepath))
    results_dir = os.path.join(project_dir, "results")
    os.makedirs(results_dir, exist_ok=True)

    if output_path is None:
        output_path = os.path.join(results_dir, "coverage-report.json")

    idle_action = config.engine_idle_action
    features = feature_map.features
    coverage = {f.id: "not_reached" for f in features}
    details = {}
    not_reached_reasons = {}

    print(f"[*] Phase 1 — Verify: {len(features)} features to test")
    print(f"[*] Connecting to game ({config.engine_type})...")

    adapter.connect()
    current_state = adapter.reset()
    print(f"[*] Connected. Starting verification run (max_turns={max_turns})...")

    start_time = time.time()

    for turn in range(1, max_turns + 1):
        # Build task list: untested features whose precondition is met, by priority
        pending = [f for f in features if coverage[f.id] not in ("passed", "failed")]
        if not pending:
            print(f"[+] All features resolved after turn {turn - 1}.")
            break

        tasks_this_turn = []
        for feature in pending:
            if len(tasks_this_turn) >= MAX_TASKS_PER_TURN:
                break
            if feature.precondition:
                try:
                    met = SafeEvaluator(feature.precondition, strict=True).evaluate(current_state)
                    if not met:
                        continue
                except Exception:
                    not_reached_reasons[feature.id] = "precondition_error"
                    continue
            tasks_this_turn.append(feature)

        if not tasks_this_turn:
            # No preconditions met — step the game's declared idle action to advance
            # state. This was hardcoded to 0 on the assumption that action 0 is a
            # conventional no-op/wait; the assumption is wrong in the direction that
            # matters, because a no-op that changes NOTHING cannot tick a world
            # forward, and every feature with a slow precondition then reports
            # NOT_REACHED no matter how large max_turns is. Which action advances a
            # given game is game knowledge, so it is declared in that game's config
            # (engine.idle_action) rather than guessed here — M1 either way: the
            # framework still contains no game-specific advance logic.
            try:
                current_state, terminated, truncated, _ = adapter.step(idle_action)
                if terminated or truncated:
                    current_state = adapter.reset()
            except Exception:
                pass
            continue

        for feature in tasks_this_turn:
            coverage[feature.id] = "running"
            before_state = _deep_copy(current_state)

            try:
                action_ids = feature_map.action_ids_for_feature(feature, config)
            except FeatureMapError as e:
                coverage[feature.id] = "failed"
                details[feature.id] = {
                    "status": "FAILED",
                    "error": str(e),
                    "before": before_state,
                    "after": before_state,
                }
                print(f"  [FAIL] {feature.id}: {e}")
                continue

            try:
                after_state = before_state
                terminated = truncated = False
                for action_id in action_ids:
                    after_state, terminated, truncated, _ = adapter.step(action_id)
                    current_state = after_state

                # Evaluate each assertion
                failed_assertions = []
                for assertion_expr in feature.assertions:
                    try:
                        result = SafeEvaluator(assertion_expr, strict=True).evaluate(
                            after_state, extra_context={"before": before_state}
                        )
                        if not result:
                            failed_assertions.append(assertion_expr)
                    except Exception as eval_err:
                        failed_assertions.append(f"{assertion_expr} [eval error: {eval_err}]")

                delta = _compute_delta(before_state, after_state)

                if not failed_assertions:
                    coverage[feature.id] = "passed"
                    details[feature.id] = {
                        "status": "PASSED",
                        "before": before_state,
                        "after": after_state,
                        "delta": delta,
                    }
                    print(f"  [PASS] {feature.id}")
                else:
                    coverage[feature.id] = "failed"
                    details[feature.id] = {
                        "status": "FAILED",
                        "error": f"Assertion failed: {failed_assertions[0]}",
                        "all_failed": failed_assertions,
                        "before": before_state,
                        "after": after_state,
                        "delta": delta,
                    }
                    print(f"  [FAIL] {feature.id}: {failed_assertions[0]}")

                if terminated or truncated:
                    current_state = adapter.reset()

            except Exception as err:
                coverage[feature.id] = "failed"
                details[feature.id] = {
                    "status": "FAILED",
                    "error": f"Runtime error: {err}",
                    "before": before_state,
                    "after": current_state,
                }
                print(f"  [FAIL] {feature.id}: runtime error — {err}")
                # Attempt recovery
                try:
                    current_state = adapter.reset()
                except Exception:
                    pass

    adapter.close()
    duration = round(time.time() - start_time, 1)

    # Final status mapping: "running" → "not_reached" (interrupted), "not_reached" stays.
    #
    # The guard is `fid not in details` — it fills in the features the run never
    # resolved, and must NOT touch the ones it did. It used to read
    # `coverage[fid] not in details`, comparing a STATUS STRING ("passed") against a
    # dict keyed by FEATURE ID, so it was always true: every rich entry written above
    # — before, after, delta, the failed-assertion list — was overwritten with a bare
    # {"status": ...} on the way out. A whole run's evidence reached the report as
    # nothing but a verdict. Found by a game repo reading its own coverage-report.json
    # and finding 9 features and no deltas (SpacerQuest T-1604a, finding F6).
    status_map = {"passed": "PASSED", "failed": "FAILED", "not_reached": "NOT_REACHED", "running": "NOT_REACHED"}
    for fid in coverage:
        if fid not in details:
            mapped_status = status_map.get(coverage[fid], "NOT_REACHED")
            if mapped_status == "NOT_REACHED":
                details[fid] = {
                    "status": "NOT_REACHED",
                    "not_reached_reason": not_reached_reasons.get(fid, "turn_budget_exceeded"),
                }
            else:
                details[fid] = {"status": mapped_status}

    passed = sum(1 for v in coverage.values() if v == "passed")
    failed = sum(1 for v in coverage.values() if v == "failed")
    not_reached = sum(1 for v in coverage.values() if v in ("not_reached", "running"))
    not_reached_precondition_error = sum(
        1 for fid, v in coverage.items()
        if v in ("not_reached", "running") and not_reached_reasons.get(fid) == "precondition_error"
    )
    not_reached_turn_budget = not_reached - not_reached_precondition_error
    total = len(features)
    coverage_pct = round((passed / total) * 100, 1) if total > 0 else 0.0

    report = {
        "game": config.project_name,
        "total_features": total,
        "passed": passed,
        "failed": failed,
        "not_reached": not_reached,
        "not_reached_precondition_error": not_reached_precondition_error,
        "not_reached_turn_budget": not_reached_turn_budget,
        "coverage_pct": coverage_pct,
        "duration_seconds": duration,
        "results": {fid: details[fid] for fid in [f.id for f in features]},
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\n[+] Verification complete in {duration}s")
    print(f"[+] Coverage: {passed}/{total} PASSED ({coverage_pct}%)  |  {failed} FAILED  |  {not_reached} NOT REACHED")
    if not_reached_precondition_error > 0:
        print(f"    ({not_reached_precondition_error} precondition_error, {not_reached_turn_budget} turn_budget_exceeded)")
    if failed > 0:
        print(f"[!] Failed features:")
        for fid, d in details.items():
            if d.get("status") == "FAILED":
                print(f"    - {fid}: {d.get('error', '')}")
    print(f"[+] Report: {output_path}")

    return report


def _deep_copy(state):
    """JSON-round-trip copy of state dict — safe for nested dicts with primitives."""
    try:
        return json.loads(json.dumps(state, default=str))
    except Exception:
        return dict(state)


def _compute_delta(before, after, prefix=""):
    """Compute a flat dict of changed scalar values between two nested state dicts."""
    delta = {}
    if not isinstance(before, dict) or not isinstance(after, dict):
        return delta
    all_keys = set(before.keys()) | set(after.keys())
    for key in all_keys:
        full_key = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        b_val = before.get(key)
        a_val = after.get(key)
        if isinstance(b_val, dict) or isinstance(a_val, dict):
            delta.update(_compute_delta(b_val or {}, a_val or {}, prefix=full_key))
        elif b_val != a_val:
            if isinstance(b_val, (int, float)) and isinstance(a_val, (int, float)):
                diff = a_val - b_val
                delta[full_key] = f"{'+' if diff > 0 else ''}{diff}"
            else:
                delta[full_key] = f"{b_val!r} → {a_val!r}"
    return delta

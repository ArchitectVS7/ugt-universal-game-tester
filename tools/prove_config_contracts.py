#!/usr/bin/env python3
"""Proof harness for UgtConfig and FeatureMap — the two loaders (O-26).

    python3 tools/prove_config_contracts.py

There is no pytest in this repo. These two classes are the front door for every
game-specific file a user authors, and until 2026-07-27 neither had any unit coverage
(recorded in the 2026-07-25 repo review and carried unclosed).

Built to LESSONS §A M11 (red parts). One known-good config is defined once and must pass
100%. Every red part is that same config with **exactly one** defect injected, and must
fail *that* defect's check — a red part that fails for a second reason as well would mean
the checks are entangled and their individual verdicts mean less than they look.

Re-run after touching ugt/utils/config_parser.py or ugt/utils/feature_map.py.
"""
from __future__ import annotations

import copy
import os
import sys
import tempfile

import yaml

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from ugt.utils.config_parser import UgtConfig, ConfigError  # noqa: E402
from ugt.utils.feature_map import FeatureMap, FeatureMapError  # noqa: E402
from ugt.core.trial import GateRunner  # noqa: E402

gate = GateRunner()


def check(ok, label, detail=""):
    return gate.ck(label, ok, detail)


# ── the known-good part ──────────────────────────────────────────────────────
GOOD_CONFIG = {
    "project": {"name": "Prover Game", "version": "0.1.0"},
    "engine": {"type": "simulation", "entry": "python3 game.py"},
    "observation_space": {
        "type": "box", "shape": 2,
        "mappings": [{"path": "credits"}, {"path": "hp"}],
    },
    "action_space": {
        "type": "discrete", "size": 2,
        "actions": {0: {"name": "wait"}, 1: {"name": "buy"}},
    },
}

GOOD_FEATURE_MAP = {
    "features": [
        {"id": "f_minor", "description": "a minor one", "action": "wait",
         "assertion": "state.credits == before.credits", "priority": "minor"},
        {"id": "f_crit", "description": "a critical one", "action": ["buy", "wait"],
         "assertion": ["state.credits < before.credits"], "priority": "critical",
         "precondition": "state.credits > 0", "rng_controlled": True},
    ]
}


def write(obj):
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as fh:
        yaml.safe_dump(obj, fh)
    return path


def load_config(obj):
    """Returns (ok, detail). ok=True means it LOADED."""
    p = write(obj)
    try:
        return True, UgtConfig(p)
    except ConfigError as e:
        return False, str(e)
    finally:
        os.unlink(p)


def red_config(mutate, label, expect_substr):
    """One red part: the good config with exactly one defect."""
    bad = copy.deepcopy(GOOD_CONFIG)
    mutate(bad)
    ok, detail = load_config(bad)
    if ok:
        return check(False, f"red part rejected: {label}", "IT LOADED — the defect was not caught")
    hit = expect_substr.lower() in str(detail).lower()
    return check(hit, f"red part rejected: {label}",
                 f"{'names its own defect' if hit else 'WRONG ERROR'} — {str(detail)[:90]}")


def load_fmap(obj):
    p = write(obj)
    try:
        return True, FeatureMap(p)
    except FeatureMapError as e:
        return False, str(e)
    finally:
        os.unlink(p)


def red_fmap(mutate, label, expect_substr):
    bad = copy.deepcopy(GOOD_FEATURE_MAP)
    mutate(bad)
    ok, detail = load_fmap(bad)
    if ok:
        return check(False, f"red part rejected: {label}", "IT LOADED — the defect was not caught")
    hit = expect_substr.lower() in str(detail).lower()
    return check(hit, f"red part rejected: {label}",
                 f"{'names its own defect' if hit else 'WRONG ERROR'} — {str(detail)[:90]}")


def main() -> int:
    print("Proving UgtConfig and FeatureMap — the two loaders\n")

    # ═══ UgtConfig ═══════════════════════════════════════════════════════════
    print("  -- UgtConfig: the good part must pass 100% --")
    ok, cfg = load_config(GOOD_CONFIG)
    check(ok, "the known-good config loads", "" if ok else str(cfg))
    if ok:
        check(cfg.project_name == "Prover Game", "project_name")
        check(cfg.engine_type == "simulation", "engine_type")
        check(cfg.engine_entry == "python3 game.py", "engine_entry")
        check(cfg.obs_shape == 2 and len(cfg.obs_mappings) == 2, "obs shape + mappings")
        check(cfg.action_size == 2 and len(cfg.action_mappings) == 2, "action size + mappings")
        check(cfg.engine_reset_command is None, "absent optional reads None, not KeyError")
        check(cfg.engine_idle_action == 0, "engine.idle_action defaults to 0 when undeclared",
              "0 was the hardcoded value before the key existed; the default must preserve it")

    print("\n  -- UgtConfig: engine.idle_action is read when declared --")
    idle = copy.deepcopy(GOOD_CONFIG)
    idle["engine"]["idle_action"] = 1
    ok, c3 = load_config(idle)
    check(ok, "a declared engine.idle_action loads", "" if ok else str(c3))
    if ok:
        check(c3.engine_idle_action == 1, "engine.idle_action reads the declared id")

    print("\n  -- UgtConfig: custom needs no entry (the documented exception) --")
    custom = copy.deepcopy(GOOD_CONFIG)
    custom["engine"] = {"type": "custom"}
    ok, c2 = load_config(custom)
    check(ok, "engine.type=custom loads WITHOUT engine.entry",
          "" if ok else str(c2))
    if ok:
        check(c2.engine_entry is None, "custom: engine_entry reads None")

    print("\n  -- UgtConfig red parts: one defect each --")
    red_config(lambda c: c["project"].pop("name"),               "missing project.name", "project.name")
    red_config(lambda c: c.pop("engine"),                        "missing engine section", "engine")
    red_config(lambda c: c["engine"].__setitem__("type", "wat"), "unknown engine.type", "engine.type")
    red_config(lambda c: c["engine"].pop("entry"),               "non-custom missing engine.entry", "engine.entry")
    red_config(lambda c: c.pop("observation_space"),             "missing observation_space", "observation_space")
    red_config(lambda c: c["observation_space"].__setitem__("type", "dict"), "obs type not box", "box")
    red_config(lambda c: c["observation_space"].__setitem__("shape", "2"),   "obs shape not int", "integer")
    red_config(lambda c: c["observation_space"].__setitem__("mappings", {}), "mappings not a list", "list")
    red_config(lambda c: c["observation_space"].__setitem__("shape", 3),     "shape != len(mappings)", "does not match")
    red_config(lambda c: c.pop("action_space"),                  "missing action_space", "action_space")
    red_config(lambda c: c["action_space"].__setitem__("type", "box"),  "action type not discrete", "discrete")
    red_config(lambda c: c["action_space"].__setitem__("size", None),   "action size not int", "integer")
    red_config(lambda c: c["action_space"].__setitem__("size", 5),      "size != len(actions)", "does not match")
    # idle_action names an action the tier will actually STEP, so a wrong one is a
    # silent no-op run rather than an error at use — it has to be rejected at load.
    red_config(lambda c: c["engine"].__setitem__("idle_action", "wait"), "idle_action not an int", "idle_action")
    red_config(lambda c: c["engine"].__setitem__("idle_action", True),   "idle_action is a bool", "idle_action")
    red_config(lambda c: c["engine"].__setitem__("idle_action", 2),      "idle_action outside the action space", "outside the action space")
    red_config(lambda c: c["engine"].__setitem__("idle_action", -1),     "idle_action negative", "outside the action space")

    print("\n  -- UgtConfig: file-level failures --")
    try:
        UgtConfig("/nonexistent/path/to/ugt.config.yaml")
        check(False, "a missing file raises ConfigError")
    except ConfigError as e:
        check("not found" in str(e).lower(), "a missing file raises ConfigError", str(e)[:70])
    p = write(["not", "a", "mapping"])
    try:
        UgtConfig(p); check(False, "a non-mapping YAML raises ConfigError")
    except ConfigError as e:
        check("dictionary" in str(e).lower(), "a non-mapping YAML raises ConfigError", str(e)[:70])
    finally:
        os.unlink(p)

    # ═══ FeatureMap ══════════════════════════════════════════════════════════
    print("\n  -- FeatureMap: the good part must pass 100% --")
    ok, fm = load_fmap(GOOD_FEATURE_MAP)
    check(ok, "the known-good feature map loads", "" if ok else str(fm))
    if ok:
        feats = fm.features
        check(len(feats) == 2, "both features parsed")
        check(feats[0].id == "f_crit", "sorted CRITICAL first, not definition order",
              f"order: {[f.id for f in feats]}")
        check(feats[0].action_names == ["buy", "wait"], "list-valued action preserved in order")
        check(feats[1].action_names == ["wait"], "scalar action normalized to a 1-item list")
        check(feats[1].assertions == ["state.credits == before.credits"],
              "scalar assertion normalized to a list")
        check(feats[0].rng_controlled is True and feats[1].rng_controlled is False,
              "rng_controlled defaults False and is read when present")
        check(feats[0].precondition == "state.credits > 0" and feats[1].precondition is None,
              "precondition is optional and reads None when absent")
        check(fm.features is not fm._features, "features property returns a COPY",
              "a caller must not be able to mutate the loader's list")

        _, cfg2 = load_config(GOOD_CONFIG)
        ids = fm.action_ids_for_feature(feats[0], cfg2)
        check(ids == [1, 0], "action names resolve to config ids in order", f"buy,wait -> {ids}")
        bad_feat = copy.deepcopy(feats[0]); bad_feat.action_names = ["teleport"]
        try:
            fm.action_ids_for_feature(bad_feat, cfg2)
            check(False, "an action name absent from the config raises")
        except FeatureMapError as e:
            check("teleport" in str(e) and "Available" in str(e),
                  "an unknown action name raises AND lists what IS available",
                  "an error that does not say what was valid costs a debugging round")

    print("\n  -- FeatureMap red parts: one defect each --")
    red_fmap(lambda d: d["features"][0].pop("id"),                  "feature missing id", "missing required field 'id'")
    red_fmap(lambda d: d["features"][0].pop("action"),              "feature missing action", "missing required field 'action'")
    red_fmap(lambda d: d["features"][0].pop("assertion"),           "feature missing assertion", "missing required field 'assertion'")
    red_fmap(lambda d: d["features"][0].__setitem__("priority", "urgent"), "unknown priority", "unknown priority")
    red_fmap(lambda d: d["features"][0].__setitem__("action", 5),   "action is not str/list", "must be a string or list")
    red_fmap(lambda d: d["features"][0].__setitem__("assertion", 5), "assertion is not str/list", "must be a string or list")
    red_fmap(lambda d: d.__setitem__("features", {"a": 1}),         "features is not a list", "must be a list")
    red_fmap(lambda d: d["features"].__setitem__(0, "just a string"), "feature entry not a mapping", "must be a mapping")

    print("\n  -- FeatureMap: file-level failures --")
    try:
        FeatureMap("/nonexistent/feature-map.yaml")
        check(False, "a missing file raises FeatureMapError")
    except FeatureMapError as e:
        check("not found" in str(e).lower(), "a missing file raises FeatureMapError", str(e)[:70])
    p = write("just a scalar")
    try:
        FeatureMap(p); check(False, "a non-mapping YAML raises FeatureMapError")
    except FeatureMapError as e:
        check("mapping" in str(e).lower(), "a non-mapping YAML raises FeatureMapError", str(e)[:70])
    finally:
        os.unlink(p)

    print("\n  -- an empty map is legal, and must not pretend otherwise --")
    ok, fm2 = load_fmap({"features": []})
    check(ok and fm2.features == [], "zero features loads and yields zero features",
          "a verify run over an empty map should report NOTHING covered, not pass")

    return gate.finish(
        "CONFIG-CONTRACTS PROOF",
        "One known-good config and one known-good feature map pass in full; every red part "
        "carries exactly one defect and is rejected by the check that owns it, naming that "
        "defect in its message; the documented custom-needs-no-entry exception is pinned; "
        "and both loaders fail loudly on a missing or malformed file.")


if __name__ == "__main__":
    sys.exit(main())

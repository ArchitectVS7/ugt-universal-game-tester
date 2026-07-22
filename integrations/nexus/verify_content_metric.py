#!/usr/bin/env python3
"""
Fail-proof for the progressive-content engagement metric (`_RevealTracker`).

WHY THIS EXISTS: a metric that has only ever been seen green on one happy run is not
evidence of anything (LESSONS.md O2 — a check that cannot fail is prohibited). This
drives the metric offline against SYNTHETIC state/action sequences shaped exactly like
NEXUS's live `player-state` payload, so both the ENGAGED and the IGNORED verdicts are
demonstrated, plus every edge the design promises (pending, optional, no_reveals,
starting kit, self-credit). No server, no LLM, no cost — replayed sequences, not a
live run.

It also validates NEXUS's OWN `playtest.revealed_content` config, because it reads the
groups straight out of `integrations/nexus/ugt.config.yaml` rather than defining its
own. A typo'd path or a broken optional_ids list fails here.

Run from the UGT repo root:
    python3 integrations/nexus/verify_content_metric.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from ugt.core.playtester import _RevealTracker  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

CONFIG_PATH = "integrations/nexus/ugt.config.yaml"

PASS: list[str] = []
FAIL: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))


def state(commands: list[str], missions: list[dict]) -> dict:
    """A NEXUS-shaped state slice: only the two fields the groups name."""
    return {"unlockedCommands": list(commands), "missions": [dict(m) for m in missions]}


def mission(mid: str, status: str = "active", done: int = 0, total: int = 3) -> dict:
    return {"missionId": mid, "status": status,
            "objectivesCompleted": done, "objectivesTotal": total}


def drive(cfg_playtest, script, baseline):
    """Replay (action, post_state) pairs through the tracker exactly as the playtest
    loop does: note_action BEFORE the step, observe AFTER it."""
    t = _RevealTracker(cfg_playtest)
    t.rebaseline(baseline)
    for i, (action, post) in enumerate(script, start=1):
        t.note_action(i, action)
        t.observe(post, i)
    return t.report(len(script))


def main() -> int:
    cfg = UgtConfig(CONFIG_PATH)
    pt = cfg.data.get("playtest") or {}

    print("=== Config wiring ===")
    groups = {g["name"]: g for g in _RevealTracker(pt).groups}
    check("NEXUS declares both revealed_content groups",
          set(groups) == {"commands", "missions"}, str(sorted(groups)))
    check("commands group points at unlockedCommands with the invoke rule",
          groups.get("commands", {}).get("path") == "unlockedCommands"
          and groups["commands"]["engage"] == {"invoke"})
    check("missions group is keyed by missionId with the progress rule",
          groups.get("missions", {}).get("id_field") == "missionId"
          and groups["missions"]["engage"] == {"progress"})
    check("the 5 shipped side quests are marked optional",
          groups.get("missions", {}).get("optional_ids") == {
              "undercity_intro", "carnival_chaos", "data_broker_job",
              "ghost_protocol_test", "foundation_research"})

    base_cmds = ["scan", "connect", "ls", "cat", "exploit"]
    baseline = state(base_cmds, [])

    # ── 1. THE FAILING CASE: content revealed, pilot ignores it ─────────────────
    # A story mission goes live at step 1 and a new verb is granted at step 2; the pilot
    # then spends the rest of the run doing the recon it already knew how to do.
    print("\n=== 1. Pilot IGNORES newly revealed content (the case that must FAIL) ===")
    m_live = [mission("the_breadcrumb")]
    ignored = [("accept the_breadcrumb", state(base_cmds, m_live))]
    ignored.append(("status", state(base_cmds + ["traceroute"], m_live)))
    ignored += [("ls", state(base_cmds + ["traceroute"], m_live)) for _ in range(30)]
    r = drive(pt, ignored, baseline)
    check("status is 'ignored'", r["status"] == "ignored", r["status"])
    check("denominator is visible and non-empty", r["required_scored"] == 2,
          f"required_scored={r['required_scored']}")
    check("engaged = 0", r["required_engaged"] == 0)
    check("engagement_rate = 0.0", r["engagement_rate"] == 0.0)
    missed = sorted(i["item"] for g in r["groups"].values() for i in g["items"]
                    if i["status"] == "missed")
    check("both ignored items are named in the report",
          missed == ["the_breadcrumb", "traceroute"], str(missed))

    # ── 2. The passing case: pilot follows the quest line AND tries the new verb ──
    print("\n=== 2. Pilot ENGAGES both (the case that must PASS) ===")
    engaged = [("accept the_breadcrumb", state(base_cmds, m_live))]
    engaged.append(("status", state(base_cmds + ["traceroute"], m_live)))
    engaged.append(("traceroute 10.0.0.1", state(base_cmds + ["traceroute"], m_live)))
    engaged.append(("cat /home/j/notes.txt",
                    state(base_cmds + ["traceroute"], [mission("the_breadcrumb", done=1)])))
    engaged += [("ls", state(base_cmds + ["traceroute"],
                             [mission("the_breadcrumb", done=1)])) for _ in range(30)]
    r = drive(pt, engaged, baseline)
    check("status is 'engaged'", r["status"] == "engaged", r["status"])
    check("2/2 engaged on the same denominator",
          (r["required_engaged"], r["required_scored"]) == (2, 2))
    rules = {i["item"]: i["engaged_by_rule"] for g in r["groups"].values() for i in g["items"]}
    check("the verb was credited by 'invoke'", rules.get("traceroute") == "invoke")
    check("the quest line was credited by 'progress' (objectivesCompleted 0->1)",
          rules.get("the_breadcrumb") == "progress")

    # ── 3. Non-vacuity: nothing revealed must NOT read as a perfect score ────────
    print("\n=== 3. Nothing revealed -> 'no_reveals', never 100% (O2) ===")
    r = drive(pt, [("ls", baseline) for _ in range(25)], baseline)
    check("status is 'no_reveals'", r["status"] == "no_reveals", r["status"])
    check("rate is null, not 1.0", r["engagement_rate"] is None, str(r["engagement_rate"]))
    check("denominator is reported as empty", r["required_scored"] == 0)
    check("the starting kit is reported but not scored",
          r["groups"]["commands"]["revealed_at_start"] == len(base_cmds)
          and r["groups"]["commands"]["revealed_during_run"] == 0)

    # ── 4. Optional (side quest) content never counts as failure ─────────────────
    print("\n=== 4. Side quests are optional (owner's rule) ===")
    side = [mission("undercity_intro")]
    r = drive(pt, [("accept undercity_intro", state(base_cmds, side))]
              + [("ls", state(base_cmds, side)) for _ in range(30)], baseline)
    check("an ignored SIDE quest leaves the denominator empty",
          r["required_scored"] == 0 and r["status"] == "no_reveals", r["status"])
    check("it is still reported as optional_revealed",
          r["groups"]["missions"]["optional_revealed"] == 1)
    story_and_side = [("accept undercity_intro", state(base_cmds, side))]
    story_and_side.append(("accept the_breadcrumb",
                           state(base_cmds, side + [mission("the_breadcrumb")])))
    story_and_side += [("ls", state(base_cmds, side + [mission("the_breadcrumb")]))
                       for _ in range(30)]
    r = drive(pt, story_and_side, baseline)
    check("a STORY quest ignored alongside it still fails",
          r["status"] == "ignored" and r["required_scored"] == 1,
          f"{r['status']} scored={r['required_scored']}")

    # ── 5. Window semantics ─────────────────────────────────────────────────────
    print("\n=== 5. Window: late reveals are PENDING, late engagement does not count ===")
    late = [("ls", baseline) for _ in range(5)]
    late.append(("status", state(base_cmds + ["traceroute"], [])))
    late += [("ls", state(base_cmds + ["traceroute"], [])) for _ in range(3)]
    r = drive(pt, late, baseline)
    check("a reveal inside the last window is PENDING, not missed",
          r["pending_at_run_end"] == 1 and r["required_scored"] == 0,
          f"pending={r['pending_at_run_end']} scored={r['required_scored']}")
    check("pending does not manufacture a rate", r["engagement_rate"] is None)

    stale = [("status", state(base_cmds + ["traceroute"], []))]
    stale += [("ls", state(base_cmds + ["traceroute"], [])) for _ in range(20)]
    stale.append(("traceroute 10.0.0.1", state(base_cmds + ["traceroute"], [])))
    stale += [("ls", state(base_cmds + ["traceroute"], [])) for _ in range(5)]
    r = drive(pt, stale, baseline)
    check("engagement 21 steps after a 12-step-window reveal does NOT count",
          r["status"] == "ignored" and r["required_engaged"] == 0, r["status"])

    # ── 6. Revelation must not credit itself ────────────────────────────────────
    print("\n=== 6. The action that reveals an item cannot engage it ===")
    self_credit = [("traceroute 10.0.0.1", state(base_cmds + ["traceroute"], []))]
    self_credit += [("ls", state(base_cmds + ["traceroute"], [])) for _ in range(20)]
    r = drive(pt, self_credit, baseline)
    check("a verb typed in the same step it appears is not self-credited",
          r["required_engaged"] == 0 and r["required_scored"] == 1, str(r["status"]))

    # ── 7. Episode reset re-baselines ───────────────────────────────────────────
    print("\n=== 7. An episode reset re-baselines instead of re-revealing ===")
    t = _RevealTracker(pt)
    t.rebaseline(state(base_cmds + ["traceroute"], []))
    for i in range(1, 4):
        t.note_action(i, "ls")
        t.observe(state(base_cmds + ["traceroute"], []), i)
    t.note_reset(state(base_cmds, []))          # reset drops the granted verb
    for i in range(4, 20):
        t.note_action(i, "ls")
        t.observe(state(base_cmds, []), i)
    r = t.report(19)
    check("post-reset state is the new starting kit, not a wave of reveals",
          r["status"] == "no_reveals" and r["required_scored"] == 0, r["status"])

    # ── 8. A game with no declaration is inert, not silently perfect ────────────
    print("\n=== 8. Unconfigured games report 'not_configured' ===")
    r = drive({}, [("x", {}) for _ in range(3)], {})
    check("status is 'not_configured'", r["status"] == "not_configured", r["status"])
    check("no rate is invented", "engagement_rate" not in r)

    total = len(PASS) + len(FAIL)
    print(f"\n{'CONTENT METRIC MET' if not FAIL else 'CONTENT METRIC NOT MET'} — "
          f"{len(PASS)}/{total}")
    for f in FAIL:
        print(f"  [FAIL] {f}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())

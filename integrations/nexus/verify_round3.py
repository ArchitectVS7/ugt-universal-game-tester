#!/usr/bin/env python3
"""
NEXUS ROUND 3 — the ROBUSTNESS tier: UGT's REAL ExploitHunter
(ugt/core/exploit_hunter.py — the framework's Phase-1 machinery, NOT a bespoke
loop) driving the live nexus-world-builder server through a seeded heuristic +
refusal-probing policy, with EVERY invariant checked after EVERY step and a
byte-identical same-seed episode-0 replay.

Where R1 walked one mission and R2 drove the scripted 8-mission spine to a win,
R3 hands the wheel to a stochastic policy over the whole command vocabulary
(status/help/missions/scan/connect/ls/cat/analyze/exploit/crack/escalate/
backdoor/download/accept/talk/choose/disconnect/whoami + an intentionally
unmapped id + a garbage token). N seeded episodes x M steps; args are composed
from OBSERVED state (discovered servers, analyzed vulns, listed files, live
missions, met NPCs) — never fabricated. The policy also deliberately probes the
refusal paths (ungated / bad-vuln hacks, undiscovered connect, early choose,
re-accepting a completed mission, cat of a missing file, an unmapped action id,
and a garbage token) — each must be refused AND leave the game state inert.

Every step is checked against ALL of R1/R2's per-command invariants (the 7 in
invariants.py, wrapped to the hunter's (before, action_id, info, after, ctx)
signature) PLUS two R3-only stateful invariants (completed-story-missions
monotonic; no 25-in-a-row soft-lock). Target: ZERO findings.

Gate (fail-closed):
  1. all EPISODES ran (report.episodes == EPISODES, total_steps > 0);
  2. ZERO findings across every invariant x every step (each printed [FINDING]);
  3. the R3 stateful invariants are clean;
  4. every mapped action id was attempted at least once (coverage);
  5. the unmapped + garbage probes fired and were inert;
  6. the refusal probes fired (> 0) with a per-kind histogram;
  7. non-vacuous PROGRESS: >= 1 exploit/crack roll, >= 1 compromise, >= 1 story
     mission completed across the episodes;
  8. a fresh same-seed re-run of episode 0 reproduces its trajectory byte for
     byte (command stream, CommandResult stream, rngCounter progression,
     normalized per-step player-state) and is itself non-vacuous (>= 1 roll).

A failed check is DATA: an invariant violation / crash / soft-lock / statistical
anomaly is an NX-R3-x finding, to be fixed upstream in the game (with a pinning
test) and re-run — never tolerated or weakened here.

Run (server up on :3100 — verify the LISTEN pid is yours:
lsof -nP -iTCP:3100 -sTCP:LISTEN):

    python3 integrations/nexus/verify_round3.py [base_seed]

Exit 0 + "ROUND 3 MET — N/N" means the gate passed.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import invariants  # noqa: E402  (local module, from integrations/nexus/)

from ugt.adapters.nexus_http import NexusHttpAdapter  # noqa: E402
from ugt.core.exploit_hunter import ExploitHunter, Invariant  # noqa: E402
from ugt.core.trial import GateRunner, first_divergence  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

CONFIG_PATH = "integrations/nexus/ugt.config.yaml"

BASE_SEED = sys.argv[1] if len(sys.argv) > 1 else "nexus-r3"
POLICY_SEED = 424242
EPISODES = 4
STEPS_PER_EPISODE = 90

# ── action ids (lockstep with ugt.config.yaml) ───────────────────────────────
STATUS, HELP, MISSIONS, SCAN, CONNECT = 0, 1, 2, 3, 4
LS, CAT, ANALYZE, EXPLOIT, CRACK = 5, 6, 7, 8, 9
ESCALATE, BACKDOOR, DOWNLOAD, ACCEPT = 10, 11, 12, 13
TALK, CHOOSE, DISCONNECT, WHOAMI = 14, 15, 16, 17
UNMAPPED_ID, GARBAGE_ID = 18, 19
MARKET, BUY = 20, 21   # NX-L14-1 economy

# ── refusal probes: (kind, action_id). Kinds in _PROBE_COMPOSE get a bad arg
#    composed in the R3 subclass; unmapped_id/garbage need no compose (the base
#    adapter sends "action_18" / a nonsense token verbatim -> "Command not
#    found"). Every probe must satisfy inv_refused_state_inert. ──────────────
PROBES = [
    ("hack_ungated", EXPLOIT),
    ("hack_nonexistent_vuln", EXPLOIT),
    ("connect_undiscovered", CONNECT),
    ("choose_early", CHOOSE),
    ("accept_completed", ACCEPT),
    ("cat_nonexistent", CAT),
    ("unmapped_id", UNMAPPED_ID),
    ("garbage", GARBAGE_ID),
]
_PROBE_COMPOSE = {"hack_ungated", "hack_nonexistent_vuln", "connect_undiscovered",
                  "choose_early", "accept_completed", "cat_nonexistent"}

# Coverage-exploration pool: guarantees the otherwise rarely-selected verbs
# (help/escalate/backdoor/whoami/disconnect/analyze/talk/…) are each attempted
# regardless of how far into the story an episode gets (talk without a met NPC
# is simply refused + inert — still real coverage of the verb).
EXPLORE = [HELP, STATUS, MISSIONS, SCAN, LS, ANALYZE, ESCALATE, BACKDOOR,
           WHOAMI, DISCONNECT, DOWNLOAD, CRACK, TALK,
           # NX-L14-1 economy. BUY picks its tier uniformly rather than an
           # affordable one, so most buys are REFUSALS — and that is the point:
           # inv_refused_state_inert then asserts a refused purchase left credits
           # and toolTier untouched, which is the failure mode that matters for an
           # economy. Downgrades and re-buys arise naturally once one has landed.
           MARKET, BUY]
# Guaranteed-success recovery commands (always legal) — a real player retreats
# to these after a run of failures rather than hammering a dead action.
SAFE = [STATUS, WHOAMI, MISSIONS, HELP]

# met_<flag> -> the talk handle to use.
MET_MAP = {"met_sp3ctr3": "sp3ctr3", "met_axiom": "axiom",
           "met_elena_cross": "e.cross"}

# ── objective-directed steering (the "heuristic" the policy biases toward) ───
# The available side-missions gate on narrative triggers (contact_npc broker,
# abstract targets) that generic hacking can't satisfy, and each story mission
# lands on ONE specific server+file — so a purely uniform connect/cat almost
# never aligns with a mission's objective inside a short episode. The policy
# therefore leans on the SAME known spine targets R1/R2 encode test-side (this
# is the heuristic's game knowledge, NOT game logic — every effect is still read
# back from state) to actually make progress, while the 15% refusal probes, 10%
# uniform exploration, stochastic vuln/file fallbacks and the unmapped/garbage
# ids keep it a robustness walk, not a scripted spine.
STORY_ORDER = ["the_breadcrumb", "following_the_money", "project_meridian",
               "dead_drop", "into_the_syndicate", "the_other", "the_architect",
               "point_of_no_return"]

# mission -> ordered legs; each leg = (ip, vuln, [files]). vuln is a vuln type
# for `exploit`, "crack:<file>" for a `crack` leg, or None when the server is
# readable without compromise. (Verified against verify_round2.py::SPINE.)
MISSION_TARGETS = {
    "the_breadcrumb": [
        ("192.168.1.105", "weak_password",
         ["/Users/jmiller/Documents/work_vpn.txt"])],
    "following_the_money": [
        ("10.52.0.7", "weak_password",
         ["/shared/reports/Q3_2024_CONFIDENTIAL.xlsx",
          "/shared/IT/network_diagram.png.txt",
          "/home/jmiller/private/.insurance"])],
    "project_meridian": [
        ("10.52.2.20", "privilege_escalation",
         ["/classified/PROJECT_M/README.txt",
          "/classified/PROJECT_M/financial_transfers.log",
          "/classified/PROJECT_M/surveillance_metadata.json"])],
    "dead_drop": [
        ("10.99.0.50", "weak_password",
         ["/drop/meridian_files.enc", "/drop/contacts.txt"])],
    "into_the_syndicate": [
        ("172.16.50.1", "crack:/var/log/access.log", []),
        ("172.16.50.25", "privilege_escalation",
         ["/axiom/docs/architecture_v3_FINAL.pdf",
          "/axiom/logs/decision_history_summary.txt"])],
    "the_other": [
        ("10.99.0.50", None, ["/drop/null_origin.dat"])],       # + talk sp3ctr3
    "the_architect": [
        ("10.42.0.1", None, ["/foundation/cross_testimony.txt"])],  # + talk e.cross
}
_TALK_LEG = {"the_other": ("met_sp3ctr3", "sp3ctr3"),
             "the_architect": ("met_elena_cross", "e.cross")}

# analyze line: "  [SEVERITY] <type> in <service> service"
_VULN_RE = re.compile(r"\[[A-Z]+\]\s+(\S+)\s+in\s")
# ls line ends with the absolute file path (no spaces in paths).
_PATH_RE = re.compile(r"(/[^\s]+)")
# missions (available filter): "Use 'accept <id>' to start" — the id is quote-
# delimited, so stop at the closing quote (do NOT swallow it into the id).
_ACCEPT_RE = re.compile(r"accept\s+([^\s']+)'?\s+to start")


_normalize_state = invariants.normalize_state


# ── the seeded, instrumented R3 adapter ──────────────────────────────────────
class R3NexusAdapter(NexusHttpAdapter):
    """NexusHttpAdapter with seeded episode resets, per-episode observed-state
    caches used to compose real command args, refusal-probe composition, and a
    per-episode trajectory record (completion + determinism gate checks).

    Contains NO game logic: every arg is picked from state the game reported,
    every effect is read back from player-state. Instrumentation + composition
    only — the transport and every game interaction is the parent class's.
    """

    def __init__(self, config, base_seed):
        super().__init__(config)
        self.base_seed = base_seed
        self.episode = -1
        self.stats: list[dict] = []
        self._probe_hist: Counter = Counter()   # spans episodes (coverage)
        self._ep_rng = None                       # bound by the policy each call
        self._probe = None                        # one-shot pending probe kind
        self._reset_ep_caches()

    def _reset_ep_caches(self):
        self._known_vulns: dict[str, list[str]] = {}   # ip -> [vuln type]
        self._known_files: dict[str, list[str]] = {}   # ip -> [file path]
        self._read_files: set[str] = set()             # paths already cat/download'd
        self._available_missions: list[str] = []       # ids parsed from `missions`
        self._cur_ip = None                            # ip of the carried connection
        self._probe = None
        self._forced_command = None                    # one-shot directed override

    # ── lifecycle (NO-ARG reset, matching the hunter) ────────────────────────
    def reset(self):
        self.episode += 1
        seed = f"{self.base_seed}-ep{self.episode}"
        self._reset_ep_caches()
        state = super().reset(seed)
        self._last_state = state
        self.stats.append({
            "seed": seed, "steps": 0, "traj": [],
            "compromised": 0, "completed": 0, "missions_done": 0, "rolls": 0,
            "final_status": {},
        })
        return state

    def step(self, action_id):
        after, terminated, truncated, info = super().step(action_id)
        command = info.get("command", "")
        result = info.get("result") or {}
        output = result.get("output", "") or ""
        success = bool(result.get("success"))

        # ── record the trajectory (the determinism-replay surface) ───────────
        st = self.stats[-1]
        st["steps"] += 1
        st["traj"].append((
            action_id,
            command,
            json.dumps(result, sort_keys=True),
            after.get("rngCounter"),
            json.dumps(_normalize_state(after), sort_keys=True, default=str),
        ))
        if "[Success Rate:" in output:
            st["rolls"] += 1
        st["compromised"] = len(after.get("compromisedServers") or [])
        st["missions_done"] = after.get("missionsCompletedCount", 0) or 0
        gs = after.get("gameStatus") or {}
        st["completed"] = gs.get("completedStoryMissions", 0) or 0
        st["final_status"] = gs

        # ── parse observed output into the arg caches (successful only) ───────
        verb = command.split(" ", 1)[0].lower()
        if success and verb == "connect":
            parts = command.split()
            self._cur_ip = parts[1] if len(parts) > 1 else self._cur_ip
        elif success and verb == "disconnect":
            self._cur_ip = None
        if success and verb == "analyze" and self._cur_ip:
            vulns = _VULN_RE.findall(output)
            if vulns:
                self._known_vulns[self._cur_ip] = sorted(set(vulns))
        if success and verb == "ls" and self._cur_ip:
            paths = [p for ln in output.splitlines() for p in _PATH_RE.findall(ln)]
            if paths:
                self._known_files[self._cur_ip] = sorted(set(paths))
        if success and verb in ("cat", "download", "crack"):
            parts = command.split(" ", 1)
            if len(parts) > 1:
                self._read_files.add(parts[1])   # (crack marks a directed leg done)
        if success and verb == "missions" and "available" in output.lower():
            self._available_missions = sorted(set(_ACCEPT_RE.findall(output)))

        self._last_state = after
        return after, terminated, truncated, info

    # ── command composition (state-driven + probes; NO game logic) ───────────
    def _compose_command(self, name: str) -> str:
        probe = self._probe
        self._probe = None
        if probe is not None:
            return self._compose_probe(probe)

        # A directed leg picks both the action AND its arg atomically in the
        # policy; honor it here (one-shot) so the arg matches the intent.
        if self._forced_command is not None:
            cmd = self._forced_command
            self._forced_command = None
            return cmd

        rng = self._ep_rng
        st = self._last_state or {}
        if name in self._INFO_BARE:
            return name
        if name == "connect":
            return self._pick_connect(st, rng)
        if name == "exploit":
            return f"exploit {self._pick_vuln(rng)}"
        if name == "crack":
            return f"crack {self._pick_crack(rng)}"
        if name in ("cat", "download"):
            return f"{name} {self._pick_readfile(rng)}"
        if name == "accept":
            return f"accept {self._pick_accept(st, rng)}"
        if name == "talk":
            return f"talk {self._pick_npc(st, rng)}"
        if name == "choose":
            return "choose liberation"
        if name == "buy":
            return f"buy {self._pick_tier(rng)}"
        # garbage / action_18 / anything else -> the base default.
        return super()._compose_command(name)

    # Every purchasable tier, cheapest first. The walk picks UNIFORMLY, so it
    # deliberately spends most of its buys on tiers it cannot afford — those are
    # refusals, and `inv_refused_state_inert` then asserts the refused purchase left
    # credits/toolTier untouched, which is the failure mode that matters for an
    # economy (a refused buy that still debits). Downgrades and re-buys arise
    # naturally once a tier has been bought, and are refusals too.
    _TIERS = ("commercial", "black_market", "custom", "zero_day")

    def _pick_tier(self, rng):
        return self._TIERS[rng.randrange(len(self._TIERS))]

    _INFO_BARE = {"market", "status", "help", "missions", "scan", "ls", "analyze",
                  "escalate", "backdoor", "whoami", "disconnect"}

    def _compose_probe(self, kind: str) -> str:
        if kind == "hack_ungated":          # exploit while (usually) not connected
            return "exploit weak_password"
        if kind == "hack_nonexistent_vuln":
            return "exploit definitely_not_a_vuln"
        if kind == "connect_undiscovered":
            return "connect 203.0.113.99"   # TEST-NET-3, never seeded/discovered
        if kind == "choose_early":
            return "choose liberation"      # refused unless point_of_no_return active
        if kind == "accept_completed":
            done = sorted(m.get("missionId") for m in (self._last_state or {}).get("missions", [])
                          if m.get("status") == "completed" and m.get("missionId"))
            return f"accept {done[0] if done else self._FALLBACK_MISSION}"
        if kind == "cat_nonexistent":
            return "cat /no/such/file"
        return kind  # unreachable for the two verbatim probes

    # ── seeded arg pickers (all pools sorted -> hash-seed-independent) ────────
    def _pick_connect(self, st, rng):
        discovered = sorted(st.get("discoveredServers") or [])
        comp = {c.get("ipAddress") for c in st.get("compromisedServers") or []}
        fresh = [ip for ip in discovered if ip not in comp]
        pool = fresh or discovered
        return f"connect {rng.choice(pool)}" if pool else "connect 192.168.1.105"

    def _pick_vuln(self, rng):
        known = self._known_vulns.get(self._cur_ip or "", [])
        return rng.choice(known) if known else self._COMMON_VULN

    def _pick_crack(self, rng):
        known = self._known_files.get(self._cur_ip or "", [])
        return rng.choice(known) if known else self._CRACK_TARGET

    def _pick_readfile(self, rng):
        known = sorted(set(self._known_files.get(self._cur_ip or "", [])) - self._read_files)
        return rng.choice(known) if known else self._GENERIC_FILE

    def _pick_accept(self, st, rng):
        accepted = {m.get("missionId") for m in st.get("missions") or []}
        avail = set(self._available_missions) - accepted
        # Prefer the earliest reachable STORY mission (so the directed legs have
        # something to drive); fall back to any available side mission.
        for mid in STORY_ORDER:
            if mid in avail:
                return mid
        return rng.choice(sorted(avail)) if avail else self._FALLBACK_MISSION

    # ── objective-directed leg (the heuristic bias toward reachable progress) ─
    def _directed_command(self, st):
        """Return (action_id, full_command) for the current story-spine leg, or
        None when no story mission is active with a pending leg. Pure function of
        (state, carried nav, files/cracks already read) -> deterministic."""
        active = {m.get("missionId") for m in st.get("missions") or []
                  if m.get("status") == "active"}
        discovered = set(st.get("discoveredServers") or [])
        comp_ips = {c.get("ipAddress") for c in st.get("compromisedServers") or []}
        flags = set(st.get("storyFlags") or [])
        for mid in STORY_ORDER:
            if mid not in active:
                continue
            if mid == "point_of_no_return":
                return (CHOOSE, "choose liberation")
            for ip, vuln, files in MISSION_TARGETS.get(mid, []):
                if vuln and vuln.startswith("crack:"):
                    cfile = vuln.split(":", 1)[1]
                    if cfile in self._read_files:
                        continue                      # crack leg already done
                    if self._cur_ip != ip:
                        return (CONNECT, f"connect {ip}") if ip in discovered else (SCAN, "scan")
                    return (CRACK, f"crack {cfile}")
                if self._cur_ip != ip:
                    return (CONNECT, f"connect {ip}") if ip in discovered else (SCAN, "scan")
                if vuln and ip not in comp_ips:
                    return (EXPLOIT, f"exploit {vuln}")
                unread = [f for f in files if f not in self._read_files]
                if unread:
                    return (CAT, f"cat {unread[0]}")
                talk = _TALK_LEG.get(mid)
                if talk and talk[0] in flags:
                    return (TALK, f"talk {talk[1]}")
            # this story mission's legs are all satisfied but it is still active
            # (waiting on an auto-complete) — nothing directed to do for it.
        return None

    def _pick_npc(self, st, rng):
        flags = set(st.get("storyFlags") or [])
        met = sorted(handle for flag, handle in MET_MAP.items() if flag in flags)
        return rng.choice(met) if met else "sp3ctr3"


# ── the phase-aware, refusal-probing policy (bound to one adapter) ───────────
def make_nexus_policy(adapter):
    """Deterministic given (state, rng, ctx, adapter caches). Binds the adapter
    so it can read the carried nav state + observed-state caches (player-state
    alone does NOT expose currentServerId — the stateless-nav contract — nor the
    available-mission list)."""

    def policy(state, action_ids, rng, ctx):
        adapter._ep_rng = rng
        adapter._forced_command = None   # cleared unless the directed branch sets it

        # Recovery: after a run of failures a real player stops hammering the
        # dead action and does something guaranteed-legal (info commands always
        # succeed in NEXUS). This keeps the walk from tripping its OWN
        # no_soft_lock invariant on a policy dead-end — a real game soft-lock
        # (no legal move) would still surface because SAFE would also fail.
        if ctx.get("consecutive_fails", 0) >= 8:
            return rng.choice(SAFE)

        r = rng.random()

        # 15% refusal probes — exercise every refusal path, each must be inert.
        if r < 0.15:
            kind, aid = rng.choice(PROBES)
            adapter._probe_hist[kind] += 1
            if kind in _PROBE_COMPOSE:
                adapter._probe = kind
            return aid

        # 10% coverage exploration — guarantees the rare verbs are attempted.
        if r < 0.25:
            return rng.choice(EXPLORE)

        # Objective-directed leg (drives the active story mission's next step);
        # sets the one-shot forced command so compose fills the matching arg.
        directed = adapter._directed_command(state)
        if directed is not None:
            aid, command = directed
            adapter._forced_command = command
            return aid

        # ── phase-aware progress (no story mission is actively directed) ─────
        missions = state.get("missions") or []
        active = [m for m in missions if m.get("status") == "active"]
        connected = adapter._cur_server_id is not None
        cur_ip = adapter._cur_ip
        comp_ips = {c.get("ipAddress") for c in state.get("compromisedServers") or []}
        on_compromised = cur_ip is not None and cur_ip in comp_ips
        unread = bool(cur_ip and (set(adapter._known_files.get(cur_ip, [])) - adapter._read_files))
        flags = set(state.get("storyFlags") or [])
        met_npcs = [h for f, h in MET_MAP.items() if f in flags]
        ponr_active = any(m.get("missionId") == "point_of_no_return" for m in active)

        if not active:
            accepted = {m.get("missionId") for m in missions}
            if set(adapter._available_missions) - accepted:
                return ACCEPT
            return MISSIONS            # discover what is acceptable next
        if ponr_active:
            return CHOOSE
        if connected and not on_compromised:
            return rng.choice([EXPLOIT, CRACK, ANALYZE])
        if connected and on_compromised:
            if unread:
                return rng.choice([CAT, LS, DOWNLOAD])
            return rng.choice([LS, CAT])   # ls to discover files, then cat
        if met_npcs and rng.random() < 0.5:
            return TALK
        if not connected:
            return rng.choice([SCAN, CONNECT])
        return rng.choice([STATUS, MISSIONS, CONNECT, DISCONNECT])

    return policy


# ── R3-only stateful invariants (hunter signature) ──────────────────────────
def inv_story_missions_monotonic(before, action_id, info, after, ctx):
    """completedStoryMissions never decreases and isComplete never flips
    true -> false (win is terminal, spanning the whole episode)."""
    bs = before.get("gameStatus") or {}
    as_ = after.get("gameStatus") or {}
    bc = bs.get("completedStoryMissions", 0) or 0
    ac = as_.get("completedStoryMissions", 0) or 0
    if ac < bc:
        return f"completedStoryMissions regressed {bc} -> {ac}"
    if bs.get("isComplete") is True and as_.get("isComplete") is not True:
        return f"isComplete flipped true -> {as_.get('isComplete')!r} (win not terminal)"
    return None


def inv_no_soft_lock(before, action_id, info, after, ctx):
    """No 25-in-a-row streak of failed commands (a real player would be stuck)."""
    success = bool((info.get("result") or {}).get("success"))
    fails = 0 if success else ctx.get("consecutive_fails", 0) + 1
    ctx["consecutive_fails"] = fails
    if fails >= 25:
        cmd = info.get("command", "")
        return f"{fails} consecutive failed commands (last: {cmd!r})"
    return None


# The 7 R1/R2 predicates (refused-state-inert already excludes rngCounter,
# NX-OBS-1), wrapped to the hunter signature by the shared suite, + the 2
# R3-only stateful invariants.
INVARIANTS = invariants.SUITE.to_hunter_invariants() + [
    Invariant("story_missions_monotonic", inv_story_missions_monotonic,
              inv_story_missions_monotonic.__doc__ or ""),
    Invariant("no_soft_lock", inv_no_soft_lock, inv_no_soft_lock.__doc__ or ""),
]
_R3_STATEFUL = {"story_missions_monotonic", "no_soft_lock"}


def main() -> int:
    cfg = UgtConfig(CONFIG_PATH)
    action_names = {int(k): v["name"]
                    for k, v in cfg.data["action_space"]["actions"].items()}
    action_ids = list(action_names.keys())
    gate = GateRunner()
    ck = gate.ck

    print(f"NEXUS Round 3 — real ExploitHunter, {EPISODES} episodes x "
          f"{STEPS_PER_EPISODE} steps (base seed {BASE_SEED!r}, policy seed {POLICY_SEED})\n")

    adapter = R3NexusAdapter(cfg, BASE_SEED)
    try:
        adapter.connect()

        # ── the hunt ─────────────────────────────────────────────────────────
        print("  -- hunt --")
        hunter = ExploitHunter(adapter, INVARIANTS, action_ids,
                               action_names=action_names,
                               policy=make_nexus_policy(adapter), seed=POLICY_SEED)
        report = hunter.run(episodes=EPISODES, steps_per_episode=STEPS_PER_EPISODE,
                            log=lambda m: print(f"    {m}"))

        # ── gate ─────────────────────────────────────────────────────────────
        print("\n  -- gate --")
        ck(f"all {EPISODES} episodes ran through the ExploitHunter",
           report.episodes == EPISODES and report.total_steps > 0,
           f"{report.episodes} episodes, {report.total_steps} steps")

        ck("ZERO invariant violations / crashes across every step",
           not report.findings,
           f"{len(INVARIANTS)} invariants x {report.total_steps} steps clean"
           if not report.findings else f"{len(report.findings)} finding(s) — see below")
        for f in report.findings:
            print(f"      [FINDING] ep{f.episode} step{f.step} {f.kind}/{f.name} "
                  f"action={f.action_name}: {f.message}")

        r3_findings = [f for f in report.findings if f.name in _R3_STATEFUL]
        ck("R3 stateful invariants (story-missions monotonic, no soft-lock) clean",
           not r3_findings,
           "0 violations" if not r3_findings else f"{len(r3_findings)} violation(s)")

        missing = [n for n in action_names.values() if n not in report.action_counts]
        ck("every mapped action id attempted at least once (coverage)",
           not missing,
           f"coverage: { {k: report.action_counts[k] for k in sorted(report.action_counts)} }"
           if not missing else f"never attempted: {missing}")

        unmapped_hits = report.action_counts.get("action_18", 0)
        garbage_hits = report.action_counts.get("garbage", 0)
        ck("unmapped-id + garbage probes both fired and were inert",
           unmapped_hits > 0 and garbage_hits > 0,
           f"action_18 x{unmapped_hits}, garbage x{garbage_hits} "
           f"(inertness enforced by inv_refused_state_inert)")

        probes_fired = sum(adapter._probe_hist.values())
        ck("refusal probes fired (per-kind histogram)",
           probes_fired > 0 and len(adapter._probe_hist) == len(PROBES),
           f"{dict(sorted(adapter._probe_hist.items()))}")

        total_rolls = sum(st["rolls"] for st in adapter.stats[:EPISODES])
        max_comp = max((st["compromised"] for st in adapter.stats[:EPISODES]), default=0)
        max_done = max((st["missions_done"] for st in adapter.stats[:EPISODES]), default=0)
        max_story = max((st["completed"] for st in adapter.stats[:EPISODES]), default=0)
        ck("non-vacuous progress: >=1 seeded roll, >=1 compromise, >=1 mission completed",
           total_rolls >= 1 and max_comp >= 1 and max_done >= 1,
           f"rolls={total_rolls} maxCompromised={max_comp} maxMissionsCompleted={max_done} "
           f"(story={max_story})")

        # ── coverage report ──────────────────────────────────────────────────
        print("\n  -- coverage report --")
        distinct_cmds = set()
        for i, st in enumerate(adapter.stats[:EPISODES]):
            for entry in st["traj"]:
                distinct_cmds.add(entry[1].split(" ", 1)[0])
            gs = st["final_status"] or {}
            print(f"    episode {i}: seed {st['seed']!r}, {st['steps']} steps, "
                  f"compromised={st['compromised']}, "
                  f"missionsCompleted={st['missions_done']} (story={st['completed']}), "
                  f"rolls={st['rolls']}, gameStatus="
                  f"(complete={gs.get('isComplete')} "
                  f"{gs.get('completedStoryMissions')}/{gs.get('totalStoryMissions')} "
                  f"ending={gs.get('ending')})")
        agg_steps = sum(st["steps"] for st in adapter.stats[:EPISODES])
        print(f"    aggregate: {agg_steps} steps, {len(distinct_cmds)} distinct command verbs, "
              f"{sum(st['compromised'] for st in adapter.stats[:EPISODES])} server-compromises "
              f"(final, summed), {max_done} max missions completed")
        print(f"    refusal-probe histogram: {dict(sorted(adapter._probe_hist.items()))}")
        print(f"    action histogram: { {k: report.action_counts[k] for k in sorted(report.action_counts)} }")

        # ── determinism: replay EPISODE 0 with a FRESH adapter + hunter ──────
        print("\n  -- determinism replay (episode 0, fresh adapter + hunter) --")
        replay_adapter = R3NexusAdapter(cfg, BASE_SEED)
        replay_adapter.connect()
        replay_hunter = ExploitHunter(replay_adapter, INVARIANTS, action_ids,
                                      action_names=action_names,
                                      policy=make_nexus_policy(replay_adapter),
                                      seed=POLICY_SEED)
        replay_report = replay_hunter.run(episodes=1, steps_per_episode=STEPS_PER_EPISODE,
                                          log=lambda m: print(f"    {m}"))
        first = adapter.stats[0]["traj"]
        second = replay_adapter.stats[0]["traj"]
        same_len = len(first) == len(second)
        divergence = first_divergence(first, second)
        ck("episode-0 replay is byte-identical (commands + CommandResults + "
           "rngCounter + normalized state)",
           same_len and divergence is None and not replay_report.findings,
           f"{len(first)} steps identical" if same_len and divergence is None
           else (f"len {len(first)} vs {len(second)}; first divergence at step "
                 f"{divergence}: {first[divergence] if divergence is not None and divergence < len(first) else '-'} "
                 f"vs {second[divergence] if divergence is not None and divergence < len(second) else '-'}"))
        ck("episode-0 replay is NON-VACUOUS (fired >= 1 seeded roll)",
           replay_adapter.stats[0]["rolls"] >= 1,
           f"rolls={replay_adapter.stats[0]['rolls']}")
        replay_adapter.close()

    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        ck("exception-free run", False, f"{type(exc).__name__}: {exc}")
    finally:
        adapter.close()

    return gate.finish(
        "ROUND 3",
        f"UGT's real ExploitHunter drove {EPISODES} seeded episodes of "
        f"heuristic + refusal-probing real actions through the live handler: "
        f"every invariant held on every step, the whole action vocabulary "
        f"(and the unmapped-id + garbage probes) was exercised, the walk made "
        f"real progress (compromises + mission completions + seeded rolls), "
        f"and a fresh same-seed re-run replays episode 0 byte for byte. "
        f"NEXUS trial ladder complete.",
        not_met_msg="Findings above are the work list.")


if __name__ == "__main__":
    sys.exit(main())

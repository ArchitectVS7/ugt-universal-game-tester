#!/usr/bin/env python3
"""
Tarot-war ROUND 2 verification — every mode to completion, effects accounted,
invariants after every dispatch.

Round-2 definition of done (Round 1 must already pass):

    A. a CLASSIC game runs to completion under per-dispatch invariants:
       legal phase transitions only, scores/rounds/log monotonic, war pile
       empty between dispatches, finished implies a winner, and a card census
       after every dispatch (every id at most twice; total only ever drops by
       exactly 2 alongside a Tower-destruction log)
    B. a SURVIVAL game ends on the first score-changing round with the
       SURVIVAL log entry and the round winner as game winner
    C. an ENDLESS game terminates at the score target with the ENDLESS log
    D. coverage with exact accounting, aggregated across campaigns:
       >=1 war (TW-R1 regression), >=1 Tower destruction (-2 exactly),
       >=1 discard-move card effect (Magician/Empress/Hierophant),
       >=1 deck recycle — all with the census intact
    E. effect log entries are stamped with the round they fire in
       (candidate finding: currentRound increments AFTER effects execute)
    F. hard-AI determinism: two same-seed hard games match move for move,
       and reset preserves difficulty/mode (the documented UI behavior)

No game logic is reimplemented. Run (dev server on :5173, verify the LISTEN
PID is yours):

    python3 integrations/tarot-war/verify_round2.py [base_seed]

Exit 0 + "ROUND 2 MET" means the gate passed. Findings print regardless —
a failed check is data.
"""
from __future__ import annotations

import sys
import time
from collections import Counter

sys.path.insert(0, ".")

from ugt.adapters.playwright import PlaywrightAdapter
from ugt.utils.config_parser import UgtConfig

CONFIG_PATH = "integrations/tarot-war/ugt.config.yaml"
BASE_SEED = 20260708

WAIT, PLAY_ROUND = 0, 1
SET_AI_EASY, SET_AI_MEDIUM, SET_AI_HARD = 2, 3, 4
SET_MODE_CLASSIC, SET_MODE_SURVIVAL, SET_MODE_ENDLESS = 5, 6, 7

MAX_DISPATCHES = 700
ENDLESS_TARGET = 13  # gameModes.ts ENDLESS_SCORE_TARGET (read back from logs too)

DISCARD_MOVE_MARKERS = ("Magician manifests", "Empress nurtures", "Hierophant grants redemption")


def reset_seeded(ad: PlaywrightAdapter, seed: int) -> dict:
    ad.page.evaluate(f"window.__RESET_GAME__({seed})")
    state = ad.page.evaluate("window.__GET_STATE__()")
    if not isinstance(state, dict):
        raise RuntimeError("__GET_STATE__ did not return an object after reset")
    return state


def get_state(ad: PlaywrightAdapter) -> dict:
    return ad.page.evaluate("window.__GET_STATE__()")


def wait_phase(ad: PlaywrightAdapter, phase: str, timeout_s: float = 3.5) -> dict:
    deadline = time.time() + timeout_s
    state = get_state(ad)
    while state.get("gamePhase") != phase and time.time() < deadline:
        time.sleep(0.05)
        state = get_state(ad)
    return state


def card_census(state: dict) -> Counter:
    ids = (
        state["player1"]["deckIds"] + state["player1"]["discardIds"]
        + state["player2"]["deckIds"] + state["player2"]["discardIds"]
    )
    return Counter(ids)


def world_victory(state: dict) -> bool:
    """The World's instant-victory ending (designed comeback: caster's
    deck+hand <= 7). A legitimate game end in every mode — the loser keeps
    their cards."""
    return any("The World completes!" in e["message"] for e in state.get("gameLog", []))


class InvariantTracker:
    """Feeds on consecutive step() states; accumulates violations + coverage."""

    ALLOWED_TRANSITIONS = {
        ("setup", "resolving"), ("setup", "finished"),
        ("playing", "resolving"), ("playing", "finished"),
        ("resolving", "playing"),
        # a timer-race can auto-advance then our dispatch resolves a full round:
        ("resolving", "resolving"), ("resolving", "finished"),
        ("finished", "finished"),
    }

    def __init__(self, label: str):
        self.label = label
        self.violations: list[str] = []
        self.stamp_mismatches: list[str] = []
        self.wars = 0
        self.towers = 0
        self.recycles = 0
        self.discard_moves = 0
        self.prev: dict | None = None

    def _new_entries(self, prev: dict, state: dict) -> list[dict]:
        added = state["gameLogTotal"] - prev["gameLogTotal"]
        if added <= 0:
            return []
        log = state.get("gameLog", [])
        return log[-added:] if added <= len(log) else log

    def feed(self, state: dict, ctx: str = "") -> None:
        prev, self.prev = self.prev, state
        if prev is None:
            return
        v = self.violations.append
        where = f"[{self.label}{' ' + ctx if ctx else ''} r{state.get('currentRound')}]"

        tr = (prev.get("gamePhase"), state.get("gamePhase"))
        if tr not in self.ALLOWED_TRANSITIONS:
            v(f"{where} illegal phase transition {tr[0]} -> {tr[1]}")
        for p in ("player1", "player2"):
            if state[p]["score"] < prev[p]["score"]:
                v(f"{where} {p} score decreased {prev[p]['score']} -> {state[p]['score']}")
        if state["currentRound"] < prev["currentRound"]:
            v(f"{where} currentRound decreased {prev['currentRound']} -> {state['currentRound']}")
        if state["gameLogTotal"] < prev["gameLogTotal"]:
            v(f"{where} game log shrank {prev['gameLogTotal']} -> {state['gameLogTotal']}")
        if state.get("warCardCount", 0) != 0:
            v(f"{where} war pile not empty between dispatches: {state.get('warCardCount')}")
        if state.get("gamePhase") == "finished" and state.get("winner") not in ("player1", "player2"):
            v(f"{where} finished without a winner: {state.get('winner')}")

        entries = self._new_entries(prev, state)
        msgs = [e["message"] for e in entries]
        self.wars += sum(1 for m in msgs if "WAR!" in m)
        self.recycles += sum(1 for m in msgs if "replenished" in m)
        self.discard_moves += sum(1 for m in msgs if any(k in m for k in DISCARD_MOVE_MARKERS))
        tower_hits = sum(1 for m in msgs if "Tower destroys" in m)
        self.towers += tower_hits

        census = card_census(state)
        over = {cid: n for cid, n in census.items() if n > 2}
        if over:
            v(f"{where} card duplication: {over}")
        delta = sum(census.values()) - sum(card_census_from(prev).values())
        if delta != -2 * tower_hits:
            v(f"{where} census total changed by {delta} with {tower_hits} Tower destruction(s) "
              f"logged (expected {-2 * tower_hits})")

        # Effect-log round stamping: an effect entry created by this dispatch
        # must carry the round it visibly fires in. Skip racy double-round
        # dispatches where two rounds' entries interleave.
        if state["currentRound"] - prev["currentRound"] <= 1 and tr != ("resolving", "resolving"):
            for e in entries:
                if e["type"] == "effect" and e["round"] not in (0, state["currentRound"]):
                    self.stamp_mismatches.append(
                        f"{where} effect entry stamped r{e['round']} while resolving "
                        f"r{state['currentRound']}: \"{e['message'][:70]}\"")


def card_census_from(state: dict) -> Counter:
    return card_census(state)


def drive_to_completion(ad: PlaywrightAdapter, tracker: InvariantTracker,
                        max_dispatches: int = MAX_DISPATCHES,
                        stop_after_rounds: int | None = None,
                        use_auto_advance: bool = False,
                        per_round: list | None = None) -> tuple[dict, int]:
    """Dispatch play_round (and round-advances) until finished / caps hit.
    Records (round, p1 card, p2 card, scores) into per_round at each resolution."""
    state = get_state(ad)
    tracker.feed(state, "start")
    dispatches = 0
    while state.get("gamePhase") != "finished" and dispatches < max_dispatches:
        phase = state.get("gamePhase")
        if phase in ("setup", "playing"):
            state, term, trunc, info = ad.step(PLAY_ROUND)
            dispatches += 1
            tracker.feed(state)
            if not info.get("ok"):
                tracker.violations.append(f"[{tracker.label}] play_round refused: {info.get('error')}")
                break
            if per_round is not None and state.get("gamePhase") in ("resolving", "finished"):
                per_round.append((
                    state.get("currentRound"),
                    (state["lastPlayedCards"]["player1"] or {}).get("id"),
                    (state["lastPlayedCards"]["player2"] or {}).get("id"),
                    state["player1"]["score"], state["player2"]["score"],
                ))
            if stop_after_rounds and len(per_round or []) >= stop_after_rounds:
                break
        elif phase == "resolving":
            if use_auto_advance:
                state = wait_phase(ad, "playing")
                if state.get("gamePhase") == "resolving":  # timer never fired?
                    tracker.violations.append(f"[{tracker.label}] auto-advance never left 'resolving'")
                    break
                tracker.feed(state, "auto")
            else:
                state, term, trunc, info = ad.step(PLAY_ROUND)
                dispatches += 1
                tracker.feed(state)
        else:
            break
    return state, dispatches


def main() -> int:
    base_seed = int(sys.argv[1]) if len(sys.argv) > 1 else BASE_SEED
    config = UgtConfig(CONFIG_PATH)
    ad = PlaywrightAdapter(config)
    checks: list[tuple[str, bool, str]] = []
    findings: list[str] = []

    def ck(name: str, ok: bool, detail: str = ""):
        checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))

    def finding(text: str):
        findings.append(text)
        print(f"  [FINDING] {text}")

    print(f"Round 2 — every mode to completion through the REAL tarot-war client (base seed {base_seed})\n")
    trackers: list[InvariantTracker] = []
    try:
        ad.connect()

        # ── A. classic to completion ──────────────────────────────────────────
        print("  -- A. classic campaign --")
        ta = InvariantTracker("classic")
        trackers.append(ta)
        reset_seeded(ad, base_seed)
        sa, da = drive_to_completion(ad, ta)
        loser = "player2" if sa.get("winner") == "player1" else "player1"
        loser_cardless = (sa[loser]["deckCount"] == 0 and sa[loser]["discardCount"] == 0)
        world_a = world_victory(sa)
        ck("classic game terminates by a designed path (exhaustion or The World)",
           sa.get("gamePhase") == "finished" and sa.get("winner") in ("player1", "player2")
           and (loser_cardless or world_a),
           f"winner={sa.get('winner')} after {sa.get('currentRound')} rounds ({da} dispatches), "
           f"final {sa['player1']['score']}-{sa['player2']['score']}, "
           + ("via The World's instant victory" if world_a and not loser_cardless
              else f"loser holds {sa[loser]['deckCount']}+{sa[loser]['discardCount']} cards"))
        if world_a:
            log_a = sa.get("gameLog", [])
            world_idx = max(i for i, e in enumerate(log_a) if "The World completes!" in e["message"])
            post_finish = [e for e in log_a[world_idx + 1:] if e["round"] == log_a[world_idx]["round"]]
            if post_finish:
                finding("TW-R8 regression: The World's instant victory does not stop the "
                        f"round pipeline — {len(post_finish)} log entr{'y' if len(post_finish)==1 else 'ies'} "
                        f"after the victory (e.g. \"{post_finish[-1]['message'][:60]}\"): the round "
                        "keeps resolving (claims/wars/scores mutate) after gamePhase='finished'")
            # TW-R7 (World ignored the discard pile) is FIXED upstream and
            # pinned by effectDeterminism.test.ts — a World ending seen here
            # now means the caster truly owned <= 7 cards.
        ck("classic: per-dispatch invariants held (phase/scores/log/war-pile/winner)",
           not ta.violations, f"{len(ta.violations)} violations" if ta.violations else f"{da} dispatches clean")
        for viol in ta.violations[:5]:
            finding(viol)

        # ── B. survival ───────────────────────────────────────────────────────
        print("\n  -- B. survival campaign --")
        tb = InvariantTracker("survival")
        trackers.append(tb)
        reset_seeded(ad, base_seed + 1)
        ad.step(SET_MODE_SURVIVAL)
        rounds_b: list[tuple] = []
        sb, db = drive_to_completion(ad, tb, max_dispatches=60, per_round=rounds_b)
        surv_log = [e for e in sb.get("gameLog", []) if "SURVIVAL" in e["message"]]
        pre_final_all_scoreless = all(r[3] == 0 and r[4] == 0 for r in rounds_b[:-1])
        final_winner_scored = bool(rounds_b) and rounds_b[-1][3 if sb.get("winner") == "player1" else 4] > 0
        surv_ok = (bool(surv_log) and pre_final_all_scoreless and final_winner_scored) or world_victory(sb)
        ck("survival ends on the first score-changing round (SURVIVAL log, round winner wins)",
           sb.get("gamePhase") == "finished" and surv_ok and not tb.violations,
           surv_log[-1]["message"] if surv_log else f"phase={sb.get('gamePhase')} rounds={rounds_b}")
        for viol in tb.violations[:5]:
            finding(viol)
        s_after_reset = reset_seeded(ad, base_seed + 1)
        ck("reset preserves the chosen mode (documented UI behavior)",
           s_after_reset.get("gameMode") == "survival",
           f"gameMode={s_after_reset.get('gameMode')} after reset from a survival game")

        # ── C. endless ────────────────────────────────────────────────────────
        print("\n  -- C. endless campaign --")
        tc = InvariantTracker("endless")
        trackers.append(tc)
        reset_seeded(ad, base_seed + 2)
        ad.step(SET_MODE_ENDLESS)
        sc, dc = drive_to_completion(ad, tc, max_dispatches=400)
        endless_log = [e for e in sc.get("gameLog", []) if "ENDLESS" in e["message"]]
        w = sc.get("winner")
        winner_score = sc[w]["score"] if w in ("player1", "player2") else -1
        endless_ok = (bool(endless_log) and winner_score >= ENDLESS_TARGET) or world_victory(sc)
        ck("endless terminates at the score target with the ENDLESS log",
           sc.get("gamePhase") == "finished" and endless_ok and not tc.violations,
           endless_log[-1]["message"] if endless_log else
           f"phase={sc.get('gamePhase')} winner={w} score={winner_score} violations={len(tc.violations)}")
        for viol in tc.violations[:5]:
            finding(viol)

        # ── D. coverage aggregate (extra classic seeds if anything is missing) ─
        print("\n  -- D. effect coverage --")
        extra_seed = base_seed + 10
        while (min(sum(t.wars for t in trackers), sum(t.towers for t in trackers),
                   sum(t.discard_moves for t in trackers), sum(t.recycles for t in trackers)) == 0
               and extra_seed < base_seed + 13):
            print(f"     (coverage gap — extra classic campaign, seed {extra_seed})")
            tx = InvariantTracker(f"extra{extra_seed % 100}")
            trackers.append(tx)
            reset_seeded(ad, extra_seed)
            ad.step(SET_MODE_CLASSIC)
            drive_to_completion(ad, tx)
            for viol in tx.violations[:5]:
                finding(viol)
            extra_seed += 1

        wars = sum(t.wars for t in trackers)
        towers = sum(t.towers for t in trackers)
        moves = sum(t.discard_moves for t in trackers)
        recycles = sum(t.recycles for t in trackers)
        census_clean = not any("census" in v or "duplication" in v for t in trackers for v in t.violations)
        ck("wars resolved with cards conserved (TW-R1 regression)", wars > 0 and census_clean,
           f"{wars} wars, census clean" if census_clean else f"{wars} wars but census violations exist")
        ck("Tower destruction accounted exactly (-2 per strike)", towers > 0 and census_clean,
           f"{towers} Tower destructions, each -2 exactly" if towers else "never fired — inconclusive")
        ck("discard-move card effects observed and conserved (Magician/Empress/Hierophant)",
           moves > 0 and census_clean, f"{moves} discard-move effects")
        ck("deck recycling observed and conserved", recycles > 0 and census_clean,
           f"{recycles} recycles")

        # ── E. effect-log round stamping ──────────────────────────────────────
        print("\n  -- E. log stamping --")
        stamps = [m for t in trackers for m in t.stamp_mismatches]
        ck("effect log entries are stamped with the round they fire in", not stamps,
           f"all effect entries correctly stamped" if not stamps else f"{len(stamps)} mis-stamped; e.g. {stamps[0]}")
        if stamps:
            finding("effect logs are stamped with the PREVIOUS round (game bug): the reducer "
                    "increments currentRound AFTER card effects execute, so PRE_COMBAT/EFFECT "
                    "entries carry round N-1 while resolving round N — GameBoard's 'Magical "
                    "Effects' panel (filters log.round === currentRound) shows nothing from "
                    "round 2 on, and GameLog labels them under the wrong round")

        # ── F. hard-AI determinism ────────────────────────────────────────────
        print("\n  -- F. hard-AI determinism --")
        def hard_run() -> list[tuple]:
            tf = InvariantTracker("hard")
            trackers.append(tf)
            reset_seeded(ad, base_seed + 3)
            ad.step(SET_MODE_CLASSIC)
            ad.step(SET_AI_HARD)
            rounds: list[tuple] = []
            drive_to_completion(ad, tf, max_dispatches=40, stop_after_rounds=12,
                                use_auto_advance=True, per_round=rounds)
            return rounds

        run1 = hard_run()
        s_mid = reset_seeded(ad, base_seed + 3)
        difficulty_kept = s_mid.get("aiDifficulty") == "hard"
        run2 = hard_run()
        ck("reset preserves the chosen difficulty (documented UI behavior)", difficulty_kept,
           f"aiDifficulty={s_mid.get('aiDifficulty')} after reset from a hard game")
        ck("two same-seed HARD games match move for move (12 rounds)",
           len(run1) >= 10 and run1 == run2,
           f"{len(run1)} rounds compared" if run1 == run2 else f"diverged: A={run1[:4]}... B={run2[:4]}...")
        if run1 != run2:
            finding("hard-AI same-seed games diverge — adaptive pattern state leaks across resets "
                    "or an unseeded RNG remains in selectCard/pattern scoring")
        ad.step(SET_AI_MEDIUM)

    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        ck("exception-free run", False, f"{type(exc).__name__}: {exc}")
    finally:
        ad.close()

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    print(f"\n{'=' * 70}")
    if findings:
        print("FINDINGS (bugs/gaps in the game, to fix upstream):")
        for i, f in enumerate(findings, 1):
            print(f"  {i}. {f}")
        print()
    if passed == total:
        print(f"ROUND 2 MET — {passed}/{total} checks. All three modes complete cleanly under "
              f"per-dispatch invariants, every effect class is accounted exactly, logs are "
              f"stamped right, and hard-AI games reproduce. Ready for Round 3.")
        return 0
    print(f"ROUND 2 NOT MET — {passed}/{total} checks passed. Fix the failures above and re-run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

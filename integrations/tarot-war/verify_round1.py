#!/usr/bin/env python3
"""
Tarot-war ROUND 1 playability verification — one full playable loop through the
REAL game.

Drives the actual React game (npm run dev on :5173) via PlaywrightAdapter and
the UGT hooks in tarot-war/src/ugt-hooks.ts. Round-1 definition of done:

    A. a fresh seeded game starts and its state is readable
    B. all game information a player sees has real values (info accessibility)
    C. the setup-screen choices work through the real UI handlers
    D. the player takes their turn (play_round draws + resolves through the
       same reducer path the button uses) and the Oracle responds in-turn
    E. the game cycles itself (GameBoard's AI auto-advance moves
       resolving -> playing with no tester input)
    F. a second full cycle works (repeatability)
    G. probes: same-seed determinism (fingerprint + 3-round replay), card
       conservation across a full game, termination of a classic game,
       honest no-op reporting once finished
       (expected failures here are FINDINGS to fix upstream, not harness errors)

No game logic is reimplemented; every effect is read back from the live
GameState projection. Run (with the dev server up on :5173 — verify the
LISTEN PID is yours: lsof -nP -iTCP:5173 -sTCP:LISTEN):

    python3 integrations/tarot-war/verify_round1.py [seed]

Exit 0 + "ROUND 1 MET" means the one-loop gate is passed. Findings are printed
regardless — a failed check is data.
"""
from __future__ import annotations

import sys
import time
from collections import Counter

sys.path.insert(0, ".")

from ugt.adapters.playwright import PlaywrightAdapter
from ugt.utils.config_parser import UgtConfig

CONFIG_PATH = "integrations/tarot-war/ugt.config.yaml"
SEED = 20260707

WAIT, PLAY_ROUND = 0, 1
SET_AI_EASY, SET_AI_MEDIUM, SET_AI_HARD = 2, 3, 4
SET_MODE_CLASSIC, SET_MODE_SURVIVAL, SET_MODE_ENDLESS = 5, 6, 7

# Fields a player can see on the board that therefore must exist and be non-null.
REQUIRED_TOP_FIELDS = ["gamePhase", "currentRound", "gameMode", "aiDifficulty"]
REQUIRED_PLAYER_FIELDS = ["name", "score", "deckCount", "discardCount"]

MAX_DISPATCHES = 600  # completion-probe cap (~300 rounds)


def reset_seeded(ad: PlaywrightAdapter, seed: int) -> dict:
    """Seeded variant of adapter.reset(): same __RESET_GAME__ hook, fixed decks."""
    ad.page.evaluate(f"window.__RESET_GAME__({seed})")
    state = ad.page.evaluate("window.__GET_STATE__()")
    if not isinstance(state, dict):
        raise RuntimeError("__GET_STATE__ did not return an object after reset")
    return state


def get_state(ad: PlaywrightAdapter) -> dict:
    return ad.page.evaluate("window.__GET_STATE__()")


def wait_phase(ad: PlaywrightAdapter, phase: str, timeout_s: float = 3.5) -> dict:
    """Poll the live state until gamePhase == phase (or timeout); returns last state."""
    deadline = time.time() + timeout_s
    state = get_state(ad)
    while state.get("gamePhase") != phase and time.time() < deadline:
        time.sleep(0.05)
        state = get_state(ad)
    return state


def deck_fingerprint(state: dict) -> tuple:
    """Stable identity of a freshly shuffled game: both full deck orders."""
    return (tuple(state["player1"]["deckIds"]), tuple(state["player2"]["deckIds"]))


def card_census(state: dict) -> Counter:
    """Multiset of card ids across both decks + discards (+ war pile size checked
    separately). Both decks are copies of the same 22 Major Arcana, so every id
    must appear exactly twice unless a card was destroyed (Tower) or duplicated
    (a bug)."""
    ids = (
        state["player1"]["deckIds"] + state["player1"]["discardIds"]
        + state["player2"]["deckIds"] + state["player2"]["discardIds"]
    )
    return Counter(ids)


def round_result_logs(state: dict, round_no: int) -> list[dict]:
    """Result entries the UI surfaces for a given round (victory/special/stalemate)."""
    return [
        e for e in state.get("gameLog", [])
        if e["round"] == round_no and e["type"] in ("victory", "special")
        or (e["round"] == round_no and e["type"] == "info" and "stalemate" in e["message"].lower())
    ]


def play_one_round(ad: PlaywrightAdapter, use_auto_advance: bool) -> tuple[dict, dict]:
    """Resolve one full round from 'playing'/'setup', then get back to 'playing'
    (or stop at 'finished'). Returns (state_at_resolution, state_after_advance)."""
    state, term, trunc, info = ad.step(PLAY_ROUND)
    resolved = state
    if state.get("gamePhase") == "resolving":
        if use_auto_advance:
            state = wait_phase(ad, "playing")
        else:
            # Click "Next Round" ourselves — same handler, immediately after
            # entering 'resolving' (the auto-timer can't have fired yet).
            state, term, trunc, info = ad.step(PLAY_ROUND)
    return resolved, state


def main() -> int:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else SEED
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

    print(f"Round 1 — one full playable loop through the REAL tarot-war client (seed {seed})\n")
    try:
        ad.connect()

        # ── A. fresh seeded game ──────────────────────────────────────────────
        print("  -- A. seeded reset --")
        s0 = reset_seeded(ad, seed)
        ck("reset(seed) yields a readable fresh game",
           s0.get("ready") is True and s0.get("gamePhase") == "setup"
           and s0["player1"]["deckCount"] == 22 and s0["player2"]["deckCount"] == 22
           and s0["player1"]["score"] == 0 and s0["player2"]["score"] == 0
           and s0.get("gameLogTotal") == 0,
           f"phase={s0.get('gamePhase')} decks={s0['player1']['deckCount']}/{s0['player2']['deckCount']}")
        ck("seed is honored (determinism seam live)", s0.get("seed") == seed,
           f"state.seed={s0.get('seed')}")
        fp_first = deck_fingerprint(s0)

        # ── B. information accessibility ─────────────────────────────────────
        print("\n  -- B. information access --")
        missing = [f for f in REQUIRED_TOP_FIELDS if s0.get(f) in (None, "")]
        for p in ("player1", "player2"):
            missing += [f"{p}.{f}" for f in REQUIRED_PLAYER_FIELDS if (s0.get(p) or {}).get(f) in (None, "")]
        ck("required board fields present and non-null", not missing,
           f"missing={missing}" if missing else
           f"{s0['player1']['name']} vs {s0['player2']['name']} (AI={s0['player2']['isAI']})")
        ck("fresh-game defaults are the documented ones (classic / medium)",
           s0.get("gameMode") == "classic" and s0.get("aiDifficulty") == "medium",
           f"mode={s0.get('gameMode')} difficulty={s0.get('aiDifficulty')}")
        ck("played-cards panel and log are readable",
           "player1" in (s0.get("lastPlayedCards") or {}) and isinstance(s0.get("gameLog"), list),
           f"lastPlayed={s0.get('lastPlayedCards')} logEntries={len(s0.get('gameLog', []))}")

        # ── C. setup-screen choices (real UI handlers) ────────────────────────
        print("\n  -- C. setup pickers --")
        s, _, _, info = ad.step(SET_AI_HARD)
        ok_hard = bool(info.get("ok")) and s.get("aiDifficulty") == "hard"
        s, _, _, info = ad.step(SET_AI_MEDIUM)
        ck("difficulty picker works on the setup screen",
           ok_hard and bool(info.get("ok")) and s.get("aiDifficulty") == "medium",
           f"medium -> hard -> medium (now {s.get('aiDifficulty')})")
        s, _, _, info = ad.step(SET_MODE_SURVIVAL)
        ok_surv = bool(info.get("ok")) and s.get("gameMode") == "survival"
        s, _, _, info = ad.step(SET_MODE_CLASSIC)
        ck("game-mode picker works on the setup screen",
           ok_surv and bool(info.get("ok")) and s.get("gameMode") == "classic",
           f"classic -> survival -> classic (now {s.get('gameMode')})")

        # ── D. player takes their turn; the Oracle answers in-turn ───────────
        print("\n  -- D. player turn --")
        s1, term, trunc, info = ad.step(PLAY_ROUND)
        ck("play_round starts the battle (setup -> resolving, round 1)",
           bool(info.get("ok")) and s1.get("gamePhase") == "resolving" and s1.get("currentRound") == 1,
           f"phase={s1.get('gamePhase')} round={s1.get('currentRound')}")
        p1c, p2c = s1["lastPlayedCards"]["player1"], s1["lastPlayedCards"]["player2"]
        ck("both cards drawn and revealed",
           p1c is not None and p2c is not None and s1["player1"]["deckCount"] < 22,
           f"{p1c and p1c['name']} (pw {p1c and p1c['power']}) vs {p2c and p2c['name']} (pw {p2c and p2c['power']})")
        oracle_lines = [e for e in s1.get("gameLog", []) if "Oracle:" in e["message"]]
        ck("the Oracle (AI) chose its card inside the same turn",
           s1["player2"]["currentCard"] is not None and len(oracle_lines) > 0,
           oracle_lines[-1]["message"] if oracle_lines else "no Oracle flavor line logged")
        results1 = round_result_logs(s1, 1)
        score_sum = s1["player1"]["score"] + s1["player2"]["score"]
        ck("round 1 resolved with a visible result",
           len(results1) > 0 and (score_sum >= 2 or any(
               "tower" in e["message"].lower() or "stalemate" in e["message"].lower() for e in results1)),
           results1[-1]["message"] if results1 else f"no result log; scores {s1['player1']['score']}-{s1['player2']['score']}")

        # ── E. the game cycles itself (AI auto-advance) ───────────────────────
        print("\n  -- E. auto-advance --")
        s2 = wait_phase(ad, "playing")
        ck("game advances resolving -> playing on its own (AI turn cycle)",
           s2.get("gamePhase") == "playing"
           and s2["player1"]["currentCard"] is None and s2["player2"]["currentCard"] is None,
           f"phase={s2.get('gamePhase')} (no tester input; cards cleared)")

        # ── F. second full cycle (repeatability) ─────────────────────────────
        print("\n  -- F. second cycle --")
        s3, term, trunc, info = ad.step(PLAY_ROUND)
        results2 = round_result_logs(s3, 2)
        ck("cycle 2: play_round resolves round 2",
           bool(info.get("ok")) and s3.get("gamePhase") in ("resolving", "finished")
           and s3.get("currentRound") == 2 and len(results2) > 0,
           results2[-1]["message"] if results2 else f"phase={s3.get('gamePhase')} round={s3.get('currentRound')}")
        census = card_census(s3)
        dupes = {cid: n for cid, n in census.items() if n > 2}
        conserved = not dupes and sum(census.values()) + s3.get("warCardCount", 0) >= 40
        ck("cards conserved after two rounds (every id exactly twice)",
           not dupes, f"duplicated={dupes}" if dupes else f"{sum(census.values())} cards accounted for")
        if dupes:
            finding(f"card duplication after round {s3.get('currentRound')}: {dupes} "
                    f"(war double-claim suspected: the reducer zeroes warDepth before the "
                    f"claim-phase skip check, so war rounds re-claim the two tied cards)")

        # ── G. probes ─────────────────────────────────────────────────────────
        print("\n  -- G. probes --")

        # G1: mid-game picker honesty — the difficulty UI does not exist outside
        # the setup screen, so the hook must refuse, not fake.
        s4 = wait_phase(ad, "playing")
        s5, _, _, info = ad.step(SET_AI_EASY)
        ck("mid-game difficulty change is refused (transport honesty)",
           not info.get("ok") and s5.get("aiDifficulty") == "medium" and bool(info.get("error")),
           str(info.get("error")))

        # G2: same-seed determinism — a second reset with the same seed must
        # produce the same shuffled decks.
        s_re = reset_seeded(ad, seed)
        fp_second = deck_fingerprint(s_re)
        same = fp_first == fp_second
        ck("same seed reproduces the same decks", same,
           "fingerprints match" if same else "deck orders differ — seed seam broken")

        # G3: same-seed replay — two fresh 3-round games must match move for move.
        def replay(rounds: int) -> list[tuple]:
            trace = []
            state = reset_seeded(ad, seed)
            for _ in range(rounds):
                resolved, state = play_one_round(ad, use_auto_advance=True)
                trace.append((
                    resolved.get("currentRound"),
                    (resolved["lastPlayedCards"]["player1"] or {}).get("id"),
                    (resolved["lastPlayedCards"]["player2"] or {}).get("id"),
                    resolved["player1"]["score"], resolved["player2"]["score"],
                    tuple(e["message"] for e in round_result_logs(resolved, resolved.get("currentRound"))),
                ))
                if state.get("gamePhase") == "finished":
                    break
            return trace

        trace_a = replay(3)
        trace_b = replay(3)
        ck("same-seed 3-round replay is identical (cards, scores, results)",
           trace_a == trace_b,
           f"rounds compared={len(trace_a)}" if trace_a == trace_b else f"A={trace_a} B={trace_b}")
        if trace_a != trace_b:
            finding("same-seed replays diverge — an unseeded RNG call site remains in the round pipeline")

        # G4: full classic game — must terminate, conserve cards, and exercise war.
        state = reset_seeded(ad, seed)
        dispatches = 0
        wars = towers = 0
        first_violation = None
        rounds_seen = 0
        while state.get("gamePhase") != "finished" and dispatches < MAX_DISPATCHES:
            phase = state.get("gamePhase")
            if phase in ("setup", "playing"):
                state, term, trunc, info = ad.step(PLAY_ROUND)
                dispatches += 1
                if not info.get("ok"):
                    finding(f"play_round refused mid-game at dispatch {dispatches}: {info.get('error')}")
                    break
                rn = state.get("currentRound")
                rounds_seen = max(rounds_seen, rn or 0)
                slice_msgs = [e["message"] for e in state.get("gameLog", []) if e["round"] == rn]
                wars += sum(1 for m in slice_msgs if "WAR!" in m)
                towers += sum(1 for m in slice_msgs if "Tower destroys" in m)
                census = card_census(state)
                over = {cid: n for cid, n in census.items() if n > 2}
                if over and first_violation is None:
                    first_violation = (rn, dict(over), "after WAR" if any("WAR!" in m for m in slice_msgs) else "no war this round")
            elif phase == "resolving":
                # immediate Next Round click (same handler as the auto-timer)
                state, term, trunc, info = ad.step(PLAY_ROUND)
                dispatches += 1
            else:
                break
        finished = state.get("gamePhase") == "finished"
        ck("a classic game terminates with a winner",
           finished and state.get("winner") in ("player1", "player2"),
           f"winner={state.get('winner')} after {rounds_seen} rounds, {dispatches} dispatches, "
           f"{wars} wars, {towers} tower destructions, final {state['player1']['score']}-{state['player2']['score']}")
        if not finished:
            finding(f"classic game did not finish within {MAX_DISPATCHES} dispatches "
                    f"(round {rounds_seen}) — possible non-termination")
        ck("war mechanic exercised during the full game", wars > 0,
           f"{wars} wars observed" if wars else "no tie occurred — probe inconclusive, try another seed")
        ck("cards conserved across the whole game (no id ever more than twice)",
           first_violation is None,
           "clean" if first_violation is None else f"first violation at round {first_violation[0]}: {first_violation[1]} ({first_violation[2]})")
        if first_violation:
            finding(f"card duplication (game bug): round {first_violation[0]} {first_violation[1]} "
                    f"{first_violation[2]} — winner's discard re-claims the two tied cards after a "
                    f"war resolution (useGameState.ts claim phase: warDepth already reset to 0 when "
                    f"the skip-claim check runs), inflating score by +2 and duplicating card objects")

        # G5: finished-state honesty + reset-after-finish.
        if finished:
            s6, term, trunc, info = ad.step(PLAY_ROUND)
            ck("play_round after game over is an honest no-op",
               not info.get("ok") and term and "reset" in str(info.get("error", "")).lower(),
               str(info.get("error")))
            s7 = reset_seeded(ad, seed)
            ck("reset after game over yields a fresh game",
               s7.get("gamePhase") == "setup" and s7["player1"]["deckCount"] == 22
               and deck_fingerprint(s7) == fp_first,
               "fresh seeded setup state, fingerprint matches")
        else:
            ck("play_round after game over is an honest no-op", False, "game never finished — not exercised")
            ck("reset after game over yields a fresh game", False, "game never finished — not exercised")

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
        print(f"ROUND 1 MET — {passed}/{total} checks. The player takes a turn through the real "
              f"UI handlers, the Oracle answers, the game cycles itself, same-seed runs reproduce, "
              f"and a full classic game terminates cleanly. Ready for Round 2.")
        return 0
    print(f"ROUND 1 NOT MET — {passed}/{total} checks passed. Fix the failures above and re-run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

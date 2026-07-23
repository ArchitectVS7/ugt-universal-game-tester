# NEXUS World Builder — terminal-hacking single-player RPG

**Status: FULL LADDER COMPLETE (2026-07-09).** LLM playtest tier **WIRED AND
LIVE-VERIFIED 2026-07-21** (L-006) — this postdates the ladder work below and is
the newest capability on this integration.

See `HANDOFF.md` for the full resume-here state and `RESULTS.md` for the
commit-traceable findings log. Historical planning material lives in `archive/`
(see the note at the bottom of this file).

## What this integration drives

NEXUS World Builder is a terminal-hacking single-player RPG — a Next.js 16 +
tRPC + Prisma game at `~/Dev/Games/nexus-world-builder/apps/game`. UGT drives
the **real, live** server over plain HTTP via a purpose-built
`NexusHttpAdapter` (`ugt/adapters/nexus_http.py`) — pure `requests`, no browser,
no websocket — hitting four API-key-gated test-only routes:

| Route | Purpose |
|---|---|
| `bootstrap-player` | create a throwaway player |
| `reset-episode` | re-pin the player to a deterministic seed + baseline |
| `closed-alpha` | execute one game command |
| `player-state` | GET — full observable invariant surface |

This is a standalone-script integration: there is no `engine.type` CLI path for
it, the ladder scripts construct a minimal config shim directly.

## Ladder results

| Round | Result |
|---|---|
| Phase 0 | spike 8/8 · smoke 5/5 · DoD 7/7 |
| R1 | 25/25 — one full mission loop + determinism |
| R2 | 36/36 — full 8-mission story spine to a real win, all 3 difficulty modes (tutorial/normal/hardcore) |
| R3 | 9/9 — real `ExploitHunter`, 4 seeded episodes x 90 steps = 360 real steps, **zero findings**, byte-identical same-seed replay |

Game suite at trial end: unit 1265/1265, integration 173/173, 0 skip.

## Headline findings

Five game bugs found and fixed upstream, each pinned by a test in the game
suite (full detail in `RESULTS.md`):

- **NX-P0-1** — the hack surface was locked behind an ungrantable tutorial gate.
- **NX-R1-1** — `seed-story.ts` dropped canonical mission ids, breaking `accept <missionId>`.
- **NX-R1-2** — a mission with a skipped optional objective completed SILENTLY, with no completion banner.
- **NX-R2-1** — the `talk` verb was AND-gated on an ungrantable `met_mercury` flag, making the story unwinnable.
- **NX-R2-2** — `talk` hard-required a live AI provider, so it could never fire in the AI-off deterministic test environment.

Two non-defect characterizations worth knowing, not bugs:

- **NX-OBS-1** — a refused command still ticks `rngCounter` by design (the per-command RNG clock advances unconditionally, before command lookup).
- **NX-R3-OBS** — R3's random walk plateaus at 1/8 missions per episode vs R2's scripted 8/8 — expected: R3 is a robustness walk, not "R2 with probes."

## LLM playtest tier

**WIRED AND LIVE-VERIFIED — L-006, 2026-07-21.** Uses the L-002 direct-adapter
entry point (`playtest_game_with_adapter`) since `NexusHttpAdapter` isn't
registered under any `engine.type`. The drive channel is `type_text` — the LLM
types full command lines, the most faithful mode available for this game.

Getting this live required a root-cause fix to the shared loop in
`ugt/core/playtester.py`: its `type_text` branch was fire-and-forget; it now
uses `adapter.type_text_step` when the adapter provides one.

Live run: Ollama `gemma4:26b`, 25/25 actions all via `type_text` with real
state deltas observed, invariant suite ran clean throughout. R1 was re-verified
unaffected (25/25) after the loop edit.

Run recipe: `python3 integrations/nexus/playtest_nexus.py`

## How to run (full recipe)

```bash
python3 integrations/nexus/spike_nexus.py          # raw HTTP protocol round-trip
python3 integrations/nexus/smoke_nexus_adapter.py  # same path through BaseAdapter
python3 integrations/nexus/verify_dod.py           # Phase-0 DoD: one full hack loop
python3 integrations/nexus/verify_round1.py        # R1: playability gate
python3 integrations/nexus/verify_round2.py        # R2: full 8-mission spine, all 3 modes
python3 integrations/nexus/verify_round3.py        # R3: exploit-hunter + replay determinism
python3 integrations/nexus/playtest_nexus.py       # LLM playtest tier
```

`invariants.py` holds the per-command/per-step invariant checks shared across
rounds; `ugt.config.yaml` is the config shim (action ids must stay in lockstep
with `NexusHttpAdapter._compose_command`); `strategy-guide.md` is the guide
handed to the LLM playtester.

For the live-server bring-up recipe (Docker Postgres, schema push, deterministic
seed, starting `next dev` with the test env, PID verification) see `HANDOFF.md`.

## Disambiguation

Unlike `spacerquest` (which shared a name prefix with the now-deleted `spacerquest_old`), NEXUS has no
naming-collision risk in this repo — a single unambiguous integration, no special banner needed.

## Archive

`archive/ROLLOUT.md` is the original pre-work planning doc (headed "Status: not
started"). Every deliverable it lists is now built — it retains only
historical value.

# NEXUS UGT Trial — Test Results Log

Consolidated, commit-traceable record of every ladder round's final **verified**
outcome. Full per-round narrative + the findings registry are in `README.md`;
the resume-here state is in `HANDOFF.md`. Every round was run against the **live**
game over HTTP (Docker Postgres + `next dev`, AI-off deterministic env,
PID-verified) and **independently re-run by a review agent** before being logged.

Repos: NEXUS game `~/Dev/Games/nexus-world-builder` (on `main`, pushed to origin);
UGT framework `~/Dev/Games/_UGT Universal Game Tester` (on `main`, local-only, no
remote). Game suite baseline at trial end: **unit 1265 / integration 173, 0 skip**,
typecheck + lint clean.

## Ladder — ALL ROUNDS PASSED (trial ladder COMPLETE)

| Round | Date | Script | Result (live) | Findings | UGT commit | Game commit(s) |
|---|---|---|---|---|---|---|
| **Phase 0** | 2026-07-08 | `spike_nexus.py` · `smoke_nexus_adapter.py` · `verify_dod.py` | **spike 8/8 · smoke 5/5 · DoD 7/7** — bring-up + one real hack loop (scan→connect→exploit→compromise) through the adapter | NX-P0-1 (fixed) | `6740027` | `a4fc7a2`, `4d6a227` |
| **R1** | 2026-07-09 | `verify_round1.py` · `invariants.py` | **25/25** (+ spike 8/8) — one full `the_breadcrumb` loop; rewards-exactly-once; per-command invariants clean; byte-identical same-seed replay + 8-seed variance | NX-R1-1, NX-R1-2 (fixed) | `cc7ba7e` | `780bc31` |
| **R2** | 2026-07-09 | `verify_round2.py` · `invariants.py` | **36/36** (+ spike 8/8) — FULL 8-mission spine to a **real win** (`isComplete`, `ending_liberation`, 8/8) under **all 3 difficulty modes**; XP scaling 4/5/8; multi-mission determinism prefix | NX-R2-1, NX-R2-2 (fixed) | `87cd758` | `0e5dd92` |
| **R3** | 2026-07-09 | `verify_round3.py` · `invariants.py` | **9/9** (+ spike 8/8) — real `ExploitHunter`, 4 episodes × 90 = **360 steps, ZERO findings**; 9 invariants/step; all 20 verbs + all 8 refusal-probe kinds inert; byte-identical episode-0 replay (90/90) | none (game clean) | `c86a86c` | — (no game change) |

## Findings surfaced by the ladder

**Game fixes (each pinned by a test in the game suite):**
- **NX-P0-1** — the hack surface was gated behind un-grantable tutorial state → `reset-episode` `baseline:"post_tutorial"`.
- **NX-R1-1** — the story seed dropped canonical mission ids → extracted `story-mission-seed.ts` preserving `id`.
- **NX-R1-2** — missions with a skipped optional objective completed **silently** (no banner) → trust the required-only status.
- **NX-R2-1** — `talk` could never unlock (AND-gated on the ungrantable `met_mercury`) → OR-logic across reachable met flags.
- **NX-R2-2** — `talk` hard-required a live AI provider → delivers scripted lines + emits `contact_npc` when AI is disabled.

**Characterizations (by-design / coverage notes, not defects):**
- **NX-OBS-1** — a refused command still ticks `rngCounter` by design (the per-command clock); invariants exclude it.
- **NX-OBS-2** — the exploit roll is genuinely seeded; ~90% success at the P0 baseline (variance verified via multi-seed sweep).
- **NX-R3** — R3 surfaced zero game defects; two issues fixed harness-side (a parse regex + policy arg-composition bias).
- **NX-R3-OBS** — R3 is a genuine robustness walk (plateaus at 1/8 vs R2's scripted 8/8), not "R2 with probes"; late-game `talk`/`choose` success paths are R2-covered, not re-covered — strengthen later via longer episodes / mid-spine seeded reset.

## Post-ladder: trial-scaffold extraction re-validation (2026-07-09)

The ladder's shared skeleton (the `ck`/`finding`/footer gate runner, the
invariant sweep + hunter-signature wrapping, the first-divergence determinism
compare, and the per-script `_normalize_state` copies) was extracted into
**`ugt/core/trial.py`** (`GateRunner` / `InvariantSuite` / `first_divergence`;
`normalize_state` consolidated into `invariants.py`) — net **−92 lines** of
per-game glue, zero intended behavior change. Validated by re-running the FULL
ladder live (fresh server, PID-verified): **spike 8/8 · R1 25/25 · R2 36/36 ·
R3 9/9**, zero findings, same winning seeds (`-tut`, `-hc-0`), same R3 profile
(360 steps, 7 compromises, 30 seeded rolls), and both same-seed replays
byte-identical — an exact reproduction of the pinned results above. The
scaffold is the greenfield starting point for the next game's trial;
warzones/tarot-war/SpacerQuest scripts backport lazily (they are frozen,
passing, and commit-traceable).

## How to re-run (reproduce any result)

Per `HANDOFF.md` §"Live bring-up": `docker start nexus_ugt_pg` → from `apps/game`
`next dev -p 3100` with the deterministic AI-off env (`TEST_API_KEY`, the `:5455`
`DATABASE_URL`/`POSTGRES_*`, `AI_ENABLED=false AI_FILES_ENABLED=false
AI_DIALOGUE_ENABLED=false UGT_DETERMINISTIC=1`, `AUTH_SECRET`/`NEXTAUTH_SECRET`;
**not** `NODE_ENV=production`) → `lsof` the LISTEN PID → `python3
integrations/nexus/spike_nexus.py` then `verify_round{1,2,3}.py`.

## Status: NEXUS robustness/trial ladder COMPLETE (2026-07-09)

The game is winnable, byte-identical-replayable, and robust under a 360-step
random walk — all verified live over HTTP. Next tier (not part of this ladder):
the LLM balance-playtester (API-credit-gated), whose findings would drive the
deliberately-deferred progression-math rebalance.

## L-006: LLM playtest tier wired (2026-07-21)

`integrations/nexus/playtest_nexus.py` drives NEXUS through the L-002 direct-adapter
entry point (`playtest_game_with_adapter`) — NexusHttpAdapter is not registered under
any `engine.type`, so its ladder scripts build it directly (the same reason DDD needs
this path). `strategy-guide.md` (command surface + accept→scan→connect→exploit→cat
loop + the three R2 difficulty modes) and an additive, ladder-inert `playtest:` block
in `ugt.config.yaml` were added.

**DRIVE CHANNEL — `type_text`, the real terminal UX (root-cause fix, fix-round-1):**
L-006's accept text names `type_text`/`get_terminal_text` as the drive channel. The
first delivery instead used `action_mode="action_id"` and *disclosed the deviation*,
because the shared loop's `type_text` branch was fire-and-forget — it called
`adapter.type_text(value)` and never reassigned `current_state`, so `after == before`,
every `_compute_delta` returned `{}`, and any type_text-driven run was VACUOUS. The
review correctly ruled the literal criterion unmet. **Fix round 1 diagnosed that as a
real, fixable loop defect rather than an unavoidable limitation** and repaired the root
cause:

- `ugt/core/playtester.py` — the `type_text` branch now reassigns
  `current_state, terminated, truncated, step_info` from `adapter.type_text_step(value)`
  **when the adapter exposes it** (a `hasattr` guard). `NexusHttpAdapter.type_text_step`
  already returns the real `(state, term, trunc, info)` transition (nexus_http.py:191),
  so typed commands now produce GENUINE deltas. Adapters whose `type_text` is a pure
  keystroke-into-a-field (PlaywrightAdapter, RealClientAdapter — neither has
  `type_text_step`) keep the existing fire-and-forget behavior byte-for-byte. This is an
  **added input channel, not a contract change** (delta assertion, the
  `reasoning`/`expected_outcome`/`potential_bug` fields, and the bug-report shape are
  untouched) — exactly what the Standing Constraints permit. The earlier "editing the
  branch changes the contract for every engine" concern only applied to an *unguarded*
  edit; the `hasattr` guard makes it a no-op for every other engine (verified: DDD
  `legal_action` and the `action_id` path run unchanged).
- A new `action_mode="text"` + `_build_terminal_prompt` present the game AS a terminal
  and steer the LLM to `action_type="type_text"` with a full command line it composes
  from live state (`scan`, `connect <ip>`, `exploit <vuln>`, `accept <mission>`,
  `cat <file>`). Game-agnostic: the prompt lists the command vocabulary from
  `config.action_mappings` only; argument syntax lives in the game's own strategy guide,
  never in `playtester.py`. `action_id` / `legal_action` prompt selection is untouched.

This channel is strictly MORE faithful than the earlier action_id route: action_id runs
each verb through the adapter's `_compose_command` heuristic (which auto-fills the
target/file/mission) — the tester composing commands; here the LLM types the whole
command line, which is what a real player does. `get_terminal_text` is consumed every
step to build the prompt.

**Non-vacuous invariants:** the run hands the loop the SAME `invariants.SUITE` R3 hands
the ExploitHunter (`to_hunter_invariants()`); its wrappers read `info["command"]`/
`info["result"]`, which is exactly the `{command,result,state}` dict
`NexusHttpAdapter.type_text_step` returns (nexus_http.py:242). These are fail-capable
checks (e.g. `inv_rng_tick` requires rngCounter +1 EXACTLY, `inv_refused_state_inert`)
that held every step — exercised, not stubbed.

**Live ollama run (server up on :3100, PID-verified; `--provider ollama`, gemma4:26b,
25 actions):** PLAYTEST MET — `actions_taken=25`, **all 25 steps are `type_text`**,
**typed commands with a real state delta `=25`**, invariant suite ran with **0
violations**. gemma4:26b composed real command lines from live state every step
(`scan` → `discoveredServersCount +17`/`xp +25`; `connect 192.168.1.105` → `xp +15`;
`cat …/work_vpn.txt` → `storyFlags += found_meridian_credentials`), confirming the
delta is genuine, not `{}`. Report at `integrations/nexus/results/playtest-report.json`
(gitignored via root `results/`). A 5-action probe first confirmed the channel wiring
(5/5 typed commands, 5/5 with deltas) before the full run.

**R1 non-regression:** `verify_round1.py` re-run live after the change → **ROUND 1 MET —
25/25** (identical count), confirming R1 is unaffected by the shared-loop edit.

---

## L-014: LLM-playtest pre-flight audit (LESSONS.md §B) — 3 starvation defects found + fixed before any balance batch (2026-07-22)

The DDD balance rounds ended by discovering that two multi-hour batches (L-008, L-011)
had measured a pilot that could not see the game. Those lessons were generalized into
`LESSONS.md` §B (P1–P9, the information-integrity pre-flight) and this is the first
integration audited against it *before* spending a batch rather than after. Server was
brought up per HANDOFF and PID-verified (a 24h-old `next-server` was squatting :3100 and
was replaced, not trusted — LESSONS.md O1); `spike_nexus.py` **8/8** against the new PID
confirmed current code before any measurement below.

Dispositions, all cited against `nexus-world-builder@0e5dd92`:

### P1 · entity identity — **PARTIAL, mitigated**
State carries `discoveredServers` as a bare `string[]` of IPs (`player-state/route.ts:104-108`)
— no hostname, no **securityLevel**, no vulnerabilities, no files. `missions[]` carries
`objectivesCompleted`/`objectivesTotal` **counts only**, never the objective text
(`route.ts:110-118`). So the entire read layer of this game lives in terminal output, not
in state. Not a defect (the terminal *is* the player's channel and the LLM sees it) but it
makes P3 load-bearing, and the guide now says so explicitly.

### P2 · adapter drops nothing PUBLIC — **PASS (checked & clean)**
Diffed `NexusHttpAdapter._read_state()` against every field the route returns. The route
emits 14 top-level fields; the adapter keeps 13 and drops only `playerId` (an identifier,
not player-visible information). Unlike DDD's `_seat()` (which silently ate four PUBLIC
fields), this adapter is lossless. The starvation here is upstream of the adapter.

### P3 · truncation — **FAIL. Fixed. This was the real defect.**
`playtest.terminal_char_budget` was **600**, and the budget keeps the **tail**. Measured
live against the running game, not estimated:

- `scan` (the discovery command) returns **1,666 chars / 27 servers**. At 600 the LLM saw
  only the last ~11. The dropped head contained **every low-security host on the network** —
  `home-router` (1/10), `LG-SMART-TV` (1/10), `DESKTOP-JMILLER` (2/10),
  `digital-surveillance-agency-desktop-131` (2/10) — while the surviving tail was the
  high-security remainder. Since success rate is `0.60 + (level - serverSecurity)*0.10`
  (§4.1 below), **the pilot was structurally prevented from choosing targets by the one
  term that dominates its odds**, and could not recover the security levels from state
  either (P1: bare IPs). `DESKTOP-JMILLER` — the host the previous L-006 run compromised —
  was itself in the dropped head.
- `analyze` measured 378 chars on a security-5 host (6 vulnerabilities) so it fit, but it
  emits `max(1, 11 - securityLevel)` lines (`worldgen/server-generator.ts:463`), i.e. up to
  ~520 chars on a security-1 host — the exact hosts a competent player should prefer. As
  `analyze` is the **only** source of vulnerability names (`executors.ts:557-613`) and
  `exploit <vuln>` requires an exact type-string match (`executors.ts:2309`), a truncated
  `analyze` is unplayable by construction. It sat one low-security target away from biting.

**Fixes:** `terminal_char_budget` 600 → **2400** (sized against the measured 1,666 worst
case, with headroom); `guide_char_budget` 3500 → **9000** (the rewritten guide is 8,501
chars). Framework-level: `ugt/core/playtester.py::_fit()` now applies both budgets in all
three prompt builders and prints a `[WARN]` naming the overflow the first time either
bites — previously every prompt builder did a bare slice, so **truncation was completely
silent for every game**. `playtest_nexus.py` additionally fails CLOSED pre-flight if the
guide exceeds its budget.

### P4 · action channel — **PASS (by construction)**
`action_mode="text"`: the LLM composes the entire command line and it is sent verbatim via
`type_text_step`. There is no argument-filling layer that could drop what the LLM chose
(this is the DDD D-L3 failure mode, and NEXUS's `_compose_command` heuristic is bypassed
entirely in this mode).

### P5 · no god-view leak — **PASS (checked & clean)**
`player-state` is a strict subset of what the terminal shows: `discoveredServers` is read
from the player's own `gameState` blob, written only by `scan`/`connect`
(`executors.ts:1902-1922`) — no `db.gameServer.findMany` in the route; `missions` is the
`PlayerMission` join, so un-offered missions are absent; file contents and vulnerability
lists are never selected; `rngSeed` is structurally excluded (`route.ts:71`). **No
`redact_state_fields` needed.** (`rngCounter` is exposed and is not player-visible, but the
seed is not, so it confers no advantage; it is already in `ignore_delta_fields`.)

### P6 · the guide taught no rules — **FAIL. Fixed.**
Same class as DDD D-L5. The old guide taught the command loop but not one line of the math
that decides every hack. It also **misinformed** the pilot: it asserted hardcore was
"~30% base hack odds … fails ~70%", whereas `success-calculator.ts:75-83` applies hardcore
as a flat **−10%** term on a level-relative base — a pilot told to expect 30% will
over-retry and mis-price every target. Rewritten to teach, with citations to the game's own
source: the rate formula and its clamps (`success-calculator.ts:85-124`); level-vs-security
as the dominant ±10%/level term; the +15%/skill-level bonus and that skill level *starts at
1* (`player.ts:692`), so every player silently carries +15%; the two independent skill
tracks (`exploitation` ← exploit/crack, `persistence` ← backdoor/escalate) and their point
values; `escalate` costing +1 effective security (`executors.ts:2556-2563`); the flat XP
curve `floor(xp/1000)+1`; refusal-vs-failed-roll; and that `analyze` is the sole source of
vulnerability names.

### Game-side finding — NX-L14-1 · the progression economy is inert
Surfaced by the P6 pass over the game's source, and it reframes the integration's own
deferred work item ("progression-math rebalance: tool tiers / skill cap / hidden +15%
baseline / XP curve"). Two of those four knobs are **not reachable by any player action**:

- **Credits can never be spent.** The command registry is 35 verbs; a grep for
  `buy|shop|purchase|upgrade|store|market` over `registry.ts` returns **zero** matches.
  Credits are granted (mission rewards `mission.ts:1026-1032`, starting `BigInt(1000)`
  `player.ts:102`) and displayed by `status`, never debited. The debit paths
  (`player.ts:380-382`, `:781-786`) are tRPC procedures no command calls.
- **The tool-tier axis is dead.** `TOOL_BONUSES` spans 0 → +50%
  (`success-calculator.ts:59-70`), but all four hack call sites hardcode `ToolTier.BASIC`
  (`executors.ts:2334`, `:1483`, `:1652`, `:2560`). No command changes it.
- **Skill allocation is not player-directed** — `skills` is display-only
  (`executors.ts:675-716`); points accrue passively per verb.
- **"Skill cap" does not exist** as named: skill level is uncapped
  (`player.ts:692`); the only clamp is on the final rate, `[0.05, 0.95]`
  (`success-calculator.ts:100`).
- Additionally, **a failed roll costs nothing** — no credits, cooldown, trace or detection
  penalty in any of the four executors — so retry-spamming a low-percentage attempt is
  strictly correct play.

Recorded here as a characterization for the game owner, **not** fixed: rebalancing tool
tiers is meaningless until a verb exists that changes a tool tier. The rewritten guide asks
the pilot to report these as observations (§5) rather than being told they are defects, so
the upcoming batch produces independent evidence rather than an echo.

### Interpretation guardrail (P8)
The L-006 run (gemma4:26b, 25 actions) predates every fix above and was a **channel**
validation, not a balance measurement. Its numbers must not be pooled with any post-L-014
batch.

### P7 · live competence probe (post-fix sanity run) — channel HEALTHY, pilot NOT YET COMPETENT

`playtest_nexus.py --provider ollama --model qwen3-coder:30b --max-actions 40`, against the
PID-verified server, 363.5s. **PLAYTEST MET** — 40 actions, 34 `type_text` commands, **34/34
with a real state delta**, invariant suite ran with **0 violations**, 0 bugs flagged, and
**0 truncation `[WARN]`s** (confirming the new 2400 budget clears the measured 1,666-char
`scan`). Per P7, the verdict comes from the reasoning text, not the exit code:

**The P3 fix demonstrably changed play.** 12 reasonings reference server security level, and
the pilot now selects targets by the §4.1 gap in its own words — step 2: *"The home-router at
192.168.1.1 … has the lowest security level (1/10), making it an ideal target for a beginner
player at level 5"*; step 38: *"security level 2/10, which is manageable for level 6 player."*
**Both of those hosts were in the head that the old 600-char tail-budget discarded.** This is
the causal evidence the audit wanted: pre-fix the pilot could not have named them.

**But §4.2–4.4 went unused.** Zero mentions of a success rate, odds or any percentage; zero of
the `persistence` track; zero of skill points or the +15%/level bonus; zero recognition that
`escalate` is one notch harder. The pilot uses the *qualitative* half of §4.1 ("lower security
is better") and none of the arithmetic the guide now supplies.

**Coverage gap: `cat` was never issued once in 40 actions** — the verb that completes missions
(guide §2 step 6). Nor were `crack`, `backdoor`, `download` or `talk`. Verb distribution:
connect 8, ls 8, scan 7, analyze 6, exploit 6, escalate 2, missions 1, accept 1, disconnect 1.
The run compromised 2 servers but completed **0 missions** and gained **0 credits**, cycling
scan→connect→ls→analyze→exploit over the same two hosts (steps 35–40 are a visible loop).
Recorded as a pilot-competence observation, **not** yet a game finding — `ls` ran 8 times
without a `cat` following it, which points at the model rather than the game, but it must be
re-checked against a stronger model before anyone concludes either way (M9).

**Model-adequacy verdict (O6/B): `qwen3-coder:30b` is adequate to prove the CHANNEL and not
adequate to judge BALANCE for this game.** It is a local coding model; it reads state, composes
valid command lines and picks targets sensibly, but it does not do the multi-step arithmetic or
the skill-track planning the balance question needs, and it does not close the mission loop. Per
P9, this run establishes that the pilot can see and act — nothing about NEXUS's balance. **The
real batch should run on Anthropic (credit-gated) and must re-verify P7 before its numbers are
used.**

**Checked, not a finding:** every step's `unexpected_deltas` record contains `rngCounter`
despite `ignore_delta_fields`. Tracing it, `ignore_delta_fields` is applied to the contradiction
detector's `material_delta` (playtester.py:537-541) while the per-step surprise record is
deliberately left raw (playtester.py:612-614, "Per-step raw records stay in the log"), and the
summary's own ubiquity filter reduces 40 → the correct 10. Working as designed. Noted only
because the two noise filters are independent mechanisms: a game whose administrative field
ticks on <80% of steps would be honoured by the config knob but missed by the summary heuristic.

**R1 non-regression:** `verify_round1.py` re-run live after all changes → **ROUND 1 MET —
25/25**, the same count as every prior run.

### P10 · the pilot had no memory — found on review of the sanity run, fixed (2026-07-22)

Owner review of the P7 run asked whether the pilot had enough context to decide well, citing a
SpacerQuest-era observation that the LLM repeated already-completed, inconsequential actions.
Re-measuring the 40-step NEXUS log confirms it, and it **partly supersedes the model-adequacy
verdict recorded above** — the pilot was not only weak, it was amnesiac.

Repeat structure of the run (`Counter` over the action log, ignoring `rngCounter`):

| action | tries | at steps | material delta | consecutive? |
|---|---|---|---|---|
| `ls` | 8 | 3,6,16,19,28,32,36,39 | 0/8 (display-only) | **no** |
| `scan` | 6 | 1,7,14,20,26,37 | 6/6 | **no** |
| `analyze` | 6 | 4,9,17,22,29,33 | 6/6 | **no** |
| `exploit` | 5 | 5,10,18,23,30 | 5/5 | **no** |
| `connect 192.168.1.1` | 4 | 2,8,27,35 | 4/4 | **no** |
| `connect 192.168.1.105` | 4 | 15,21,31,38 | 4/4 | **no** |

**Zero consecutive repeats anywhere in 40 steps**, so `noop_streaks` — the only memory signal in
the prompt — fired **zero times** while the agent cycled the same 6-step loop over the same two
hosts five times. The two guards fail for structural reasons, not tuning: the recent-actions
window *slides* (default 5, shorter than this 6–7 step cycle, so each repeat scrolled out before
the next), and the no-op counter is *consecutive* and resets on any productive step
(`playtester.py`, the `else: noop_streaks[noop_key] = 0` branch). Note `_noop_warning_block`'s own
docstring already predicted "a pattern that repeats every 6+ steps" — the mechanism chosen does
not cover it. Also: `connect <ip>` scores a material delta every time (`currentServerId` moves)
even when re-treading an owned host, so **material delta ≠ progress**.

The cumulative counts existed in `action_counts` for the report the whole time and were simply
never shown back to the agent.

**Fixes (all game-agnostic core + config, no game logic in the framework):**
- **`_action_ledger_block`** — a cumulative digest in all three prompt builders: per distinct
  action, attempts, how many *changed state*, and the last step tried. Bounded by distinct-action
  count (cap 20, overflow disclosed), so it does not grow with run length. Display-only verbs are
  labelled rather than scored as unproductive.
- **`playtest.history_window`** (default 5, back-compatible) — NEXUS set to **14**, ~2× the
  observed cycle.
- **`playtest.objective`** — the win condition and a priority order, rendered high in the prompt;
  the guide states it from the bottom, behind the state JSON and terminal buffer.
- **`playtest.available_actions_path`** → `unlockedCommands` — the verb list now comes from the
  game's own live unlock list instead of the static 20-id config vocabulary.

**Validation:** replaying this exact 40-step log through the new ledger renders the loop
explicitly (`'ls' — tried 8x … last at step 39`, `'connect 192.168.1.105' — tried 4x …`).
Fail-capable assertions cover: empty ledger renders nothing, the cap is disclosed rather than
silent, `history_window` widens and defaults to 5, and `available_actions_path` falls back
cleanly when absent or unresolvable. `py_compile` clean across the repo.

**Still to verify live** (blocked while the NX-L14-1 economy work is in flight in the game repo):
re-probe `unlockedCommands` over the wire, re-run spike + R1, then a fresh sanity run to confirm
the `cat` gap and the cycling actually close. **The P7 competence verdict above should be treated
as provisional until that re-run** — with no memory in the prompt, this run could not have
distinguished a weak model from a blind one.

#### P10 correction (same day, owner review): repetition was NOT the defect

The first P10 fix framed the ledger as an anti-repetition nudge ("prefer an action you have NOT
tried"). **That was wrong and is corrected here** (M9 — record the correction, don't delete the
mistake). In NEXUS, `ls`/`scan`/`analyze` are scoped to the host you are connected to, so
re-running them at a new server is *correct play*; a prompt that discourages it suppresses the
behaviour under test. The owner's actual point was narrower and deeper: **the pilot needs
contextual knowledge of the whole run, not just the current turn.**

Re-reading the run under that lens, the cycling is a *symptom*, not the disease. `analyze` at
step 4 printed the vulnerability names for that host; by step 9 the terminal buffer had rolled and
that knowledge was gone. `scan` at step 1 printed every server's security level — the input to the
success formula — and it was gone too, because `discoveredServers` is a bare IP list (P1). The
agent re-ran recon because it genuinely no longer knew, which is the right response to not knowing.

**Revised fixes:**
- Ledger **reframed as knowledge, not judgement** — header "What you have already established this
  run", explicitly noting that re-running a command somewhere new is normal play. Asserted in test:
  the rendered block contains none of "do not" / "prefer an action" / "stuck".
- Ledger **keyed by (action, context)** via new `playtest.action_context_path` →
  `currentServerId`. `ls` at four servers now reads as four observations; four `ls` at one server
  is still visible. Without this the two are indistinguishable.
- New **`playtest.terminal_recall_budget`** (default 0 = off; NEXUS **3000**) — retains the latest
  terminal output per (action, server), so terminal-only knowledge survives the rolling buffer.
  Populated with no extra adapter call (at iteration N+1 the fetched terminal text *is* action N's
  output). Oldest entries drop first and the drop is disclosed in-prompt.
- `playtest.objective` reworded — dropped "repeating recon on hosts you already own does not
  advance it", added that recon is how you learn what to do next and should be run whenever you
  reach somewhere new or lack information.

---

## L-015: NX-L14-1 economy landed (game side) + two UGT-side starvation defects it exposed (2026-07-22)

The NX-L14-1 characterization was routed to the game repo and implemented there:
`nexus-world-builder` branch `feat/nx-l14-1-economy`, commit **`c95e9a5`** (not pushed).
`market`/`buy <tier>` verbs, a `Player.toolTier` column, the tier threaded into every
success-rate call site, and `toolTier` added to the `player-state` route. Game gates:
typecheck+lint clean, **unit 1265 → 1293, integration 173 → 184**.

**Two of my briefing facts were wrong and the implementer corrected them with evidence** —
recorded per M9:
- My "~9,000 lifetime credits" anchor came from `prisma/seed-missions.ts`, which is **dead
  code nothing imports**. The live table is `apps/game/data/missions/core-story.json`
  (via `story-mission-seed.ts`): 54,500 across nine core missions, of which ~**35,500** is
  genuinely spendable since the 20,000 finale ends the game. Prices were set against the
  real figure (1,500 / 6,000 / 12,000 / 25,000).
- I cited **four** hardcoded `ToolTier.BASIC` sites; there were **six** — `upload`
  (`executors.ts:2012`) and the `analyze` preview (`:246`) also had it. All six wired.

### Ladder non-regression (live, PID-verified server on the economy branch)
`prisma db push` + `prisma generate` + server restart (the stale Prisma client 500s
`player-state` until the client is regenerated — worth knowing for the next schema change).
**spike 8/8 · R1 25/25**, byte-identical same-seed replay. No regression.

### D-L15-1 (UGT) · `available_actions_path` would have HIDDEN the new economy — P1, self-inflicted
Introduced hours earlier in the P10 work with the rationale "never advertise a verb the game
will refuse", replacing the prompt's verb list with the game's live `unlockedCommands`.
Probed live, that field is a **hack-verb** list:
`scan, connect, disconnect, ls, cd, cat, clues, whois, analyze, download, exploit, crack,
escalate, backdoor` — it omits `status`, `missions`, `accept`, `talk`, `choose`, **and both
new economy verbs**. As a replacement it would have starved the pilot of most of the game
*including the feature this round exists to test*. **Fixed:** the knob now ANNOTATES and
never replaces ("the game currently reports these as unlocked: … this list may be partial"),
with a test asserting the full vocabulary survives. Lesson generalized: a partial list
becomes a starvation defect the moment it is treated as authoritative.

### D-L15-2 (UGT) · `toolTier` exposed on the wire, dropped by the adapter — P2, in the very
integration certified clean on P2 hours earlier
`"toolTier" in state` was **False**. The game added it to `player-state`, but
`NexusHttpAdapter._read_state()` builds an explicit dict and silently discards anything not
listed — the DDD `_seat()` defect reproduced exactly. The pilot could buy a toolkit and never
see that it owned one, and the `Tool: +N%` line in the odds breakdown would be unexplainable
from state. **Fixed:** `toolTier` carried through, and added to `key_state_paths` so it is in
the prompt's KEY VALUES line. **P2 is not a one-time check — it must be re-run every time the
game's state surface changes.**

### Guide/config lockstep (P6/P3)
The guide asserted "toolBonus: always 0 in practice — every caller passes `ToolTier.BASIC`"
and asked the pilot to flag credits as unspendable; both false as of `c95e9a5`. Rewritten:
new §4.2b (tier table, prices, that `market`/`buy` is the only credit sink, that a purchase
shows as `Tool: +N%`, that re-buy/downgrade is refused and inert), economy verbs added to §1,
and §5's balance prompts re-pointed at price-vs-power rather than at the dead axis. That took
the guide to 9,539 chars against the 9,000 budget — **P3 bit my own change** — so
`guide_char_budget` went 9,000 → 12,000 in the same edit.

Live wire check: `market` renders the catalogue; `buy commercial` on 1,000 credits refuses
("costs 1500 credits. You have 1000.") with credits and toolTier unchanged.

### L-015 post-fix sanity run — harness now ADEQUATE, model conclusively NOT

`--model qwen3-coder:30b --max-actions 40` on the economy branch. **PLAYTEST MET** (40
actions, 39/39 typed with deltas, 0 invariant violations, **0 truncation warnings**), but the
play got *worse*, not better: `ls` **21 times of 40 steps** (was 8), 1 server compromised (was
2), still **0 `cat`**, 0 missions, and `market`/`buy` never tried despite being in the guide,
the verb list and KEY VALUES.

**Hypothesis tested and REFUTED (M9):** that the enlarged prompt (~18.9k chars ≈ 4.7k tokens)
had overflowed Ollama's context window, since `_OllamaLLM` never sets `num_ctx`. Probed the
running server directly — `prompt_eval_count` came back 516 / 3,016 / 8,016 for 500 / 3,000 /
8,000-token prompts, i.e. **no truncation**, and `qwen3-coder:30b` reports a 262,144-token
context. The prompt is delivered intact. (Worth keeping in mind for a smaller local model:
`num_ctx` is still unset, so this refutation is model-specific, not general.)

**The decisive evidence is a live wire probe, not inference.** Steps 12–20 are nine
*consecutive* `ls` calls, each reasoning "I need to list files to find the target file". Driving
the identical sequence by hand through the adapter:
`ls` on DESKTOP-JMILLER returns four fully-qualified paths (`/Users/jmiller/Documents/work_vpn.txt`
…), and `cat /Users/jmiller/Documents/work_vpn.txt` succeeds, printing the credentials and a
`[PASSWORD] Discovered` story beat. **The game handed the pilot everything it needed and the
pilot did not take the step.** With the read layer confirmed intact end-to-end, this is a model
competence ceiling, not information starvation. `qwen3-coder:30b` is settled as unfit for the
balance tier here; the tier needs Anthropic.

Two notes for the next run:
- `ls` is in `display_only_verbs`, which exempts it from `noop_streaks` — correct for
  per-server recon (D-L4 correction), but it meant nine consecutive `ls` **on the same host**
  raised nothing. The context-keyed ledger did surface it (`'ls' at 192.168.1.105 — 9x`) and
  the model ignored it. The exemption should stay; the gap is the pilot.
- The success breakdown renders live as `[Player Lv5 | Exploit Skill Lv0 | Basic Tools]` /
  `Base: 90% = 90%` — confirming `base = 0.60 + (5-2)*0.10` exactly.

### D-L15-3 (guide) · my §4.2a "+15% floor" claim was WRONG — caught by the live breakdown
The guide stated skill level is `floor(points/100)+1` so "you start at level 1 and already carry
+15%". Live shows `Exploit Skill Lv0` and **no `Skill:` term in the breakdown at all**.
Root cause: `getSkillLevel` (`executors.ts:97-103`) returns `skill?.level ?? 0` — absent skill
row = **level 0 = +0%**. The `floor(points/100)+1` I cited (`player.ts:692`) is the *update*
formula applied after points are earned, not the starting value. Corrected in the guide, with
the genuinely useful consequence spelled out: because of that `+1`, the FIRST point-earning
success jumps Lv0 → Lv1 = +15% in one step, the largest early swing available.

**This is the second guide claim of mine to be falsified by live behaviour** (the first:
hardcore stated as "~30% base odds" when it is a flat −10%). Both were read from source and
both were wrong about what the running game does. **P6 additions must be verified against a
live breakdown, not only against the code that appears to produce it.**

---

## L-016: R2 re-run with economy coverage — NX-L15-1 found + fixed; ROUND 2 MET 46/46 (2026-07-22)

R2 was first re-run unchanged against the economy branch and came back **36/36 — exactly the
baseline**. That number was the finding: grepping `verify_round2.py` for `market`/`buy`/
`toolTier` returned **zero hits**, so a green R2 was certifying a game whose newest major system
it never touched. By R2's own definition in this repo ("every major mode/system driven to a real
outcome; no vacuous passes"), that is the failure mode the rung exists to prevent.

**Added an economy leg (10 checks, 36 → 46).** Driven on the post-spine player, who has real
mission income, so the purchase is made the way a player would make it: `market` is read-only
(credits AND tier unchanged); `buy commercial` debits **exactly** 1500 and sets the tier;
re-buying what you own and downgrading are both refused **state-inert**; climbing to
`black_market` charges its full 6000 with **no trade-in**; credits never go negative; and — the
check the whole feature exists for — a purchased tier reaches the odds math
(`Base: 90% | Tool: +20% | Difficulty: -10% = 95%`), with a `finding()` armed if the breakdown
ever reports `Basic` again, which is what fires if a call site is re-hardcoded.

**The first draft of that leg was wrong and R2 red-flagged it** — proof the checks are
fail-capable, so no separate mutation test was needed. It assumed a poor player, but the section
runs after three full spines (level 20, ~55k credits): `buy zero_day` succeeded and the follow-up
`buy commercial` was correctly refused as a DOWNGRADE. Rewritten to ladder UP from `basic`, with
an explicit precondition check that the player starts on `basic` so a future reordering fails
loudly, and the insufficient-funds case moved onto a fresh reset where the player really does
have 1000 credits.

### NX-L15-1 (GAME, fixed + pinned) · `reset-episode` never reset `toolTier`
The economy leg's last check failed: after `reset()`, credits returned to 1000 but `toolTier`
stayed `black_market`. `reset-episode/route.ts` resets `rngSeed`, `rngCounter`, `level`, `xp`,
`credits`, `difficulty` and deletes missions/servers/inventory/skills — the column added with
NX-L14-1 was never added to that baseline. Consequences, both squarely on the testing path:
- **every multi-episode run starts contaminated**, inheriting the previous episode's toolkit;
- **same-seed replay determinism breaks** — tool tier feeds the hack success rate, so a replayed
  episode can compute different odds than the run it replays. That is **R3's exit criterion**,
  where this would have surfaced as a mysterious non-deterministic replay far from its cause.

Fixed at `nexus-world-builder` **`5dfd489`** (`toolTier: "basic"` in the reset baseline), pinned
by an integration test that seeds `zero_day`, resets, asserts `basic`, **and** asserts credits
still land on the documented 1000 baseline so a row-wiping "fix" cannot pass it. Game gates:
typecheck clean, lint 0 errors, unit **1293/1293**, integration **184 → 185/185**.

### Self-inflicted: a test suite cleared the LIVE dev database
Between those runs, R2 failed with `'exploit weak_password' failed within 15 attempts`. At the
reference seed that hack runs at 90% (`base = 0.60 + (5-2)*0.10`), so 15 consecutive failures is
~1e-15 — the arithmetic is what said "this is not a failed hack". It was not: `connect` was
returning **"No server at 192.168.1.105"**. Cause: an earlier attempt to run the new pinning test
used the wrong vitest config and passed `DATABASE_URL` pointing at the **live dev database**; the
integration suite's global setup clears all tables before running, got that far, then errored on
config — wiping the seeded `GameServer` rows. Recovered with `db push` → `seed.ts` →
`seed-story.ts` (100 servers + tutorial + all three acts); spike 8/8 and R2 46/46 after.
Nothing irreplaceable was lost (a dev DB that exists to be seeded), but the failure **presented
as a game bug rather than as data loss**, which is the dangerous part. Generalized to
`LESSONS.md` O9.

**ROUND 2 MET — 46/46.** Full 8-mission spine to a real win (isComplete + ending_liberation +
8/8) across normal/tutorial/hardcore, rewards once, mode-invariant mission payouts, M1-M4 prefix
byte-identical. **Next rung: R3.**

---

## L-017: R3 with economy coverage — ROUND 3 MET 9/9; + probe of the three queued progression requirements (2026-07-22)

**R3 ran twice.** First on the frozen 20-id vocabulary: **MET 9/9** — 4 episodes x 90 steps,
zero invariant violations, byte-identical episode-0 replay. That is the direct confirmation that
NX-L14-1 + the NX-L15-1 reset fix did not disturb multi-episode determinism, which is exactly
what the toolTier leak was threatening.

Then extended per O10 (`market` id 20, `buy` id 21; action_space 20 -> 22). **Two iterations
were needed and R3's own gate caught both**, which is the rung working as designed:
1. Adding the ids + arg composition was not enough — `[FAIL] never attempted: ['market','buy']`.
   R3's policy is phase-aware, not uniform over `action_ids`, so a verb absent from a selection
   pool is reachable in principle and dead in practice — the same shape as the hardcoded
   `ToolTier.BASIC` defect this whole thread started from.
2. Fixed by adding both to `EXPLORE` (the 10% branch that exists to guarantee rare verbs fire).

`buy` picks its tier UNIFORMLY rather than affordably, so most buys are refusals and
`inv_refused_state_inert` asserts each left credits and `toolTier` untouched — a refused purchase
that still debits is the failure mode that matters for an economy.

**ROUND 3 MET — 9/9.** 360 steps, 22/22 actions covered (`market` x2, `buy` x2), 8 refusal-probe
kinds fired, zero violations, episode-0 replay byte-identical and non-vacuous.
**NEXUS trial ladder COMPLETE on the economy branch.**

### Probe: the three queued progression requirements (owner-specified, for a later tier)

**(1) Command discovery/unlock — VERIFIED WORKING, with one real defect.**
At `baseline:"fresh"` (`unlockedCommands: []`), locked verbs correctly refuse:
`scan` / `exploit weak_password` / `cat /etc/passwd` all return `success:false`.
**Defect NX-L17-1: the NX-L14-1 economy verbs bypass the unlock gate entirely.** `market`
returns `success:true` on a fresh player with ZERO unlocked commands, printing the full toolkit
catalogue. `buy` reaches its price check (refused for funds, not for being locked). Both were
registered `category:"system"` and ungated. Mechanically harmless today — a fresh player has no
income — but it contradicts the progressive-unlock model and leaks the economy's existence before
the game reveals it. `status`/`help` are also ungated, presumably deliberately.
**Design question for the owner (not filed as a defect):** a locked command returns
`Command not found: scan. Type 'help' for available commands.` — indistinguishable from a typo.
That is deliberate (`handler.ts:128/140`; locked commands masquerade as unknown), but it is the
inverse of the philosophy stated in requirement (2), where the owner explicitly wants a meaningful
"blocked" message rather than pretending the thing does not exist. Worth confirming which
principle wins for commands.

**(2) Quest-gated areas — ALREADY SATISFIED, and better than specified.** The game already
distinguishes gated from nonexistent, with exactly the message style requested:
```
connect 10.42.0.1   (real host, story-gated)   -> success:false
    Connection to 10.42.0.1 blocked.
    Access denied. You don't have the required access level.
    [HINT] Progress through the story to unlock this target.
connect 10.99.99.99 (no such host)             -> success:false
    Connection failed: No server at 10.99.99.99
```
R3 already fires a `connect_undiscovered` probe (x6 this run) and asserts inertness.
**Two gaps, neither a game defect:** (a) no gate asserts the two messages are DISTINGUISHABLE —
a regression that collapsed "blocked" into "No server at" would pass every rung today; (b)
`baseline:"post_tutorial"` pre-seeds `discoveredServers` with ALL 10 story IPs
(`getAllStoryServers()`), so the ladder exercises ACCESS gating but never DISCOVERY progression.
Note discovery and access are separate gates here — a host can be discovered and still blocked,
which is good design and worth keeping in mind when specifying the eventual test.

**(3) LLM awareness of unlocked commands + quest lines — NOT YET MEASURABLE.** Partly advanced
today: `playtest.available_actions_path` now annotates the prompt with the game's live
`unlockedCommands`. Three gaps remain before the owner's judging criterion ("follows at least
some new quest lines and some new commands; side quests optional") can be scored:
- `unlockedCommands` is a PARTIAL list (D-L15-1) — it omits `status`/`missions`/`accept`/`talk`/
  `choose` and both economy verbs, so it cannot serve as the authoritative "what is unlocked now"
  signal that requirement (3) needs. Either the game should make it complete, or the tester must
  merge it with the static vocabulary (which is what it does today).
- `missions[]` carries `missionId` + `status` + counts only, never objective TEXT (P1), so the
  pilot sees quest IDs but not what they ask. Following a newly revealed quest line requires
  reading the terminal after `accept`/`missions`.
- **No metric exists** for "did the pilot engage a newly unlocked command / newly revealed quest".
  This needs new instrumentation in the playtest report: snapshot `unlockedCommands` and
  `missions[]` per step, diff for newly-appearing entries, and score whether the pilot used any
  within N steps. Recommend building this as an explicit playtest metric rather than judging it
  by eye — it is the same "measure it, do not infer it" rule as P7.

---

## L-018: NX-L16-1 gated-access messages + hint throttling — full ladder green (2026-07-22)

Owner-directed UX change, implemented game-side on `nexus-world-builder`
`feat/nx-l16-1-hint-throttle` (`5d7f9e2`, off the economy branch, unpushed): locked commands now
return an access-denied message instead of masquerading as a typo, and the `[HINT]` line on both
gated-command and gated-address refusals is throttled to attempts **1, 5, 10, 15…** (owner chose
that cadence over 1/6/11; note 1→5 is only 4 apart, which is deliberate and guarded by a test so
nobody "fixes" it). Two INDEPENDENT counters — one for any gated command, one for any gated
address — chosen over a single shared tally so a player hammering gated IPs cannot burn the
command hint and never see it. Counters live in `Player.gameState` and are explicitly zeroed by
`reset-episode`, applying the NX-L15-1 lesson directly.

**Verified live over the wire, not from the report.** Interleaved on `post_tutorial` with a gated
address (`connect 10.42.0.1`) and a gated command (`talk sp3ctr3`):
```
address hints 1..10: H . . . H . . . . H
command hints 1..10: H . . . H . . . . H
```
Both at 1/5/10, neither burning the other, both re-firing after a reset. The refusal text prints
every time; only the hint throttles. A genuine typo still returns `Command not found`, so the
unknown-command path (which UGT's garbage/unmapped probes hit) is intact.

**Two of my own probes were wrong before I got a clean read** — recorded per M9 because the
mistake is instructive. First I used `cat` at `post_tutorial`, but `cat` is already unlocked
there, so it hit a "requires an active connection" refusal and never touched the gated path. Then
I moved to `fresh`, where `connect` is ITSELF a gated command, so both probe lines incremented the
same command counter and never reached the address gate. Both times I nearly filed a counter leak.
The tell was that the combined sequence landed on exactly 1, 5, 10, 15, 20 — too clean for two
broken counters. A valid test needs a baseline where `connect` is unlocked but the TARGET is
gated, plus a command still gated there: `post_tutorial` + `talk`.

**Ladder re-run, full: spike 8/8 · R1 25/25 · R2 46/46 · R3 9/9**, episode-0 replay
byte-identical. That last point is the one that matters: prompt/terminal output now depends on a
PERSISTED counter, so a byte-identical replay is direct evidence the counters increment
deterministically from the command sequence and are properly reset — exactly the property
NX-L15-1 destroyed for `toolTier`. Game gates: typecheck clean, lint 0 errors, unit 1293 → 1309,
integration 185 → 188.

**Guide updated in lockstep (P6) — it had gone stale within the hour.** It still told the pilot
that a command it cannot use replies `Command not found` and that this is "a wasted step, not a
bug", which after this change would make it misread every `blocked` message. §3 rewritten into an
explicit table of the SIX distinct "no" answers (typo / gated command / gated host / nonexistent
host / unmet precondition / failed roll) with which ones justify a retry, plus: "blocked" is
content not yet reached and must NOT be filed via `potential_bug`, and a missing `[HINT]` on later
attempts is intentional. Guide 9,966 → 11,025 chars, still inside the 12,000 budget.
**Third time today a guide claim was falsified by live behaviour** — P6's "verify against the
running game, not the source" is earning its place.

### Open before the ladder is truly closed (not regressions — coverage + one defect)
1. **NX-L17-1** (game): `market` succeeds with zero unlocked commands; the economy verbs bypass
   the unlock gate. More visible now that other commands say "blocked".
2. **No gate asserts "blocked" stays distinguishable from "No server at"** — a regression
   collapsing them passes every rung today.
3. **The hint throttle has no ladder coverage** — verified by the game suite and by hand, but no
   UGT gate would catch a regression to hint-every-time. O10: new behaviour shipped, denominator
   did not move.
4. Owner decision pending: `help <locked-command>` still replies `Unknown command: <name>` — the
   one place the old "pretend it does not exist" behaviour survives. Should browsing help reveal
   the command exists, and should it burn a hint?

---

## L-019: coverage gaps closed — NX-L17-1 fixed, R2 46 -> 54; model corrected to gemma4 (2026-07-22)

Closes the three items L-018 left open.

### NX-L17-1 (GAME, fixed) · the economy verbs bypassed the unlock system
`market`/`buy` shipped `category:"system"` and ungated, so a player with an EMPTY
`unlockedCommands` list could open the black market — verified live before the fix. Both now
carry `unlockRequirements` at tutorial-complete parity with the core hack verbs (the earliest
point a player has any income). Fixed at `nexus-world-builder` **`81e38c0`**.

**A consequence worth recording**: gating them forced `POST_TUTORIAL_UNLOCKED_COMMANDS` to grant
them explicitly. Without that, R2's economy leg and R3's `market`/`buy` coverage would have gone
on reporting green while exercising a LOCKED subsystem — the same vacuous-pass shape that let the
economy sit untested behind a green 36/36 R2 (O10). Closing one gap can silently open another;
after gating anything, re-ask what the gates are now actually driving.

### R2 gated-access coverage: 46 -> 54 checks, ALL PASS
Player-facing refusal semantics had no gate at all. Added to R2 (the content rung):
gated host is refused with access-denied; a nonexistent host gets a DIFFERENT "no such server"
message; **the two are distinguishable and neither leaks the other's wording** (the regression
guard — collapsing them would have passed every other check in the ladder); both refusals are
state-inert; gated-address `[HINT]` fires on 1 and 5, silent on 2-4; a gated COMMAND says blocked,
NOT `Command not found`; a genuine typo STILL says `Command not found` (unknown != gated, which
protects UGT's own garbage/unmapped probes); and gated-command hints throttle 1/5 **independently
while the address counter already sits at 5** — the condition that would expose a shared tally.

### Full ladder after all of it
**spike 8/8 · R1 25/25 · R2 54/54 · R3 9/9**, episode-0 replay byte-identical. Game gates: unit
1309/1309, integration 188/188, lint 0 errors, typecheck clean.
R3 note: `market`/`buy` are now gated refusals early in a walk rather than successful purchases —
still real coverage, and `inv_refused_state_inert` holds them to being inert.

### Model: the balance tier was being judged by a CODING model, by my own hand
`gemma4:26b` (25.8B, gemma4 family, 262k ctx) was installed all along **and is already the default
in `playtester.py`**. The L-014/L-015 runs used `qwen3-coder:30b` solely because I passed
`--model` on the command line. That is the whole explanation for the P7 result: two 40-action runs
that never once issued `cat`, completed 0 missions, and still reported PLAYTEST MET with 0
violations.

Fixed by documenting rather than by changing a default: `playtest_nexus.py`'s header and its
`--model` help now say to leave the flag unset, name `gemma4:26b`, and state explicitly that a
coding model is unfit for this tier with the evidence attached. A bare default is too easy for a
future session to override exactly as I did.

**Interpretation guardrail:** every P7 competence observation in L-014/L-015 is a qwen3-coder
number and must NOT be pooled with, or compared to, any gemma4 run. The channel findings (deltas,
invariants, truncation) stand; the competence verdict must be re-established on gemma4.

### Still open
1. ~~**Requirement (3) instrumentation**~~ — **BUILT in L-020 below.**
2. **Owner decision**: `help <locked-command>` still replies `Unknown command: <name>` — the one
   surviving place with the old "pretend it does not exist" behaviour. Should help reveal that a
   command exists, and should it burn a hint?
3. A real balance batch still needs Anthropic credits; gemma4 can now be re-baselined locally.

---

## L-020: progressive-content engagement metric — requirement (3) is now MEASURED, not eyeballed (2026-07-22)

Closes L-017 item (3) / L-019 open 1. The owner's judging criterion for a full run — *"the LLM
player should be aware of both unlocked commands and unlocked quest lines … judging the tester
means they follow at least some of the new quest lines and some of the new commands (side quests
may be judged as optional and are not an LLM test failure)"* — had **no metric at all**. Scoring
it by reading the log is exactly what LESSONS.md P7 forbids: measure competence, do not infer it.

### What was built (game-agnostic core + NEXUS as the reference configuration)
`ugt/core/playtester.py::_RevealTracker`, driven entirely by a new
`playtest.revealed_content` list. **No NEXUS nouns in core** — a game names its own state paths,
and a second game adopts the metric by adding config only.

**REVEALED** — an item newly APPEARS in a config-named state collection. Two shapes, neither
special-cased in core: `kind: strings` (a flat list, NEXUS `unlockedCommands`) and
`kind: objects` + `id_field` (a list of dicts, NEXUS `missions` keyed by `missionId`). Items
present at reset are the STARTING KIT (`revealed_at_start`) and are never scored.

**ENGAGED** — the pilot did something about that item within the group's `window` steps AFTER the
reveal. Three rules, any of which can fire: `invoke` (the first token of the pilot's command
equals the item — a new VERB was typed), `mention` (the item id appears in the command — for
argument-shaped items), `progress` (one of the item's own `progress_fields` increased, or its
status entered `engage_status` — the GAME reports the pilot advanced it). `note_action` runs
BEFORE the step executes, so an item revealed *by* an action can never be credited to it.

NEXUS values and why:
- **commands** → `unlockedCommands`, rule `invoke`, window **12** (~2x the observed 6-7 step recon
  cycle). An ATTEMPT counts even if refused: the behaviour under test is "did the pilot notice new
  content and try it", and a refusal is the game's answer, not the pilot's failure.
- **missions** → `missions`, rule `progress` on `objectivesCompleted` (+ `status: completed`),
  window **20** (one compromise→`cat` chain plus recon). It must be `progress`, not "did it
  mention the id": `missions[]` carries **no objective text** (P1), and this is precisely the
  L-015 failure shape — a pilot that re-issued `accept the_breadcrumb` 11 times, never issued
  `cat`, and left `objectivesCompleted` at 0 while the run reported PLAYTEST MET.
- **Optional (side quests)**: NEXUS state carries no story/side marker, so the split comes from
  `optional_ids` — the 5 ids in `apps/game/data/missions/side-missions.json`. Optional items are
  reported (`optional_revealed`/`optional_engaged`) but **never enter the denominator**. Staleness
  direction is deliberate: a side quest added later and not listed scores as REQUIRED, i.e. a loud
  false failure rather than a silent free pass (O2). Core also supports `optional_field` for games
  that mark it on the item, which is preferred wherever the game exposes it.

### Where the numbers land
`playtest-report.json` gains a top-level `content_engagement` block (status, `required_scored`,
`required_engaged`, `required_missed`, `pending_at_run_end`, `engagement_rate`, a per-group
breakdown carrying its `caveat`, a per-item audit trail with reveal step / engage step / which
rule fired / which action did it, and an inline `definition`). Three headline numbers also go into
`summary` so `_aggregate_runs` gives them a mean/95%-CI across a batch like every other metric.
`playtest_nexus.py` prints the breakdown and gates `PLAYTEST MET` on **`content_metric_ran`** — the
rate itself deliberately does NOT gate: a weak pilot ignoring everything is a valid, informative
result, but a silently-not-running metric is not (O10).

### Non-vacuity (O2), stated as rules the code enforces
- Nothing revealed → status **`no_reveals`**, rate **`null`**. Never 1.0, never 0.0. The
  denominator is a headline field, not a footnote, so a 100% can never be read without seeing it
  came from N chances.
- A reveal inside the last `window` steps is **PENDING** — the run ended before the pilot could be
  judged. Pending is excluded from the denominator: neither a free pass nor a free failure.
- Engagement *outside* the window does not count.
- A game with no `revealed_content` declaration reports `not_configured` — visible, not absent.

### Proof it can FAIL — `integrations/nexus/verify_content_metric.py` (new, **27/27**)
Replayed synthetic NEXUS-shaped state/action sequences (no server, no LLM, no cost), driving the
tracker through the same `note_action`-then-`observe` order the live loop uses, and reading the
groups out of NEXUS's real `ugt.config.yaml` so a typo'd path fails here:
1. **pilot ignores** a story mission + a new verb → `status: ignored`, `required_scored=2`,
   `engaged=0`, `rate=0.0`, both items named. 2. pilot follows both → `engaged`, 2/2, credited by
`invoke` and `progress` respectively. 3. nothing revealed → `no_reveals`, rate null. 4. an ignored
SIDE quest leaves the denominator empty, while a story quest ignored beside it still fails.
5. late reveal → PENDING; engagement 21 steps after a 12-step window → does not count.
6. self-credit blocked. 7. episode reset re-baselines. 8. unconfigured → `not_configured`.
**Mutation-tested**: monkeypatching `note_action` to credit everything unconditionally turns
**10 of the 27 checks RED** and exits 1 — the verifier is fail-capable, not decorative.

### Live end-to-end (gemma4:26b, 22 actions, PID-verified server)
**PLAYTEST MET.** 22/22 typed commands with real deltas, 0 invariant violations, 0 bugs, 3 servers
compromised. Metric output: `commands` revealed_during_run **0** (at_start 16), `missions`
revealed_during_run **1** (`tutorial_awakening`, accepted at step 3) → overall **`no_reveals`,
rate null, 1 pending**. Two things that says, both useful:
- The metric is honest about having had nothing to score, instead of reporting a perfect run.
- `tutorial_awakening` sat at `objectivesCompleted: 0/2` for 19 steps while the pilot compromised
  three hosts and `cat`'d two files. At window 20 that lands as PENDING by one step; at the script
  default of 40 actions it would score as **MISSED** — i.e. the metric is already pointed at the
  exact behaviour the owner wants judged. (Worth a separate look at whether `tutorial_awakening`'s
  objectives are advanceable by what this pilot did at all.)
- Side note, unrelated to this change: **gemma4 played visibly better than the qwen3-coder runs of
  L-014/L-015** — a real recon→analyze→exploit→`cat` chain across three hosts, `cat` issued twice
  (qwen3-coder: zero in 80 actions). Consistent with L-019's model correction.

### KNOWN LIMITATIONS — shipped deliberately, not buried
1. **`unlockedCommands` is a severe lower bound (D-L15-1, now quantified).**
   `unlock-checker.ts:59-74` unlocks a command if it is in that list **OR** if any
   `unlockRequirements` path (level / storyFlags) is satisfied, and *nothing writes the list on
   level-up*. Its only writer is mission-reward `unlockCommands` (`mission.ts:1104-1115`), and
   across all 14 shipped missions there is **exactly one grant**: the SIDE quest
   `ghost_protocol_test` → `traceroute`. So (a) this group's denominator is 0 on nearly every run,
   and (b) commands that become usable by levelling (`traceroute` Lv2, `crack` Lv3, `escalate`
   Lv4, `backdoor`/`upload` Lv5) are genuinely new content the metric **cannot see**.
   **Game-side ask (NX-L20-1):** have `player-state` report the commands currently PASSING the
   unlock check, not just those explicitly granted. Until then the commands group measures a
   lower bound, and the report says so in its own `caveat` field.
2. **Quest lines the pilot never accepts are invisible.** `missions[]` lists only ACCEPTED
   missions — the AVAILABLE list is printed by the `missions` command into terminal text and never
   reaches state (verified live: 4 missions offered, state array empty). So "revealed" here means
   "this quest line became live", and the judged behaviour is whether the pilot then FOLLOWED it
   rather than accepting and wandering off. A pilot that never accepts anything scores
   `no_reveals`, not "missed" — which is honest, but it is not the whole question.
   **Game-side ask (NX-L20-2):** expose available/offered missions in `player-state`.
3. `optional_ids` duplicates the game's side-mission list and can go stale (direction chosen to
   fail loudly, see above).

### Ladder — re-run and skip decisions (justified per rung, not blanket)
The change is confined to `ugt/core/playtester.py` plus the `playtest:` block of
`integrations/nexus/ugt.config.yaml`. **`grep -n "playtest\|playtester"` over `spike_nexus.py`,
`smoke_nexus_adapter.py`, `verify_round1/2/3.py` returns ZERO hits**, and `ugt/core/playtester.py`
is imported only by `ugt/cli.py` and the per-game `playtest_*.py` scripts — no ladder rung loads
it. The one way a rung could regress is the YAML edit itself.
- **RAN `verify_content_metric.py` — 27/27** (new; the metric's own gate, and where the new
  denominator lives).
- **RAN `spike_nexus.py` — 8/8**, matching baseline. Cheapest proof the edited config still parses
  and the adapter/server path is intact.
- **RAN `verify_round1.py` — 25/25**, byte-identical same-seed replay, matching baseline. A full
  live loop through the same `UgtConfig` object; if the YAML edit had broken anything real, this
  is where it shows.
- **RAN `playtest_nexus.py` (ollama/gemma4, 22 actions) — PLAYTEST MET**, now with
  `content_metric_ran:True` in the exit line.
- **SKIPPED `verify_round2.py` (54/54) and `verify_round3.py` (9/9).** Both were re-run green
  hours earlier on this same build; neither reads `playtest.*` nor imports the playtester, and
  this change adds no adapter call and mutates no state (the tracker only reads the state dict the
  loop already holds), so it cannot alter the command sequence R3's byte-identical replay
  criterion depends on. Spike + R1 already cover the only shared surface (config parse). Re-running
  a 360-step determinism walk to re-certify code it does not touch would be motion, not evidence.

**Baselines after this change: spike 8/8 · R1 25/25 · R2 54/54 (not re-run) · R3 9/9 (not re-run)
· content-metric 27/27 (new) · playtest MET.**

---

## L-021: NX-L20-1 + NX-L20-2 RESOLVED — the agility metric now has a real denominator (2026-07-22)

L-020 shipped the new-content engagement metric with two limitations stated plainly rather than
buried. Both are now closed game-side (`nexus-world-builder` `feat/nx-l20-observability-agility`,
commit **`773bd82`**, unpushed) and wired through UGT.

### NX-L20-1 (RESOLVED) · `usableCommands`
The route now reports the set that currently PASSES `checkCommandUnlock`, computed live, **added
alongside** `unlockedCommands` rather than replacing it — the two answer different questions
("usable right now" vs "explicitly granted") and conflating them would repeat D-L15-1. Measured
live at `post_tutorial`: **35 usable vs 16 granted**, the stored list missing more than half the
surface including `traceroute` and `upload`. That is the quantified version of the D-L15-1
caveat, and it is why the metric's command denominator was ~0 on every run.

### NX-L20-2 (RESOLVED) · `offeredMissions`
The board the player can see but has not accepted, with the eligibility rules **moved** into a
shared `lib/missions/availability.ts` (`missionPrerequisitesMet` / `isMissionOffered` /
`effectiveStoryFlags`) and called by BOTH the mission router and the test route — not copied.
Copying them would have made the test route a second implementation of the game's own gating,
which is the `sim_bridge` failure mode this project exists to avoid (M1). Nothing new is
persisted (pure derivations of already-loaded rows), so `reset-episode` needs no change and the
NX-L15-1 class does not apply; the route still makes exactly 2 DB calls. Verified live that
`rngSeed` is still never emitted while both new fields are non-empty.

### UGT-side wiring (mine)
- **Adapter passthrough (P2) — the THIRD time this session** that `_read_state()` would have
  silently swallowed new route fields, since it builds an explicit dict. Both carried now. P2's
  "re-run it on every state-surface change" is not theoretical advice.
- **`available_actions_path`** switched `unlockedCommands` → `usableCommands`. Still an
  annotation, never a replacement — the D-L15-1 rule holds no matter how accurate the list gets.
- **Metric config**: the `commands` group reads `usableCommands` (its lower-bound caveat replaced
  with the resolution), and a NEW **`offered_quests`** group reads `offeredMissions`, keyed by
  `missionId`, engaged by `mention` — because `accept <missionId>` IS the act of taking up a
  quest line. This is the behaviour the owner's requirement (3) actually asks about ("did the
  pilot notice a newly available quest and follow it"), and it was unobservable before: with only
  `missions[]`, "revealed" could only ever mean "already accepted". The existing `missions` group
  still answers the separate question of post-acceptance progress.
  Side quests are marked optional via the game's own `missionType` field rather than the
  hand-maintained `optional_ids` list L-020 shipped — it can no longer go stale.

### The metric gate caught my own config change
Repointing the groups took `verify_content_metric.py` from 27/27 to **17/27** — by design: it
asserts the REFERENCE integration's config shape, so changing the config must break it.
Expectations updated to the new truth and **strengthened, not relaxed**: it now fails if anyone
reverts the commands group to the explicit-grant list, and it pins `offered_quests` to the game's
own marker. **29/29**, and re-verified fail-capable after the edit (neutering `note_action` still
turns 3 checks red, exit 1) — worth re-checking precisely because I had just modified the file
that proves the metric works.

### Full ladder
**spike 8/8 · R1 25/25 · R2 56/56 · R3 9/9**, episode-0 replay byte-identical, on a stable server.
Game gates: typecheck clean, lint 0 errors, unit 1312/1312, integration 188 → **196/196**.

**Process note (O1-adjacent):** an earlier R3 in this round reported 2/8 then 0/1 and looked like
a catastrophic regression. It was not — the L20 agent was mid-edit and the dev server had
hot-reloaded into a non-compiling `player-state/route.ts`, so `bootstrap-player` 500'd and the run
died at setup. **The tell was the collapsing DENOMINATOR**: a real behavioural regression fails
checks against a stable total, whereas a total that shrinks means the run never started. Do not
run the ladder against a repo an agent is actively editing.

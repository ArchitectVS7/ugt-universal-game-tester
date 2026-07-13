# DDD × UGT — results log

Commit-traceable record of every ladder round run against the real DDD engine over
the harness wire. A round is only "green" if it was **run live** and printed its own
`MET — n/n` footer; nothing here is inferred.

Game: `/Users/vs7/Dev/Games/DDD`, branch `feat/d16-type-triangle`.
Driver: `ugt/adapters/ddd_harness.py::DddHarnessAdapter` → `packages/harness/bin/harness.mjs`.

## Rounds

| Round | Date | Script | Result (live) | Findings | UGT commit | DDD commit |
|---|---|---|---|---|---|---|
| Spike | 2026-07-12 | `spike_ddd.py` | **10/10** raw-protocol | — | `00aaa33` | `61125b64` |
| Smoke | 2026-07-12 | `smoke_ddd_adapter.py` | **5/5** BaseAdapter contract | — | `00aaa33` | `61125b64` |
| R1 | 2026-07-12 | `verify_round1.py` | **11/11** — one full match to WIN/KNOCKOUT (turn 11, 24 plies), sweep clean both runs, byte-identical same-seed replay, harness self-replay verified | — | `00aaa33` | `61125b64` |
| R2 | 2026-07-12 | `verify_round2.py` | **26/26** — 12-match corpus, 348 plies: 4 wave configs × 2 formats × 4 decks (mirrors + crosses); 4 terminal arms; **36/36 cards played**; 19 `CARD_RETURNED` w/ zero-firing control; D16 differential (+4 exactly); D2 in all 20 combats; both determinism oracles | — | `00aaa33` | `61125b64` |
| R3 | 2026-07-12 | `verify_round3.py` | **31/31** — ExploitHunter 8 ep × 60 steps, full 13-id vocabulary, **zero findings**; 9 RulesError arms provoked, 14/14 probes state-inert; fog-of-war clean; same-seed episode-0 replay byte-identical | 1 characterization (D-C1) | `9ff38b1` | `61125b64` |

**Prior run superseded.** An earlier R1 (UGT `61d3c6d`, 2026-07-11) reported 11/11 —
but against the **wrong game**. See D-F2 below. Its hashes and its 44-ply/turn-21
match shape are void; the re-baselined match resolves in 24 plies / turn 11.

## Game fixes (each pinned by a test in DDD's own suite)

### D-F1 · `legalTargets` was unreachable over the wire — graveyard cards were inert
**Fixed:** DDD `61125b64` — new `targets` op on the harness protocol.
**Pinned by:** `packages/harness/src/harness.test.ts` ("targets op — graveyard targets
are reachable over the wire", 5 tests) + `bin/stdio-smoke.mjs` (real subprocess wire,
asserts a `CARD_RETURNED` actually fires).

`legalActions` deliberately enumerates every action with `targets: []` (engine D-A:
choosing zero targets is legal, so the base move is legal; richer sets are enumerated
on demand via `legalTargets`). But `legalTargets` was exported from the engine and
**never exposed over the protocol**. A stdio client could therefore *play* a
graveyard-targeting card but never *fill* it — the effect was permanently inert.

That is **7 of `sw_competitive`'s 40 cards**: `sw_nest_builder` ×3,
`sw_adaptation_chamber` ×2, `sw_endless_tide`, `sw_deep_emergence`. `apps/play`
escaped it only because it calls `dispatch()` in-process. UGT's only door is the
wire, so the mechanic was invisible to it — and the 2026-07-11 R1 run played every
one of those cards blank without noticing.

This is the same class as DDD's own T6.0 finding ("the balance gate had been
measuring a game nobody plays"). The wire can now express targets;
**`@ddd/ai` and `@ddd/sim` still cannot** — see D-C2.

### D-F2 · `create` accepted a `MatchConfig` that `replay` would refuse
**Fixed:** DDD `61125b64` — `create` now validates with the same predicate `replay`
uses (`validateMatchConfig`, exported from the engine).
**Pinned by:** `harness.test.ts` ("create — structural MatchConfig validation shares
one predicate with replay", 3 tests) + `stdio-smoke.mjs` (partial config refused).

`parse.ts` cast `config` to `MatchConfig` after an `isPlainObject` check and nothing
else. So a config omitting a wave key was **accepted**: the key read as `undefined` →
falsy → the wave was silently OFF and the harness played a *different game* than the
caller asked for. Meanwhile `replay` **refused** that same config
(`MALFORMED_RECORD: missing key "typeTriangle"`). A match could be created that could
never be verified — the engine's own determinism oracle silently disabled.

The validator already existed (`validateConfig`, private behind `validateMatchRecord`);
it simply was not run at the door. Both doors now share it and cannot drift — the
`capturesTurnHash` discipline.

**This was not hypothetical.** UGT's `ugt.config.yaml` predated D16 and named only two
of the three wave keys, so its entire 2026-07-11 R1 run certified a game with the type
triangle **off** — the one mechanic D16 exists to add — and never ran combo chains or
Rare predictions at all (`chainsPredictions: false`). Found by re-running the spike.

## Characterizations (by design — recorded, not defects)

### D-C1 · The Focus economy never binds
Measured by `verify_round3.py`: across **26 probed turn-states over 20 seeds, zero
cards were ever unaffordable**. `STARTING_FOCUS` is 1, but resource regen plus
Balanced-stance regen puts a seat at focus **3 on turn 1** and at the cap (**5**) by
turn 4 — while the most expensive card in the entire 36-card pack costs **3**.

Consequences: cost is never a real decision, and the `INSUFFICIENT_FOCUS` rules arm is
~~unreachable in normal play (dead code against shipped content)~~.

**Caveat (2026-07-12, DDD-side re-measurement):** the 26-state sample was too small
for the "unreachable/dead code" claim. Over ~1,700 live selection states per pairing
(60 games, skilled play), **6–10% of states contain at least one unaffordable card**
— the arm is *rare*, not dead. The headline conclusion stands and is confirmed at
scale: **90–94% of states can afford the entire hand and 40–51% sit at the focus
cap**, so cost is not a decision.

This is DDD's own open **T6.5** ("The Focus economy — make cost a real decision"), so
it is ratified design debt, not a robustness defect. R3 records it and does **not**
fail on it.

### D-C2 · ~~The in-process instruments still never fill targets~~ **REFUTED IN PART (2026-07-12, DDD-side re-measurement)**
Original claim: `@ddd/ai` and `@ddd/sim` never call `legalTargets` (verified: zero
references), so even after D-F1 the AI tiers and the Monte-Carlo balance sim still
play all four graveyard-return cards inert, and the AI-ladder numbers in CI are
measured on a Swarm deck with 7 dead cards.

**Correction.** The "zero references" verification was wrong — a grep at DDD HEAD
(`e89e4abe`, same commit range this round ran against) finds `legalTargets` called at
`packages/ai/src/eval/candidate.ts:45` (`chooseTargets`), present since T5.1/T5.2 and
used by BOTH tier 2 (greedy) and tier 3 (one-ply). Confirmed empirically (60
games/pairing, real pack): greedy filled targets on **131/136** grave-card plays
(242 `CARD_RETURNED`), one-ply **140/144** (211). **The AI-ladder CI numbers are
measured with the subject tier fully armed and stand.**

What the claim got right: `@ddd/sim`'s `randomPolicy` and tier-1
`uniformRandomStrategy` never fill targets (**0/121** grave-card plays, 0 returns), so
the random-vs-random *balance gate* does blank 7 of `sw_competitive`'s 40 cards —
that half remains owned by DDD **T6.0** (b)/(c), and was deliberately not fixed here
because it moves published balance numbers.

**Method lesson for UGT:** a static-reference claim ("zero references, verified") must
be pinned by the actual search command + commit hash in the results log, exactly as
dynamic claims are pinned by scripts. This one wasn't, and it shipped a false finding
into DDD's task ledger (since corrected in DDD `TASKS.md` T6.0(c)).

### D-C3 · Some RulesError arms are shadowed by earlier checks
The battery provokes 9 of the 14 arms. The rest are not unreachable bugs — they are
*shadowed* by validation ordering, which is correct behavior:
- phase is checked before card ownership → a bad commit in MULLIGAN returns
  `WRONG_PHASE`, not `CARD_NOT_IN_HAND` (both reachable; just probe in the right phase);
- shape is checked before semantics → a non-`CardType` prediction returns
  `MALFORMED_ACTION`, not `INVALID_PREDICTION`;
- `INSUFFICIENT_FOCUS` — see D-C1: rare against shipped content (~6–10% of skilled-play
  states have an unaffordable card), not unreachable; the 26-state battery just never hit it.
`NOT_YOUR_ACTION` / `UNSUPPORTED_ACTION` remain defensive arms with no wire route found.

## How to re-run

No server to start — the adapter spawns the harness itself. Needs node ≥ 24 and DDD
deps installed.

```bash
# from the UGT repo root
python3 integrations/ddd/spike_ddd.py           # 10/10 raw protocol (incl. the targets op)
python3 integrations/ddd/smoke_ddd_adapter.py   #  5/5 BaseAdapter contract
python3 integrations/ddd/verify_round1.py       # 11/11 one match + determinism
python3 integrations/ddd/verify_round2.py       # 26/26 full content spine
python3 integrations/ddd/verify_round3.py       # 31/31 ExploitHunter + refusal battery

# DDD's own gate (from /Users/vs7/Dev/Games/DDD)
pnpm typecheck && pnpm lint && pnpm test && pnpm smoke && pnpm bench
node apps/ladder/bin/ladder.mjs
```

Every script is fail-closed (`GateRunner.finish` returns 0 only when passed == total)
and prints `[FINDING]` lines inline. A failed check is DATA: fix it upstream in DDD
with a pinning test and re-run — never weaken it here.

## Next tier

The LLM balance-playtester (`ugt playtest`) is the tier that judges *"is this a good
game?"* rather than *"does it work?"* — it is the natural home for D-C1 and for DDD's
T8.2. It is credit-gated and not yet wired to this adapter (`DddHarnessAdapter` has no
`press_key`/`get_terminal_text`; the harness is structured JSON, not a terminal, so
the playtester would drive `legal`/`act` directly rather than a screen).

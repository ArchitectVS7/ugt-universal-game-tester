# UGT — Critical Assessment & Fix Roadmap

> **Status of this document:** an **external review** written 2026-06-29 while evaluating whether to point
> UGT at a different project (a 2–4 player deterministic TypeScript board game, *Iron Throne of Ashes*).
> It is deliberately separate from `UNIVERSAL-ML-TESTER-ASSESSMENT.md` (the original build-time self-review,
> which is accurate about *architecture* but optimistic about *validity*). Every claim below was verified
> against the code/results on disk — file:line evidence is cited so a future fixer can confirm fast.
>
> **Bottom line:** UGT is a clean, working *scaffold* with a sound adapter/config decoupling, but it is
> **not yet a trustworthy balance tester**, and it is **structurally mis-scoped for multiplayer / social
> games**. Its single realistic integration produced a silently-collapsed policy. Do not rely on its output
> for balance until the P0 items below are fixed. **Come back to this file when you want to make UGT real.**

---

## 1. What UGT is (verified)

A ~1,100-LOC Python framework that wraps **Stable-Baselines3** (PPO/DQN/A2C, all `MlpPolicy`) to train a
**single** agent against a game exposed through one of two adapters:

- **Subprocess** (`ugt/adapters/subprocess.py`) — newline-delimited JSON over stdin/stdout: `reset` →
  `{state}`, `step{action_id}` → `{state, terminated, truncated, info}`, `close`.
- **Playwright** (`ugt/adapters/playwright.py`) — browser games via `window.__GET_STATE__` /
  `__SEND_ACTION__` / `__RESET_GAME__`.

The game is described declaratively in `ugt.config.yaml`: dotted state paths → a fixed-length numeric
observation **Box** (`ugt/core/env.py`), a flat **Discrete** action set, and reward as an **arithmetic
formula** over `state.*` evaluated by a safe AST evaluator (`ugt/utils/formula_evaluator.py`) plus
`win_bonus` / `loss_penalty` (`ugt/core/env.py:104-122`).

**Maturity:** self-labeled Stage 3 of 4. Config parser, dynamic env/trainer, and one real game port
(Warzones) are done; a second port is pending. The architecture is decoupled and reasonable. **But "runs
end-to-end" ≠ "produces valid signal" — see §2.** Not a git repo (no history); untouched since ~mid-June.

---

## 2. The evidence it does not yet work (the smoking gun)

UGT's **only realistic, non-mock integration** is `examples/spacerquest/`. Its saved evaluation
(`examples/spacerquest/results/explorer_eval_summary.json`, model `ppo_explorer_160000_steps`, 50 episodes)
is a **textbook collapsed / degenerate policy** — and UGT reported it as a clean run:

```
wins: 0 / 50           (win_rate 0.00%)
reward: mean = median = min = max = -789.21,  std = 0.0     ← identical every episode
steps:  every episode hits the 50-step cap (no agency)
actions used: combat_attack ×2050, navigate_neighbor ×450  ← only 2 of 15 actions, EVER
```

A policy that emits the *same two actions every step of every episode* for an identical reward, never wins,
and always times out is the canonical RL failure mode (policy collapse / no learning signal). **Nothing in
the framework detected, warned about, or flagged this** — `evaluator.py` happily wrote the summary. This is
the single most important fact about UGT today: **on the one hard problem it was given, it failed silently.**

This mirrors a sibling project's post-mortem almost exactly: *Iron Throne of Ashes* previously scrapped its
own PPO/SB3 "balance" harness for the same reasons (degenerate agent, non-reproducible, no signal) — see that
project's `docs/design-history/ML-SYSTEM-ANALYSIS.md`. Two independent PPO-wrapper attempts, same outcome.
That is a pattern, not bad luck.

---

## 3. Root-cause problems (prioritized, with evidence)

### P0 — blocks trustworthy results (fix before relying on any output)

1. **No policy-collapse / no-signal diagnostics.** The §2 collapse shipped undetected. There is no
   baseline-vs-random comparison, no action-entropy / mode-collapse check, no "did the agent learn anything
   over random?" gate. *A balance tester that cannot tell when it has learned nothing is worse than no tester
   — it produces confident garbage.* (`ugt/core/evaluator.py` reports raw stats only.)

2. **Non-reproducibility.** Training/eval are not seed-pinned: `env.py:88-89` forwards `seed` to the
   Gymnasium base `reset` only; there is **no** `set_random_seed` for SB3 / numpy / torch in
   `ugt/core/trainer.py`. Worse, a bridge introduces raw nondeterminism: `examples/spacerquest/sim_bridge.ts:470`
   calls `Math.random()`. Result: runs are not reproducible, so a balance number cannot be re-derived or
   trusted, and a regression cannot be bisected.

3. **Single-agent only — invalid for multiplayer balance.** SB3 trains one policy vs a *fixed* environment.
   There is no self-play, no multi-agent, no opponent-pool. For any game whose balance is a question about
   **competing competent players** (most multiplayer/social/board games), this is a category error: the other
   seats must be baked into the bridge as scripted AI, so UGT measures "can one RL agent beat our scripts,"
   not "is the game balanced among peers." (`trainer.py` single `model.learn`; no league/self-play anywhere.)

4. **Reward-formula → reward hacking.** Reward is a hand-written proxy formula (`env.py:104-122`); the docs
   admit it "cannot express deltas/conditionals/milestones" and that the Warzones port only *approximates* the
   real objective. Optimizing a mis-scaled proxy is exactly how you get a degenerate policy. For balance you
   want agents that play to **win** (sparse win/loss reward), with shaping optional and guarded — the inverse
   of the current default.

### P1 — limits fidelity / realism

5. **No legal-action masking.** The agent samples any action id; illegal ones must no-op inside the bridge
   (`env.py` has no mask — grep confirms zero mask references). PPO then wastes capacity learning legality,
   and the action distribution is polluted by no-ops. Real action masking (or an `info["action_mask"]` the
   policy respects) is needed for any game with conditional legality.

6. **Flat discrete action space only.** Actions are fixed integer macros (`action_space.size`). Games with
   **parameterized** commands (target *whom*, pledge *how much*, move to *which* node) must be hand-compressed
   into a small macro set — discarding the very decisions that drive balance. (Warzones: 5 macros; SpacerQuest:
   15.) No parameterized/auto-regressive/factored action support.

7. **Optimal-only evaluation — no human-error model.** Eval is greedy (`evaluator.py:55`,
   `deterministic=True`); training explores via the algorithm's own entropy but eval reports the greedy
   policy. There is **no bounded-rationality / suboptimal-play injection**. Real tables are won and lost on
   *mistakes*; optimal-vs-optimal balance is lukewarm and misleading. (The right model is a "d20 vs a skill
   check": each decision passes with some probability and otherwise takes a worse legal action — seeded so it
   stays reproducible.)

### P2 — hygiene / confidence

8. **No statistical-confidence reporting** beyond raw std; no confidence intervals, no seed-band stability,
   no "N to detect an X% imbalance" guidance.

9. **Docs document architecture, not limitations.** `README.md` / `WALKTHROUGH.md` /
   `UNIVERSAL-ML-TESTER-ASSESSMENT.md` are rosy; none state the §2 collapse or the P0 validity gaps. (This
   file is the corrective.)

---

## 4. What UGT is genuinely good for *today* (be fair)

The scaffold is not worthless — it is *mis-scoped*. As-is it is a reasonable fit for:

- **Single-agent or 1-vs-fixed-opponent games** where "can an agent beat the game?" is the actual question.
- **Browser-game smoke/exploit hunting** — the Playwright adapter's soft-reset work (15 s → <20 ms) and
  adaptive waiting are genuinely useful; a random/short-trained agent can surface crashes, soft-locks, and
  obvious degenerate lines.
- **The decoupling pattern itself** — config-driven obs/action mapping + a thin stdin/stdout bridge is a
  clean contract worth keeping. A TS bridge example already exists (`examples/spacerquest/sim_bridge.ts`), so
  plumbing a new TS/JS game in is ~1–2 days.

It is a **poor fit** for multiplayer, hidden-information, or social-deduction games whose balance is a
multi-agent equilibrium question — which is most board games.

---

## 5. Fix roadmap (what to do when you come back)

Ordered cheapest-highest-value first. Phases A–B make the *current* tool trustworthy; C–E make it the right
*kind* of tool.

**Phase A — Make results honest (small, do first).**
- A1. **Collapse/no-signal guard:** before writing any eval summary, run a `random-policy` baseline over the
  same N episodes and refuse to report (or loudly flag) a trained model whose win-rate / mean-reward is not
  meaningfully above random, or whose action entropy is near zero, or whose reward std is ~0. This single
  check would have caught the SpacerQuest collapse.
- A2. **Seed everything:** `set_random_seed()` for SB3 + numpy + torch in `trainer.py`/`evaluator.py`; thread
  a config seed; forbid `Math.random()`/wall-clock in bridges (lint or a determinism self-check at handshake).
- A3. **Statistical confidence:** report CIs + seed-band stability, not just std.

**Phase B — Make play realistic (small–medium; the "d20" idea).**
- B1. **Bounded-rationality eval mode:** an `epsilon` / temperature knob — with probability *p*, the agent
  takes a sampled (not greedy) or a deliberately suboptimal legal action; seeded for reproducibility. Report
  balance across a *sweep* of *p* (optimal → sloppy), since balance that only holds at *p*=0 is not real
  balance. (This is the highest-value idea for balance fidelity and is largely tool-agnostic.)

**Phase C — Make it valid for multiplayer (large; the real unlock).**
- C1. **Self-play / multi-agent:** an opponent pool / league so multiple competing seats are *learned*, not
  scripted; per-seat policies; mirror-match and mixed-pool evaluation. Without this, multiplayer "balance"
  numbers are not meaningful. (This is a substantial redesign of `trainer.py`, not a tweak.)

**Phase D — Improve action fidelity (medium).**
- D1. **Action masking** (respect `info["action_mask"]`), and
- D2. **Parameterized/factored actions** (target + verb + amount) so rich command spaces aren't flattened.

**Phase E — Reward design (medium).**
- E1. Default to **sparse win/loss reward**; make shaping opt-in, scale-checked, and reported separately so
  proxy-optimization can't masquerade as winning.

**A pragmatic note:** Phases C+D+E together approach "build a purpose-fit self-play harness on the target
game's real engine." For any single game, that is often *less* work and *more* valid than bending UGT to fit.
UGT's value proposition is **cross-game reuse**; only invest in C–E if the multi-game portfolio payoff is
real. For one game (e.g. a game that already has a fast deterministic reducer + Monte-Carlo sim), prefer a
self-play loop directly on that engine and use UGT, if at all, for single-agent exploit-hunting.

---

## 6. "Definition of done" for a UGT you could trust for balance

Come back when you want UGT to clear this bar:
1. It **refuses to report** a collapsed / no-better-than-random policy (Phase A1).
2. Same `(config, seed)` ⇒ **identical** training + eval (Phase A2).
3. It can run **self-play across N competing learned seats** and report per-seat win-share (Phase C1).
4. It evaluates across a **bounded-rationality sweep**, not just optimal play (Phase B1).
5. It can re-derive a known balance result on a game whose balance is independently understood (a validation
   target — the way Warzones/this-game's existing deterministic sim could serve as ground truth).

Until at least #1 and #2 exist, treat UGT output as *unvalidated* and prefer a deterministic Monte-Carlo
sim for any balance decision.

---

## 7. Evidence index (verified 2026-06-29)

| Claim | File:line |
|---|---|
| Collapsed eval (0/50 wins, std 0.0, 2/15 actions, all 50-step caps) | `examples/spacerquest/results/explorer_eval_summary.json` |
| Nondeterminism in a bridge (`Math.random`) | `examples/spacerquest/sim_bridge.ts:470` |
| Greedy-only eval | `ugt/core/evaluator.py:55` (`deterministic=True`) |
| Seeds not pinned for SB3/numpy/torch | `ugt/core/env.py:88-89` (gym only); none in `ugt/core/trainer.py` |
| No action masking | `ugt/core/env.py` (no mask refs) |
| Reward = proxy formula + win/loss bonus | `ugt/core/env.py:104-122`; `ugt/utils/formula_evaluator.py` |
| Single-agent SB3, no self-play | `ugt/core/trainer.py` (single `MlpPolicy` learn) |
| Subprocess protocol | `ugt/adapters/subprocess.py:41-82` |
| Self-review (architecture-accurate, validity-optimistic) | `UNIVERSAL-ML-TESTER-ASSESSMENT.md` |
</content>

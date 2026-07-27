"""
Phase 3: LLM-driven playtest runner.

Drives a game through an LLM agent that reads game state and picks actions
with explicit reasoning and expected outcomes. Produces a structured bug report.

Supported providers:
  anthropic  — Anthropic API (requires: pip install ugt[playtest], ANTHROPIC_API_KEY env var)
  ollama     — Local Ollama server (requires: ollama running at localhost:11434, no key needed)

Usage:
  ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md
  ugt playtest --provider ollama --model gemma4:26b --strategy-guide strategy-guide.md
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

from ugt.core import seeding

# LLMAction JSON schema — returned by the model (tool_use for Anthropic, JSON mode for Ollama)
LLM_ACTION_SCHEMA = {
    "type": "object",
    "required": ["action_type", "value", "reasoning", "expected_outcome"],
    "properties": {
        "action_type": {
            "type": "string",
            "enum": ["action_id", "press_key", "type_text", "wait", "diagnose", "end_turn",
                     "legal_action"],
            "description": (
                "action_id: simulation game — value is the action name from the config. "
                "press_key: browser game — value is a single key (e.g. 'T', 'Enter'). "
                "type_text: browser game — value is text to type. "
                "wait: pause for one step (use sparingly). "
                "diagnose: flag that the current state is confusing or broken. "
                "end_turn: signal that the current turn is complete. "
                "legal_action: harness game — value is the INDEX (0-based, as a string) "
                "of one action from the LEGAL ACTIONS list shown in the prompt."
            ),
        },
        "value":            {"type": "string", "description": "The action value (action name, key, or text)"},
        "reasoning":        {"type": "string", "description": "Why this action right now"},
        "expected_outcome": {"type": "string", "description": "What you expect to see after this action"},
        "potential_bug":    {"type": "string", "description": "Describe any suspected bug in the current state (omit if none)"},
        "is_novel":         {"type": "boolean", "description": "True if this exercises a behavior outside the feature map"},
    },
}

# Valid action_type values for fallback parsing
_VALID_ACTION_TYPES = {"action_id", "press_key", "type_text", "wait", "diagnose", "end_turn",
                       "legal_action"}


def playtest_game(config, strategy_guide, max_actions=100, output_path=None, provider="anthropic",
                  model=None, runs=1, invariants=None):
    """
    Phase 3: LLM-powered playtest.

    config         — UgtConfig instance
    strategy_guide — string content of the strategy guide markdown file
    max_actions    — maximum LLM actions per run
    output_path    — report path. runs==1: playtest-report.json (legacy shape + summary).
                     runs>1: per-run playtest-run-{i}.json + aggregate playtest-summary.json
                     (output_path overrides the summary path).
    provider       — "anthropic" or "ollama"
    model          — model name override (None = provider default)
    runs           — number of independent runs (adapter.reset() isolates each)
    invariants     — optional machine checks run after every executed action, kept fully
                     game-agnostic: either a list of objects with .name and
                     .check(before, action_id, info, after, ctx) (the invariant-fuzzer
                     contract), or a callable (adapter) -> such a list. Violations are
                     recorded per run (separate from LLM-suspected potential_bugs) and
                     never abort the run — a failed check is data.

    Returns the aggregate report dict (runs>1) or the single run report (runs==1).
    """
    sys.stdout.reconfigure(line_buffering=True)

    if provider == "anthropic":
        llm = _AnthropicLLM(model or "claude-opus-4-8")
    elif provider == "ollama":
        llm = _OllamaLLM(model or "gemma4:26b")
    else:
        raise ValueError(f"Unknown LLM provider: '{provider}'. Choose 'anthropic' or 'ollama'.")

    if config.engine_type == "browser":
        from ugt.adapters.playwright import PlaywrightAdapter
        adapter = PlaywrightAdapter(config)
    elif config.engine_type == "simulation":
        from ugt.adapters.subprocess import SubprocessAdapter
        adapter = SubprocessAdapter(config)
    elif config.engine_type == "custom":
        raise ValueError(
            "engine.type 'custom' cannot be dispatched here — build your adapter directly "
            "and call playtest_game_with_adapter() instead (see that function's docstring)."
        )
    else:
        raise ValueError(f"Unknown engine type: '{config.engine_type}'")

    return _run_and_write(adapter, llm, config, strategy_guide, max_actions,
                          output_path, provider, runs, invariants,
                          action_mode="action_id")


def playtest_game_with_adapter(adapter, provider, strategy_guide, max_actions=100,
                               output_path=None, model=None, runs=1, invariants=None,
                               action_mode="legal_action", config=None):
    """Playtest via an ALREADY-CONSTRUCTED adapter instance.

    The three JSON-lines harness adapters (a trading-card game, a sci-fi board game, and
    a roguelike survival shooter) are not registered under an `engine.type` in env.py —
    each game's own ladder scripts
    build the adapter directly. This entry point takes that adapter and runs the
    SAME LLM loop as `playtest_game`; the only difference is the input/action
    channel (`action_mode`, e.g. "legal_action"). Text-driven integrations (e.g.
    a terminal RPG's command-line mode) use this entry point directly.

    adapter        — a connected-or-not adapter instance (connect() is called here).
                     For action_mode="legal_action" it MUST expose legal_actions()
                     and apply_legal(); otherwise a NotImplementedError names the gap.
    provider       — "anthropic" or "ollama" (same dispatch as playtest_game).
    config         — a UgtConfig-like object for project_name / playtest block /
                     results dir. Defaults to adapter.config. May be minimal — every
                     access is getattr-guarded.

    Returns the aggregate report dict (runs>1) or the single run report (runs==1).
    """
    sys.stdout.reconfigure(line_buffering=True)

    if provider == "anthropic":
        llm = _AnthropicLLM(model or "claude-opus-4-8")
    elif provider == "ollama":
        llm = _OllamaLLM(model or "gemma4:26b")
    else:
        raise ValueError(f"Unknown LLM provider: '{provider}'. Choose 'anthropic' or 'ollama'.")

    if config is None:
        config = getattr(adapter, "config", None)

    return _run_and_write(adapter, llm, config, strategy_guide, max_actions,
                          output_path, provider, runs, invariants,
                          action_mode=action_mode)


def _write_retained(payload, primary_path, results_dir, stem):
    """Write a report to its stable path AND to a timestamped archive beside it.

    The stable filename must not move — every gate, integration script and
    downstream reader opens it by name. But it is also OVERWRITTEN by the next
    run, and that cost is not hypothetical: the 599-action run whose stall
    behaviour later needed analysis had already been destroyed by a subsequent
    30-action smoke run, so the analysis had to be done against a synthetic
    reconstruction of numbers quoted in a findings log. A trace is evidence, and
    evidence you overwrite is evidence you do not have.

    `results/` is gitignored repo-wide, so archives never enter version control.
    Returns the archive path so the caller can print it.
    """
    with open(primary_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    archive = os.path.join(results_dir, f"{stem}-{stamp}.json")
    with open(archive, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return archive


def _run_and_write(adapter, llm, config, strategy_guide, max_actions, output_path,
                   provider, runs, invariants, action_mode="action_id"):
    """Shared post-adapter orchestration for both entry points: connect, wire
    invariants + action vocabulary, drive `runs` playtests, write reports. The
    `action_mode` is threaded straight through to `_run_single_playtest`; every
    `config` access is getattr-guarded so a minimal adapter-supplied config works."""
    project_name = getattr(config, "project_name", None) or "the game"
    cfg_data = getattr(config, "data", None)
    cfg_data = cfg_data if isinstance(cfg_data, dict) else {}
    action_mappings = getattr(config, "action_mappings", None) or {}

    filepath = getattr(config, "filepath", None)
    if output_path:
        results_dir = os.path.dirname(os.path.abspath(output_path)) or "."
    elif filepath:
        results_dir = os.path.join(os.path.dirname(os.path.abspath(filepath)), "results")
    else:
        results_dir = os.path.abspath("results")
    os.makedirs(results_dir, exist_ok=True)

    playtest_cfg = cfg_data.get("playtest", {}) if isinstance(cfg_data, dict) else {}

    engine_type = getattr(config, "engine_type", None) or action_mode
    print(f"[*] Phase 3 — Playtest: connecting to game ({engine_type}, mode={action_mode})...")
    adapter.connect()

    invariant_list = list(invariants(adapter)) if callable(invariants) else list(invariants or [])
    if invariant_list:
        print(f"[*] {len(invariant_list)} invariant check(s) active during play")

    # Give the LLM layer the action vocabulary so mis-fielded intents can be salvaged.
    # (Only meaningful for action_id mode; legal_action mode indexes into the live
    # legal list, so an empty vocabulary here is correct and harmless.)
    valid_action_names = set()
    for action_def in action_mappings.values():
        valid_action_names.add(action_def.get("name") if isinstance(action_def, dict) else str(action_def))
    if hasattr(llm, "valid_actions"):
        llm.valid_actions = valid_action_names
    # The truncation salvage validates differently per channel: an action-id run
    # matches the whole value against the vocabulary, a text run matches only the
    # command's VERB (the rest is the model's own argument). See
    # `_salvage_truncated_action`.
    llm.action_mode = action_mode

    run_reports = []
    try:
        for run_index in range(1, runs + 1):
            if runs > 1:
                print(f"\n[*] ── Run {run_index}/{runs} "
                      f"(provider={provider}, model={llm.model}, max_actions={max_actions}) ──")
            else:
                print(f"[*] Connected. Starting LLM playtest (provider={provider}, "
                      f"model={llm.model}, max_actions={max_actions})...")
            run_report = _run_single_playtest(
                adapter, llm, config, strategy_guide, max_actions,
                playtest_cfg, invariant_list, run_index, action_mode=action_mode,
            )
            run_report["provider"] = provider
            run_report["model"] = llm.model
            run_reports.append(run_report)
            if runs > 1:
                run_path = os.path.join(results_dir, f"playtest-run-{run_index}.json")
                _write_retained(run_report, run_path, results_dir,
                                f"playtest-run-{run_index}")
                s = run_report["summary"]
                print(f"[+] Run {run_index}: actions={s['actions_taken']} "
                      + " ".join(f"{k}={v}" for k, v in s.items()
                                 if k not in ("actions_taken",) and not isinstance(v, (dict, list))))
    finally:
        adapter.close()

    if runs == 1:
        report = run_reports[0]
        report["game"] = project_name
        out = output_path or os.path.join(results_dir, "playtest-report.json")
        archive = _write_retained(report, out, results_dir, "playtest-report")
        _print_run_summary(report, out)
        print(f"[+] Trace retained: {archive}")
        return report

    aggregate = _aggregate_runs(run_reports)
    summary_report = {
        "game": project_name,
        "provider": provider,
        "model": llm.model,
        "runs": runs,
        "max_actions": max_actions,
        "aggregate": aggregate,
        "runs_detail": [r["summary"] for r in run_reports],
        "run_report_files": [f"playtest-run-{i}.json" for i in range(1, runs + 1)],
    }
    out = output_path or os.path.join(results_dir, "playtest-summary.json")
    archive = _write_retained(summary_report, out, results_dir, "playtest-summary")

    print(f"\n[+] Playtest batch complete: {runs} runs × {max_actions} actions")
    for label, stats in aggregate.items():
        if isinstance(stats, dict) and "mean" in stats:
            print(f"    {label}: mean={stats['mean']} ±{stats['ci95_half_width']} (95% CI), "
                  f"std={stats['std']}, values={stats['values']}")
        else:
            print(f"    {label}: {stats}")
    print(f"[+] Summary: {out}")
    print(f"[+] Trace retained: {archive}")
    return summary_report


def _run_single_playtest(adapter, llm, config, strategy_guide, max_actions,
                         playtest_cfg, invariant_list, run_index, action_mode="action_id"):
    """One playtest run: reset, drive up to max_actions LLM decisions, return the run report.

    `action_mode` selects the input/action CHANNEL only — the loop body (delta
    assertion, bug-report shape, invariant checks, contradiction detector) is
    identical across modes. "action_id" (default) drives config-registered discrete
    ids / UI keys; "legal_action" drives one of the adapter's own reported legal
    actions per step (harness games with no terminal / no config action vocabulary);
    "text" drives a terminal game by having the LLM TYPE raw command lines
    (action_type="type_text"), the way a human at the prompt would — non-vacuous for
    any adapter that reports the transition via type_text_step().
    """
    terminal_budget = int(playtest_cfg.get("terminal_char_budget", 400))
    summary_paths = [e for e in (playtest_cfg.get("summary_paths") or [])
                     if isinstance(e, dict) and "path" in e]

    if action_mode == "legal_action":
        if not (hasattr(adapter, "legal_actions") and hasattr(adapter, "apply_legal")):
            raise NotImplementedError(
                f"{type(adapter).__name__} does not support action_mode='legal_action' "
                f"(needs legal_actions() and apply_legal())"
            )

    # Build action name → ID map (action_id mode only — legal_action mode indexes
    # into the live legal list and never consults the config action vocabulary).
    name_to_id = {}
    if action_mode != "legal_action":
        action_mappings = getattr(config, "action_mappings", None) or {}
        for action_id, action_def in action_mappings.items():
            name = action_def.get("name", str(action_id)) if isinstance(action_def, dict) else str(action_def)
            name_to_id[name] = int(action_id)

    # ── Per-episode seeding (LESSONS.md §B P9) ──────────────────────────────
    # Without this, every episode in a run replays whatever seed the game reset
    # itself to, so a "batch" of N episodes is one match sampled N times — an
    # N-sized denominator over a 1-sized sample, and nothing in the output says
    # so. `playtest.episode_seeds` rotates a fixed, declared seed list one seed
    # per EPISODE (not per run: a 30-action run spans several episodes, and they
    # must differ from each other, not just from the next run's).
    #
    # Seeds rotate rather than being consumed, so the list length and the episode
    # count are independent — 8 seeds over 16 episodes is two passes, which is a
    # legitimate paired design, not an error.
    #
    # Since 2026-07-26 the MODE is declared rather than inferred from whether a
    # seed list happens to be present — `ugt/core/seeding.py` explains why the
    # absent case was ambiguous — and the declaration is probed against the live
    # game before the run starts, so a game that silently ignores its seed is
    # caught here instead of in a batch nobody can trust afterwards.
    seeding_mode, episode_seeds = seeding.resolve(playtest_cfg)
    _episode_index = 0  # 0-based; also the rotation cursor

    def _current_seed():
        return episode_seeds[_episode_index % len(episode_seeds)] if episode_seeds else None

    def _reset_episode(first=False):
        """Reset onto this episode's seed, or plainly if no seeds are configured.

        `reset_seeded` raises for adapters that cannot control the seed, and that
        refusal is deliberately NOT caught: a caller that asked for seed variety
        and silently did not get it is the exact failure this knob exists to
        remove."""
        nonlocal _episode_index
        if not first:
            _episode_index += 1
        if not episode_seeds:
            return adapter.reset()
        return adapter.reset_seeded(_current_seed())

    # Prove the declaration before spending anything. This runs for EVERY game,
    # not just the ones whose author remembered to write a probe — the browser
    # dice game had to carry its own, which is how the check stayed a per-game
    # habit instead of a guarantee.
    # `probe_actions` (a LIST, driven verbatim) wins over `probe_action` (a single
    # id, repeated). The list exists for games whose seed-sensitive action has a
    # precondition — see ugt/core/seeding.py::as_sequence.
    _probe_action = playtest_cfg.get("probe_actions", playtest_cfg.get("probe_action", 0))
    try:
        print(f"[*] {seeding.probe(adapter, seeding_mode, episode_seeds, _probe_action)}")
    except seeding.SeedingError as e:
        print(f"[-] Seeding declaration failed against the live game:\n    {e}")
        raise
    except NotImplementedError as e:
        # BaseAdapter.reset_seeded()'s refusal, surfaced with the config context
        # that makes it actionable.
        print(f"[-] seeding={seeding_mode!r} needs an adapter that can seed:\n    {e}")
        raise

    # One record per episode the run actually finishes, so a batch can be scored
    # at all. Until now the outcome survived ONLY as a delta inside the action
    # log ("winner: None -> 'player'"), which no aggregate could read.
    episodes = []
    _victory_key = ((getattr(config, "data", None) or {}).get("evaluation") or {}).get("victory_key") \
        if isinstance(getattr(config, "data", None), dict) else None
    _episode_first_step = 1

    def _close_episode(final_state, last_step, reason):
        episodes.append({
            "episode": len(episodes) + 1,
            "seed": _current_seed(),
            "first_step": _episode_first_step,
            "last_step": last_step,
            "actions": max(0, last_step - _episode_first_step + 1),
            "end_reason": reason,
            # The game's own declared outcome field (evaluation.victory_key),
            # read verbatim — this module never interprets it.
            "outcome": _resolve_path(final_state, _victory_key) if _victory_key else None,
            "final_state": json.loads(json.dumps(final_state, default=str)),
        })

    current_state = _reset_episode(first=True)
    baseline_state = json.loads(json.dumps(current_state, default=str))
    # Progressive-content metric (owner requirement: is the pilot AGILE about newly
    # revealed commands / quest lines?). Read-only over the state the loop already
    # holds — no extra adapter calls, no change to the LLM contract.
    reveals = _RevealTracker(playtest_cfg)
    reveals.rebaseline(current_state)
    # Deltas accumulated across mid-run episode resets: on each reset we bank
    # (pre-reset value − baseline value) per summary path, then re-baseline.
    banked = {e["path"]: 0 for e in summary_paths}

    def bank_deltas(pre_reset_state):
        for e in summary_paths:
            pre = _resolve_path(pre_reset_state, e["path"])
            base = _resolve_path(baseline_state, e["path"])
            if isinstance(pre, (int, float)) and isinstance(base, (int, float)):
                banked[e["path"]] += pre - base

    action_log = []
    potential_bugs = []
    novel_behaviors = []
    invariant_violations = []
    action_counts = {}
    episode_resets = 0
    noop_streaks = {}  # action -> consecutive no-material-delta count (contradiction detector)
    # action -> {tries, productive, last_step, display_only}: the CUMULATIVE record shown
    # back to the agent each step (LESSONS.md P10). noop_streaks resets on any productive
    # step and the recent-actions window slides, so neither survives an interleaved loop.
    action_ledger = {}
    # (action, context) -> {text, step}: the LATEST terminal output each action produced,
    # so terminal-only knowledge (a terminal RPG's security levels / vuln names / file lists) survives
    # past the single rolling buffer. Populated one step late: at the top of iteration N+1
    # the fetched terminal_text IS the output of action N, so no extra adapter call.
    terminal_recall = {}
    _pending_recall = None  # (key, step) awaiting its output on the next iteration
    # (verb) -> {text, step}: the LATEST output of a quest/mission-status command (e.g.
    # 'progress'/'missions'), kept GLOBALLY — deliberately NOT scoped by context like
    # terminal_recall above. A mission is player-global state, not location-scoped, so
    # keying its recall by currentServerId (as terminal_recall does for recon commands)
    # would fragment the same information into multiple stale, duplicate entries across
    # whatever server the pilot happened to be on each time it checked. See _quest_block.
    quest_recall = {}
    _quest_commands = set((playtest_cfg or {}).get("quest_commands") or [])
    # Immediate-adjacency guard: distinct from noop_streaks (material-delta-gated, and
    # bypassed entirely for display_only_verbs so legitimate repeatable recon like a terminal RPG's
    # `ls` never trips it). This tracks ONLY whether the literal previous step picked the
    # SAME (action_type, value) as this one, regardless of delta or display-only status —
    # "used often" (spaced out, or after other actions) is fine and untouched; "used
    # back-to-back with nothing in between" is capped by TWO mechanisms below: a soft
    # warning fed into the prompt (repeat_streak), then a HARD, deterministic block once
    # `playtest.repeat_block_threshold` is reached — a text warning alone is advisory and
    # a model can simply not follow it (live evidence: gemma4:26b repeated one command
    # 163x in a row on a terminal RPG, restating "I'm stuck" almost every time regardless).
    _last_seq_key = None
    _consecutive_repeat = 0
    repeat_streak = {}  # {noop_key: current back-to-back run length}, single active entry
    ended_early = None
    # P15 bookkeeping: a turn the LOOP threw away (unparseable / truncated reply)
    # is not a turn the pilot chose to pass on, and a silent discard is
    # indistinguishable from a deliberate wait in every downstream number.
    discarded_turns = 0
    salvaged_turns = 0
    truncated_replies = 0
    # Run-level stall signal (D3). The adjacency guard answers "is the pilot
    # repeating itself RIGHT NOW"; this answers "is the RUN going anywhere",
    # which is the question a diffuse stall fails. A 599-action run once spread
    # its stalling across dozens of different dead targets, tripping the
    # adjacency guard exactly 0 times, and the stall was only ever found by a
    # human reading the transcript afterwards.
    #
    # REPORT-ONLY, deliberately: simulation showed that turning per-target
    # futility into a BLOCK is wrong for a game whose gates open over time —
    # 6 of 7 blocks would have suppressed a target that later became legitimately
    # playable, and no expiry policy fixed it. So this measures; it never vetoes.
    _stall_window = []
    _stall_win_size = int(playtest_cfg.get("stall_window", 20))
    _stall_floor = float(playtest_cfg.get("stall_min_productive", 0.20))
    stall_signal_steps = 0
    # Counted HERE, where materiality is known. The action_log stores the RAW
    # delta (line ~783), which for any game with a per-command counter (an RNG
    # cursor, a turn number) is never empty — deriving futility from the log
    # would report 0.0 forever and look healthy by construction (O2).
    productive_steps = 0
    material_steps_seen = 0
    # Shared mutable context for stateful invariants (invariant-fuzzer semantics:
    # one ctx per episode — cleared whenever the game resets mid-run).
    inv_ctx = {}
    start_time = time.time()

    for step_num in range(1, max_actions + 1):
        legal_list = None
        if action_mode == "legal_action":
            legal_list = adapter.legal_actions()
            if not legal_list:
                # ONGOING with no legal move would be a soft-lock; in practice this
                # means the match ended between steps. Reset to a fresh episode
                # rather than spin — same banking/re-baseline as a normal reset.
                pre_reset = current_state
                _close_episode(pre_reset, step_num - 1, "no_legal_actions")
                try:
                    current_state = _reset_episode()
                except Exception:
                    ended_early = "no_legal_actions_and_reset_failed"
                    break
                else:
                    bank_deltas(pre_reset)
                    baseline_state = json.loads(json.dumps(current_state, default=str))
                    episode_resets += 1
                    _episode_first_step = step_num
                    inv_ctx.clear()
                    reveals.note_reset(current_state)
                    continue
            terminal_text = ""
            prompt = _build_legal_prompt(config, strategy_guide, current_state,
                                         legal_list, action_log, playtest_cfg,
                                         noop_streaks=noop_streaks, ledger=action_ledger,
                                         repeat_streak=repeat_streak, quest_recall=quest_recall)
        else:
            terminal_text = adapter.get_terminal_text(terminal_budget)
            if _pending_recall and terminal_text:
                _pk, _ps = _pending_recall
                terminal_recall[_pk] = {"text": terminal_text, "step": _ps}
                _pending_value = _pk[0] if isinstance(_pk, tuple) else _pk
                _pending_verb = (_pending_value.split(None, 1)[0]
                                 if isinstance(_pending_value, str) and _pending_value else None)
                if _pending_verb in _quest_commands:
                    quest_recall[_pending_verb] = {"text": terminal_text, "step": _ps}
            _pending_recall = None
            if action_mode == "text":
                prompt = _build_terminal_prompt(config, strategy_guide, current_state,
                                                terminal_text, action_log, playtest_cfg,
                                                noop_streaks=noop_streaks, ledger=action_ledger,
                                                recall=terminal_recall, repeat_streak=repeat_streak,
                                                quest_recall=quest_recall)
            else:
                prompt = _build_prompt(config, strategy_guide, current_state, terminal_text, action_log,
                                       noop_streaks=noop_streaks, ledger=action_ledger,
                                       recall=terminal_recall, repeat_streak=repeat_streak,
                                       quest_recall=quest_recall)

        try:
            llm_action = llm.choose_action(prompt)
        except Exception as api_err:
            print(f"  [Step {step_num}] LLM error: {api_err}")
            ended_early = f"llm_error: {api_err}"
            break

        if llm_action.get("_discarded"):
            discarded_turns += 1
        if llm_action.get("_salvaged"):
            salvaged_turns += 1
        if llm_action.get("_truncated"):
            truncated_replies += 1

        action_type   = llm_action.get("action_type", "wait")
        value         = llm_action.get("value", "")
        reasoning     = llm_action.get("reasoning", "")
        expected      = llm_action.get("expected_outcome", "")
        potential_bug = llm_action.get("potential_bug", "")
        is_novel      = bool(llm_action.get("is_novel", False))

        # ── Hard repeat block: deterministic, not a prompt-level nudge ───────────────
        # The `repeat_streak` warning below (fed into the NEXT prompt) is a soft
        # signal — it asks the model to reconsider, it doesn't stop it. That's not
        # enough for a weak/local model: a live run on a terminal RPG integration had gemma4:26b repeat the
        # literal same command, `ls /home/jmiller`, 163 times in a row, restating
        # "I'm stuck in a loop" almost every time while picking it again anyway — a
        # markdown warning is advisory, and an LLM can simply not follow it. This
        # block makes back-to-back repetition past a hard ceiling IMPOSSIBLE, in code,
        # rather than discouraged in prose: the model's choice is overridden, not
        # just warned against. `wait` is the universal, game-agnostic override target
        # — it is already a no-op in every action_mode (see the `elif action_type ==
        # "wait": pass` branch below), so this never has to fabricate a plausible
        # game-specific command. Tunable per game via `playtest.repeat_block_threshold`
        # (default 3 — i.e. two consecutive identical picks are tolerated, a third is
        # not). If the model's own proposal already IS `wait`, forcing `wait` again
        # would be a no-op override, so that case is left alone rather than blocked.
        _forced_original_action = None
        _proposed_key = f"{action_type}:{value}"
        _consecutive_repeat = _consecutive_repeat + 1 if _proposed_key == _last_seq_key else 1
        _last_seq_key = _proposed_key
        _repeat_block_threshold = int(playtest_cfg.get("repeat_block_threshold", 3))
        if _consecutive_repeat >= _repeat_block_threshold and action_type != "wait":
            _forced_original_action = {"action_type": action_type, "value": value}
            print(f"  [BLOCKED] '{action_type}:{value}' would be the same action "
                  f"{_consecutive_repeat}x in a row — hard-blocked at "
                  f"repeat_block_threshold={_repeat_block_threshold}; forcing "
                  f"action_type='wait' instead of asking the LLM again "
                  f"(deterministic, not model-decided).")
            reasoning = (f"[FORCED by repeat-block guard] the model's proposed "
                         f"{action_type}:{value!r} was rejected — it would have been "
                         f"the same action {_consecutive_repeat} times in a row.")
            expected = ""
            action_type = "wait"
            value = ""
            is_novel = False
            # The executed action is now 'wait', not the rejected proposal — track
            # THAT for the next step's adjacency check, not the rejected one.
            _last_seq_key = f"{action_type}:{value}"
            _consecutive_repeat = 1

        # Feeds the NEXT prompt's '## Warnings' block (soft signal, one step ahead of
        # the hard block above) — cleared and re-set each step so it only ever holds
        # the single currently-active streak, never stale entries from an old one.
        repeat_streak.clear()
        if _consecutive_repeat >= 2:
            repeat_streak[_last_seq_key] = _consecutive_repeat

        print(f"  [Step {step_num}] {action_type}({value!r}) — {reasoning[:60]}")

        # Credit engagement BEFORE the action runs, so an item this very action reveals
        # can never be credited to it (revelation and engagement must not collapse).
        reveals.note_action(step_num, value)

        if potential_bug:
            potential_bugs.append(_make_bug_report(
                step=step_num,
                source="llm_flag",
                description=potential_bug,
                action_log=action_log,
                current_action={"step": step_num, "action_type": action_type,
                                "action": value, "expected": expected},
                # The LLM flags a suspected bug in the CURRENT state, before the
                # chosen action executes — so before/after are the same state here.
                preconditions=current_state,
                post_state=current_state,
                expected=expected,
                actual=potential_bug,
                terminal_text=terminal_text,
            ))
            print(f"  [!] Potential bug flagged: {potential_bug[:80]}")

        before_state = json.loads(json.dumps(current_state, default=str))
        terminated = truncated = False
        step_info = {}
        executed_action_id = None

        try:
            if action_type == "action_id":
                action_id = name_to_id.get(value)
                if action_id is None:
                    print(f"  [Step {step_num}] Unknown action name '{value}' — skipping")
                    continue
                executed_action_id = action_id
                current_state, terminated, truncated, step_info = adapter.step(action_id)

            elif action_type == "press_key":
                adapter.press_key(value)
                executed_action_id = -1
                step_info = {"key": value}
                try:
                    current_state, terminated, truncated, _ = adapter.step(0)
                except Exception:
                    pass

            elif action_type == "type_text":
                executed_action_id = -1
                # If the adapter's type_text semantically ADVANCES the game and can
                # report the resulting transition (type_text_step -> (state, term,
                # trunc, info)), capture it so the state-delta assertion and the
                # invariant checks see the REAL delta — never a vacuous empty one.
                # Adapters whose type_text is a pure keystroke-into-a-field (e.g. browser:
                # the text is buffered and only committed by a later
                # Enter/step) do NOT expose type_text_step, so they keep the existing
                # fire-and-forget behavior byte-for-byte. This is an added input
                # channel, not a change to the delta/fields/bug-report contract.
                if hasattr(adapter, "type_text_step"):
                    current_state, terminated, truncated, step_info = adapter.type_text_step(value)
                else:
                    adapter.type_text(value)
                    step_info = {"text": value}

            elif action_type == "wait":
                pass

            elif action_type == "diagnose":
                print(f"  [Step {step_num}] Agent is confused — flagging as potential bug")
                confusion_desc = f"Agent confusion: {reasoning}"
                potential_bugs.append(_make_bug_report(
                    step=step_num,
                    source="agent_confusion",
                    description=confusion_desc,
                    action_log=action_log,
                    current_action={"step": step_num, "action_type": action_type,
                                    "action": value, "expected": expected},
                    # 'diagnose' flags the current state as confusing/broken before
                    # any state transition — before/after are the same state.
                    preconditions=current_state,
                    post_state=current_state,
                    expected=expected,
                    actual=confusion_desc,
                    terminal_text=terminal_text,
                ))
                # `playtest.diagnose_resets_episode` (default True, preserving prior
                # behavior): unconditionally resetting the whole episode is the right
                # call for a short/cheap-to-restart episode (a browser level, a sim
                # match) — but the WRONG one for a long-running, persistent campaign
                # where "I don't know what to do next" and "the game state is broken"
                # are very different problems that got conflated into one response.
                # Found 2026-07-23 on a terminal RPG integration: a single `diagnose` (correct, well-reasoned
                # self-diagnosis of a stuck state) erased ~310 turns of real, valid
                # campaign progress — a cost the model was never even told about (the
                # LLM_ACTION_SCHEMA description just says "flag... confusing or
                # broken", no mention of a reset). Games that document their own
                # "no loss state" design (a terminal RPG, the trading-card game, the sci-fi board game) should set this
                # False so pilot confusion costs a turn, not the whole run.
                if bool(playtest_cfg.get("diagnose_resets_episode", True)):
                    pre_reset = current_state
                    _close_episode(pre_reset, step_num, "diagnose")
                    try:
                        current_state = _reset_episode()
                    except Exception:
                        pass
                    else:
                        bank_deltas(pre_reset)
                        baseline_state = json.loads(json.dumps(current_state, default=str))
                        episode_resets += 1
                        _episode_first_step = step_num + 1
                        inv_ctx.clear()
                        reveals.note_reset(current_state)
                    continue
                # Else: fall through like `wait` — current_state is untouched, so the
                # normal delta/logging/invariant pipeline below sees an empty delta and
                # records a real, auditable step instead of vanishing from the log the
                # way the reset path above deliberately does.

            elif action_type == "end_turn":
                # If the game maps an end-turn action, "turn complete" means EXECUTE it;
                # only games without one treat this as a pure signal.
                end_turn_id = name_to_id.get(value) or name_to_id.get("end_turn")
                if end_turn_id is not None:
                    executed_action_id = end_turn_id
                    current_state, terminated, truncated, step_info = adapter.step(end_turn_id)

            elif action_type == "legal_action":
                # value is the 0-based index of one action in THIS step's legal list.
                try:
                    idx = int(str(value).strip())
                except (ValueError, TypeError):
                    idx = -1
                if not legal_list or not (0 <= idx < len(legal_list)):
                    upper = (len(legal_list) - 1) if legal_list else -1
                    print(f"  [Step {step_num}] legal index {value!r} out of range 0..{upper} — skipping")
                    continue
                executed_action_id = -1  # sentinel: same convention as press_key/type_text
                current_state, terminated, truncated, step_info = adapter.apply_legal(
                    legal_list[idx], legal_count=len(legal_list))

        except Exception as exec_err:
            print(f"  [Step {step_num}] Execution error: {exec_err}")
            # The game is being reset mid-step: invariants must not compare the
            # pre-error state against the post-reset state (false violations —
            # same rule as invariant_fuzzer's crash path).
            executed_action_id = None
            pre_reset = current_state
            _close_episode(pre_reset, step_num, "execution_error")
            try:
                current_state = _reset_episode()
            except Exception:
                pass
            else:
                bank_deltas(pre_reset)
                baseline_state = json.loads(json.dumps(current_state, default=str))
                episode_resets += 1
                _episode_first_step = step_num + 1
                inv_ctx.clear()
                reveals.note_reset(current_state)

        action_counts[f"{action_type}:{value}"] = action_counts.get(f"{action_type}:{value}", 0) + 1

        # Machine-checked invariants (invariant-fuzzer contract) — run on every executed action.
        if invariant_list and executed_action_id is not None:
            for inv in invariant_list:
                try:
                    msg = inv.check(before_state, executed_action_id, step_info, current_state, inv_ctx)
                except Exception as inv_err:  # a broken check is itself worth surfacing
                    msg = f"invariant check crashed: {inv_err}"
                if msg:
                    invariant_violations.append({
                        "step": step_num,
                        "name": getattr(inv, "name", inv.__class__.__name__),
                        "message": msg,
                        "action_type": action_type,
                        "action": value,
                    })
                    print(f"  [!!] INVARIANT VIOLATION [{getattr(inv, 'name', '?')}]: {msg}")

        after_state = current_state
        # Record anything the game has newly revealed, and any progress it reports on
        # an item revealed earlier.
        reveals.observe(after_state, step_num)
        delta = _compute_delta(before_state, after_state)

        log_entry = {
            "step": step_num,
            "action_type": action_type,
            "action": value,
            "reasoning": reasoning,
            "expected": expected,
            "state_delta": delta,
        }
        # Mechanical expected-vs-delta escalation: the LLM rarely volunteers mismatches,
        # so surface state changes its stated expectation never mentioned. Heuristic
        # (leaf-name substring match) — an escalation signal for triage, not a verdict.
        surprises = _unexpected_delta_fields(delta, f"{expected} {reasoning}",
                                             redact=_prompt_hidden_paths(playtest_cfg))
        if surprises:
            log_entry["unexpected_deltas"] = surprises
        if _consecutive_repeat >= 2:
            log_entry["consecutive_repeat"] = _consecutive_repeat
        if _forced_original_action:
            log_entry["forced_by_repeat_block"] = _forced_original_action
        if is_novel:
            log_entry["is_novel"] = True
            novel_behaviors.append(log_entry)

        # Mechanical contradiction detector (Gate-C fix): the surprise heuristic only sees
        # deltas that HAPPENED — it is blind to expected deltas that DIDN'T. If the same
        # action keeps producing no material state change while the agent keeps expecting
        # one, that's either a silent game refusal (e.g. a hidden precondition) or the
        # agent stuck in a loop — both are auto-flag-worthy without LLM cooperation.
        #
        # "turn_number" is excluded by default, but a game may have its OWN administrative
        # field that ticks on every command regardless of whether the command had any real
        # effect (e.g. a terminal RPG's rngCounter, which advances even on a refused/no-op command by
        # design — NX-OBS-1). Without excluding that field too, EVERY action in such a game
        # always has a "non-empty" delta and this whole detector goes permanently inert for
        # that game. Games declare extra fields to ignore via playtest.ignore_delta_fields
        # in their ugt.config.yaml (matched on the full dotted key or its leaf name).
        _ignore_delta_fields = {"turn_number"} | set(playtest_cfg.get("ignore_delta_fields") or [])
        material_delta = {
            k: v for k, v in delta.items()
            if k not in _ignore_delta_fields and k.rsplit(".", 1)[-1] not in _ignore_delta_fields
        }
        # Feed the run-level window. Display-only verbs count as NON-productive
        # here on purpose: they are legitimate recon (which is why the LEDGER
        # exempts them from futility), but a run made only of them is not
        # advancing the game, and this metric asks whether the run is advancing.
        material_steps_seen += 1
        if material_delta:
            productive_steps += 1
        _stall_window.append(1 if material_delta else 0)
        if len(_stall_window) > _stall_win_size:
            _stall_window.pop(0)
        if (len(_stall_window) == _stall_win_size
                and sum(_stall_window) / _stall_win_size < _stall_floor):
            stall_signal_steps += 1
            print(f"  [STALL] last {_stall_win_size} steps moved the state "
                  f"{sum(_stall_window)}x (< {_stall_floor:.0%}) — the RUN is not "
                  f"advancing. Reported, not blocked.")
            _stall_window.clear()

        noop_key = f"{action_type}:{value}"
        # Some commands (e.g. a terminal RPG's `ls`/`analyze`) are legitimately display-only: their real
        # payload is rendered into terminal_text, not into any structured state field, so they will
        # NEVER show a material delta no matter how useful the information they just revealed was.
        # Tracking them in noop_streaks would auto-flag normal, repeatable recon as a "stuck loop"
        # false positive (found 2026-07-21: `ls` on a brand-new server flagged after 3 calls even
        # though each one legitimately listed a different directory). Games declare these verbs via
        # playtest.display_only_verbs in their ugt.config.yaml — matched on the first whitespace
        # token of `value`, so `"ls"` also exempts `"ls -la"` if a model ever types that variant.
        _display_only_verbs = set(playtest_cfg.get("display_only_verbs") or [])
        _verb = value.split(None, 1)[0] if isinstance(value, str) and value else value
        # Key the ledger by (action, CONTEXT) so location-scoped recon is not conflated:
        # `ls` at four different servers is four legitimate observations, not one repeat.
        # `playtest.action_context_path` names the state field that defines "where you are"
        # (e.g. a terminal RPG: currentServerId). Absent -> context None, i.e. plain per-action keying.
        _ctx_path = playtest_cfg.get("action_context_path")
        _ctx = _resolve_path(before_state, str(_ctx_path)) if _ctx_path else None
        _led = action_ledger.setdefault(
            (str(value), None if _ctx is None else str(_ctx)),
            {"tries": 0, "productive": 0, "last_step": step_num, "display_only": False})
        _pending_recall = ((str(value), None if _ctx is None else str(_ctx)), step_num)
        _led["tries"] += 1
        _led["last_step"] = step_num
        if _verb in _display_only_verbs:
            _led["display_only"] = True
        elif material_delta:
            _led["productive"] += 1

        if _verb in _display_only_verbs:
            pass
        elif not material_delta and action_type in ("action_id", "press_key", "type_text", "end_turn", "legal_action"):
            noop_streaks[noop_key] = noop_streaks.get(noop_key, 0) + 1
            if noop_streaks[noop_key] == 3:
                repeats = noop_streaks[noop_key]
                contradiction_desc = (
                    f"AUTO-FLAG (contradiction detector): action '{value}' produced no "
                    f"material state change {repeats} consecutive times "
                    f"while the agent expected: {expected[:160]!r}. Silent refusal "
                    f"(hidden precondition?) or stuck loop."
                )
                potential_bugs.append(_make_bug_report(
                    step=step_num,
                    source="contradiction_detector",
                    description=contradiction_desc,
                    action_log=action_log,
                    current_action={"step": step_num, "action_type": action_type,
                                    "action": value, "expected": expected},
                    preconditions=before_state,
                    post_state=after_state,
                    expected=expected,
                    actual=f"no material state change after {repeats} consecutive repeats",
                    terminal_text=terminal_text,
                    extra={"noop_repeats": repeats},
                ))
                print(f"  [!] AUTO-FLAG: '{value}' no-op x{noop_streaks[noop_key]} — silent refusal or stuck loop")
        else:
            noop_streaks[noop_key] = 0

        action_log.append(log_entry)

        if terminated or truncated:
            print(f"  [Step {step_num}] Episode ended (terminated={terminated}) — resetting")
            pre_reset = current_state
            # Closed BEFORE the reset, on the pre-reset state — that state is the
            # only place the outcome exists, and the reset overwrites it.
            _close_episode(pre_reset, step_num, "terminated" if terminated else "truncated")
            try:
                current_state = _reset_episode()
                bank_deltas(pre_reset)
                baseline_state = json.loads(json.dumps(current_state, default=str))
                episode_resets += 1
                _episode_first_step = step_num + 1
                inv_ctx.clear()
                reveals.note_reset(current_state)
                # Insert a marker so the LLM knows this is a fresh episode, not a crash.
                action_log.append({
                    "step": step_num,
                    "action_type": "episode_reset",
                    "action": "EPISODE_RESET",
                    "reasoning": "Episode ended normally (win/death/step-limit). Game has been reset to initial state.",
                    "expected": "Fresh episode — all stats restored",
                    "state_delta": {},
                })
            except Exception:
                ended_early = "reset_failed_after_episode_end"
                break

    duration = round(time.time() - start_time, 1)

    # The episode still in progress when the budget ran out is recorded too, with
    # its own end_reason, so a scorer can SEE it and exclude it deliberately.
    # Dropping it silently would understate the run; counting it as a finished
    # episode would put an unresolved match into an outcome tally (O8).
    _last_step = max((e.get("step", 0) for e in action_log), default=0)
    if _last_step >= _episode_first_step:
        _close_episode(current_state, _last_step, "budget_exhausted")

    # ── Per-run summary: deltas from the post-reset baseline (plus banked segments) ──
    real_actions = [e for e in action_log if e.get("action_type") != "episode_reset"]

    # Surprise metric noise floor: a key that changes on nearly every step (harness step
    # counters, per-action fuel ticks) carries no signal — only count steps whose
    # surprises include a NON-ubiquitous key. Per-step raw records stay in the log.
    #
    # Denominator is delta-bearing actions only, NOT all of real_actions: a `wait` step
    # (genuine or forced by the repeat-block guard) never touches the adapter, so its
    # state_delta is always {} by construction — it can contribute to no key's frequency
    # count but still inflates the denominator, artificially depressing every key's
    # ubiquity ratio. Found 2026-07-23: a 300-action run with 62 forced-wait steps saw
    # rngCounter's ratio fall to 238/300 (just under the 0.8 cutoff, purely from the
    # wait steps diluting it), which flipped `unexpected_delta_steps` from its usual
    # single digits to 238/238 — every real action "surprising" for a purely mechanical
    # reason, not a genuine change in pilot behavior.
    delta_bearing = [e for e in real_actions if e.get("action_type") != "wait"]
    key_freq = {}
    for e in delta_bearing:
        for k in (e.get("state_delta") or {}):
            key_freq[k] = key_freq.get(k, 0) + 1
    ubiquitous = {k for k, n in key_freq.items() if n >= 0.8 * max(1, len(delta_bearing))}
    unexpected_delta_steps = sum(
        1 for e in delta_bearing
        if any(k not in ubiquitous for k in (e.get("unexpected_deltas") or {}))
    )
    # Visibility only, not a bug count: immediate back-to-back repeats of the same action
    # are wasted pilot turns, not game defects (see `_noop_warning_block`'s repeat_streak).
    back_to_back_repeat_steps = sum(1 for e in real_actions if e.get("consecutive_repeat"))
    # How many times the hard repeat-block actually overrode the model's choice — the
    # deterministic ceiling firing, distinct from the soft warning above. Non-zero here
    # means the model tried to exceed repeat_block_threshold at least once; it does NOT
    # mean the model ever exceeded it, since the override makes that impossible.
    forced_repeat_blocks = sum(1 for e in real_actions if e.get("forced_by_repeat_block"))

    summary = {
        "actions_taken": len(real_actions),
        "duration_seconds": duration,
        "ended_early": ended_early,
        "episode_resets": episode_resets,
        "bugs_flagged": len(potential_bugs),
        "invariant_violations": len(invariant_violations),
        "unexpected_delta_steps": unexpected_delta_steps,
        "back_to_back_repeat_steps": back_to_back_repeat_steps,
        # P15: turns lost to the model<->loop channel rather than to the pilot.
        "discarded_turns": discarded_turns,
        "salvaged_turns": salvaged_turns,
        "truncated_replies": truncated_replies,
        # Stall measurement (report-only). `distinct_dead_targets` reads the
        # ledger that already exists rather than counting anything twice:
        # entries tried >= 3 times that NEVER moved the state, display-only
        # verbs excluded because their payload is terminal text by design.
        # A high count with stall_signal_steps == 0 means the pilot spread its
        # futility thinly; both high means the run stopped advancing outright.
        "stall_signal_steps": stall_signal_steps,
        "distinct_dead_targets": sum(
            1 for rec in action_ledger.values()
            if rec["tries"] >= 3 and rec["productive"] == 0 and not rec.get("display_only")
        ),
        "futile_step_fraction": (
            round(1 - (productive_steps / material_steps_seen), 3)
            if material_steps_seen else 0.0
        ),
        "forced_repeat_blocks": forced_repeat_blocks,
        # Episodes that reached a real ending, i.e. the only ones an outcome tally
        # may count. Kept separate from `episode_resets` (which counts resets of
        # every kind, including confusion and error recoveries) so a scorer never
        # has to guess which number is its denominator.
        "episodes_completed": sum(1 for e in episodes if e["end_reason"] in ("terminated", "truncated")),
        "episodes_recorded": len(episodes),
        # How many DISTINCT seeds the run actually played. 1 with more than one
        # episode is the P9 trap firing: the episodes are the same match.
        "distinct_episode_seeds": len({e["seed"] for e in episodes if e["seed"] is not None}),
        # The declared sample structure, and one sentence saying what the episode
        # count is actually worth. A reader should never have to infer that from
        # a seed column — "8 episodes" and "8 samples" are different claims, and
        # for a deterministic game they are never the same one.
        "seeding_mode": seeding_mode,
        "sample_note": seeding.sample_note(
            seeding_mode,
            len(episodes),
            len({e["seed"] for e in episodes if e["seed"] is not None}),
        ),
    }
    for e in summary_paths:
        final = _resolve_path(current_state, e["path"])
        base = _resolve_path(baseline_state, e["path"])
        label = e.get("label", e["path"])
        if isinstance(final, (int, float)) and isinstance(base, (int, float)):
            summary[label] = banked[e["path"]] + (final - base)
    # Progressive-content engagement (owner requirement). The counts go into `summary`
    # so `_aggregate_runs` gives them a mean/CI across a batch exactly like every other
    # numeric metric; the auditable per-item trail lives in the run report below.
    content_engagement = reveals.report(len(real_actions))
    if content_engagement.get("status") != "not_configured":
        summary["content_revealed_scored"] = content_engagement["required_scored"]
        summary["content_engaged"] = content_engagement["required_engaged"]
        summary["content_engagement_status"] = content_engagement["status"]
        # Only emit a RATE when the denominator is non-empty. Emitting 0.0 (or 1.0) for
        # a run that revealed nothing would put a fabricated number into the batch mean.
        if content_engagement["engagement_rate"] is not None:
            summary["content_engagement_rate"] = content_engagement["engagement_rate"]

    win_path = playtest_cfg.get("win_path")
    loss_path = playtest_cfg.get("loss_path")
    if win_path:
        summary["won_game"] = bool(_resolve_path(current_state, win_path))
    if loss_path:
        summary["lost_game"] = bool(_resolve_path(current_state, loss_path))

    return {
        "run": run_index,
        "total_actions": len(action_log),
        "duration_seconds": duration,
        "summary": summary,
        "content_engagement": content_engagement,
        "baseline_state": baseline_state,
        "final_state": current_state,
        # One record per episode: seed, step span, why it ended, and the game's
        # own declared outcome. This is what a batch is scored from.
        "episodes": episodes,
        "action_counts": action_counts,
        "potential_bugs": potential_bugs,
        "novel_behaviors": novel_behaviors,
        "invariant_violations": invariant_violations,
        "action_log": action_log,
    }


def _aggregate_runs(run_reports):
    """mean/std/95%-CI per numeric summary metric across runs (stdlib statistics;
    normal-approximation CI, same spirit as evaluate's seed-band aggregation)."""
    import math
    import statistics

    summaries = [r["summary"] for r in run_reports]
    n = len(summaries)
    aggregate = {"runs": n}

    numeric_keys = sorted({
        k for s in summaries for k, v in s.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    })
    for key in numeric_keys:
        values = [s.get(key, 0) for s in summaries]
        mean = statistics.mean(values)
        std = statistics.stdev(values) if n > 1 else 0.0
        half = 1.96 * std / math.sqrt(n) if n > 1 else 0.0
        aggregate[key] = {
            "mean": round(mean, 2),
            "std": round(std, 2),
            "ci95": [round(mean - half, 2), round(mean + half, 2)],
            "ci95_half_width": round(half, 2),
            "values": values,
        }

    aggregate["wins"] = sum(1 for s in summaries if s.get("won_game"))
    aggregate["losses"] = sum(1 for s in summaries if s.get("lost_game"))
    aggregate["runs_ended_early"] = sum(1 for s in summaries if s.get("ended_early"))
    aggregate["bugs_flagged_total"] = sum(s.get("bugs_flagged", 0) for s in summaries)
    aggregate["invariant_violations_total"] = sum(s.get("invariant_violations", 0) for s in summaries)
    return aggregate


def _print_run_summary(report, output_path):
    print(f"\n[+] Playtest complete in {report['duration_seconds']}s")
    # `total_actions` is len(action_log), which also counts the synthetic
    # EPISODE_RESET markers — so on a multi-episode run this line used to print
    # MORE "actions taken" than the max-actions budget allowed (96 actions and 9
    # resets read as "Actions taken: 105"). The summary's own count has always
    # been right; only this line was wrong, and it is the line people read.
    _taken = (report.get("summary") or {}).get("actions_taken", report["total_actions"])
    _resets = report["total_actions"] - _taken
    print(f"[+] Actions taken: {_taken}"
          + (f"  (+{_resets} episode-reset markers in the log)" if _resets else ""))
    print(f"[+] Potential bugs flagged: {len(report['potential_bugs'])}")
    print(f"[+] Invariant violations: {len(report.get('invariant_violations', []))}")
    print(f"[+] Novel behaviors observed: {len(report['novel_behaviors'])}")
    ce = report.get("content_engagement") or {}
    if ce.get("status") == "no_reveals":
        print("[+] Newly-revealed content: NONE revealed during this run — "
              "engagement is UNMEASURED (not a pass)")
    elif ce.get("status") and ce["status"] != "not_configured":
        print(f"[+] Newly-revealed content engaged: {ce['required_engaged']}/"
              f"{ce['required_scored']} required (rate={ce['engagement_rate']}, "
              f"status={ce['status']}, pending={ce['pending_at_run_end']})")
        for name, g in (ce.get("groups") or {}).items():
            missed = [i["item"] for i in g["items"]
                      if i["status"] == "missed" and not i["optional"]]
            print(f"    {name}: {g['required_engaged']}/{g['required_scored']} "
                  f"(revealed_during_run={g['revealed_during_run']}, "
                  f"at_start={g['revealed_at_start']}, optional={g['optional_revealed']})"
                  + (f" — ignored: {', '.join(missed)}" if missed else ""))
    if report.get("summary"):
        interesting = {k: v for k, v in report["summary"].items()
                       if k not in ("actions_taken", "duration_seconds")}
        print(f"[+] Summary: {interesting}")
    if report["potential_bugs"]:
        print("[!] Potential bugs:")
        for b in report["potential_bugs"]:
            print(f"    Step {b['step']}: {b['description'][:80]}")
    for v in report.get("invariant_violations", []):
        print(f"[!!] Invariant violation at step {v['step']} [{v['name']}]: {v['message'][:100]}")
    print(f"[+] Report: {output_path}")


# ---------------------------------------------------------------------------
# LLM backends
# ---------------------------------------------------------------------------

class _AnthropicLLM:
    """Anthropic API backend — uses tool_use to force structured JSON output."""

    def __init__(self, model):
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "The 'anthropic' package is required for --provider anthropic.\n"
                "Install it with: pip install 'ugt[playtest]'"
            )
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY environment variable is not set.\n"
                "Export it before running: export ANTHROPIC_API_KEY=sk-ant-..."
            )
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key)

    def choose_action(self, prompt):
        response = self._client.messages.create(
            model=self.model,
            # 4096, not the 512 this file was born with in 2026-07-05's first
            # spike and never revisited. `max_tokens` is a CEILING, not an
            # allocation — you are billed for tokens generated, so a bigger cap
            # costs nothing unless replies genuinely run longer, while a cap that
            # bites costs a whole pilot turn for a decision already made (P15).
            max_tokens=4096,
            tools=[{
                "name": "choose_action",
                "description": "Choose the next game action",
                "input_schema": LLM_ACTION_SCHEMA,
            }],
            tool_choice={"type": "any"},
            messages=[{"role": "user", "content": prompt}],
        )
        stop = getattr(response, "stop_reason", None)
        tool_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_block is None:
            raise RuntimeError(
                f"No tool_use block in Anthropic response (stop_reason={stop!r}). "
                f"If that is 'max_tokens', the cap cut the reply before the tool "
                f"call completed — raise max_tokens in _AnthropicLLM."
            )
        data = dict(tool_block.input or {})
        # This backend forces tool_use, so it never reaches `_parse_json_action`
        # and its salvage. A cap hit mid-tool-input therefore arrives as an EMPTY
        # or partial input dict, which the loop would silently read as a `wait` —
        # a discarded turn indistinguishable from a deliberate one. `stop_reason`
        # is authoritative regardless of how the SDK renders partial JSON, so
        # diagnose from it and mark the turn so the summary can count it (P15).
        if stop == "max_tokens" and not data.get("action_type"):
            print("  [warn] provider truncated the reply at max_tokens before the "
                  "decision was complete; turn discarded.")
            return {"action_type": "wait", "value": "",
                    "reasoning": "(provider truncated the reply at max_tokens)",
                    "expected_outcome": "", "_discarded": True}
        if stop == "max_tokens":
            data["_truncated"] = True
        return data


class _OllamaLLM:
    """Ollama backend — calls local server with JSON format mode."""

    DEFAULT_HOST = "http://localhost:11434"

    def __init__(self, model):
        self.model = model
        self.valid_actions = set()  # set by playtest_game; enables intent salvage in parsing
        self._host = os.environ.get("OLLAMA_HOST", self.DEFAULT_HOST).rstrip("/")
        self._verify_server()

    def _verify_server(self):
        try:
            req = urllib.request.Request(f"{self._host}/api/tags")
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception as e:
            raise RuntimeError(
                f"Ollama server not reachable at {self._host}.\n"
                f"Start it with: ollama serve\n"
                f"Error: {e}"
            )

    def choose_action(self, prompt):
        # Gemma 4 variants return empty content when a system role is present,
        # so we prepend the instructions directly into the user message instead.
        instructions = (
            "You are a game QA agent. Respond with ONLY a JSON object — no prose, no markdown fences.\n\n"
            "REQUIRED FORMAT (copy this structure exactly):\n"
            '{"action_type": "action_id", "value": "<one of the action names below>", '
            '"reasoning": "<why>", "expected_outcome": "<what happens>", '
            '"potential_bug": "", "is_novel": false}\n\n'
            "RULES: Use action_type=\"action_id\" to do things. "
            "Only use \"wait\" or \"diagnose\" when explicitly needed. "
            "potential_bug is empty string when nothing is wrong.\n\n"
        )
        combined = instructions + prompt

        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": combined}],
            "stream": False,
            "think": False,   # Gemma 4 thinking models hide output in <think> blocks; disable it
            # num_predict was 256 until 2026-07-26, when a Godot puzzle integration
            # showed what that costs. The required JSON puts `reasoning` and
            # `expected_outcome` AFTER the action, so a reply cut off mid-reasoning
            # is unparseable and the step becomes a forced `wait` — the model had
            # already decided, and the cap threw the decision away. Spatial games
            # produce longer reasoning than card games ("the player is at (3,2), the
            # crate is at (2,2), the target is at…"), so the cap bound there first
            # and nothing in the run summary said so. A truncated reply is never
            # useful, so a bigger ceiling can only ever preserve work.
            "options": {"temperature": 0.2, "num_predict": 512},
        }).encode()

        req = urllib.request.Request(
            f"{self._host}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Ollama HTTP {e.code}: {e.read().decode()[:200]}")

        raw = body.get("message", {}).get("content", "")
        return _parse_json_action(raw, self.valid_actions,
                                  getattr(self, "action_mode", "action_id"))


def _salvage_truncated_action(text, valid_actions, action_mode="action_id"):
    """Recover the decision from a reply the provider cut off mid-JSON.

    The response contract puts the action FIRST and the prose after it:

        {"action_type": "action_id", "value": "down", "reasoning": "the player is…

    so a reply truncated by the provider's token ceiling has usually already said
    what it wants to do — and the old behaviour threw that away and forced a
    `wait`, spending a step of the pilot's budget on nothing. Found on a Godot
    puzzle game, where spatial reasoning ("the player is at (4,2), the crate is
    at…") runs longer than a card game's and hit the ceiling first.

    Deliberately conservative — returns None unless the salvaged name is one the
    config actually declares, so this can never invent an action or coerce a
    hallucinated name onto a neighbouring id (§B P4). A salvage is also marked in
    the reasoning, so a transcript never implies the model said more than it did.

    **`action_mode="text"` needs its own rule, and without it the whole mechanism
    is inert for text-driven games.** There the value is a whole command LINE
    ("connect 10.0.0.5"), which is never a member of `valid_actions`, so the
    membership test above rejects every salvage and the turn burns as a `wait` —
    exactly the P15 defect, surviving the P15 fix. Found on a terminal-hacking
    RPG, the wordiest genre in the portfolio and the one likeliest to truncate.
    The declared-vocabulary guarantee is kept by checking the command's VERB (its
    first token) against the config instead of the whole line: `connect ...`
    recovers, `frobnicate ...` still refuses. The arguments are the model's own
    text and are never invented here.
    """
    if not valid_actions:
        return None
    m = re.search(r'"value"\s*:\s*"([^"]+)"', text)
    if not m:
        return None
    value = m.group(1)
    if action_mode == "text":
        verb = value.strip().split(" ", 1)[0].lower()
        if not verb or verb not in {str(a).lower() for a in valid_actions}:
            return None
        recovered_type = "type_text"
    else:
        if value not in valid_actions:
            return None
        recovered_type = "action_id"
    tail = text[m.end():]
    reasoning = ""
    rm = re.search(r'"reasoning"\s*:\s*"([^"]*)', tail)
    if rm:
        reasoning = rm.group(1)
    return {
        "action_type": recovered_type,
        "value": value,
        "reasoning": (reasoning + " [reply truncated by the provider's token limit; "
                      "action recovered from the prefix]").strip(),
        "expected_outcome": "",
        "_salvaged": True,
    }


def _parse_json_action(raw_text, valid_actions=None, action_mode="action_id"):
    """Parse LLM JSON response, tolerating markdown fences and minor formatting.

    `valid_actions` (a set of the config's action names) enables salvaging two common
    small-model mistakes instead of burning the step as a wait:
      {"action_type": "<action name>"}          -> action_id with that name
      {"action_type": "wait", "value": "<action name>"} -> action_id with that name
    """
    valid_actions = valid_actions or set()
    text = raw_text.strip()
    if not text:
        return {"action_type": "wait", "value": "", "reasoning": "(empty response)",
                "expected_outcome": "", "_discarded": True}
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract the first {...} block
        start = text.find("{")
        end = text.rfind("}") + 1
        data = None
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        if data is None:
            # Before burning the step: the reply may be a COMPLETE decision with an
            # incomplete tail. See `_salvage_truncated_action`.
            salvaged = _salvage_truncated_action(text, valid_actions, action_mode)
            if salvaged is not None:
                print(f"  [salvaged] response was cut off mid-JSON; recovered "
                      f"{salvaged['action_type']}={salvaged['value']!r} from the prefix.")
                return salvaged
            reason = "(parse error)" if start >= 0 and end > start else "(no json)"
            print(f"  [warn] Unparseable/absent JSON from LLM, skipping step: {text[:100]}")
            # `_discarded` marks a turn the LOOP threw away, not one the pilot
            # chose to wait on. Without it the two are indistinguishable in the
            # report and a silent discard reads as a deliberate pass (§B P15).
            return {"action_type": "wait", "value": "", "reasoning": reason,
                    "expected_outcome": "", "_discarded": True}

    # Validate required fields; salvage recognizable intents, else default gracefully
    atype = data.get("action_type")
    if atype not in _VALID_ACTION_TYPES:
        if atype in valid_actions:  # model put the action NAME in action_type
            data["action_type"] = "action_id"
            data["value"] = atype
        else:
            data["action_type"] = "wait"
    if data["action_type"] == "wait" and data.get("value") in valid_actions and data.get("value"):
        # model hedged: declared wait but named a real action — take it at its word
        data["action_type"] = "action_id"
    if "value" not in data:
        data["value"] = ""
    if "reasoning" not in data:
        data["reasoning"] = ""
    if "expected_outcome" not in data:
        data["expected_outcome"] = ""
    return data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json_safe(value):
    """Round-trip through JSON so a bug report never carries un-serializable objects."""
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return str(value)


def _make_bug_report(step, source, description, action_log, current_action,
                     preconditions, post_state, expected, actual, terminal_text,
                     tail=10, extra=None):
    """Structured BugReport shape (PLAYTEST-DESIGN.md §"Bug report shape").

    All three flag sites (LLM-volunteered, agent confusion/diagnose, and the mechanical
    contradiction detector) emit this SAME shape so reports are consistent across runs.
    Stays fully game-agnostic — no game-specific keys or strings.

    Design-spec keys (the floor): action_sequence, preconditions, post_state, expected,
    actual, terminal_text, reproducible. Additional keys kept for triage: step, source,
    description (source == which detector/flag fired).

    step            — 1-based step index at which the flag fired
    source          — which flag site emitted this (e.g. "llm_flag")
    description     — human-readable summary (kept from the legacy ad-hoc dict)
    action_log      — the run's action log; its tail becomes action_sequence
    current_action  — the action in flight at flag time, appended to the sequence
                      (None to append nothing)
    preconditions   — tracked state before the flagged step
    post_state      — tracked state after the flagged step
    expected/actual — what was expected vs. what actually happened, per site
    terminal_text   — terminal text at flag time (last ~600 chars kept; "" if none)
    tail            — how many prior log steps to include in action_sequence
    extra           — optional dict of extra site-specific keys merged in last
    """
    sequence = []
    for e in list(action_log)[-tail:]:
        sequence.append({
            "step": e.get("step"),
            "action_type": e.get("action_type"),
            "action": e.get("action"),
            "expected": e.get("expected", ""),
        })
    if current_action is not None:
        sequence.append(current_action)

    report = {
        # --- design-spec shape (the floor) ---
        "action_sequence": sequence,
        "preconditions": _json_safe(preconditions),
        "post_state": _json_safe(post_state),
        "expected": expected or "",
        "actual": actual or "",
        "terminal_text": (terminal_text or "")[-600:],
        "reproducible": None,
        # --- additional triage keys (kept from the legacy dict) ---
        "step": step,
        "source": source,
        "description": description,
    }
    if extra:
        report.update(extra)
    return report


def _action_ledger_block(ledger, cap=24):
    """Render what the agent has ESTABLISHED so far this run — cumulative situational
    knowledge, not a repetition penalty.

    LESSONS.md P10 ("the pilot needs memory, not just state"). The prompt otherwise shows
    only the current turn plus a short sliding window, so anything learned earlier is
    simply gone: on a terminal RPG, 2026-07-22, a 40-step run cycled the same six-step loop over the
    same two servers five times with **zero** consecutive repeats, so `noop_streaks`
    (which counts only CONSECUTIVE no-delta repeats and resets on any productive step)
    never fired, and the recent-actions window had slid past every repeat before the next
    one was chosen. The cumulative counts already existed in `action_counts` for the
    report and were never shown back to the agent.

    IMPORTANT — this block must NOT read as "do not repeat yourself". Repetition is
    correct play in most games: location-scoped recon (a terminal RPG's `ls`/`scan`/`analyze`) SHOULD
    be re-run every time the agent reaches a new place, and penalising that would suppress
    the exact behaviour the game wants. That is why entries are keyed by CONTEXT
    (`playtest.action_context_path`, e.g. `currentServerId`) — `ls` at four different
    servers reads as four separate, legitimate observations, while `ls` four times at the
    SAME server is visible as such and the agent can draw its own conclusion. The block
    reports; it does not instruct.

    Display-only verbs (`playtest.display_only_verbs`) are labelled, not scored as
    unproductive: their payload lands in terminal text by design.

    Bounded by DISTINCT (action, context) count, capped at `cap` with any overflow
    disclosed, so it does not grow with run length.
    """
    if not ledger:
        return ""
    entries = sorted(ledger.items(), key=lambda kv: (-kv[1]["last_step"], -kv[1]["tries"]))
    lines = []
    for key, rec in entries[:cap]:
        action, ctx = key if isinstance(key, tuple) else (key, None)
        where = f" at {ctx}" if ctx else ""
        times = f"{rec['tries']}x" if rec["tries"] > 1 else "once"
        if rec.get("display_only"):
            detail = "output was shown in the terminal"
        elif rec["productive"] == 0:
            detail = "no state change"
        elif rec["productive"] == rec["tries"]:
            detail = "changed state"
        else:
            detail = f"changed state {rec['productive']}/{rec['tries']}"
        lines.append(f"  step {rec['last_step']:>3}: {action!r}{where} — {times}, {detail}")
    if len(entries) > cap:
        lines.append(f"  … and {len(entries) - cap} earlier action(s) not listed")
    return (
        "## What you have already established this run\n"
        "(Everything you have done, including steps older than Recent Actions. Re-running a\n"
        "command somewhere NEW is normal and often correct play; this is here so you keep\n"
        "what you have already learned.)\n"
        + "\n".join(lines) + "\n\n"
    )


def _terminal_recall_block(recall, budget):
    """Replay the most recent terminal output the agent saw for each distinct
    (action, context) it has run — bounded by `playtest.terminal_recall_budget` chars.

    LESSONS.md P10, the deeper half. In some games the read layer lives ONLY in terminal
    output, never in structured state: e.g. a terminal RPG may expose `discoveredServers` as bare IPs, so a
    server's SECURITY LEVEL (from `scan`), its VULNERABILITY NAMES (from `analyze`, the sole
    source, and `exploit` needs an exact match) and its FILE LIST (from `ls`) are printed
    once and then lost when the single rolling terminal buffer moves on. The agent is left
    re-running recon not because it is looping, but because it genuinely no longer knows —
    and re-running recon is the correct response to not knowing.

    Retaining the LATEST output per (action, context) keeps that knowledge available without
    replaying the whole session: superseded outputs for the same key are overwritten, and the
    budget drops the oldest entries first. Default 0 = off, so games whose state already
    carries their read layer are unaffected.
    """
    if not recall or budget <= 0:
        return ""
    items = sorted(recall.items(), key=lambda kv: -kv[1]["step"])
    chunks, used = [], 0
    for key, rec in items:
        action, ctx = key if isinstance(key, tuple) else (key, None)
        where = f" at {ctx}" if ctx else ""
        text = (rec["text"] or "").strip()
        if not text:
            continue
        chunk = f"### step {rec['step']}: {action!r}{where}\n{text}\n"
        if used + len(chunk) > budget:
            break
        chunks.append(chunk)
        used += len(chunk)
    if not chunks:
        return ""
    dropped = len(items) - len(chunks)
    tail = f"(+{dropped} older output(s) no longer retained)\n" if dropped > 0 else ""
    return ("## Earlier terminal output you have seen (most recent first)\n"
            "These are the results of things you already did — the details here are still\n"
            "valid unless the game has changed them since.\n"
            + "\n".join(chunks) + tail + "\n")


class _RevealTracker:
    """Measures whether the pilot is AGILE about content the game reveals mid-run.

    The question this answers: when a game unlocks a new command or opens a new quest line, does
    the pilot notice and *do something about it* — or does it keep playing the game it
    already knew? Until now that was an eyeball judgement, which LESSONS.md P7 rejects:
    competence is read off the log, never inferred from the exit code.

    REVEALED and ENGAGED are deliberately separate:
      * REVEALED — an item APPEARS in a config-named state collection that was not there
        before. Purely a property of the game's state. Items already present in the state
        at reset are the STARTING KIT and are never scored (`revealed_at_start`).
      * ENGAGED  — the pilot then did something about that item, within `window` steps of
        the reveal. Three game-agnostic rules, any of which can fire (a group lists the
        ones that make sense for it):
          - "invoke"   the first whitespace token of the pilot's action equals the item
                       (a newly unlocked VERB was typed).
          - "mention"  the item id appears anywhere in the pilot's action string
                       (an argument-shaped item: `accept <id>`, `progress <id>`).
          - "progress" one of the item's own `progress_fields` INCREASED, or its
                       `status_field` entered `engage_status` — i.e. the game itself
                       reports the pilot advanced this item.
        An ATTEMPT counts, including one the game refuses: the behaviour under test is
        "did the pilot notice new content and try it", and a refusal is the game's
        answer, not the pilot's failure.

    Deliberate non-vacuity rules (LESSONS.md O2 — a score that cannot fail is prohibited):
      * A reveal in the last `window` steps of the run is PENDING, not missed — the run
        ended before the pilot could be judged. Pending items are excluded from the
        denominator and reported separately, so a late reveal is neither a free pass nor
        a free failure.
      * Items marked OPTIONAL (`optional_ids`, or an item field via `optional_field`) are
        counted and reported but never enter the denominator — the owner's rule that side
        quests are optional and are not an LLM test failure.
      * If nothing was ever revealed, the rate is `null` and the status is "no_reveals",
        never 1.0. An empty denominator is reported as an empty denominator.

    Config (`playtest.revealed_content`, a list of groups) — nothing game-specific lives
    in this module; a game names its own state paths:

        revealed_content:
          - name: "commands"          # label in the report
            path: "unlockedCommands"  # dotted path to a LIST in the adapter's state
            kind: "strings"           # flat list of scalars
            engage: ["invoke"]
            window: 12
          - name: "missions"
            path: "missions"
            kind: "objects"           # list of dicts keyed by id_field
            id_field: "missionId"
            engage: ["progress"]
            progress_fields: ["objectivesCompleted"]
            status_field: "status"
            engage_status: ["completed"]
            window: 20
            optional_ids: ["side_quest_a", "side_quest_b"]
            note: "caveat carried into the report"

    Episode resets re-baseline: the post-reset collection is the new starting kit, and
    items are keyed by (group, id, episode) so a second episode's reveals are their own.
    """

    _DEFAULT_WINDOW = 15

    def __init__(self, playtest_cfg):
        self.groups = []
        for raw in (playtest_cfg or {}).get("revealed_content") or []:
            if not isinstance(raw, dict) or "path" not in raw:
                continue
            engage = raw.get("engage") or ["invoke"]
            if not isinstance(engage, (list, tuple)):
                engage = [engage]
            progress_fields = raw.get("progress_fields") or []
            if not isinstance(progress_fields, (list, tuple)):
                progress_fields = [progress_fields]
            self.groups.append({
                "name": str(raw.get("name") or raw["path"]),
                "path": str(raw["path"]),
                "kind": str(raw.get("kind", "strings")),
                "id_field": raw.get("id_field"),
                "engage": {str(r) for r in engage},
                "progress_fields": [str(f) for f in progress_fields],
                "status_field": raw.get("status_field"),
                "engage_status": {str(s) for s in (raw.get("engage_status") or [])},
                "window": int(raw.get("window", self._DEFAULT_WINDOW)),
                "optional_ids": {str(x) for x in (raw.get("optional_ids") or [])},
                "optional_field": raw.get("optional_field"),
                "note": raw.get("note"),
            })
        self.enabled = bool(self.groups)
        self.episode = 0
        self._known = {}      # group name -> set of item ids seen so far this episode
        self._at_start = {}   # group name -> count of items present at a baseline
        self.items = []       # per-item records, the auditable trail

    # ── ingestion ────────────────────────────────────────────────────────────
    def rebaseline(self, state):
        """Adopt `state`'s collections as the starting kit (run start, and after every
        episode reset). Nothing here is a 'reveal' — it is what the pilot was handed."""
        if not self.enabled:
            return
        for g in self.groups:
            found = self._extract(g, state)
            self._known[g["name"]] = set(found)
            self._at_start[g["name"]] = self._at_start.get(g["name"], 0) + len(found)

    def note_action(self, step_num, value):
        """Record what the pilot just chose to do, and credit any revealed item it
        engages by "invoke"/"mention". Called BEFORE the action executes, so an item
        revealed BY this action can never be credited to it."""
        if not self.enabled:
            return
        text = str(value or "")
        low = text.lower()
        verb = low.split(None, 1)[0] if low.split() else ""
        for rec in self.items:
            if rec["status"] != "revealed" or rec["episode"] != self.episode:
                continue
            g = self._group(rec["group"])
            if step_num - rec["revealed_at_step"] > g["window"]:
                continue
            item = rec["item"].lower()
            if "invoke" in g["engage"] and verb and verb == item:
                self._engage(rec, step_num, "invoke", text)
            elif "mention" in g["engage"] and item and item in low:
                self._engage(rec, step_num, "mention", text)

    def observe(self, state, step_num):
        """Read the post-action state: credit "progress" engagement on already-revealed
        items, then record anything that has newly APPEARED."""
        if not self.enabled:
            return
        for g in self.groups:
            found = self._extract(g, state)
            known = self._known.setdefault(g["name"], set())
            if "progress" in g["engage"]:
                for rec in self.items:
                    if (rec["group"] != g["name"] or rec["episode"] != self.episode
                            or rec["status"] != "revealed"):
                        continue
                    if step_num - rec["revealed_at_step"] > g["window"]:
                        continue
                    now = found.get(rec["item"])
                    if self._progressed(g, rec["snapshot"], now):
                        self._engage(rec, step_num, "progress", "(game reported progress)")
            for item_id, entry in found.items():
                if item_id in known:
                    continue
                known.add(item_id)
                self.items.append({
                    "group": g["name"],
                    "item": item_id,
                    "episode": self.episode,
                    "revealed_at_step": step_num,
                    "optional": self._is_optional(g, item_id, entry),
                    "status": "revealed",
                    "engaged_at_step": None,
                    "engaged_by_rule": None,
                    "engaged_by_action": None,
                    "snapshot": entry if isinstance(entry, dict) else None,
                })

    def note_reset(self, state):
        self.episode += 1
        self.rebaseline(state)

    # ── scoring ──────────────────────────────────────────────────────────────
    def report(self, last_step):
        """Final tally. `last_step` is the run's final step index — it decides which
        reveals were still inside their window when the run ended (PENDING)."""
        if not self.enabled:
            return {"status": "not_configured",
                    "note": "no playtest.revealed_content groups declared for this game"}

        groups_out = {}
        for g in self.groups:
            recs = [r for r in self.items if r["group"] == g["name"]]
            for r in recs:
                if r["status"] == "revealed":
                    r["status"] = ("missed"
                                   if last_step - r["revealed_at_step"] >= g["window"]
                                   else "pending")
            required = [r for r in recs if not r["optional"]]
            optional = [r for r in recs if r["optional"]]
            scored = [r for r in required if r["status"] != "pending"]
            engaged = [r for r in scored if r["status"] == "engaged"]
            entry = {
                "path": g["path"],
                "window_steps": g["window"],
                "engage_rules": sorted(g["engage"]),
                "revealed_at_start": self._at_start.get(g["name"], 0),
                "revealed_during_run": len(recs),
                "required_scored": len(scored),
                "required_engaged": len(engaged),
                "required_missed": len(scored) - len(engaged),
                "pending_at_run_end": len([r for r in required if r["status"] == "pending"]),
                "optional_revealed": len(optional),
                "optional_engaged": len([r for r in optional if r["status"] == "engaged"]),
                "engagement_rate": (round(len(engaged) / len(scored), 3) if scored else None),
                "items": [{k: v for k, v in r.items() if k != "snapshot"} for r in recs],
            }
            if g["note"]:
                entry["caveat"] = str(g["note"])
            groups_out[g["name"]] = entry

        scored_total = sum(e["required_scored"] for e in groups_out.values())
        engaged_total = sum(e["required_engaged"] for e in groups_out.values())
        pending_total = sum(e["pending_at_run_end"] for e in groups_out.values())
        if scored_total == 0:
            status = "no_reveals"
            rate = None
        else:
            rate = round(engaged_total / scored_total, 3)
            status = "engaged" if engaged_total == scored_total else (
                "partial" if engaged_total else "ignored")
        return {
            # The denominator is the headline, not a footnote (O2/O8): a reader must be
            # able to see that a 100% rate came from 4 chances and not from zero.
            "status": status,
            "required_scored": scored_total,
            "required_engaged": engaged_total,
            "required_missed": scored_total - engaged_total,
            "pending_at_run_end": pending_total,
            "engagement_rate": rate,
            "groups": groups_out,
            "definition": (
                "REVEALED = an item newly APPEARED in a config-named state collection "
                "(items present at reset are the starting kit and are not scored). "
                "ENGAGED = the pilot invoked/mentioned it, or the game reported progress "
                "on it, within the group's window of steps AFTER the reveal. Items "
                "revealed inside the last window of the run are PENDING and excluded "
                "from the denominator. OPTIONAL items are reported but never scored. "
                "An empty denominator reports status 'no_reveals', never a perfect rate."
            ),
        }

    # ── internals ────────────────────────────────────────────────────────────
    def _group(self, name):
        return next(g for g in self.groups if g["name"] == name)

    def _engage(self, rec, step_num, rule, action_text):
        rec["status"] = "engaged"
        rec["engaged_at_step"] = step_num
        rec["engaged_by_rule"] = rule
        rec["engaged_by_action"] = action_text[:120]

    @staticmethod
    def _extract(group, state):
        """item id -> raw entry, for one group's collection in `state`."""
        node = _resolve_path(state, group["path"])
        out = {}
        if not isinstance(node, (list, tuple)):
            return out
        for entry in node:
            if group["kind"] == "objects":
                if not isinstance(entry, dict):
                    continue
                raw_id = entry.get(group["id_field"]) if group["id_field"] else None
                if raw_id is None:
                    continue
                out[str(raw_id)] = entry
            else:
                if isinstance(entry, (dict, list)):
                    continue
                out[str(entry)] = entry
        return out

    @staticmethod
    def _progressed(group, before, after):
        """Did the game itself report this item advancing? Numeric increase on any
        declared progress field, or a status transition into `engage_status`."""
        if not isinstance(after, dict):
            return False
        before = before if isinstance(before, dict) else {}
        for field in group["progress_fields"]:
            b, a = before.get(field), after.get(field)
            if isinstance(b, (int, float)) and isinstance(a, (int, float)) and a > b:
                return True
        sf = group["status_field"]
        if sf and group["engage_status"]:
            if str(after.get(sf)) in group["engage_status"] and before.get(sf) != after.get(sf):
                return True
        return False

    @staticmethod
    def _is_optional(group, item_id, entry):
        """Optional (side content) is read from the ITEM where the game marks it, and
        only falls back to a config id list where state carries no marker at all."""
        of = group["optional_field"]
        if isinstance(of, dict) and isinstance(entry, dict) and of.get("field") in entry:
            return entry.get(of["field"]) == of.get("value")
        return item_id in group["optional_ids"]


def _objective_block(playtest_cfg):
    """Optional `playtest.objective`: one line stating what WINNING means, rendered high
    in the prompt. The strategy guide states the goal too, but it sits at the BOTTOM of
    the prompt behind a full state dump and the terminal buffer — a long way from where
    the model commits to its next action. Game-agnostic: the text is entirely config."""
    objective = (playtest_cfg or {}).get("objective")
    if not objective:
        return ""
    return f"## Your objective\n{str(objective).strip()}\n\n"


def _quest_block(playtest_cfg, current_state, quest_recall):
    """Render an '## Open Quest Lines' section — what the agent currently knows about its
    active missions/quests, kept visible every turn regardless of location.

    Two config knobs, both optional and game-agnostic:
    - `playtest.quest_state_path`: a state field holding a list of mission/quest dicts
      (e.g. a terminal RPG's `missions`). Rendered as one compact line per entry (id/title, status,
      objective counts if present) — always fresh, since it comes straight from `current_state`.
    - `playtest.quest_commands`: verb names whose terminal output IS the quest detail view
      (e.g. a terminal RPG's `progress`/`missions` print the actual objective TEXT that never reaches
      structured state at all). Their latest output is shown here too.

    Why this needs to be its own block instead of relying on the generic terminal-recall
    mechanism: that recall is keyed by (command, currentServerId) — correct for
    location-scoped recon (`ls` at server A and server B are two different facts) but WRONG
    for quest status, which is player-global. Keying it by location fragments the same
    "what does this mission need" answer into multiple stale, duplicate, never-refreshed
    copies scattered across whatever server the pilot happened to be on each time it
    checked. `quest_recall` (populated in the main loop) is deliberately keyed by verb
    alone, so there is exactly ONE always-current entry per quest command regardless of
    where it was run. Found 2026-07-23: without this, a pilot's only view of what an
    active mission actually needs was incidental — present only if it happened to check
    recently, from anywhere — which is a plausible contributor to a real hacking-RPG run never
    progressing past its second mission across two full 300-action attempts.

    Freshness caveat is explicit in the rendered text, not hidden: recalled command output
    can go stale if the mission has progressed since it was last checked. This block cannot
    guarantee freshness the structured-state half doesn't already have — it only guarantees
    the LATEST check is never lost to the passage of turns or a change of location.
    """
    lines = []
    quest_state_path = (playtest_cfg or {}).get("quest_state_path")
    if quest_state_path:
        items = _resolve_path(current_state, str(quest_state_path))
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    lines.append(f"  - {it}")
                    continue
                label = it.get("missionId") or it.get("id") or it.get("title") or "?"
                bits = [str(label)]
                if it.get("status") is not None:
                    bits.append(f"status={it['status']}")
                comp, total = it.get("objectivesCompleted"), it.get("objectivesTotal")
                if comp is not None and total is not None:
                    bits.append(f"{comp}/{total} objectives")
                lines.append("  - " + ", ".join(bits))
    quest_commands = (playtest_cfg or {}).get("quest_commands") or []
    recall_chunks = []
    for verb in quest_commands:
        rec = (quest_recall or {}).get(verb)
        text = (rec["text"] if rec else "").strip() if rec else ""
        if not text:
            continue
        recall_chunks.append(f"### last '{verb}' output (step {rec['step']})\n{text}\n")
    if not lines and not recall_chunks:
        return ""
    body = ""
    if lines:
        body += "Active, from current state (always fresh):\n" + "\n".join(lines) + "\n"
    if recall_chunks:
        body += ("\nDetail from the last time you checked (may be stale if you've since "
                 "made progress — re-check if unsure):\n" + "\n".join(recall_chunks))
    return "## Open Quest Lines\n" + body + "\n"


def _available_actions_line(playtest_cfg, current_state, fallback):
    """The verb list shown to the agent: ALWAYS the full vocabulary, plus — when the game
    maintains its own live unlock list — an annotation naming what it currently reports as
    unlocked.

    ⚠️ This knob originally REPLACED the vocabulary with the game's live list, on the
    reasoning that the agent should never be advertised a verb the game will refuse. Live
    probing on a terminal RPG, 2026-07-22, showed that is dangerous: `unlockedCommands` there is a
    *hack-verb* unlock list (scan/connect/ls/cat/exploit/crack/escalate/backdoor/…) that
    omits `status`, `missions`, `accept`, `talk`, `choose` — and omitted the newly added
    `market`/`buy` entirely, which would have hidden a brand-new economy from the pilot.
    A partial list used as a replacement is an information-starvation defect (P1); used as
    an annotation it cannot hide anything. Annotate, never replace.

    Absent path, unresolvable path, or a non-list value → plain `fallback`, so games
    without such a field are unaffected.
    """
    path = (playtest_cfg or {}).get("available_actions_path")
    if path:
        live = _resolve_path(current_state, str(path))
        if isinstance(live, (list, tuple)) and live:
            names = ", ".join(str(v) for v in live)
            return (f"{fallback}\n  (the game currently reports these as unlocked: {names} — "
                    f"this list may be partial, so it does not rule out the others)")
    return fallback


def _noop_warning_block(noop_streaks, repeat_streak=None, threshold=2, block_threshold=3):
    """Render a '## Warnings' section covering two DISTINCT stall signals:

    1. `noop_streaks` — an action whose last `threshold`+ attempts produced no material
       state change. The SAME counter the contradiction detector uses to auto-flag a bug
       at 3 repeats, surfaced one step earlier so the agent gets a chance to notice and
       change course itself. Gated on material delta, and bypassed entirely for
       `playtest.display_only_verbs` (repeatable recon like a terminal RPG's `ls` legitimately
       never shows a delta, so it never reaches this dict at all).
    2. `repeat_streak` — literal back-to-back repetition of the SAME (action_type, value),
       independent of delta or display-only status. This is what `display_only_verbs`
       deliberately does NOT cover: `ls` used repeatedly over the course of a run (new
       location each time, or after other actions) is normal, correct play — but `ls`
       picked twice+ in an unbroken row shows the IDENTICAL terminal output both times by
       construction, so it is always wasted regardless of what the verb is. Found
       2026-07-22: gemma4:26b picked plain 'ls' 8 times in a row on an already-explored
       server with zero recovery, and because `ls` is display-only it never triggered
       (1) at all — this covers exactly that gap without penalising spaced-out reuse.
       This warning is now backed by a HARD, deterministic block in the main loop (see
       `repeat_block_threshold`) — the warning fires one step before the block would, so
       the agent gets a chance to self-correct, but unlike (1) it is not the only thing
       standing between the agent and an unbounded loop. Found 2026-07-23: even this
       warning, restated every step with a growing count, did not reliably stop gemma4:26b
       — a 300-action run repeated one command 163 times in a row regardless.

    Without this, both counts exist in memory the whole time but were never shown back to
    the agent — the 5-step 'Recent Actions' window alone is too short to reveal a pattern
    that repeats every 6+ steps — in one observed run 'accept' was repeated 11
    times, each one scrolled out of view before the next attempt, with no signal that it
    had ever been tried before)."""
    lines = [
        f"  '{key.split(':', 1)[-1]}' has produced NO material change the last {count} "
        f"time{'s' if count != 1 else ''} you tried it — do NOT just repeat it, try something else"
        for key, count in (noop_streaks or {}).items() if count >= threshold
    ]
    for key, count in (repeat_streak or {}).items():
        if count < threshold:
            continue
        action = key.split(':', 1)[-1]
        # Say the TRUE thing. The "will be REJECTED / hard rule" claim is only
        # honest when the very next repeat would actually hit the deterministic
        # ceiling — i.e. when `count + 1 >= playtest.repeat_block_threshold`.
        #
        # It used to be printed unconditionally, from a message written when the
        # threshold was always its default of 3. Any game that RAISES the
        # threshold (because repetition is legitimate play there) then had the
        # prompt asserting a rule the loop does not enforce, and models comply
        # with it: a browser dice game set the threshold to 13 and its pilot
        # wrote, at step 15 of 30, "I cannot use a3_d3 because I have used it 3
        # times in a row, which would be rejected" — and switched away from the
        # allocation its own strategy guide called correct. `forced_repeat_blocks`
        # for that run was 0: nothing was ever blocked. The warning was not
        # reporting a constraint, it was inventing one, and it steered the very
        # behaviour under test.
        #
        # This is LESSONS.md P10's own correction resurfacing in a second code
        # path: an anti-repetition NUDGE is actively harmful in the many games
        # where repeating an action is the right move. Report; do not instruct.
        if count + 1 >= block_threshold:
            lines.append(
                f"  you just picked '{action}' {count} times in a row, back-to-back — "
                f"an immediate repeat shows the exact SAME result every time. Picking it "
                f"again NOW will be REJECTED and forced to 'wait' instead — this is a hard "
                f"rule, not a suggestion. If you want to use it again later (e.g. after "
                f"moving or after another action), that's fine — just not right now"
            )
        else:
            lines.append(
                f"  you have picked '{action}' {count} times in a row. That is allowed "
                f"here — repeating an action is legitimate in many games — but if it is "
                f"producing the same result every time, consider whether something else "
                f"would tell you more. (A {block_threshold}th consecutive repeat would be "
                f"rejected.)"
            )
    if not lines:
        return ""
    return "## Warnings\n" + "\n".join(lines) + "\n\n"


_TRUNCATION_WARNED = set()


def _fit(text, budget, what, tail=False):
    """Apply a prompt char budget, and SAY SO the first time it actually bites.

    LESSONS.md P3 ("truncation is silent starvation"): the budgets are the quietest
    way to blind a pilot — the guide's rules or the terminal's read layer just stop
    existing partway through, the run still reports PLAYTEST MET, and the resulting
    balance number is measuring a player who was never told the rules. Two trading-card-game
    batches were lost to exactly this before the budgets were raised
    2000→6000→11000. Warn once per (what, budget) per process so a long run does not
    spam, but never truncate silently.

    `tail=True` keeps the END of the text (terminal output — the newest lines);
    otherwise the START is kept (the guide reads top-down).
    """
    text = text or ""
    if len(text) <= budget:
        return text
    key = (what, budget)
    if key not in _TRUNCATION_WARNED:
        _TRUNCATION_WARNED.add(key)
        kept = "last" if tail else "first"
        print(
            f"[WARN] {what} TRUNCATED: {len(text)} chars > budget {budget} — the LLM sees only the "
            f"{kept} {budget}. Raise `playtest.{'terminal' if tail else 'guide'}_char_budget` in "
            f"ugt.config.yaml, or the pilot is playing without part of it (LESSONS.md P3)."
        )
    return text[-budget:] if tail else text[:budget]


def _compact_state_block(state, budget, what="Current State"):
    """Render `state` as JSON within `budget` chars by COMPACTING large lists rather than
    truncating the serialized text.

    `_fit()`'s blind text cut is correct for prose (terminal output, the guide) — the
    reader loses the least-recent/least-important end. It is the WRONG tool for a JSON
    blob: slicing the serialized string at an arbitrary byte offset produces invalid JSON
    and drops whatever field happens to fall after the cut, regardless of importance (the
    `missions` array is exactly as likely to be sacrificed as a `discoveredServers` entry
    nobody needs). Compaction instead shrinks the largest list-valued fields FIRST, at every
    nesting level, keeping the JSON valid and every top-level field present throughout —
    only the enumeration of a long list gets shorter, never a whole field.

    budget<=0 disables this (unbounded, matches `_fit`'s off-switch convention). Warns once
    per (what, budget) per process, same convention as `_fit`, only if even the most
    aggressive compaction (keep=1 per list) still doesn't fit — at that point the
    most-compacted form is returned anyway rather than ever truncating the JSON text itself.
    """
    full = json.dumps(state, indent=2, default=str)
    if budget <= 0 or len(full) <= budget:
        return full

    def _compact(obj, keep):
        if isinstance(obj, list):
            kept = [_compact(v, keep) for v in obj[:keep]]
            if len(obj) > keep:
                kept.append(f"… +{len(obj) - keep} more ({len(obj)} total — not shown to save prompt space)")
            return kept
        if isinstance(obj, dict):
            return {k: _compact(v, keep) for k, v in obj.items()}
        return obj

    result = full
    for keep in (8, 4, 2, 1):
        candidate = json.dumps(_compact(state, keep), indent=2, default=str)
        result = candidate
        if len(candidate) <= budget:
            return candidate

    key = (what, budget)
    if key not in _TRUNCATION_WARNED:
        _TRUNCATION_WARNED.add(key)
        print(
            f"[WARN] {what} is {len(result)} chars even after maximum compaction "
            f"(budget {budget}) — every list is down to 1 item and it still doesn't fit. "
            f"Raise `playtest.state_char_budget` in ugt.config.yaml. Showing the "
            f"most-compacted form rather than truncating mid-JSON."
        )
    return result


def _redaction_paths(playtest_cfg):
    """Config knob `playtest.redact_state_fields` — the tier's FOG OF WAR list.

    Dot-separated state paths whose values the game's own wire protocol HIDES from
    the acting player but the adapter's normalized state must carry for machine
    checks — e.g. the trading-card game's card-conservation invariant needs the
    god-view `committedCard` term, while the engine's redacted opponent view
    exposes only `hasCommitted`. These paths are dropped from EVERY channel the
    LLM reads (the state JSON *and* the recent-action delta summaries); logs,
    invariants and reports keep the full state.

    **This is not the knob for "the same information, rendered somewhere else"** —
    that is `hide_from_state_block` (below), and conflating the two costs real
    signal. See its docstring for what it cost.
    """
    return [str(p) for p in (playtest_cfg or {}).get("redact_state_fields") or []]


def _state_block_only_paths(playtest_cfg):
    """Config knob `playtest.hide_from_state_block` — CONTEXT ECONOMY, not fog of war.

    Dot-separated state paths the pilot is fully entitled to see, but which are
    already rendered to it in a better form elsewhere in the prompt (typically the
    Terminal panel). They are dropped from the `## Current State` JSON only, and
    are STILL PRESENT in the recent-action delta summaries.

    Why the distinction is load-bearing, and what conflating it cost (found
    2026-07-26 on a Godot puzzle integration): that game put a whole-board ASCII
    render (`grid`) into `redact_state_fields` purely to avoid printing the same
    board twice, since the aligned copy in the Terminal panel is the one a player
    looks at. Because `redact_state_fields` also strips the deltas, the board
    silently vanished from all twelve history entries too — and in that game a
    push to a non-target cell moves no visible scalar at all, so a crate-pushing
    move and a plain walk rendered identically in the pilot's own memory
    (`Step 2: up → {'player_y': '-1'}`). The single most important feedback signal
    in the game reached the pilot on ZERO channels beyond one current-frame
    snapshot. A context-economy decision had become an information restriction.

    So: `redact_state_fields` when the game hides it from the player;
    `hide_from_state_block` when the prompt shows it elsewhere. Default absent, so
    every existing config renders byte-identically.
    """
    return [str(p) for p in (playtest_cfg or {}).get("hide_from_state_block") or []]


def _prompt_hidden_paths(playtest_cfg):
    """The union of both knobs — every path absent from the `## Current State` JSON.

    Also what every *analysis* path must exclude (§B P16): the surprise heuristic
    matches a delta key's leaf name against the pilot's prose, and a field whose
    NAME never appears in the state block cannot fairly be matched against prose
    that calls it "the board". Using the union there also means nothing RECORDED
    changes when a path moves between the two lists.
    """
    return _redaction_paths(playtest_cfg) + _state_block_only_paths(playtest_cfg)


def _redact_state(state, paths):
    """A deep copy of `state` with each dotted path removed. No paths → `state`
    unchanged (no copy)."""
    if not paths or not isinstance(state, dict):
        return state
    redacted = json.loads(json.dumps(state, default=str))
    for path in paths:
        parts = path.split(".")
        node = redacted
        for part in parts[:-1]:
            node = node.get(part) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict):
            node.pop(parts[-1], None)
    return redacted


def _redact_delta(delta, paths):
    """Delta dicts are already flattened to dotted keys — drop exact matches."""
    if not paths or not isinstance(delta, dict):
        return delta
    hidden = set(paths)
    return {k: v for k, v in delta.items() if k not in hidden}


def _recent_actions_summary(action_log, redact, window=5):
    """The recent-actions block shared by all prompt builders, with fog-of-war paths
    removed from the displayed deltas. `window` is `playtest.history_window` (default
    5). It is a SLIDING window, so it can only reveal a behavioural cycle shorter than
    itself — the cumulative `_action_ledger_block` is what covers longer ones.

    `redact` here is `redact_state_fields` ONLY — deliberately not the union with
    `hide_from_state_block`. What the prompt renders in another panel is still part
    of the pilot's memory of what its own moves DID; see
    `_state_block_only_paths` for the defect that distinction fixes. This block has
    no char budget of its own (only `window` bounds it), so a game that puts a
    large field on this channel should size `history_window` knowing that."""
    window = max(1, int(window or 5))
    recent_log = action_log[-window:] if len(action_log) > window else action_log
    return "\n".join(
        f"  Step {e['step']}: {e['action']} → {_redact_delta(e.get('state_delta', {}), redact)}"
        for e in recent_log
    ) or "  (no actions taken yet)"


def _build_prompt(config, strategy_guide, current_state, terminal_text, action_log, noop_streaks=None,
                  ledger=None, recall=None, repeat_streak=None, quest_recall=None):
    playtest_cfg = config.data.get("playtest", {}) if isinstance(config.data, dict) else {}
    guide_budget = int(playtest_cfg.get("guide_char_budget", 2000))
    state_char_budget = int(playtest_cfg.get("state_char_budget", 4000))
    terminal_budget = int(playtest_cfg.get("terminal_char_budget", 400))

    # Two lists, two jobs: `redact` is fog of war and applies to every channel;
    # `block_hidden` additionally drops what is rendered elsewhere in this prompt.
    redact = _redaction_paths(playtest_cfg)
    block_hidden = _prompt_hidden_paths(playtest_cfg)

    action_lines = []
    for action_id, action_def in config.action_mappings.items():
        name = action_def.get("name", str(action_id)) if isinstance(action_def, dict) else str(action_def)
        action_lines.append(f"  {action_id}: {name}")

    recent_summary = _recent_actions_summary(action_log, redact, playtest_cfg.get('history_window', 5))

    action_name_list = ", ".join(
        (action_def.get("name", str(aid)) if isinstance(action_def, dict) else str(action_def))
        for aid, action_def in config.action_mappings.items()
    )

    return (
        f"You are playtesting {config.project_name}. Choose the best next action.\n\n"
        f"NOTE: If you see EPISODE_RESET in recent actions, that means the previous episode ended normally "
        f"(win, death, or step limit) and the game restarted fresh — this is NOT a bug. "
        f"Do NOT use 'diagnose' for episode resets. Continue playing from the current state.\n\n"
        f"VALID action names (use one as value when action_type=action_id):\n"
        f"  {action_name_list}\n\n"
        + _objective_block(playtest_cfg)
        + _quest_block(playtest_cfg, current_state, quest_recall)
        + f"## Current State\n"
        + _key_values_line(playtest_cfg, current_state)
        + f"```json\n{_compact_state_block(_redact_state(current_state, block_hidden), state_char_budget, 'Current State')}\n```\n\n"
        f"## Recent Actions\n{recent_summary}\n\n"
        + _noop_warning_block(noop_streaks, repeat_streak,
                              block_threshold=int(playtest_cfg.get('repeat_block_threshold', 3)))
        + _action_ledger_block(ledger)
        + _terminal_recall_block(recall, int(playtest_cfg.get('terminal_recall_budget', 0)))
        + f"## Terminal Output\n```\n{_fit(terminal_text, terminal_budget, 'Terminal output', tail=True)}\n```\n\n"
        f"## Strategy Guide\n{_fit(strategy_guide, guide_budget, 'Strategy guide')}\n\n"
        f"Respond JSON only. Use action_type=\"action_id\" and value=<one of the action names above>."
    )


def _build_legal_prompt(config, strategy_guide, current_state, legal_list, action_log, playtest_cfg,
                        noop_streaks=None, ledger=None, recall=None, repeat_streak=None, quest_recall=None):
    """Prompt for legal_action mode: the adapter's own structured state (serialized
    JSON — the exact shape the game's ladder scripts read) plus its live legal-action
    list. Game-agnostic: each legal action is dumped as its raw JSON, with no
    game-specific interpretation in this module."""
    project = getattr(config, "project_name", None) or "the game"
    playtest_cfg = playtest_cfg or {}
    guide_budget = int(playtest_cfg.get("guide_char_budget", 2000))
    state_char_budget = int(playtest_cfg.get("state_char_budget", 4000))

    redact = _redaction_paths(playtest_cfg)
    block_hidden = _prompt_hidden_paths(playtest_cfg)

    legal_lines = "\n".join(
        f"  {i}: {json.dumps(a, default=str)}" for i, a in enumerate(legal_list)
    ) or "  (no legal actions)"

    recent_summary = _recent_actions_summary(action_log, redact, playtest_cfg.get('history_window', 5))

    upper = len(legal_list) - 1
    return (
        f"You are playtesting {project}. Choose the best next action.\n\n"
        f"NOTE: If you see EPISODE_RESET in recent actions, the previous episode "
        f"ended normally (win/draw/step limit) and the game restarted — NOT a bug.\n\n"
        + _objective_block(playtest_cfg)
        + _quest_block(playtest_cfg, current_state, quest_recall)
        + f"## Current State\n"
        + _key_values_line(playtest_cfg, current_state)
        + f"```json\n{_compact_state_block(_redact_state(current_state, block_hidden), state_char_budget, 'Current State')}\n```\n\n"
        f"## LEGAL ACTIONS (respond with action_type=\"legal_action\", value=<the NUMBER>)\n"
        f"{legal_lines}\n\n"
        f"## Recent Actions\n{recent_summary}\n\n"
        + _noop_warning_block(noop_streaks, repeat_streak,
                              block_threshold=int(playtest_cfg.get('repeat_block_threshold', 3)))
        + _action_ledger_block(ledger)
        + f"## Strategy Guide\n{_fit(strategy_guide, guide_budget, 'Strategy guide')}\n\n"
        f"Respond JSON only. action_type=\"legal_action\", value=\"<index 0..{upper}>\"."
    )


def _build_terminal_prompt(config, strategy_guide, current_state, terminal_text, action_log, playtest_cfg,
                           noop_streaks=None, ledger=None, recall=None, repeat_streak=None, quest_recall=None):
    """Prompt for "text" mode: the LLM drives the game by TYPING a raw command line
    (action_type="type_text"), exactly as a human at the terminal would. The adapter's
    own get_terminal_text output and structured state are shown; the command vocabulary
    is listed from config.action_mappings, but the LLM types the FULL command line
    (verb + any argument). Argument syntax — which files / servers / missions / targets
    to name — lives in the game's own strategy guide, never in this module, so this
    stays game-agnostic (no game-specific strings here)."""
    playtest_cfg = playtest_cfg or {}
    guide_budget = int(playtest_cfg.get("guide_char_budget", 2000))
    state_char_budget = int(playtest_cfg.get("state_char_budget", 4000))
    terminal_budget = int(playtest_cfg.get("terminal_char_budget", 400))
    project = getattr(config, "project_name", None) or "the game"

    action_mappings = getattr(config, "action_mappings", None) or {}
    command_names = ", ".join(
        (a.get("name", str(k)) if isinstance(a, dict) else str(a))
        for k, a in action_mappings.items()
    ) or "(see the strategy guide)"

    redact = _redaction_paths(playtest_cfg)
    block_hidden = _prompt_hidden_paths(playtest_cfg)
    recent_summary = _recent_actions_summary(action_log, redact, playtest_cfg.get('history_window', 5))

    return (
        f"You are playtesting {project} at its TERMINAL. Type ONE command line to play.\n\n"
        f"NOTE: If you see EPISODE_RESET in recent actions, the previous episode ended "
        f"normally (win/death/step limit) and the game restarted — NOT a bug. Keep playing.\n\n"
        f"## Available command verbs (type the FULL line: verb + any argument it needs)\n"
        f"  {command_names}\n"
        f"  (Which files / servers / missions / targets to name as arguments is in the "
        f"Strategy Guide below — read the Current State to fill in REAL arguments.)\n\n"
        + _objective_block(playtest_cfg)
        + _quest_block(playtest_cfg, current_state, quest_recall)
        + f"## Current State\n"
        + _key_values_line(playtest_cfg, current_state)
        + f"```json\n{_compact_state_block(_redact_state(current_state, block_hidden), state_char_budget, 'Current State')}\n```\n\n"
        f"## Recent Actions\n{recent_summary}\n\n"
        + _noop_warning_block(noop_streaks, repeat_streak,
                              block_threshold=int(playtest_cfg.get('repeat_block_threshold', 3)))
        + _action_ledger_block(ledger)
        + _terminal_recall_block(recall, int(playtest_cfg.get('terminal_recall_budget', 0)))
        + f"## Terminal Output\n```\n{_fit(terminal_text, terminal_budget, 'Terminal output', tail=True)}\n```\n\n"
        f"## Strategy Guide\n{_fit(strategy_guide, guide_budget, 'Strategy guide')}\n\n"
        f"Respond JSON only. Use action_type=\"type_text\" and "
        f"value=\"<the full command line to type>\"."
    )


def _resolve_path(state, path):
    """Resolve a dot-separated path into a nested dict; None if any hop is missing."""
    node = state
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _key_values_line(playtest_cfg, current_state):
    """Optional '⚡ KEY VALUES' prompt line, driven entirely by the config's
    playtest.key_state_paths ({path, label, note} entries). Games declare which state
    fields the LLM should watch — nothing game-specific lives in this module."""
    paths = playtest_cfg.get("key_state_paths") or []
    if not paths or not isinstance(current_state, dict):
        return ""
    parts = []
    for entry in paths:
        if not isinstance(entry, dict) or "path" not in entry:
            continue
        value = _resolve_path(current_state, entry["path"])
        if value is None:
            continue
        label = entry.get("label", entry["path"])
        note = entry.get("note")
        parts.append(f"{label}={value}" + (f" ({note})" if note else ""))
    if not parts:
        return ""
    return "⚡ KEY VALUES: " + ", ".join(parts) + "\n\n"


def _unexpected_delta_fields(delta, expectation_text, redact=None):
    """State-change keys whose leaf name the LLM's expectation/reasoning never mentioned.

    Heuristic escalation only: leaf-name substring match, underscores also matched as
    spaces (e.g. delta key 'ship.shield_strength' is 'mentioned' by 'shield strength').

    **A field absent from the state block can never be a surprise.** Pass
    `redact=_prompt_hidden_paths(cfg)` — the union of `redact_state_fields` (fog of
    war: the pilot is deliberately not shown it) and `hide_from_state_block` (the
    pilot is shown it in another panel, under another name). Either way this
    heuristic works by matching the delta key's LEAF NAME against the pilot's
    prose, and a field whose name never appears in the state block cannot fairly
    be matched against prose that calls it "the board". Recording it as something
    the pilot "failed to predict" charges it for information it was denied — and it
    is exactly the fields that change often which look worst. Found 2026-07-26 on a
    Godot puzzle integration that hides `grid` (a whole-board render) and redacts
    `moves_taken`: every successful move logged both as unexpected. There the
    summary's ubiquity floor happened to absorb it, which is luck rather than
    correctness — a hidden field changing on half the steps sits under that floor
    and would be counted forever. Taking the union also means nothing RECORDED
    moves when a path is reclassified from one list to the other.
    """
    text = (expectation_text or "").lower()
    redact = set(redact or ())
    surprises = {}
    for key, change in delta.items():
        leaf = key.rsplit(".", 1)[-1]
        if key in redact or leaf in redact:
            continue
        if leaf.lower() in text or leaf.lower().replace("_", " ") in text:
            continue
        surprises[key] = change
    return surprises


def _compute_delta(before, after, prefix=""):
    delta = {}
    if not isinstance(before, dict) or not isinstance(after, dict):
        return delta
    all_keys = set(before.keys()) | set(after.keys())
    for key in all_keys:
        full_key = f"{prefix}.{key}" if prefix else key
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

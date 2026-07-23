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
import sys
import time
import urllib.request
import urllib.error

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
                     .check(before, action_id, info, after, ctx) (the exploit-hunter
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
    elif config.engine_type == "real_server":
        from ugt.adapters.realclient import RealClientAdapter
        adapter = RealClientAdapter(config)
    else:
        raise ValueError(f"Unknown engine type: '{config.engine_type}'")

    return _run_and_write(adapter, llm, config, strategy_guide, max_actions,
                          output_path, provider, runs, invariants,
                          action_mode="action_id")


def playtest_game_with_adapter(adapter, provider, strategy_guide, max_actions=100,
                               output_path=None, model=None, runs=1, invariants=None,
                               action_mode="legal_action", config=None):
    """Playtest via an ALREADY-CONSTRUCTED adapter instance (L-002).

    The three JSON-lines harness adapters (DDD / Nexus-Dominion / Pond) are not
    registered under an `engine.type` in env.py — each game's own ladder scripts
    build the adapter directly. This entry point takes that adapter and runs the
    SAME LLM loop as `playtest_game`; the only difference is the input/action
    channel (`action_mode`, e.g. "legal_action"). It is the integration seam L-006
    (NEXUS text-driven mode) will reuse.

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
                with open(run_path, "w") as f:
                    json.dump(run_report, f, indent=2, default=str)
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
        with open(out, "w") as f:
            json.dump(report, f, indent=2, default=str)
        _print_run_summary(report, out)
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
    with open(out, "w") as f:
        json.dump(summary_report, f, indent=2, default=str)

    print(f"\n[+] Playtest batch complete: {runs} runs × {max_actions} actions")
    for label, stats in aggregate.items():
        if isinstance(stats, dict) and "mean" in stats:
            print(f"    {label}: mean={stats['mean']} ±{stats['ci95_half_width']} (95% CI), "
                  f"std={stats['std']}, values={stats['values']}")
        else:
            print(f"    {label}: {stats}")
    print(f"[+] Summary: {out}")
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

    current_state = adapter.reset()
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
    # so terminal-only knowledge (NEXUS security levels / vuln names / file lists) survives
    # past the single rolling buffer. Populated one step late: at the top of iteration N+1
    # the fetched terminal_text IS the output of action N, so no extra adapter call.
    terminal_recall = {}
    _pending_recall = None  # (key, step) awaiting its output on the next iteration
    ended_early = None
    # Shared mutable context for stateful invariants (exploit-hunter semantics:
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
                try:
                    current_state = adapter.reset()
                except Exception:
                    ended_early = "no_legal_actions_and_reset_failed"
                    break
                else:
                    bank_deltas(pre_reset)
                    baseline_state = json.loads(json.dumps(current_state, default=str))
                    episode_resets += 1
                    inv_ctx.clear()
                    reveals.note_reset(current_state)
                    continue
            terminal_text = ""
            prompt = _build_legal_prompt(config, strategy_guide, current_state,
                                         legal_list, action_log, playtest_cfg,
                                         noop_streaks=noop_streaks, ledger=action_ledger)
        else:
            terminal_text = adapter.get_terminal_text(terminal_budget)
            if _pending_recall and terminal_text:
                _pk, _ps = _pending_recall
                terminal_recall[_pk] = {"text": terminal_text, "step": _ps}
            _pending_recall = None
            if action_mode == "text":
                prompt = _build_terminal_prompt(config, strategy_guide, current_state,
                                                terminal_text, action_log, playtest_cfg,
                                                noop_streaks=noop_streaks, ledger=action_ledger,
                                                recall=terminal_recall)
            else:
                prompt = _build_prompt(config, strategy_guide, current_state, terminal_text, action_log,
                                       noop_streaks=noop_streaks, ledger=action_ledger,
                                       recall=terminal_recall)

        try:
            llm_action = llm.choose_action(prompt)
        except Exception as api_err:
            print(f"  [Step {step_num}] LLM error: {api_err}")
            ended_early = f"llm_error: {api_err}"
            break

        action_type   = llm_action.get("action_type", "wait")
        value         = llm_action.get("value", "")
        reasoning     = llm_action.get("reasoning", "")
        expected      = llm_action.get("expected_outcome", "")
        potential_bug = llm_action.get("potential_bug", "")
        is_novel      = bool(llm_action.get("is_novel", False))

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
                # Adapters whose type_text is a pure keystroke-into-a-field (browser /
                # real_server: the text is buffered and only committed by a later
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
                pre_reset = current_state
                try:
                    current_state = adapter.reset()
                except Exception:
                    pass
                else:
                    bank_deltas(pre_reset)
                    baseline_state = json.loads(json.dumps(current_state, default=str))
                    episode_resets += 1
                    inv_ctx.clear()
                    reveals.note_reset(current_state)
                continue

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
            # same rule as exploit_hunter's crash path).
            executed_action_id = None
            pre_reset = current_state
            try:
                current_state = adapter.reset()
            except Exception:
                pass
            else:
                bank_deltas(pre_reset)
                baseline_state = json.loads(json.dumps(current_state, default=str))
                episode_resets += 1
                inv_ctx.clear()
                reveals.note_reset(current_state)

        action_counts[f"{action_type}:{value}"] = action_counts.get(f"{action_type}:{value}", 0) + 1

        # Machine-checked invariants (exploit-hunter contract) — run on every executed action.
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
        surprises = _unexpected_delta_fields(delta, f"{expected} {reasoning}")
        if surprises:
            log_entry["unexpected_deltas"] = surprises
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
        # effect (e.g. NEXUS's rngCounter, which advances even on a refused/no-op command by
        # design — NX-OBS-1). Without excluding that field too, EVERY action in such a game
        # always has a "non-empty" delta and this whole detector goes permanently inert for
        # that game. Games declare extra fields to ignore via playtest.ignore_delta_fields
        # in their ugt.config.yaml (matched on the full dotted key or its leaf name).
        _ignore_delta_fields = {"turn_number"} | set(playtest_cfg.get("ignore_delta_fields") or [])
        material_delta = {
            k: v for k, v in delta.items()
            if k not in _ignore_delta_fields and k.rsplit(".", 1)[-1] not in _ignore_delta_fields
        }
        noop_key = f"{action_type}:{value}"
        # Some commands (e.g. NEXUS's `ls`/`analyze`) are legitimately display-only: their real
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
        # (NEXUS: currentServerId). Absent -> context None, i.e. plain per-action keying.
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
            try:
                current_state = adapter.reset()
                bank_deltas(pre_reset)
                baseline_state = json.loads(json.dumps(current_state, default=str))
                episode_resets += 1
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

    # ── Per-run summary: deltas from the post-reset baseline (plus banked segments) ──
    real_actions = [e for e in action_log if e.get("action_type") != "episode_reset"]

    # Surprise metric noise floor: a key that changes on nearly every step (harness step
    # counters, per-action fuel ticks) carries no signal — only count steps whose
    # surprises include a NON-ubiquitous key. Per-step raw records stay in the log.
    key_freq = {}
    for e in real_actions:
        for k in (e.get("state_delta") or {}):
            key_freq[k] = key_freq.get(k, 0) + 1
    ubiquitous = {k for k, n in key_freq.items() if n >= 0.8 * max(1, len(real_actions))}
    unexpected_delta_steps = sum(
        1 for e in real_actions
        if any(k not in ubiquitous for k in (e.get("unexpected_deltas") or {}))
    )

    summary = {
        "actions_taken": len(real_actions),
        "duration_seconds": duration,
        "ended_early": ended_early,
        "episode_resets": episode_resets,
        "bugs_flagged": len(potential_bugs),
        "invariant_violations": len(invariant_violations),
        "unexpected_delta_steps": unexpected_delta_steps,
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
    print(f"[+] Actions taken: {report['total_actions']}")
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
            max_tokens=512,
            tools=[{
                "name": "choose_action",
                "description": "Choose the next game action",
                "input_schema": LLM_ACTION_SCHEMA,
            }],
            tool_choice={"type": "any"},
            messages=[{"role": "user", "content": prompt}],
        )
        tool_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_block is None:
            raise RuntimeError("No tool_use block in Anthropic response")
        return tool_block.input


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
            "options": {"temperature": 0.2, "num_predict": 256},
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
        return _parse_json_action(raw, self.valid_actions)


def _parse_json_action(raw_text, valid_actions=None):
    """Parse LLM JSON response, tolerating markdown fences and minor formatting.

    `valid_actions` (a set of the config's action names) enables salvaging two common
    small-model mistakes instead of burning the step as a wait:
      {"action_type": "<action name>"}          -> action_id with that name
      {"action_type": "wait", "value": "<action name>"} -> action_id with that name
    """
    valid_actions = valid_actions or set()
    text = raw_text.strip()
    if not text:
        return {"action_type": "wait", "value": "", "reasoning": "(empty response)", "expected_outcome": ""}
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
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end])
            except json.JSONDecodeError:
                print(f"  [warn] Unparseable JSON from LLM, skipping step: {text[:100]}")
                return {"action_type": "wait", "value": "", "reasoning": "(parse error)", "expected_outcome": ""}
        else:
            print(f"  [warn] No JSON object in LLM response, skipping step: {text[:100]}")
            return {"action_type": "wait", "value": "", "reasoning": "(no json)", "expected_outcome": ""}

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
    simply gone: on NEXUS 2026-07-22 a 40-step run cycled the same six-step loop over the
    same two servers five times with **zero** consecutive repeats, so `noop_streaks`
    (which counts only CONSECUTIVE no-delta repeats and resets on any productive step)
    never fired, and the recent-actions window had slid past every repeat before the next
    one was chosen. The cumulative counts already existed in `action_counts` for the
    report and were never shown back to the agent.

    IMPORTANT — this block must NOT read as "do not repeat yourself". Repetition is
    correct play in most games: location-scoped recon (NEXUS `ls`/`scan`/`analyze`) SHOULD
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
    output, never in structured state: NEXUS exposes `discoveredServers` as bare IPs, so a
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

    The question this answers (owner-specified, NEXUS RESULTS.md L-017 item 3 / L-019
    "still open" 1): when a game unlocks a new command or opens a new quest line, does
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


def _available_actions_line(playtest_cfg, current_state, fallback):
    """The verb list shown to the agent: ALWAYS the full vocabulary, plus — when the game
    maintains its own live unlock list — an annotation naming what it currently reports as
    unlocked.

    ⚠️ This knob originally REPLACED the vocabulary with the game's live list, on the
    reasoning that the agent should never be advertised a verb the game will refuse. Live
    probing on NEXUS 2026-07-22 showed that is dangerous: `unlockedCommands` there is a
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


def _noop_warning_block(noop_streaks, threshold=2):
    """Render a '## Warnings' section for any action whose last `threshold`+ attempts
    produced no material state change — the SAME counter the contradiction detector
    uses to auto-flag a bug at 3 repeats, surfaced one step earlier so the agent gets
    a chance to notice and change course itself, rather than only being scored on it
    after the fact. Without this, that count exists in memory the whole time but was
    never shown back to the agent — the 5-step 'Recent Actions' window alone is too
    short to reveal a pattern that repeats every 6+ steps (see NEXUS the_breadcrumb
    2026-07-21: 'accept' repeated 11 times, each one scrolled out of view before the
    next attempt, with no signal that it had ever been tried before)."""
    if not noop_streaks:
        return ""
    lines = [
        f"  '{key.split(':', 1)[-1]}' has produced NO material change the last {count} "
        f"time{'s' if count != 1 else ''} you tried it — do NOT just repeat it, try something else"
        for key, count in noop_streaks.items() if count >= threshold
    ]
    if not lines:
        return ""
    return "## Warnings\n" + "\n".join(lines) + "\n\n"


_TRUNCATION_WARNED = set()


def _fit(text, budget, what, tail=False):
    """Apply a prompt char budget, and SAY SO the first time it actually bites.

    LESSONS.md P3 ("truncation is silent starvation"): the budgets are the quietest
    way to blind a pilot — the guide's rules or the terminal's read layer just stop
    existing partway through, the run still reports PLAYTEST MET, and the resulting
    balance number is measuring a player who was never told the rules. Two DDD
    batches (L-009, L-011) were lost to exactly this before the budgets were raised
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


def _redaction_paths(playtest_cfg):
    """Config knob `playtest.redact_state_fields`: dot-separated state paths whose
    values the game's own wire protocol HIDES from the acting player (fog of war)
    but the adapter's normalized state must carry for machine checks — e.g. DDD's
    card-conservation invariant needs the god-view `committedCard` term, while the
    engine's redacted opponent view exposes only `hasCommitted`. These paths are
    dropped ONLY from what the LLM is shown (the state JSON and the recent-action
    delta summaries); logs, invariants and reports keep the full state."""
    return [str(p) for p in (playtest_cfg or {}).get("redact_state_fields") or []]


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
    itself — the cumulative `_action_ledger_block` is what covers longer ones."""
    window = max(1, int(window or 5))
    recent_log = action_log[-window:] if len(action_log) > window else action_log
    return "\n".join(
        f"  Step {e['step']}: {e['action']} → {_redact_delta(e.get('state_delta', {}), redact)}"
        for e in recent_log
    ) or "  (no actions taken yet)"


def _build_prompt(config, strategy_guide, current_state, terminal_text, action_log, noop_streaks=None,
                  ledger=None, recall=None):
    playtest_cfg = config.data.get("playtest", {}) if isinstance(config.data, dict) else {}
    guide_budget = int(playtest_cfg.get("guide_char_budget", 2000))
    terminal_budget = int(playtest_cfg.get("terminal_char_budget", 400))

    redact = _redaction_paths(playtest_cfg)

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
        + f"## Current State\n"
        + _key_values_line(playtest_cfg, current_state)
        + f"```json\n{json.dumps(_redact_state(current_state, redact), indent=2, default=str)}\n```\n\n"
        f"## Recent Actions\n{recent_summary}\n\n"
        + _noop_warning_block(noop_streaks)
        + _action_ledger_block(ledger)
        + _terminal_recall_block(recall, int(playtest_cfg.get('terminal_recall_budget', 0)))
        + f"## Terminal Output\n```\n{_fit(terminal_text, terminal_budget, 'Terminal output', tail=True)}\n```\n\n"
        f"## Strategy Guide\n{_fit(strategy_guide, guide_budget, 'Strategy guide')}\n\n"
        f"Respond JSON only. Use action_type=\"action_id\" and value=<one of the action names above>."
    )


def _build_legal_prompt(config, strategy_guide, current_state, legal_list, action_log, playtest_cfg,
                        noop_streaks=None, ledger=None, recall=None):
    """Prompt for legal_action mode: the adapter's own structured state (serialized
    JSON — the exact shape the game's ladder scripts read) plus its live legal-action
    list. Game-agnostic: each legal action is dumped as its raw JSON, with no
    game-specific interpretation in this module."""
    project = getattr(config, "project_name", None) or "the game"
    playtest_cfg = playtest_cfg or {}
    guide_budget = int(playtest_cfg.get("guide_char_budget", 2000))

    redact = _redaction_paths(playtest_cfg)

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
        + f"## Current State\n"
        + _key_values_line(playtest_cfg, current_state)
        + f"```json\n{json.dumps(_redact_state(current_state, redact), indent=2, default=str)}\n```\n\n"
        f"## LEGAL ACTIONS (respond with action_type=\"legal_action\", value=<the NUMBER>)\n"
        f"{legal_lines}\n\n"
        f"## Recent Actions\n{recent_summary}\n\n"
        + _noop_warning_block(noop_streaks)
        + _action_ledger_block(ledger)
        + f"## Strategy Guide\n{_fit(strategy_guide, guide_budget, 'Strategy guide')}\n\n"
        f"Respond JSON only. action_type=\"legal_action\", value=\"<index 0..{upper}>\"."
    )


def _build_terminal_prompt(config, strategy_guide, current_state, terminal_text, action_log, playtest_cfg,
                           noop_streaks=None, ledger=None, recall=None):
    """Prompt for "text" mode: the LLM drives the game by TYPING a raw command line
    (action_type="type_text"), exactly as a human at the terminal would. The adapter's
    own get_terminal_text output and structured state are shown; the command vocabulary
    is listed from config.action_mappings, but the LLM types the FULL command line
    (verb + any argument). Argument syntax — which files / servers / missions / targets
    to name — lives in the game's own strategy guide, never in this module, so this
    stays game-agnostic (no game-specific strings here)."""
    playtest_cfg = playtest_cfg or {}
    guide_budget = int(playtest_cfg.get("guide_char_budget", 2000))
    terminal_budget = int(playtest_cfg.get("terminal_char_budget", 400))
    project = getattr(config, "project_name", None) or "the game"

    action_mappings = getattr(config, "action_mappings", None) or {}
    command_names = ", ".join(
        (a.get("name", str(k)) if isinstance(a, dict) else str(a))
        for k, a in action_mappings.items()
    ) or "(see the strategy guide)"

    redact = _redaction_paths(playtest_cfg)
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
        + f"## Current State\n"
        + _key_values_line(playtest_cfg, current_state)
        + f"```json\n{json.dumps(_redact_state(current_state, redact), indent=2, default=str)}\n```\n\n"
        f"## Recent Actions\n{recent_summary}\n\n"
        + _noop_warning_block(noop_streaks)
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


def _unexpected_delta_fields(delta, expectation_text):
    """State-change keys whose leaf name the LLM's expectation/reasoning never mentioned.

    Heuristic escalation only: leaf-name substring match, underscores also matched as
    spaces (e.g. delta key 'ship.shield_strength' is 'mentioned' by 'shield strength').
    """
    text = (expectation_text or "").lower()
    surprises = {}
    for key, change in delta.items():
        leaf = key.rsplit(".", 1)[-1].lower()
        if leaf in text or leaf.replace("_", " ") in text:
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

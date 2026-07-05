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
            "enum": ["action_id", "press_key", "type_text", "wait", "diagnose", "end_turn"],
            "description": (
                "action_id: simulation game — value is the action name from the config. "
                "press_key: browser game — value is a single key (e.g. 'T', 'Enter'). "
                "type_text: browser game — value is text to type. "
                "wait: pause for one step (use sparingly). "
                "diagnose: flag that the current state is confusing or broken. "
                "end_turn: signal that the current turn is complete."
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
_VALID_ACTION_TYPES = {"action_id", "press_key", "type_text", "wait", "diagnose", "end_turn"}


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

    project_dir = os.path.dirname(os.path.abspath(config.filepath))
    results_dir = os.path.join(project_dir, "results")
    os.makedirs(results_dir, exist_ok=True)

    playtest_cfg = config.data.get("playtest", {}) if isinstance(config.data, dict) else {}

    print(f"[*] Phase 3 — Playtest: connecting to game ({config.engine_type})...")
    adapter.connect()

    invariant_list = list(invariants(adapter)) if callable(invariants) else list(invariants or [])
    if invariant_list:
        print(f"[*] {len(invariant_list)} invariant check(s) active during play")

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
                playtest_cfg, invariant_list, run_index,
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
        report["game"] = config.project_name
        out = output_path or os.path.join(results_dir, "playtest-report.json")
        with open(out, "w") as f:
            json.dump(report, f, indent=2, default=str)
        _print_run_summary(report, out)
        return report

    aggregate = _aggregate_runs(run_reports)
    summary_report = {
        "game": config.project_name,
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
                         playtest_cfg, invariant_list, run_index):
    """One playtest run: reset, drive up to max_actions LLM decisions, return the run report."""
    terminal_budget = int(playtest_cfg.get("terminal_char_budget", 400))
    summary_paths = [e for e in (playtest_cfg.get("summary_paths") or [])
                     if isinstance(e, dict) and "path" in e]

    # Build action name → ID map
    name_to_id = {}
    for action_id, action_def in config.action_mappings.items():
        name = action_def.get("name", str(action_id)) if isinstance(action_def, dict) else str(action_def)
        name_to_id[name] = int(action_id)

    current_state = adapter.reset()
    baseline_state = json.loads(json.dumps(current_state, default=str))
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
    ended_early = None
    # Shared mutable context for stateful invariants (exploit-hunter semantics:
    # one ctx per episode — cleared whenever the game resets mid-run).
    inv_ctx = {}
    start_time = time.time()

    for step_num in range(1, max_actions + 1):
        terminal_text = adapter.get_terminal_text(terminal_budget)
        prompt = _build_prompt(config, strategy_guide, current_state, terminal_text, action_log)

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

        if potential_bug:
            potential_bugs.append({
                "step": step_num,
                "description": potential_bug,
                "state": current_state,
                "terminal_text": terminal_text,
            })
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
                adapter.type_text(value)
                executed_action_id = -1
                step_info = {"text": value}

            elif action_type == "wait":
                pass

            elif action_type == "diagnose":
                print(f"  [Step {step_num}] Agent is confused — flagging as potential bug")
                potential_bugs.append({
                    "step": step_num,
                    "description": f"Agent confusion: {reasoning}",
                    "state": current_state,
                    "terminal_text": terminal_text,
                })
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
                continue

            elif action_type == "end_turn":
                pass

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
        delta = _compute_delta(before_state, after_state)

        log_entry = {
            "step": step_num,
            "action_type": action_type,
            "action": value,
            "reasoning": reasoning,
            "expected": expected,
            "state_delta": delta,
        }
        if is_novel:
            log_entry["is_novel"] = True
            novel_behaviors.append(log_entry)

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
    summary = {
        "actions_taken": len(real_actions),
        "duration_seconds": duration,
        "ended_early": ended_early,
        "episode_resets": episode_resets,
        "bugs_flagged": len(potential_bugs),
        "invariant_violations": len(invariant_violations),
    }
    for e in summary_paths:
        final = _resolve_path(current_state, e["path"])
        base = _resolve_path(baseline_state, e["path"])
        label = e.get("label", e["path"])
        if isinstance(final, (int, float)) and isinstance(base, (int, float)):
            summary[label] = banked[e["path"]] + (final - base)
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
        return _parse_json_action(raw)


def _parse_json_action(raw_text):
    """Parse LLM JSON response, tolerating markdown fences and minor formatting."""
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

    # Validate required fields; default gracefully
    if "action_type" not in data or data["action_type"] not in _VALID_ACTION_TYPES:
        data["action_type"] = "wait"
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

def _build_prompt(config, strategy_guide, current_state, terminal_text, action_log):
    playtest_cfg = config.data.get("playtest", {}) if isinstance(config.data, dict) else {}
    guide_budget = int(playtest_cfg.get("guide_char_budget", 2000))
    terminal_budget = int(playtest_cfg.get("terminal_char_budget", 400))

    action_lines = []
    for action_id, action_def in config.action_mappings.items():
        name = action_def.get("name", str(action_id)) if isinstance(action_def, dict) else str(action_def)
        action_lines.append(f"  {action_id}: {name}")

    recent_log = action_log[-5:] if len(action_log) > 5 else action_log
    recent_summary = "\n".join(
        f"  Step {e['step']}: {e['action']} → {e.get('state_delta', {})}"
        for e in recent_log
    ) or "  (no actions taken yet)"

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
        f"## Current State\n"
        + _key_values_line(playtest_cfg, current_state)
        + f"```json\n{json.dumps(current_state, indent=2, default=str)}\n```\n\n"
        f"## Recent Actions\n{recent_summary}\n\n"
        f"## Terminal Output\n```\n{terminal_text[-terminal_budget:]}\n```\n\n"
        f"## Strategy Guide\n{strategy_guide[:guide_budget]}\n\n"
        f"Respond JSON only. Use action_type=\"action_id\" and value=<one of the action names above>."
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

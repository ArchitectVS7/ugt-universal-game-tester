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


def playtest_game(config, strategy_guide, max_actions=100, output_path=None, provider="anthropic", model=None):
    """
    Phase 3: LLM-powered playtest.

    config         — UgtConfig instance
    strategy_guide — string content of the strategy guide markdown file
    max_actions    — maximum LLM actions to take
    output_path    — path to write playtest-report.json (default: results/playtest-report.json)
    provider       — "anthropic" or "ollama"
    model          — model name override (None = provider default)

    Returns the playtest report dict.
    """
    sys.stdout.reconfigure(line_buffering=True)

    if provider == "anthropic":
        llm = _AnthropicLLM(model or "claude-opus-4-8")
    elif provider == "ollama":
        llm = _OllamaLLM(model or "gemma4:26b")
    else:
        raise ValueError(f"Unknown LLM provider: '{provider}'. Choose 'anthropic' or 'ollama'.")

    from ugt.adapters.subprocess import SubprocessAdapter
    from ugt.adapters.playwright import PlaywrightAdapter

    if config.engine_type == "browser":
        adapter = PlaywrightAdapter(config)
    elif config.engine_type == "simulation":
        adapter = SubprocessAdapter(config)
    else:
        raise ValueError(f"Unknown engine type: '{config.engine_type}'")

    project_dir = os.path.dirname(os.path.abspath(config.filepath))
    results_dir = os.path.join(project_dir, "results")
    os.makedirs(results_dir, exist_ok=True)

    if output_path is None:
        output_path = os.path.join(results_dir, "playtest-report.json")

    # Build action name → ID map for simulation games
    action_names = {}
    name_to_id = {}
    for action_id, action_def in config.action_mappings.items():
        name = action_def.get("name", str(action_id)) if isinstance(action_def, dict) else str(action_def)
        action_names[int(action_id)] = name
        name_to_id[name] = int(action_id)

    print(f"[*] Phase 3 — Playtest: connecting to game ({config.engine_type})...")
    adapter.connect()
    current_state = adapter.reset()
    print(f"[*] Connected. Starting LLM playtest (provider={provider}, model={llm.model}, max_actions={max_actions})...")

    action_log = []
    potential_bugs = []
    novel_behaviors = []
    start_time = time.time()

    for step_num in range(1, max_actions + 1):
        terminal_text = adapter.get_terminal_text(600)
        prompt = _build_prompt(config, strategy_guide, current_state, terminal_text, action_log)

        try:
            llm_action = llm.choose_action(prompt)
        except Exception as api_err:
            print(f"  [Step {step_num}] LLM error: {api_err}")
            break

        action_type   = llm_action.get("action_type", "wait")
        value         = llm_action.get("value", "")
        reasoning     = llm_action.get("reasoning", "")
        expected      = llm_action.get("expected_outcome", "")
        potential_bug = llm_action.get("potential_bug", "")
        is_novel      = bool(llm_action.get("is_novel", False))

        print(f"  [Step {step_num}] {action_type}({value!r}) — {reasoning[:60]}")

        if potential_bug:
            bug_entry = {
                "step": step_num,
                "description": potential_bug,
                "state": current_state,
                "terminal_text": terminal_text,
            }
            potential_bugs.append(bug_entry)
            print(f"  [!] Potential bug flagged: {potential_bug[:80]}")

        before_state = json.loads(json.dumps(current_state, default=str))
        terminated = truncated = False

        try:
            if action_type == "action_id":
                action_id = name_to_id.get(value)
                if action_id is None:
                    print(f"  [Step {step_num}] Unknown action name '{value}' — skipping")
                    continue
                current_state, terminated, truncated, _ = adapter.step(action_id)

            elif action_type == "press_key":
                adapter.press_key(value)
                try:
                    current_state, terminated, truncated, _ = adapter.step(0)
                except Exception:
                    pass

            elif action_type == "type_text":
                adapter.type_text(value)

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
                try:
                    current_state = adapter.reset()
                except Exception:
                    pass
                continue

            elif action_type == "end_turn":
                pass

        except Exception as exec_err:
            print(f"  [Step {step_num}] Execution error: {exec_err}")
            try:
                current_state = adapter.reset()
            except Exception:
                pass

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
            try:
                current_state = adapter.reset()
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
                break

    adapter.close()
    duration = round(time.time() - start_time, 1)

    report = {
        "game": config.project_name,
        "provider": provider,
        "model": llm.model,
        "total_actions": len(action_log),
        "duration_seconds": duration,
        "potential_bugs": potential_bugs,
        "novel_behaviors": novel_behaviors,
        "action_log": action_log,
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\n[+] Playtest complete in {duration}s")
    print(f"[+] Actions taken: {len(action_log)} / {max_actions}")
    print(f"[+] Potential bugs flagged: {len(potential_bugs)}")
    print(f"[+] Novel behaviors observed: {len(novel_behaviors)}")
    if potential_bugs:
        print("[!] Potential bugs:")
        for b in potential_bugs:
            print(f"    Step {b['step']}: {b['description'][:80]}")
    print(f"[+] Report: {output_path}")

    return report


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
        + (
            f"⚡ KEY VALUES: credits={current_state.get('character',{}).get('credits',0)}, "
            f"cargo_pods={current_state.get('character',{}).get('cargo_pods',0)}, "
            f"destination={current_state.get('character',{}).get('destination',0)}, "
            f"trip_count={current_state.get('character',{}).get('trip_count',0)}/2 (2=blocked until end_turn), "
            f"fuel={current_state.get('ship',{}).get('fuel',0)}\n\n"
            if isinstance(current_state, dict) else ""
        )
        + f"```json\n{json.dumps(current_state, indent=2, default=str)}\n```\n\n"
        f"## Recent Actions\n{recent_summary}\n\n"
        f"## Terminal Output\n```\n{terminal_text[-400:]}\n```\n\n"
        f"## Strategy Guide\n{strategy_guide[:2000]}\n\n"
        f"Respond JSON only. Use action_type=\"action_id\" and value=<one of the action names above>."
    )


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

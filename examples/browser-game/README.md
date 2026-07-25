# Example: `browser-game` — the `browser` (Playwright) integration

**BrowserExampleGame (Credit Clicker)** is the same little game as
`../mock-game`, but it runs as a **real web page** and is driven through UGT's
**`browser` engine type**: a headless Chromium instance calls three hook
functions the page exposes on `window`. It shows that a UGT integration doesn't
care whether a game is a subprocess or a browser — the config and feature map are
the same; only the transport differs.

## Files

| File | Role |
|---|---|
| `index.html` | The game + the three UGT hooks: `__GET_STATE__`, `__SEND_ACTION__`, `__RESET_GAME__`. Terminal flags (`victory`/`defeat`) are exposed so the tester can see the outcome. |
| `serve.py` | Starts a local HTTP server on `http://localhost:8080` (cross-platform). |
| `ugt.config.yaml` | `engine.type: browser`; same observation/action space as mock-game. |
| `feature-map.yaml` | The correctness assertions `ugt verify` checks — identical to mock-game's (a feature map is transport-agnostic). |
| `strategy-guide.md` | The tier-3 LLM playtest briefing. |

## Run it

```bash
# One-time: install the browser driver
pip install playwright && playwright install chromium

# Terminal 1 — serve the game
python3 serve.py                 # http://localhost:8080

# Terminal 2 — drive it
ugt smoke-test --config ugt.config.yaml   # 5 random steps through the browser
ugt verify --config ugt.config.yaml --feature-map feature-map.yaml
```

## How the hooks work

UGT injects nothing into your game logic — the page opts in by defining three
functions on `window` (see `index.html`):

- `__GET_STATE__()` → the current state as a plain JSON object
- `__SEND_ACTION__(actionId)` → applies an action, returns `{state, terminated, truncated, info}`
- `__RESET_GAME__()` → soft reset (avoids a ~15s full page reload per episode)

The adapter is transport-only: it reads state and dispatches actions through these
hooks and never re-implements a rule — the same discipline as every UGT adapter.

## Notes

- **Expose terminal state.** A black-box tester can't infer a win/loss; the game
  must surface it. This example puts `victory`/`defeat` in `__GET_STATE__` so the
  `game.win_condition` feature can assert on it (`LESSONS.md` M8).
- For the full trial-ladder methodology (spike → R3, exploit-hunter, determinism),
  see `../harness-game`; for the subprocess equivalent of this game, `../mock-game`.

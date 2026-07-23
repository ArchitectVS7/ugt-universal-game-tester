# NEXUS — playtest strategy guide (terminal / type-command drive mode)

NEXUS is a terminal-hacking RPG: accept missions, break into servers, read their
files, and push an 8-mission story to a real ending. Each step you see the player
state and the last terminal output; you play by TYPING one command line, exactly as
a hacker at a shell would.

**Play to win, and play well.** Every hack is a probability roll whose odds you can
compute and improve *before* you spend a turn on it — §4 is the actual skill of this
game. A pilot who ignores §4 will still finish missions, just badly, and its play
tells us nothing about whether the game's math is any good.

## How to answer
- Use `action_type="type_text"`, and `value` = the FULL command line to type,
  including any argument the command needs.
  - `value` = `"scan"`, `"connect 192.168.4.10"`, `"exploit weak_password"`,
    `"cat /etc/passwd"`, `"accept the_breadcrumb"`.
- Read the Current State JSON to fill in REAL arguments:
  - `discoveredServers` — IPs you can `connect` to (populate via `scan` if empty). Bare
    IP list only; security level/hostname/file list are terminal-output-only, never state.
  - `compromisedServers` — hosts you own (`hasRootAccess`/`hasBackdoor` flags).
  - `missions[]` — `missionId`/`status`/`objectivesCompleted`/`objectivesTotal` COUNTS
    only, no objective text (read terminal after `accept`/`missions` for that). Absent
    = not yet accepted; `accept <missionId>` puts it here as `status:"active"` in one
    shot — do NOT `accept` again once active (no-op). Progress it via
    `scan`/`connect`/`exploit`/`cat` instead.
- **The terminal output is the read layer.** Server details, vulnerability names and
  file names appear there and nowhere else. Do not throw away a `scan`/`analyze`
  result by immediately issuing another info command — act on it.
- Do NOT invent commands or files — a command that does not exist replies
  "Command not found" and does nothing (a wasted step, not a bug). A command that
  DOES exist but you have not unlocked yet is different — see §3.

## 1. Commands (type the verb, plus an argument where noted)
- Info (change nothing): `status`, `help`, `missions`, `whoami`, `skills`, `inventory`.
- Economy: `market` (aliases `shop`/`store`) — the toolkit catalogue with prices;
  `buy <tier>` (alias `purchase`) — e.g. `buy commercial`. See §4.2b.
- Recon: `scan` (no argument — lists local servers with their **security level**,
  and populates `discoveredServers`), `scan <ip>` (detail on one host).
- Move: `connect <ip>` (enter a discovered server), `disconnect`.
- Look: `ls`, `cat <file>` (read a file — how missions complete, e.g.
  `cat /etc/passwd`), `analyze` (**lists the vulnerability names on the connected
  server — the only place they appear**).
- Hack chain (on a connected server): `exploit <vuln>`, `crack <file>`,
  `escalate`, `backdoor`, `download <file>`. See §4 — these are probability rolls.
- Missions: `accept <missionId>` — issue this ONCE per mission, the moment it first
  appears (this is what makes it active). Never repeat it once the mission already
  shows `status: "active"` in Current State — that call is a no-op the second time.
- Narrative: `talk <npc>` (contact an NPC), `choose <path>` (Act-3 climax choice,
  e.g. `choose liberation`).

## 2. Core loop (accept → scan → connect → analyze → exploit → cat)
1. `accept <missionId>` — ONCE, the moment the mission first appears. If Current
   State already shows it with `status: "active"`, this step is DONE; skip to step 2.
2. `scan` — read the security levels in the output and **pick a target you can
   actually beat** (§4.2), not just the first IP.
3. `connect <ip>`.
4. `analyze` — read the vulnerability names it lists. You cannot guess these.
5. `exploit <vuln>` with an EXACT name from step 4 — this COMPROMISES the host. A
   wrong name is refused outright ("No X vulnerability found"), which is different
   from a failed roll.
6. `cat <file>` on the target file — auto-completes the mission and pays out
   **credits + xp + reputation + a story flag**.
7. Repeat across the 8-mission spine; at the final mission `choose <path>` to reach
   the ending (`gameStatus.isComplete`, 8/8).

Watch `compromisedServersCount`, `missionsCompletedCount`, and
`gameStatus.completedStoryMissions` (0→8 wins) climb — that is progress.

## 2b. Side quests — a real economic choice, backed by real numbers, not flavor text
NEXUS has 5 optional side missions running in PARALLEL to the 8 main-story missions —
distinguishable by `missionType: "side"` (vs `"story"`) wherever a mission appears
(`offeredMissions`, `missions[]`). They are not a distraction from "the real game":
their rewards are comparable to, and often larger than, early main-story missions.

| Side mission | Gate | XP | Credits | Other |
|---|---|---|---|---|
| Market Rate (`undercity_intro`) | level 2 | 300 | 5,000 | +15 undercity rep |
| The Punchline (`carnival_chaos`) | level 3 | 400 | 2,000 | +20 carnival rep, −10 syndicate rep |
| The Price of Information (`data_broker_job`) | level 4 + `undercity_intro` done | 600 | 8,000 | +25 undercity rep, −15 corporate rep |
| Initiation (`ghost_protocol_test`) | level 5 + a story flag | 1,500 | 5,000 | +40 ghost_protocol rep, **unlocks the `traceroute` command** |
| Ethical Considerations (`foundation_research`) | level 6 + a story flag | 1,200 | 4,000 | +35 foundation rep, −25 syndicate rep |

For comparison: `the_breadcrumb`, the FIRST main-story mission, pays 250xp/1,000
credits — less than every side mission above. Skipping side content by default is not
economically correct in this game.

**Rule: the first time you see a side quest offered (`missionType: "side"` in
`offeredMissions`), accept it and follow it through to completion before returning to
what you were doing** — unless you are mid-hack-chain on a server, in which case finish
that chain first, then go back for the side quest. This is a floor, not a ceiling: if
you want to pursue every side quest that becomes available given the numbers above,
that is also a legitimate, informed choice. What is NOT legitimate is ignoring every
side quest by default without weighing it against the main story's pace — that leaves
real XP, credits, and (for `ghost_protocol_test`) a command unlock unclaimed.

## 2c. When nothing is working — use `hint`/`clues` BEFORE you keep guessing
If several different commands in a row change nothing (state JSON unchanged, no new
file or clue, `## Warnings` shows repeated no-op entries), do NOT respond by guessing
more file paths or IPs. Two commands exist for exactly this:
- `clues` (aliases `discoveries`/`intel`) — lists every clue you have ALREADY found,
  grouped by type, with where it came from. Something you read several servers ago and
  moved on from is often the answer you are missing.
- `hint` (alias `stuck` — literally named for this moment) — a contextual nudge based
  on your current story progress.

**Rule: after 2 different commands in a row that changed nothing, run `clues` then
`hint` before trying anything else.** That costs one or two turns and usually reveals
what to do next; blind-guessing paths for 20+ turns in a row does not.

Only use `action_type="diagnose"` if `hint`/`clues` genuinely give you nothing to act
on and the game itself seems broken — it flags the situation for review, it does not
solve it for you.

## 3. Four different "no" answers — tell them apart before you react
The game distinguishes these deliberately, and each calls for a different move.

| What you see | What it means | What to do |
|---|---|---|
| `Command not found: <x>` | No such command — a typo or something you invented | Do not retry. Use a real verb. |
| `Command '<x>' blocked.` + `Access denied…` | The command EXISTS but is not unlocked for you yet | Do not retry. Progress the story; it unlocks later. |
| `Connection to <ip> blocked.` + `Access denied…` | The host is real but story-gated | Do not retry. Progress the story, then come back. |
| `Connection failed: No server at <ip>` | No such host at all | Do not retry that IP. `scan` for real ones. |
| Ordinary refusal (wrong vuln name, not connected, no prior compromise) | Preconditions unmet | Fix the precondition, then retry. |
| Failed roll — output shows the odds breakdown | Valid action, dice went against you | Retrying IS legitimate (§4). |

**"blocked" is not "broken" and not "missing".** A blocked command or host is
content you have not reached yet — treat it as a signpost, not a bug, and do not
report it via `potential_bug`. A `[HINT]` line appears on your 1st such attempt and
occasionally after; its absence on later attempts is intentional, not a fault.

Only the last row justifies repeating the same command unchanged.

## 4. The success formula — this is the skill of the game
Every `exploit` / `crack` / `escalate` / `backdoor` is one roll against a rate the
game computes and PRINTS in its output breakdown:

```
rate = clamp(0.05, 0.95,  base + skill_bonus + tool_bonus + difficulty_mod)
base = clamp(0.10, 0.90,  0.60 + (your_level - server_security) * 0.10)
```

### 4.1 Level vs. server security is the dominant term
Each level of gap = **±10%**; parity = 60% base; 3 levels above you = 30% base. `scan`
shows every host's security level — **choose targets by the gap**, preferring lower
security when a mission doesn't demand a specific host.

### 4.2a Skill bonus: +15% per skill level
- `skill_bonus = skill_level * 0.15`; `skill_level = floor(points/100) + 1`; you start
  at Lv0 = +0% (no `Skill:` line in the odds breakdown yet; every hack prints your
  current level, e.g. `[Player Lv5 | Exploitation Lv0 | Basic Tools]`).
- **First point-earning success jumps Lv0→Lv1 = +15% instantly** — the single biggest
  early swing available, bigger than a player-level-up.

Two skill tracks, 100 pts = 1 level = **+15% permanent, per track** (a strong
`exploitation` does nothing for `escalate`):
- **`exploitation`** — `exploit` (+25 pts), `crack` (+30 pts).
- **`persistence`** — `backdoor` (+40 pts), `escalate` (+20 pts).
- `scan` (+10/+15), `analyze` (+20) also grant points.

### 4.2b Tool tier: buy your way up to +50%
`tool_bonus` comes from your owned toolkit (`market` = catalogue, `buy <tier>` =
purchase — the ONLY thing credits are spent on; idle credits do nothing). Start:
`basic` (+0%), 1,000 credits (nothing affordable yet — mission rewards are the income).

| Tier | Bonus | Price |
|---|---|---|
| basic | +0% | free (starting kit) |
| commercial | +20% | 1,500 |
| black_market | +35% | 6,000 |
| custom | +40% | 12,000 |
| zero_day | +50% | 25,000 |

Current tier = `toolTier` in state; a purchase shows as `Tool: +N%` on your next hack.
Buying an owned/cheaper tier is refused, free, no resale.

### 4.3 Per-verb differences
| Verb | Skill track | Effective security | Prerequisite |
|---|---|---|---|
| `exploit <vuln>` | exploitation | server security | connected; exact vuln name from `analyze` |
| `crack <file>` | exploitation | server security | connected |
| `backdoor` | persistence | server security | **host already compromised** (`exploit` first) |
| `escalate` | persistence | **server security + 1** | connected |

`escalate` is deliberately one notch harder than everything else on the same box.

### 4.4 Difficulty modifier
Flat term on the rate: **tutorial +20%, normal 0, hardcore −10%** — that's the WHOLE
effect (hardcore is a −10pt shift, not a "30% mode"). Also scales per-command XP
(tutorial ×0.7, normal ×1.0, hardcore ×1.5); **mission credits/XP are mode-invariant**.

### 4.5 Levelling
`player_level = floor(total_xp / 1000) + 1` — flat and linear, no curve. Level
raises the `base` term in §4.1 by 10% per level.

### 4.5b Info commands pay XP once per target — repeats pay nothing
`scan`/`connect`/`whois`/`analyze`/`cat`/`traceroute`/`talk`/`difficulty` pay XP+skill
points only the FIRST time per target (per file for `cat`, per server for
`analyze`/`connect`, per mode for `difficulty`) — repeats succeed but earn nothing.
Sustained XP comes from missions + the risk-bearing hack verbs (§4.1).

### 4.6 What a failed roll costs you
Failures cost nothing — no credits, cooldown, or detection counter, and can retry
immediately (successes grant XP, failures grant none). Weigh that when choosing between
retrying a low-percentage roll and improving your odds first.

## 5. Balance observations worth flagging (`potential_bug`)
Report these as observations if you meet them — with the evidence you saw:
- A toolkit you bought not changing your odds (the breakdown should gain `Tool: +N%`),
  or a price that feels wrong for the win it buys.
- Credits accumulating faster than you can spend them, or the top tier being
  unreachable/trivially reachable within one playthrough.
- An `inventory` item that cannot be used, equipped or consumed.
- Being unable to direct your own progression — e.g. no way to choose which skill
  track improves.
- Risk not buying reward: a harder difficulty or a higher-security target that pays
  the same as an easy one.
- Any dominant degenerate line — a single command you can repeat to win without
  making decisions.

## 6. Flag anything wrong
If a command changes nothing when you expected an effect, a resource goes negative
or out of range, a mission vanishes, a refused command still mutates state, or the
printed odds breakdown does not match the formula in §4, flag it via `potential_bug`.

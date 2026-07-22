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
  - `discoveredServers` — IP addresses you can `connect` to (populate it with `scan`
    first if empty). It is a bare list of IPs; a server's security level, hostname
    and file list exist ONLY in terminal output, never in the state JSON.
  - `compromisedServers` — hosts you already own (with `hasRootAccess`/`hasBackdoor`).
  - `missions[]` — each has a `missionId`, a `status`, and `objectivesCompleted` /
    `objectivesTotal` **counts only** — the objective *text* is not in state, so read
    the terminal after `accept`/`missions` to learn what a mission actually wants.
    A mission starts out NOT in this list at all; `accept <missionId>` is what PUTS
    it here with `status: "active"` in one shot. Once you see a mission with
    `status: "active"`, it is ALREADY accepted — do NOT `accept` it again (that call
    does nothing the second time). Move on to `scan`/`connect`/`exploit`/`cat` to
    make its `objectivesCompleted` count go up instead.
- **The terminal output is the read layer.** Server details, vulnerability names and
  file names appear there and nowhere else. Do not throw away a `scan`/`analyze`
  result by immediately issuing another info command — act on it.
- Do NOT invent commands or files — an unknown command replies "Command not found"
  and does nothing (that is a wasted step, not a bug).

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

## 3. Refusal vs. failed roll — they are different
- **Refusal**: the command was invalid here (wrong vuln name, not connected, no
  prior compromise). The output says so. Retrying identically is pointless.
- **Failed roll**: the command was valid and the dice went against you. The output
  shows the odds breakdown. Retrying is legitimate.
Read the output before deciding which one you just hit.

## 4. The success formula — this is the skill of the game
Every `exploit` / `crack` / `escalate` / `backdoor` is one roll against a rate the
game computes and PRINTS in its output breakdown:

```
rate = clamp(0.05, 0.95,  base + skill_bonus + tool_bonus + difficulty_mod)
base = clamp(0.10, 0.90,  0.60 + (your_level - server_security) * 0.10)
```

### 4.1 Level vs. server security is the dominant term
Each level of gap is worth **±10%**. At parity, base = 60%. Against a server 3
levels above you, base = 30%. `scan` tells you every host's security level — so
**choose targets by the gap**, and prefer a lower-security host when a mission does
not demand a specific one.

### 4.2a Skill bonus: +15% per skill level
`skill_bonus = skill_level * 0.15`. **You start at skill level 0, so +0%** — a brand-new
player gets no skill bonus at all, and the odds breakdown shows no `Skill:` line until
you have earned some. Every hack prints your current level, e.g.
`[Player Lv5 | Exploitation Lv0 | Basic Tools]`.

Once you have any points at all, level is `floor(points / 100) + 1`, so your **first**
successful point-earning action jumps you straight from Lv0 to Lv1 = **+15%**. That
first success is the single most valuable percentage swing available to you early —
worth more than a level of player XP.

Two separate skill tracks, and each verb trains only one of them:
- **`exploitation`** — trained by `exploit` (+25 pts) and `crack` (+30 pts).
- **`persistence`** — trained by `backdoor` (+40 pts) and `escalate` (+20 pts).
- `scan` (+10/+15) and `analyze` (+20) also grant points.

100 points = one skill level = a permanent +15% on every roll in that track. Both
tracks matter: a strong `exploitation` does nothing for `escalate`.

### 4.2b Tool tier: buy your way up to +50%
`tool_bonus` comes from the toolkit you own, and you start on the free `basic` (+0%).
Run `market` to see the catalogue and `buy <tier>` to purchase — this is the ONLY
thing credits are spent on, so credits you are sitting on are doing nothing.

| Tier | Bonus | Price |
|---|---|---|
| basic | +0% | free (starting kit) |
| commercial | +20% | 1,500 |
| black_market | +35% | 6,000 |
| custom | +40% | 12,000 |
| zero_day | +50% | 25,000 |

You start with 1,000 credits, so nothing is affordable immediately — mission rewards
are the income. Your current toolkit is `toolTier` in Current State, and a purchase
shows up in the odds breakdown as a `Tool: +N%` line on your next hack. Buying a tier
you own, or a cheaper one than you own, is refused and costs nothing. There is no
resale.

### 4.3 Per-verb differences
| Verb | Skill track | Effective security | Prerequisite |
|---|---|---|---|
| `exploit <vuln>` | exploitation | server security | connected; exact vuln name from `analyze` |
| `crack <file>` | exploitation | server security | connected |
| `backdoor` | persistence | server security | **host already compromised** (`exploit` first) |
| `escalate` | persistence | **server security + 1** | connected |

`escalate` is deliberately one notch harder than everything else on the same box.

### 4.4 Difficulty modifier
Applied as a flat term on the rate: **tutorial +20%, normal 0, hardcore −10%.**
That is the *whole* effect on odds — hardcore is not a "30% chance" mode, it is a
−10 point shift. Difficulty also scales per-command XP (tutorial ×0.7, normal ×1.0,
hardcore ×1.5), but **mission-reward credits and XP are mode-invariant**.

### 4.5 Levelling
`player_level = floor(total_xp / 1000) + 1` — flat and linear, no curve. Level
raises the `base` term in §4.1 by 10% per level.

### 4.6 What a failed roll costs you
Nothing is deducted on a failure — no credits, no cooldown, no trace or detection
counter, and the attempt can be repeated immediately. Successes grant XP; failures
grant none. Take that into account when deciding between retrying a low-percentage
roll and going to improve your odds first.

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

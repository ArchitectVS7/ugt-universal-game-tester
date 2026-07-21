# NEXUS — playtest strategy guide (terminal / type-command drive mode)

NEXUS is a terminal-hacking RPG: accept missions, break into servers, read their
files, and push an 8-mission story to a real ending. Each step you see the player
state and the last terminal output; you play by TYPING one command line, exactly as
a hacker at a shell would.

## How to answer
- Use `action_type="type_text"`, and `value` = the FULL command line to type,
  including any argument the command needs.
  - `value` = `"scan"`, `"connect 192.168.4.10"`, `"exploit weak_password"`,
    `"cat /etc/passwd"`, `"accept the_breadcrumb"`.
- Read the Current State JSON to fill in REAL arguments:
  - `discoveredServers` — IP addresses you can `connect` to (populate it with `scan`
    first if empty).
  - `compromisedServers` — hosts you already own.
  - `missions[]` — each has a `missionId` and a `status`; `accept` the one whose
    status is `active`.
- Do NOT invent commands or files — an unknown command replies "Command not found"
  and does nothing (that is a wasted step, not a bug).

## Commands (type the verb, plus an argument where noted)
- Info (change nothing — do NOT repeat; 3 no-op repeats get flagged): `status`,
  `help`, `missions`, `whoami`.
- Recon: `scan` (no argument — populates `discoveredServers`).
- Move: `connect <ip>` (enter a discovered server), `disconnect`.
- Look: `ls`, `cat <file>` (read a file — how missions complete, e.g.
  `cat /etc/passwd`), `analyze`.
- Hack chain (on a connected server): `exploit <vuln>` (e.g.
  `exploit weak_password` — seeded roll → compromise host), `crack <file>` (guess a
  password), `escalate`, `backdoor`, `download <file>`.
- Missions: `accept <missionId>` (take the active mission so its rewards can pay out).
- Narrative: `talk <npc>` (contact an NPC), `choose <path>` (Act-3 climax choice,
  e.g. `choose liberation`).

## Core loop (accept → scan → connect → exploit → cat)
1. `accept <missionId>` for the active mission — rewards only pay out once accepted.
2. `scan`, then `connect <ip>` to a discovered target server.
3. `exploit <vuln>` to COMPROMISE the host. If it refuses, RETRY — the roll is seeded
   and re-rolls (hardcore fails ~70%, so expect several retries).
4. `cat <file>` on the target file — this auto-completes the mission and pays out
   **credits + xp + reputation + a story flag**.
5. Repeat across the 8-mission spine; at the final mission `choose <path>` to reach
   the ending (`gameStatus.isComplete`, 8/8).

Watch `compromisedServersCount`, `missionsCompletedCount`, and
`gameStatus.completedStoryMissions` (0→8 wins) climb — that is progress. Prefer
progress commands over repeating info verbs so state actually moves.

## Three difficulty modes (a balance question to probe)
- **tutorial** — easy: high hack odds, per-command xp ×0.7.
- **normal** — baseline: per-command xp ×1.0 (this run's default).
- **hardcore** — ~30% base hack odds, so `exploit`/`crack` often refuse and must be
  retried; per-command xp ×1.5.

Mode scales only PER-COMMAND xp. Mission-reward credits and xp are
**mode-invariant** (+1000 / +250 payouts identical in all three modes) — if you
notice hardcore's extra risk buys no extra mission reward, that is a real balance
observation to flag via `potential_bug`.

## Flag anything wrong
If a command changes nothing when you expected an effect, a resource goes negative
or out of range, a mission vanishes, or a refused command still mutates state, flag
it via `potential_bug`.

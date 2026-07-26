/**
 * Balance sweep — measure outcome distribution straight off the engine.
 *
 *   node tools/balance_sweep.mjs [seedCount]
 *
 * Not a test and not part of the gate. This is the measuring instrument for a
 * retune: it plays the same battle many times, with several player strategies,
 * against the real AI, and reports how the game actually ENDS.
 *
 * It talks to `src/engine.js` directly rather than through the browser, because
 * a retune means running this dozens of times and a headless Chromium round-trip
 * per round would make that unbearably slow. The UGT ladder is what proves the
 * shipped build behaves the same way; this is for choosing the numbers.
 */
import {
  ALLOCATIONS, MAX_ROUNDS, STARTING_FS, HIT_THRESHOLD, POOL_SIZE, DUG_IN_THRESHOLD,
  DEFENSE_BLOCK, applyAction, createInitialState, resolveRound,
} from '../src/engine.js'

const SEEDS = Number(process.argv[2] ?? 40)

/** Player strategies worth distinguishing. The AI always plays its own policy. */
const STRATEGIES = {
  'all-attack': () => 0,
  'attack-lean': () => 1,
  balanced: () => 3,
  adaptive: (s) => (s.player.force_strength <= DUG_IN_THRESHOLD ? 5 : 0),
}

function playOne(seed, pick) {
  let s = createInitialState(String(seed))
  while (!s.battle_over) s = applyAction(s, pick(s))
  return s
}

function summarise(name, results) {
  const n = results.length
  const wins = results.filter((r) => r.winner === 'player').length
  const losses = results.filter((r) => r.winner === 'enemy').length
  const draws = results.filter((r) => r.winner === 'draw').length
  const decisive = wins + losses
  const avgRound = (results.reduce((a, r) => a + r.round_number, 0) / n).toFixed(1)
  const avgMargin = (
    results.reduce((a, r) => a + Math.abs(r.player.force_strength - r.enemy.force_strength), 0) / n
  ).toFixed(1)
  const closest = Math.min(...results.map((r) => Math.min(r.player.force_strength, r.enemy.force_strength)))
  return { name, n, wins, losses, draws, decisive, pct: Math.round((100 * decisive) / n), avgRound, avgMargin, closest }
}

console.log(
  `constants: STARTING_FS=${STARTING_FS} HIT_THRESHOLD=${HIT_THRESHOLD} ` +
  `POOL_SIZE=${POOL_SIZE} DUG_IN=${DUG_IN_THRESHOLD} MAX_ROUNDS=${MAX_ROUNDS} ` +
  `DEFENSE_BLOCK=${DEFENSE_BLOCK}\n`,
)
console.log(
  'strategy      n   decisive   W    L    D   avg_round  avg_margin  closest_call',
)
const rows = []
for (const [name, pick] of Object.entries(STRATEGIES)) {
  const results = []
  for (let seed = 0; seed < SEEDS; seed += 1) results.push(playOne(seed, pick))
  const r = summarise(name, results)
  rows.push(r)
  console.log(
    `${r.name.padEnd(13)}${String(r.n).padStart(3)}   ` +
    `${String(r.pct + '%').padStart(5)}    ${String(r.wins).padStart(3)}  ` +
    `${String(r.losses).padStart(3)}  ${String(r.draws).padStart(3)}   ` +
    `${r.avgRound.padStart(7)}   ${r.avgMargin.padStart(8)}   ${String(r.closest).padStart(8)}`,
  )
}
const overall = Math.round(
  (100 * rows.reduce((a, r) => a + r.decisive, 0)) / rows.reduce((a, r) => a + r.n, 0),
)
console.log(`\noverall decisive rate: ${overall}%   (draws: ${100 - overall}%)`)

/* ---------------------------------------------------------------------------
 * DEPTH. Everything above is win rate, and win rate CANNOT tell a balanced game
 * from a flat one — both read ~50%. A candidate rule change once passed the
 * table above with every strategy at 42-50% while its full strategy grid was a
 * wall of 0.50: it had removed the dominant strategy by removing the decision.
 *
 * So this section takes the AI out of the loop entirely and plays all 7x7 fixed
 * allocations against each other. What it reports:
 *
 *   best response per column  if it reads 0,0,0,0,0,0,0 the game has ONE answer
 *   regret of all-attack      what the naive line costs vs a best response;
 *                             ~0 means there is no decision worth making
 *   dead allocations          choices that beat nothing, at any opponent, ever
 *
 * See LESSONS.md §D6. Sample size matters more here than above — at 200 seeds
 * these numbers reverse (§D7), so the grid gets its own larger count.
 * ------------------------------------------------------------------------- */
const GRID_SEEDS = Number(process.argv[3] ?? Math.max(2000, SEEDS))
const P = [0, 1, 2, 3, 4, 5, 6]

function duel(i, j, seeds) {
  let w = 0, d = 0
  for (let seed = 0; seed < seeds; seed += 1) {
    let s = createInitialState(String(seed))
    while (!s.battle_over) s = resolveRound(s, i, j)
    if (s.winner === 'player') w += 1
    else if (s.winner === 'draw') d += 1
  }
  return (w + 0.5 * d) / seeds // draws worth half
}

console.log(`\nDEPTH — 7x7 fixed-allocation grid, ${GRID_SEEDS} seeds/cell (AI not involved)\n`)
const M = P.map((i) => P.map((j) => duel(i, j, GRID_SEEDS)))
console.log('        ' + P.map((j) => `${ALLOCATIONS[j].attack}a${ALLOCATIONS[j].defense}d`.padStart(7)).join(''))
M.forEach((row, i) => {
  console.log(
    `  ${ALLOCATIONS[i].attack}a${ALLOCATIONS[i].defense}d ` +
    row.map((v) => v.toFixed(2).padStart(7)).join(''),
  )
})
const br = P.map((j) => P.reduce((b, i) => (M[i][j] > M[b][j] ? i : b), 0))
const regret0 = P.reduce((a, j) => a + (M[br[j]][j] - M[0][j]), 0) / P.length
const dead = P.filter((i) => P.every((j) => M[i][j] <= 0.5))
console.log(`\n  best response per enemy column : [${br.join(', ')}]`)
console.log(`  regret of all-attack           : ${regret0.toFixed(4)}` +
            `${regret0 < 0.02 ? '   <-- WARNING: no real decision' : ''}`)
console.log(`  dead allocations (beat nobody) : ${dead.length ? dead.join(', ') : 'none'}`)

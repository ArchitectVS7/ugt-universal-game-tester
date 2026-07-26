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
  MAX_ROUNDS, STARTING_FS, HIT_THRESHOLD, POOL_SIZE, DUG_IN_THRESHOLD,
  applyAction, createInitialState,
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
  `POOL_SIZE=${POOL_SIZE} DUG_IN=${DUG_IN_THRESHOLD} MAX_ROUNDS=${MAX_ROUNDS}\n`,
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

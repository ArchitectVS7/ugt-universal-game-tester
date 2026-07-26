/**
 * Paired baseline — what a fixed policy achieves on each seed the LLM will play.
 *
 *   node tools/paired_baseline.mjs [seed ...]        # defaults to the config's 8
 *   node tools/paired_baseline.mjs --json            # machine-readable
 *
 * Not a test and not part of the gate. This is the SCORING INSTRUMENT for the
 * LLM playtest tier, and it exists because of one measurement: across 200 seeds,
 * the final force-strength margin of a fixed policy has sd 3.53, but its margin
 * MINUS that seed's own mean-across-policies has sd 2.16. Removing the seed's
 * difficulty is worth 2.7x the battles — which is what turns a budget of 8
 * battles from noise into a measurement.
 *
 * Why not just report the LLM's win rate: at 8 battles a win rate carries a 95%
 * CI of +/-34 points, so it cannot distinguish a 40% pilot from a 75% one, and
 * 31 of 200 seeds cannot be won by ANY policy — so a small-n win rate is mostly
 * reporting which seeds you happened to draw. Paired margin at n=8 is +/-1.49
 * against a mean policy spread of 7.6.
 *
 * Like `balance_sweep.mjs` it talks to `src/engine.js` directly. That is sound
 * here for the same reason: the UGT ladder proves the shipped browser build
 * behaves identically (R3 replays it byte-for-byte), and this has to run every
 * time a batch is scored.
 */
import { DUG_IN_THRESHOLD, applyAction, createInitialState } from '../src/engine.js'

/**
 * The reference policies. These are the "average sensible line" the pilot is
 * scored against — deliberately a SPREAD of postures rather than the single best
 * one, because the question is "does the pilot play well", not "did it find the
 * one optimum". `all-defense` is included even though it wins nothing: it is the
 * floor, and dropping it would quietly inflate every paired score.
 */
export const POLICIES = {
  'all-attack': () => 0,
  'attack-lean': () => 1,
  balanced: () => 3,
  'def-lean': () => 4,
  'all-defense': () => 6,
  adaptive: (s) => (s.player.force_strength <= DUG_IN_THRESHOLD ? 5 : 0),
  'lead-hold': (s) => (s.player.force_strength > s.enemy.force_strength ? 4 : 1),
}

/** The seed set in `integration/ugt.config.yaml`. Kept in sync by hand — the
 *  Python side asserts the two agree, so drift fails a run rather than silently
 *  scoring against the wrong baseline. */
export const DEFAULT_SEEDS = [
  'dice-s01', 'dice-s02', 'dice-s03', 'dice-s04',
  'dice-s05', 'dice-s06', 'dice-s07', 'dice-s08',
]

/** Final force-strength margin, the tier's outcome measure. Positive = player
 *  ahead. This is the quantity the round cap now decides on, so it is a real
 *  score rather than a proxy. */
export const margin = (s) => s.player.force_strength - s.enemy.force_strength

function play(seed, pick) {
  let s = createInitialState(String(seed))
  while (!s.battle_over) s = applyAction(s, pick(s))
  return s
}

/** Per-seed baseline: every policy's margin, plus the mean and best. */
export function baselineFor(seed) {
  const byPolicy = {}
  for (const [name, pick] of Object.entries(POLICIES)) {
    const s = play(seed, pick)
    byPolicy[name] = { margin: margin(s), winner: s.winner, rounds: s.round_number }
  }
  const margins = Object.values(byPolicy).map((r) => r.margin)
  const mean = margins.reduce((a, b) => a + b, 0) / margins.length
  const best = Math.max(...margins)
  return {
    seed,
    by_policy: byPolicy,
    mean_margin: Number(mean.toFixed(3)),
    best_margin: best,
    worst_margin: Math.min(...margins),
    spread: best - Math.min(...margins),
    // A seed no policy can win still scores fine paired, but say so — a reader
    // seeing a run of losses deserves to know some were unwinnable.
    winnable: Object.values(byPolicy).some((r) => r.winner === 'player'),
  }
}

// Only run the CLI when invoked directly. Without this guard the table below
// prints on IMPORT too, so anything reading `--json` off stdout gets the table
// glued to the front of its JSON — which is how this was first found.
import { pathToFileURL } from 'node:url'
const isMain = import.meta.url === pathToFileURL(process.argv[1] ?? '').href

const args = process.argv.slice(2)
const asJson = args.includes('--json')
const seedsOnly = args.includes('--seeds-json')
const seeds = args.filter((a) => !a.startsWith('--'))
const set = seeds.length ? seeds : DEFAULT_SEEDS

if (!isMain) {
  // imported as a module — export only, print nothing
} else if (seedsOnly) {
  // The declared seed set, for the Python side's drift check. Deliberately its
  // own flag rather than a dynamic import: importing a CLI module to read one
  // constant is how the stdout collision above happened.
  console.log(JSON.stringify(DEFAULT_SEEDS))
} else if (asJson) {
  console.log(JSON.stringify(set.map(baselineFor), null, 2))
} else {
  const rows = set.map(baselineFor)
  const names = Object.keys(POLICIES)
  console.log('seed         ' + names.map((n) => n.slice(0, 8).padStart(10)).join('') + '      mean  best  spread  winnable')
  for (const r of rows) {
    console.log(
      r.seed.padEnd(13) +
        names.map((n) => `${r.by_policy[n].winner === 'player' ? 'W' : r.by_policy[n].winner === 'enemy' ? 'L' : 'D'}${r.by_policy[n].margin}`.padStart(10)).join('') +
        String(r.mean_margin).padStart(10) + String(r.best_margin).padStart(6) +
        String(r.spread).padStart(8) + String(r.winnable).padStart(10),
    )
  }
  const meanOfMeans = rows.reduce((a, r) => a + r.mean_margin, 0) / rows.length
  console.log(
    `\n${rows.length} seeds | mean baseline margin ${meanOfMeans.toFixed(2)} | ` +
      `unwinnable ${rows.filter((r) => !r.winnable).length} | ` +
      `mean spread ${(rows.reduce((a, r) => a + r.spread, 0) / rows.length).toFixed(2)}`,
  )
  console.log('\nAn LLM battle on seed X scores  (its final margin) - (that seed\'s mean).')
}

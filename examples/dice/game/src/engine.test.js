import { describe, it, expect } from 'vitest'
import { rollDie, rollPool, isHit, DIE_FACES, HIT_THRESHOLD } from './engine.js'

/** 20 consecutive faces starting at `start` — the Accept criterion's sample size. */
function samples(seed, start) {
  return Array.from({ length: 20 }, (_, i) => rollDie(seed, start + i))
}

describe('rollDie — determinism (Accept: same (seed, roll_counter) → same roll)', () => {
  it('returns the same face for the same (seed, rollCounter), every time', () => {
    for (let c = 0; c < 50; c += 1) {
      expect(rollDie('alpha', c)).toBe(rollDie('alpha', c))
    }
  })

  it('has no hidden stream state — interleaved calls do not perturb later ones', () => {
    const before = rollPool(6, 'alpha', 12)
    for (let c = 0; c < 100; c += 1) {
      rollDie('noise', c * 7)
      rollDie('alpha', c)
    }
    expect(rollPool(6, 'alpha', 12)).toEqual(before)
  })

  it('normalizes the seed, so numeric and string seeds agree', () => {
    expect(rollDie(7, 3)).toBe(rollDie('7', 3))
    expect(rollPool(6, 7, 3)).toEqual(rollPool(6, '7', 3))
  })
})

describe('rollDie — divergence (Accept: different roll_counter differs within 20 samples)', () => {
  const pairs = [
    [0, 1],
    [0, 7],
    [5, 100],
    [1000, 1001],
  ]
  for (const [a, b] of pairs) {
    it(`counters ${a} and ${b} differ at least once across 20 samples`, () => {
      expect(samples('alpha', a)).not.toEqual(samples('alpha', b))
    })
  }

  it('different seeds diverge at the same counter', () => {
    expect(samples('alpha', 0)).not.toEqual(samples('bravo', 0))
  })
})

describe('rollDie — distribution sanity', () => {
  const faces = Array.from({ length: 1000 }, (_, i) => rollDie('dist', i))

  it('only ever produces integer faces in [1, 6]', () => {
    for (const face of faces) {
      expect(Number.isInteger(face)).toBe(true)
      expect(face).toBeGreaterThanOrEqual(1)
      expect(face).toBeLessThanOrEqual(DIE_FACES)
    }
  })

  it('reaches every face (a collapsed hash would not)', () => {
    expect(new Set(faces).size).toBe(DIE_FACES)
  })

  it('hits at roughly the true 1/3 rate over 6000 dice', () => {
    const { hits } = rollPool(6000, 'dist', 0)
    const rate = hits / 6000
    expect(rate).toBeGreaterThan(0.25)
    expect(rate).toBeLessThan(0.42)
  })
})

describe('isHit', () => {
  it('is true for exactly 5 and 6', () => {
    expect([1, 2, 3, 4, 5, 6].filter(isHit)).toEqual([5, 6])
    expect(HIT_THRESHOLD).toBe(5)
  })
})

describe('rollPool', () => {
  it('advances the counter once per die and returns that many rolls', () => {
    for (const n of [0, 1, 6, 8]) {
      const out = rollPool(n, 'pool', 4)
      expect(out.rolls).toHaveLength(n)
      expect(out.rollCounter).toBe(4 + n)
    }
  })

  it('rolls die i at rollCounter + i — no gaps, no reuse', () => {
    const { rolls } = rollPool(8, 'pool', 4)
    rolls.forEach((face, i) => {
      expect(face).toBe(rollDie('pool', 4 + i))
    })
  })

  it('counts hits consistently with its own rolls', () => {
    for (let c = 0; c < 30; c += 1) {
      const { rolls, hits } = rollPool(7, 'pool', c)
      expect(hits).toBe(rolls.filter((f) => f >= 5).length)
    }
  })

  it('treats an empty pool as legal (the (6,0) preset rolls 0 defense dice)', () => {
    expect(rollPool(0, 'pool', 9)).toEqual({ rolls: [], hits: 0, rollCounter: 9 })
  })

  it('returns a fresh array each call', () => {
    const a = rollPool(3, 'pool', 0)
    const b = rollPool(3, 'pool', 0)
    expect(a.rolls).not.toBe(b.rolls)
    a.rolls.push(99)
    expect(rollPool(3, 'pool', 0).rolls).toEqual(b.rolls)
  })

  it('is deterministic across repeated identical calls', () => {
    expect(rollPool(6, 'alpha', 42)).toEqual(rollPool(6, 'alpha', 42))
  })

  it('throws on an invalid die count rather than silently coercing', () => {
    for (const bad of [-1, 2.5, '3', NaN, undefined, null]) {
      expect(() => rollPool(bad, 'pool', 0)).toThrow(TypeError)
    }
  })

  it('throws on a non-integer rollCounter', () => {
    for (const bad of [1.5, '0', NaN, undefined]) {
      expect(() => rollPool(2, 'pool', bad)).toThrow(TypeError)
      expect(() => rollDie('pool', bad)).toThrow(TypeError)
    }
  })
})

describe('RNG discipline (standing constraint)', () => {
  it('never calls Math.random()', () => {
    const real = Math.random
    Math.random = () => {
      throw new Error('Math.random() called in engine')
    }
    try {
      expect(() => rollPool(50, 'discipline', 0)).not.toThrow()
      expect(() => rollDie('discipline', 3)).not.toThrow()
    } finally {
      Math.random = real
    }
  })
})

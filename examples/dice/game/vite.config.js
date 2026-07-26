import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Relative asset URLs so the built bundle works from any static server root
  // (see examples/browser-game/serve.py).
  base: './',
  test: {
    // Engine tests are pure; component tests opt into jsdom per-file with
    // `// @vitest-environment jsdom`.
    environment: 'node',
    // Vitest exits 1 on "no test files found"; the scaffold ships zero tests
    // on purpose (real tests land in T-002+).
    passWithNoTests: true,
    // Explicit `import { describe, it, expect } from 'vitest'` in every test.
    globals: false,
  },
})

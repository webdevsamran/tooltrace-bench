/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base './' so the built site works from GitHub Pages project subpaths
export default defineConfig({
  plugins: [react()],
  base: './',
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test-setup.ts',
    // Playwright e2e specs live outside vitest.
    exclude: ['tests/e2e/**', 'node_modules/**', 'dist/**'],
  },
})
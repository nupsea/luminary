import path from "path"
import { defineConfig } from "vitest/config"

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "node",
    coverage: {
      provider: "v8",
      include: ["src/**"],
      reporter: ["text-summary"],
      // Floors are the measured numbers rounded down (2026-09-28: 16.33 / 13.9 /
      // 11.63 / 15.97). Raise them as coverage grows; never lower one to pass.
      thresholds: { statements: 16, branches: 13, functions: 11, lines: 15 },
    },
  },
})

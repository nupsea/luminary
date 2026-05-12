import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

const NO_RAW_FETCH = {
  selector: 'CallExpression[callee.type="Identifier"][callee.name="fetch"]',
  message:
    'Use the apiClient (request / apiGet / apiPost / ...) from "@/lib/apiClient" instead of raw fetch(). The only legitimate exceptions are SSE streaming, binary downloads, and local-asset reads; add `// eslint-disable-next-line no-restricted-syntax` on the line and a short comment explaining why.',
}

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
  },
  {
    // Forbid raw fetch() outside src/lib/**. Migrations under audit #12
    // funnel all network calls through src/lib/apiClient.ts.
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/lib/**'],
    rules: {
      'no-restricted-syntax': ['error', NO_RAW_FETCH],
    },
  },
])

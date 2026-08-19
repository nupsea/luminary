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
    rules: {
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
      ],
      // Warn, not off: `npm run lint` pins --max-warnings so the backlog can
      // shrink but never grow. Re-raise to error as each WP lands.
      '@typescript-eslint/no-explicit-any': 'warn', // WP5
      'react-hooks/refs': 'warn', // WP5
      'react-hooks/set-state-in-effect': 'warn', // WP5
      'react-hooks/static-components': 'warn', // WP5
      'react-refresh/only-export-components': 'warn', // WP5
    },
  },
  {
    // Forbid raw fetch() outside src/lib/**. Migrations under audit #12
    // funnel all network calls through src/lib/apiClient.ts.
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/lib/**'],
    rules: {
      // An error, not a warning: as a warning it sat inside the --max-warnings
      // budget and the count roughly doubled while nothing ever failed. Every
      // legitimate exception carries an inline disable comment and a reason, so
      // adding one is a decision someone makes rather than a number that drifts.
      'no-restricted-syntax': ['error', NO_RAW_FETCH],
    },
  },
])

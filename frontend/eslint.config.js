import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

// One transport, so a paired device's token and base URL apply to every request (#447).
const RAW_FETCH_MESSAGE =
  'Call the backend through "@/lib/apiClient": request / apiGet / apiPost for JSON, apiFetch for streams, downloads and asset reads, apiUrl for src= URLs. Raw fetch() bypasses the transport.'
const API_BASE_MESSAGE =
  'Build URLs with apiUrl / apiBaseUrl from "@/lib/apiClient"; API_BASE is only the transport default.'
const NO_TRANSPORT_BYPASS = [
  {
    selector: 'MemberExpression[object.name=/^(window|globalThis|self)$/][property.name="fetch"]',
    message: RAW_FETCH_MESSAGE,
  },
  {
    selector: 'MemberExpression[object.type="MemberExpression"][object.object.type="MetaProperty"][object.property.name="env"][property.name="VITE_API_BASE"]',
    message: API_BASE_MESSAGE,
  },
]

// api -> domain -> ui (#448): code imports only from its own layer or one below, so the phone's
// shell takes the api and domain layers without the desktop's screens. A type-only import is
// erased at build and allowed: some domain types still live beside the screens that drew them.
const UI_LAYER = ['**/components/**', '**/pages/**', '**/App', '**/App.tsx']
const DOMAIN_LAYER = ['**/hooks/**', '**/store', '**/store/**', '**/store.ts']
const layerRule = (group, layer) => [
  'error',
  {
    patterns: [
      {
        group,
        allowTypeImports: true,
        message: `${layer} code may not import a higher layer at runtime (api -> domain -> ui, #448).`,
      },
    ],
  },
]

// I-67
const NO_INLINE_INNER_HTML = {
  selector: 'JSXAttribute[name.name="dangerouslySetInnerHTML"] > JSXExpressionContainer > ObjectExpression',
  message:
    'React 19 rewrites innerHTML whenever this object is new, so an inline {__html} re-parses the markup on every render. Build it with useMemo keyed on the string (I-67).',
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
    files: ['src/**/*.{ts,tsx}'],
    rules: {
      // An error, not a warning: as a warning it sat inside the --max-warnings
      // budget and the count roughly doubled while nothing ever failed.
      'no-restricted-syntax': ['error', NO_INLINE_INNER_HTML],
    },
  },
  {
    // The transport's own module, its build-time default and the tests that stub fetch are exempt.
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/lib/apiClient.ts', 'src/lib/config.ts', 'src/**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': ['error', NO_INLINE_INNER_HTML, ...NO_TRANSPORT_BYPASS],
      'no-restricted-globals': ['error', { name: 'fetch', message: RAW_FETCH_MESSAGE }],
      'no-restricted-imports': [
        'error',
        { patterns: [{ regex: '(^@/lib|^\\.{1,2}(/\\.\\.)*(/lib)?)/config$', importNames: ['API_BASE'], message: API_BASE_MESSAGE }] },
      ],
    },
  },
  {
    files: ['src/lib/**/*.{ts,tsx}', 'src/hooks/**/*.{ts,tsx}', 'src/store/**/*.ts', 'src/store.ts', 'src/types/**/*.ts'],
    ignores: ['src/**/*.test.{ts,tsx}'],
    rules: { '@typescript-eslint/no-restricted-imports': layerRule(UI_LAYER, 'Domain') },
  },
  {
    files: ['src/lib/apiClient.ts', 'src/lib/config.ts', 'src/lib/*Api.ts'],
    rules: { '@typescript-eslint/no-restricted-imports': layerRule([...UI_LAYER, ...DOMAIN_LAYER], 'API') },
  },
  {
    // The phone's shell: the api and domain layers and shared components, never a desktop screen.
    files: ['src/mobile/**/*.{ts,tsx}'],
    ignores: ['src/**/*.test.{ts,tsx}'],
    rules: { '@typescript-eslint/no-restricted-imports': layerRule(['**/pages/**', '**/App', '**/App.tsx'], 'Mobile') },
  },
])

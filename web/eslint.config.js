// Flat config. ESLint 10 removed support for .eslintrc.* and the --ext flag,
// so the 9 -> 10 bump is a configuration migration, not just a version change.
// Every rule below is carried over from the previous .eslintrc.json unchanged.
import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import reactHooks from 'eslint-plugin-react-hooks'

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'coverage', '**/*.cjs'] },
  js.configs.recommended,
  {
    // The service worker runs in a worker global scope, not the window one:
    // `self`, `caches` and `clients` exist there and nowhere else. Declaring
    // them here rather than disabling `no-undef` for the file keeps the rule
    // catching real typos in it.
    files: ['public/sw.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'script',
      globals: {
        self: 'readonly',
        caches: 'readonly',
        clients: 'readonly',
        fetch: 'readonly',
        Response: 'readonly',
        Headers: 'readonly',
        URL: 'readonly',
      },
    },
  },
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
)

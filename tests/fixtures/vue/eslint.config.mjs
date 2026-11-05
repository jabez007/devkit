import vue from 'eslint-plugin-vue'
import ts from 'typescript-eslint'
export default [
  { ignores: ['node_modules/**', 'test-results/**', 'playwright-report/**', '.claude/**', '.gc/**', '.devcontainer/**'] },
  ...ts.configs.recommended,
  ...vue.configs['flat/essential'],
  { files: ['**/*.vue'], languageOptions: { parserOptions: { parser: ts.parser } } },
]

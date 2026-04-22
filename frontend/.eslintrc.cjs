/**
 * Pixels Rover Web Frontend — ESLint config (legacy .eslintrc.cjs for ESLint 8.57).
 *
 * 本配置机械化 `docs/development/frontend.md §2` 的三条开发纪律：
 *
 *   - lint-0（纪律 3）：跨 feature 只能经由 `features/<name>/index.ts` barrel；
 *                      `features/` / `shared/` 不允许反向依赖 `app/`。
 *   - lint-1（纪律 1）：`features/*\/model/**` 不允许 import `react` /
 *                      `react-router-dom` / `antd`（保持 model 层对渲染层零依赖）。
 *   - lint-2（纪律 2）：`shared/api/**` 不允许访问 `document` / `window` /
 *                      `localStorage` / `sessionStorage`；浏览器副作用统一归
 *                      `shared/storage/`。
 *
 * 合规判据（见 `frontend.md §3.0`）：
 *   - 每条规则都有对应 `src/__eslint_assertions__/<rule>.lint-assertion.ts.skip`
 *     固化反例；`.skip` 后缀使其不被 `eslint . --ext ts,tsx` 命中，但可通过
 *     `cp xxx.ts.skip xxx.ts && npm run lint` 一键回归验证规则仍有效。
 *   - `npm run lint` baseline 对当前代码库期望 0 error / 0 warning。
 *
 * lint-2 用 `no-restricted-syntax` + AST 选择器（见 `frontend.md §3.4` caveat）而
 * 非 `no-restricted-globals`：后者对 TypeScript 项目下 `lib.dom.d.ts` 声明的全局
 * 通常放行，不满足"规则实际触发"的合规判据。
 */

/** 共享 group 定义：跨 feature 内部文件穿透 barrel（纪律 3 的正向禁令） */
const featureBarrierGroup = {
  group: [
    '@/features/*/components/*',
    '@/features/*/hooks/*',
    '@/features/*/services/*',
    '@/features/*/model/*',
  ],
  message:
    '跨 feature 访问请只经由 `@/features/<name>` 的 index.ts（frontend.md §2 纪律 3）',
};

/** 共享 group 定义：features/ 与 shared/ 反向依赖 app/（纪律 3 的依赖方向禁令） */
const appReverseDepGroup = {
  group: ['@/app/*', '@/app'],
  message:
    'features/ 和 shared/ 不允许反向依赖 app/（frontend.md §2 纪律 3 依赖方向：app → features → shared）',
};

/** lint-1：features/*\/model/ 禁 framework 精确包名（纪律 1） */
const modelFrameworkPaths = [
  { name: 'react', message: 'features/*\/model 不允许依赖 React（frontend.md §2 纪律 1）' },
  {
    name: 'react-router-dom',
    message: 'features/*\/model 不允许依赖 React Router（frontend.md §2 纪律 1）',
  },
  { name: 'antd', message: 'features/*\/model 不允许依赖 AntD（frontend.md §2 纪律 1）' },
];

module.exports = {
  root: true,
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 2020,
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  env: { browser: true, es2020: true, node: true },
  plugins: ['@typescript-eslint', 'react-hooks', 'react-refresh'],
  extends: ['eslint:recommended', 'plugin:@typescript-eslint/recommended'],
  ignorePatterns: [
    'dist/',
    'node_modules/',
    '**/*.lint-assertion.ts.skip',
    '**/*.lint-assertion.tsx.skip',
  ],
  rules: {
    // lint-0：纪律 3 全仓约束——跨 feature 禁止穿透 barrel
    'no-restricted-imports': ['error', { patterns: [featureBarrierGroup] }],

    // 把 base `no-unused-vars` 交给 @typescript-eslint 版本（否则 TS 类型引用会误报）
    'no-unused-vars': 'off',
    '@typescript-eslint/no-unused-vars': [
      'error',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
    ],

    // 本次 PR 只关心三条纪律的机械化，不收紧广谱代码质量（留给后续 PR）
    '@typescript-eslint/no-explicit-any': 'off',
    '@typescript-eslint/ban-ts-comment': 'off',
    '@typescript-eslint/no-empty-function': 'off',

    // `while (true) { ...; if (done) break; }` 是 ReadableStream.read() 的规范
    // 写法（见 shared/api/sse.ts）；只在 `if (false)` / 三元里 `true` 这种真常量
    // 条件上报错
    'no-constant-condition': ['error', { checkLoops: false }],
  },
  overrides: [
    // lint-0 续：features/ 与 shared/ 禁反向依赖 app/
    // （在目录级 overrides 里重列 featureBarrierGroup，因为 `no-restricted-imports`
    //   不合并——overrides 的配置会整体替换父级同名规则）
    {
      files: ['src/features/**/*.{ts,tsx}', 'src/shared/**/*.{ts,tsx}'],
      rules: {
        'no-restricted-imports': [
          'error',
          { patterns: [featureBarrierGroup, appReverseDepGroup] },
        ],
      },
    },

    // lint-1：features/*\/model/** 禁 react / react-router-dom / antd
    // 同样重列 featureBarrierGroup + appReverseDepGroup 以保持纪律 3 仍生效
    {
      files: ['src/features/*/model/**/*.{ts,tsx}'],
      rules: {
        'no-restricted-imports': [
          'error',
          {
            paths: modelFrameworkPaths,
            patterns: [featureBarrierGroup, appReverseDepGroup],
          },
        ],
      },
    },

    // lint-2：shared/api/** 禁 document / window / localStorage / sessionStorage
    // 用 no-restricted-syntax + AST 选择器（frontend.md §3.4 首选兜底路径）
    {
      files: ['src/shared/api/**/*.{ts,tsx}'],
      rules: {
        'no-restricted-syntax': [
          'error',
          {
            selector:
              "MemberExpression[object.name=/^(document|window|localStorage|sessionStorage)$/]",
            message:
              'shared/api 不允许直接访问 document / window / localStorage / sessionStorage，请走 shared/storage（frontend.md §2 纪律 2）',
          },
          {
            selector:
              "VariableDeclarator > Identifier.id[name=/^(document|window|localStorage|sessionStorage)$/]",
            message:
              'shared/api 不允许以变量别名绕过禁令访问浏览器全局（frontend.md §2 纪律 2）',
          },
        ],
      },
    },

    // 测试文件豁免：colocated 测试能 import 本 feature 内部符号（frontend.md §1.1.1）；
    // 同时 features/*\/model 的测试允许渲染 hook/组件（§1.1.1 第 4 点豁免）
    {
      files: ['**/*.test.{ts,tsx}', '**/__tests__/**/*.{ts,tsx}'],
      rules: {
        'no-restricted-imports': 'off',
        '@typescript-eslint/no-unused-vars': 'off',
      },
    },

    // vite.config.ts / 顶层脚本：Node 运行时，不参与 src/ 的纪律
    {
      files: ['vite.config.{ts,js}', '*.config.{ts,js,cjs}'],
      env: { node: true },
      rules: {
        'no-restricted-imports': 'off',
      },
    },
  ],
};

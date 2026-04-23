/**
 * `features/auth` barrel——frontend.md §2 纪律 3 指定的唯一跨 feature 入口。
 *
 * 对外暴露：
 *   - `useAuthStore`——登录态快照 & 登出动作（AppRouter guard / AppHeader
 *     内部消费、其它 feature 如果需要"知道当前用户是不是谁"也经由这里）；
 *   - `AppHeader`——顶栏组件（Home 布局里挂一个；不走 lazy，因为它是 Home
 *     的首屏元素，单独 chunk 反而增加首次渲染等待）；
 *   - `Login` / `Register`——**用 React.lazy 包装过的**路由组件。之所以
 *     lazy 在 barrel 里完成而不是在 AppRouter 里：
 *
 *       * AppRouter 如果走 `import('../../features/auth').then(m => m.Login)`
 *         会把 useAuthStore / AppHeader 一起打成同一个 chunk，等于绕过了
 *         "登录页只加载登录所需代码"的初衷；
 *       * 如果 AppRouter 直接 `import('../../features/auth/components/Login')`
 *         就穿透了 barrier（lint-0 精神）。
 *
 *     在 barrel 内部完成 `React.lazy(() => import('./components/Login'))`，
 *     内部 `./components/Login` 是同 feature 相对路径（合规），同时 Rollup
 *     把 lazy import 识别成独立 chunk——两个约束同时满足。
 *
 * 不暴露：
 *   - `authApi`——feature 私有 API 客户端；其它代码读登录态走 `useAuthStore`，
 *     不直接喊 endpoint；
 *   - `services/` / `model/` / `components/` 内部文件——lint-0 的
 *     `@/features/*\/components/*` 等 pattern 会阻止跨 feature 穿透。
 */

import React from 'react';

export { useAuthStore } from './model/store';
export { default as AppHeader } from './components/AppHeader';

export const Login = React.lazy(() => import('./components/Login'));
export const Register = React.lazy(() => import('./components/Register'));

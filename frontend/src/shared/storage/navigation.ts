/**
 * Navigation side-effects on the browser (frontend.md §2 纪律 2）。
 *
 * 这里承载的是"需要直接触发浏览器导航"的副作用调用点（如 refresh token 彻底失败
 * 后跳登录）。`shared/api/` 是纯网络契约层，禁止直接访问 `window.location`；
 * 把这类调用集中在 `shared/storage/` 可以让 SSR / 测试环境用一行 mock 注入替换。
 */

const LOGIN_PATH = '/login';

/**
 * Hard-redirect the current browser tab to the login page.
 *
 * 之所以用 `window.location.assign` 而不是 react-router `navigate()`：
 *   - 调用点在 axios 拦截器里（非 React 渲染树），拿不到 router context；
 *   - refresh token 彻底失败意味着 in-memory 状态已不可信，整页硬刷可以把
 *     Zustand / TanStack Query 等客户端缓存全部清掉，避免残留态被滥用。
 */
export function redirectToLogin(): void {
  window.location.assign(LOGIN_PATH);
}

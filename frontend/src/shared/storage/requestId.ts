/**
 * X-Request-Id 的生成层（frontend.md §4.6 硬规则）。
 *
 * **职责边界（硬规则）**：本文件只承担
 *
 *   - id 的**生成**（纯函数，优先 `crypto.randomUUID()`，回退 timestamp+rand）；
 *   - id 的**"一次性取得"语义**（`ensureRequestId(existing?)`）——给定一个可
 *     选的已有 id，若非空就原样返回，否则生成新 id。把"复用 vs 新建"的二元
 *     判断显式化为函数调用的参数，调用点（axios 拦截器 / SSE 客户端）就不
 *     会靠"拦截到同一个 config 对象"这种隐式前提来保证复用。
 *
 * 本文件**明确不做**（frontend.md §4.6 职责边界）：
 *
 *   - 不 import `axios` / 不感知 `fetch` / `Request`——把 id 绑定到请求是
 *     `shared/api/` 的职责；
 *   - 不读写 `localStorage` / `sessionStorage`——当前所有需要 "同一 request-id
 *     延续跨多次底层 IO" 的场景（axios 401 重试、SSE 30s 心跳断流后一次自动
 *     重连）都是**同一逻辑请求的生命周期内**解决，调用点自己把 id 留在闭包
 *     / 模块局部变量里复用即可；在 storage 层做进程级单例缓存反而会把"两个
 *     逻辑请求同时在飞"的场景错误合并成同一个 id。
 *
 * 这两条不做的东西是 `scripts/check-contracts.py::frontend-request-id-storage-isolation`
 * 的兜底检查对象：任何一天有人把 `import axios` 或 `localStorage` 写进本文件，
 * PR 会被静态断言拦下。
 */

/**
 * Generate a fresh request id. Prefer ``crypto.randomUUID()`` — it's
 * universally available in modern browsers and avoids any observable
 * pattern that a server-side log aggregator could use to infer timing.
 * The ``req-<ts>-<rand>`` fallback only triggers on environments that
 * predate ``crypto.randomUUID`` (very old Edge builds, JSDOM in tests).
 */
export function createRequestId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * Resolve the request id for the current logical request.
 *
 * - If ``existing`` is a non-empty string, return it verbatim. Call sites
 *   pass their own captured id here when a single logical request produces
 *   multiple underlying IO calls (axios 401 → refresh → retry; SSE 30s
 *   heartbeat timeout → reconnect with ``Last-Event-Id``).
 * - Otherwise, mint a fresh id via ``createRequestId()``.
 *
 * The function is intentionally **not** stateful. Callers that need to
 * reuse an id across multiple IO attempts must hold it themselves — either
 * in the axios request config (``config.headers['X-Request-Id']``, which
 * the request interceptor already respects by checking for presence first)
 * or in a local variable scoped to the SSE stream lifecycle. This avoids
 * the "two parallel logical requests collide in a global slot" bug that a
 * session-wide cache would introduce.
 */
export function ensureRequestId(existing?: string | null): string {
  if (typeof existing === 'string' && existing.length > 0) {
    return existing;
  }
  return createRequestId();
}

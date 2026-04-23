/**
 * TanStack Query key stratification — decision C1 in `.notes/todolist.md §12`.
 *
 * 核心约束：
 *
 *   1. 所有 query key 的第 0 段必须是一个**显式注册**的 feature namespace
 *      字符串字面量（见 {@link FEATURE_NAMESPACES}）。新 feature 必须先在
 *      这里注册，防止跨 feature key 撞名 / 野 key 绕过 barrier。
 *
 *   2. Feature 内部通过 {@link createFeatureKeyFactory} 派生自己的 key，不
 *      直接手写 `['auth', 'me']` 这种字面量数组。工厂保证第 0 段是合法的
 *      namespace，并让 feature 子分类（`'list'` / `'detail'` / ...）可以
 *      随 key 语义自然扩展。
 *
 *   3. Key tuple 全部声明为 `readonly`：TanStack 自身把 key 当作只读缓存键
 *      使用，业务代码也不该在读后 mutate 它。`QueryKey` 的 `as const`
 *      派生在组件里 `queryKey: keys.list(backendId)` 不需要显式 `as const`。
 *
 * 本文件故意放在 `shared/types/`（而非 `shared/api/`）——它是纯类型 / 字面
 * 量数据，不触发任何运行时副作用；和 `shared/api/**` 的 lint-2 浏览器全局
 * 禁令无关，也不需要被 app/features 反向依赖。
 */

// ════════════════════════════════════════
// Feature namespace registry
// ════════════════════════════════════════

/**
 * 注册表：所有允许作为 query key 第 0 段的 feature 名。
 *
 * 加新 feature：
 *   1. 在这里追加字符串字面量（保持按字母序）。
 *   2. 对应的 feature 入口（`features/<name>/model/queryKeys.ts`）用
 *      {@link createFeatureKeyFactory} 派生自己的 key 工厂。
 *   3. 跨 feature 读对方 key 只能经由对方 `features/<name>/index.ts` barrel
 *      重新 export 出来的 key 工厂（lint-0 纪律 3）。
 *
 * `__probe__` 是专给 `features/__probe__/` 用的保留值；任何正式 feature
 * 都不应该用它。
 */
export const FEATURE_NAMESPACES = [
  '__probe__',
  'analysis',
  'auth',
  'backends',
  'conversation',
  'schema',
  'semantic',
] as const;

export type FeatureNamespace = (typeof FEATURE_NAMESPACES)[number];

/**
 * 运行时校验一个字符串是否是合法 namespace。仅用于 devtools / 测试边界，
 * 不应该进生产热路径——工厂在类型层面已经把这件事拦在编译期。
 */
export function isFeatureNamespace(value: unknown): value is FeatureNamespace {
  return (
    typeof value === 'string' &&
    (FEATURE_NAMESPACES as readonly string[]).includes(value)
  );
}

// ════════════════════════════════════════
// Query key shape
// ════════════════════════════════════════

/**
 * 分层后的 query key tuple：首段是 namespace，剩余段由 feature 自己拼。
 *
 * 比 TanStack 默认的 `unknown[]` 收紧一层——确保任何 `useQuery({ queryKey })`
 * 的调用都能被类型系统追回到某个注册过的 feature。
 */
export type QueryKey = readonly [FeatureNamespace, ...readonly unknown[]];

// ════════════════════════════════════════
// Factory
// ════════════════════════════════════════

/**
 * 返回一组绑定到特定 namespace 的 key 辅助函数。
 *
 * Feature 的典型用法（在 `features/<name>/model/queryKeys.ts`）：
 *
 *   const keys = createFeatureKeyFactory('analysis');
 *   export const analysisKeys = {
 *     all: keys.all(),
 *     sessions: () => keys.segment('sessions'),
 *     session: (id: string) => keys.segment('sessions', id),
 *   } as const;
 *
 * 之所以把"分类 + 参数"的语义留给 feature 层自己定义而不是在工厂里硬编
 * `list()` / `detail(id)` 两个槽位——
 *   - 真实需求不是只有 list/detail：有 infinite pagination、按 schema 的
 *     session 分片、按 backendId 的能力探测 etc.
 *   - 强制一个二选一的 shape 会逼 feature 层往 key 里塞 magic string。
 *
 * 工厂只承诺：namespace 段正确 + 返回值是合法 `QueryKey`。
 */
export function createFeatureKeyFactory(namespace: FeatureNamespace) {
  return {
    /** 该 feature 下所有 key 的根——用于 `queryClient.invalidateQueries({ queryKey: keys.all() })`。 */
    all(): QueryKey {
      return [namespace] as const;
    },
    /** 在 namespace 之后拼任意段；feature 层应包一层具名函数再对外暴露。 */
    segment(...rest: readonly unknown[]): QueryKey {
      return [namespace, ...rest] as const;
    },
  };
}

export type FeatureKeyFactory = ReturnType<typeof createFeatureKeyFactory>;

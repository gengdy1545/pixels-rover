/**
 * @vitest-environment node
 *
 * C1 query-key 工厂的契约测试。
 *
 * 这层测试不验收"TanStack 的缓存语义对不对"——那是 TanStack 自己的职责。
 * 它只锁死工厂对外暴露的三件事：
 *   - namespace 只能取自 {@link FEATURE_NAMESPACES}；
 *   - `all()` 返回恰好单元素 tuple，用于 invalidate 整个 feature；
 *   - `segment(...rest)` 在 namespace 之后附带任意段。
 *
 * 显式 pin `@vitest-environment node`：本测试完全是纯 TS 逻辑，不需要 DOM。
 * 项目默认 env 是 jsdom（见 `vite.config.ts`），会把 html-encoding-sniffer →
 * @exodus/bytes 的 CJS/ESM 兼容性问题拖进这个 suite；显式降到 node env 把
 * 非必要副作用挡在外面，同时也在文档层面提示读者："model 层 key 测试不该
 * 依赖 DOM"。
 */

import { describe, it, expect } from 'vitest';
import {
  FEATURE_NAMESPACES,
  createFeatureKeyFactory,
  isFeatureNamespace,
} from './query-keys';

describe('FEATURE_NAMESPACES registry', () => {
  it('registry 不重复 —— 防止同 namespace 被注册两遍绕过撞名检查', () => {
    const set = new Set(FEATURE_NAMESPACES);
    expect(set.size).toBe(FEATURE_NAMESPACES.length);
  });

  it('__probe__ 是专用保留段 —— 文档边界，业务 feature 不要占用', () => {
    expect(FEATURE_NAMESPACES).toContain('__probe__');
  });

  it('isFeatureNamespace 仅对注册过的字符串返回 true', () => {
    expect(isFeatureNamespace('auth')).toBe(true);
    expect(isFeatureNamespace('not-a-feature')).toBe(false);
    expect(isFeatureNamespace(42)).toBe(false);
    expect(isFeatureNamespace(undefined)).toBe(false);
  });
});

describe('createFeatureKeyFactory', () => {
  it('all() 返回 [namespace] 单元素 tuple', () => {
    const keys = createFeatureKeyFactory('auth');
    expect(keys.all()).toEqual(['auth']);
  });

  it('segment(...rest) 把 namespace 作为第 0 段', () => {
    const keys = createFeatureKeyFactory('analysis');
    expect(keys.segment('sessions', 'abc')).toEqual(['analysis', 'sessions', 'abc']);
  });

  it('segment 允许非字符串段 —— 对象过滤器也合法', () => {
    const keys = createFeatureKeyFactory('schema');
    const filter = { backendId: 'b1' };
    expect(keys.segment('list', filter)).toEqual(['schema', 'list', filter]);
  });

  it('两个不同 namespace 的工厂产出的 key 绝不相等', () => {
    const authKeys = createFeatureKeyFactory('auth');
    const analysisKeys = createFeatureKeyFactory('analysis');
    expect(authKeys.all()).not.toEqual(analysisKeys.all());
  });
});

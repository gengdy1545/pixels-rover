# 可观测性 Roadmap（观测采集管道的路线图）

> 本文件定义 Pixels Rover 在"观测采集管道"（log pipeline / metrics pipeline / tracing pipeline）这件事上的**当前决策**与**重新评估触发条件**。写在 `runbooks/` 下是因为它是运维主题而非 dev 主题——但其约束会反向影响 dev 文档中的日志字段、指标字段、trace 上下文字段。
>
> **长期契约锚点**：`backend.md §10.1`、`gateway.md §8.2`、`frontend.md §4.6` 中定义的结构化字段名集合与语义，是跨管道的稳定承诺；本 roadmap 的任何阶段切换都**不得**回头修改那些字段的含义，只能扩展。
>
> 与 [`../development/backend.md`](../development/backend.md) / [`../development/gateway.md`](../development/gateway.md) 冲突时以 dev 文档为准。

## 1. 当前阶段的决策

**当前阶段：不落地独立的观测采集管道。**

- 日志：各服务与 gateway 以 JSON 结构化日志写 stdout；本地开发通过 `docker compose logs -f` 消费，生产通过容器平台（或 host 级 `journald` / `logrotate`）落盘。
- 指标：各服务按 `backend.md §10.2` 暴露 `/metrics`（Prometheus 格式）；**当前不部署**独立的 Prometheus 实例，也不接任何外部时序库。该端点的存在价值是**准备好被未来采集管道直接爬取**，以及**本地故障定位时 `curl`-check**。
- Tracing：当前**不引入** OpenTelemetry / Jaeger / Zipkin。由 `X-Request-Id` 在日志层贯穿请求链路承担"跨服务关联"的最小职责，字段契约见 `backend.md §5` / `gateway.md §8.1`。

**这是一个被显式锁定的决策，不是疏漏**。选择背景：

- 项目当前处于单实例 gateway + 单实例 auth-service + 单实例 assistant-service 的规模（见 `gateway.md §1.2` / `backend.md §13.1`），完整接入"日志采集 → 索引 → 查询"三段链路的运维成本远大于收益；
- 结构化日志 + `X-Request-Id` 贯穿已经足以覆盖当前阶段的故障定位场景（开发者 `grep requestId=<uuid>` 跨服务日志 = 人工 trace）；
- 过早引入 pipeline 会让"采集链路本身"成为新的故障面（采集 agent 占 CPU / backpressure / 索引膨胀 / 查询超时），与当前项目"把复杂度留给业务、把接入面做薄"的总体方向冲突。

## 2. 不做观测管道**不代表**放弃以下硬规则

以下规则无论是否引入管道都必须满足，任何单个业务 PR **不得**以"反正还没接管道"为由绕开：

1. **日志必须是结构化 JSON**：每条日志一行 JSON，包含 `backend.md §10.1` 规定的全部字段；禁止"`INFO - user 123 logged in`"这类人话日志作为唯一输出形态（可以并行，但不能取代）。
2. **日志字段命名即契约**：字段名与语义不因阶段变化而变。新增字段必须在对应 dev 文档的 §10.1 / §8.2 表内落地，走 PR review。
3. **`X-Request-Id` 贯穿所有层**：前端 → gateway → auth-service / assistant-service 的日志必须能通过同一个 `requestId` 串起来。破坏贯穿的 PR 即便功能正确也拒绝合并——这是观测基础设施的最低边界，不随管道阶段变化。
4. **不得在业务代码里 hardcode "`logger.log(JSON.stringify(...))`"**：结构化日志必须走服务各自的 logger 封装（`auth-service` 的 `LoggingConfig` / `assistant-service` 的 `structlog` 或等价抽象），以便未来切换 formatter / sink 时只改一处。
5. **`/metrics` 端点必须可用**：即便当前没有 Prometheus 在爬，该端点必须返回 200 且格式正确。

这五条是"观测管道未来可接入"的前提条件——如果它们破损，届时再想接管道会发现"先要补半年的日志规范化"，成本远大于现在顺手遵守。

## 3. 重新评估触发信号

出现下列任一信号时，回到本 roadmap 重新评估是否进入"阶段 B：引入观测采集管道"：

- **运维规模**：生产实例总数 ≥ 3（例如 assistant-service 横向扩容、或新服务接入），人工 `grep` 跨实例日志已不可行；
- **合规要求**：出现"日志必须集中存储 N 天 + 可审计查询"的合规需求（等保、ISO 27001 等）；
- **故障复现成本**：连续 ≥ 2 次生产故障在"日志散落各容器无法聚合"这一层卡住 MTTR（从故障报告到根因定位 > 30 min 且主因是日志不聚合）；
- **tracing 需求**：出现"跨 ≥ 3 服务的复合请求链路，且其中延迟 / 错误分布无法从日志推导"（当前不存在此类请求，因此不需要 tracing）；
- **外部观测方进入**：项目被纳入更大的观测集群（例如公司统一监控平台），此时"加入集群"本身就是该集群的硬要求。

**仅单一信号出现时先做"局部补强"**（例如给某个特定服务加个 Loki sink 做临时聚合），不立刻升到阶段 B；**两个以上信号同时成立**再走阶段 B 的完整决策流程。

## 4. 阶段 B 的候选方案（触发信号命中后再展开）

本节仅列出进入阶段 B 时的候选技术栈方向，**当前不选型、不预研、不做技术 POC**——项目资源投入在业务与基础接入面，而非尚未触发的管道建设。

- **日志聚合**：Loki + Grafana / Elastic Stack / Vector + 外部对象存储等。
- **指标采集**：Prometheus + Grafana / VictoriaMetrics / 托管 TSDB。
- **tracing**：OpenTelemetry SDK + OTel Collector + Jaeger / Tempo。
- **统一接入**：OTel Collector 作为 single pane 同时吸纳日志 / 指标 / trace 并路由。

触发阶段 B 时，选型评估**必须**在本文件生成专门章节（或独立 ADR 文档），与 `backend.md §10.1` / `gateway.md §8.2` 的字段契约显式比对，证明选型不需要改动已定字段语义。

## 5. 与其他文档的耦合

- [`../development/backend.md §10.1`](../development/backend.md)：结构化日志字段表；本 roadmap 不改动该表字段，只在阶段 B 触发时补充"如何消费"。
- [`../development/backend.md §10.2`](../development/backend.md)：Prometheus 指标维度；当前阶段各服务**必须**暴露该端点即便无采集方。
- [`../development/gateway.md §8.2`](../development/gateway.md)：gateway access.log 字段；与 §10.1 对齐，同一字段名在两层日志中含义一致。
- [`../development/frontend.md §4.6`](../development/frontend.md)：前端 `X-Request-Id` 生成与回显契约；贯穿链路的起点在此。
- [`./jwt-rotation-drill.md`](./jwt-rotation-drill.md)：轮换期的日志字段观测点在阶段 B 之后会被纳入可视化面板，但**演练动作本身**不依赖管道，只依赖 `docker logs`。

## 6. 变更记录

新增变更在本节追加条目，**不**覆盖历史。每条包含：时间 / 触发信号 / 进入阶段 / 对其他文档的联动改动摘要。

- *（当前阶段：锁定"阶段 A：stdout + 无独立管道"，无变更记录。）*

import json
import logging

from app.schemas.task import AnalysisTask
from app.schemas.semantic import ResolvedContext
from app.schemas.plan import AnalysisPlan, PlanStep, StepParams
from app.schemas.harness import PlanValidationError
from app.infra.llm import LLMClient
from app.core.harness import RunContext, OutputGuardrail

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """你是一个数据分析计划生成器。根据分析任务和语义上下文，生成一个线性执行计划。

## 可用的步骤类型（action）
1. "generate_and_execute_sql" - 生成 SQL 并执行查询
2. "summarize_results" - 汇总所有步骤结果，生成自然语言结论（必须是最后一步）

## 输出 JSON 格式
{
  "steps": [
    {
      "step_id": "s1",
      "action": "generate_and_execute_sql",
      "description": "获取本月北美 GMV",
      "params": {
        "purpose": "查询本月北美地区的 GMV 总额",
        "metrics": ["gmv"],
        "filters": [{"dimension": "region", "operator": "=", "value": "北美"}],
        "time_range": {"preset": "this_month", "description": "本月"},
        "group_by": null,
        "schema_name": "tpch",
        "backend_id": "duckdb-local"
      }
    },
    {
      "step_id": "s2",
      "action": "summarize_results",
      "description": "汇总分析结果并生成结论",
      "params": {"purpose": "基于查询结果生成自然语言分析结论"}
    }
  ],
  "explanation": "用一两句话解释为什么这样规划"
}

## 规则
1. 步骤数量限制: 最少 2 步（至少一个查询 + summarize），最多由任务信封限制。
2. 最后一步必须是 "summarize_results"。
3. query 类任务: 1 个查询步骤 + summarize。
4. compare 类任务: 2 个查询步骤（当前期 + 基线期）+ summarize。
5. diagnose 类任务: 2-5 个查询步骤（当前值 + 基线值 + 维度拆解）+ summarize。
6. params 中的 metrics 使用 canonical_name（标准名），不是用户原文。
7. params 中的 schema_name 和 backend_id 从语义上下文获取。
8. step_id 格式: "s1", "s2", "s3"...
9. 必须输出合法 JSON。"""


class Planner:
    def __init__(self, llm_client: LLMClient, output_guardrail: OutputGuardrail):
        self._llm = llm_client
        self._guardrail = output_guardrail

    async def generate_plan(
        self,
        task: AnalysisTask,
        resolved: ResolvedContext,
        ctx: RunContext,
    ) -> AnalysisPlan:
        ctx.check_budget()

        context_info = self._build_context(task, resolved, ctx)
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": context_info},
        ]

        resp = await self._llm.call_json(messages)
        ctx.record_llm_call(resp.tokens_in, resp.tokens_out)

        def retry_fn(error: str) -> list[dict]:
            return messages + [
                {"role": "assistant", "content": resp.content},
                {"role": "user", "content": f"计划输出解析失败: {error}\n请重新输出合法的 JSON。"},
            ]

        plan = await self._guardrail.parse_llm_output(
            resp.content, AnalysisPlan, ctx, retry_prompt_fn=retry_fn
        )

        self._validate_plan(plan, resolved, ctx.envelope.max_steps)
        return plan

    def _build_context(
        self, task: AnalysisTask, resolved: ResolvedContext, ctx: RunContext
    ) -> str:
        metrics_info = []
        for m in resolved.metrics:
            metrics_info.append(
                f"- {m.canonical_name} (显示名: {m.display_name}): "
                f"{m.calculation} FROM {m.source_schema}.{m.source_table} "
                f"[backend: {m.backend_id}]"
            )

        dims_info = []
        for d in resolved.dimensions:
            dims_info.append(
                f"- {d.canonical_name} (显示名: {d.display_name}): "
                f"列 {d.source_column} FROM {d.source_schema}.{d.source_table}"
            )

        joins_info = []
        for j in resolved.join_paths:
            joins_info.append(f"- {j.left_table} {j.join_type} JOIN {j.right_table} ON {j.join_condition}")

        parts = [
            f"## 分析任务",
            f"类型: {task.task_type}",
            f"原始输入: {task.raw_input}",
            f"指标: {task.target_metrics}",
            f"过滤条件: {json.dumps([f.model_dump() for f in task.filters], ensure_ascii=False) if task.filters else '无'}",
            f"时间范围: {task.time_range.model_dump() if task.time_range else '未指定'}",
            f"对比基线: {task.comparison_baseline.model_dump() if task.comparison_baseline else '无'}",
            f"分析维度: {task.analysis_dimensions if task.analysis_dimensions else '无'}",
            "",
            f"## 已解析的语义上下文",
            f"指标定义:",
            "\n".join(metrics_info) if metrics_info else "  (无)",
            f"维度定义:",
            "\n".join(dims_info) if dims_info else "  (无)",
            f"Join 路径:",
            "\n".join(joins_info) if joins_info else "  (无)",
            "",
            f"## 约束",
            f"最大步骤数: {ctx.envelope.max_steps}",
        ]
        return "\n".join(parts)

    def _validate_plan(self, plan: AnalysisPlan, resolved: ResolvedContext, max_steps: int) -> None:
        if not plan.steps:
            raise PlanValidationError("计划不能为空")

        if len(plan.steps) > max_steps:
            raise PlanValidationError(f"步骤数 {len(plan.steps)} 超过限制 {max_steps}")

        last_step = plan.steps[-1]
        if last_step.action != "summarize_results":
            raise PlanValidationError("最后一步必须是 summarize_results")

        sql_steps = [s for s in plan.steps if s.action == "generate_and_execute_sql"]
        if not sql_steps:
            raise PlanValidationError("至少需要一个 generate_and_execute_sql 步骤")

        for i, step in enumerate(plan.steps):
            if not step.step_id:
                step.step_id = f"s{i + 1}"

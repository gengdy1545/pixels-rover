import json
import time
import logging

import sqlglot

from app.schemas.plan import PlanStep, StepResult
from app.schemas.semantic import ResolvedContext
from app.schemas.backend import ValidationResult
from app.schemas.harness import GuardrailViolation
from app.storage.base import StorageBackend
from app.infra.llm import LLMClient
from app.core.harness import RunContext, check_sql_safety

logger = logging.getLogger(__name__)

SQL_GEN_SYSTEM_PROMPT = """你是一个 SQL 生成专家。根据分析上下文生成一条精确的 SELECT SQL 语句。

## 规则
1. 只生成一条 SELECT 语句。
2. 使用提供的表名、列名和计算公式，不要编造不存在的表或列。
3. 输出纯 JSON: {"sql": "SELECT ..."}
4. 时间过滤请使用标准日期格式。
5. 如果需要聚合，确保 GROUP BY 与 SELECT 中的非聚合列一致。
6. 使用前序步骤的结果来优化查询（如果提供了的话）。
7. 不要添加 LIMIT 子句（由执行层控制）。"""


class StepExecutor:
    """Executes individual plan steps: SQL generation -> validation -> execution."""

    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    async def execute(
        self,
        step: PlanStep,
        resolved: ResolvedContext,
        ctx: RunContext,
        all_steps: list[PlanStep],
        backend: StorageBackend,
    ) -> None:
        start = time.monotonic()
        step.status = "running"

        try:
            ctx.check_budget()
            ctx.record_step()

            if step.action == "generate_and_execute_sql":
                await self._execute_sql_step(step, resolved, ctx, all_steps, backend)
            else:
                step.status = "skipped"

        except GuardrailViolation as e:
            step.status = "failed"
            step.error = str(e)
            logger.warning("Step %s guardrail violation: %s", step.step_id, e)
        except Exception as e:
            step.status = "failed"
            step.error = str(e)
            logger.error("Step %s failed: %s", step.step_id, e, exc_info=True)
        finally:
            step.duration_ms = int((time.monotonic() - start) * 1000)

    async def _execute_sql_step(
        self,
        step: PlanStep,
        resolved: ResolvedContext,
        ctx: RunContext,
        all_steps: list[PlanStep],
        backend: StorageBackend,
    ) -> None:
        schema = self._get_schema(step, resolved)

        sql = await self._generate_sql(step, resolved, ctx, all_steps, schema)
        step.result = StepResult(sql=sql)

        check_sql_safety(sql)

        validation = await self._validate_sql(sql, schema, backend)
        if not validation.is_valid:
            sql = await self._retry_sql_generation(
                step, resolved, ctx, all_steps, schema, validation.error_message or "校验失败"
            )
            step.result.sql = sql
            check_sql_safety(sql)

        ctx.record_sql_execution()
        result = await backend.execute_query(sql, schema)

        step.result.columns = result.columns
        step.result.rows = result.rows
        step.result.row_count = result.row_count
        step.result.execution_time_ms = result.execution_time_ms
        step.status = "completed"

        if result.row_count == 0:
            ctx.add_warning(f"步骤 {step.step_id} 查询结果为空")
        if result.row_count > 100_000:
            ctx.add_warning(f"步骤 {step.step_id} 返回 {result.row_count} 行，结果可能被截断")

    async def _generate_sql(
        self,
        step: PlanStep,
        resolved: ResolvedContext,
        ctx: RunContext,
        all_steps: list[PlanStep],
        schema: str,
    ) -> str:
        context = self._build_sql_context(step, resolved, all_steps, schema)
        messages = [
            {"role": "system", "content": SQL_GEN_SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ]

        resp = await self._llm.call_json(messages)
        ctx.record_llm_call(resp.tokens_in, resp.tokens_out)

        data = json.loads(resp.content)
        sql = data.get("sql", "").strip()
        if not sql:
            raise GuardrailViolation("sql_empty", "LLM 未生成有效 SQL")
        return sql

    async def _retry_sql_generation(
        self,
        step: PlanStep,
        resolved: ResolvedContext,
        ctx: RunContext,
        all_steps: list[PlanStep],
        schema: str,
        error: str,
    ) -> str:
        context = self._build_sql_context(step, resolved, all_steps, schema)
        messages = [
            {"role": "system", "content": SQL_GEN_SYSTEM_PROMPT},
            {"role": "user", "content": context},
            {"role": "assistant", "content": json.dumps({"sql": step.result.sql if step.result else ""})},
            {"role": "user", "content": f"上面的 SQL 校验失败: {error}\n请修正后重新输出。"},
        ]

        resp = await self._llm.call_json(messages)
        ctx.record_llm_call(resp.tokens_in, resp.tokens_out)

        data = json.loads(resp.content)
        sql = data.get("sql", "").strip()
        if not sql:
            raise GuardrailViolation("sql_empty", "SQL 重试后仍未生成有效 SQL")
        return sql

    async def _validate_sql(self, sql: str, schema: str, backend: StorageBackend) -> ValidationResult:
        try:
            tables = self._extract_table_names(sql)
            known_tables = await backend.get_tables(schema)
            known_names = {t.name.lower() for t in known_tables}

            for table in tables:
                if table.lower() not in known_names:
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"表 '{table}' 不存在于 schema '{schema}'。已知表: {sorted(known_names)}",
                    )

            result = await backend.validate_sql(sql, schema)
            return result
        except Exception as e:
            logger.warning("SQL validation error (non-fatal): %s", e)
            return ValidationResult(is_valid=True)

    def _extract_table_names(self, sql: str) -> list[str]:
        try:
            parsed = sqlglot.parse_one(sql)
            tables = []
            for table in parsed.find_all(sqlglot.exp.Table):
                name = table.name
                if name:
                    tables.append(name)
            return tables
        except Exception:
            return []

    def _get_schema(self, step: PlanStep, resolved: ResolvedContext) -> str:
        if step.params.schema_name:
            return step.params.schema_name
        if resolved.metrics:
            return resolved.metrics[0].source_schema
        return "main"

    def _build_sql_context(
        self,
        step: PlanStep,
        resolved: ResolvedContext,
        all_steps: list[PlanStep],
        schema: str,
    ) -> str:
        parts = [f"## 目标\n{step.params.purpose or step.description}"]

        parts.append(f"\n## Schema: {schema}")

        if resolved.metrics:
            parts.append("\n## 可用指标")
            for m in resolved.metrics:
                parts.append(f"- {m.canonical_name}: {m.calculation} FROM {m.source_table}")

        if resolved.dimensions:
            parts.append("\n## 可用维度")
            for d in resolved.dimensions:
                parts.append(f"- {d.canonical_name}: 列 {d.source_column} FROM {d.source_table}")

        if resolved.join_paths:
            parts.append("\n## Join 路径")
            for j in resolved.join_paths:
                parts.append(f"- {j.left_table} {j.join_type} JOIN {j.right_table} ON {j.join_condition}")

        if step.params.filters:
            parts.append(f"\n## 过滤条件")
            for f in step.params.filters:
                parts.append(f"- {f.dimension} {f.operator} {f.value}")

        if step.params.time_range:
            parts.append(f"\n## 时间范围: {step.params.time_range.description or step.params.time_range.preset}")

        if step.params.group_by:
            parts.append(f"\n## GROUP BY: {step.params.group_by}")

        prior_results = []
        for s in all_steps:
            if s.step_id == step.step_id:
                break
            if s.status == "completed" and s.result:
                summary = f"步骤 {s.step_id} ({s.description}): "
                if s.result.row_count > 0 and s.result.columns:
                    preview = s.result.rows[:3] if s.result.rows else []
                    summary += f"返回 {s.result.row_count} 行, 列={s.result.columns}, 前几行={preview}"
                else:
                    summary += "无数据"
                prior_results.append(summary)

        if prior_results:
            parts.append("\n## 前序步骤结果")
            parts.extend(prior_results)

        return "\n".join(parts)

import json
import logging

from app.schemas.task import AnalysisTask
from app.schemas.plan import PlanStep
from app.infra.llm import LLMClient
from app.core.harness import RunContext

logger = logging.getLogger(__name__)

SUMMARY_SYSTEM_PROMPT = """你是一个数据分析结论生成专家。基于查询步骤的结果，用简洁、准确的中文生成分析结论。

## 规则
1. 结论 1-5 句话，直接回答用户的分析问题。
2. 必须包含关键数字（来自查询结果），不要编造数据。
3. 如果有对比数据，指出变化方向和幅度。
4. 如果某些步骤失败了，在结论末尾注明。
5. 使用中文输出。
6. 只输出结论文本，不要加任何 JSON 包装或 markdown 格式。"""


class ResultInterpreter:
    """Generates natural language summary from analysis step results."""

    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    async def summarize(
        self,
        task: AnalysisTask,
        steps: list[PlanStep],
        ctx: RunContext,
    ) -> str:
        ctx.check_budget()

        context = self._build_summary_context(task, steps)
        messages = [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ]

        resp = await self._llm.call(messages, temperature=0.3)
        ctx.record_llm_call(resp.tokens_in, resp.tokens_out)

        return resp.content.strip()

    def _build_summary_context(self, task: AnalysisTask, steps: list[PlanStep]) -> str:
        parts = [
            f"## 用户问题\n{task.raw_input}",
            f"\n## 任务类型: {task.task_type}",
            f"## 目标指标: {task.target_metrics}",
        ]

        parts.append("\n## 各步骤执行结果")
        for step in steps:
            if step.action == "summarize_results":
                continue

            parts.append(f"\n### 步骤 {step.step_id}: {step.description}")
            parts.append(f"状态: {step.status}")

            if step.status == "completed" and step.result:
                if step.result.sql:
                    parts.append(f"SQL: {step.result.sql}")
                if step.result.columns and step.result.rows:
                    parts.append(f"列: {step.result.columns}")
                    rows_to_show = step.result.rows[:20]
                    parts.append(f"数据 (前 {len(rows_to_show)} 行):")
                    for row in rows_to_show:
                        parts.append(f"  {row}")
                    if step.result.row_count > 20:
                        parts.append(f"  ... 共 {step.result.row_count} 行")
                elif step.result.row_count == 0:
                    parts.append("查询结果为空")

            elif step.status == "failed":
                parts.append(f"错误: {step.error}")

        return "\n".join(parts)

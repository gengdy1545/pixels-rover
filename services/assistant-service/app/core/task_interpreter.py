import json
import logging

from app.schemas.task import AnalysisTask
from app.infra.llm import LLMClient
from app.core.harness import RunContext, OutputGuardrail

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个数据分析任务解析器。用户会用自然语言描述分析目标，你需要输出一个结构化的 JSON。

## 任务类型定义
- query: 简单查数（"本月 GMV 是多少"）
- compare: 对比分析（"本月 vs 上月 GMV"）
- diagnose: 归因诊断（"为什么 GMV 下降"）

## 输出 JSON 格式（严格遵守）
{
  "task_type": "query" | "compare" | "diagnose",
  "target_metrics": ["指标1", "指标2"],
  "time_range": {
    "preset": "this_month" | "last_month" | "last_7_days" | "last_30_days" | "this_quarter" | "this_year" | "ytd" | null,
    "start": "YYYY-MM-DD" | null,
    "end": "YYYY-MM-DD" | null,
    "description": "用户原文描述"
  },
  "filters": [
    {"dimension": "维度名", "operator": "=", "value": "值"}
  ],
  "comparison_baseline": { 同 time_range 格式 },
  "analysis_dimensions": ["dimension1", "dimension2"],
  "confidence": 0.0 到 1.0,
  "needs_clarification": false,
  "clarification_question": null
}

## 规则
1. 从用户输入中提取所有可识别的分析要素，不要编造用户没提到的内容。
2. 如果用户没有提到时间范围，time_range 设为 null。
3. 如果用户提到对比（"vs""同比""环比"），设置 comparison_baseline。
4. 对于 diagnose 类型，如果用户没有指定对比基线，默认 comparison_baseline 为 {"preset": "last_month"}。
5. confidence 反映你对解析结果的把握：明确输入给 0.9+，模糊输入给 0.5-0.7。
6. 如果置信度 < 0.5，设置 needs_clarification=true 并提供 clarification_question。
7. 指标名保留用户原文（如"成交额""订单量"），不要翻译成英文或 SQL 列名。
8. 必须输出合法 JSON，不要添加注释或额外文本。"""

FEW_SHOT_EXAMPLES = [
    {
        "input": "本月北美 GMV 是多少",
        "output": {
            "task_type": "query",
            "target_metrics": ["GMV"],
            "time_range": {"preset": "this_month", "description": "本月"},
            "filters": [{"dimension": "地区", "operator": "=", "value": "北美"}],
            "comparison_baseline": None,
            "analysis_dimensions": [],
            "confidence": 0.95,
            "needs_clarification": False,
            "clarification_question": None,
        },
    },
    {
        "input": "各区域本月 vs 上月 GMV 对比",
        "output": {
            "task_type": "compare",
            "target_metrics": ["GMV"],
            "time_range": {"preset": "this_month", "description": "本月"},
            "filters": [],
            "comparison_baseline": {"preset": "last_month", "description": "上月"},
            "analysis_dimensions": ["区域"],
            "confidence": 0.9,
            "needs_clarification": False,
            "clarification_question": None,
        },
    },
    {
        "input": "为什么本月 GMV 下降了",
        "output": {
            "task_type": "diagnose",
            "target_metrics": ["GMV"],
            "time_range": {"preset": "this_month", "description": "本月"},
            "filters": [],
            "comparison_baseline": {"preset": "last_month", "description": "上月"},
            "analysis_dimensions": [],
            "confidence": 0.9,
            "needs_clarification": False,
            "clarification_question": None,
        },
    },
]


class TaskInterpreter:
    def __init__(self, llm_client: LLMClient, output_guardrail: OutputGuardrail):
        self._llm = llm_client
        self._guardrail = output_guardrail

    async def interpret(
        self,
        question: str,
        ctx: RunContext,
        available_schemas: list[str] | None = None,
    ) -> AnalysisTask:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        for example in FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": example["input"]})
            messages.append({
                "role": "assistant",
                "content": json.dumps(example["output"], ensure_ascii=False),
            })

        user_msg = question
        if available_schemas:
            user_msg = f"可用数据源 schema: {available_schemas}\n\n用户输入: {question}"

        messages.append({"role": "user", "content": user_msg})

        resp = await self._llm.call_json(messages)
        ctx.record_llm_call(resp.tokens_in, resp.tokens_out)

        def retry_fn(error: str) -> list[dict]:
            return messages + [
                {"role": "assistant", "content": resp.content},
                {
                    "role": "user",
                    "content": f"你的输出解析失败: {error}\n请重新输出合法的 JSON。",
                },
            ]

        task = await self._guardrail.parse_llm_output(
            resp.content, AnalysisTask, ctx, retry_prompt_fn=retry_fn
        )
        task.raw_input = question
        return task

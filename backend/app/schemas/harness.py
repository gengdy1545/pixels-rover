from pydantic import BaseModel


class TaskEnvelope(BaseModel):
    max_steps: int = 10
    max_llm_calls: int = 20
    max_wall_time_sec: int = 180
    max_sql_executions: int = 5


class BudgetExhausted(Exception):
    def __init__(self, dimension: str, current: float, limit: float):
        self.dimension = dimension
        self.current = current
        self.limit = limit
        super().__init__(f"预算耗尽: {dimension} ({current:.1f} >= {limit:.1f})")


class GuardrailViolation(Exception):
    def __init__(self, check_name: str, detail: str):
        self.check_name = check_name
        self.detail = detail
        super().__init__(f"护栏拦截 [{check_name}]: {detail}")


class PlanValidationError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"计划校验失败: {reason}")

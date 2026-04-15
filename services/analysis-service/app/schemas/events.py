from enum import Enum


class SSEEventType(str, Enum):
    STATUS_CHANGE = "status_change"
    TASK_PARSED = "task_parsed"
    CLARIFICATION = "clarification"
    PLAN_CREATED = "plan_created"
    STEP_STARTED = "step_started"
    STEP_SQL = "step_sql"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    SUMMARY_READY = "summary_ready"
    ANALYSIS_DONE = "analysis_done"
    WARNING = "warning"
    ERROR = "error"

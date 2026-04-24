from typing import Any, Protocol


class Planner(Protocol):
    async def plan(self, *args: Any, **kwargs: Any) -> Any:
        ...


class StepExecutor(Protocol):
    async def execute_step(self, *args: Any, **kwargs: Any) -> Any:
        ...


class ResultInterpreter(Protocol):
    async def interpret(self, *args: Any, **kwargs: Any) -> Any:
        ...


class TaskInterpreter(Protocol):
    async def interpret(self, *args: Any, **kwargs: Any) -> Any:
        ...

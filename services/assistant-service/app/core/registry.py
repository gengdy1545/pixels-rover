"""Factory registry for the four `app/core/` pluggable seams.

architecture-tasks §Task 16 acceptance clause 2 reads:

    Replacing `Planner` with a stub implementation only requires
    swapping one symbol in a registry, no edits inside `core/`.

This module is that registry. It holds a name-keyed table of factory
callables for each of the four protocols declared in
:mod:`app.core.interfaces`:

    - ``planner``             → :class:`app.core.interfaces.Planner`
    - ``step_executor``       → :class:`app.core.interfaces.StepExecutor`
    - ``result_interpreter``  → :class:`app.core.interfaces.ResultInterpreter`
    - ``task_interpreter``    → :class:`app.core.interfaces.TaskInterpreter`

``app.dependencies`` consults this registry when assembling the
``AnalysisService``; swapping in a stub for a test or a feature flag
is now a single :func:`register` call at startup (or in a pytest
fixture) and NEVER requires touching any file under ``app/core/``.
This keeps the seam visible in the tree rather than hidden inside an
``if os.environ.get(...)`` branch in the actual planner file — which
was the exact anti-pattern Finding #11 flagged: "pluggable backend"
story reads better than the structure does.

The registry is deliberately minimal (no DAG, no lifecycle hooks, no
async resolution). Anything fancier belongs one layer up, in
``app.dependencies``. The only guarantee we owe here is:

    1. Each seam name resolves to a single factory.
    2. Replacing the factory later overwrites the mapping, without
       mutating the previously returned instance.
    3. Seam names are frozen (see :data:`SEAM_NAMES`) so a typo in a
       :func:`register` call raises immediately instead of silently
       creating a dead entry.

Test harnesses that need to swap in a stub should do so through this
registry + reset after the test:

    from app.core.registry import register, reset_defaults

    register("planner", lambda llm, guard: StubPlanner())
    try:
        ...
    finally:
        reset_defaults()
"""
from __future__ import annotations

from typing import Any, Callable, Final

from app.core.interfaces import (
    Planner,
    ResultInterpreter,
    StepExecutor,
    TaskInterpreter,
)

# The four seams the registry accepts. Declared as a frozenset (not a
# plain tuple) because lookup is hot and we want early rejection for
# typos like `register("plannner", ...)`.
SEAM_NAMES: Final[frozenset[str]] = frozenset(
    {"planner", "step_executor", "result_interpreter", "task_interpreter"}
)

# Factory callables are intentionally typed ``Callable[..., Any]`` —
# each seam's factory has its own signature (planner needs an LLM +
# OutputGuardrail; result_interpreter needs only an LLM; etc.) and
# pinning them here would duplicate what the Protocols in
# ``app.core.interfaces`` already express. The registry's contract is
# "give me a factory, I'll store it under the seam name"; the caller
# in ``app.dependencies`` is what knows the concrete signature.
_Factory = Callable[..., Any]


def _default_planner_factory(llm_client, output_guardrail) -> Planner:
    # Imported lazily so ``app.core.registry`` itself does not pull in
    # the LLM client graph at import time — that keeps the registry
    # usable from lightweight test harnesses that want to override a
    # seam BEFORE the default factory's imports get evaluated.
    from app.core.planner import Planner as _Planner
    return _Planner(llm_client, output_guardrail)


def _default_step_executor_factory(llm_client) -> StepExecutor:
    from app.core.step_executor import StepExecutor as _StepExecutor
    return _StepExecutor(llm_client)


def _default_result_interpreter_factory(llm_client) -> ResultInterpreter:
    from app.core.result_interpreter import ResultInterpreter as _ResultInterpreter
    return _ResultInterpreter(llm_client)


def _default_task_interpreter_factory(llm_client, output_guardrail) -> TaskInterpreter:
    from app.core.task_interpreter import TaskInterpreter as _TaskInterpreter
    return _TaskInterpreter(llm_client, output_guardrail)


_DEFAULT_FACTORIES: Final[dict[str, _Factory]] = {
    "planner": _default_planner_factory,
    "step_executor": _default_step_executor_factory,
    "result_interpreter": _default_result_interpreter_factory,
    "task_interpreter": _default_task_interpreter_factory,
}

# Live factory table. Starts as a copy of the defaults; ``register``
# mutates it; ``reset_defaults`` restores it. The defaults themselves
# are a MappingProxy-free frozen dict (treated as immutable by
# convention — the module never writes to it after import).
_factories: dict[str, _Factory] = dict(_DEFAULT_FACTORIES)


def register(seam: str, factory: _Factory) -> None:
    """Override the factory for ``seam``.

    Raises :class:`KeyError` if ``seam`` is not one of the four
    declared names in :data:`SEAM_NAMES`. This is a guardrail against
    typos that would otherwise silently create a dead seam name
    nobody ever resolves.
    """
    if seam not in SEAM_NAMES:
        raise KeyError(
            f"Unknown core seam {seam!r}; valid seams are "
            f"{sorted(SEAM_NAMES)!r}. Extending the seam set requires "
            f"adding a matching Protocol in app/core/interfaces.py AND "
            f"relaxing the core-registry-swap-seam-present contract "
            f"in scripts/check-contracts.py."
        )
    _factories[seam] = factory


def get(seam: str) -> _Factory:
    """Return the currently-registered factory for ``seam``.

    Callers pass the factory's own arguments in positionally —
    :mod:`app.dependencies` is the sole production caller and knows
    each seam's concrete signature.
    """
    if seam not in SEAM_NAMES:
        raise KeyError(
            f"Unknown core seam {seam!r}; valid seams are "
            f"{sorted(SEAM_NAMES)!r}."
        )
    return _factories[seam]


def reset_defaults() -> None:
    """Restore all seams to their default factories.

    Intended for pytest fixtures that :func:`register` a stub: calling
    ``reset_defaults`` in ``finally`` (or an autouse fixture's
    teardown) keeps the in-process registry state test-isolated.
    """
    _factories.clear()
    _factories.update(_DEFAULT_FACTORIES)

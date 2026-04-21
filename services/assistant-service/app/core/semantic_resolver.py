import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.semantic import SemanticMetric, SemanticDimension, SemanticSynonym, SemanticJoinPath
from app.schemas.semantic import ResolvedMetric, ResolvedDimension, JoinPath, ResolvedContext
from app.schemas.task import AnalysisTask

logger = logging.getLogger(__name__)


class SemanticResolver:
    """Resolves user terms to database entities via exact + synonym matching."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def resolve(self, task: AnalysisTask) -> ResolvedContext:
        metrics: list[ResolvedMetric] = []
        dimensions: list[ResolvedDimension] = []
        unresolved: list[str] = []
        warnings: list[str] = []

        for metric_name in task.target_metrics:
            resolved = await self._resolve_metric(metric_name)
            if resolved:
                metrics.append(resolved)
            else:
                unresolved.append(metric_name)

        dim_names = [f.dimension for f in task.filters] + task.analysis_dimensions
        for dim_name in dim_names:
            resolved_dim = await self._resolve_dimension(dim_name)
            if resolved_dim:
                dimensions.append(resolved_dim)
            else:
                warnings.append(f"维度 '{dim_name}' 无法解析，将由 SQL 生成 LLM 处理")

        join_paths = await self._find_join_paths(metrics, dimensions)

        return ResolvedContext(
            metrics=metrics,
            dimensions=dimensions,
            join_paths=join_paths,
            unresolved=unresolved,
            warnings=warnings,
        )

    async def _resolve_metric(self, user_term: str) -> ResolvedMetric | None:
        term_lower = user_term.lower().strip()

        result = await self._db.execute(
            select(SemanticMetric).where(
                SemanticMetric.name == term_lower
            )
        )
        metric = result.scalar_one_or_none()

        if not metric:
            result = await self._db.execute(
                select(SemanticMetric).where(
                    SemanticMetric.display_name == user_term
                )
            )
            metric = result.scalar_one_or_none()

        if not metric:
            synonym = await self._db.execute(
                select(SemanticSynonym).where(
                    SemanticSynonym.term == term_lower,
                    SemanticSynonym.entity_type == "metric",
                )
            )
            syn = synonym.scalar_one_or_none()
            if syn:
                result = await self._db.execute(
                    select(SemanticMetric).where(SemanticMetric.name == syn.canonical_name)
                )
                metric = result.scalar_one_or_none()

        if not metric:
            return None

        return ResolvedMetric(
            user_term=user_term,
            canonical_name=metric.name,
            display_name=metric.display_name or metric.name,
            calculation=metric.calculation,
            source_table=metric.source_table,
            source_schema=metric.source_schema,
            backend_id=metric.backend_id,
        )

    async def _resolve_dimension(self, user_term: str) -> ResolvedDimension | None:
        term_lower = user_term.lower().strip()

        result = await self._db.execute(
            select(SemanticDimension).where(SemanticDimension.name == term_lower)
        )
        dim = result.scalar_one_or_none()

        if not dim:
            result = await self._db.execute(
                select(SemanticDimension).where(SemanticDimension.display_name == user_term)
            )
            dim = result.scalar_one_or_none()

        if not dim:
            synonym = await self._db.execute(
                select(SemanticSynonym).where(
                    SemanticSynonym.term == term_lower,
                    SemanticSynonym.entity_type == "dimension",
                )
            )
            syn = synonym.scalar_one_or_none()
            if syn:
                result = await self._db.execute(
                    select(SemanticDimension).where(SemanticDimension.name == syn.canonical_name)
                )
                dim = result.scalar_one_or_none()

        if not dim:
            return None

        return ResolvedDimension(
            user_term=user_term,
            canonical_name=dim.name,
            display_name=dim.display_name or dim.name,
            source_column=dim.source_column,
            source_table=dim.source_table,
            source_schema=dim.source_schema,
            backend_id=dim.backend_id,
        )

    async def _find_join_paths(
        self,
        metrics: list[ResolvedMetric],
        dimensions: list[ResolvedDimension],
    ) -> list[JoinPath]:
        tables = set()
        for m in metrics:
            tables.add(m.source_table)
        for d in dimensions:
            tables.add(d.source_table)

        if len(tables) <= 1:
            return []

        join_paths: list[JoinPath] = []
        table_list = list(tables)
        for i in range(len(table_list)):
            for j in range(i + 1, len(table_list)):
                result = await self._db.execute(
                    select(SemanticJoinPath).where(
                        SemanticJoinPath.left_table == table_list[i],
                        SemanticJoinPath.right_table == table_list[j],
                    )
                )
                path = result.scalar_one_or_none()
                if not path:
                    result = await self._db.execute(
                        select(SemanticJoinPath).where(
                            SemanticJoinPath.left_table == table_list[j],
                            SemanticJoinPath.right_table == table_list[i],
                        )
                    )
                    path = result.scalar_one_or_none()

                if path:
                    join_paths.append(JoinPath(
                        left_table=path.left_table,
                        right_table=path.right_table,
                        join_condition=path.join_condition,
                        join_type=path.join_type or "INNER",
                    ))

        return join_paths

    async def list_available_metrics(self) -> list[ResolvedMetric]:
        result = await self._db.execute(select(SemanticMetric))
        all_metrics = result.scalars().all()
        return [
            ResolvedMetric(
                user_term=m.name,
                canonical_name=m.name,
                display_name=m.display_name or m.name,
                calculation=m.calculation,
                source_table=m.source_table,
                source_schema=m.source_schema,
                backend_id=m.backend_id,
            )
            for m in all_metrics
        ]

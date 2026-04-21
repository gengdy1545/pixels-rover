import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_response import api_success
from app.database import get_db
from app.auth import get_current_user
from app.models.semantic import SemanticMetric, SemanticDimension, SemanticSynonym

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/semantic", tags=["semantic"], dependencies=[Depends(get_current_user)])


class MetricCreate(BaseModel):
    name: str
    display_name: str | None = None
    description: str | None = None
    calculation: str
    source_table: str
    source_schema: str
    backend_id: str
    data_type: str | None = None


class DimensionCreate(BaseModel):
    name: str
    display_name: str | None = None
    source_column: str
    source_table: str
    source_schema: str
    backend_id: str


class SynonymCreate(BaseModel):
    term: str
    canonical_name: str
    entity_type: str


@router.get("/metrics")
async def list_metrics(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SemanticMetric))
    metrics = result.scalars().all()
    return api_success([
        {
            "id": m.id, "name": m.name, "display_name": m.display_name,
            "description": m.description, "calculation": m.calculation,
            "source_table": m.source_table, "source_schema": m.source_schema,
            "backend_id": m.backend_id, "data_type": m.data_type,
        }
        for m in metrics
    ])


@router.post("/metrics")
async def create_metric(data: MetricCreate, db: AsyncSession = Depends(get_db)):
    metric = SemanticMetric(**data.model_dump())
    db.add(metric)
    await db.commit()
    await db.refresh(metric)
    return api_success({"id": metric.id, "name": metric.name})


@router.get("/dimensions")
async def list_dimensions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SemanticDimension))
    dims = result.scalars().all()
    return api_success([
        {
            "id": d.id, "name": d.name, "display_name": d.display_name,
            "source_column": d.source_column, "source_table": d.source_table,
            "source_schema": d.source_schema, "backend_id": d.backend_id,
        }
        for d in dims
    ])


@router.post("/dimensions")
async def create_dimension(data: DimensionCreate, db: AsyncSession = Depends(get_db)):
    dim = SemanticDimension(**data.model_dump())
    db.add(dim)
    await db.commit()
    await db.refresh(dim)
    return api_success({"id": dim.id, "name": dim.name})


@router.get("/synonyms")
async def list_synonyms(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SemanticSynonym))
    syns = result.scalars().all()
    return api_success([
        {"id": s.id, "term": s.term, "canonical_name": s.canonical_name, "entity_type": s.entity_type}
        for s in syns
    ])


@router.post("/synonyms")
async def create_synonym(data: SynonymCreate, db: AsyncSession = Depends(get_db)):
    syn = SemanticSynonym(**data.model_dump())
    db.add(syn)
    await db.commit()
    await db.refresh(syn)
    return api_success({"id": syn.id, "term": syn.term})

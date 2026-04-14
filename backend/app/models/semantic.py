from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from app.database import Base


class SemanticMetric(Base):
    __tablename__ = "semantic_metrics"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text)
    calculation: Mapped[str] = mapped_column(Text)
    source_table: Mapped[str] = mapped_column(String(256))
    source_schema: Mapped[str] = mapped_column(String(128))
    backend_id: Mapped[str] = mapped_column(String(128))
    data_type: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SemanticDimension(Base):
    __tablename__ = "semantic_dimensions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(256))
    source_column: Mapped[str] = mapped_column(String(256))
    source_table: Mapped[str] = mapped_column(String(256))
    source_schema: Mapped[str] = mapped_column(String(128))
    backend_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SemanticSynonym(Base):
    __tablename__ = "semantic_synonyms"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    term: Mapped[str] = mapped_column(String(256), index=True)
    canonical_name: Mapped[str] = mapped_column(String(256))
    entity_type: Mapped[str] = mapped_column(String(32))


class SemanticJoinPath(Base):
    __tablename__ = "semantic_join_paths"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    left_table: Mapped[str] = mapped_column(String(256))
    right_table: Mapped[str] = mapped_column(String(256))
    join_condition: Mapped[str] = mapped_column(Text)
    join_type: Mapped[str] = mapped_column(String(16), default="INNER")
    source_schema: Mapped[str] = mapped_column(String(128))
    backend_id: Mapped[str] = mapped_column(String(128))

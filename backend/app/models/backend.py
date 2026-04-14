from sqlalchemy import String, Boolean, JSON, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from app.database import Base


class StorageBackendRecord(Base):
    __tablename__ = "storage_backends"

    backend_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    backend_type: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str | None] = mapped_column(String(256))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SchemaBackendMapping(Base):
    __tablename__ = "schema_backend_mapping"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    schema_name: Mapped[str] = mapped_column(String(128), index=True)
    backend_id: Mapped[str] = mapped_column(String(128))

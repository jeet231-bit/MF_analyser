"""ORM tables. Import this module before ``init_db`` so the tables register on ``Base``."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.storage.db import Base


class WorkbookVersion(Base):
    """One uploaded workbook file. Versions are immutable once parsed."""

    __tablename__ = "workbook_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="parsing")
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parse_seconds: Mapped[float | None] = mapped_column(nullable=True)
    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="RawWorkbook JSON without per-sheet cells"
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    activation_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    sheets: Mapped[list[RawSheetBlob]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="RawSheetBlob.sheet_index"
    )
    logic_models: Mapped[list[LogicModelRow]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="LogicModelRow.created_at"
    )
    runs: Mapped[list[Run]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="Run.created_at"
    )


class RawSheetBlob(Base):
    """Gzipped RawSheet JSON, one row per sheet, so a sheet can be loaded without the rest."""

    __tablename__ = "raw_sheets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("workbook_versions.id", ondelete="CASCADE"), index=True
    )
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sheet_index: Mapped[int] = mapped_column(Integer, nullable=False)
    cell_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    formula_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    version: Mapped[WorkbookVersion] = relationship(back_populates="sheets")


class LogicModelRow(Base):
    """A WorkbookLogicModel derived from a version (gzipped JSON). Re-interpreting replaces it."""

    __tablename__ = "logic_models"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("workbook_versions.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    peak_mb: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    version: Mapped[WorkbookVersion] = relationship(back_populates="logic_models")


class SheetRoleOverride(Base):
    """User-set sheet role for one version; applied on top of heuristics and config."""

    __tablename__ = "sheet_role_overrides"
    __table_args__ = (UniqueConstraint("version_id", "sheet_name", name="uq_role_override"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("workbook_versions.id", ondelete="CASCADE"), index=True
    )
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Run(Base):
    """One engine run: model version + overrides -> computed values (per-sheet blobs)."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("workbook_versions.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # full | incremental
    parent_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    overrides_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    version: Mapped[WorkbookVersion] = relationship(back_populates="runs")
    sheets: Mapped[list[RunSheetValues]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ValidationRow(Base):
    """A ValidationReport for one version (gzipped JSON); the latest one gates activation."""

    __tablename__ = "validations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("workbook_versions.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class RunSheetValues(Base):
    """Gzipped columnar JSON of a run's formula-cell values for one sheet."""

    __tablename__ = "run_values"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    cell_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    run: Mapped[Run] = relationship(back_populates="sheets")

"""ORM tables. Import this module before ``init_db`` so the tables register on ``Base``."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text
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

    sheets: Mapped[list[RawSheetBlob]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="RawSheetBlob.sheet_index"
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

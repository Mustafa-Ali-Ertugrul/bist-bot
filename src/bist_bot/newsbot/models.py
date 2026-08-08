"""Haber botu SQLAlchemy ORM modelleri."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from bist_bot.db.database import Base


class NewsbotSource(Base):
    __tablename__ = "newsbot_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    source_type: Mapped[str] = mapped_column(String, default="news")
    trust_score: Mapped[int] = mapped_column(Integer, default=70)
    scrape_interval_seconds: Mapped[int] = mapped_column(Integer, default=120)
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class NewsbotArticle(Base):
    __tablename__ = "newsbot_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("newsbot_sources.id"), nullable=False
    )
    url: Mapped[str | None] = mapped_column(String)
    canonical_url: Mapped[str | None] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String)
    content: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    language: Mapped[str] = mapped_column(String, default="tr")
    content_hash: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    is_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    original_article_id: Mapped[int | None] = mapped_column(Integer)
    trust_score: Mapped[int | None] = mapped_column(Integer)
    raw_payload: Mapped[str | None] = mapped_column(Text)

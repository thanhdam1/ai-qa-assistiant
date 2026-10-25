from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text)
    acceptance_criteria: Mapped[list] = mapped_column(JSON, default=list)
    business_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    dependencies: Mapped[list] = mapped_column(JSON, default=list)
    language: Mapped[str] = mapped_column(String(16), default="auto")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    reviews: Mapped[list[RequirementReview]] = relationship(
        back_populates="story",
        cascade="all, delete-orphan",
        order_by="RequirementReview.created_at.desc()",
    )
    test_case_sets: Mapped[list[TestCaseSet]] = relationship(
        back_populates="story",
        cascade="all, delete-orphan",
        order_by="TestCaseSet.created_at.desc()",
    )


class RequirementReview(Base):
    __tablename__ = "requirement_reviews"
    __table_args__ = (
        UniqueConstraint("story_id", "idempotency_key", name="uq_review_story_idempotency"),
        Index("ix_review_story_version", "story_id", "story_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"))
    story_version: Mapped[int] = mapped_column(Integer)
    ai_original: Mapped[dict] = mapped_column(JSON)
    content: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    model_name: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(32))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    story: Mapped[Story] = relationship(back_populates="reviews")
    test_case_sets: Mapped[list[TestCaseSet]] = relationship(back_populates="review")


class TestCaseSet(Base):
    __tablename__ = "test_case_sets"
    __table_args__ = (
        UniqueConstraint("story_id", "idempotency_key", name="uq_testset_story_idempotency"),
        Index("ix_testset_story_version", "story_id", "story_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"))
    review_id: Mapped[str] = mapped_column(
        ForeignKey("requirement_reviews.id", ondelete="RESTRICT")
    )
    story_version: Mapped[int] = mapped_column(Integer)
    ai_original: Mapped[dict] = mapped_column(JSON)
    content: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    model_name: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(32))
    generation_info: Mapped[dict] = mapped_column(JSON, default=dict)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    story: Mapped[Story] = relationship(back_populates="test_case_sets")
    review: Mapped[RequirementReview] = relationship(back_populates="test_case_sets")

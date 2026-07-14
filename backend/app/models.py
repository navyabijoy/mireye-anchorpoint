import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import String, Float, Integer, Boolean, DateTime, ForeignKey, JSON, Uuid, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


def _utcnow() -> datetime:
    """Returns a timezone-aware UTC datetime. Used as a column default."""
    return datetime.now(timezone.utc)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Valid statuses: pending | processing_demand | demand_completed | processing_scoring | completed | failed
    status: Mapped[str] = mapped_column(String, default="pending")
    hub_count: Mapped[int] = mapped_column(Integer, default=1)

    # User-defined scoring weights for Stage 2
    transport_weight: Mapped[float] = mapped_column(Float, default=0.2)
    power_weight: Mapped[float] = mapped_column(Float, default=0.2)
    buildability_weight: Mapped[float] = mapped_column(Float, default=0.2)
    context_weight: Mapped[float] = mapped_column(Float, default=0.2)
    hazard_weight: Mapped[float] = mapped_column(Float, default=0.2)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    demand_points: Mapped[List["DemandPoint"]] = relationship(
        "DemandPoint", back_populates="run", cascade="all, delete-orphan"
    )
    regions: Mapped[List["CandidateRegion"]] = relationship(
        "CandidateRegion", back_populates="run", cascade="all, delete-orphan"
    )


class DemandPoint(Base):
    __tablename__ = "demand_points"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("runs.id"), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    zip_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    order_count: Mapped[int] = mapped_column(Integer, default=1)
    revenue: Mapped[float] = mapped_column(Float, default=0.0)
    weight: Mapped[float] = mapped_column(Float, default=1.0)

    run: Mapped["Run"] = relationship("Run", back_populates="demand_points")


class CandidateRegion(Base):
    __tablename__ = "candidate_regions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("runs.id"), nullable=False)
    centroid_lat: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_lng: Mapped[float] = mapped_column(Float, nullable=False)
    radius_km: Mapped[float] = mapped_column(Float, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)

    run: Mapped["Run"] = relationship("Run", back_populates="regions")
    sites: Mapped[List["CandidateSite"]] = relationship(
        "CandidateSite", back_populates="region", cascade="all, delete-orphan"
    )


class CandidateSite(Base):
    __tablename__ = "candidate_sites"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    region_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("candidate_regions.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String, nullable=False)  # "synthetic", "LoopNet", etc.
    parcel_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    region: Mapped["CandidateRegion"] = relationship("CandidateRegion", back_populates="sites")
    scores: Mapped[List["SiteScore"]] = relationship(
        "SiteScore", back_populates="site", cascade="all, delete-orphan"
    )


class FieldValue(Base):
    __tablename__ = "field_values"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Precision level depends on field type — see ScoringService.get_cache_key
    coordinate_hash: Mapped[str] = mapped_column(String, index=True)
    field_name: Mapped[str] = mapped_column(String, index=True)
    value_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    confidence: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    ttl_seconds: Mapped[int] = mapped_column(Integer, default=86400)

    # Composite index speeds up the primary lookup pattern: WHERE coordinate_hash=? AND field_name=?
    __table_args__ = (
        Index("ix_field_values_coord_field", "coordinate_hash", "field_name"),
    )


class PartialFailure(Base):
    __tablename__ = "partial_failures"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    coordinate_hash: Mapped[str] = mapped_column(String, index=True)
    field_name: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    error: Mapped[str] = mapped_column(String, nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Composite index speeds up the primary lookup pattern: WHERE coordinate_hash=? AND field_name=?
    __table_args__ = (
        Index("ix_partial_failures_coord_field", "coordinate_hash", "field_name"),
    )


class SiteScore(Base):
    __tablename__ = "site_scores"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("candidate_sites.id"), nullable=False)
    dimension_scores_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Null when below the 50% data completeness floor
    composite_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    data_completeness_pct: Mapped[float] = mapped_column(Float, default=100.0)
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    scoring_version: Mapped[str] = mapped_column(String, default="v1")

    site: Mapped["CandidateSite"] = relationship("CandidateSite", back_populates="scores")

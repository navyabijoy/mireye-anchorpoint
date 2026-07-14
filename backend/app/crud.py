from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from app import models, schemas
import uuid
from typing import List, Optional, Dict, Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_run(db: AsyncSession, run_in: schemas.RunCreate) -> models.Run:
    db_run = models.Run(
        name=run_in.name,
        hub_count=run_in.hub_count,
        transport_weight=run_in.transport_weight,
        power_weight=run_in.power_weight,
        buildability_weight=run_in.buildability_weight,
        context_weight=run_in.context_weight,
        hazard_weight=run_in.hazard_weight,
        status="pending",
    )
    db.add(db_run)
    await db.flush()
    return db_run


async def get_run(db: AsyncSession, run_id: uuid.UUID) -> Optional[models.Run]:
    result = await db.execute(
        select(models.Run)
        .where(models.Run.id == run_id)
        .options(selectinload(models.Run.regions))
    )
    return result.scalar_one_or_none()


async def get_runs(db: AsyncSession, limit: int = 20) -> List[models.Run]:
    result = await db.execute(
        select(models.Run)
        .options(selectinload(models.Run.regions))
        .order_by(models.Run.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def add_demand_points(
    db: AsyncSession,
    run_id: uuid.UUID,
    points: List[Dict[str, Any]],
) -> None:
    """Batch-inserts demand points for a run in a single operation."""
    db.add_all([
        models.DemandPoint(
            run_id=run_id,
            lat=p["lat"],
            lng=p["lng"],
            zip_code=p.get("zip_code"),
            order_count=p.get("order_count", 1),
            revenue=p.get("revenue", 0.0),
            weight=p.get("weight", 1.0),
        )
        for p in points
    ])
    await db.flush()


async def add_regions(
    db: AsyncSession,
    run_id: uuid.UUID,
    regions: List[Dict[str, Any]],
) -> List[models.CandidateRegion]:
    db_regions = [
        models.CandidateRegion(
            run_id=run_id,
            centroid_lat=r["lat"],
            centroid_lng=r["lng"],
            radius_km=r["radius_km"],
            name=r["name"],
        )
        for r in regions
    ]
    db.add_all(db_regions)
    await db.flush()
    return db_regions


async def add_sites(
    db: AsyncSession,
    region_id: uuid.UUID,
    sites: List[Dict[str, Any]],
) -> List[models.CandidateSite]:
    """Batch-inserts candidate sites for a region in a single operation."""
    db_sites = [
        models.CandidateSite(
            id=s["id"],
            region_id=region_id,
            name=s["name"],
            lat=s["lat"],
            lng=s["lng"],
            is_synthetic=s["is_synthetic"],
            source=s["source"],
            parcel_ref=s.get("parcel_ref"),
        )
        for s in sites
    ]
    db.add_all(db_sites)
    await db.flush()
    return db_sites


async def get_run_regions(db: AsyncSession, run_id: uuid.UUID) -> List[models.CandidateRegion]:
    result = await db.execute(
        select(models.CandidateRegion).where(models.CandidateRegion.run_id == run_id)
    )
    return list(result.scalars().all())


async def get_region_sites(db: AsyncSession, region_id: uuid.UUID) -> List[models.CandidateSite]:
    result = await db.execute(
        select(models.CandidateSite)
        .where(models.CandidateSite.region_id == region_id)
        .options(selectinload(models.CandidateSite.scores))
    )
    return list(result.scalars().all())


async def get_site(db: AsyncSession, site_id: uuid.UUID) -> Optional[models.CandidateSite]:
    result = await db.execute(
        select(models.CandidateSite).where(models.CandidateSite.id == site_id)
    )
    return result.scalar_one_or_none()


async def save_site_score(
    db: AsyncSession,
    site_id: uuid.UUID,
    dimension_scores: Dict[str, float],
    composite_score: Optional[float],
    completeness: float,
) -> models.SiteScore:
    # Replace existing score — each site has at most one active score at a time
    await db.execute(delete(models.SiteScore).where(models.SiteScore.site_id == site_id))

    db_score = models.SiteScore(
        site_id=site_id,
        dimension_scores_json=dimension_scores,
        composite_score=composite_score,
        data_completeness_pct=completeness,
        scored_at=_utcnow(),
        scoring_version="v1",
    )
    db.add(db_score)
    await db.flush()
    return db_score

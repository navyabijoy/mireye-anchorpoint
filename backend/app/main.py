import uuid
import logging
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, Depends, UploadFile, File, Form, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import engine, Base, get_db, async_session_maker, set_wal_mode
from app.config import settings
from app import crud, schemas, models
from app.services.ingestion import IngestionService
from app.services.demand import DemandModelingService
from app.services.sourcing import CandidateSourcingService
from app.services.scoring import ScoringService
from app.services.ranking import ScoringRankingEngine
from app.mireye import MireyeClient, MIREYE_FIELDS, FIELD_DIMENSIONS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: auto-create tables and enable WAL mode for SQLite concurrency
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await set_wal_mode()
    logger.info("Database tables initialized.")
    yield
    # Shutdown: nothing to clean up currently


app = FastAPI(
    title="Anchorpoint API",
    description="Warehouse network siting tool backend built on Mireye Earth",
    version="1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, run_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.setdefault(run_id, []).append(websocket)
        logger.info(f"WebSocket client connected to run {run_id}")

    def disconnect(self, run_id: str, websocket: WebSocket):
        connections = self.active_connections.get(run_id, [])
        if websocket in connections:
            connections.remove(websocket)
        if not connections:
            self.active_connections.pop(run_id, None)
        logger.info(f"WebSocket client disconnected from run {run_id}")

    async def broadcast(self, run_id: str, message: dict):
        """
        Broadcasts a message to all active WebSocket subscribers for a run.
        Automatically removes stale connections that fail to send.
        """
        connections = self.active_connections.get(run_id, [])
        if not connections:
            return

        stale_connections: List[WebSocket] = []
        for connection in list(connections):  # Iterate a copy so we can mutate during loop
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.debug(f"Stale WebSocket detected for run {run_id}, removing: {e}")
                stale_connections.append(connection)

        # Evict all connections that failed to send
        for stale in stale_connections:
            self.disconnect(run_id, stale)


ws_manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Background task: Stage 2 site scoring
# ---------------------------------------------------------------------------

async def run_scoring_in_background(run_id: uuid.UUID, region_id: uuid.UUID, weights: dict):
    """
    Fetches Mireye fields for all sites in a region, scores them, and persists results.
    Broadcasts live progress updates over WebSocket throughout.
    """
    async with async_session_maker() as db:
        try:
            db_run = await crud.get_run(db, run_id)
            if not db_run:
                return

            db_run.status = "processing_scoring"
            await db.commit()

            await ws_manager.broadcast(str(run_id), {
                "type": "status",
                "status": "processing_scoring",
                "message": "Initiating Stage 2 site scoring...",
            })

            mireye_client = MireyeClient()

            async def progress_cb(site_id: str, site_name: str, progress: float, msg: str):
                await ws_manager.broadcast(str(run_id), {
                    "type": "progress",
                    "site_id": site_id,
                    "site_name": site_name,
                    "progress": progress,
                    "message": msg,
                })

            results_dict = await ScoringService.score_region_sites(
                db, region_id, mireye_client, progress_cb
            )

            for site_id_str, fields_dict in results_dict.items():
                site_id = uuid.UUID(site_id_str)
                dim_scores, composite_score, completeness = ScoringRankingEngine.calculate_scores(
                    fields_dict, weights
                )
                await crud.save_site_score(db, site_id, dim_scores, composite_score, completeness)

            await db.commit()

            # Refresh run and mark completed
            db_run = await crud.get_run(db, run_id)
            if db_run:
                db_run.status = "completed"
                await db.commit()

            await ws_manager.broadcast(str(run_id), {
                "type": "status",
                "status": "completed",
                "message": "Site scoring completed successfully.",
            })

            await mireye_client.close()

        except Exception as e:
            logger.error(f"Error in background scoring for run {run_id}: {e}", exc_info=True)

            # Update run status to failed using the same session (already rolled back by context)
            async with async_session_maker() as fail_db:
                fail_run = await crud.get_run(fail_db, run_id)
                if fail_run:
                    fail_run.status = "failed"
                    await fail_db.commit()

            await ws_manager.broadcast(str(run_id), {
                "type": "status",
                "status": "failed",
                "message": f"Scoring failed: {str(e)}",
            })


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/runs", response_model=schemas.RunResponse)
async def create_run_endpoint(
    name: str = Form(...),
    hub_count: int = Form(1),
    transport_weight: float = Form(0.2),
    power_weight: float = Form(0.2),
    buildability_weight: float = Form(0.2),
    context_weight: float = Form(0.2),
    hazard_weight: float = Form(0.2),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Creates a new siting run. Parses customer order geography CSV, runs Stage 1
    clustering (K-Medians) to establish candidate region centroids, and pre-sources candidate sites.
    """
    try:
        content = (await file.read()).decode("utf-8", errors="replace")
        demand_points = await IngestionService.parse_order_csv(content)
    except Exception as e:
        logger.error(f"CSV parse error: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid CSV file upload: {str(e)}")

    if not demand_points:
        raise HTTPException(status_code=400, detail="CSV contained no valid geocodable order data")

    run_create = schemas.RunCreate(
        name=name,
        hub_count=hub_count,
        transport_weight=transport_weight,
        power_weight=power_weight,
        buildability_weight=buildability_weight,
        context_weight=context_weight,
        hazard_weight=hazard_weight,
    )
    db_run = await crud.create_run(db, run_create)
    await crud.add_demand_points(db, db_run.id, demand_points)

    logger.info(f"Running Stage 1 clustering with k={hub_count} for run {db_run.id}")
    regions = DemandModelingService.run_k_medians(demand_points, hub_count)

    db_regions = await crud.add_regions(db, db_run.id, regions)
    for region in db_regions:
        sites = CandidateSourcingService.generate_candidate_sites(
            region_id=region.id,
            centroid_lat=region.centroid_lat,
            centroid_lng=region.centroid_lng,
            count=4,
        )
        await crud.add_sites(db, region.id, sites)

    db_run.status = "demand_completed"
    await db.commit()

    return await crud.get_run(db, db_run.id)


@app.get("/api/runs", response_model=List[schemas.RunResponse])
async def list_runs_endpoint(db: AsyncSession = Depends(get_db)):
    return await crud.get_runs(db)


@app.get("/api/runs/{id}", response_model=schemas.RunResponse)
async def get_run_endpoint(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    run = await crud.get_run(db, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.post("/api/runs/{id}/score")
async def trigger_scoring_endpoint(
    id: uuid.UUID,
    region_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Triggers Stage 2 site scoring for a specific candidate region within a run.
    Scoring runs in the background and broadcasts progress over WebSocket.
    """
    run = await crud.get_run(db, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    weights = {
        "transport_weight": run.transport_weight,
        "power_weight": run.power_weight,
        "buildability_weight": run.buildability_weight,
        "context_weight": run.context_weight,
        "hazard_weight": run.hazard_weight,
    }

    background_tasks.add_task(run_scoring_in_background, run_id=id, region_id=region_id, weights=weights)
    return {"message": "Scoring queued successfully in background."}


@app.get("/api/runs/{id}/sites", response_model=List[schemas.CandidateSiteResponse])
async def list_sites_endpoint(
    id: uuid.UUID,
    region_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Returns candidate sites in a region, along with their scores (if evaluated)."""
    sites = await crud.get_region_sites(db, region_id)

    response = []
    for site in sites:
        score_schema = None
        if site.scores:
            latest = site.scores[0]
            score_schema = schemas.SiteScoreSchema(
                dimension_scores_json=latest.dimension_scores_json,
                composite_score=latest.composite_score,
                data_completeness_pct=latest.data_completeness_pct,
                scored_at=latest.scored_at,
                scoring_version=latest.scoring_version,
            )
        response.append(schemas.CandidateSiteResponse(
            id=site.id,
            region_id=site.region_id,
            name=site.name,
            lat=site.lat,
            lng=site.lng,
            is_synthetic=site.is_synthetic,
            source=site.source,
            parcel_ref=site.parcel_ref,
            score=score_schema,
        ))

    return response


@app.get("/api/sites/{id}/citations", response_model=schemas.SiteCitationsResponse)
async def get_site_citations_endpoint(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieves full field-by-field citation details for a site, grouped by dimension.
    Uses 2 batched queries instead of N per-field queries.
    """
    site = await crud.get_site(db, id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    lat, lng = site.lat, site.lng

    # Build all cache keys for this site's fields
    all_fields = [field for fields in FIELD_DIMENSIONS.values() for field in fields]
    cache_key_for_field = {
        field: ScoringService.get_cache_key(lat, lng, field)
        for field in all_fields
    }
    all_cache_keys = list(set(cache_key_for_field.values()))

    # --- Batched query 1: all cached FieldValues ---
    fv_rows = await db.execute(
        select(models.FieldValue).where(
            models.FieldValue.coordinate_hash.in_(all_cache_keys),
            models.FieldValue.field_name.in_(all_fields),
        )
    )
    field_value_lookup: Dict[tuple, models.FieldValue] = {
        (row.coordinate_hash, row.field_name): row
        for row in fv_rows.scalars().all()
    }

    # --- Batched query 2: all active PartialFailures ---
    pf_rows = await db.execute(
        select(models.PartialFailure).where(
            models.PartialFailure.coordinate_hash.in_(all_cache_keys),
            models.PartialFailure.field_name.in_(all_fields),
            models.PartialFailure.resolved_at.is_(None),
        )
    )
    partial_failure_lookup: Dict[tuple, models.PartialFailure] = {
        (row.coordinate_hash, row.field_name): row
        for row in pf_rows.scalars().all()
    }

    citations_grouped: Dict[str, List[schemas.CitationDetail]] = {
        dim: [] for dim in FIELD_DIMENSIONS
    }

    for dim, fields in FIELD_DIMENSIONS.items():
        for field in fields:
            cache_key = cache_key_for_field[field]
            val_rec = field_value_lookup.get((cache_key, field))

            if val_rec:
                citations_grouped[dim].append(schemas.CitationDetail(
                    field_name=field,
                    value=val_rec.value_json.get("value") if val_rec.value_json else None,
                    unit=val_rec.unit,
                    source=val_rec.source,
                    source_url=val_rec.source_url,
                    confidence=val_rec.confidence,
                    fetched_at=val_rec.fetched_at,
                    present=True,
                    error=None,
                ))
                continue

            fail_rec = partial_failure_lookup.get((cache_key, field))
            if fail_rec:
                citations_grouped[dim].append(schemas.CitationDetail(
                    field_name=field,
                    value=None, unit=None,
                    source=fail_rec.source, source_url=None, confidence=None,
                    fetched_at=fail_rec.first_seen_at,
                    present=False, error=fail_rec.error,
                ))
            else:
                citations_grouped[dim].append(schemas.CitationDetail(
                    field_name=field,
                    value=None, unit=None, source="None", source_url=None, confidence=None,
                    fetched_at=None, present=False, error="Not yet evaluated",
                ))

    return schemas.SiteCitationsResponse(
        site_id=site.id,
        name=site.name,
        lat=site.lat,
        lng=site.lng,
        is_synthetic=site.is_synthetic,
        citations=citations_grouped,
    )


@app.get("/api/meta/fields")
async def get_meta_fields_endpoint():
    """Proxies Mireye Earth API field metadata list."""
    client = MireyeClient()
    try:
        return await client.fetch_meta_fields()
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# WebSocket progress stream
# ---------------------------------------------------------------------------

@app.websocket("/api/runs/{id}/progress")
async def websocket_progress_endpoint(websocket: WebSocket, id: str):
    await ws_manager.connect(id, websocket)
    try:
        while True:
            await websocket.receive_text()  # Keeps connection alive; listens for client disconnect
    except WebSocketDisconnect:
        ws_manager.disconnect(id, websocket)
    except Exception as e:
        logger.error(f"WebSocket error for run {id}: {e}")
        ws_manager.disconnect(id, websocket)

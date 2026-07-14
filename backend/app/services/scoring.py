import datetime
import logging
from typing import List, Dict, Any, Tuple, Callable, Awaitable, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from app.models import CandidateSite, FieldValue, PartialFailure
from app.mireye import MireyeClient, MIREYE_FIELDS, PARCEL_SPECIFIC_FIELDS, FIELD_DIMENSIONS

logger = logging.getLogger("scoring_service")

# Progress callback type: (site_id, site_name, progress_pct, message)
ProgressCallback = Callable[[str, str, float, str], Awaitable[None]]


def _utcnow() -> datetime.datetime:
    """Returns a timezone-aware UTC datetime. Centralizes the deprecated utcnow() replacement."""
    return datetime.datetime.now(datetime.timezone.utc)


class ScoringService:
    @staticmethod
    def get_cache_key(lat: float, lng: float, field_name: str) -> str:
        """
        Calculates cache key based on field type:
        - Parcel-specific: full precision (7 decimal places, ~1.1cm)
        - Regional / stable: rounded (4 decimal places, ~11m)
        """
        is_parcel_specific = PARCEL_SPECIFIC_FIELDS.get(field_name, False)
        if is_parcel_specific:
            return f"{lat:.7f},{lng:.7f}"
        return f"{lat:.4f},{lng:.4f}"

    @classmethod
    async def get_cached_fields(
        cls,
        db: AsyncSession,
        lat: float,
        lng: float,
        fields: List[str],
    ) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
        """
        Retrieves cached field values from the database using 2 batched queries
        instead of 2N sequential queries (one per field).

        Returns:
            Tuple: (dict of cached values keyed by field_name, list of field names to fetch live)
        """
        now = _utcnow()

        # Build all cache keys for this coordinate/field combination
        cache_key_for_field = {
            field: cls.get_cache_key(lat, lng, field)
            for field in fields
        }

        # --- Batched query 1: fetch all FieldValue rows in one round-trip ---
        all_cache_keys = list(set(cache_key_for_field.values()))
        field_value_rows = await db.execute(
            select(FieldValue).where(
                FieldValue.coordinate_hash.in_(all_cache_keys),
                FieldValue.field_name.in_(fields),
            )
        )
        # Build a lookup: (coordinate_hash, field_name) -> FieldValue
        cached_field_values: Dict[Tuple[str, str], FieldValue] = {
            (row.coordinate_hash, row.field_name): row
            for row in field_value_rows.scalars().all()
        }

        # --- Batched query 2: fetch all active PartialFailure rows in one round-trip ---
        partial_failure_rows = await db.execute(
            select(PartialFailure).where(
                PartialFailure.coordinate_hash.in_(all_cache_keys),
                PartialFailure.field_name.in_(fields),
                PartialFailure.resolved_at.is_(None),
            )
        )
        cached_partial_failures: Dict[Tuple[str, str], PartialFailure] = {
            (row.coordinate_hash, row.field_name): row
            for row in partial_failure_rows.scalars().all()
        }

        cached_results: Dict[str, Dict[str, Any]] = {}
        fields_to_fetch: List[str] = []

        for field in fields:
            cache_key = cache_key_for_field[field]
            field_val = cached_field_values.get((cache_key, field))

            if field_val:
                expire_time = field_val.fetched_at.replace(
                    tzinfo=datetime.timezone.utc
                ) + datetime.timedelta(seconds=field_val.ttl_seconds)
                if expire_time > now:
                    cached_results[field] = {
                        "value": field_val.value_json.get("value") if field_val.value_json else None,
                        "unit": field_val.unit,
                        "source": field_val.source,
                        "source_url": field_val.source_url,
                        "confidence": field_val.confidence,
                        "fetched_at": field_val.fetched_at,
                        "present": True,
                        "error": None,
                    }
                    continue  # Fresh cache hit — no live fetch needed

            # Check for a permanent (non-retryable) failure in the batch results
            failure = cached_partial_failures.get((cache_key, field))
            if failure and not failure.retryable:
                cached_results[field] = {
                    "value": None,
                    "unit": None,
                    "source": failure.source,
                    "source_url": None,
                    "confidence": None,
                    "fetched_at": failure.first_seen_at,
                    "present": False,
                    "error": failure.error,
                }
                continue  # Permanent failure cached — don't retry

            # Cache miss, expired, or retryable failure — needs live fetch
            fields_to_fetch.append(field)

        return cached_results, fields_to_fetch

    @classmethod
    async def score_site(
        cls,
        db: AsyncSession,
        site: CandidateSite,
        mireye_client: MireyeClient,
    ) -> Dict[str, Any]:
        """
        Orchestrates cache-lookup, Mireye API fetching, database updates,
        and result formatting for a single candidate site.
        """
        lat, lng = site.lat, site.lng

        # Determine which fields are cached and which need a live fetch
        cached, fields_to_fetch = await cls.get_cached_fields(db, lat, lng, MIREYE_FIELDS)

        if not fields_to_fetch:
            logger.info(f"All fields cached for site {site.name} ({lat}, {lng})")
            return cached

        logger.info(f"Fetching {len(fields_to_fetch)} fields from Mireye for site {site.name} ({lat}, {lng})")

        fetched_data: Dict[str, Any] = {}
        partial_failures: List[Dict[str, Any]] = []

        try:
            fetched_data, partial_failures = await mireye_client.fetch_coordinate_fields(lat, lng, fields_to_fetch)
        except ValueError as ve:
            if str(ve) == "coord_out_of_bounds":
                logger.error(f"Coordinates out of bounds for site {site.name} ({lat}, {lng})")
                partial_failures = [
                    {"field": field, "error": "coord_out_of_bounds", "retryable": False}
                    for field in fields_to_fetch
                ]
            else:
                raise
        except Exception as e:
            logger.error(f"Failed to fetch fields from Mireye API for site {site.name}: {e}")
            partial_failures = [
                {"field": field, "error": str(e), "retryable": True}
                for field in fields_to_fetch
            ]

        now = _utcnow()
        results = {**cached}

        # --- Process successful fetches ---
        for field_name, detail in fetched_data.items():
            field_status = detail.get("status", "ok")

            if field_status == "failed":
                # Inline failure from API — treat as a partial failure
                partial_failures.append({
                    "field": field_name,
                    "source": detail.get("source", "Mireye Earth API"),
                    "error": detail.get("error", "field fetch failed"),
                    "retryable": detail.get("retryable", True),
                })
                continue

            if field_status == "absent":
                # Valid no-data response — contributes zero weight to scoring
                results[field_name] = {
                    "value": None, "unit": detail.get("unit"),
                    "source": detail.get("source", "Unknown"),
                    "source_url": detail.get("source_url"),
                    "confidence": detail.get("confidence"),
                    "fetched_at": now, "present": False, "error": None,
                }
                continue

            cache_key = cls.get_cache_key(lat, lng, field_name)
            ttl = detail.get("ttl_seconds", 86400)
            val_json = {"value": detail.get("value")}

            # Upsert the successfully fetched value
            exist_q = await db.execute(
                select(FieldValue).where(
                    FieldValue.coordinate_hash == cache_key,
                    FieldValue.field_name == field_name,
                )
            )
            existing = exist_q.scalar_one_or_none()

            if existing:
                existing.value_json = val_json
                existing.unit = detail.get("unit")
                existing.source = detail.get("source", "Unknown")
                existing.source_url = detail.get("source_url")
                existing.confidence = detail.get("confidence")
                existing.fetched_at = now
                existing.ttl_seconds = ttl
            else:
                db.add(FieldValue(
                    coordinate_hash=cache_key,
                    field_name=field_name,
                    value_json=val_json,
                    unit=detail.get("unit"),
                    source=detail.get("source", "Unknown"),
                    source_url=detail.get("source_url"),
                    confidence=detail.get("confidence"),
                    fetched_at=now,
                    ttl_seconds=ttl,
                ))

            # Mark any prior failures for this field as resolved
            await db.execute(
                update(PartialFailure)
                .where(
                    PartialFailure.coordinate_hash == cache_key,
                    PartialFailure.field_name == field_name,
                    PartialFailure.resolved_at.is_(None),
                )
                .values(resolved_at=now)
            )

            results[field_name] = {
                "value": detail.get("value"),
                "unit": detail.get("unit"),
                "source": detail.get("source", "Unknown"),
                "source_url": detail.get("source_url"),
                "confidence": detail.get("confidence"),
                "fetched_at": now,
                "present": True,
                "error": None,
            }

        # --- Process partial failures ---
        for fail in partial_failures:
            # Mireye API uses "field" key; internal synthetic failures may use "field_name"
            field_name = fail.get("field") or fail.get("field_name")
            if not field_name:
                continue

            error_msg = fail.get("error", "unknown error")
            retryable = fail.get("retryable", True)
            cache_key = cls.get_cache_key(lat, lng, field_name)

            fail_q = await db.execute(
                select(PartialFailure).where(
                    PartialFailure.coordinate_hash == cache_key,
                    PartialFailure.field_name == field_name,
                    PartialFailure.resolved_at.is_(None),
                )
            )
            existing_fail = fail_q.scalar_one_or_none()

            if existing_fail:
                existing_fail.error = error_msg
                existing_fail.retryable = retryable
            else:
                db.add(PartialFailure(
                    coordinate_hash=cache_key,
                    field_name=field_name,
                    source="Mireye Earth API",
                    error=error_msg,
                    retryable=retryable,
                    first_seen_at=now,
                ))

            # Evict any stale cached FieldValue so it's re-fetched next time
            await db.execute(
                delete(FieldValue).where(
                    FieldValue.coordinate_hash == cache_key,
                    FieldValue.field_name == field_name,
                )
            )

            results[field_name] = {
                "value": None,
                "unit": None,
                "source": "Mireye Earth API",
                "source_url": None,
                "confidence": None,
                "fetched_at": now,
                "present": False,
                "error": error_msg,
            }

        await db.flush()
        return results

    @classmethod
    async def score_region_sites(
        cls,
        db: AsyncSession,
        region_id: Any,
        mireye_client: MireyeClient,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Triggers Stage 2 scoring for all sites in a region.
        Communicates real-time progress via the optional progress_callback.
        """
        query = await db.execute(
            select(CandidateSite).where(CandidateSite.region_id == region_id)
        )
        sites = query.scalars().all()

        num_sites = len(sites)
        if num_sites == 0:
            return {}

        site_results: Dict[str, Dict[str, Any]] = {}

        for idx, site in enumerate(sites):
            if progress_callback:
                await progress_callback(
                    str(site.id),
                    site.name,
                    float(idx) / num_sites,
                    f"Initiating fetch for {site.name}...",
                )

            results = await cls.score_site(db, site, mireye_client)
            site_results[str(site.id)] = results

            if progress_callback:
                await progress_callback(
                    str(site.id),
                    site.name,
                    float(idx + 1) / num_sites,
                    f"Completed fetching for {site.name}.",
                )

        return site_results

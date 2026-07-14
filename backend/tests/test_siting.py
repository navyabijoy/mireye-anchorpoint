import pytest
import uuid
import random
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.database import Base
from app.models import CandidateSite, FieldValue, PartialFailure
from app.services.demand import DemandModelingService, haversine_distance
from app.services.sourcing import CandidateSourcingService
from app.services.scoring import ScoringService
from app.services.ranking import ScoringRankingEngine
from app.mireye import MIREYE_FIELDS

# Stage 1 Clustering tests
def test_haversine_distance():
    # NYC to LA distance is approx 3940 km
    nyc_lat, nyc_lng = 40.7128, -74.0060
    la_lat, la_lng = 34.0522, -118.2437
    dist = haversine_distance(nyc_lat, nyc_lng, la_lat, la_lng)
    assert 3900.0 < dist < 4000.0

def test_k_medians_clustering():
    # Seed random so K-Medians++ initialization is deterministic across test runs
    random.seed(42)
    demand_points = [
        {"lat": 40.7128, "lng": -74.0060, "weight": 10.0},  # NY
        {"lat": 40.7306, "lng": -73.9352, "weight": 5.0},   # NY close
        {"lat": 34.0522, "lng": -118.2437, "weight": 8.0},  # LA
        {"lat": 34.0549, "lng": -118.2426, "weight": 2.0},  # LA close
    ]
    
    # Run clustering with k=2
    regions = DemandModelingService.run_k_medians(demand_points, k=2)
    
    assert len(regions) == 2
    
    # One region should be around NY and one around LA
    ny_centroid = next(r for r in regions if r["lng"] > -80.0)
    la_centroid = next(r for r in regions if r["lng"] < -100.0)
    
    assert 40.0 < ny_centroid["lat"] < 41.0
    assert -75.0 < ny_centroid["lng"] < -73.0
    assert 33.0 < la_centroid["lat"] < 35.0
    assert -119.0 < la_centroid["lng"] < -117.0
    assert ny_centroid["radius_km"] >= 10.0  # floor
    assert la_centroid["radius_km"] >= 10.0

# Stage 2 Scoring and weight redistribution tests
def test_scoring_normalization():
    # Test transport normalization: nearest major road distance (lower is better, best=200m, worst=10000m)
    assert ScoringRankingEngine.normalize_field("nearest_major_road_distance_m", 150.0) == 1.0
    assert ScoringRankingEngine.normalize_field("nearest_major_road_distance_m", 15000.0) == 0.0
    # Mid point: (10000 - 5100) / 9800 = 4900 / 9800 = 0.5
    assert ScoringRankingEngine.normalize_field("nearest_major_road_distance_m", 5100.0) == 0.5

    # Test zoning mapping
    assert ScoringRankingEngine.normalize_field("parcel_zoning", "M-1 Light Industrial") == 1.0
    assert ScoringRankingEngine.normalize_field("parcel_zoning", "C-2 Retail Commercial") == 0.5
    assert ScoringRankingEngine.normalize_field("parcel_zoning", "R-1 Residential") == 0.1

    # Test floodplain mapping (False -> 1.0, True -> 0.0)
    assert ScoringRankingEngine.normalize_field("within_floodplain_polygon", False) == 1.0
    assert ScoringRankingEngine.normalize_field("within_floodplain_polygon", True) == 0.0

def test_weight_redistribution_and_completeness():
    # Base configuration weights (equal weight 0.2 each)
    weights = {
        "transport_weight": 0.2,
        "power_weight": 0.2,
        "buildability_weight": 0.2,
        "context_weight": 0.2,
        "hazard_weight": 0.2
    }

    # Define realistic optimal values for each field
    optimal_values = {
        "nearest_major_road_distance_m": 200.0,
        "roads_within_500m_count": 5.0,
        "nearest_rail_line_distance_m": 500.0,
        "nearest_transmission_line_distance_m": 100.0,
        "nearest_transmission_line_voltage_kv": 230.0,
        "nearest_substation_distance_m": 500.0,
        "parcel_zoning": "Industrial",
        "parcel_area_m2": 200000.0,
        "developable_acres_proxy": 40.0,
        "grading_difficulty_class": 1,
        "nearest_urban_area_distance_m": 15000.0,
        "housing_units_within_1km": 1000.0,
        "housing_units_density_per_km2": 500.0,
        "wildfire_annual_frequency": 0.0001,
        "within_floodplain_polygon": False,
        "seismic_pga_2pct_50yr_g": 0.05,
        "design_wind_speed_mph": 90.0
    }

    # Simulate fully present fields (100% completeness)
    results_full = {
        f: {"present": True, "value": optimal_values[f]}
        for f in MIREYE_FIELDS
    }
    
    dim_scores, composite_score, completeness = ScoringRankingEngine.calculate_scores(results_full, weights)
    assert completeness == 100.0
    assert composite_score is not None
    assert 0.9 <= composite_score <= 1.0 # High score since values are optimal

    # Simulate missing fields in transport (e.g. nearest_rail_line_distance_m is missing)
    results_partial = {**results_full}
    results_partial["nearest_rail_line_distance_m"] = {"present": False, "value": None}
    
    dim_scores_p, composite_p, completeness_p = ScoringRankingEngine.calculate_scores(results_partial, weights)
    # 16 out of 17 fields present
    assert completeness_p == (16 / 17) * 100.0
    assert composite_p is not None

    # Simulate completely missing hazard dimension (all hazard fields missing)
    results_no_hazard = {**results_full}
    for f in ["wildfire_annual_frequency", "within_floodplain_polygon", "seismic_pga_2pct_50yr_g", "design_wind_speed_mph"]:
        results_no_hazard[f] = {"present": False, "value": None}
        
    dim_scores_h, composite_h, completeness_h = ScoringRankingEngine.calculate_scores(results_no_hazard, weights)
    # 13 out of 17 fields present
    assert completeness_h == (13 / 17) * 100.0
    assert completeness_h >= 50.0  # Above floor
    assert composite_h is not None
    
    # Check that hazard weight was redistributed: the active dimensions (transport, power, buildability, context)
    # sum to 0.8, re-normalized, they should still produce a valid composite score.
    assert dim_scores_h["hazard"] == 0.0

    # Simulate low completeness below floor (e.g., only 5 fields present = 29.4% completeness)
    results_low_comp = {
        f: {"present": False, "value": None}
        for f in MIREYE_FIELDS
    }
    for f in MIREYE_FIELDS[:5]:
        results_low_comp[f] = {"present": True, "value": 1.0}
        
    dim_scores_l, composite_l, completeness_l = ScoringRankingEngine.calculate_scores(results_low_comp, weights)
    assert completeness_l < 50.0
    assert composite_l is None  # Triggered floor!

# Async cache strategy tests using a SQLite in-memory database
@pytest.mark.asyncio
async def test_split_coordinate_caching():
    # Setup test in-memory database
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    test_session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    async with test_session_maker() as db:
        lat, lng = 34.0522, -118.2437
        
        # Save a parcel specific field (parcel_zoning) and a regional field (wildfire_annual_frequency)
        # Using the correct cache keys
        parcel_key = ScoringService.get_cache_key(lat, lng, "parcel_zoning")
        regional_key = ScoringService.get_cache_key(lat, lng, "wildfire_annual_frequency")
        
        # Verify cache keys:
        # parcel key should be high-precision: "34.0522000,-118.2437000"
        # regional key should be rounded: "34.0522,-118.2437"
        assert parcel_key == "34.0522000,-118.2437000" or parcel_key == f"{lat:.7f},{lng:.7f}"
        assert regional_key == "34.0522,-118.2437"
        
        now = datetime.now(timezone.utc)
        db.add(FieldValue(
            coordinate_hash=parcel_key,
            field_name="parcel_zoning",
            value_json={"value": "Industrial"},
            unit=None,
            source="Test Assessor",
            fetched_at=now,
            ttl_seconds=86400
        ))
        db.add(FieldValue(
            coordinate_hash=regional_key,
            field_name="wildfire_annual_frequency",
            value_json={"value": 0.002},
            unit="pct",
            source="Test NOAA",
            fetched_at=now,
            ttl_seconds=86400
        ))
        await db.commit()
        
        # 1. Lookup at the EXACT SAME coordinates -> both should hit cache
        cached_exact, fetch_exact = await ScoringService.get_cached_fields(
            db, lat, lng, ["parcel_zoning", "wildfire_annual_frequency"]
        )
        assert len(fetch_exact) == 0
        assert cached_exact["parcel_zoning"]["value"] == "Industrial"
        assert cached_exact["wildfire_annual_frequency"]["value"] == 0.002
        
        # 2. Lookup at a SLIGHTLY shifted coordinate: shift by 0.00002 deg (~2 meters)
        # This keeps the rounded key identical ("34.0522,-118.2437")
        # but changes the full precision key!
        shifted_lat = lat + 0.00002
        shifted_lng = lng + 0.00002
        
        cached_shift, fetch_shift = await ScoringService.get_cached_fields(
            db, shifted_lat, shifted_lng, ["parcel_zoning", "wildfire_annual_frequency"]
        )
        
        # The regional field (wildfire frequency) should STILL hit cache because it rounds to 4 decimals
        assert "wildfire_annual_frequency" in cached_shift
        assert cached_shift["wildfire_annual_frequency"]["value"] == 0.002
        
        # The parcel-specific field (zoning) should MISSED cache and require fetching!
        assert "parcel_zoning" not in cached_shift
        assert "parcel_zoning" in fetch_shift

    await test_engine.dispose()

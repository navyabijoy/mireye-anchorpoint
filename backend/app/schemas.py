from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import List, Optional, Dict, Any, Union


class RunCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    hub_count: int = Field(default=1, ge=1, le=10)
    transport_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    power_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    buildability_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    context_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    hazard_weight: float = Field(default=0.2, ge=0.0, le=1.0)


class DemandPointBase(BaseModel):
    lat: float
    lng: float
    zip_code: Optional[str] = None
    order_count: int = 1
    revenue: float = 0.0


class DemandPointResponse(DemandPointBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    weight: float


class CandidateRegionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    centroid_lat: float
    centroid_lng: float
    radius_km: float
    name: str


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    status: str
    hub_count: int
    transport_weight: float
    power_weight: float
    buildability_weight: float
    context_weight: float
    hazard_weight: float
    created_at: datetime
    regions: List[CandidateRegionResponse] = []


class SiteScoreSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dimension_scores_json: Dict[str, float]
    composite_score: Optional[float] = None
    data_completeness_pct: float
    scored_at: datetime
    scoring_version: str


class CandidateSiteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    region_id: UUID
    name: str
    lat: float
    lng: float
    is_synthetic: bool
    source: str
    parcel_ref: Optional[str] = None
    score: Optional[SiteScoreSchema] = None


class CitationDetail(BaseModel):
    field_name: str
    # Narrowed from Any to the actual value types Mireye returns
    value: Union[str, int, float, bool, None] = None
    unit: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    confidence: Optional[str] = None
    fetched_at: Optional[datetime] = None
    present: bool
    error: Optional[str] = None


class SiteCitationsResponse(BaseModel):
    site_id: UUID
    name: str
    lat: float
    lng: float
    is_synthetic: bool
    citations: Dict[str, List[CitationDetail]]  # Grouped by dimension name

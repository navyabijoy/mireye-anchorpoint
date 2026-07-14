import asyncio
import logging
import httpx
from typing import List, Dict, Any, Tuple
from app.config import settings

logger = logging.getLogger("mireye_client")

MIREYE_API_URL = "https://api.mireye.com/v1"

# The active field set used for scoring candidate warehouse sites
MIREYE_FIELDS = [
    # Transport access
    "nearest_major_road_distance_m",
    "roads_within_500m_count",
    "nearest_rail_line_distance_m",
    # Power/utility access
    "nearest_transmission_line_distance_m",
    "nearest_transmission_line_voltage_kv",
    "nearest_substation_distance_m",
    # Buildability
    "parcel_zoning",
    "parcel_area_m2",
    "developable_acres_proxy",
    "grading_difficulty_class",
    # Context
    "nearest_urban_area_distance_m",
    "housing_units_within_1km",
    "housing_units_density_per_km2",
    # Hazard/insurability screening
    "wildfire_annual_frequency",
    "within_floodplain_polygon",
    "seismic_pga_2pct_50yr_g",
    "design_wind_speed_mph"
]

# Field grouping mapping for frontend display and scoring breakdown
FIELD_DIMENSIONS = {
    "transport": [
        "nearest_major_road_distance_m",
        "roads_within_500m_count",
        "nearest_rail_line_distance_m"
    ],
    "power": [
        "nearest_transmission_line_distance_m",
        "nearest_transmission_line_voltage_kv",
        "nearest_substation_distance_m"
    ],
    "buildability": [
        "parcel_zoning",
        "parcel_area_m2",
        "developable_acres_proxy",
        "grading_difficulty_class"
    ],
    "context": [
        "nearest_urban_area_distance_m",
        "housing_units_within_1km",
        "housing_units_density_per_km2"
    ],
    "hazard": [
        "wildfire_annual_frequency",
        "within_floodplain_polygon",
        "seismic_pga_2pct_50yr_g",
        "design_wind_speed_mph"
    ]
}

# Map fields to their cache level
# True if parcel-specific (requires full precision cache), False if regional/stable (can use rounded cache)
PARCEL_SPECIFIC_FIELDS = {
    "parcel_zoning": True,
    "parcel_area_m2": True,
    "developable_acres_proxy": True,
    "grading_difficulty_class": True,
    # Remaining are regional / terrain / hazard / context
    "nearest_major_road_distance_m": False,
    "roads_within_500m_count": False,
    "nearest_rail_line_distance_m": False,
    "nearest_transmission_line_distance_m": False,
    "nearest_transmission_line_voltage_kv": False,
    "nearest_substation_distance_m": False,
    "nearest_urban_area_distance_m": False,
    "housing_units_within_1km": False,
    "housing_units_density_per_km2": False,
    "wildfire_annual_frequency": False,
    "within_floodplain_polygon": False,
    "seismic_pga_2pct_50yr_g": False,
    "design_wind_speed_mph": False
}

class MireyeClient:
    def __init__(self, api_token: str = settings.MIREYE_API_TOKEN):
        self.api_token = api_token
        # Restrict concurrent requests to Mireye API to avoid overwhelming it
        self.semaphore = asyncio.Semaphore(5)
        # HTTPX AsyncClient with reasonable timeouts
        self.client = httpx.AsyncClient(
            base_url=MIREYE_API_URL,
            timeout=httpx.Timeout(20.0, connect=5.0)
        )

    async def close(self):
        await self.client.aclose()

    def get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }

    async def fetch_meta_fields(self) -> List[Dict[str, Any]]:
        """
        Public endpoint GET /v1/meta/fields (no token needed).
        """
        try:
            response = await self.client.get("/meta/fields")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error calling /v1/meta/fields: {e}")
            # Return a fallback catalog containing our primary fields in case of failure
            return [
                {"field_name": name, "category": "unknown", "description": "No description", "type": "float", "source": "US Federal"}
                for name in MIREYE_FIELDS
            ]

    async def fetch_coordinate_fields(self, lat: float, lng: float, fields: List[str]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Fetches requested fields for a coordinate from Mireye API.
        Returns:
            Tuple[fields_dict, partial_failures_list]
        Raises:
            ValueError: If coordinate is out of bounds (returns 400 from Mireye API)
            httpx.HTTPStatusError: For other HTTP client errors
        """
        if not self.api_token:
            raise ValueError("Missing MIREYE_API_TOKEN environment variable. Please configure it in your environment or a .env file.")

        # Coordinate bounds check: lat in [18, 72], lng in [-180, -65]
        if not (18.0 <= lat <= 72.0) or not (-180.0 <= lng <= -65.0):
            raise ValueError("coord_out_of_bounds")

        payload = {
            "lat": lat,
            "lng": lng,
            "fields": fields
        }

        async with self.semaphore:
            max_retries = 3
            backoff_factor = 1.0

            for attempt in range(max_retries):
                try:
                    response = await self.client.post(
                        "/fetch",
                        json=payload,
                        headers=self.get_headers(),
                    )

                    if response.status_code == 400 and "coord_out_of_bounds" in response.text:
                        raise ValueError("coord_out_of_bounds")

                    response.raise_for_status()
                    data = response.json()
                    return data.get("fields", {}), data.get("partial_failures", [])

                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        # Honour Retry-After header if present; otherwise use exponential backoff
                        retry_after = e.response.headers.get("Retry-After")
                        wait_time = (
                            float(retry_after) if retry_after and retry_after.isdigit()
                            else backoff_factor * (2 ** attempt)
                        )
                        logger.warning(f"Rate limited (429). Retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        continue

                    if e.response.status_code == 400 and "coord_out_of_bounds" in e.response.text:
                        raise ValueError("coord_out_of_bounds")

                    logger.error(f"HTTP error fetching fields (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt == max_retries - 1:
                        raise
                    await asyncio.sleep(backoff_factor * (2 ** attempt))

                except Exception as e:
                    logger.error(f"Network error fetching fields (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt == max_retries - 1:
                        raise
                    await asyncio.sleep(backoff_factor * (2 ** attempt))


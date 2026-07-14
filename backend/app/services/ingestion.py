import csv
import io
import logging
import httpx
from typing import List, Dict, Any, Tuple, Optional
import re

logger = logging.getLogger("ingestion_service")

# Revenue threshold treated as equivalent to 1 order when computing demand weight.
# e.g. $50 revenue ≈ 1 order unit. Adjust to match your order economics.
REVENUE_TO_ORDER_EQUIVALENT: float = 50.0

# In-process cache mapping cleaned ZIP codes → (lat, lng).
# This is NOT shared across worker processes (e.g., gunicorn multi-worker).
# Seeded with common US metro codes to avoid network calls for typical test data.
ZIP_COORDINATE_CACHE = {
    "10001": (40.7508, -73.9961),  # NYC
    "90210": (34.1030, -118.4105), # Beverly Hills
    "60601": (41.8858, -87.6250),  # Chicago
    "77001": (29.7589, -95.3677),  # Houston
    "33101": (25.7743, -80.1937),  # Miami
    "94102": (37.7749, -122.4194), # SF
    "02108": (42.3581, -71.0636),  # Boston
    "98101": (47.6101, -122.3421), # Seattle
    "30301": (33.7490, -84.3880),  # Atlanta
    "80201": (39.7392, -104.9903), # Denver
    "75201": (32.7801, -96.8005),  # Dallas
    "19102": (39.9526, -75.1652),  # Philadelphia
    "37201": (36.1627, -86.7816),  # Nashville
    "85001": (33.4484, -112.0740), # Phoenix
    "48201": (42.3314, -83.0458),  # Detroit
    "20001": (38.8951, -77.0364)   # Washington DC
}

async def geocode_zip_census(zip_code: str) -> Optional[Tuple[float, float]]:
    """
    Asynchronously geocodes a US ZIP code using the free US Census Geocoding API.
    Returns:
        Tuple[lat, lng] or None
    """
    clean_zip = re.sub(r"\D", "", zip_code)[:5]
    if not clean_zip:
        return None
        
    # Check local cache first
    if clean_zip in ZIP_COORDINATE_CACHE:
        return ZIP_COORDINATE_CACHE[clean_zip]

    # Query US Census Geocoder API
    url = f"https://geocoding.geo.census.gov/geocoder/locations/postalcode?postal={clean_zip}&format=json"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                results = data.get("result", {}).get("addressMatches", [])
                if results:
                    coord = results[0].get("coordinates", {})
                    # Census API returns x (lng) and y (lat)
                    if "x" in coord and "y" in coord:
                        lat, lng = coord["y"], coord["x"]
                        # Save to cache
                        ZIP_COORDINATE_CACHE[clean_zip] = (lat, lng)
                        return lat, lng
    except Exception as e:
        logger.error(f"Failed to geocode zip {zip_code} using Census Geocoder: {e}")
        
    return None

class IngestionService:
    @classmethod
    async def parse_order_csv(cls, csv_content: str) -> List[Dict[str, Any]]:
        """
        Parses order history CSV and extracts demand points.
        Accepts formats:
        - `lat`, `lng`, `zip_code` (optional), `order_count` (optional), `revenue` (optional)
        - If lat/lng are missing but `zip_code` exists, geocodes it.
        """
        reader = csv.DictReader(io.StringIO(csv_content))
        demand_points = []

        for idx, row in enumerate(reader):
            # Clean keys to lowercase/strip
            row_clean = {k.strip().lower(): v.strip() for k, v in row.items() if k and v}
            
            lat = None
            lng = None
            zip_code = row_clean.get("zip_code") or row_clean.get("zip") or row_clean.get("postal_code")
            
            # Extract lat/lng
            lat_str = row_clean.get("lat") or row_clean.get("latitude")
            lng_str = row_clean.get("lng") or row_clean.get("longitude") or row_clean.get("lon")
            
            if lat_str and lng_str:
                try:
                    lat = float(lat_str)
                    lng = float(lng_str)
                except ValueError:
                    pass
            
            # Geocode if lat/lng are missing but zip is present
            if (lat is None or lng is None) and zip_code:
                coords = await geocode_zip_census(zip_code)
                if coords:
                    lat, lng = coords
            
            if lat is None or lng is None:
                # Skip invalid lines
                logger.warning(f"Row {idx} skipped: Missing geocodable details: {row}")
                continue

            # Extract weight components
            try:
                order_count = int(row_clean.get("order_count") or row_clean.get("orders") or 1)
            except ValueError:
                order_count = 1
                
            try:
                revenue = float(row_clean.get("revenue") or row_clean.get("sales") or 0.0)
            except ValueError:
                revenue = 0.0
                
            # Combine order frequency and revenue into a single demand weight.
            # Revenue is normalized by REVENUE_TO_ORDER_EQUIVALENT so that
            # $50 revenue contributes the same weight as 1 order.
            weight = float(order_count) + (revenue / REVENUE_TO_ORDER_EQUIVALENT)
            if weight <= 0:
                weight = 1.0

            demand_points.append({
                "lat": lat,
                "lng": lng,
                "zip_code": zip_code,
                "order_count": order_count,
                "revenue": revenue,
                "weight": weight
            })

        return demand_points

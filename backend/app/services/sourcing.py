import math
from typing import List, Tuple, Dict, Any
import uuid

def offset_coordinate(lat: float, lng: float, dist_km: float, bearing_deg: float) -> Tuple[float, float]:
    """
    Calculate new coordinate given a starting coordinate, distance in km,
    and bearing in degrees (0 is North, 90 is East, etc.).
    """
    R = 6371.0  # Earth radius in km
    lat_rad = math.radians(lat)
    lng_rad = math.radians(lng)
    bearing_rad = math.radians(bearing_deg)
    
    angular_dist = dist_km / R

    new_lat_rad = math.asin(
        math.sin(lat_rad) * math.cos(angular_dist) +
        math.cos(lat_rad) * math.sin(angular_dist) * math.cos(bearing_rad)
    )
    
    new_lng_rad = lng_rad + math.atan2(
        math.sin(bearing_rad) * math.sin(angular_dist) * math.cos(lat_rad),
        math.cos(angular_dist) - math.sin(lat_rad) * math.sin(new_lat_rad)
    )
    
    return math.degrees(new_lat_rad), math.degrees(new_lng_rad)

class CandidateSourcingService:
    @staticmethod
    def generate_candidate_sites(
        region_id: uuid.UUID,
        centroid_lat: float,
        centroid_lng: float,
        count: int = 4
    ) -> List[Dict[str, Any]]:
        """
        Generates illustrative candidate sites around a candidate region centroid.
        Names are derived explicitly from the offset geometry rather than fabricated addresses.
        Marks each site with `is_synthetic: True`.
        """
        # Spaced out configurations (distance in km, bearing in degrees, direction string)
        configs = [
            (3.5, 45.0, "NE"),
            (5.2, 180.0, "S"),
            (7.8, 270.0, "W"),
            (4.1, 135.0, "SE"),
            (9.0, 315.0, "NW")
        ]
        
        # Cap count to configs size
        count = min(count, len(configs))
        
        sites = []
        for i in range(count):
            dist, bearing, direction = configs[i]
            site_lat, site_lng = offset_coordinate(centroid_lat, centroid_lng, dist, bearing)
            
            # Formulate the name transparently without fabricating addresses
            name = f"Candidate site {i + 1}, ~{dist:.1f}km {direction} of centroid"
            
            sites.append({
                "id": uuid.uuid4(),
                "region_id": region_id,
                "name": name,
                "lat": site_lat,
                "lng": site_lng,
                "is_synthetic": True,
                "source": "synthetic",
                "parcel_ref": f"SYN-{region_id.hex[:6].upper()}-{i+1}"
            })
            
        return sites

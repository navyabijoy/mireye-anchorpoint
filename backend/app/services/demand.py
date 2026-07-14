import math
import random
from typing import List, Tuple, Dict, Any

# Algorithm tuning constants
EARTH_RADIUS_KM: float = 6371.0
WEISZFELD_MAX_ITERATIONS: int = 20
WEISZFELD_CONVERGENCE_THRESHOLD: float = 1e-6
WEISZFELD_MIN_DISTANCE_KM: float = 0.001  # Avoids division by zero for coincident points

def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate the great circle distance between two points
    on the earth (specified in decimal degrees) in kilometers.
    """
    # Convert decimal degrees to radians
    lat1_rad = math.radians(lat1)
    lng1_rad = math.radians(lng1)
    lat2_rad = math.radians(lat2)
    lng2_rad = math.radians(lng2)

    # Haversine formula
    d_lat = lat2_rad - lat1_rad
    d_lng = lng2_rad - lng1_rad
    a = math.sin(d_lat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(d_lng / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    r = EARTH_RADIUS_KM
    return r * c

class DemandModelingService:
    @staticmethod
    def calculate_weighted_median(points: List[Tuple[float, float, float]]) -> Tuple[float, float]:
        """
        Finds the geometric median of a list of points (lat, lng, weight)
        using a simplified Weiszfeld's algorithm for weighted coordinates.
        """
        if not points:
            return 0.0, 0.0

        total_weight = sum(p[2] for p in points)
        if total_weight <= 0:
            # All weights are zero or negative — treat all points equally
            points = [(p[0], p[1], 1.0) for p in points]  # local copy, not mutation
            total_weight = float(len(points))

        curr_lat = sum(p[0] * p[2] for p in points) / total_weight
        curr_lng = sum(p[1] * p[2] for p in points) / total_weight

        # Run Weiszfeld iterations
        for _ in range(WEISZFELD_MAX_ITERATIONS):
            num_lat = 0.0
            num_lng = 0.0
            denom = 0.0

            for lat, lng, w in points:
                dist = haversine_distance(curr_lat, curr_lng, lat, lng)
                if dist < WEISZFELD_MIN_DISTANCE_KM:
                    dist = WEISZFELD_MIN_DISTANCE_KM

                # Each point's contribution is weight / distance (Weiszfeld update rule)
                contribution = w / dist
                num_lat += lat * contribution
                num_lng += lng * contribution
                denom += contribution

            if denom == 0:
                break

            new_lat = num_lat / denom
            new_lng = num_lng / denom

            if abs(new_lat - curr_lat) < WEISZFELD_CONVERGENCE_THRESHOLD \
                    and abs(new_lng - curr_lng) < WEISZFELD_CONVERGENCE_THRESHOLD:
                break

            curr_lat = new_lat
            curr_lng = new_lng

        return curr_lat, curr_lng

    @classmethod
    def run_k_medians(
        cls, 
        demand_points: List[Dict[str, Any]], 
        k: int, 
        max_iterations: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Runs weighted K-Medians clustering on a list of demand points.
        Each demand point is a dict with keys: 'lat', 'lng', 'weight'.
        Returns:
            A list of region centroids with keys: 'lat', 'lng', 'radius_km', 'name'
        """
        if not demand_points:
            return []

        # Format points: (lat, lng, weight)
        points = [(dp["lat"], dp["lng"], dp["weight"]) for dp in demand_points]
        n = len(points)
        
        if n <= k:
            # Fewer points than cluster count, return each point as its own centroid
            regions = []
            for i, p in enumerate(points):
                regions.append({
                    "lat": p[0],
                    "lng": p[1],
                    "radius_km": 15.0,  # Default radius
                    "name": f"Region {i+1} (Single Point Cluster)"
                })
            return regions

        # 1. Initialize centroids (kmeans++ style weighted selection)
        centroids = []
        # First centroid selected at random weighted by weight
        weights = [p[2] for p in points]
        first_centroid = random.choices(points, weights=weights, k=1)[0]
        centroids.append((first_centroid[0], first_centroid[1]))
        
        for _ in range(1, k):
            # Select remaining centroids based on distance to nearest existing centroid
            distances = []
            for p in points:
                min_dist = min(haversine_distance(p[0], p[1], c[0], c[1]) for c in centroids)
                distances.append((min_dist ** 2) * p[2])  # weighted distance squared
            
            total_dist_sq = sum(distances)
            if total_dist_sq == 0:
                # Fallback to random choice if all points overlap
                chosen = random.choice(points)
            else:
                prob = [d / total_dist_sq for d in distances]
                chosen = random.choices(points, weights=prob, k=1)[0]
            centroids.append((chosen[0], chosen[1]))

        # 2. Iterate assignment and update
        assignments = [0] * n
        for iteration in range(max_iterations):
            # Assignment Step: Assign each point to the closest centroid
            changed = False
            for i, p in enumerate(points):
                min_dist = float('inf')
                best_cluster = 0
                for c_idx, c in enumerate(centroids):
                    dist = haversine_distance(p[0], p[1], c[0], c[1])
                    if dist < min_dist:
                        min_dist = dist
                        best_cluster = c_idx
                if assignments[i] != best_cluster:
                    assignments[i] = best_cluster
                    changed = True
            
            if not changed and iteration > 0:
                break
                
            # Update Step: Find geometric median for each cluster
            new_centroids = []
            for c_idx in range(k):
                cluster_points = [points[i] for i in range(n) if assignments[i] == c_idx]
                if not cluster_points:
                    # If a cluster becomes empty, select a random point as centroid
                    chosen = random.choice(points)
                    new_centroids.append((chosen[0], chosen[1]))
                else:
                    new_c = cls.calculate_weighted_median(cluster_points)
                    new_centroids.append(new_c)
            
            centroids = new_centroids

        # 3. Build region responses (calculate radius and names)
        regions = []
        for c_idx, c in enumerate(centroids):
            cluster_points = [points[i] for i in range(n) if assignments[i] == c_idx]
            
            # Radius is the maximum distance from centroid to any cluster member (with a 10km floor)
            if not cluster_points:
                radius = 10.0
            else:
                max_dist = max(haversine_distance(c[0], c[1], p[0], p[1]) for p in cluster_points)
                radius = max(max_dist, 10.0)

            # Assign a regional descriptive name based on centroid coordinates
            # Simplified naming - e.g. North/South/East/West based on relative position
            # Can be expanded based on USA geographical zones.
            lat, lng = c
            lat_label = "North" if lat > 38.0 else "South"
            lng_label = "East" if lng > -95.0 else ("West" if lng < -110.0 else "Central")
            region_name = f"Region {c_idx + 1} ({lat_label} {lng_label} Centroid)"

            regions.append({
                "lat": lat,
                "lng": lng,
                "radius_km": radius,
                "name": region_name
            })
            
        return regions

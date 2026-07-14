import logging
from typing import Dict, Any, Optional, Tuple, NamedTuple, Callable

from app.mireye import FIELD_DIMENSIONS

logger = logging.getLogger("ranking_service")


# ---------------------------------------------------------------------------
# Normalization helpers — pure functions, no side effects
# ---------------------------------------------------------------------------

def norm_lower_is_better(val: float, best_val: float, worst_val: float) -> float:
    """Maps val to [0.0, 1.0] where lower raw values are better."""
    if val <= best_val:
        return 1.0
    if val >= worst_val:
        return 0.0
    return (worst_val - val) / (worst_val - best_val)


def norm_higher_is_better(val: float, worst_val: float, best_val: float) -> float:
    """Maps val to [0.0, 1.0] where higher raw values are better."""
    if val >= best_val:
        return 1.0
    if val <= worst_val:
        return 0.0
    return (val - worst_val) / (best_val - worst_val)


def norm_zoning(val: Any) -> float:
    """Industrial zoning is optimal for warehouse siting; commercial is acceptable."""
    val_str = str(val).lower()
    if "ind" in val_str or "industrial" in val_str:
        return 1.0
    if "comm" in val_str or "commercial" in val_str:
        return 0.5
    return 0.1


def norm_boolean_false_is_best(val: Any) -> float:
    """Floodplain/hazard boolean: False (not present) is best (1.0), True is worst (0.0)."""
    if isinstance(val, bool):
        return 1.0 if not val else 0.0
    if isinstance(val, (int, float)):
        return 1.0 if val == 0 else 0.0
    return 0.0


def norm_grading_difficulty(val: Any) -> float:
    """Grading difficulty class: Flat (≤1) is best, Moderate (≤2) is acceptable, Steep is worst."""
    if isinstance(val, (int, float)):
        if val <= 1.0:
            return 1.0
        if val <= 2.0:
            return 0.6
        return 0.2
    val_str = str(val).lower()
    if "flat" in val_str or "low" in val_str or "1" in val_str:
        return 1.0
    if "mod" in val_str or "2" in val_str:
        return 0.6
    return 0.2


def norm_urban_proximity(val: float) -> float:
    """
    Labor proximity heuristic. Optimal band is 1–30km from an urban area.
    Under 1km risks zoning conflicts / high land cost (capped at 0.8).
    Over 30km degrades linearly to 0.0 at 100km.
    """
    if val < 1000.0:
        return 0.8
    if val <= 30000.0:
        return 1.0
    return norm_lower_is_better(val, 30000.0, 100000.0)


# ---------------------------------------------------------------------------
# Data-driven normalization config
# ---------------------------------------------------------------------------
# Each entry maps a field_name → a callable that accepts (raw_value) → float [0,1].
# Adding a new Mireye field only requires adding one line here.

_FIELD_NORMALIZERS: Dict[str, Callable[[Any], float]] = {
    # Transport
    "nearest_major_road_distance_m":
        lambda v: norm_lower_is_better(float(v), 200.0, 10000.0),
    "roads_within_500m_count":
        lambda v: norm_higher_is_better(float(v), 0.0, 5.0),
    "nearest_rail_line_distance_m":
        lambda v: norm_lower_is_better(float(v), 500.0, 20000.0),

    # Power / utility
    "nearest_transmission_line_distance_m":
        lambda v: norm_lower_is_better(float(v), 100.0, 10000.0),
    "nearest_transmission_line_voltage_kv":
        lambda v: norm_higher_is_better(float(v), 10.0, 230.0),
    "nearest_substation_distance_m":
        lambda v: norm_lower_is_better(float(v), 500.0, 15000.0),

    # Buildability
    "parcel_zoning":       norm_zoning,
    "parcel_area_m2":      lambda v: norm_higher_is_better(float(v), 5000.0, 200000.0),
    "developable_acres_proxy": lambda v: norm_higher_is_better(float(v), 1.0, 40.0),
    "grading_difficulty_class": norm_grading_difficulty,

    # Context / labor
    "nearest_urban_area_distance_m": lambda v: norm_urban_proximity(float(v)),
    "housing_units_within_1km":      lambda v: norm_higher_is_better(float(v), 10.0, 1000.0),
    "housing_units_density_per_km2": lambda v: norm_higher_is_better(float(v), 5.0, 500.0),

    # Hazards
    "wildfire_annual_frequency":  lambda v: norm_lower_is_better(float(v), 0.0001, 0.01),
    "within_floodplain_polygon":  norm_boolean_false_is_best,
    "seismic_pga_2pct_50yr_g":    lambda v: norm_lower_is_better(float(v), 0.05, 0.8),
    "design_wind_speed_mph":      lambda v: norm_lower_is_better(float(v), 90.0, 150.0),
}


class ScoringRankingEngine:
    @staticmethod
    def normalize_field(field_name: str, val: Any) -> float:
        """
        Normalizes a raw Mireye field value to a 0.0–1.0 score
        where 1.0 is optimal for warehouse siting.
        Dispatches via the data-driven _FIELD_NORMALIZERS config table.
        """
        if val is None:
            return 0.0

        normalizer = _FIELD_NORMALIZERS.get(field_name)
        if normalizer is None:
            # Unknown field — return neutral score rather than silently failing
            logger.warning(f"No normalizer configured for field '{field_name}'; defaulting to 0.5")
            return 0.5

        try:
            return normalizer(val)
        except (ValueError, TypeError) as e:
            logger.error(f"Error normalizing field '{field_name}' with value {val!r}: {e}")
            return 0.0

    @classmethod
    def calculate_scores(
        cls,
        results: Dict[str, Dict[str, Any]],
        weights: Dict[str, float],
    ) -> Tuple[Dict[str, float], Optional[float], float]:
        """
        Calculates per-dimension normalized scores, enforces the 50% completeness floor,
        redistributes weights for entirely missing dimensions, and computes the composite score.

        Returns:
            Tuple[dimension_scores_dict, composite_score_or_None, data_completeness_pct]
        """
        # 1. Data completeness — fraction of expected fields that are present
        total_field_count = sum(len(fields) for fields in FIELD_DIMENSIONS.values())
        present_field_count = sum(
            1 for field_detail in results.values() if field_detail.get("present", False)
        )
        data_completeness_pct = (present_field_count / total_field_count) * 100.0

        # 2. Score each dimension by averaging the normalized scores of present sub-fields
        dimension_scores: Dict[str, float] = {}
        for dim_name, dim_fields in FIELD_DIMENSIONS.items():
            present_scores = [
                cls.normalize_field(field, results[field].get("value"))
                for field in dim_fields
                if results.get(field, {}).get("present", False)
            ]
            # Entire dimension missing → score is 0.0 (excluded from composite below)
            dimension_scores[dim_name] = (
                sum(present_scores) / len(present_scores) if present_scores else 0.0
            )

        # 3. Enforce the 50% completeness floor — site is unrankable below this threshold
        if data_completeness_pct < 50.0:
            logger.warning(
                f"Data completeness ({data_completeness_pct:.1f}%) is below the 50% floor. "
                "Excluding site from composite score ranking."
            )
            return dimension_scores, None, data_completeness_pct

        # 4. Composite score — redistribute weight from fully-missing dimensions
        #    Only dimensions with at least one present field contribute to the composite.
        evaluated_dims = [dim for dim, score in dimension_scores.items() if score > 0.0]

        active_weights = {
            dim: weights.get(f"{dim}_weight", 0.2)
            for dim in evaluated_dims
        }
        total_active_weight = sum(active_weights.values())

        if total_active_weight == 0:
            return dimension_scores, None, data_completeness_pct

        # Normalize active weights so they sum to 1.0 before computing composite
        composite_score = round(
            sum(
                dimension_scores[dim] * (active_weights[dim] / total_active_weight)
                for dim in evaluated_dims
            ),
            3,
        )

        return dimension_scores, composite_score, data_completeness_pct

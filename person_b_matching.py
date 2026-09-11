"""
matching.py
Person B's module: Haversine distance + ranking/scoring logic.

Deliberately has ZERO dependency on FastAPI, SQLite, or any web framework.
Person B can develop and unit-test this file completely independently of
Person A finishing the backend. main.py just imports the two public
functions at the bottom (rank_resource_matches / rank_referral_matches)
and passes in plain dicts pulled from the DB.
"""

from __future__ import annotations
from dataclasses import dataclass
from math import radians, sin, cos, sqrt, atan2
from typing import List, Dict, Any

# ---------------------------------------------------------------------------
# Urgency weighting — tune these two numbers and every score in the demo
# shifts accordingly. Kept as module-level constants so they're easy to find
# and easy to justify to judges ("critical requests are weighted 4x low").
# ---------------------------------------------------------------------------
URGENCY_WEIGHT = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lng points, in kilometers."""
    lat1_r, lon1_r, lat2_r, lon2_r = map(radians, (lat1, lon1, lat2, lon2))
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = sin(dlat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return EARTH_RADIUS_KM * c


@dataclass
class RankedMatch:
    hospital_id: int
    name: str
    lat: float
    lng: float
    distance_km: float
    score: float
    quantity_available: int | None = None
    available_capacity: int | None = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "hospital_id": self.hospital_id,
            "name": self.name,
            "lat": self.lat,
            "lng": self.lng,
            "distance_km": round(self.distance_km, 1),
            "score": round(self.score, 2),
        }
        if self.quantity_available is not None:
            d["quantity_available"] = self.quantity_available
        if self.available_capacity is not None:
            d["available_capacity"] = self.available_capacity
        return d


def _distance_decay(distance_km: float, max_relevant_km: float = 50.0) -> float:
    """
    Returns a multiplier in (0, 1] that shrinks as distance grows.
    At distance 0 -> 1.0. At max_relevant_km -> 0.5. Never hits zero,
    so a far-away hospital with huge availability can still outrank a
    close one with almost nothing — which is the behavior we want.
    """
    return max_relevant_km / (max_relevant_km + distance_km)


def score_resource_match(
    urgency: str,
    quantity_needed: int,
    quantity_available: int,
    distance_km: float,
) -> float:
    """
    Higher is better. Combines:
      - urgency of the requesting hospital (critical requests should
        surface hospitals even if they're a bit further away)
      - how well the offer covers what's needed (capped at 1.5x need,
        so hoarding 500 units doesn't drown out a hospital with exactly
        enough)
      - distance decay (closer is better, but not an on/off cliff)
    """
    urgency_component = URGENCY_WEIGHT.get(urgency, 1) * 10
    coverage_ratio = min(quantity_available / max(quantity_needed, 1), 1.5)
    coverage_component = coverage_ratio * 15
    proximity_component = _distance_decay(distance_km) * 20
    return urgency_component + coverage_component + proximity_component


def score_referral_match(
    urgency: str,
    available_capacity: int,
    distance_km: float,
) -> float:
    """
    Same shape as score_resource_match but for patient referrals, where
    there's no "quantity needed" — just "does this hospital have room,
    and can the patient realistically get there."
    """
    urgency_component = URGENCY_WEIGHT.get(urgency, 1) * 10
    capacity_component = min(available_capacity, 10) * 3
    proximity_component = _distance_decay(distance_km) * 20
    return urgency_component + capacity_component + proximity_component


def rank_resource_matches(
    request: Dict[str, Any],
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    request: {"lat": float, "lng": float, "urgency": str, "quantity_needed": int}
        (lat/lng here = the REQUESTING hospital's location)
    candidates: list of hospitals that HAVE the requested resource_type in
        stock, each: {"hospital_id", "name", "lat", "lng", "quantity_available"}

    Returns candidates sorted best-first, as plain dicts ready for JSON.
    """
    results = []
    for c in candidates:
        dist = haversine_km(request["lat"], request["lng"], c["lat"], c["lng"])
        score = score_resource_match(
            urgency=request["urgency"],
            quantity_needed=request["quantity_needed"],
            quantity_available=c["quantity_available"],
            distance_km=dist,
        )
        results.append(
            RankedMatch(
                hospital_id=c["hospital_id"],
                name=c["name"],
                lat=c["lat"],
                lng=c["lng"],
                distance_km=dist,
                score=score,
                quantity_available=c["quantity_available"],
            )
        )
    results.sort(key=lambda r: r.score, reverse=True)
    return [r.to_dict() for r in results]


def rank_referral_matches(
    referral: Dict[str, Any],
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    referral: {"lat": float, "lng": float, "urgency": str,
               "preferred_radius_km": float | None}
        (lat/lng here = the REFERRING hospital's location)
    candidates: hospitals that have the required_facility capability,
        each: {"hospital_id", "name", "lat", "lng", "available_capacity"}

    If preferred_radius_km is set, candidates outside it are dropped
    entirely (a "must be within X km" hard filter) rather than merely
    down-weighted — a referral has a real ambulance-transport limit that
    a resource pickup doesn't.
    """
    radius = referral.get("preferred_radius_km")
    results = []
    for c in candidates:
        dist = haversine_km(referral["lat"], referral["lng"], c["lat"], c["lng"])
        if radius is not None and dist > radius:
            continue
        score = score_referral_match(
            urgency=referral["urgency"],
            available_capacity=c["available_capacity"],
            distance_km=dist,
        )
        results.append(
            RankedMatch(
                hospital_id=c["hospital_id"],
                name=c["name"],
                lat=c["lat"],
                lng=c["lng"],
                distance_km=dist,
                score=score,
                available_capacity=c["available_capacity"],
            )
        )
    results.sort(key=lambda r: r.score, reverse=True)
    return [r.to_dict() for r in results]
    
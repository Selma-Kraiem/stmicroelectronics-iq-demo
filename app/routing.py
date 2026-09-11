"""Deterministic V1 orchestration routes used by the presenter and Hosted Agent."""

from __future__ import annotations

import re

RADAR_ONLY = "RADAR_ONLY"
FAB_ONLY = "FAB_ONLY"
FULL_ASSESSMENT = "FULL_ASSESSMENT"

_PUBLIC_TERMS = {
    "public",
    "regulatory",
    "regulation",
    "weather",
    "market",
    "supply",
    "logistics",
    "news",
    "policy",
    "european",
    "delivery",
    "deliveries",
    "export",
}
_EXPOSURE_TERMS = {
    "blocked",
    "field exposure",
    "in field",
    "shipment",
    "shipments",
    "stock",
    "blockable",
    "units in field",
    "shipped percentage",
}
_FAB_TERMS = {
    "lot",
    "wafer",
    "tester",
    "recipe",
    "vth",
    "root cause",
    "fabric",
    "ontology",
    "quality",
    "containment",
    "procedure",
    "fmea",
    "telemetry",
    "inventory",
    "customer",
    "sharepoint",
    "onedrive",
    "work iq",
    "8d",
}
_COMPOSITE_TERMS = {
    "assessment",
    "assess",
    "brief",
    "compile",
    "executive update",
    "evidence trace",
    "teams-ready",
}


def _contains_any(text: str, terms: set[str]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) for term in terms)


def explicit_route_header(request: str) -> str | None:
    """Read a trusted route only from an exact first-line protocol header."""
    first_line = request.splitlines()[0].strip().upper() if request.splitlines() else ""
    route = first_line.removeprefix("ROUTE=")
    return route if first_line == f"ROUTE={route}" and route in {
        RADAR_ONLY,
        FAB_ONLY,
        FULL_ASSESSMENT,
    } else None


def select_orchestration_route(query: str) -> str:
    """Select only the evidence domains required by the user's request."""
    normalized = " ".join(query.lower().split())
    has_public = _contains_any(normalized, _PUBLIC_TERMS)
    has_exposure = _contains_any(normalized, _EXPOSURE_TERMS)
    has_fab = _contains_any(normalized, _FAB_TERMS)
    has_composite_intent = _contains_any(normalized, _COMPOSITE_TERMS)
    if has_composite_intent and (has_public or has_exposure or has_fab):
        return FULL_ASSESSMENT
    if has_public and (has_exposure or has_fab):
        return FULL_ASSESSMENT
    if has_public and not has_exposure and not has_fab:
        return RADAR_ONLY
    if has_exposure or has_fab:
        return FAB_ONLY
    return FULL_ASSESSMENT

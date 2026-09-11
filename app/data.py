"""Deterministic synthetic operational data; no customer or production data is used."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

DEMO_SEED = 20260813


@dataclass(frozen=True)
class ScenarioData:
    seed: int
    plants: list[dict]
    lots: list[dict]
    products: list[dict]
    customers: list[dict]
    orders: list[dict]
    telemetry: list[dict]
    incidents: list[dict]
    inventory: list[dict]
    procedures: list[dict]


def build_demo_data(seed: int = DEMO_SEED) -> ScenarioData:
    """Return the same safe, fictional dataset for every run of a seed."""
    rng = Random(seed)
    plants = [
        {"id": "ST-CAT", "name": "Catania SIC Campus", "region": "Italy"},
        {"id": "ST-ANG", "name": "Ang Mo Kio Assembly", "region": "Singapore"},
    ]
    products = [
        {
            "id": "SCTW90N65G2V",
            "name": "Synthetic automotive SiC MOSFET",
            "technology": "silicon-carbide",
        },
        {
            "id": "SIC-MOD-1200-450",
            "name": "ST SiC traction power module 1200V / 450A",
            "technology": "silicon-carbide",
        },
    ]
    lots = [
        {
            "id": "SiC-AUTO-2451",
            "plant_id": "ST-CAT",
            "product_id": "SCTW90N65G2V",
            "quantity": 38700,
            "status": "quarantine",
        },
        {
            "id": "SiC-AUTO-2452",
            "plant_id": "ST-CAT",
            "product_id": "SCTW90N65G2V",
            "quantity": 520,
            "status": "released",
        },
        {
            "id": "CAT-26-0813-A",
            "plant_id": "ST-CAT",
            "product_id": "SIC-MOD-1200-450",
            "quantity": 480,
            "status": "quarantine",
        },
    ]
    customers = [
        {"id": "CUST-ALPHA", "name": "AutoTier1-Alpha (fictional)", "tier": "Tier-1"},
        {"id": "CUST-BETA", "name": "AutoTier1-Beta (fictional)", "tier": "Tier-1"},
        {"id": "CUST-ORION", "name": "Orion Mobility (fictional)", "tier": "strategic"},
        {"id": "CUST-NOVA", "name": "Nova Drive Systems (fictional)", "tier": "standard"},
    ]
    orders = [
        {
            "id": "SHIP-001",
            "customer_id": "CUST-ALPHA",
            "lot_id": "SiC-AUTO-2451",
            "quantity": 12000,
        },
        {"id": "SHIP-002", "customer_id": "CUST-BETA", "lot_id": "SiC-AUTO-2451", "quantity": 6500},
        {
            "id": "SO-41028",
            "customer_id": "CUST-ORION",
            "lot_id": "CAT-26-0813-A",
            "quantity": 180,
        },
        {
            "id": "SO-41031",
            "customer_id": "CUST-NOVA",
            "lot_id": "CAT-26-0813-A",
            "quantity": 120,
        },
    ]
    telemetry = [
        {
            "id": "TEL-7781",
            "lot_id": "SiC-AUTO-2451",
            "metric": "Vth_V",
            "value": round(4.08 + rng.random() * 0.02, 2),
            "threshold": 3.8,
            "observed_at": "2026-08-30T12:42:00Z",
        },
        {
            "id": "TEL-V2-7781",
            "lot_id": "CAT-26-0813-A",
            "metric": "gate_oxide_leakage_uA",
            "value": round(8.6 + rng.random(), 2),
            "threshold": 5.0,
            "observed_at": "2026-08-13T12:42:00Z",
        },
    ]
    incidents = [
        {
            "id": "SIC-QI-2451",
            "severity": "SEV-1",
            "title": "Automotive SiC MOSFET Vth parametric excursion",
            "affected_lot": "SiC-AUTO-2451",
            "opened_at": "2026-08-30T12:50:00Z",
        },
        {
            "id": "INC-SIC-0813",
            "severity": "SEV-1",
            "title": "Elevated leakage signal on SiC module final test",
            "affected_lot": "CAT-26-0813-A",
            "opened_at": "2026-08-13T12:50:00Z",
        },
    ]
    inventory = [
        {"site": "ST-ANG", "product_id": "SIC-MOD-1200-450", "available": 210, "allocated": 80},
        {"site": "ST-CAT", "product_id": "SIC-MOD-1200-450", "available": 360, "allocated": 0},
    ]
    procedures = [
        {
            "id": "PROC-SIC-17",
            "title": "SiC containment and traceability procedure",
            "excerpt": (
                "Quarantine the suspect lot and adjacent T-07 lots, block inventory, preserve "
                "e-test traces, and notify affected EV-traction customer owners."
            ),
        }
    ]
    return ScenarioData(
        seed=seed,
        plants=plants,
        lots=lots,
        products=products,
        customers=customers,
        orders=orders,
        telemetry=telemetry,
        incidents=incidents,
        inventory=inventory,
        procedures=procedures,
    )

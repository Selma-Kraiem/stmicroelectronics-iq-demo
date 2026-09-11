# %% [markdown]
# ST IQ Fabric ontology seed (synthetic demo data)
#
# Run this file as a Fabric Python notebook or locally. It produces deterministic
# entity and relationship tables. Every customer, lot, order, incident, and
# telemetry record is fictional. Seed: 20260813.

# %%
from __future__ import annotations

import json
from pathlib import Path
from random import Random

SEED = 20260813
OUTPUT = Path("data/fabric_seed")
OUTPUT.mkdir(parents=True, exist_ok=True)
rng = Random(SEED)

# %%
entities = {
    "plants": [
        {"plant_id": "ST-CAT", "name": "Catania SiC Campus", "country": "Italy"},
        {"plant_id": "ST-ANG", "name": "Ang Mo Kio Assembly", "country": "Singapore"},
    ],
    "products": [
        {
            "product_id": "SIC-MOD-1200-450",
            "name": "Synthetic SiC traction module 1200V / 450A",
            "technology": "silicon-carbide",
        }
    ],
    "lots": [
        {
            "lot_id": "CAT-26-0813-A",
            "plant_id": "ST-CAT",
            "product_id": "SIC-MOD-1200-450",
            "status": "quarantine",
            "quantity": 480,
        },
        {
            "lot_id": "CAT-26-0813-B",
            "plant_id": "ST-CAT",
            "product_id": "SIC-MOD-1200-450",
            "status": "released",
            "quantity": 520,
        },
    ],
    "customers": [
        {"customer_id": "CUST-ORION", "name": "Orion Mobility (fictional)"},
        {"customer_id": "CUST-NOVA", "name": "Nova Drive Systems (fictional)"},
    ],
    "orders": [
        {
            "order_id": "SO-41028",
            "customer_id": "CUST-ORION",
            "lot_id": "CAT-26-0813-A",
            "quantity": 180,
        },
        {
            "order_id": "SO-41031",
            "customer_id": "CUST-NOVA",
            "lot_id": "CAT-26-0813-A",
            "quantity": 120,
        },
    ],
    "telemetry": [
        {
            "telemetry_id": "TEL-7781",
            "lot_id": "CAT-26-0813-A",
            "metric": "gate_oxide_leakage_uA",
            "value": round(8.6 + rng.random(), 2),
            "threshold": 5.0,
            "observed_at": "2026-08-13T12:42:00Z",
        }
    ],
    "incidents": [
        {
            "incident_id": "INC-SIC-0813",
            "lot_id": "CAT-26-0813-A",
            "severity": "SEV-1",
            "status": "contained",
        }
    ],
    "inventory": [
        {
            "inventory_id": "INV-ANG-01",
            "plant_id": "ST-ANG",
            "product_id": "SIC-MOD-1200-450",
            "available": 210,
            "allocated": 80,
        },
        {
            "inventory_id": "INV-CAT-02",
            "plant_id": "ST-CAT",
            "product_id": "SIC-MOD-1200-450",
            "available": 360,
            "allocated": 0,
        },
    ],
}

relationships = [
    {
        "from_type": "Incident",
        "from_id": "INC-SIC-0813",
        "relation": "affects",
        "to_type": "Lot",
        "to_id": "CAT-26-0813-A",
    },
    {
        "from_type": "Lot",
        "from_id": "CAT-26-0813-A",
        "relation": "manufacturedAt",
        "to_type": "Plant",
        "to_id": "ST-CAT",
    },
    {
        "from_type": "Lot",
        "from_id": "CAT-26-0813-A",
        "relation": "contains",
        "to_type": "Product",
        "to_id": "SIC-MOD-1200-450",
    },
    {
        "from_type": "Order",
        "from_id": "SO-41028",
        "relation": "drawsFrom",
        "to_type": "Lot",
        "to_id": "CAT-26-0813-A",
    },
    {
        "from_type": "Order",
        "from_id": "SO-41031",
        "relation": "drawsFrom",
        "to_type": "Lot",
        "to_id": "CAT-26-0813-A",
    },
    {
        "from_type": "Order",
        "from_id": "SO-41028",
        "relation": "placedBy",
        "to_type": "Customer",
        "to_id": "CUST-ORION",
    },
    {
        "from_type": "Order",
        "from_id": "SO-41031",
        "relation": "placedBy",
        "to_type": "Customer",
        "to_id": "CUST-NOVA",
    },
]

# %%
for name, rows in entities.items():
    (OUTPUT / f"{name}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
(OUTPUT / "relationships.json").write_text(
    json.dumps(relationships, indent=2), encoding="utf-8"
)
(OUTPUT / "manifest.json").write_text(
    json.dumps(
        {
            "seed": SEED,
            "classification": "synthetic-demo-only",
            "entities": sorted(entities),
            "relationships": "relationships.json",
        },
        indent=2,
    ),
    encoding="utf-8",
)
print(f"Wrote deterministic Fabric ontology seed to {OUTPUT.resolve()}")

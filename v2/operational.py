"""Deterministic operational domain used by the two structured V2 APIs."""

from __future__ import annotations

from typing import Any

from app.data import ScenarioData, build_demo_data


class OperationalDomain:
    """Resolve telemetry and commercial exposure without vector retrieval."""

    def __init__(self, data: ScenarioData | None = None) -> None:
        self.data = data or build_demo_data()
        self.equipment = {
            "EQ-CAT-FT-07": {
                "id": "EQ-CAT-FT-07",
                "name": "SiC final-test cell 07",
                "plant_id": "ST-CAT",
                "status": "inspection-required",
            }
        }

    def telemetry_for_lot(self, lot_id: str) -> dict[str, Any]:
        lot = next((item for item in self.data.lots if item["id"] == lot_id), None)
        if lot is None:
            raise KeyError(lot_id)
        observations = [
            {
                **item,
                "equipment_id": "EQ-CAT-FT-07",
                "exceeded": item["value"] > item["threshold"],
            }
            for item in self.data.telemetry
            if item["lot_id"] == lot_id
        ]
        return {
            "lot": lot,
            "equipment": self.equipment["EQ-CAT-FT-07"],
            "observations": observations,
            "anomaly_count": sum(item["exceeded"] for item in observations),
            "data_classification": "synthetic-demo-only",
            "seed": self.data.seed,
        }

    def exposure_for_lot(self, lot_id: str) -> dict[str, Any]:
        lot = next((item for item in self.data.lots if item["id"] == lot_id), None)
        if lot is None:
            raise KeyError(lot_id)
        customer_names = {item["id"]: item["name"] for item in self.data.customers}
        orders = [
            {**order, "customer": customer_names[order["customer_id"]]}
            for order in self.data.orders
            if order["lot_id"] == lot_id
        ]
        reallocation = sum(
            item["available"] - item["allocated"] for item in self.data.inventory
        )
        demand = sum(item["quantity"] for item in orders)
        return {
            "lot": lot,
            "affected_orders": orders,
            "affected_customer_count": len({item["customer_id"] for item in orders}),
            "affected_units": demand,
            "available_reallocation": reallocation,
            "coverage_gap": max(0, demand - reallocation),
            "inventory": self.data.inventory,
            "knowledge_path": [
                "Incident",
                "Lot",
                "Product",
                "SalesOrder",
                "Customer",
                "Inventory",
            ],
            "data_classification": "synthetic-demo-only",
            "seed": self.data.seed,
        }

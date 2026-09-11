from fastapi.testclient import TestClient

from v2.api.common import ApiRuntime
from v2.api.exposure import create_app as create_exposure_app
from v2.api.telemetry import create_app as create_telemetry_app

HEADERS = {"X-STIQ-API-Key": "test-key", "X-Correlation-ID": "corr-test"}


def test_telemetry_api_requires_auth_and_returns_provenance() -> None:
    with TestClient(create_telemetry_app(ApiRuntime("test-key"))) as client:
        assert client.get("/api/v2/telemetry/lots/CAT-26-0813-A").status_code == 401
        response = client.get(
            "/api/v2/telemetry/lots/CAT-26-0813-A",
            headers=HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["correlation_id"] == "corr-test"
    assert body["source"] == "Manufacturing Telemetry API"
    assert body["data_classification"] == "synthetic-demo-only"
    assert body["anomaly_count"] == 1
    assert body["observations"][0]["exceeded"] is True


def test_exposure_api_resolves_customer_inventory_path() -> None:
    with TestClient(create_exposure_app(ApiRuntime("test-key"))) as client:
        response = client.get(
            "/api/v2/exposure/lots/CAT-26-0813-A",
            headers=HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["affected_units"] == 300
    assert body["available_reallocation"] == 490
    assert body["coverage_gap"] == 0
    assert all(item["customer"].endswith("(fictional)") for item in body["affected_orders"])
    assert body["knowledge_path"] == [
        "Incident",
        "Lot",
        "Product",
        "SalesOrder",
        "Customer",
        "Inventory",
    ]


def test_operational_apis_return_404_for_unknown_lot() -> None:
    with TestClient(create_telemetry_app(ApiRuntime("test-key"))) as client:
        response = client.get("/api/v2/telemetry/lots/UNKNOWN", headers=HEADERS)
    assert response.status_code == 404

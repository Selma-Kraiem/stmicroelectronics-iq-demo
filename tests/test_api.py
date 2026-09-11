from __future__ import annotations

import asyncio
import os

from fastapi.testclient import TestClient

os.environ.pop("STIQ_LIVE_MODE", None)
from app.main import app  # noqa: E402


def complete(client: TestClient) -> tuple[str, dict]:
    run_id = client.post("/api/scenarios").json()["id"]
    for _ in range(30):
        response = client.get(f"/api/scenarios/{run_id}/result")
        if response.status_code == 200:
            return run_id, response.json()
        asyncio.run(asyncio.sleep(0.03))
    raise AssertionError("assessment did not complete")


def test_preflight_reports_degraded_demo_adapters() -> None:
    with TestClient(app) as client:
        body = client.get("/api/preflight").json()
    assert body["mode"] == "demo"
    assert body["seed"] == 20260813
    assert {item["name"] for item in body["adapters"]} >= {
        "Adaptive Foundry workflow",
        "Shipment exposure calculation",
        "Fabric IQ ontology",
        "SharePoint Knowledge",
        "Work IQ delegated context",
    }
    assert any(
        item["state"] in {"degraded", "blocked"} for item in body["adapters"]
    )


def test_assessment_contract_includes_provenance_and_customer_impact() -> None:
    with TestClient(app) as client:
        run_id, result = complete(client)
        assert client.get(f"/api/scenarios/{run_id}").json()["status"] == "completed"
    assert result["mode"] == "demo"
    assert result["incident"]["affected_lot"] == "SiC-AUTO-2451"
    assert result["brief"]["field_impact"]["units_in_field"] == 22500
    assert result["brief"]["field_impact"]["blockable_stock"] == 13200
    assert result["brief"]["field_impact"]["containment_perimeter_pct"] == 65.9
    assert result["agent_outputs"]["fab_intelligence"]["suspect_tester"] == "T-07"
    assert result["evidence_trace"]["completed"] == result["evidence_trace"]["total"]
    assert {item["badge"] for item in result["citations"]} >= {
        "Synthetic workbook",
        "Fabric IQ fallback",
        "Foundry IQ fallback",
        "Work IQ fallback",
    }
    assert result["teams_update"]["delivery"] == "dry-run"
    teams_text = result["teams_update"]["text"]
    assert "<h2>🚨 Critical quality alert</h2>" in teams_text
    assert "<strong>22,500</strong> units already in the field" in teams_text
    assert "<h3>🛑 Immediate containment actions</h3>" in teams_text
    assert "<li><strong>Lot hold</strong>" in teams_text
    assert "[DRY RUN]" not in teams_text


def test_teams_stays_dry_run_without_explicit_opt_in() -> None:
    with TestClient(app) as client:
        run_id, _ = complete(client)
        response = client.post(f"/api/scenarios/{run_id}/teams", json={"explicit_opt_in": False})
    assert response.status_code == 200
    assert response.json() == {
        "sent": False,
        "mode": "dry-run",
        "reason": "Explicit opt-in was not supplied.",
    }


def test_chat_and_history_support_presenter_experience() -> None:
    objective = "Assess fictional SiC lot exposure and prepare a cited containment brief."
    with TestClient(app) as client:
        chat = client.post("/api/chat", json={"message": "What is the containment procedure?"})
        run = client.post(
            "/api/scenarios",
            json={"objective": objective, "include_work_iq": True},
        ).json()
        history = client.get("/api/scenarios").json()["items"]

    assert chat.status_code == 200
    assert chat.json()["mode"] == "demo"
    assert chat.json()["route"] == "fab_only"
    assert [step["agent"] for step in chat.json()["trajectory"]] == ["Fab Intelligence"]
    assert run["objective"] == objective
    assert run["include_work_iq"] is True
    assert history[0]["id"] == run["id"]
    assert history[0]["objective"] == objective


def test_external_chat_activates_only_radar() -> None:
    with TestClient(app) as client:
        chat = client.post(
            "/api/chat",
            json={
                "message": (
                    "What current public regulatory, weather, market, or supply developments "
                    "could affect European automotive silicon-carbide module deliveries?"
                )
            },
        )

    assert chat.status_code == 200
    assert chat.json()["route"] == "radar_only"
    assert [step["agent"] for step in chat.json()["trajectory"]] == ["Radar"]
    assert "no internal or delegated source" in chat.json()["answer"]


def test_presenter_routes_serve_the_single_page_application() -> None:
    with TestClient(app) as client:
        for path in ("/", "/chat", "/tasks", "/history", "/evaluation"):
            response = client.get(path)
            assert response.status_code == 200
            assert "ST IQ Operations Assistant" in response.text


def test_evaluation_defaults_to_public_not_run_template() -> None:
    with TestClient(app) as client:
        response = client.get("/api/evaluation")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not-run"
    assert body["candidates"] == []
    assert body["optimizer"]["state"] == "blocked"
    assert "public source tree" in body["optimizer"]["reason"].lower()


def test_internal_tools_require_api_key_and_return_structured_evidence(
    monkeypatch,
) -> None:
    monkeypatch.setenv("STIQ_INTERNAL_API_KEY", "unit-test-internal-key")
    with TestClient(app) as client:
        rejected = client.get("/internal/onedrive/lots/SiC-AUTO-2451/exposure")
        accepted = client.get(
            "/internal/onedrive/lots/SiC-AUTO-2451/exposure",
            headers={"X-STIQ-API-Key": "unit-test-internal-key"},
        )
        unknown = client.get(
            "/internal/fabric/lots/unknown",
            headers={"X-STIQ-API-Key": "unit-test-internal-key"},
        )

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["units_in_field"] == 22500
    assert accepted.json()["citation"]["badge"] == "Synthetic workbook"
    assert unknown.status_code == 404

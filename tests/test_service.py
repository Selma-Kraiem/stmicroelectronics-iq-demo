from __future__ import annotations

import asyncio
import json
from dataclasses import replace

from app.adapters import Citation
from app.config import Settings
from app.data import build_demo_data
from app.service import AssessmentService


def live_settings() -> Settings:
    return replace(
        Settings.from_env(),
        demo_mode=False,
        fabric_iq_mcp_endpoint="https://fabric.example.test/mcp",
        fabric_iq_tool_name="search_ontology",
        fabric_iq_tool_arguments_json='{"query": "SiC-AUTO-2451"}',
        fabric_iq_access_token="delegated-token",
    )


def test_external_chat_never_queries_fabric(monkeypatch) -> None:
    service = AssessmentService(live_settings(), build_demo_data())
    envelope = {
        "route": "radar_only",
        "answer": "Public context",
        "activated_agents": ["Radar"],
        "sources": [
            {
                "title": "",
                "url": "https://digital-strategy.ec.europa.eu/en/policies/european-chips-act",
                "source_type": "",
                "badge": "",
                "excerpt": "",
            }
        ],
        "result": {},
    }

    async def fail_fabric() -> dict:
        raise AssertionError("External-only chat must not query Fabric IQ.")

    async def retrieve(_: str) -> list[Citation]:
        return [
            Citation(
                "hosted-agent",
                "Foundry",
                "mcp://agent",
                "hosted",
                "live",
                json.dumps(envelope),
            )
        ]

    monkeypatch.setattr(service.fabric, "assess_impact", fail_fabric)
    monkeypatch.setattr(service.foundry, "retrieve", retrieve)

    response = asyncio.run(
        service.chat(
            "What public regulatory, weather, market, or supply developments affect deliveries?"
        )
    )

    assert response["route"] == "radar_only"
    assert [step["agent"] for step in response["trajectory"]] == ["Radar"]
    assert response["sources"][0] == {
        "title": "European Commission Digital Strategy",
        "url": "https://digital-strategy.ec.europa.eu/en/policies/european-chips-act",
        "source_type": "public-web",
        "badge": "Web Knowledge Source (Web IQ fallback)",
        "excerpt": "Public evidence retrieved by Radar for the current assessment.",
    }


def test_fab_chat_delegates_fabric_selection_to_hosted_tool_search(monkeypatch) -> None:
    service = AssessmentService(live_settings(), build_demo_data())
    envelope = {
        "route": "fab_only",
        "answer": "Internal finding",
        "activated_agents": ["Fab Intelligence"],
        "sources": [],
        "result": {
            "agent": "Fab Intelligence",
            "root_cause_probable": "Live ontology root cause",
            "suspect_tester": "T-07",
            "suspect_recipe": "R-GOX-12",
            "source_modes": {
                "fabric_iq": "Fabric IQ live",
                "foundry_iq": "not-activated",
                "work_iq_onedrive": "not-activated",
            },
            "citations": [
                {
                    "title": "ST IQ Semiconductor Operations",
                    "url": "https://fabric.example.test/ontology",
                    "source_type": "live Microsoft Fabric ontology",
                    "badge": "Fabric IQ live",
                    "excerpt": "Live causal trace.",
                }
            ],
        },
    }
    prompts: list[str] = []

    async def assess_impact() -> dict:
        raise AssertionError("The presenter must not pre-query Fabric IQ.")

    async def retrieve(prompt: str) -> list[Citation]:
        prompts.append(prompt)
        return [
            Citation(
                "hosted-agent",
                "Foundry",
                "mcp://agent",
                "hosted",
                "live",
                json.dumps(envelope),
            )
        ]

    monkeypatch.setattr(service.fabric, "assess_impact", assess_impact)
    monkeypatch.setattr(service.foundry, "retrieve", retrieve)

    response = asyncio.run(service.chat("Which lot and tester caused the Vth excursion?"))
    structured = response["structured"]

    assert "ORCHESTRATOR_FABRIC_IQ_EVIDENCE=" not in prompts[0]
    assert structured["result"]["source_modes"]["fabric_iq"] == "Fabric IQ live"
    assert structured["result"]["suspect_tester"] == "T-07"
    assert structured["result"]["citations"][0]["badge"] == "Fabric IQ live"


def test_exposure_only_chat_does_not_query_fabric(monkeypatch) -> None:
    service = AssessmentService(live_settings(), build_demo_data())
    envelope = {
        "route": "fab_only",
        "answer": "44,900 units are in field.",
        "activated_agents": ["Fab Intelligence"],
        "sources": [{"title": "Workbook", "source_type": "synthetic shipment workbook"}],
        "result": {
            "agent": "Fab Intelligence",
            "field_exposure": 44900,
            "blockable_stock": 13200,
            "impacted_customers": [],
            "containment_perimeter_pct": 65.9,
            "source_modes": {
                "fabric_iq": "not-activated",
                "foundry_iq": "not-activated",
                "work_iq_onedrive": "Agent Framework Python function (synthetic workbook)",
            },
            "citations": [],
        },
    }

    async def fail_fabric() -> dict:
        raise AssertionError("Exposure-only chat must not query Fabric IQ.")

    async def retrieve(_: str) -> list[Citation]:
        return [
            Citation(
                "hosted-agent",
                "Foundry",
                "mcp://agent",
                "hosted",
                "live",
                json.dumps(envelope),
            )
        ]

    monkeypatch.setattr(service.fabric, "assess_impact", fail_fabric)
    monkeypatch.setattr(service.foundry, "retrieve", retrieve)

    response = asyncio.run(
        service.chat("Quantify blockable inventory and field exposure for SiC-AUTO-2451.")
    )

    assert response["route"] == "fab_only"
    assert response["answer"].startswith("22,500 units are in field")
    assert not response["answer"].startswith("{")
    assert response["structured"]["result"]["field_exposure"] == 22500
    assert response["structured"]["result"]["impacted_customers"]
    assert response["sources"][0]["source_type"] == "synthetic shipment workbook"


def test_verified_exposure_falls_back_when_live_onedrive_fails(monkeypatch) -> None:
    service = AssessmentService(live_settings(), build_demo_data())

    async def fail_onedrive() -> dict:
        raise RuntimeError("delegated download rejected")

    monkeypatch.setattr(service.onedrive, "assess_impact", fail_onedrive)

    exposure = asyncio.run(service._verified_exposure())

    assert exposure["source_mode"] == "synthetic-local"
    assert exposure["units_in_field"] == 22500
    assert exposure["live_error"] == "delegated download rejected"

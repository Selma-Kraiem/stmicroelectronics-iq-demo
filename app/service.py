"""Long-running assessment coordination for the local UI and API."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from app.adapters import (
    FabricIQAdapter,
    FoundryKnowledgeAdapter,
    OneDriveWorkbookAdapter,
    OperationalKnowledgeAdapter,
    SharePointKnowledgeAdapter,
    TeamsAdapter,
    WebIQAdapter,
    WorkIQA2AAdapter,
)
from app.config import Settings
from app.data import ScenarioData
from app.routing import FAB_ONLY, FULL_ASSESSMENT, RADAR_ONLY, select_orchestration_route
from app.v1_assets import (
    calculate_field_exposure,
    compile_offline_brief,
    extract_json_object,
    format_teams_incident_update,
    offline_fab_output,
    offline_radar_output,
)


@dataclass
class AssessmentRun:
    id: str
    objective: str
    include_work_iq: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: str = "running"
    progress: int = 0
    stage: str = "Queued"
    events: list[dict] = field(default_factory=list)
    result: dict | None = None

    def event(self, progress: int, stage: str) -> None:
        self.progress, self.stage = progress, stage
        self.events.append(
            {
                "progress": progress,
                "stage": stage,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    def summary(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "stage": self.stage,
            "objective": self.objective,
            "include_work_iq": self.include_work_iq,
            "created_at": self.created_at,
        }


class AssessmentService:
    def __init__(self, settings: Settings, data: ScenarioData):
        self.settings, self.data = settings, data
        self.foundry = FoundryKnowledgeAdapter(settings, data)
        self.web = WebIQAdapter(settings)
        self.operations = OperationalKnowledgeAdapter(settings, data)
        self.onedrive = OneDriveWorkbookAdapter(settings)
        self.fabric = FabricIQAdapter(settings, data)
        self.sharepoint = SharePointKnowledgeAdapter(settings)
        self.workiq = WorkIQA2AAdapter(settings)
        self.teams = TeamsAdapter(settings)
        self.runs: dict[str, AssessmentRun] = {}

    def statuses(self) -> list[dict]:
        return [
            adapter.status().as_dict()
            for adapter in (
                self.foundry,
                self.web,
                self.operations,
                self.onedrive,
                self.fabric,
                self.sharepoint,
                self.workiq,
                self.teams,
            )
        ]

    def start(
        self, objective: str | None = None, *, include_work_iq: bool = False
    ) -> AssessmentRun:
        run = AssessmentRun(
            id=str(uuid4()),
            objective=objective
            or (
                "Assess the current SiC power-module quality incident, identify customer and "
                "production exposure, and produce a cited response brief."
            ),
            include_work_iq=include_work_iq,
        )
        run.event(2, "Assessment queued")
        self.runs[run.id] = run
        asyncio.create_task(self._run(run))
        return run

    def history(self) -> list[dict]:
        return [
            run.summary()
            for run in sorted(self.runs.values(), key=lambda item: item.created_at, reverse=True)
        ]

    @staticmethod
    def _normalize_public_citations(citations: list[dict]) -> list[dict]:
        source_names = {
            "commission.europa.eu": "European Commission",
            "cordis.europa.eu": "CORDIS EU Research",
            "digital-strategy.ec.europa.eu": "European Commission Digital Strategy",
            "ec.europa.eu": "European Commission",
            "newsroom.st.com": "STMicroelectronics Newsroom",
            "publications.jrc.ec.europa.eu": "European Commission Joint Research Centre",
            "www.europarl.europa.eu": "European Parliament",
        }
        normalized = []
        for citation in citations:
            item = dict(citation)
            hostname = urlparse(str(item.get("url", ""))).hostname or ""
            item["title"] = item.get("title") or source_names.get(hostname) or hostname
            item["source_type"] = item.get("source_type") or "public-web"
            item["badge"] = item.get("badge") or "Web Knowledge Source (Web IQ fallback)"
            item["excerpt"] = item.get("excerpt") or (
                "Public evidence retrieved by Radar for the current assessment."
            )
            normalized.append(item)
        return normalized

    @staticmethod
    def _synthetic_procedure_actions() -> list[dict[str, str]]:
        return [
            {
                "owner": "Quality lead",
                "action": "Confirm containment and preserve final-test traces.",
                "source": "synthetic procedure projection",
            },
            {
                "owner": "Supply planner",
                "action": "Hold affected allocations and validate substitute inventory.",
                "source": "synthetic procedure projection",
            },
            {
                "owner": "Account lead",
                "action": "Prepare customer communication after quality confirmation.",
                "source": "synthetic procedure projection",
            },
        ]

    @staticmethod
    def _apply_verified_exposure(
        fab: dict, exposure: dict, *, exposure_only: bool = False
    ) -> None:
        fab.update(
            {
                "field_exposure": exposure["units_in_field"],
                "blockable_stock": exposure["blockable_stock"],
                "impacted_customers": exposure["impacted_customers"],
                "containment_perimeter_pct": exposure["containment_perimeter_pct"],
            }
        )
        fab.setdefault("source_modes", {})["work_iq_onedrive"] = exposure["source_label"]
        citations = [] if exposure_only else [
            citation
            for citation in fab.get("citations", [])
            if citation.get("url") != exposure["citation"]["url"]
        ]
        fab["citations"] = [*citations, exposure["citation"]]

    @staticmethod
    def _apply_verified_exposure_to_assessment(result: dict, exposure: dict) -> None:
        fab = result["agent_outputs"]["fab_intelligence"]
        AssessmentService._apply_verified_exposure(fab, exposure)
        result["brief"]["field_impact"] = {
            "units_in_field": exposure["units_in_field"],
            "blockable_stock": exposure["blockable_stock"],
            "impacted_customers": exposure["impacted_customers"],
            "containment_perimeter_pct": exposure["containment_perimeter_pct"],
        }
        result["citations"] = [
            citation
            for citation in result.get("citations", [])
            if citation.get("url") != exposure["citation"]["url"]
        ]
        result["citations"].append(exposure["citation"])
        result["teams_update"] = {
            "text": format_teams_incident_update(fab, exposure),
            "delivery": "dry-run",
        }

    async def _verified_exposure(self) -> dict:
        try:
            return await self.onedrive.assess_impact()
        except (RuntimeError, httpx.HTTPError) as exc:
            exposure = calculate_field_exposure()
            exposure["live_error"] = str(exc)
            return exposure

    async def chat(self, message: str) -> dict:
        route = select_orchestration_route(message)
        request = f"ROUTE={route}\nUSER_REQUEST={message}\n"
        normalized_message = message.casefold()
        fabric_terms = (
            "e-test",
            "ontology",
            "recipe",
            "root cause",
            "telemetry",
            "tester",
            "vth",
            "wafer",
        )
        needs_fabric = route == FULL_ASSESSMENT or any(
            term in normalized_message for term in fabric_terms
        )
        citations = await self.foundry.retrieve(
            f"{request}Return one JSON object."
        )
        if self.settings.demo_mode:
            if route == RADAR_ONLY:
                answer = (
                    "Demo mode is active. Only Radar would be activated for this public-only "
                    "request; no internal or delegated source is queried."
                )
            elif route == FAB_ONLY:
                answer = (
                    "Demo mode is active. Only Fab Intelligence would be activated for this "
                    "internal quality request."
                )
            else:
                answer = (
                    "Demo mode is active. The Chief/Compiler activates Radar and Fab "
                    "Intelligence in parallel, then synthesizes their evidence."
                )
        else:
            answer = citations[0].excerpt
        route_agents = {
            RADAR_ONLY: ["Radar"],
            FAB_ONLY: ["Fab Intelligence"],
            FULL_ASSESSMENT: ["Radar", "Fab Intelligence", "Chief/Compiler"],
        }[route]
        source_payload = [citation.as_dict() for citation in citations]
        structured_response = None
        if not self.settings.demo_mode:
            try:
                structured = extract_json_object(answer)
            except (ValueError, json.JSONDecodeError):
                structured = {}
            if isinstance(structured.get("sources"), list):
                source_payload = structured["sources"]
                if route == RADAR_ONLY:
                    source_payload = self._normalize_public_citations(source_payload)
                    structured["sources"] = source_payload
                    if isinstance(structured.get("result"), dict):
                        structured["result"]["citations"] = source_payload
            if isinstance(structured.get("activated_agents"), list):
                route_agents = [str(agent) for agent in structured["activated_agents"]]
            if structured:
                route_result = structured.get("result")
                if (
                    route == FAB_ONLY
                    and isinstance(route_result, dict)
                    and not needs_fabric
                ):
                    verified_exposure = await self._verified_exposure()
                    self._apply_verified_exposure(
                        route_result, verified_exposure, exposure_only=True
                    )
                    structured["sources"] = route_result["citations"]
                    source_payload = structured["sources"]
                    answer = (
                        f"{route_result['field_exposure']:,} units are in field, "
                        f"{route_result['blockable_stock']:,} units remain blockable, and "
                        f"the modeled containment perimeter is "
                        f"{route_result['containment_perimeter_pct']}%."
                    )
                    structured["answer"] = answer
                elif route == FULL_ASSESSMENT and isinstance(route_result, dict):
                    verified_exposure = await self._verified_exposure()
                    self._apply_verified_exposure_to_assessment(
                        route_result, verified_exposure
                    )
                    structured["sources"] = route_result["citations"]
                    source_payload = structured["sources"]
                    answer = str(
                        route_result["brief"].get("probable_root_cause")
                        or structured.get("answer")
                        or answer
                    )
                    structured["answer"] = answer
                else:
                    answer = str(structured.get("answer") or answer)
                structured_response = (
                    route_result
                    if route == FULL_ASSESSMENT and isinstance(route_result, dict)
                    else structured
                )
        return {
            "mode": "demo" if self.settings.demo_mode else "live-configured",
            "route": route.lower(),
            "answer": answer,
            "structured": structured_response,
            "sources": source_payload,
            "trajectory": [
                {
                    "agent": agent,
                    "state": "completed",
                    "detail": (
                        "Public-only request routed to Web Knowledge Source."
                        if agent == "Radar" and route == RADAR_ONLY
                        else "Internal quality and procedure evidence requested."
                        if agent == "Fab Intelligence" and route == FAB_ONLY
                        else "Selected for the composite incident assessment."
                    ),
                }
                for agent in route_agents
            ],
        }

    async def _run(self, run: AssessmentRun) -> None:
        try:
            run.event(8, "Chief/Compiler · dispatching the incident assessment")
            await asyncio.sleep(0.03)
            run.event(20, "Parallel fan-out · Radar and Fab Intelligence started")
            await asyncio.sleep(0.03)
            fabric_status = self.fabric.status()
            work_iq_status = self.workiq.status()
            fabric_request = (
                "Use Tool Search to discover and call Fabric IQ; preserve its citation. "
                if fabric_status.mode == "live"
                else "Use Tool Search first, then explicitly label any Fabric IQ fallback. "
            )
            work_iq_request = (
                "Use the read-only delegated Work IQ toolbox for the exact Quality Ops "
                "handbook under the signed-in user's permissions. "
                if run.include_work_iq and work_iq_status.mode == "live-toolbox"
                else ""
            )
            if self.settings.demo_mode:
                radar, fab = await asyncio.gather(
                    asyncio.to_thread(offline_radar_output),
                    asyncio.to_thread(offline_fab_output),
                )
                run.event(52, "Radar · public web analysis completed")
                run.event(
                    58,
                    "Fab Intelligence · internal exposure, ontology, and knowledge trace completed",
                )
                result = compile_offline_brief(radar, fab, run.objective)
            else:
                result = await self.foundry.invoke_assessment(
                    f"ROUTE={FULL_ASSESSMENT}\n{run.objective}\n"
                    "Assess synthetic lot SiC-AUTO-2451 and product "
                    "SCTW90N65G2V. Radar must use only public web evidence. Fab Intelligence "
                    "must calculate internal workbook exposure and use Foundry IQ, the labelled "
                    "three internal Tool Search capabilities: Foundry IQ, Fabric IQ, and "
                    f"Work IQ OneDrive workbook analysis. {fabric_request}{work_iq_request}"
                    "Return the strict Chief/Compiler JSON contract and a Teams dry-run only.",
                    timeout_seconds=900,
                )
                run.event(52, "Radar · parallel worker output completed")
                run.event(58, "Fab Intelligence · parallel worker output completed")
            verified_exposure = await self._verified_exposure()
            self._apply_verified_exposure_to_assessment(result, verified_exposure)
            await asyncio.sleep(0.03)
            run.event(72, "Chief/Compiler · validating both worker JSON outputs")
            await asyncio.sleep(0.03)
            run.event(
                84,
                (
                    "Work IQ · delegated handbook context requested"
                    if run.include_work_iq and work_iq_status.mode == "live-toolbox"
                    else "Work IQ · local SharePoint handbook snapshot explicitly labelled"
                ),
            )
            await asyncio.sleep(0.03)
            run.event(93, "Chief/Compiler · cited incident disposition assembled")
            run.result = result
            run.status = "completed"
            run.event(100, "Assessment complete")
        except Exception as exc:
            run.status = "failed"
            run.event(run.progress, f"Assessment failed: {type(exc).__name__}: {exc}")

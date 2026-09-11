"""FastAPI orchestrator and static UI for the ST IQ incident demonstration."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from app.config import Settings
from app.data import build_demo_data
from app.service import AssessmentService
from app.v1_assets import calculate_field_exposure, load_fabric_trace


class TeamsSendRequest(BaseModel):
    explicit_opt_in: bool = False
    approval_code: str | None = Field(default=None, max_length=128)


class ScenarioRequest(BaseModel):
    objective: str = Field(
        default=(
            "Assess the SiC-AUTO-2451 Vth excursion, determine field exposure and probable "
            "root cause, and produce a cited containment brief."
        ),
        min_length=10,
        max_length=2000,
    )
    include_work_iq: bool = False


class ChatRequest(BaseModel):
    message: str = Field(min_length=3, max_length=2000)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    app.state.service = AssessmentService(settings, build_demo_data())
    yield


app = FastAPI(title="ST IQ Operations Assistant", version="1.0.0", lifespan=lifespan)
STATIC = Path(__file__).parent / "static"
INTERNAL_API_KEY = APIKeyHeader(name="X-STIQ-API-Key", auto_error=False)
EVALUATION_SUMMARY = Path(__file__).parent / os.getenv(
    "EVALUATION_SUMMARY_FILE", "evaluation-summary.json"
)


def service(request: Request) -> AssessmentService:
    return request.app.state.service


def require_internal_api_key(
    request: Request,
    supplied: str | None = Depends(INTERNAL_API_KEY),
) -> None:
    expected = service(request).settings.internal_api_key
    if not expected:
        raise HTTPException(503, "Internal intelligence API authentication is not configured.")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "A valid X-STIQ-API-Key is required.")


@app.get(
    "/internal/fabric/lots/{lot_id}",
    operation_id="searchFabricOntology",
    summary="Query Fabric IQ for synthetic lot causal evidence",
)
async def internal_fabric_trace(
    lot_id: str,
    request: Request,
    _: None = Depends(require_internal_api_key),
    correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
) -> dict:
    if lot_id != "SiC-AUTO-2451":
        raise HTTPException(404, "Unknown synthetic lot.")
    try:
        evidence = await service(request).fabric.assess_impact()
        fallback_reason = None
    except (RuntimeError, httpx.HTTPError) as exc:
        evidence = load_fabric_trace(lot_id)
        fallback_reason = str(exc)
    return {
        "correlation_id": correlation_id,
        "source": evidence.get("source_label", "Fabric IQ"),
        "synthetic": True,
        "live_error": fallback_reason,
        **evidence,
    }


@app.get(
    "/internal/onedrive/lots/{lot_id}/exposure",
    operation_id="analyzeOneDriveWorkbook",
    summary="Calculate synthetic shipment exposure from the delegated OneDrive workbook",
)
async def internal_onedrive_exposure(
    lot_id: str,
    request: Request,
    _: None = Depends(require_internal_api_key),
    correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
) -> dict:
    if lot_id != "SiC-AUTO-2451":
        raise HTTPException(404, "Unknown synthetic lot.")
    try:
        exposure = await service(request).onedrive.assess_impact(lot_id)
        fallback_reason = None
    except (RuntimeError, httpx.HTTPError) as exc:
        exposure = calculate_field_exposure(lot_id)
        fallback_reason = str(exc)
    return {
        "correlation_id": correlation_id,
        "source": exposure["source_label"],
        "synthetic": True,
        "live_error": fallback_reason,
        **exposure,
    }


@app.get("/health")
async def health(request: Request) -> dict:
    return {
        "status": "ok",
        "mode": "demo" if service(request).settings.demo_mode else "live-configured",
    }


@app.get("/api/status")
@app.get("/api/preflight")
async def preflight(request: Request) -> dict:
    coordinator = service(request)
    return {
        "mode": "demo" if coordinator.settings.demo_mode else "live-configured",
        "seed": coordinator.data.seed,
        "adapters": coordinator.statuses(),
        "notice": (
            "Live integrations are never simulated. Degraded adapters report their exact "
            "missing configuration."
        ),
    }


@app.get("/api/scenarios")
async def scenario_history(request: Request) -> dict:
    return {"items": service(request).history()}


@app.post("/api/scenarios")
async def start_scenario(request: Request, payload: ScenarioRequest | None = None) -> dict:
    run = service(request).start(
        payload.objective if payload else None,
        include_work_iq=payload.include_work_iq if payload else False,
    )
    return run.summary()


@app.post("/api/chat")
async def chat(payload: ChatRequest, request: Request) -> dict:
    return await service(request).chat(payload.message)


@app.get("/api/evaluation")
async def evaluation() -> dict:
    if not EVALUATION_SUMMARY.is_file():
        raise HTTPException(503, "No verified evaluation summary is available.")
    return json.loads(EVALUATION_SUMMARY.read_text(encoding="utf-8"))


@app.get("/api/scenarios/{run_id}")
async def scenario_status(run_id: str, request: Request) -> dict:
    run = service(request).runs.get(run_id)
    if not run:
        raise HTTPException(404, "Scenario not found")
    return {**run.summary(), "events": run.events}


@app.get("/api/scenarios/{run_id}/result")
async def scenario_result(run_id: str, request: Request) -> dict:
    run = service(request).runs.get(run_id)
    if not run:
        raise HTTPException(404, "Scenario not found")
    if run.status != "completed":
        raise HTTPException(409, "Scenario is not complete")
    return run.result or {}


@app.get("/api/scenarios/{run_id}/events")
async def scenario_events(run_id: str, request: Request) -> StreamingResponse:
    coordinator = service(request)
    if run_id not in coordinator.runs:
        raise HTTPException(404, "Scenario not found")

    async def stream():
        position = 0
        while True:
            run = coordinator.runs[run_id]
            while position < len(run.events):
                yield f"data: {json.dumps(run.events[position])}\n\n"
                position += 1
            if run.status in {"completed", "failed"}:
                yield f"event: done\ndata: {json.dumps(run.summary())}\n\n"
                return
            await asyncio.sleep(0.05)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/scenarios/{run_id}/teams")
async def send_teams(run_id: str, payload: TeamsSendRequest, request: Request) -> dict:
    coordinator = service(request)
    run = coordinator.runs.get(run_id)
    if not run:
        raise HTTPException(404, "Scenario not found")
    if not run.result:
        raise HTTPException(409, "Scenario is not complete")
    try:
        return await coordinator.teams.send(
            run.result["teams_update"]["text"],
            payload.explicit_opt_in,
            delivery_key=run_id,
            approval_code=payload.approval_code,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/", include_in_schema=False)
@app.get("/chat", include_in_schema=False)
@app.get("/tasks", include_in_schema=False)
@app.get("/history", include_in_schema=False)
@app.get("/evaluation", include_in_schema=False)
async def ui() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/static/{filename}", include_in_schema=False)
async def static_file(filename: str) -> FileResponse:
    path = STATIC / filename
    if not path.is_file():
        raise HTTPException(404, "Asset not found")
    return FileResponse(path)

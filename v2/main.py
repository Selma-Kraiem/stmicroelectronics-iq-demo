"""FastAPI presenter for the isolated ST IQ demo V2."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from v2.api.exposure import create_app as create_exposure_app
from v2.api.telemetry import create_app as create_telemetry_app
from v2.cloud import RemoteCommanderClient
from v2.orchestration import DEFAULT_OBJECTIVE, CommanderService


class ChatRequest(BaseModel):
    message: str = Field(min_length=3, max_length=2000)


class TaskRequest(BaseModel):
    objective: str = Field(default=DEFAULT_OBJECTIVE, min_length=10, max_length=3000)


class PublishRequest(BaseModel):
    explicit_opt_in: bool = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    remote = RemoteCommanderClient.from_env()
    app.state.commander = CommanderService(remote=remote)
    try:
        yield
    finally:
        if remote is not None:
            await remote.close()


app = FastAPI(title="ST IQ Incident Command V2", version="2.0.0", lifespan=lifespan)
STATIC = Path(__file__).parent / "static"


def commander(request: Request) -> CommanderService:
    return request.app.state.commander


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "v2", "work_iq_teams": "disabled"}


@app.get("/api/v2/status")
async def status(request: Request) -> dict:
    return {
        "version": "v2",
        "adapters": commander(request).statuses(),
        "notice": "Live integrations and fallbacks are always labelled explicitly.",
    }


@app.post("/api/v2/chat")
async def chat(payload: ChatRequest, request: Request) -> dict:
    try:
        return await commander(request).chat(payload.message)
    except RuntimeError as exc:
        raise HTTPException(504, str(exc)) from exc


@app.get("/api/v2/tasks")
async def history(request: Request) -> dict:
    return {"items": commander(request).history()}


@app.post("/api/v2/tasks")
async def start_task(payload: TaskRequest, request: Request) -> dict:
    return commander(request).start_task(payload.objective).summary()


@app.get("/api/v2/tasks/{run_id}")
async def task_status(run_id: str, request: Request) -> dict:
    run = commander(request).runs.get(run_id)
    if run is None:
        raise HTTPException(404, "Task not found")
    return {**run.summary(), "events": run.events}


@app.get("/api/v2/tasks/{run_id}/result")
async def task_result(run_id: str, request: Request) -> dict:
    run = commander(request).runs.get(run_id)
    if run is None:
        raise HTTPException(404, "Task not found")
    if run.status == "running":
        raise HTTPException(409, "Task is not complete")
    return run.result or {}


@app.get("/api/v2/tasks/{run_id}/events")
async def task_events(run_id: str, request: Request) -> StreamingResponse:
    service = commander(request)
    if run_id not in service.runs:
        raise HTTPException(404, "Task not found")

    async def stream():
        position = 0
        while True:
            run = service.runs[run_id]
            while position < len(run.events):
                yield f"data: {json.dumps(run.events[position])}\n\n"
                position += 1
            if run.status != "running":
                yield f"event: done\ndata: {json.dumps(run.summary())}\n\n"
                return
            await asyncio.sleep(0.05)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/v2/tasks/{run_id}/teams")
async def publish_teams(run_id: str, payload: PublishRequest, request: Request) -> dict:
    try:
        return await commander(request).publish_teams(run_id, payload.explicit_opt_in)
    except KeyError as exc:
        raise HTTPException(404, "Task not found") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/", include_in_schema=False)
@app.get("/v2", include_in_schema=False)
async def ui_root() -> RedirectResponse:
    return RedirectResponse("/v2/chat")


@app.get("/v2/chat", include_in_schema=False)
@app.get("/v2/tasks", include_in_schema=False)
async def ui_surface() -> FileResponse:
    path = STATIC / "index.html"
    if not path.is_file():
        raise HTTPException(503, "V2 presenter assets are not built.")
    return FileResponse(path)


app.mount("/v2/static", StaticFiles(directory=STATIC), name="v2-static")
app.mount("/operational/telemetry", create_telemetry_app(), name="telemetry-api")
app.mount("/operational/exposure", create_exposure_app(), name="exposure-api")

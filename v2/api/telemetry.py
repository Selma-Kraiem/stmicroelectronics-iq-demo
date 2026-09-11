"""Manufacturing Telemetry API for synthetic equipment and lot observations."""

from __future__ import annotations

import os

from fastapi import Depends, FastAPI, HTTPException, Request

from v2.api.common import API_KEY_HEADER, ApiRuntime, correlation_id, require_api_key
from v2.operational import OperationalDomain


def create_app(
    runtime: ApiRuntime | None = None,
    domain: OperationalDomain | None = None,
) -> FastAPI:
    app = FastAPI(
        title="ST IQ V2 Manufacturing Telemetry API",
        version="2.0.0",
        description=(
            "Deterministic synthetic semiconductor telemetry. Every response is demo-only "
            "and carries correlation and provenance metadata."
        ),
    )
    app.state.runtime = runtime or ApiRuntime(os.getenv("STIQ_V2_API_KEY"))
    app.state.domain = domain or OperationalDomain()

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "api": "manufacturing-telemetry", "synthetic": True}

    @app.get(
        "/api/v2/telemetry/lots/{lot_id}",
        operation_id="getLotTelemetry",
        summary="Get telemetry anomalies for a manufacturing lot",
    )
    async def lot_telemetry(
        lot_id: str,
        request: Request,
        api_key: str | None = Depends(API_KEY_HEADER),
        request_correlation_id: str = Depends(correlation_id),
    ) -> dict:
        require_api_key(request, api_key)
        try:
            result = request.app.state.domain.telemetry_for_lot(lot_id)
        except KeyError as exc:
            raise HTTPException(404, f"Unknown synthetic lot: {lot_id}") from exc
        return {
            "correlation_id": request_correlation_id,
            "source": "Manufacturing Telemetry API",
            "provenance": "deterministic synthetic data",
            **result,
        }

    return app


app = create_app()

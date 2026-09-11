"""Shared API authentication and correlation helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Header, HTTPException, Request
from fastapi.security import APIKeyHeader

API_KEY_HEADER = APIKeyHeader(name="X-STIQ-API-Key", auto_error=False)


@dataclass(frozen=True)
class ApiRuntime:
    api_key: str | None

    @classmethod
    def from_env(cls) -> "ApiRuntime":
        api_key = os.getenv("STIQ_V2_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("STIQ_V2_API_KEY is required for the operational APIs.")
        return cls(api_key=api_key)


def correlation_id(value: str | None = Header(default=None, alias="X-Correlation-ID")) -> str:
    return value or f"corr-{uuid4().hex}"


def require_api_key(request: Request, supplied: str | None = None) -> None:
    expected = request.app.state.runtime.api_key
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Operational API authentication is not configured.",
        )
    if not supplied or supplied != expected:
        raise HTTPException(status_code=401, detail="A valid X-STIQ-API-Key is required.")

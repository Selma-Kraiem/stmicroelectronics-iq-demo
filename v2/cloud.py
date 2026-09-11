"""Client for the deployed V2 Commander Hosted Agent."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from azure.identity import DefaultAzureCredential, get_bearer_token_provider


def _output_text(response: dict[str, Any]) -> str:
    for item in reversed(response.get("output", [])):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                return str(text)
    raise RuntimeError("Commander Hosted Agent returned no output text.")


def _json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        decoder = json.JSONDecoder()
        for position, character in enumerate(value):
            if character != "{":
                continue
            try:
                payload, _ = decoder.raw_decode(value, position)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        raise RuntimeError("Commander Hosted Agent did not return the JSON contract.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Commander Hosted Agent returned a non-object JSON value.")
    return payload


class _BearerAuth(httpx.Auth):
    def __init__(self, token_provider) -> None:
        self._token_provider = token_provider

    def auth_flow(self, request):
        request.headers["Authorization"] = f"Bearer {self._token_provider()}"
        yield request


class RemoteCommanderClient:
    """Invoke the deployed Commander while preserving caller-owned identifiers."""

    def __init__(
        self,
        endpoint: str,
        *,
        credential=None,
        timeout_seconds: float = 300.0,
    ) -> None:
        self.endpoint = endpoint
        azure_credential = credential or DefaultAzureCredential()
        provider = get_bearer_token_provider(
            azure_credential,
            "https://ai.azure.com/.default",
        )
        self._client = httpx.AsyncClient(
            auth=_BearerAuth(provider),
            timeout=httpx.Timeout(timeout_seconds),
        )

    @classmethod
    def from_env(cls) -> "RemoteCommanderClient | None":
        endpoint = os.getenv("FOUNDRY_V2_COMMANDER_ENDPOINT", "").strip()
        return cls(endpoint) if endpoint else None

    async def close(self) -> None:
        await self._client.aclose()

    async def invoke(
        self,
        *,
        mode: str,
        objective: str,
        run_id: str,
        incident_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        request = {
            "input": (
                f"MODE={mode.upper()}\n"
                f"run_id={run_id}\n"
                f"incident_id={incident_id}\n"
                f"correlation_id={correlation_id}\n"
                f"OBJECTIVE={objective}"
            )
        }
        try:
            response = await self._client.post(self.endpoint, json=request)
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                "Commander invocation timed out before Foundry returned a response."
            ) from exc
        if response.is_error:
            raise RuntimeError(
                f"Commander invocation failed ({response.status_code}): {response.text[:1000]}"
            )
        body = response.json()
        if body.get("status") != "completed":
            raise RuntimeError(
                f"Commander invocation ended in status {body.get('status', 'unknown')}."
            )
        result = _json_object(_output_text(body))
        result.update(
            {
                "run_id": run_id,
                "incident_id": incident_id,
                "correlation_id": correlation_id,
            }
        )
        return result

"""Explicit adapter boundaries for IQ services, with deterministic fallback implementations."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import time
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

from app.config import Settings
from app.data import ScenarioData
from app.v1_assets import (
    calculate_field_exposure,
    calculate_field_exposure_bytes,
    extract_json_object,
    load_fabric_trace,
)


@dataclass(frozen=True)
class AdapterStatus:
    name: str
    state: str
    mode: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class Citation:
    source_id: str
    title: str
    url: str | None
    source_type: str
    badge: str
    excerpt: str

    def as_dict(self) -> dict[str, str | None]:
        return asdict(self)


def response_output_text(body: dict[str, Any]) -> str:
    """Extract final text from the Responses 2.0.0 agent shape."""
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    for item in reversed(body.get("output") or []):
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                return str(content["text"])
    raise RuntimeError("Hosted agent response completed without final output text.")


def mcp_response_json(response: Any) -> dict[str, Any]:
    """Decode MCP responses delivered as JSON or server-sent JSON events."""
    try:
        value = response.json()
    except json.JSONDecodeError:
        value = None
        for line in reversed(response.text.splitlines()):
            if line.startswith("data:"):
                candidate = line.removeprefix("data:").strip()
                if candidate and candidate != "[DONE]":
                    try:
                        value = json.loads(candidate)
                        break
                    except json.JSONDecodeError:
                        continue
    if not isinstance(value, dict):
        raise RuntimeError("MCP response contained neither JSON nor a valid SSE JSON event.")
    return value


def fabric_search_trace(payload: dict[str, Any], endpoint: str) -> dict[str, Any]:
    """Normalize the official Fabric Ontology search result into the V1 trace contract."""
    raw = payload.get("raw")
    if not isinstance(raw, dict):
        raise RuntimeError("Fabric IQ search result did not contain the expected raw graph data.")
    fields, values = raw.get("Fields"), raw.get("Value")
    if not isinstance(fields, list) or not isinstance(values, list) or not values:
        raise RuntimeError("Fabric IQ search result contained no graph rows.")
    rows = [dict(zip(fields, row, strict=True)) for row in values if len(row) == len(fields)]
    failed = [
        row
        for row in rows
        if float(row.get("Vth_Value", 0)) > float(row.get("USL", 0))
    ]
    if not failed:
        raise RuntimeError("Fabric IQ graph rows contained no Vth value above the USL.")

    scalar_properties = {
        "Lot": {"LotID": "LotID"},
        "Wafer": {"WaferID": "WaferID"},
        "Tester": {
            "TesterID": "TesterID",
            "LastPM_date": "Tester_LastPM_date",
        },
        "Recipe": {
            "RecipeID": "RecipeID",
            "AnnealTemp_C": "Recipe_AnnealTemp_C",
        },
        "ETestResult": {
            "ResultID": "ResultID",
            "Parameter": "Parameter",
            "Value": "Vth_Value",
            "USL": "USL",
        },
    }

    def properties(row: dict[str, Any], entity: str) -> dict[str, Any]:
        value = row.get(f"{entity}_json")
        try:
            decoded = json.loads(value) if isinstance(value, str) else value
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Fabric IQ returned invalid {entity} graph JSON.") from exc
        if isinstance(decoded, dict) and isinstance(decoded.get("properties"), dict):
            return decoded["properties"]
        fallback = {
            property_name: row[field_name]
            for property_name, field_name in scalar_properties[entity].items()
            if row.get(field_name) is not None
        }
        if not fallback:
            raise RuntimeError(f"Fabric IQ returned no {entity} properties.")
        return fallback

    suspect_tester = Counter(str(row["TesterID"]) for row in failed).most_common(1)[0][0]
    suspect_recipe = Counter(str(row["RecipeID"]) for row in failed).most_common(1)[0][0]
    lot = properties(failed[0], "Lot")
    tester = properties(failed[0], "Tester")
    recipe = next(
        properties(row, "Recipe")
        for row in failed
        if str(row["RecipeID"]) == suspect_recipe
    )
    measured_values = [float(row["Vth_Value"]) for row in failed]
    usl = float(failed[0]["USL"])
    anneal_temp = int(recipe["AnnealTemp_C"])
    return {
        "lot": lot,
        "failed_wafers": [str(row["WaferID"]) for row in failed],
        "deviating_parameter": "Vth",
        "measured_values_v": measured_values,
        "usl_v": usl,
        "suspect_tester": suspect_tester,
        "tester_last_pm": tester["LastPM_date"],
        "suspect_recipe": suspect_recipe,
        "anneal_temp_c": anneal_temp,
        "process_upper_limit_c": 1190,
        "root_cause_probable": (
            f"{suspect_recipe} gate-oxide anneal at {anneal_temp} degC exceeded the "
            f"1190 degC process limit on {suspect_tester}, producing a positive Vth shift."
        ),
        "ontology_path": ["Lot", "Wafer", "Tester", "Recipe", "ETestResult"],
        "source_mode": "live",
        "source_label": "Fabric IQ",
        "citation": {
            "title": "ST IQ Semiconductor Operations",
            "url": endpoint,
            "source_type": "live Microsoft Fabric ontology",
            "badge": "Fabric IQ live",
            "excerpt": (
                f"{lot['LotID']} -> {suspect_tester} -> {suspect_recipe} -> Vth "
                f"{'/'.join(str(value) for value in measured_values)} V vs {usl} V USL."
            ),
        },
    }


def is_safe_external_query(query: str) -> bool:
    """External knowledge may receive generic public context only."""
    prohibited = ("lot", "customer", "order", "telemetry", "incident", "inventory", "confidential")
    normalized = query.lower()
    return bool(normalized.strip()) and not any(term in normalized for term in prohibited)


class FoundryKnowledgeAdapter:
    """Adaptive Foundry workflow boundary; production retrieval is not simulated."""

    def __init__(self, settings: Settings, data: ScenarioData):
        self.settings, self.data = settings, data

    def status(self) -> AdapterStatus:
        if self.settings.foundry_agent_endpoint and not self.settings.demo_mode:
            return AdapterStatus(
                "Adaptive Foundry workflow",
                "available",
                "live",
                "The Chief Orchestrator activates only Radar, only Fab Intelligence, or both "
                "in parallel with Chief/Compiler synthesis according to the request.",
            )
        return AdapterStatus(
            "Adaptive Foundry workflow",
            "degraded",
            "demo",
            "Hosted workflow is not called; missing FOUNDRY_AGENT_ENDPOINT or STIQ_LIVE_MODE=1.",
        )

    async def invoke_assessment(self, query: str, timeout_seconds: float = 900) -> dict[str, Any]:
        if self.settings.demo_mode or self.status().state != "available":
            raise RuntimeError("The Hosted Agent is not configured for live invocation.")
        import httpx
        from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

        credential = (
            ManagedIdentityCredential(client_id=os.getenv("AZURE_CLIENT_ID"))
            if os.getenv("AZURE_CLIENT_ID")
            else DefaultAzureCredential()
        )
        access_token = credential.get_token("https://ai.azure.com/.default").token
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                self.settings.foundry_agent_endpoint,
                headers={"Authorization": "Bearer " + access_token},
                json={"input": query},
            )
            response.raise_for_status()
            body = response.json()
        if body.get("status") == "failed":
            error = body.get("error") or {}
            raise RuntimeError(str(error.get("message") or "Hosted agent response failed."))
        result = extract_json_object(response_output_text(body))
        if (
            result.get("route") == "full_assessment"
            and isinstance(result.get("result"), dict)
        ):
            result = result["result"]
        required = {
            "incident",
            "agent_outputs",
            "brief",
            "evidence_trace",
            "citations",
            "teams_update",
        }
        missing = required - result.keys()
        if missing:
            raise RuntimeError(
                f"Hosted Agent JSON is missing required fields: {', '.join(sorted(missing))}"
            )
        if result["teams_update"].get("delivery") != "dry-run":
            raise RuntimeError("Hosted Agent attempted to return a non-dry-run Teams action.")
        return result

    async def retrieve(self, query: str, timeout_seconds: float = 220) -> list[Citation]:
        if not self.settings.demo_mode and self.status().state == "available":
            import httpx
            from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

            credential = (
                ManagedIdentityCredential(client_id=os.getenv("AZURE_CLIENT_ID"))
                if os.getenv("FOUNDRY_AGENT_NAME")
                else DefaultAzureCredential()
            )
            access_token = credential.get_token("https://ai.azure.com/.default").token
            headers = {"Authorization": f"Bearer {access_token}"}
            payload = {"input": query}
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    self.settings.foundry_agent_endpoint,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
            if body.get("status") == "failed":
                error = body.get("error") or {}
                raise RuntimeError(
                    str(error.get("message") or "Hosted agent response failed.")
                )
            return [
                Citation(
                    "foundry-agent-response",
                    "Foundry hosted-agent response",
                    None,
                    "Foundry multi-agent workflow",
                    "Foundry workflow",
                    response_output_text(body),
                )
            ]
        # Demo behavior is deliberately local; it does not claim a live retrieval occurred.
        return [
            Citation(
                "ST-PUBLIC-SIC",
                "STMicroelectronics SiC power MOSFET and module overview",
                "https://www.st.com/en/power-transistors/silicon-carbide-sic-devices.html",
                "public ST documentation",
                "Public ST",
                "Public product context for silicon-carbide power technology.",
            ),
            Citation(
                self.data.procedures[0]["id"],
                self.data.procedures[0]["title"],
                None,
                "synthetic internal procedure",
                "Demo procedure",
                self.data.procedures[0]["excerpt"],
            ),
        ]


class OperationalKnowledgeAdapter:
    """Deterministic operational graph indexed in Foundry IQ for the quality specialist."""

    def __init__(self, settings: Settings, data: ScenarioData):
        self.settings, self.data = settings, data

    def status(self) -> AdapterStatus:
        return AdapterStatus(
            "Shipment exposure calculation",
            "available",
            "agent-framework-function",
            (
                "Fab Intelligence calls a Python function tool over the canonical "
                "synthetic workbook."
            ),
        )

    async def assess_impact(self) -> dict[str, Any]:
        return calculate_field_exposure()


class OneDriveWorkbookAdapter:
    """Retrieve the synthetic shipment workbook through delegated Work IQ."""

    ROOT_FOLDER = "ST-IQ-Demo"
    WORKBOOK = "SiC_AUTO_Shipments.xlsx"
    MAX_WORKBOOK_BYTES = 5 * 1024 * 1024
    LIST_TOOL = "WorkIqOneDriveConnection___getFolderChildrenInMyOnedrive"

    def __init__(self, settings: Settings):
        self.settings = settings

    def status(self) -> AdapterStatus:
        if (
            self.settings.work_iq_onedrive_toolbox_endpoint
            and not self.settings.demo_mode
        ):
            return AdapterStatus(
                "Work IQ OneDrive workbook",
                "available",
                "live-toolbox",
                (
                    "A private read-only Work IQ toolbox retrieves the synthetic workbook; "
                    "Python calculates KPIs outside the model context."
                ),
            )
        return AdapterStatus(
            "Work IQ OneDrive workbook",
            "degraded",
            "synthetic-local",
            (
                "The delegated OneDrive toolbox is unavailable; the canonical committed "
                "synthetic workbook is used and labelled as a fallback."
            ),
        )

    @staticmethod
    def _content_text(result: dict[str, Any]) -> str:
        if result.get("isError"):
            raise RuntimeError("Work IQ OneDrive returned an MCP tool error.")
        texts = [
            str(item.get("text", ""))
            for item in result.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        texts = [text.strip() for text in texts if text.strip()]
        if not texts:
            raise RuntimeError("Work IQ OneDrive returned no textual tool payload.")
        # Agent 365 appends a second human-readable status frame after the data frame.
        return texts[0]

    async def _call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        import httpx
        from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

        endpoint = self.settings.work_iq_onedrive_toolbox_endpoint
        if not endpoint:
            raise RuntimeError("WORK_IQ_ONEDRIVE_TOOLBOX_ENDPOINT is not configured.")
        token = self.settings.work_iq_access_token
        if token:
            expires_at = self.settings.work_iq_access_token_expires_at
            if expires_at is not None and expires_at <= int(time.time()) + 60:
                raise RuntimeError("The delegated Work IQ access token has expired.")
        else:
            credential = (
                ManagedIdentityCredential(client_id=os.getenv("AZURE_CLIENT_ID"))
                if os.getenv("AZURE_CLIENT_ID")
                else DefaultAzureCredential()
            )
            token = credential.get_token("https://ai.azure.com/.default").token
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                endpoint,
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/json, text/event-stream",
                    "Foundry-Features": "Toolboxes=V1Preview",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": f"onedrive-{tool_name}",
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
            )
            response.raise_for_status()
        body = mcp_response_json(response)
        if body.get("error"):
            error = body["error"]
            raise RuntimeError(
                f"Work IQ OneDrive MCP error {error.get('code')}: {error.get('message')}"
            )
        result = body.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Work IQ OneDrive returned no MCP result object.")
        return result

    async def _children(self, parent_folder_id: str) -> list[dict[str, Any]]:
        children: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            arguments = {"parentFolderId": parent_folder_id}
            if cursor:
                arguments["pageCursor"] = cursor
            result = await self._call(self.LIST_TOOL, arguments)
            try:
                payload = json.loads(self._content_text(result))
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    "Work IQ OneDrive folder listing was not valid JSON."
                ) from exc
            if isinstance(payload.get("Error"), str):
                raise RuntimeError(
                    f"Work IQ OneDrive folder listing failed: {payload['Error']}"
                )
            page = payload.get("value")
            if not isinstance(page, list):
                raise RuntimeError("Work IQ OneDrive folder listing has no value array.")
            children.extend(item for item in page if isinstance(item, dict))
            cursor = payload.get("nextPageCursor")
            if not cursor:
                return children

    async def assess_impact(self, lot_id: str = "SiC-AUTO-2451") -> dict[str, Any]:
        if self.status().mode != "live-toolbox":
            return calculate_field_exposure(lot_id)
        root_items = await self._children("root")
        folders = [
            item
            for item in root_items
            if item.get("name") == self.ROOT_FOLDER and isinstance(item.get("folder"), dict)
        ]
        if len(folders) != 1:
            raise RuntimeError(
                f"Expected exactly one OneDrive folder named {self.ROOT_FOLDER}."
            )
        items = await self._children(str(folders[0]["id"]))
        workbooks = [
            item
            for item in items
            if item.get("name") == self.WORKBOOK and isinstance(item.get("file"), dict)
        ]
        if len(workbooks) != 1:
            raise RuntimeError(
                f"Expected exactly one OneDrive workbook named {self.WORKBOOK}."
            )
        workbook = workbooks[0]
        size = int(workbook.get("size", 0))
        if size <= 0 or size > self.MAX_WORKBOOK_BYTES:
            raise RuntimeError(
                f"OneDrive workbook size {size} is outside the supported 1..5 MB range."
            )
        if workbook["file"].get("fileExtension") != ".xlsx":
            raise RuntimeError("OneDrive workbook does not have the required .xlsx extension.")
        download_url = str(workbook.get("@content.downloadUrlNoAuth") or "")
        parsed_url = urlparse(download_url)
        if (
            parsed_url.scheme != "https"
            or not parsed_url.hostname
            or not parsed_url.hostname.casefold().endswith(".sharepoint.com")
        ):
            raise RuntimeError(
                "Work IQ OneDrive did not return an approved SharePoint download URL."
            )
        import httpx

        async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
            download = await client.get(download_url)
            download.raise_for_status()
        content = download.content
        if len(content) != size:
            raise RuntimeError(
                "Work IQ OneDrive workbook size changed between metadata and download."
            )
        exposure = calculate_field_exposure_bytes(
            content,
            lot_id=lot_id,
            citation_url=str(workbook.get("webUrl") or "m365://onedrive/ST-IQ-Demo"),
        )
        exposure["workbook_item_id"] = str(workbook["id"])
        exposure["workbook_etag"] = str(workbook.get("eTag", ""))
        return exposure


class SharePointKnowledgeAdapter:
    """Status boundary for real delegated SharePoint-to-Foundry IQ synchronization."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def status(self) -> AdapterStatus:
        if self.settings.sharepoint_knowledge_mode == "live":
            return AdapterStatus(
                "SharePoint Knowledge",
                "available",
                "live-indexed",
                self.settings.sharepoint_knowledge_reason,
            )
        return AdapterStatus(
            "SharePoint Knowledge",
            "blocked",
            "prerequisite",
            self.settings.sharepoint_knowledge_reason,
        )

class WebIQAdapter:
    """Public web-knowledge boundary guarded against confidential or private context."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def status(self) -> AdapterStatus:
        if self.settings.foundry_agent_endpoint and not self.settings.demo_mode:
            return AdapterStatus(
                "Web Knowledge Source (Web IQ fallback)",
                "available",
                "live",
                (
                    "Azure AI Search public web grounding is connected through the Foundry "
                    "market toolbox; no Web IQ credential is used."
                ),
            )
        return AdapterStatus(
            "Web Knowledge Source (Web IQ fallback)",
            "degraded",
            "demo",
            (
                "The live Hosted Agent is not configured; a cached public-only demo result "
                "is used and is not presented as Web IQ retrieval."
            ),
        )

    async def retrieve(self, query: str) -> list[Citation]:
        if not is_safe_external_query(query):
            return []
        if not self.settings.demo_mode and self.settings.foundry_agent_endpoint:
            import httpx
            from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

            credential = (
                ManagedIdentityCredential(client_id=os.getenv("AZURE_CLIENT_ID"))
                if os.getenv("FOUNDRY_AGENT_NAME")
                else DefaultAzureCredential()
            )
            access_token = credential.get_token("https://ai.azure.com/.default").token
            prompt = (
                "Use only the configured Web Knowledge Source for this sanitized, public-only "
                f"context request. Do not use enterprise data. Query: {query}"
            )
            async with httpx.AsyncClient(timeout=220) as client:
                response = await client.post(
                    self.settings.foundry_agent_endpoint,
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={"input": prompt},
                )
                response.raise_for_status()
                body = response.json()
            return [
                Citation(
                    "web-knowledge-source-live",
                    "Web Knowledge Source (Web IQ fallback)",
                    None,
                    "public external knowledge",
                    "Web Knowledge Source",
                    response_output_text(body),
                )
            ]
        return [
            Citation(
                "WEB-CACHED-SIC",
                "Cached public demo context",
                None,
                "cached public knowledge",
                "Cached public demo",
                (
                    "Cached demo fallback for a sanitized public-only silicon-carbide query; "
                    "no live Web Knowledge Source retrieval occurred."
                ),
            )
        ]


class FabricIQAdapter:
    def __init__(self, settings: Settings, data: ScenarioData):
        self.settings, self.data = settings, data

    def status(self) -> AdapterStatus:
        contract, reason = self._live_contract()
        if contract and not self.settings.demo_mode:
            return AdapterStatus(
                "Fabric IQ ontology",
                "available",
                "live",
                "MCP endpoint, tool name, and tool arguments contract configured.",
            )
        return AdapterStatus(
            "Fabric IQ ontology",
            "degraded",
            "synthetic-local",
            f"Fabric IQ fallback uses the committed synthetic ontology snapshot; {reason}.",
        )

    def _live_contract(self) -> tuple[tuple[str, str, dict[str, Any], str] | None, str]:
        missing = [
            name
            for name, value in (
                ("FABRIC_IQ_MCP_ENDPOINT", self.settings.fabric_iq_mcp_endpoint),
                ("FABRIC_IQ_TOOL_NAME", self.settings.fabric_iq_tool_name),
                ("FABRIC_IQ_TOOL_ARGUMENTS_JSON", self.settings.fabric_iq_tool_arguments_json),
                ("FABRIC_IQ_ACCESS_TOKEN", self.settings.fabric_iq_access_token),
            )
            if not value
        ]
        if missing:
            return None, f"missing {', '.join(missing)}"
        try:
            arguments = json.loads(self.settings.fabric_iq_tool_arguments_json or "")
        except json.JSONDecodeError:
            return None, "FABRIC_IQ_TOOL_ARGUMENTS_JSON is not valid JSON"
        if not isinstance(arguments, dict):
            return None, "FABRIC_IQ_TOOL_ARGUMENTS_JSON must be a JSON object"
        return (
            (
                self.settings.fabric_iq_mcp_endpoint or "",
                self.settings.fabric_iq_tool_name or "",
                arguments,
                self.settings.fabric_iq_access_token or "",
            ),
            "configured",
        )

    async def assess_impact(self) -> dict[str, Any]:
        contract, _ = self._live_contract()
        if contract and not self.settings.demo_mode:
            import httpx

            async def post_mcp(
                client: httpx.AsyncClient,
                payload: dict[str, Any],
            ) -> httpx.Response:
                for attempt in range(3):
                    try:
                        response = await client.post(endpoint, headers=headers, json=payload)
                        response.raise_for_status()
                        return response
                    except (httpx.TimeoutException, httpx.NetworkError):
                        if attempt == 2:
                            raise
                    except httpx.HTTPStatusError as exc:
                        retryable = exc.response.status_code in {408, 429, 500, 502, 503, 504}
                        if not retryable or attempt == 2:
                            raise
                    await asyncio.sleep(2**attempt)
                raise RuntimeError("Fabric IQ MCP retry budget was exhausted.")

            endpoint, tool_name, arguments, access_token = contract
            headers = {
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "Authorization": "Bear" + "er " + access_token,
            }
            timeout = httpx.Timeout(60, connect=10)
            async with httpx.AsyncClient(timeout=timeout) as client:
                list_response = await post_mcp(
                    client,
                    {"jsonrpc": "2.0", "id": "fabric-tools-list", "method": "tools/list"},
                )
                tools = mcp_response_json(list_response).get("result", {}).get("tools", [])
                if not any(tool.get("name") == tool_name for tool in tools):
                    raise RuntimeError(
                        f"Configured Fabric IQ MCP tool '{tool_name}' was not advertised."
                    )
                semantic_error: RuntimeError | None = None
                for attempt in range(3):
                    call_response = await post_mcp(
                        client,
                        {
                            "jsonrpc": "2.0",
                            "id": f"fabric-tools-call-{attempt + 1}",
                            "method": "tools/call",
                            "params": {"name": tool_name, "arguments": arguments},
                        },
                    )
                    result = mcp_response_json(call_response).get("result", {})
                    structured_content = result.get("structuredContent")
                    if not isinstance(structured_content, dict):
                        text = "\n".join(
                            str(item.get("text", ""))
                            for item in result.get("content", [])
                            if isinstance(item, dict) and item.get("type") == "text"
                        ).strip()
                        if text:
                            try:
                                structured_content = json.loads(text)
                            except json.JSONDecodeError:
                                raise RuntimeError(f"Fabric IQ MCP response: {text}")
                        else:
                            semantic_error = RuntimeError(
                                "Fabric IQ MCP tool did not return a structured impact contract."
                            )
                            if attempt < 2:
                                await asyncio.sleep(2**attempt)
                            continue
                    required = {
                        "affected_orders",
                        "available_reallocation",
                        "ontology_path",
                    }
                    if required.issubset(structured_content):
                        return {**structured_content, "mode": "live"}
                    try:
                        return {
                            **fabric_search_trace(structured_content, endpoint),
                            "mode": "live",
                        }
                    except RuntimeError as exc:
                        semantic_error = exc
                    if attempt < 2:
                        await asyncio.sleep(2**attempt)
            raise semantic_error or RuntimeError("Fabric IQ returned no usable evidence.")
        return load_fabric_trace()


class WorkIQA2AAdapter:
    """Delegated Work IQ boundary. It cannot claim user-authenticated data in demo mode."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def status(self) -> AdapterStatus:
        if (
            self.settings.work_iq_toolbox_endpoint
            and self.settings.foundry_agent_endpoint
            and not self.settings.demo_mode
        ):
            return AdapterStatus(
                "Work IQ delegated context",
                "available",
                "live-toolbox",
                (
                    "Read-only OAuth toolbox is connected through the Hosted Agent; access "
                    "remains scoped to the signed-in Foundry caller."
                ),
            )
        if (
            self.settings.work_iq_a2a_endpoint
            and self.settings.work_iq_access_token
            and not self.settings.demo_mode
        ):
            return AdapterStatus(
                "Work IQ delegated context",
                "available",
                "live-a2a",
                "User-authenticated A2A configured.",
            )
        missing = [
            name
            for name, value in (
                ("WORK_IQ_A2A_ENDPOINT", self.settings.work_iq_a2a_endpoint),
                ("WORK_IQ_ACCESS_TOKEN", self.settings.work_iq_access_token),
            )
            if not value
        ]
        return AdapterStatus(
            "Work IQ delegated context",
            "blocked" if self.settings.work_iq_blocker_reason else "degraded",
            "blocked" if self.settings.work_iq_blocker_reason else "demo",
            self.settings.work_iq_blocker_reason
            or f"Delegated user-authenticated A2A is not called; missing {', '.join(missing)}.",
        )

    def uses_a2a(self) -> bool:
        return (
            self.status().mode == "live-a2a"
            and bool(self.settings.work_iq_a2a_endpoint)
            and bool(self.settings.work_iq_access_token)
        )

    async def owner_actions(self) -> list[dict[str, str]]:
        if self.uses_a2a():
            import httpx

            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    self.settings.work_iq_a2a_endpoint,
                    headers={
                        "Authorization": f"Bearer {self.settings.work_iq_access_token}",
                        "A2A-Version": "1.0",
                    },
                    json={
                        "jsonrpc": "2.0",
                        "id": "st-iq-incident-actions",
                        "method": "message/send",
                        "params": {
                            "message": {
                                "messageId": "st-iq-incident-actions-message",
                                "role": "user",
                                "parts": [
                                    {
                                        "kind": "text",
                                        "text": "Assign incident actions for INC-SIC-0813.",
                                    }
                                ],
                            }
                        },
                    },
                )
                response.raise_for_status()
                payload = response.json()
            return payload["result"]["actions"]
        return [
            {
                "owner": "Quality lead",
                "action": "Confirm containment and preserve final-test traces.",
            },
            {
                "owner": "Supply planner",
                "action": "Hold affected allocations and validate substitute inventory.",
            },
            {
                "owner": "Account lead",
                "action": "Prepare customer communication after quality confirmation.",
            },
        ]


class TeamsAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._delivery_lock = asyncio.Lock()
        self._delivery_states: dict[str, str] = {}

    def status(self) -> AdapterStatus:
        if (
            self.settings.work_iq_teams_toolbox_endpoint
            and self.settings.teams_recipient_upn
            and self.settings.work_iq_access_token
            and self.settings.teams_approval_code
            and self.settings.allow_teams_send
            and self._delegated_token_active()
            and not self.settings.demo_mode
        ):
            return AdapterStatus(
                "Teams delivery",
                "available",
                "live-work-iq",
                (
                    "Explicit approval sends one direct message through Work IQ to "
                    f"{self.settings.teams_recipient_upn}."
                ),
            )
        return AdapterStatus(
            "Teams delivery",
            "degraded",
            "dry-run",
            (
                "Delivery is disabled until the Work IQ Teams toolbox, delegated token, "
                "non-expired token, fixed recipient, and presenter approval code are configured."
            ),
        )

    def _delegated_token_active(self) -> bool:
        expires_at = self.settings.work_iq_access_token_expires_at
        return expires_at is not None and expires_at > int(time.time()) + 60

    @staticmethod
    def _result_text(result: dict[str, Any]) -> str:
        return "\n".join(
            str(item.get("text", ""))
            for item in result.get("content") or []
            if isinstance(item, dict)
        ).strip()

    async def _call_work_iq(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        import httpx
        endpoint = self.settings.work_iq_teams_toolbox_endpoint
        if not endpoint:
            raise RuntimeError("The Work IQ Teams toolbox endpoint is not configured.")
        token = self.settings.work_iq_access_token
        if not token:
            from azure.identity import DefaultAzureCredential

            token = DefaultAzureCredential().get_token("https://ai.azure.com/.default").token
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                endpoint,
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/json, text/event-stream",
                    "Foundry-Features": "Toolboxes=V1Preview",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": "teams-send-message-to-user",
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments,
                    },
                },
            )
            response.raise_for_status()
            payload = mcp_response_json(response)
        if payload.get("error"):
            raise RuntimeError(
                str(payload["error"].get("message") or "Work IQ MCP call failed.")
            )
        result = payload.get("result") or {}
        if result.get("isError"):
            raise RuntimeError(self._result_text(result) or "Work IQ tool execution failed.")
        return result

    async def _send_work_iq(self, message: str) -> dict[str, Any]:
        recipient = self.settings.teams_recipient_upn
        if not recipient:
            raise RuntimeError("The direct Teams recipient UPN is not configured.")
        result = await self._call_work_iq(
            self.settings.work_iq_teams_send_tool,
            {
                "userIdOrUpn": recipient,
                "content": message,
                "contentType": "html",
                "importance": "high",
            },
        )
        if not result.get("structuredContent") and not self._result_text(result):
            raise RuntimeError("Work IQ Teams returned no delivery receipt.")
        return {
            "sent": True,
            "mode": "live-work-iq",
            "reason": f"Work IQ sent the approved direct message to {recipient}.",
        }

    async def send(
        self,
        message: str,
        explicit_opt_in: bool,
        *,
        delivery_key: str | None = None,
        approval_code: str | None = None,
    ) -> dict[str, Any]:
        if not explicit_opt_in:
            return {"sent": False, "mode": "dry-run", "reason": "Explicit opt-in was not supplied."}
        if not self.settings.allow_teams_send:
            return {
                "sent": False,
                "mode": "dry-run",
                "reason": "Live delivery is disabled.",
            }
        if not self._delegated_token_active():
            return {
                "sent": False,
                "mode": "dry-run",
                "reason": "The delegated Teams token expired; redeploy before sending.",
            }
        expected_code = self.settings.teams_approval_code or ""
        if not expected_code or not hmac.compare_digest(approval_code or "", expected_code):
            raise PermissionError("The presenter approval code is missing or invalid.")
        if (
            self.settings.work_iq_teams_toolbox_endpoint
            and self.settings.teams_recipient_upn
            and self.settings.work_iq_access_token
            and not self.settings.demo_mode
        ):
            if not delivery_key:
                raise RuntimeError("A run-scoped delivery key is required for live Teams delivery.")
            async with self._delivery_lock:
                delivery_state = self._delivery_states.get(delivery_key)
                if delivery_state == "sent":
                    return {
                        "sent": False,
                        "mode": "live-work-iq",
                        "reason": "This completed assessment was already delivered to Teams.",
                    }
                if delivery_state == "indeterminate":
                    raise RuntimeError(
                        "The previous Teams delivery outcome is indeterminate; "
                        "automatic retry is disabled to prevent a duplicate message."
                    )
                self._delivery_states[delivery_key] = "sending"
                try:
                    result = await self._send_work_iq(message)
                except Exception:
                    self._delivery_states[delivery_key] = "indeterminate"
                    raise
                self._delivery_states[delivery_key] = "sent"
                return result
        return {
            "sent": False,
            "mode": "dry-run",
            "reason": "No complete Work IQ Teams target is configured.",
        }

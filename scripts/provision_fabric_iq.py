"""Provision the synthetic ST IQ Fabric workspace, Lakehouse, notebook, and ontology."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.v1_assets import load_fabric_tables

FABRIC_API = "https://api.fabric.microsoft.com/v1"
FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"
TABLE_TYPES = {
    "Lot": {
        "LotID": "String",
        "ProductRef": "String",
        "FabSite": "String",
        "ProductionWeek": "String",
        "Status": "String",
    },
    "Wafer": {
        "WaferID": "String",
        "LotID": "String",
        "Position": "BigInt",
        "Yield_pct": "Double",
        "TesterID": "String",
        "RecipeID": "String",
    },
    "Tester": {
        "TesterID": "String",
        "Location": "String",
        "LastPM_date": "String",
    },
    "Recipe": {
        "RecipeID": "String",
        "Step": "String",
        "AnnealTemp_C": "BigInt",
        "OxideThickness_nm": "Double",
    },
    "ETestResult": {
        "ResultID": "String",
        "WaferID": "String",
        "Parameter": "String",
        "Value": "Double",
        "Unit": "String",
        "USL": "Double",
        "Status": "String",
    },
}
ENTITY_KEYS = {
    "Lot": ["LotID"],
    "Wafer": ["WaferID"],
    "Tester": ["TesterID"],
    "Recipe": ["RecipeID"],
    "ETestResult": ["ResultID"],
}
RELATIONSHIPS = (
    ("LotContainsWafer", "Lot", "Wafer", "Wafer", ["LotID"], ["WaferID"]),
    ("WaferTestedOnTester", "Wafer", "Tester", "Wafer", ["WaferID"], ["TesterID"]),
    ("WaferUsesRecipe", "Wafer", "Recipe", "Wafer", ["WaferID"], ["RecipeID"]),
    (
        "WaferHasETestResult",
        "Wafer",
        "ETestResult",
        "ETestResult",
        ["WaferID"],
        ["ResultID"],
    ),
)


class FabricApiError(RuntimeError):
    """A Fabric REST request failed."""

    def __init__(self, status: int, method: str, url: str, body: str):
        super().__init__(f"Fabric API {method} {url} failed with HTTP {status}: {body}")
        self.status = status
        self.body = body


@dataclass
class FabricClient:
    tenant_id: str

    def __post_init__(self) -> None:
        from azure.identity import AzureCliCredential

        self.credential = AzureCliCredential(tenant_id=self.tenant_id)

    def request(
        self,
        method: str,
        path_or_url: str,
        body: dict[str, Any] | None = None,
        *,
        timeout: int = 120,
    ) -> tuple[Any, dict[str, str], int]:
        url = path_or_url if path_or_url.startswith("https://") else f"{FABRIC_API}{path_or_url}"
        payload = None if body is None else json.dumps(body).encode("utf-8")
        token = self.credential.get_token(FABRIC_SCOPE).token
        request = urllib.request.Request(
            url,
            data=payload,
            method=method.upper(),
            headers={
                "Authorization": "Bear" + "er " + token,
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                headers = {key.lower(): value for key, value in response.headers.items()}
                return _decode_response(raw), headers, response.status
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise FabricApiError(error.code, method.upper(), url, detail) from None

    def wait_for_operation(self, location: str, timeout_seconds: int = 900) -> Any:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            result, headers, _ = self.request("GET", location)
            status = str((result or {}).get("status", "")).casefold()
            if status in {"succeeded", "completed"}:
                return result
            if status in {"failed", "cancelled", "canceled", "deduped"}:
                raise RuntimeError(f"Fabric operation ended in {status}: {json.dumps(result)}")
            time.sleep(max(2, int(headers.get("retry-after", "5"))))
        raise TimeoutError(f"Timed out waiting for Fabric operation: {location}")

    def wait_for_job(
        self,
        location: str,
        timeout_seconds: int = 1800,
        *,
        label: str = "job",
    ) -> Any:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            result, _, _ = self.request("GET", location)
            status = str((result or {}).get("status", "")).casefold()
            print(f"Fabric {label}: {status or 'pending'}", flush=True)
            if status in {"completed", "succeeded"}:
                return result
            if status in {"failed", "cancelled", "canceled"}:
                raise RuntimeError(f"Fabric notebook job ended in {status}: {json.dumps(result)}")
            time.sleep(10)
        raise TimeoutError(f"Timed out waiting for Fabric notebook job: {location}")


def _decode_response(raw: str) -> Any:
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        for line in reversed(raw.splitlines()):
            if line.startswith("data:"):
                candidate = line.removeprefix("data:").strip()
                if candidate and candidate != "[DONE]":
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        continue
    raise RuntimeError(f"Fabric returned a non-JSON response: {raw[:500]}")


def _stable_id(name: str) -> str:
    value = int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:8], "big")
    return str((value & ((1 << 63) - 1)) or 1)


def _base64_json(value: Any) -> str:
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _decoded_definition_parts(definition: dict[str, Any]) -> dict[str, Any]:
    return {
        part["path"]: json.loads(base64.b64decode(part["payload"]).decode("utf-8"))
        for part in definition.get("parts", [])
    }


def _definition_part(path: str, value: Any) -> dict[str, str]:
    return {"path": path, "payload": _base64_json(value), "payloadType": "InlineBase64"}


def _list_all(client: FabricClient, path: str) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    next_url: str | None = path
    while next_url:
        response, _, _ = client.request("GET", next_url)
        values.extend(response.get("value") or response.get("data") or [])
        next_url = response.get("continuationUri")
    return values


def _find_named(items: list[dict[str, Any]], display_name: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("displayName") == display_name), None)


def ensure_workspace(
    client: FabricClient, display_name: str, capacity_id: str
) -> dict[str, Any]:
    workspace = _find_named(_list_all(client, "/workspaces"), display_name)
    if workspace is None:
        workspace, headers, status = client.request(
            "POST",
            "/workspaces",
            {
                "displayName": display_name,
                "description": (
                    "Synthetic STMicroelectronics SiC incident demo. "
                    "No production or customer data."
                ),
                "capacityId": capacity_id,
            },
        )
        if status == 202:
            client.wait_for_operation(headers["location"])
            workspace = _find_named(_list_all(client, "/workspaces"), display_name)
    if workspace is None:
        raise RuntimeError("Fabric workspace creation completed but the workspace was not found.")
    if workspace.get("capacityId") != capacity_id:
        _, headers, status = client.request(
            "POST",
            f"/workspaces/{workspace['id']}/assignToCapacity",
            {"capacityId": capacity_id},
        )
        if status == 202:
            client.wait_for_operation(headers["location"])
        workspace = _find_named(_list_all(client, "/workspaces"), display_name) or workspace
        if workspace.get("capacityId") != capacity_id:
            raise RuntimeError(
                f"Workspace {workspace['id']} is not assigned to capacity {capacity_id}."
            )
    return workspace


def ensure_lakehouse(
    client: FabricClient, workspace_id: str, display_name: str
) -> dict[str, Any]:
    path = f"/workspaces/{workspace_id}/items?type=Lakehouse"
    lakehouse = _find_named(_list_all(client, path), display_name)
    if lakehouse is None:
        _, headers, status = client.request(
            "POST",
            f"/workspaces/{workspace_id}/lakehouses",
            {
                "displayName": display_name,
                "description": (
                    "Deterministic synthetic SiC lot, wafer, tester, recipe, and e-test data."
                ),
            },
        )
        if status == 202:
            client.wait_for_operation(headers["location"])
        lakehouse = _find_named(_list_all(client, path), display_name)
    if lakehouse is None:
        raise RuntimeError("Fabric Lakehouse creation completed but the item was not found.")
    return lakehouse


def _typed_tables(model_path: Path) -> dict[str, list[dict[str, Any]]]:
    tables = load_fabric_tables(model_path)
    typed: dict[str, list[dict[str, Any]]] = {}
    for table_name, rows in tables.items():
        converted: list[dict[str, Any]] = []
        for row in rows:
            converted_row: dict[str, Any] = {}
            for column, value_type in TABLE_TYPES[table_name].items():
                value = row[column]
                if value_type == "BigInt":
                    converted_row[column] = int(value)
                elif value_type == "Double":
                    converted_row[column] = float(value)
                else:
                    converted_row[column] = value
            converted.append(converted_row)
        typed[table_name] = converted
    return typed


def _notebook_definition(
    workspace_id: str,
    lakehouse_id: str,
    lakehouse_name: str,
    model_path: Path,
) -> dict[str, Any]:
    tables = _typed_tables(model_path)
    spark_types = {
        "String": "StringType()",
        "BigInt": "LongType()",
        "Double": "DoubleType()",
    }
    schema_code: dict[str, list[tuple[str, str]]] = {
        table_name: [
            (column, spark_types[value_type])
            for column, value_type in columns.items()
        ]
        for table_name, columns in TABLE_TYPES.items()
    }
    code = f"""\
import json
from pyspark.sql.types import DoubleType, LongType, StringType, StructField, StructType

tables = json.loads({json.dumps(json.dumps(tables, separators=(",", ":")))})
schema_code = {schema_code!r}
counts = {{}}
for table_name, rows in tables.items():
    fields = [
        StructField(column, eval(type_expression), False)
        for column, type_expression in schema_code[table_name]
    ]
    schema = StructType(fields)
    ordered_rows = [
        tuple(row[column] for column, _ in schema_code[table_name])
        for row in rows
    ]
    dataframe = spark.createDataFrame(ordered_rows, schema)
    dataframe.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(table_name)
    counts[table_name] = spark.table(table_name).count()

expected = {{name: len(rows) for name, rows in tables.items()}}
assert counts == expected, f"Unexpected table counts: {{counts}} != {{expected}}"
print(json.dumps({{"status": "completed", "counts": counts}}, sort_keys=True))
"""
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Synapse PySpark",
                "language": "Python",
                "name": "synapse_pyspark",
            },
            "language_info": {"name": "python"},
            "trident": {
                "lakehouse": {
                    "default_lakehouse": lakehouse_id,
                    "default_lakehouse_name": lakehouse_name,
                    "default_lakehouse_workspace_id": workspace_id,
                    "known_lakehouses": [{"id": lakehouse_id}],
                }
            },
        },
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# ST IQ synthetic Fabric seed\n",
                    "Generated from FabricIQ_Data_Model.md. All records are fictional.\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [f"{line}\n" for line in code.splitlines()],
            },
        ],
    }
    return {
        "format": "ipynb",
        "parts": [
            _definition_part("notebook-content.ipynb", notebook),
            _definition_part(
                ".platform",
                {
                    "$schema": (
                        "https://developer.microsoft.com/json-schemas/fabric/"
                        "item/platformProperties/2.0.0/schema.json"
                    ),
                    "metadata": {"type": "Notebook", "displayName": "Seed ST IQ Fabric Data"},
                    "config": {
                        "version": "2.0",
                        "logicalId": str(
                            uuid.uuid5(uuid.NAMESPACE_URL, "st-iq-fabric:seed-notebook")
                        ),
                    },
                },
            ),
        ],
    }


def ensure_seed_notebook(
    client: FabricClient,
    workspace_id: str,
    lakehouse: dict[str, Any],
    model_path: Path,
) -> dict[str, Any]:
    display_name = "Seed ST IQ Fabric Data"
    definition = _notebook_definition(
        workspace_id, lakehouse["id"], lakehouse["displayName"], model_path
    )
    path = f"/workspaces/{workspace_id}/items?type=Notebook"
    notebook = _find_named(_list_all(client, path), display_name)
    if notebook is None:
        _, headers, status = client.request(
            "POST",
            f"/workspaces/{workspace_id}/notebooks",
            {
                "displayName": display_name,
                "description": "Idempotently loads the synthetic ST IQ ontology source tables.",
                "definition": definition,
            },
        )
    else:
        _, headers, status = client.request(
            "POST",
            f"/workspaces/{workspace_id}/notebooks/{notebook['id']}/updateDefinition",
            {"definition": definition},
        )
    if status == 202:
        client.wait_for_operation(headers["location"])
    notebook = _find_named(_list_all(client, path), display_name)
    if notebook is None:
        raise RuntimeError("Fabric notebook upsert completed but the item was not found.")
    return notebook


def run_seed_notebook(
    client: FabricClient, workspace_id: str, notebook_id: str
) -> dict[str, Any]:
    _, headers, status = client.request(
        "POST",
        (
            f"/workspaces/{workspace_id}/items/{notebook_id}/jobs/instances"
            "?jobType=RunNotebook"
        ),
        {},
    )
    if status != 202 or "location" not in headers:
        raise RuntimeError("Fabric did not return a job-instance location for the notebook run.")
    return client.wait_for_job(headers["location"], label="notebook job")


def verify_lakehouse_tables(
    client: FabricClient,
    workspace_id: str,
    lakehouse_id: str,
) -> list[dict[str, Any]]:
    tables = _list_all(
        client,
        f"/workspaces/{workspace_id}/lakehouses/{lakehouse_id}/tables",
    )
    actual = {str(table.get("name")) for table in tables}
    expected = {name.casefold() for name in TABLE_TYPES}
    if actual != expected:
        raise RuntimeError(
            "Fabric Lakehouse table registration mismatch: "
            f"expected {sorted(expected)}, found {sorted(actual)}."
        )
    return tables


def refresh_sql_endpoint_metadata(
    client: FabricClient,
    workspace_id: str,
    sql_endpoint_id: str,
) -> Any:
    result, headers, status = client.request(
        "POST",
        (
            f"/workspaces/{workspace_id}/sqlEndpoints/{sql_endpoint_id}/"
            "refreshMetadata"
        ),
        {"recreateTables": True},
        timeout=900,
    )
    if status == 202:
        return client.wait_for_operation(headers["location"], timeout_seconds=900)
    failures = [
        item
        for item in (result or {}).get("value", [])
        if item.get("status") not in {"Success", "NotRun"}
    ]
    if failures:
        raise RuntimeError(
            "Fabric SQL endpoint metadata refresh failed: "
            + json.dumps(failures, ensure_ascii=True)
        )
    return result


def refresh_ontology_graph(
    client: FabricClient,
    workspace_id: str,
    ontology_name: str,
) -> tuple[dict[str, Any], Any]:
    graph_models = _list_all(client, f"/workspaces/{workspace_id}/graphModels")
    prefix = f"{ontology_name}_graph_"
    matches = [
        graph
        for graph in graph_models
        if str(graph.get("displayName", "")).startswith(prefix)
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one generated graph model for '{ontology_name}', found {len(matches)}."
        )
    graph = matches[0]
    jobs_path = (
        f"/workspaces/{workspace_id}/items/{graph['id']}/jobs/instances"
        "?jobType=Refresh"
    )
    active_jobs = [
        job
        for job in _list_all(client, jobs_path)
        if str(job.get("status", "")).casefold() in {"notstarted", "inprogress"}
    ]
    if active_jobs:
        active = active_jobs[0]
        location = (
            f"/workspaces/{workspace_id}/items/{graph['id']}/jobs/instances/"
            f"{active['id']}"
        )
        return graph, client.wait_for_job(
            location,
            timeout_seconds=900,
            label="graph refresh",
        )
    result, headers, status = client.request(
        "POST",
        (
            f"/workspaces/{workspace_id}/graphModels/{graph['id']}/jobs/instances"
            "?jobType=RefreshGraph"
        ),
        {},
    )
    if status == 202:
        result = client.wait_for_job(
            headers["location"],
            timeout_seconds=900,
            label="graph refresh",
        )
    return graph, result


def _ontology_definition(
    workspace_id: str,
    lakehouse_id: str,
    display_name: str,
) -> dict[str, Any]:
    entity_ids = {name: _stable_id(f"entity:{name}") for name in TABLE_TYPES}
    property_ids = {
        entity: {
            prop: _stable_id(f"entity:{entity}:property:{prop}")
            for prop in properties
        }
        for entity, properties in TABLE_TYPES.items()
    }
    parts = [
        _definition_part(
            ".platform",
            {
                "$schema": (
                    "https://developer.microsoft.com/json-schemas/fabric/"
                    "item/platformProperties/2.0.0/schema.json"
                ),
                "metadata": {"type": "Ontology", "displayName": display_name},
                "config": {
                    "version": "2.0",
                    "logicalId": str(
                        uuid.uuid5(uuid.NAMESPACE_URL, "st-iq-fabric:ontology")
                    ),
                },
            },
        ),
        _definition_part("definition.json", {}),
    ]
    for entity, columns in TABLE_TYPES.items():
        entity_id = entity_ids[entity]
        keys = ENTITY_KEYS[entity]
        parts.append(
            _definition_part(
                f"EntityTypes/{entity_id}/definition.json",
                {
                    "id": entity_id,
                    "namespace": "usertypes",
                    "baseEntityTypeId": None,
                    "name": entity,
                    "entityIdParts": [property_ids[entity][key] for key in keys],
                    "displayNamePropertyId": property_ids[entity][keys[0]],
                    "namespaceType": "Custom",
                    "visibility": "Visible",
                    "properties": [
                        {
                            "id": property_ids[entity][column],
                            "name": column,
                            "redefines": None,
                            "baseTypeNamespaceType": None,
                            "valueType": value_type,
                        }
                        for column, value_type in columns.items()
                    ],
                },
            )
        )
        binding_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"st-iq-fabric:{entity}:binding")
        )
        parts.append(
            _definition_part(
                f"EntityTypes/{entity_id}/DataBindings/{binding_id}.json",
                {
                    "id": binding_id,
                    "dataBindingConfiguration": {
                        "dataBindingType": "NonTimeSeries",
                        "propertyBindings": [
                            {
                                "sourceColumnName": column,
                                "targetPropertyId": property_ids[entity][column],
                            }
                            for column in columns
                        ],
                        "sourceTableProperties": {
                            "sourceType": "LakehouseTable",
                            "workspaceId": workspace_id,
                            "itemId": lakehouse_id,
                            "sourceTableName": entity.casefold(),
                        },
                    },
                },
            )
        )
    for (
        relationship,
        source,
        target,
        binding_table,
        source_columns,
        target_columns,
    ) in RELATIONSHIPS:
        relationship_id = _stable_id(f"relationship:{relationship}")
        parts.append(
            _definition_part(
                f"RelationshipTypes/{relationship_id}/definition.json",
                {
                    "namespace": "usertypes",
                    "id": relationship_id,
                    "name": relationship,
                    "namespaceType": "Custom",
                    "source": {"entityTypeId": entity_ids[source]},
                    "target": {"entityTypeId": entity_ids[target]},
                },
            )
        )
        contextualization_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"st-iq-fabric:{relationship}:context")
        )
        parts.append(
            _definition_part(
                (
                    f"RelationshipTypes/{relationship_id}/Contextualizations/"
                    f"{contextualization_id}.json"
                ),
                {
                    "id": contextualization_id,
                    "dataBindingTable": {
                        "workspaceId": workspace_id,
                        "itemId": lakehouse_id,
                        "sourceTableName": binding_table.casefold(),
                        "sourceType": "LakehouseTable",
                    },
                    "sourceKeyRefBindings": [
                        {
                            "sourceColumnName": column,
                            "targetPropertyId": property_ids[source][key],
                        }
                        for column, key in zip(
                            source_columns, ENTITY_KEYS[source], strict=True
                        )
                    ],
                    "targetKeyRefBindings": [
                        {
                            "sourceColumnName": column,
                            "targetPropertyId": property_ids[target][key],
                        }
                        for column, key in zip(
                            target_columns, ENTITY_KEYS[target], strict=True
                        )
                    ],
                },
            )
        )
    return {"parts": parts}


def ensure_ontology(
    client: FabricClient,
    workspace_id: str,
    lakehouse_id: str,
    display_name: str,
) -> dict[str, Any]:
    definition = _ontology_definition(workspace_id, lakehouse_id, display_name)
    path = f"/workspaces/{workspace_id}/items?type=Ontology"
    ontology = _find_named(_list_all(client, path), display_name)
    if ontology is None:
        _, headers, status = client.request(
            "POST",
            f"/workspaces/{workspace_id}/ontologies",
            {
                "displayName": display_name,
                "description": (
                    "Synthetic Lot-Wafer-Tester-Recipe-ETestResult ontology for SIC-QI-2451."
                ),
                "definition": definition,
            },
        )
    else:
        current, _, _ = client.request(
            "POST",
            f"/workspaces/{workspace_id}/items/{ontology['id']}/getDefinition",
            {},
        )
        if _decoded_definition_parts(current.get("definition", {})) == (
            _decoded_definition_parts(definition)
        ):
            status, headers = 200, {}
        else:
            _, headers, status = client.request(
                "POST",
                f"/workspaces/{workspace_id}/ontologies/{ontology['id']}/updateDefinition",
                {"definition": definition},
            )
    if status == 202:
        client.wait_for_operation(headers["location"])
    ontology = _find_named(_list_all(client, path), display_name)
    if ontology is None:
        raise RuntimeError("Fabric ontology upsert completed but the item was not found.")
    return ontology


def list_ontology_tools(
    client: FabricClient, workspace_id: str, ontology_id: str
) -> tuple[str, list[dict[str, Any]]]:
    endpoint = (
        f"{FABRIC_API}/mcp/dataPlane/workspaces/{workspace_id}/items/"
        f"{ontology_id}/ontologyEndpoint"
    )
    response, _, _ = client.request(
        "POST",
        endpoint,
        {"jsonrpc": "2.0", "id": "st-iq-tools-list", "method": "tools/list"},
    )
    if response.get("error"):
        raise RuntimeError(f"Fabric ontology MCP tools/list failed: {json.dumps(response)}")
    return endpoint, response.get("result", {}).get("tools", [])


def select_and_verify_ontology_tool(
    client: FabricClient, endpoint: str, tools: list[dict[str, Any]]
) -> tuple[str, dict[str, Any], Any]:
    if not tools:
        raise RuntimeError("Fabric ontology MCP advertised no tools.")
    ranked = sorted(
        tools,
        key=lambda tool: sum(
            term
            in f"{tool.get('name', '')} {tool.get('description', '')}".casefold()
            for term in ("query", "search", "ontology", "graph", "data")
        ),
        reverse=True,
    )
    query = (
        "For LotID SiC-AUTO-2451, list WaferID, TesterID, Tester LastPM_date, "
        "RecipeID, Recipe AnnealTemp_C, Vth Value, and USL."
    )
    selected: dict[str, Any] | None = None
    arguments: dict[str, Any] = {}
    for tool in ranked:
        schema = tool.get("inputSchema", {})
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        candidate: dict[str, Any] = {}
        compatible = True
        for name in required:
            definition = properties.get(name, {})
            normalized = name.casefold()
            if definition.get("type") == "string":
                candidate[name] = (
                    "SiC-AUTO-2451"
                    if normalized in {"lot", "lotid", "lot_id", "entityid", "entity_id"}
                    else query
                )
            else:
                compatible = False
                break
        if compatible:
            optional_query = next(
                (
                    name
                    for name, definition in properties.items()
                    if name not in candidate
                    and definition.get("type") == "string"
                    and any(
                        term in name.casefold()
                        for term in ("query", "question", "prompt", "search")
                    )
                ),
                None,
            )
            if optional_query:
                candidate[optional_query] = query
            selected, arguments = tool, candidate
            break
    if selected is None:
        raise RuntimeError(
            "Fabric ontology MCP exposed tools, but none had a safe string-only input contract."
        )
    deadline = time.monotonic() + 600
    while True:
        response, _, _ = client.request(
            "POST",
            endpoint,
            {
                "jsonrpc": "2.0",
                "id": "st-iq-tools-call",
                "method": "tools/call",
                "params": {"name": selected["name"], "arguments": arguments},
            },
        )
        result_text = json.dumps(response)
        if (
            response.get("result", {}).get("isError")
            and "Graph Model is not ready" in result_text
            and time.monotonic() < deadline
        ):
            print("Fabric ontology graph model is still building; retrying...", flush=True)
            time.sleep(15)
            continue
        break
    if response.get("error") or response.get("result", {}).get("isError"):
        raise RuntimeError(f"Fabric ontology MCP verification failed: {json.dumps(response)}")
    result = response.get("result", {})
    if not result.get("structuredContent") and not result.get("content"):
        raise RuntimeError("Fabric ontology MCP verification returned no evidence.")
    return selected["name"], arguments, result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--capacity-id", required=True)
    parser.add_argument("--workspace-name", default="ST IQ Semiconductor Demo")
    parser.add_argument("--lakehouse-name", default="STIQSemiconductorLakehouse")
    parser.add_argument("--ontology-name", default="STIQSemiconductorOperations")
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-seed", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = FabricClient(args.tenant_id)
    evidence: dict[str, Any] = {
        "source": str(args.model_path),
        "synthetic": True,
        "capacityId": args.capacity_id,
    }
    try:
        workspace = ensure_workspace(client, args.workspace_name, args.capacity_id)
        evidence["workspace"] = workspace
        lakehouse = ensure_lakehouse(client, workspace["id"], args.lakehouse_name)
        lakehouse, _, _ = client.request(
            "GET",
            f"/workspaces/{workspace['id']}/lakehouses/{lakehouse['id']}",
        )
        evidence["lakehouse"] = lakehouse
        notebook = ensure_seed_notebook(client, workspace["id"], lakehouse, args.model_path)
        evidence["notebook"] = notebook
        evidence["notebookJob"] = (
            {
                "status": "Skipped",
                "reason": "Verification-only retry reused the last successful seed run.",
            }
            if args.skip_seed
            else run_seed_notebook(client, workspace["id"], notebook["id"])
        )
        evidence["verifiedTableCounts"] = {
            table_name: len(rows)
            for table_name, rows in _typed_tables(args.model_path).items()
        }
        evidence["lakehouseTables"] = verify_lakehouse_tables(
            client,
            workspace["id"],
            lakehouse["id"],
        )
        sql_endpoint_id = (
            lakehouse.get("properties", {})
            .get("sqlEndpointProperties", {})
            .get("id")
        )
        if not sql_endpoint_id:
            raise RuntimeError("Fabric Lakehouse returned no SQL analytics endpoint ID.")
        evidence["sqlEndpointMetadataRefresh"] = refresh_sql_endpoint_metadata(
            client,
            workspace["id"],
            sql_endpoint_id,
        )
        ontology = ensure_ontology(
            client, workspace["id"], lakehouse["id"], args.ontology_name
        )
        evidence["ontology"] = ontology
        graph_model, graph_refresh = refresh_ontology_graph(
            client,
            workspace["id"],
            args.ontology_name,
        )
        evidence["graphModel"] = graph_model
        evidence["graphRefreshJob"] = graph_refresh
        endpoint, tools = list_ontology_tools(client, workspace["id"], ontology["id"])
        evidence["ontologyMcpEndpoint"] = endpoint
        evidence["advertisedTools"] = tools
        tool_name, tool_arguments, verification = select_and_verify_ontology_tool(
            client, endpoint, tools
        )
        evidence["toolName"] = tool_name
        evidence["toolArguments"] = tool_arguments
        evidence["verification"] = verification
        evidence["status"] = "live"
    except FabricApiError as error:
        evidence["status"] = "blocked"
        evidence["blocker"] = str(error)
    except (RuntimeError, TimeoutError) as error:
        evidence["status"] = "blocked"
        evidence["blocker"] = str(error)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0 if evidence["status"] == "live" else 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import base64
import json
from pathlib import Path

from scripts.provision_fabric_iq import (
    _list_all,
    _notebook_definition,
    _ontology_definition,
    refresh_ontology_graph,
)

ROOT = Path(__file__).resolve().parents[1]


def _decoded_parts(definition: dict) -> dict[str, dict]:
    return {
        part["path"]: json.loads(base64.b64decode(part["payload"]))
        for part in definition["parts"]
    }


def test_ontology_definition_binds_all_entities_and_relationships() -> None:
    definition = _ontology_definition("workspace-id", "lakehouse-id", "ST IQ Operations")
    parts = _decoded_parts(definition)
    entity_parts = {
        path: payload
        for path, payload in parts.items()
        if path.startswith("EntityTypes/") and path.endswith("/definition.json")
    }
    relationship_parts = {
        path: payload
        for path, payload in parts.items()
        if path.startswith("RelationshipTypes/") and path.endswith("/definition.json")
    }

    assert {payload["name"] for payload in entity_parts.values()} == {
        "Lot",
        "Wafer",
        "Tester",
        "Recipe",
        "ETestResult",
    }
    assert {payload["name"] for payload in relationship_parts.values()} == {
        "LotContainsWafer",
        "WaferTestedOnTester",
        "WaferUsesRecipe",
        "WaferHasETestResult",
    }
    bindings = [
        payload
        for path, payload in parts.items()
        if "/DataBindings/" in path
    ]
    assert len(bindings) == 5
    assert all(
        binding["dataBindingConfiguration"]["sourceTableProperties"]["itemId"]
        == "lakehouse-id"
        for binding in bindings
    )
    assert all(
        "sourceSchema"
        not in binding["dataBindingConfiguration"]["sourceTableProperties"]
        for binding in bindings
    )
    assert {
        binding["dataBindingConfiguration"]["sourceTableProperties"]["sourceTableName"]
        for binding in bindings
    } == {"lot", "wafer", "tester", "recipe", "etestresult"}
    contextualizations = [
        payload
        for path, payload in parts.items()
        if "/Contextualizations/" in path
    ]
    assert {
        contextualization["dataBindingTable"]["sourceTableName"]
        for contextualization in contextualizations
    } == {"wafer", "etestresult"}


def test_seed_notebook_uses_canonical_markdown_tables() -> None:
    definition = _notebook_definition(
        "workspace-id",
        "lakehouse-id",
        "STIQSemiconductorLakehouse",
        ROOT / "data" / "v1" / "fabric_iq" / "FabricIQ_Data_Model.md",
    )
    notebook = _decoded_parts(definition)["notebook-content.ipynb"]
    source = "".join(notebook["cells"][1]["source"])

    assert notebook["metadata"]["trident"]["lakehouse"] == {
        "default_lakehouse": "lakehouse-id",
        "default_lakehouse_name": "STIQSemiconductorLakehouse",
        "default_lakehouse_workspace_id": "workspace-id",
        "known_lakehouses": [{"id": "lakehouse-id"}],
    }
    assert '.saveAsTable(table_name)' in source
    assert "SiC-AUTO-2451" in source
    assert "T-07" in source
    assert "R-GOX-12" in source
    assert "Value" in source and "4.1" in source


def test_list_all_supports_fabric_data_collection_shape() -> None:
    class Client:
        def request(self, method: str, path: str):
            assert method == "GET"
            assert path == "/tables"
            return {"data": [{"name": "lot"}]}, {}, 200

    assert _list_all(Client(), "/tables") == [{"name": "lot"}]


def test_graph_refresh_reuses_an_active_service_job() -> None:
    class Client:
        waited_for: str | None = None

        def request(self, method: str, path: str):
            assert method == "GET"
            if path.endswith("/graphModels"):
                return {
                    "value": [
                        {
                            "id": "graph-id",
                            "displayName": "STIQ_graph_ontology-id",
                        }
                    ]
                }, {}, 200
            if "jobs/instances?jobType=Refresh" in path:
                return {
                    "value": [{"id": "job-id", "status": "InProgress"}]
                }, {}, 200
            raise AssertionError(f"Unexpected request: {method} {path}")

        def wait_for_job(self, location: str, **_kwargs):
            self.waited_for = location
            return {"id": "job-id", "status": "Completed"}

    client = Client()
    graph, job = refresh_ontology_graph(client, "workspace-id", "STIQ")

    assert graph["id"] == "graph-id"
    assert job["status"] == "Completed"
    assert client.waited_for.endswith(
        "/items/graph-id/jobs/instances/job-id"
    )

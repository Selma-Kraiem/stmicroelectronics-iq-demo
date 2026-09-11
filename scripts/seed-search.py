"""Idempotently seed public-source metadata and synthetic procedures into Foundry IQ."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import requests

from app.data import build_demo_data

API_VERSION = "2026-05-01-preview"
SEARCH_SCOPE = "https://search.azure.com/.default"
REPO_ROOT = Path(__file__).resolve().parents[1]
V1_FOUNDRY_IQ_DIR = REPO_ROOT / "data" / "v1" / "foundry_iq"


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set.")
    return value


class SearchRestClient:
    def __init__(self, endpoint: str) -> None:
        token_command = [
            "az",
            "account",
            "get-access-token",
            "--scope",
            SEARCH_SCOPE,
        ]
        tenant_id = os.getenv("AZURE_TENANT_ID", "").strip()
        if tenant_id:
            token_command.extend(["--tenant", tenant_id])
        token_command.extend(
            [
                "--query",
                "accessToken",
                "-o",
                "tsv",
            ]
        )
        token_result = subprocess.run(
            token_command,
            check=True,
            capture_output=True,
            text=True,
            shell=os.name == "nt",
        )
        token = token_result.stdout.strip()
        if not token:
            raise RuntimeError("Azure CLI returned no Azure AI Search access token.")
        self.endpoint = endpoint.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def request(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = requests.request(
            method,
            f"{self.endpoint}/{path}?api-version={API_VERSION}",
            headers=self.headers,
            json=body,
            timeout=180,
        )
        if response.status_code not in (200, 201, 204):
            raise RuntimeError(
                f"{method} {path} failed ({response.status_code}): {response.text}"
            )
        return response.json() if response.content else {}


def documents() -> list[dict[str, Any]]:
    public_sources = json.loads((REPO_ROOT / "data/public_sources.json").read_text())
    procedures = json.loads((REPO_ROOT / "data/synthetic_procedures.json").read_text())
    records: list[dict[str, Any]] = []
    for index, source in enumerate(public_sources, start=1):
        records.append(
            {
                "id": f"public-{index}",
                "title": source["title"],
                "content": source["index_note"],
                "source_url": source["url"],
                "source_type": "public-st-source",
                "classification": "public",
                "synthetic": False,
                "updated_at": source["retrieved_at"],
            }
        )
    for procedure in procedures:
        records.append(
            {
                "id": procedure["id"],
                "title": procedure["title"],
                "content": procedure["content"],
                "source_url": f"synthetic://procedures/{procedure['id']}",
                "source_type": "synthetic-internal-procedure",
                "classification": "synthetic-demo-only",
                "synthetic": True,
                "updated_at": procedure["effective_date"],
            }
        )
    for source in sorted(V1_FOUNDRY_IQ_DIR.glob("*.md")):
        content = source.read_text(encoding="utf-8")
        heading = next(
            (
                line.removeprefix("#").strip()
                for line in content.splitlines()
                if line.startswith("# ")
            ),
            source.stem,
        )
        records.append(
            {
                "id": f"v1-foundry-iq-{source.stem.lower().replace('_', '-')}",
                "title": heading,
                "content": f"SYNTHETIC DEMO KNOWLEDGE.\n\n{content}",
                "source_url": f"repo://data/v1/foundry_iq/{source.name}",
                "source_type": "synthetic-foundry-iq-document",
                "classification": "synthetic-demo-only",
                "synthetic": True,
                "updated_at": "2026-08-30",
            }
        )
    scenario = build_demo_data()
    operational_groups = {
        "plant": scenario.plants,
        "product": scenario.products,
        "lot": scenario.lots,
        "customer": scenario.customers,
        "order": scenario.orders,
        "inventory": scenario.inventory,
        "telemetry": scenario.telemetry,
        "incident": scenario.incidents,
    }
    for entity_type, items in operational_groups.items():
        for index, item in enumerate(items, start=1):
            record_id = str(item.get("id") or f"{entity_type}-{index}")
            records.append(
                {
                    "id": f"synthetic-{entity_type}-{record_id}".replace("_", "-"),
                    "title": f"Synthetic {entity_type}: {record_id}",
                    "content": (
                        "SYNTHETIC DEMO DATA. Deterministic semiconductor operational record. "
                        f"Entity type: {entity_type}. Record: "
                        f"{json.dumps(item, sort_keys=True, ensure_ascii=True)}"
                    ),
                    "source_url": f"synthetic://operations/{entity_type}/{record_id}",
                    "source_type": "synthetic-operational-record",
                    "classification": "synthetic-demo-only",
                    "synthetic": True,
                    "updated_at": "2026-08-13",
                }
            )
    return records


def main() -> None:
    endpoint = required("AZURE_SEARCH_ENDPOINT")
    openai_endpoint = required("AZURE_OPENAI_ENDPOINT")
    model = required("AZURE_AI_MODEL_DEPLOYMENT_NAME")
    index_name = os.getenv("AZURE_SEARCH_INDEX_NAME", "st-iq-knowledge")
    indexed_source = os.getenv("KNOWLEDGE_SOURCE_NAME", "st-iq-index-source")
    knowledge_base = os.getenv("KNOWLEDGE_BASE_NAME", "st-iq-knowledge-base")
    web_source = os.getenv("WEB_KNOWLEDGE_SOURCE_NAME", "st-iq-web-source")
    web_base = os.getenv("WEB_KNOWLEDGE_BASE_NAME", "st-iq-web-base")
    client = SearchRestClient(endpoint)

    client.request(
        "PUT",
        f"indexes/{index_name}",
        {
            "name": index_name,
            "fields": [
                {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
                {"name": "title", "type": "Edm.String", "searchable": True, "retrievable": True},
                {"name": "content", "type": "Edm.String", "searchable": True, "retrievable": True},
                {
                    "name": "source_url",
                    "type": "Edm.String",
                    "filterable": True,
                    "retrievable": True,
                },
                {
                    "name": "source_type",
                    "type": "Edm.String",
                    "filterable": True,
                    "retrievable": True,
                },
                {
                    "name": "classification",
                    "type": "Edm.String",
                    "filterable": True,
                    "retrievable": True,
                },
                {
                    "name": "synthetic",
                    "type": "Edm.Boolean",
                    "filterable": True,
                    "retrievable": True,
                },
                {
                    "name": "updated_at",
                    "type": "Edm.String",
                    "filterable": True,
                    "retrievable": True,
                },
            ],
            "semantic": {
                "configurations": [
                    {
                        "name": "default-semantic-config",
                        "prioritizedFields": {
                            "titleField": {"fieldName": "title"},
                            "prioritizedContentFields": [{"fieldName": "content"}],
                            "prioritizedKeywordsFields": [
                                {"fieldName": "source_type"},
                                {"fieldName": "classification"},
                            ],
                        },
                    }
                ]
            },
        },
    )
    client.request(
        "POST",
        f"indexes/{index_name}/docs/index",
        {"value": [{"@search.action": "mergeOrUpload", **item} for item in documents()]},
    )
    client.request(
        "PUT",
        f"knowledgesources/{indexed_source}",
        {
            "name": indexed_source,
            "kind": "searchIndex",
            "description": (
                "Public ST metadata, SharePoint-synchronized content when configured, and "
                "deterministic synthetic procedures and operations."
            ),
            "searchIndexParameters": {
                "searchIndexName": index_name,
                "semanticConfigurationName": "default-semantic-config",
                "sourceDataFields": [
                    {"name": "title"},
                    {"name": "content"},
                    {"name": "source_url"},
                    {"name": "source_type"},
                    {"name": "classification"},
                    {"name": "synthetic"},
                ],
                "searchFields": [{"name": "title"}, {"name": "content"}],
            },
        },
    )
    web_source_body = {
        "name": web_source,
        "kind": "web",
        "description": "Web Knowledge Source (Web IQ fallback) for current public context.",
        "webParameters": {
            "domains": {
                "allowedDomains": [
                    {"address": "st.com", "includeSubpages": True},
                    {"address": "ec.europa.eu", "includeSubpages": True},
                    {"address": "europa.eu", "includeSubpages": True},
                    {"address": "nhtsa.gov", "includeSubpages": True},
                    {"address": "noaa.gov", "includeSubpages": True},
                    {"address": "meteoalarm.org", "includeSubpages": True},
                    {"address": "semiconductors.org", "includeSubpages": True},
                ]
            }
        },
    }
    web_label = "Web Knowledge Source (Web IQ fallback)"
    client.request("PUT", f"knowledgesources/{web_source}", web_source_body)

    model_reference = {
        "kind": "azureOpenAI",
        "azureOpenAIParameters": {
            "resourceUri": openai_endpoint.rstrip("/"),
            "deploymentId": model,
            "modelName": model,
        },
    }
    client.request(
        "PUT",
        f"knowledgebases/{knowledge_base}",
        {
            "name": knowledge_base,
            "description": (
                "Foundry IQ source for public ST references, approved SharePoint-synchronized "
                "content, and deterministic synthetic procedures and operations."
            ),
            "knowledgeSources": [{"name": indexed_source}],
            "outputMode": "answerSynthesis",
            "retrievalReasoningEffort": {"kind": "low"},
            "answerInstructions": (
                "Cite each factual claim. Preserve public, SharePoint, and synthetic:// source "
                "references. Always state when a source or operational record is synthetic demo "
                "data. Never describe a synchronized SharePoint source as Work IQ."
            ),
            "models": [model_reference],
        },
    )
    client.request(
        "PUT",
        f"knowledgebases/{web_base}",
        {
            "name": web_base,
            "description": f"Public external context from {web_label}.",
            "knowledgeSources": [{"name": web_source}],
            "outputMode": "answerSynthesis",
            "retrievalReasoningEffort": {"kind": "low"},
            "retrievalInstructions": (
                "Use only sanitized public-information queries. Never include customer, lot, "
                "yield, tenant, email, Teams, SharePoint, or other confidential details."
            ),
            "answerInstructions": "Return concise current context with citations and dates.",
            "models": [model_reference],
        },
    )

    print(f"Seeded {len(documents())} records into {index_name}.")
    print(
        "Foundry IQ MCP: "
        f"{endpoint.rstrip('/')}/knowledgebases/{knowledge_base}/mcp?api-version={API_VERSION}"
    )
    print(
        f"{web_label} MCP: "
        f"{endpoint.rstrip('/')}/knowledgebases/{web_base}/mcp?api-version={API_VERSION}"
    )


if __name__ == "__main__":
    main()

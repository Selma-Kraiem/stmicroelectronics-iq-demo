"""Create the V2 document-only Foundry IQ index and web knowledge source."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import httpx

API_VERSION = "2026-05-01-preview"
SEARCH_SCOPE = "https://search.azure.com/.default"
REPO_ROOT = Path(__file__).resolve().parents[2]


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set.")
    return value


class SearchRestClient:
    def __init__(self, endpoint: str) -> None:
        token_result = subprocess.run(
            [
                "az",
                "account",
                "get-access-token",
                "--scope",
                SEARCH_SCOPE,
                "--query",
                "accessToken",
                "-o",
                "tsv",
            ],
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
        response = httpx.request(
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
    """Return licensed public metadata and synthetic procedures, never operational rows."""
    public_sources = json.loads((REPO_ROOT / "data/public_sources.json").read_text())
    procedures = json.loads((REPO_ROOT / "data/synthetic_procedures.json").read_text())
    records: list[dict[str, Any]] = []
    for index, source in enumerate(public_sources, start=1):
        records.append(
            {
                "id": f"public-v2-{index}",
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
    return records


def main() -> None:
    endpoint = required("AZURE_SEARCH_ENDPOINT")
    openai_endpoint = required("AZURE_OPENAI_ENDPOINT")
    model = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-5.4-mini")
    index_name = os.getenv("V2_SEARCH_INDEX_NAME", "st-iq-v2-documents")
    indexed_source = os.getenv("V2_KNOWLEDGE_SOURCE_NAME", "st-iq-v2-document-source")
    knowledge_base = os.getenv("V2_KNOWLEDGE_BASE_NAME", "st-iq-v2-knowledge-base")
    web_source = os.getenv("V2_WEB_SOURCE_NAME", "st-iq-v2-web-source")
    web_base = os.getenv("V2_WEB_BASE_NAME", "st-iq-v2-web-base")
    client = SearchRestClient(endpoint)
    records = documents()

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
                        "name": "v2-semantic-config",
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
        {"value": [{"@search.action": "mergeOrUpload", **item} for item in records]},
    )
    client.request(
        "PUT",
        f"knowledgesources/{indexed_source}",
        {
            "name": indexed_source,
            "kind": "searchIndex",
            "description": (
                "V2 document-only source: attributed public ST metadata and synthetic "
                "internal procedures. Operational entities are intentionally excluded."
            ),
            "searchIndexParameters": {
                "searchIndexName": index_name,
                "semanticConfigurationName": "v2-semantic-config",
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
    client.request(
        "PUT",
        f"knowledgesources/{web_source}",
        {
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
        },
    )

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
            "description": "V2 Foundry IQ document knowledge, separate from structured APIs.",
            "knowledgeSources": [{"name": indexed_source}],
            "outputMode": "answerSynthesis",
            "retrievalReasoningEffort": {"kind": "low"},
            "answerInstructions": (
                "Cite every factual claim and preserve the source URL. Label synthetic:// "
                "procedures as deterministic synthetic demo content. Never imply that this "
                "knowledge base contains live manufacturing, customer, Fabric IQ, or Work IQ data."
            ),
            "models": [model_reference],
        },
    )
    client.request(
        "PUT",
        f"knowledgebases/{web_base}",
        {
            "name": web_base,
            "description": "Current public context from Web Knowledge Source (Web IQ fallback).",
            "knowledgeSources": [{"name": web_source}],
            "outputMode": "answerSynthesis",
            "retrievalReasoningEffort": {"kind": "low"},
            "retrievalInstructions": (
                "Use generic public-information queries only. Never include customer, lot, "
                "order, yield, telemetry, tenant, email, Teams, or SharePoint details."
            ),
            "answerInstructions": "Return concise, dated public context with source citations.",
            "models": [model_reference],
        },
    )

    print(f"Seeded {len(records)} document records into {index_name}.")
    print(
        "Foundry IQ MCP: "
        f"{endpoint.rstrip('/')}/knowledgebases/{knowledge_base}/mcp?api-version={API_VERSION}"
    )
    print(
        "Web Knowledge Source (Web IQ fallback) MCP: "
        f"{endpoint.rstrip('/')}/knowledgebases/{web_base}/mcp?api-version={API_VERSION}"
    )


if __name__ == "__main__":
    main()

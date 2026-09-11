"""Upload the V1 shipment workbook and create a reusable Code Interpreter toolbox."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import AutoCodeInterpreterToolParam, CodeInterpreterToolboxTool
from azure.identity import DefaultAzureCredential

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKBOOK = REPO_ROOT / "data" / "v1" / "code_interpreter" / "SiC_AUTO_Shipments.xlsx"
DEFAULT_CSV_FILES = [
    REPO_ROOT / "data" / "v1" / "code_interpreter" / name
    for name in ("Shipments.csv", "Inventory.csv", "LotMaster.csv")
]


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set.")
    return value


def main() -> None:
    endpoint = required("AZURE_AI_PROJECT_ENDPOINT")
    workbook = DEFAULT_WORKBOOK.resolve()
    if not workbook.is_file():
        raise FileNotFoundError(f"Shipment workbook not found: {workbook}")
    if workbook.read_bytes()[:4] != b"PK\x03\x04":
        raise RuntimeError(f"Shipment workbook is not a standard OOXML .xlsx file: {workbook}")
    missing_csv = [str(path) for path in DEFAULT_CSV_FILES if not path.is_file()]
    if missing_csv:
        raise FileNotFoundError(f"Code Interpreter CSV projection is missing: {missing_csv}")

    credential = DefaultAzureCredential()
    project = AIProjectClient(endpoint=endpoint, credential=credential)
    openai = project.get_openai_client()
    uploaded = []
    for path in DEFAULT_CSV_FILES:
        with path.open("rb") as stream:
            uploaded.append(openai.files.create(purpose="assistants", file=stream))

    toolbox = project.toolboxes.create_version(
        name="st-iq-fab-code-toolbox",
        description="Fab Intelligence exposure analysis over synthetic SiC shipment data.",
        tools=[
            CodeInterpreterToolboxTool(
                container=AutoCodeInterpreterToolParam(
                    file_ids=[file.id for file in uploaded]
                )
            )
        ],
    )
    toolbox_endpoint = (
        f"{endpoint.rstrip('/')}/toolboxes/{toolbox.name}/versions/"
        f"{toolbox.version}/mcp?api-version=v1"
    )
    print(
        json.dumps(
            {
                "file_ids": [file.id for file in uploaded],
                "file_name": workbook.name,
                "sha256": hashlib.sha256(workbook.read_bytes()).hexdigest(),
                "mounted_files": [path.name for path in DEFAULT_CSV_FILES],
                "toolbox": toolbox.name,
                "version": toolbox.version,
                "endpoint": toolbox_endpoint,
            }
        )
    )


if __name__ == "__main__":
    main()

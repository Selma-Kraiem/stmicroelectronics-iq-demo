"""Deterministic V1 asset loaders and offline Microsoft IQ fallbacks."""

from __future__ import annotations

import html
import json
import os
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO
from xml.etree import ElementTree

LOT_ID = "SiC-AUTO-2451"
PRODUCT_REF = "SCTW90N65G2V"
ROOT = Path(__file__).resolve().parents[1]


def data_root() -> Path:
    return Path(os.getenv("STIQ_V1_DATA_ROOT", ROOT / "data" / "v1"))


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse an agent JSON response, tolerating a surrounding Markdown fence."""
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, count=1)
        candidate = re.sub(r"\s*```$", "", candidate, count=1)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Agent output did not contain a JSON object.") from None
        value = json.loads(candidate[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Agent output JSON must be an object.")
    return value


def sanitized_external_query() -> str:
    """Return the fixed public-only query used by the Radar web branch."""
    return (
        "Current public regulatory and AEC-Q101 developments, automotive silicon-carbide "
        "market and substrate-supply signals, logistics constraints, and severe-weather "
        "events that could affect European automotive SiC module deliveries"
    )


def calculate_field_exposure(
    lot_id: str = LOT_ID, workbook: Path | None = None
) -> dict[str, Any]:
    """Compute exposure from the canonical workbook without claiming Code Interpreter."""
    path = workbook or data_root() / "code_interpreter" / "SiC_AUTO_Shipments.xlsx"
    if not path.is_file():
        raise FileNotFoundError(f"Shipment workbook not found: {path}")
    sheets = _read_xlsx(path, {"Shipments", "Inventory", "LotMaster"})
    return _calculate_exposure_from_sheets(
        sheets,
        lot_id=lot_id,
        source_mode="synthetic-local",
        source_label="Agent Framework Python function (synthetic workbook)",
        citation_url="repo://data/v1/code_interpreter/SiC_AUTO_Shipments.xlsx",
        citation_badge="Synthetic workbook",
    )


def calculate_field_exposure_bytes(
    content: bytes,
    *,
    lot_id: str = LOT_ID,
    citation_url: str,
) -> dict[str, Any]:
    """Calculate exposure from a validated in-memory XLSX retrieved from OneDrive."""
    if not content.startswith(b"PK"):
        raise ValueError("OneDrive workbook is not a valid OOXML ZIP payload.")
    sheets = _read_xlsx(BytesIO(content), {"Shipments", "Inventory", "LotMaster"})
    return _calculate_exposure_from_sheets(
        sheets,
        lot_id=lot_id,
        source_mode="live-delegated",
        source_label="Work IQ OneDrive live + deterministic Python",
        citation_url=citation_url,
        citation_badge="Work IQ OneDrive live",
    )


def _calculate_exposure_from_sheets(
    sheets: dict[str, list[dict[str, Any]]],
    *,
    lot_id: str,
    source_mode: str,
    source_label: str,
    citation_url: str,
    citation_badge: str,
) -> dict[str, Any]:
    lot_shipments = [row for row in sheets["Shipments"] if str(row["LotID"]) == lot_id]
    lot_inventory = [row for row in sheets["Inventory"] if str(row["LotID"]) == lot_id]
    lot_rows = [row for row in sheets["LotMaster"] if str(row["LotID"]) == lot_id]
    if not lot_shipments or not lot_rows:
        raise ValueError(f"Lot {lot_id} is absent from the canonical workbook.")

    field_rows = [
        row for row in lot_shipments if str(row["FieldStatus"]).casefold() == "in field"
    ]
    units_in_field = sum(int(row["QtyShipped"]) for row in field_rows)
    shipped_units = sum(int(row["QtyShipped"]) for row in lot_shipments)
    blockable_stock = sum(int(row["QtyOnHand"]) for row in lot_inventory)
    total_lot_units = shipped_units + blockable_stock
    perimeter = round((shipped_units / total_lot_units) * 100, 1) if total_lot_units else 0.0
    impacted_customers = [
        {
            "name": str(row["CustomerName"]),
            "tier": str(row["CustomerTier"]),
            "application": str(row["ApplicationEndUse"]),
            "units_in_field": int(row["QtyShipped"]),
        }
        for row in field_rows
    ]
    return {
        "lot_id": lot_id,
        "product_ref": str(lot_shipments[0]["ProductRef"]),
        "units_in_field": units_in_field,
        "shipped_units": shipped_units,
        "blockable_stock": blockable_stock,
        "impacted_customers": impacted_customers,
        "containment_perimeter_pct": perimeter,
        "calculation": "shipped_units / (shipped_units + blockable_stock)",
        "source_mode": source_mode,
        "mode": source_mode,
        "source_label": source_label,
        "citation": {
            "title": "SiC_AUTO_Shipments.xlsx",
            "url": citation_url,
            "source_type": "synthetic shipment workbook",
            "badge": citation_badge,
            "excerpt": (
                f"{units_in_field} units in field; {blockable_stock} units blockable; "
                f"{perimeter}% of the modeled lot shipped."
            ),
        },
    }


def _read_xlsx(
    source: Path | BinaryIO, required_sheets: set[str]
) -> dict[str, list[dict[str, Any]]]:
    """Read simple tabular OOXML sheets without requiring a native dataframe runtime."""
    main_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    with zipfile.ZipFile(source) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall(f"{{{main_ns}}}si"):
                shared.append("".join(node.text or "" for node in item.iter(f"{{{main_ns}}}t")))

        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        relationships = ElementTree.fromstring(
            archive.read("xl/_rels/workbook.xml.rels")
        )
        targets = {
            rel.attrib["Id"]: rel.attrib["Target"].lstrip("/")
            for rel in relationships.findall(f"{{{package_ns}}}Relationship")
        }
        result: dict[str, list[dict[str, Any]]] = {}
        for sheet in workbook.findall(f".//{{{main_ns}}}sheet"):
            name = sheet.attrib["name"]
            if name not in required_sheets:
                continue
            target = targets[sheet.attrib[f"{{{rel_ns}}}id"]]
            archive_path = target if target.startswith("xl/") else f"xl/{target}"
            xml = ElementTree.fromstring(archive.read(archive_path))
            values: list[dict[int, Any]] = []
            for row in xml.findall(f".//{{{main_ns}}}row"):
                cells: dict[int, Any] = {}
                for cell in row.findall(f"{{{main_ns}}}c"):
                    column = _column_index(cell.attrib["r"])
                    cell_type = cell.attrib.get("t")
                    value_node = cell.find(f"{{{main_ns}}}v")
                    if cell_type == "inlineStr":
                        value = "".join(
                            node.text or "" for node in cell.iter(f"{{{main_ns}}}t")
                        )
                    elif value_node is None:
                        value = ""
                    elif cell_type == "s":
                        value = shared[int(value_node.text or "0")]
                    else:
                        raw = value_node.text or ""
                        try:
                            number = float(raw)
                            value = int(number) if number.is_integer() else number
                        except ValueError:
                            value = raw
                    cells[column] = value
                values.append(cells)
            if not values:
                result[name] = []
                continue
            headers = values[0]
            result[name] = [
                {
                    str(header): row.get(index, "")
                    for index, header in headers.items()
                }
                for row in values[1:]
            ]
    missing = required_sheets - result.keys()
    if missing:
        raise ValueError(f"Workbook is missing sheets: {', '.join(sorted(missing))}")
    return result


def _column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference)
    if not letters:
        raise ValueError(f"Invalid OOXML cell reference: {reference}")
    value = 0
    for character in letters.group():
        value = value * 26 + ord(character) - ord("A") + 1
    return value


def _markdown_table(text: str, heading: str) -> list[dict[str, str]]:
    match = re.search(
        rf"^### {re.escape(heading)}\s*$\s*(\|.+?\|)\s*\n(\|[-:| ]+\|)\s*\n((?:\|.*\|\s*\n?)+)",
        text,
        flags=re.MULTILINE,
    )
    if not match:
        raise ValueError(f"Markdown table '{heading}' was not found.")
    headers = [item.strip() for item in match.group(1).strip().strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in match.group(3).strip().splitlines():
        values = [item.strip() for item in line.strip().strip("|").split("|")]
        rows.append(dict(zip(headers, values, strict=True)))
    return rows


def load_fabric_tables(model_path: Path | None = None) -> dict[str, list[dict[str, str]]]:
    """Load the five synthetic ontology tables from the canonical Markdown model."""
    path = model_path or data_root() / "fabric_iq" / "FabricIQ_Data_Model.md"
    text = path.read_text(encoding="utf-8")
    return {
        "Lot": _markdown_table(text, "Lot"),
        "Wafer": _markdown_table(text, f"Wafer (lot {LOT_ID})"),
        "Tester": _markdown_table(text, "Tester"),
        "Recipe": _markdown_table(text, "Recipe"),
        "ETestResult": _markdown_table(text, "ETestResult"),
    }


def load_fabric_trace(lot_id: str = LOT_ID, model_path: Path | None = None) -> dict[str, Any]:
    """Trace the synthetic Fabric ontology snapshot from lot to failed parameter."""
    tables = load_fabric_tables(model_path)
    lots = tables["Lot"]
    wafers = tables["Wafer"]
    testers = tables["Tester"]
    recipes = tables["Recipe"]
    results = tables["ETestResult"]

    lot = next((row for row in lots if row["LotID"] == lot_id), None)
    if lot is None:
        raise ValueError(f"Lot {lot_id} is absent from the Fabric snapshot.")
    wafer_by_id = {row["WaferID"]: row for row in wafers}
    failures = [
        row
        for row in results
        if row["Status"] == "FAIL" and wafer_by_id.get(row["WaferID"], {}).get("LotID") == lot_id
    ]
    if not failures:
        raise ValueError(f"No failed e-test result was found for {lot_id}.")
    failed_wafers = [wafer_by_id[row["WaferID"]] for row in failures]
    tester_id = max(
        {row["TesterID"] for row in failed_wafers},
        key=lambda value: sum(row["TesterID"] == value for row in failed_wafers),
    )
    recipe_id = max(
        {row["RecipeID"] for row in failed_wafers},
        key=lambda value: sum(row["RecipeID"] == value for row in failed_wafers),
    )
    tester = next(row for row in testers if row["TesterID"] == tester_id)
    recipe = next(row for row in recipes if row["RecipeID"] == recipe_id)
    values = [float(row["Value"]) for row in failures if row["Parameter"] == "Vth"]
    usl = float(next(row["USL"] for row in failures if row["Parameter"] == "Vth"))
    anneal_temp = int(recipe["AnnealTemp_C"])
    return {
        "lot": lot,
        "failed_wafers": [row["WaferID"] for row in failed_wafers],
        "deviating_parameter": "Vth",
        "measured_values_v": values,
        "usl_v": usl,
        "suspect_tester": tester_id,
        "tester_last_pm": tester["LastPM_date"],
        "suspect_recipe": recipe_id,
        "anneal_temp_c": anneal_temp,
        "process_upper_limit_c": 1190,
        "root_cause_probable": (
            f"{recipe_id} gate-oxide anneal at {anneal_temp} degC exceeded the 1190 degC "
            f"process limit on {tester_id}, producing a positive Vth shift."
        ),
        "ontology_path": ["Lot", "Wafer", "Tester", "Recipe", "ETestResult"],
        "source_mode": "synthetic-local",
        "source_label": "Fabric IQ fallback (local ontology snapshot)",
        "citation": {
            "title": "FabricIQ_Data_Model.md",
            "url": "repo://data/v1/fabric_iq/FabricIQ_Data_Model.md",
            "source_type": "synthetic Fabric ontology snapshot",
            "badge": "Fabric IQ fallback",
            "excerpt": (
                f"{lot_id} -> {tester_id} -> {recipe_id} -> Vth "
                f"{'/'.join(str(value) for value in values)} V vs {usl} V USL."
            ),
        },
    }


def load_handbook_steps(handbook_path: Path | None = None) -> list[str]:
    path = handbook_path or data_root() / "work_iq" / "WorkIQ_SharePoint_Ops_Handbook.md"
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r"^### D3 .+?\n((?:\d+\..+\n)+)",
        text,
        flags=re.MULTILINE,
    )
    if not match:
        raise ValueError("The D3 containment section was not found in the handbook.")
    return [re.sub(r"^\d+\.\s*", "", line) for line in match.group(1).strip().splitlines()]


def offline_radar_output() -> dict[str, Any]:
    return {
        "agent": "Radar",
        "normative_risk": (
            "Cached public fallback: AEC-Q101 automotive use and EV traction exposure require "
            "a conservative containment and customer-notification posture. "
            "No live web call occurred."
        ),
        "tool_trace": [
            {
                "sub_question": "external normative and market risk",
                "selected_tool": "web_knowledge_source",
                "mode": "cached-public-fallback",
            },
        ],
        "citations": [],
    }


def offline_fab_output() -> dict[str, Any]:
    trace = load_fabric_trace()
    exposure = calculate_field_exposure()
    steps = load_handbook_steps()
    return {
        "agent": "Fab Intelligence",
        "root_cause_probable": trace["root_cause_probable"],
        "suspect_tester": trace["suspect_tester"],
        "suspect_recipe": trace["suspect_recipe"],
        "matching_past_excursion": (
            "EX-2024-017: Vth shift on T-07 after preventive-maintenance anneal "
            "mis-calibration (+18 degC)."
        ),
        "field_exposure": exposure["units_in_field"],
        "blockable_stock": exposure["blockable_stock"],
        "impacted_customers": exposure["impacted_customers"],
        "containment_perimeter_pct": exposure["containment_perimeter_pct"],
        "containment_steps": steps,
        "ontology_path": trace["ontology_path"],
        "tool_trace": [
            {
                "sub_question": "lot genealogy and probable root cause",
                "selected_tool": "fabric_iq_trace",
                "mode": "fallback",
            },
            {
                "sub_question": "shipment and inventory exposure",
                "selected_tool": "fab_field_exposure",
                "mode": "fallback",
            },
            {
                "sub_question": "procedures and excursion history",
                "selected_tool": "work_iq_handbook_fallback",
                "mode": "fallback",
            },
        ],
        "source_modes": {
            "work_iq_onedrive": exposure["source_label"],
            "fabric_iq": trace["source_mode"],
            "foundry_iq": "local-knowledge-snapshot",
        },
        "citations": [
            exposure["citation"],
            trace["citation"],
            {
                "title": "Excursion History - SiC Automotive (2024-2026)",
                "url": "repo://data/v1/foundry_iq/03_Excursion_History_2024-2026.md",
                "source_type": "synthetic Foundry IQ document snapshot",
                "badge": "Foundry IQ fallback",
                "excerpt": "EX-2024-017 links T-07 post-PM mis-calibration to a Vth shift.",
            },
            {
                "title": "Quality Incident Response Playbook - Automotive SiC",
                "url": "repo://data/v1/work_iq/WorkIQ_SharePoint_Ops_Handbook.md",
                "source_type": "synthetic SharePoint handbook snapshot",
                "badge": "Work IQ fallback",
                "excerpt": (
                    "D3 requires lot hold, inventory block, exposure quantification, "
                    "and escalation."
                ),
            },
        ],
    }


def format_teams_incident_update(fab: dict[str, Any], exposure: dict[str, Any]) -> str:
    """Build the deterministic HTML alert sent after explicit Teams approval."""
    lot_id = html.escape(str(exposure.get("lot_id") or LOT_ID))
    tester = html.escape(str(fab.get("suspect_tester") or "T-07"))
    recipe = html.escape(str(fab.get("suspect_recipe") or "R-GOX-12"))
    return "".join(
        [
            "<h2>🚨 Critical quality alert</h2>",
            "<p><strong>SiC Incident SIC-QI-2451</strong> · SEV-1</p>",
            "<h3>⚠️ Impact</h3>",
            "<ul>",
            f"<li><strong>{exposure['units_in_field']:,}</strong> units already in the field</li>",
            f"<li><strong>{exposure['blockable_stock']:,}</strong> units can still be blocked</li>",
            (
                "<li><strong>"
                f"{exposure['containment_perimeter_pct']}%"
                "</strong> current containment perimeter</li>"
            ),
            "</ul>",
            "<h3>🔍 Probable root cause</h3>",
            (
                f"<p><strong>{recipe}</strong> gate-oxide anneal on Tool "
                f"<strong>{tester}</strong> exceeded the process limit.</p>"
            ),
            "<ul>",
            "<li>Actual temperature: <strong>1194&deg;C</strong></li>",
            "<li>Specification limit: <strong>1190&deg;C</strong></li>",
            "<li>Suspected effect: <strong>positive Vth shift</strong></li>",
            "</ul>",
            "<h3>🛑 Immediate containment actions</h3>",
            "<ol>",
            (
                f"<li><strong>Lot hold</strong><br>Keep {lot_id} and all adjacent "
                f"{tester}/week-22 lots on hold until electrical confirmation is complete "
                "and the root cause is verified.</li>"
            ),
            (
                f"<li><strong>Inventory block</strong><br>Block all "
                f"{exposure['blockable_stock']:,} on-hand and in-transit units.</li>"
            ),
            (
                f"<li><strong>Tool containment</strong><br>Stop and recalibrate {tester}; "
                f"verify {recipe}; retest all held lots.</li>"
            ),
            (
                "<li><strong>Customer protection</strong><br>Notify affected EV-traction "
                "Tier-1 quality leads and launch traceability checks.</li>"
            ),
            "</ol>",
            (
                "<p><em>Evidence: cited assessment available in the ST IQ Operations "
                "Assistant.<br>Data classification: synthetic customer-demo data.</em></p>"
            ),
        ]
    )


def compile_offline_brief(
    radar: dict[str, Any], fab: dict[str, Any], objective: str
) -> dict[str, Any]:
    citations = [*radar["citations"], *fab["citations"]]
    customers = fab["impacted_customers"]
    steps = [
        "Radar selected the public web branch for normative risk.",
        "Fab Intelligence calculated internal workbook exposure.",
        "Fab Intelligence traced Lot -> Wafer -> Tester -> Recipe -> ETestResult.",
        "Fab Intelligence matched the Foundry IQ excursion history.",
        "Fab Intelligence retrieved the local Work IQ handbook snapshot.",
        "Chief/Compiler reconciled both specialist outputs into the incident brief.",
    ]
    exposure = calculate_field_exposure()
    update = format_teams_incident_update(fab, exposure)
    return {
        "mode": "demo",
        "objective": objective,
        "incident": {
            "id": "SIC-QI-2451",
            "severity": "SEV-1",
            "title": "Automotive SiC MOSFET Vth parametric excursion",
            "affected_lot": LOT_ID,
            "product_ref": PRODUCT_REF,
        },
        "agent_outputs": {"radar": radar, "fab_intelligence": fab},
        "brief": {
            "containment": fab["containment_steps"],
            "probable_root_cause": fab["root_cause_probable"],
            "field_impact": {
                "units_in_field": fab["field_exposure"],
                "blockable_stock": fab["blockable_stock"],
                "impacted_customers": customers,
                "containment_perimeter_pct": fab["containment_perimeter_pct"],
            },
            "recommended_actions": [
                "Quarantine SiC-AUTO-2451 and adjacent T-07/week-22 lots.",
                "Block all on-hand and in-transit stock.",
                "Escalate immediately to EV-traction Tier-1 customer quality leads.",
                "Recalibrate T-07, verify R-GOX-12, and retest held lots.",
            ],
        },
        "evidence_trace": {"completed": len(steps), "total": len(steps), "steps": steps},
        "citations": citations,
        "teams_update": {"text": update, "delivery": "dry-run"},
        "data_notice": (
            "Operational, customer, shipment, ontology, procedure, and incident records are "
            "deterministic synthetic demo data."
        ),
    }

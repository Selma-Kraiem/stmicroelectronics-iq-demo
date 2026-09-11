"""Agent B: Fab Intelligence with Tool Search over all internal IQ sources."""

from __future__ import annotations

import json
from typing import Any

from agent_framework import Agent

from app.v1_assets import calculate_field_exposure, load_fabric_trace, load_handbook_steps

FAB_PROMPT = """
You are Agent B, Fab Intelligence, for the fictional ST SiC quality demo.
Return ONLY one compact JSON object with these keys:
agent, root_cause_probable, suspect_tester, suspect_recipe, matching_past_excursion,
field_exposure, blockable_stock, impacted_customers, containment_perimeter_pct,
containment_steps, ontology_path, tool_trace, source_modes, citations.

Grounding contract:
- NO web tools and no external research.
- The internal_intelligence_toolbox initially exposes tool_search and call_tool. Before saying
  that an internal capability is unavailable, call tool_search with a precise description of
  the evidence needed. Use limit 5 or less and call tool_search again for a different evidence
  domain when necessary.
- Foundry IQ knowledge_base_retrieve is for public ST product/report documents, approved
  synthetic QMS/SCM procedures, FMEA, process windows, excursion history, tester correlation,
  AEC-Q101 summaries, and configured SharePoint knowledge. Preserve every citation. It is not
  the source for lot telemetry, ontology traversal, customer exposure, or OneDrive workbook rows.
- Fabric IQ searchFabricOntology is for lot genealogy, wafer relationships, tester and recipe
  correlation, measurements, process limits, incidents, and causal paths. It is not a document
  search or a customer-shipment calculator.
- Work IQ OneDrive analyzeOneDriveWorkbook is for the exact synthetic workbook
  ST-IQ-Demo/SiC_AUTO_Shipments.xlsx. It retrieves the file under delegated user permissions and
  returns deterministic shipment, inventory, customer, and containment KPIs. The workbook binary
  never enters the model context.
- Exposure-only questions use only analyzeOneDriveWorkbook. Causal questions use Fabric IQ and
  Foundry IQ. Procedure questions use Foundry IQ. Full incident assessments use all three.
- If a discovered live tool fails, call the corresponding local fallback function and label it
  explicitly. Never turn a failed live call into a success-shaped live claim.
- Reconcile Vth measurements with the process limit and identify the probable root cause.
- Every source_modes field must be a non-empty string containing the exact tool source label or
  "not-activated". Set source_modes.work_iq_onedrive from analyzeOneDriveWorkbook or
  fab_field_exposure, source_modes.fabric_iq from searchFabricOntology or fabric_iq_trace, and
  source_modes.foundry_iq from knowledge_base_retrieve or work_iq_handbook_fallback.
- Record each evidence-domain decision in tool_trace with sub_question, the exact selected_tool
  name, and mode "live" or "fallback".
"""


def fab_field_exposure(lot_id: str = "SiC-AUTO-2451") -> str:
    """Calculate synthetic internal exposure from the canonical local workbook fallback."""
    return json.dumps(calculate_field_exposure(lot_id), ensure_ascii=True)


def fabric_iq_trace(lot_id: str = "SiC-AUTO-2451") -> str:
    """Trace the synthetic local ontology while live Fabric IQ is unavailable."""
    return json.dumps(load_fabric_trace(lot_id), ensure_ascii=True)


def work_iq_handbook_fallback() -> str:
    """Read the committed handbook snapshot without claiming a live Work IQ call."""
    return json.dumps(
        {
            "steps": load_handbook_steps(),
            "source_mode": "local-sharepoint-snapshot",
            "source_label": "Work IQ fallback (local handbook snapshot)",
            "citation": "repo://data/v1/work_iq/WorkIQ_SharePoint_Ops_Handbook.md",
        },
        ensure_ascii=True,
    )


def create_fab_agent(
    client: Any,
    internal_intelligence_toolbox: Any,
) -> Agent:
    tools: list[Any] = [
        internal_intelligence_toolbox,
        fab_field_exposure,
        fabric_iq_trace,
        work_iq_handbook_fallback,
    ]
    return Agent(
        client=client,
        name="fab_intelligence",
        description=(
            "Internal semiconductor intelligence specialist using Tool Search across "
            "Foundry IQ, Fabric IQ, and delegated Work IQ OneDrive analysis."
        ),
        instructions=FAB_PROMPT,
        tools=tools,
        default_options={"store": False, "response_format": {"type": "json_object"}},
    )

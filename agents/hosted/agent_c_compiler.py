"""Strict contracts and synthesis instructions for the Chief/Compiler agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CHIEF_COMPILATION_INSTRUCTIONS = """
When dispatch_request returns a full_assessment evidence bundle, act as Chief/Compiler.
Reconcile the validated Radar and Fab Intelligence JSON and place this object in the final
envelope's result field:
{
 "mode": "live-configured",
  "objective": "...",
  "incident": {
    "id": "SIC-QI-2451",
    "severity": "SEV-1",
    "title": "Automotive SiC MOSFET Vth parametric excursion",
    "affected_lot": "SiC-AUTO-2451",
    "product_ref": "SCTW90N65G2V"
  },
  "agent_outputs": {"radar": {...}, "fab_intelligence": {...}},
  "brief": {
    "containment": ["..."],
    "probable_root_cause": "...",
    "field_impact": {
      "units_in_field": 0,
      "blockable_stock": 0,
      "impacted_customers": [],
      "containment_perimeter_pct": 0.0
    },
    "recommended_actions": ["..."]
  },
  "evidence_trace": {"completed": 0, "total": 0, "steps": ["..."]},
  "citations": [
    {"title": "...", "url": "...", "source_type": "...", "badge": "...", "excerpt": "..."}
  ],
  "teams_update": {"text": "Teams-ready formatted incident alert", "delivery": "dry-run"},
  "data_notice": "All operational and customer records are synthetic demo data."
}

Preserve the two raw worker JSON objects under agent_outputs. Count the completed evidence
steps accurately. Never send a Teams message; produce a Teams-ready dry-run only. Do not claim
Fabric IQ, Work IQ OneDrive, Foundry IQ, or public web access was live when a worker labelled
that source as a fallback. Radar owns only public-web evidence. Take shipment,
inventory, customer, and field-impact values only from Fab Intelligence.

Format teams_update.text as a concise mobile-friendly Teams alert with blank lines between
sections. Use this exact section order and visual language:
1. "🚨 CRITICAL QUALITY ALERT | SiC Incident SIC-QI-2451"
2. a separator line, then "⚠️ IMPACT" with bullets for units in field, blockable units, and
   containment perimeter;
3. "🔍 PROBABLE ROOT CAUSE" with recipe, tool, 1194°C actual temperature, 1190°C limit, and
   positive Vth shift;
4. "🛑 IMMEDIATE CONTAINMENT ACTIONS (MANDATORY)" with numbered LOT HOLD, INVENTORY BLOCK,
   TOOL CONTAINMENT, and CUSTOMER PROTECTION blocks;
5. a final "📌 STATUS" block with SEV-1, cited-assessment availability, and synthetic-demo
   data classification.
Do not put "[DRY RUN]" in the message body because the same body is sent after explicit approval;
the delivery field and UI own the dry-run state.
"""


class CitationContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    url: str
    source_type: str
    badge: str
    excerpt: str


class CustomerImpactContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    tier: str
    application: str
    units_in_field: int


class ToolTraceContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sub_question: str
    selected_tool: str
    mode: str


class RadarContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent: Literal["Radar"]
    normative_risk: str
    tool_trace: list[ToolTraceContract]
    citations: list[CitationContract]


class SourceModesContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fabric_iq: str = Field(min_length=1)
    foundry_iq: str = Field(min_length=1)
    work_iq_onedrive: str = Field(min_length=1)


class FabContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent: Literal["Fab Intelligence"]
    root_cause_probable: str
    suspect_tester: str
    suspect_recipe: str
    matching_past_excursion: str
    field_exposure: int
    blockable_stock: int
    impacted_customers: list[CustomerImpactContract]
    containment_perimeter_pct: float
    containment_steps: list[str]
    ontology_path: list[str]
    tool_trace: list[ToolTraceContract]
    source_modes: SourceModesContract
    citations: list[CitationContract]


class WorkerOutputsContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    radar: RadarContract
    fab_intelligence: FabContract


class IncidentContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Literal["SIC-QI-2451"]
    severity: Literal["SEV-1"]
    title: str
    affected_lot: Literal["SiC-AUTO-2451"]
    product_ref: Literal["SCTW90N65G2V"]


class FieldImpactContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    units_in_field: int
    blockable_stock: int
    impacted_customers: list[CustomerImpactContract]
    containment_perimeter_pct: float


class BriefContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    containment: list[str]
    probable_root_cause: str
    field_impact: FieldImpactContract
    recommended_actions: list[str]


class EvidenceTraceContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    completed: int
    total: int
    steps: list[str]


class TeamsUpdateContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    delivery: Literal["dry-run"]


class CompilerOutputContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["live-configured", "demo"]
    objective: str
    incident: IncidentContract
    agent_outputs: WorkerOutputsContract
    brief: BriefContract
    evidence_trace: EvidenceTraceContract
    citations: list[CitationContract]
    teams_update: TeamsUpdateContract
    data_notice: str

"""Commander agent with adaptive A2A routing and concurrent Tasks fan-out."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

from v2.agents.common import credential, foundry_client, required, token_auth

INSTRUCTIONS = """
You are the Incident Commander and the sole user-facing entry point for the V2 demo.
You coordinate two remote specialists over A2A: Market and Quality.

Routing:
- If the input contains MODE=TASK, call run_parallel_assessment exactly once. That tool
  performs concurrent A2A fan-out and returns both branches for fan-in.
- Otherwise this is MODE=CHAT. Call ask_market for public market/regulatory/weather/logistics
  questions, ask_quality for telemetry/lot/customer/order/inventory/procedure questions, or
  run_parallel_assessment when both evidence domains are required.

Synthesis:
- Preserve the supplied run_id, incident_id, and correlation_id.
- Accept partial results when one agent fails or times out; identify the failed branch.
- Set status="completed" and complete=true when both specialists return status="completed"
  with citations, even when they explicitly identify expected missing information. Use partial
  only when a branch fails, times out, or returns no citations.
- Treat only cited evidence as facts. Separate facts, hypotheses, and missing information.
- Never invent citations.
- Preserve each specialist's agent, status, task_id, summary, structured_data, citations, and
  procedure identifiers in specialists. Merge the useful facts, hypotheses, and missing
  information at the top level instead of duplicating those arrays inside specialists.
  Include QMS-017/SCM-042 procedure evidence in the final facts and merged citations when
  Quality returns it.
- For MODE=CHAT, keep the top-level synthesis concise: copy the specialist summary into answer,
  include at most four facts, two hypotheses, three missing-information items, and the four
  strongest citations. Do not add a second research pass.
- Block any Teams publication when evidence is incomplete.
- Work IQ Teams is disabled because M365_COPILOT_BUSINESS_CHAT is not available in the
  Foundry tenant. Never claim that a Teams message was sent.

Return JSON only with this shape:
{
  "run_id": "caller supplied ID",
  "incident_id": "caller supplied ID",
  "correlation_id": "caller supplied ID",
  "status": "completed, partial, or failed",
  "complete": true,
  "answer": "concise cited incident brief",
  "route": ["market", "quality"],
  "facts": [],
  "hypotheses": [],
  "missing_information": [],
  "customer_impact": {},
  "recommended_actions": [{"owner": "role", "action": "next step"}],
  "citations": [],
  "specialists": [],
  "teams_update": {
    "delivery": "disabled",
    "text": "[DRY RUN] exact proposed update",
    "send_allowed": false,
    "reason": "exact blocker"
  },
  "data_notice": "Operational records are deterministic synthetic demo data (seed 20260813)."
}
"""


def _response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return str(text)
    messages = getattr(response, "messages", None) or []
    if messages:
        return str(getattr(messages[-1], "text", messages[-1]))
    return str(response)


def build_commander_agent():
    import httpx
    from agent_framework import Agent, tool
    from agent_framework.a2a import A2AAgent
    from azure.identity import get_bearer_token_provider

    azure_credential = credential()
    token_provider = get_bearer_token_provider(
        azure_credential,
        "https://ai.azure.com/.default",
    )

    def remote_agent(name: str, endpoint_env: str, description: str) -> A2AAgent:
        return A2AAgent(
            name=name,
            description=description,
            url=required(endpoint_env),
            http_client=httpx.AsyncClient(
                auth=token_auth(token_provider),
                timeout=httpx.Timeout(90.0),
            ),
            timeout=httpx.Timeout(75.0),
            supported_protocol_bindings=["JSONRPC"],
        )

    market = remote_agent(
        "market",
        "MARKET_A2A_ENDPOINT",
        "Current public market, regulatory, weather, and logistics research.",
    )
    quality = remote_agent(
        "quality",
        "QUALITY_A2A_ENDPOINT",
        "Foundry IQ, manufacturing telemetry, and fictional customer exposure.",
    )

    async def invoke(remote: A2AAgent, objective: str, context: str) -> dict[str, Any]:
        try:
            response = await asyncio.wait_for(
                remote.run(f"{context}\nOBJECTIVE={objective}", stream=False),
                timeout=80.0,
            )
            text = _response_text(response)
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = {
                    "agent": remote.name,
                    "status": "completed",
                    "summary": text,
                    "facts": [],
                    "hypotheses": [],
                    "missing_information": [
                        f"{remote.name} returned text instead of the structured contract."
                    ],
                    "citations": [],
                    "structured_data": {},
                }
            return payload
        except TimeoutError:
            return {
                "agent": remote.name,
                "status": "timeout",
                "summary": "",
                "facts": [],
                "hypotheses": [],
                "missing_information": [f"{remote.name} A2A call timed out."],
                "citations": [],
                "structured_data": {},
                "error": "A2A timeout",
            }
        except Exception as exc:
            return {
                "agent": remote.name,
                "status": "failed",
                "summary": "",
                "facts": [],
                "hypotheses": [],
                "missing_information": [f"{remote.name} A2A call failed."],
                "citations": [],
                "structured_data": {},
                "error": f"{type(exc).__name__}: {exc}",
            }

    @tool(
        name="ask_market",
        description="Delegate a public-only question to the Market specialist over A2A.",
    )
    async def ask_market(
        objective: Annotated[str, "Public market or regulatory question."],
        incident_id: Annotated[str, "Common incident identifier."],
        correlation_id: Annotated[str, "Common trace correlation identifier."],
    ) -> str:
        context = (
            f"MODE=CHAT\nincident_id={incident_id}\ncorrelation_id={correlation_id}\n"
            "Sanitize all external retrieval queries."
        )
        return json.dumps(await invoke(market, objective, context))

    @tool(
        name="ask_quality",
        description=(
            "Delegate an operational or quality question to the Quality specialist over A2A."
        ),
    )
    async def ask_quality(
        objective: Annotated[str, "Quality, telemetry, exposure, or procedure question."],
        incident_id: Annotated[str, "Common incident identifier."],
        correlation_id: Annotated[str, "Common trace correlation identifier."],
    ) -> str:
        context = f"MODE=CHAT\nincident_id={incident_id}\ncorrelation_id={correlation_id}"
        return json.dumps(await invoke(quality, objective, context))

    @tool(
        name="run_parallel_assessment",
        description=(
            "Run Market and Quality A2A specialists concurrently, preserve partial failures, "
            "and return both branches for Commander fan-in."
        ),
    )
    async def run_parallel_assessment(
        objective: Annotated[str, "Full incident-assessment objective."],
        run_id: Annotated[str, "Common workflow run identifier."],
        incident_id: Annotated[str, "Common incident identifier."],
        correlation_id: Annotated[str, "Common trace correlation identifier."],
    ) -> str:
        context = (
            f"MODE=TASK\nrun_id={run_id}\nincident_id={incident_id}\n"
            f"correlation_id={correlation_id}"
        )
        market_result, quality_result = await asyncio.gather(
            invoke(market, objective, context),
            invoke(quality, objective, context),
        )
        return json.dumps(
            {
                "run_id": run_id,
                "incident_id": incident_id,
                "correlation_id": correlation_id,
                "fan_out": "concurrent",
                "specialists": [market_result, quality_result],
            }
        )

    return Agent(
        client=foundry_client(azure_credential),
        name="st_iq_commander_v2",
        description=(
            "Single entry point with adaptive Chat routing and parallel A2A Tasks fan-out/fan-in."
        ),
        instructions=INSTRUCTIONS,
        tools=[ask_market, ask_quality, run_parallel_assessment],
        default_options={
            "store": False,
            "reasoning": {"effort": "low"},
            "max_tokens": 3600,
        },
    )

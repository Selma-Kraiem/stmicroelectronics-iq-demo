"""Parallel Radar/Fab Intelligence workflow hosted on Microsoft Foundry."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Literal

from azure.ai.agentserver.optimization import load_config
from pydantic import BaseModel, ConfigDict

from agents.hosted.agent_a_signal_analyst import create_radar_agent
from agents.hosted.agent_b_fab_intelligence import (
    create_fab_agent,
)
from agents.hosted.agent_c_compiler import (
    CHIEF_COMPILATION_INSTRUCTIONS,
    CitationContract,
    CompilerOutputContract,
    FabContract,
    RadarContract,
)
from app.routing import (
    FAB_ONLY,
    FULL_ASSESSMENT,
    RADAR_ONLY,
    explicit_route_header,
    select_orchestration_route,
)
from app.v1_assets import extract_json_object, sanitized_external_query

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("st_iq_hosted_agent")

ORCHESTRATOR_PROMPT = f"""
You are the ST IQ Chief/Compiler. Call dispatch_request exactly once with the complete,
unmodified presenter request. Deterministic application code selects {RADAR_ONLY}, {FAB_ONLY},
or {FULL_ASSESSMENT}; you must not choose or override that route.

For radar_only or fab_only, return the exact envelope from dispatch_request without changing
sources or activated_agents. For full_assessment, dispatch_request returns both parallel worker
outputs. Compile those outputs yourself, then return an envelope with route "full_assessment",
activated_agents ["Radar", "Fab Intelligence", "Chief/Compiler"], sources copied from the
compiled result citations, answer set to its probable root cause, and result matching the
strict synthesis contract below.

{CHIEF_COMPILATION_INSTRUCTIONS}
"""


class OrchestratorOutputContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route: Literal["radar_only", "fab_only", "full_assessment"]
    answer: str
    activated_agents: list[str]
    sources: list[CitationContract]
    result: RadarContract | FabContract | CompilerOutputContract

def _credential():
    """Use managed identity in Foundry and default credentials for local development."""
    from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

    return (
        ManagedIdentityCredential() if os.getenv("FOUNDRY_AGENT_NAME") else DefaultAzureCredential()
    )


def build_workflow_agent():
    from agent_framework import Agent
    from agent_framework.foundry import FoundryChatClient
    from agent_framework_foundry_hosting import FoundryToolbox
    from dotenv import load_dotenv

    load_dotenv(override=False)
    required = (
        "FOUNDRY_PROJECT_ENDPOINT",
        "AZURE_AI_MODEL_DEPLOYMENT_NAME",
        "MARKET_TOOLBOX_ENDPOINT",
        "INTERNAL_TOOLBOX_ENDPOINT",
    )
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            f"Hosted workflow cannot start; missing required environment: {', '.join(missing)}"
        )

    commander_config = load_config()
    if commander_config is None:
        raise RuntimeError("Agent optimizer baseline configuration was not found.")
    default_model = os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"]
    market_source_label = os.getenv(
        "MARKET_SOURCE_LABEL", "Web Knowledge Source (Web IQ fallback)"
    )
    credential = _credential()
    market_toolbox = FoundryToolbox(
        credential,
        url=os.environ["MARKET_TOOLBOX_ENDPOINT"],
        name="radar_public_signals",
        load_prompts=False,
    )
    internal_toolbox = FoundryToolbox(
        credential,
        url=os.environ["INTERNAL_TOOLBOX_ENDPOINT"],
        name="internal_intelligence_toolbox",
        load_tools=True,
        load_prompts=False,
    )

    def client(model: str):
        return FoundryChatClient(
            project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
            model=model,
            credential=credential,
        )

    radar_agent = create_radar_agent(
        client(default_model),
        market_toolbox,
        source_label=market_source_label,
    )
    fab_agent = create_fab_agent(
        client(default_model),
        internal_toolbox,
    )
    async def ask_radar(task: str) -> dict[str, Any]:
        """Use only Radar for public signals or exposure evidence selected by Tool Search."""
        public_query = sanitized_external_query()
        response = await radar_agent.run(
            f"ROUTE={RADAR_ONLY}\n{public_query}\n"
            "Return the Radar result as one JSON object. Never infer private identifiers "
            "from the parent request."
        )
        return extract_json_object(response.text)

    async def ask_fab_intelligence(task: str) -> dict[str, Any]:
        """Use only Fab Intelligence for internal quality, ontology, and procedure evidence."""
        response = await fab_agent.run(
            f"ROUTE={FAB_ONLY}\n{task}\nReturn the Fab Intelligence result as one JSON object."
        )
        return extract_json_object(response.text)

    async def run_parallel_assessment(task: str) -> dict[str, Any]:
        """Run Radar and Fab Intelligence concurrently for Chief/Compiler synthesis."""
        public_query = sanitized_external_query()
        radar_response, fab_response = await asyncio.gather(
            radar_agent.run(
                f"{public_query}\nReturn the Radar result as one JSON object. "
                "Never infer private identifiers from the parent request."
            ),
            fab_agent.run(f"{task}\nReturn the Fab Intelligence result as one JSON object."),
        )
        return {
            "route": "full_assessment",
            "objective": "Synthesize the parallel evidence into the final cited incident brief.",
            "format_instruction": "Return the Chief/Compiler envelope as one valid JSON object.",
            "parallel_worker_outputs": {
                "radar": extract_json_object(radar_response.text),
                "fab_intelligence": extract_json_object(fab_response.text),
            },
        }

    async def dispatch_request(task: str) -> str:
        """Deterministically route one complete presenter request to the required agents."""
        explicit_route = explicit_route_header(task)
        route = explicit_route or select_orchestration_route(task)
        if route == RADAR_ONLY:
            result = await ask_radar(task)
            envelope = {
                "route": "radar_only",
                "answer": result["normative_risk"],
                "activated_agents": ["Radar"],
                "sources": result["citations"],
                "result": result,
            }
        elif route == FAB_ONLY:
            result = await ask_fab_intelligence(task)
            envelope = {
                "route": "fab_only",
                "answer": result["root_cause_probable"],
                "activated_agents": ["Fab Intelligence"],
                "sources": result["citations"],
                "result": result,
            }
        else:
            envelope = await run_parallel_assessment(task)
        return json.dumps(envelope, ensure_ascii=True)

    workflow_agent = Agent(
        client=client(commander_config.model or default_model),
        name="st_sic_incident_orchestrator",
        description=(
            "Chief/Compiler Hosted Agent that deterministically routes work to Radar and "
            "Fab Intelligence, runs independent specialists in parallel, and synthesizes "
            "the cited incident brief."
        ),
        instructions=(
            f"{ORCHESTRATOR_PROMPT}\n\n{commander_config.compose_instructions()}"
        ),
        tools=[dispatch_request],
        default_options={"store": False, "response_format": OrchestratorOutputContract},
    )
    logger.info(
        "Starting adaptive Radar/Fab workflow protocol=responses/2.0.0 "
        "optimization_source=%s internal_tool_search=enabled",
        commander_config.source,
    )
    return workflow_agent


async def main() -> None:
    from agent_framework_foundry_hosting import ResponsesHostServer

    await ResponsesHostServer(build_workflow_agent()).run_async()


if __name__ == "__main__":
    asyncio.run(main())

"""Commander routing, A2A fan-out/fan-in, and incident synthesis."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from v2.models import SourceCitation, SpecialistResult, WorkflowRun
from v2.operational import OperationalDomain

DEFAULT_OBJECTIVE = (
    "Assess the current automotive SiC power-module incident for synthetic lot "
    "CAT-26-0813-A, identify live external signals and operational exposure, then produce "
    "a cited response brief."
)
WORK_IQ_BLOCKER = (
    "Work IQ Teams is disabled for V2 because the delegated identity in the Foundry "
    "tenant does not have M365_COPILOT_BUSINESS_CHAT."
)


class Specialist(Protocol):
    name: str

    async def analyze(self, objective: str, run_id: str, task_id: str) -> SpecialistResult: ...


class RemoteCommander(Protocol):
    async def invoke(
        self,
        *,
        mode: str,
        objective: str,
        run_id: str,
        incident_id: str,
        correlation_id: str,
    ) -> dict[str, Any]: ...


class CommanderRouter:
    """Select only the specialists required for an interactive Chat request."""

    MARKET_TERMS = {
        "market",
        "regulatory",
        "regulation",
        "weather",
        "logistics",
        "supply",
        "external",
        "web",
    }
    QUALITY_TERMS = {
        "quality",
        "telemetry",
        "temperature",
        "lot",
        "customer",
        "order",
        "inventory",
        "procedure",
        "incident",
        "impact",
    }

    def route(self, message: str) -> list[str]:
        words = set(message.lower().replace("-", " ").split())
        agents: list[str] = []
        if words & self.MARKET_TERMS:
            agents.append("market")
        if words & self.QUALITY_TERMS:
            agents.append("quality")
        return agents or ["quality"]


class LocalMarketSpecialist:
    """Deterministic public-only fallback; never presented as a live web call."""

    name = "market"

    async def analyze(self, objective: str, run_id: str, task_id: str) -> SpecialistResult:
        await asyncio.sleep(0)
        return SpecialistResult(
            agent="market",
            task_id=task_id,
            status="completed",
            summary=(
                "Cached public demo context indicates sustained automotive SiC qualification "
                "and supply-chain scrutiny. No live Web IQ call occurred."
            ),
            facts=[
                "The external signal is a cached public-demo result, not live Web IQ.",
                "Automotive SiC programs require controlled qualification and traceability.",
            ],
            hypotheses=[
                "A current logistics disruption could reduce the margin for replacement supply."
            ],
            missing_information=[
                "Live regulatory, weather, market, and logistics signals require "
                "the Market A2A agent."
            ],
            citations=[
                SourceCitation(
                    id="ST-PUBLIC-SIC-V2",
                    title="STMicroelectronics silicon-carbide devices",
                    source_type="public ST documentation",
                    badge="Public ST",
                    excerpt="Public product context for silicon-carbide power technology.",
                    url="https://www.st.com/en/power-transistors/silicon-carbide-sic-devices.html",
                )
            ],
            structured_data={
                "mode": "cached-public-demo",
                "run_id": run_id,
                "objective_sanitized": True,
            },
        )


class LocalQualitySpecialist:
    """Local fallback matching the Quality agent's two structured tool calls."""

    name = "quality"

    def __init__(self, domain: OperationalDomain | None = None) -> None:
        self.domain = domain or OperationalDomain()

    async def analyze(self, objective: str, run_id: str, task_id: str) -> SpecialistResult:
        await asyncio.sleep(0)
        lot_id = "CAT-26-0813-A"
        telemetry = self.domain.telemetry_for_lot(lot_id)
        exposure = self.domain.exposure_for_lot(lot_id)
        observation = telemetry["observations"][0]
        return SpecialistResult(
            agent="quality",
            task_id=task_id,
            status="completed",
            summary=(
                f"Lot {lot_id} has {telemetry['anomaly_count']} synthetic telemetry anomaly "
                f"and {exposure['affected_units']} affected synthetic order units."
            ),
            facts=[
                (
                    f"Synthetic leakage measured {observation['value']} uA against a "
                    f"{observation['threshold']} uA threshold."
                ),
                (
                    f"{len(exposure['affected_orders'])} fictional orders cover "
                    f"{exposure['affected_units']} modules."
                ),
                (
                    f"Synthetic substitute inventory provides "
                    f"{exposure['available_reallocation']} modules."
                ),
            ],
            hypotheses=[
                "The anomaly may be isolated to final-test cell EQ-CAT-FT-07 pending trace review."
            ],
            missing_information=[
                "Root cause and retest disposition are not yet confirmed."
            ],
            citations=[
                SourceCitation(
                    id="TEL-7781",
                    title="Synthetic final-test telemetry",
                    source_type="Manufacturing Telemetry API",
                    badge="Synthetic telemetry",
                    excerpt="Deterministic demo observation for lot CAT-26-0813-A.",
                    synthetic=True,
                ),
                SourceCitation(
                    id="EXP-CAT-26-0813-A",
                    title="Synthetic customer exposure projection",
                    source_type="Customer Exposure API",
                    badge="Synthetic exposure",
                    excerpt="Fictional orders, customers, and inventory for the affected lot.",
                    synthetic=True,
                ),
                SourceCitation(
                    id="PROC-SIC-17",
                    title="SiC containment and traceability procedure",
                    source_type="synthetic internal procedure",
                    badge="Foundry IQ demo procedure",
                    excerpt=(
                        "Quarantine the suspect lot, preserve test traces, and notify affected "
                        "order owners."
                    ),
                    url="synthetic://procedures/PROC-SIC-17",
                    synthetic=True,
                ),
            ],
            structured_data={
                "mode": "synthetic-local",
                "run_id": run_id,
                "lot_id": lot_id,
                "telemetry": telemetry,
                "exposure": exposure,
                "tool_sequence": [
                    "Manufacturing Telemetry API",
                    "Customer Exposure API",
                ],
            },
        )


@dataclass(frozen=True)
class CommanderConfig:
    specialist_timeout_seconds: float = 8.0
    transient_retries: int = 1


class CommanderService:
    """Single entry point for adaptive Chat and long-running Tasks."""

    def __init__(
        self,
        *,
        market: Specialist | None = None,
        quality: Specialist | None = None,
        remote: RemoteCommander | None = None,
        config: CommanderConfig | None = None,
    ) -> None:
        self.specialists: dict[str, Specialist] = {
            "market": market or LocalMarketSpecialist(),
            "quality": quality or LocalQualitySpecialist(),
        }
        self.config = config or CommanderConfig()
        self.remote = remote
        self.router = CommanderRouter()
        self.runs: dict[str, WorkflowRun] = {}

    def statuses(self) -> list[dict[str, str]]:
        if self.remote is not None:
            commander_state = {
                "name": "Commander / Router V2",
                "state": "available",
                "mode": "live-hosted-a2a",
                "reason": "Hosted Commander coordinates Market and Quality over Foundry A2A.",
            }
            market_state = {
                "name": "Market A2A agent",
                "state": "available",
                "mode": "live-web-knowledge-source",
                "reason": "Live public retrieval uses Web Knowledge Source (Web IQ fallback).",
            }
            quality_state = {
                "name": "Quality A2A agent",
                "state": "available",
                "mode": "live-foundry-iq-and-tool-search",
                "reason": "Foundry IQ knowledge and operational Tool Search are enabled.",
            }
        else:
            commander_state = {
                "name": "Commander / Router V2",
                "state": "available",
                "mode": "local-orchestrator",
                "reason": "Adaptive Chat and parallel Tasks orchestration are enabled.",
            }
            market_state = {
                "name": "Market A2A agent",
                "state": "degraded",
                "mode": "cached-public-demo",
                "reason": "Local fallback is active until the V2 Foundry agent is configured.",
            }
            quality_state = {
                "name": "Quality A2A agent",
                "state": "degraded",
                "mode": "synthetic-local",
                "reason": (
                    "Local structured APIs are active until the V2 Foundry agent is configured."
                ),
            }
        return [
            commander_state,
            market_state,
            quality_state,
            {
                "name": "Work IQ Teams",
                "state": "blocked",
                "mode": "disabled",
                "reason": WORK_IQ_BLOCKER,
            },
        ]

    async def chat(self, message: str) -> dict:
        run_id = f"chat-{uuid4().hex}"
        incident_id = "INC-SIC-0813"
        if self.remote is not None:
            result = await self.remote.invoke(
                mode="chat",
                objective=message,
                run_id=run_id,
                incident_id=incident_id,
                correlation_id=run_id,
            )
            return self._guard_remote_result(result, mode="chat")
        selected = self.router.route(message)
        results = await self._fan_out(message, run_id, selected)
        successful = [result for result in results if result.status == "completed"]
        citations = [
            citation.as_dict() for result in successful for citation in result.citations
        ]
        return {
            "mode": "chat",
            "run_id": run_id,
            "incident_id": incident_id,
            "route": selected,
            "answer": "\n\n".join(result.summary for result in successful),
            "specialists": [result.as_dict() for result in results],
            "citations": citations,
            "complete": len(successful) == len(selected),
        }

    def start_task(self, objective: str | None = None) -> WorkflowRun:
        run = WorkflowRun(
            id=f"run-{uuid4().hex}",
            incident_id="INC-SIC-0813",
            objective=objective or DEFAULT_OBJECTIVE,
        )
        run.add_event(2, "Commander accepted the incident assessment")
        self.runs[run.id] = run
        asyncio.create_task(self._execute_task(run))
        return run

    def history(self) -> list[dict]:
        return [
            run.summary()
            for run in sorted(
                self.runs.values(),
                key=lambda item: item.created_at,
                reverse=True,
            )
        ]

    async def _invoke(
        self,
        specialist: Specialist,
        objective: str,
        run_id: str,
        task_id: str,
    ) -> SpecialistResult:
        last_error: Exception | None = None
        for attempt in range(self.config.transient_retries + 1):
            try:
                return await asyncio.wait_for(
                    specialist.analyze(objective, run_id, task_id),
                    timeout=self.config.specialist_timeout_seconds,
                )
            except TimeoutError as exc:
                last_error = exc
                if attempt == self.config.transient_retries:
                    return SpecialistResult(
                        agent=specialist.name,  # type: ignore[arg-type]
                        task_id=task_id,
                        status="timeout",
                        summary="",
                        facts=[],
                        hypotheses=[],
                        missing_information=[f"{specialist.name} timed out."],
                        citations=[],
                        error="specialist timeout",
                    )
            except (ConnectionError, OSError) as exc:
                last_error = exc
                if attempt == self.config.transient_retries:
                    break
                await asyncio.sleep(0.05 * (attempt + 1))
            except Exception as exc:
                last_error = exc
                break
        return SpecialistResult(
            agent=specialist.name,  # type: ignore[arg-type]
            task_id=task_id,
            status="failed",
            summary="",
            facts=[],
            hypotheses=[],
            missing_information=[f"{specialist.name} did not return evidence."],
            citations=[],
            error=f"{type(last_error).__name__}: {last_error}",
        )

    async def _fan_out(
        self,
        objective: str,
        run_id: str,
        agents: list[str],
    ) -> list[SpecialistResult]:
        calls = []
        for agent_name in agents:
            task_id = f"a2a-{agent_name}-{uuid4().hex}"
            calls.append(
                self._invoke(
                    self.specialists[agent_name],
                    objective,
                    run_id,
                    task_id,
                )
            )
        return list(await asyncio.gather(*calls))

    async def _execute_task(self, run: WorkflowRun) -> None:
        try:
            if self.remote is not None:
                await self._execute_remote_task(run)
                return
            run.add_event(12, "Commander initiated A2A fan-out")
            run.add_event(22, "Market analysis running", agent="market")
            run.add_event(22, "Quality analysis running", agent="quality")
            results = await self._fan_out(
                run.objective,
                run.id,
                ["market", "quality"],
            )
            for result in results:
                run.add_event(
                    66,
                    f"{result.agent.capitalize()} returned {result.status}",
                    agent=result.agent,
                    state=result.status,
                    task_id=result.task_id,
                )
            successful = [
                result
                for result in results
                if result.status == "completed" and result.citations
            ]
            run.add_event(82, "Commander performing cited fan-in synthesis")
            if not successful:
                run.status = "failed"
                run.result = self._synthesize(run, results, complete=False)
                run.add_event(
                    100,
                    "Assessment failed: no cited specialist evidence",
                    state="failed",
                )
                return
            complete = len(successful) == 2
            run.status = "completed" if complete else "partial"
            run.result = self._synthesize(run, results, complete=complete)
            run.add_event(
                100,
                "Assessment complete" if complete else "Partial assessment complete",
                state=run.status,
            )
        except Exception as exc:
            run.status = "failed"
            run.result = {
                "run_id": run.id,
                "incident_id": run.incident_id,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
            run.add_event(100, "Commander failed during synthesis", state="failed")

    async def _execute_remote_task(self, run: WorkflowRun) -> None:
        run.add_event(12, "Hosted Commander initiated A2A fan-out")
        run.add_event(22, "Market and Quality A2A analysis running", agent="commander")
        result = await self.remote.invoke(
            mode="task",
            objective=run.objective,
            run_id=run.id,
            incident_id=run.incident_id,
            correlation_id=run.id,
        )
        result = self._guard_remote_result(result, mode="task")
        for specialist in result.get("specialists", []):
            agent = specialist.get("agent", "commander")
            run.add_event(
                66,
                f"{str(agent).capitalize()} returned {specialist.get('status', 'unknown')}",
                agent=str(agent),
                state=str(specialist.get("status", "failed")),
                task_id=specialist.get("task_id"),
            )
        run.add_event(82, "Hosted Commander performing cited fan-in synthesis")
        run.result = result
        run.status = result["status"]
        run.add_event(
            100,
            "Assessment complete" if run.status == "completed" else "Partial assessment complete",
            state=run.status,
        )

    @staticmethod
    def _guard_remote_result(result: dict[str, Any], *, mode: str) -> dict[str, Any]:
        specialists = result.get("specialists")
        if not isinstance(specialists, list):
            specialists = []
        successful_specialists = [
            specialist
            for specialist in specialists
            if specialist.get("status") == "completed"
            and isinstance(specialist.get("citations"), list)
            and specialist["citations"]
        ]
        citations = result.get("citations")
        if not isinstance(citations, list) or not citations:
            citations = [
                citation
                for specialist in successful_specialists
                for citation in specialist["citations"]
            ]
        complete = (
            bool(specialists)
            and len(successful_specialists) == len(specialists)
            and bool(citations)
        )
        if not citations:
            result["status"] = "failed"
            result["complete"] = False
            missing = list(result.get("missing_information") or [])
            missing.append("No cited evidence was returned by the Hosted Commander.")
            result["missing_information"] = missing
        elif not complete:
            result["status"] = "partial"
            result["complete"] = False
        else:
            result["status"] = "completed"
            result["complete"] = True
        result["specialists"] = specialists
        result["citations"] = citations
        result["mode"] = mode
        result["teams_update"] = {
            "delivery": "disabled",
            "text": (result.get("teams_update") or {}).get(
                "text",
                "[DRY RUN] Incident update unavailable.",
            ),
            "send_allowed": False,
            "reason": (
                WORK_IQ_BLOCKER
                if result["complete"]
                else "Teams publication is blocked because the assessment is incomplete."
            ),
        }
        if mode == "chat":
            route = result.get("route")
            if not isinstance(route, list) or not route:
                result["route"] = [
                    item.get("agent") for item in specialists if item.get("agent")
                ]
            answer = result.get("answer")
            if not isinstance(answer, str) or not answer.strip():
                result["answer"] = "\n\n".join(
                    str(item.get("summary", "")).strip()
                    for item in successful_specialists
                    if str(item.get("summary", "")).strip()
                )
        else:
            result.setdefault("customer_impact", {})
            result.setdefault("recommended_actions", [])
            result.setdefault(
                "data_notice",
                "Operational records are deterministic synthetic demo data (seed 20260813).",
            )
        return result

    def _synthesize(
        self,
        run: WorkflowRun,
        results: list[SpecialistResult],
        *,
        complete: bool,
    ) -> dict:
        successful = [result for result in results if result.status == "completed"]
        facts = [fact for result in successful for fact in result.facts]
        hypotheses = [item for result in successful for item in result.hypotheses]
        missing = [item for result in results for item in result.missing_information]
        failed_agents = [result.agent for result in results if result.status != "completed"]
        if failed_agents:
            missing.append(f"No cited evidence was returned by: {', '.join(failed_agents)}.")
        citations = [
            citation.as_dict() for result in successful for citation in result.citations
        ]
        quality = next((item for item in successful if item.agent == "quality"), None)
        exposure = (
            quality.structured_data.get("exposure", {})
            if quality
            else {}
        )
        preview = (
            "[DRY RUN] INC-SIC-0813: quarantine synthetic lot CAT-26-0813-A, "
            f"hold {len(exposure.get('affected_orders', []))} fictional orders, and preserve "
            "final-test traces pending root-cause confirmation."
        )
        return {
            "run_id": run.id,
            "incident_id": run.incident_id,
            "status": "completed" if complete else "partial",
            "complete": complete,
            "facts": facts,
            "hypotheses": hypotheses,
            "missing_information": missing,
            "customer_impact": exposure,
            "recommended_actions": [
                {
                    "owner": "Quality lead",
                    "action": "Keep the synthetic lot quarantined and preserve final-test traces.",
                },
                {
                    "owner": "Supply planner",
                    "action": "Hold affected fictional orders and validate substitute inventory.",
                },
                {
                    "owner": "Incident commander",
                    "action": "Publish only after all evidence branches are complete and cited.",
                },
            ],
            "citations": citations,
            "specialists": [result.as_dict() for result in results],
            "teams_update": {
                "delivery": "disabled",
                "text": preview,
                "send_allowed": False,
                "reason": (
                    WORK_IQ_BLOCKER
                    if complete
                    else "Teams publication is blocked because the assessment is incomplete."
                ),
            },
            "data_notice": (
                "Operational records are deterministic synthetic demo data (seed 20260813)."
            ),
        }

    async def publish_teams(self, run_id: str, explicit_opt_in: bool) -> dict:
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.result is None:
            raise RuntimeError("Assessment is not complete.")
        reason = run.result["teams_update"]["reason"]
        return {
            "sent": False,
            "mode": "disabled",
            "explicit_opt_in": explicit_opt_in,
            "reason": reason,
        }

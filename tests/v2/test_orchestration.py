from __future__ import annotations

import asyncio

import pytest

from v2.models import SourceCitation, SpecialistResult
from v2.orchestration import CommanderConfig, CommanderRouter, CommanderService


class StubSpecialist:
    def __init__(
        self,
        name: str,
        *,
        delay: float = 0,
        fail: bool = False,
        cited: bool = True,
    ) -> None:
        self.name = name
        self.delay = delay
        self.fail = fail
        self.cited = cited
        self.started_at: float | None = None

    async def analyze(self, objective: str, run_id: str, task_id: str) -> SpecialistResult:
        self.started_at = asyncio.get_running_loop().time()
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError(f"{self.name} failed")
        citations = (
            [
                SourceCitation(
                    id=f"{self.name}-source",
                    title=f"{self.name} evidence",
                    source_type="test",
                    badge="Test",
                    excerpt="cited evidence",
                )
            ]
            if self.cited
            else []
        )
        return SpecialistResult(
            agent=self.name,  # type: ignore[arg-type]
            task_id=task_id,
            status="completed",
            summary=f"{self.name} summary",
            facts=[f"{self.name} fact"],
            hypotheses=[f"{self.name} hypothesis"],
            missing_information=[],
            citations=citations,
            structured_data={},
        )


async def wait_for_run(service: CommanderService, run_id: str) -> dict:
    for _ in range(100):
        run = service.runs[run_id]
        if run.status != "running":
            return run.result or {}
        await asyncio.sleep(0.01)
    raise AssertionError("run did not complete")


def test_chat_router_selects_only_required_specialist() -> None:
    router = CommanderRouter()
    assert router.route("Check current market regulation and weather") == ["market"]
    assert router.route("Analyze lot telemetry and customer impact") == ["quality"]
    assert router.route("Assess external supply and internal incident impact") == [
        "market",
        "quality",
    ]


@pytest.mark.asyncio
async def test_tasks_fan_out_concurrently_and_fan_in_with_common_ids() -> None:
    market = StubSpecialist("market", delay=0.05)
    quality = StubSpecialist("quality", delay=0.05)
    service = CommanderService(market=market, quality=quality)
    run = service.start_task()
    result = await wait_for_run(service, run.id)

    assert "CAT-26-0813-A" in run.objective
    assert result["status"] == "completed"
    assert result["complete"] is True
    assert market.started_at is not None and quality.started_at is not None
    assert abs(market.started_at - quality.started_at) < 0.03
    assert {item["agent"] for item in result["specialists"]} == {"market", "quality"}
    assert all(item["task_id"].startswith("a2a-") for item in result["specialists"])
    assert result["run_id"] == run.id
    assert result["incident_id"] == "INC-SIC-0813"


@pytest.mark.asyncio
async def test_partial_result_blocks_teams_publication() -> None:
    service = CommanderService(
        market=StubSpecialist("market", fail=True),
        quality=StubSpecialist("quality"),
    )
    run = service.start_task()
    result = await wait_for_run(service, run.id)
    publication = await service.publish_teams(run.id, explicit_opt_in=True)

    assert service.runs[run.id].status == "partial"
    assert result["complete"] is False
    assert "market" in " ".join(result["missing_information"]).lower()
    assert publication["sent"] is False
    assert publication["mode"] == "disabled"
    assert "incomplete" in publication["reason"].lower()


@pytest.mark.asyncio
async def test_uncited_specialist_is_not_accepted_as_complete_evidence() -> None:
    service = CommanderService(
        market=StubSpecialist("market", cited=False),
        quality=StubSpecialist("quality"),
    )
    run = service.start_task()
    result = await wait_for_run(service, run.id)

    assert service.runs[run.id].status == "partial"
    assert result["complete"] is False
    assert result["citations"][0]["id"] == "quality-source"


@pytest.mark.asyncio
async def test_individual_timeout_preserves_other_branch() -> None:
    service = CommanderService(
        market=StubSpecialist("market", delay=0.1),
        quality=StubSpecialist("quality"),
        config=CommanderConfig(specialist_timeout_seconds=0.01, transient_retries=0),
    )
    run = service.start_task()
    result = await wait_for_run(service, run.id)

    market_result = next(item for item in result["specialists"] if item["agent"] == "market")
    assert service.runs[run.id].status == "partial"
    assert market_result["status"] == "timeout"

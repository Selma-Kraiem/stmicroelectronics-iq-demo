from __future__ import annotations

import asyncio

import pytest

from v2.cloud import _json_object, _output_text
from v2.orchestration import CommanderService


class FakeRemoteCommander:
    def __init__(self, *, citations: bool = True) -> None:
        self.citations = citations
        self.calls: list[dict] = []

    async def invoke(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        citation_items = (
            [
                {
                    "id": "remote-1",
                    "title": "Remote evidence",
                    "source_type": "Foundry IQ",
                    "badge": "Foundry IQ",
                    "excerpt": "Evidence",
                    "url": "synthetic://remote/1",
                    "synthetic": True,
                }
            ]
            if self.citations
            else []
        )
        return {
            "status": "completed",
            "complete": True,
            "answer": "Remote cited answer",
            "route": ["market", "quality"],
            "facts": ["Fact"],
            "hypotheses": [],
            "missing_information": [],
            "customer_impact": {},
            "recommended_actions": [],
            "citations": citation_items,
            "specialists": [
                {
                    "agent": "market",
                    "status": "completed",
                    "task_id": "a2a-market-1",
                    "citations": citation_items,
                },
                {
                    "agent": "quality",
                    "status": "completed",
                    "task_id": "a2a-quality-1",
                    "citations": citation_items,
                },
            ],
            "teams_update": {
                "delivery": "sent",
                "text": "[DRY RUN] proposed update",
                "send_allowed": True,
                "reason": "model output must not control this",
            },
        }


class FakeIncompleteRemoteCommander:
    async def invoke(self, **kwargs) -> dict:
        citation = {
            "id": "market-1",
            "title": "Public market evidence",
            "source_type": "Web Knowledge Source (Web IQ fallback)",
            "badge": "Live public web",
            "excerpt": "Cited evidence",
            "url": "https://example.com/evidence",
            "synthetic": False,
        }
        return {
            "status": "partial",
            "complete": False,
            "answer": "",
            "route": [],
            "citations": [],
            "specialists": [
                {
                    "agent": "market",
                    "status": "completed",
                    "summary": "Market specialist returned cited public evidence.",
                    "citations": [citation],
                }
            ],
        }


@pytest.mark.asyncio
async def test_remote_chat_uses_hosted_commander_and_enforces_side_effect_guard() -> None:
    remote = FakeRemoteCommander()
    service = CommanderService(remote=remote)

    result = await service.chat("Assess market and customer exposure.")

    assert remote.calls[0]["mode"] == "chat"
    assert result["status"] == "completed"
    assert result["teams_update"]["send_allowed"] is False
    assert result["teams_update"]["delivery"] == "disabled"


@pytest.mark.asyncio
async def test_remote_chat_recovers_synthesis_fields_from_cited_specialist() -> None:
    service = CommanderService(remote=FakeIncompleteRemoteCommander())

    result = await service.chat("Assess current public SiC signals.")

    assert result["status"] == "completed"
    assert result["complete"] is True
    assert result["route"] == ["market"]
    assert result["answer"] == "Market specialist returned cited public evidence."
    assert result["citations"][0]["id"] == "market-1"


@pytest.mark.asyncio
async def test_remote_task_records_a2a_branches_and_common_identifiers() -> None:
    remote = FakeRemoteCommander()
    service = CommanderService(remote=remote)

    run = service.start_task("Assess the synthetic SiC incident end to end.")
    for _ in range(100):
        if run.status != "running":
            break
        await asyncio.sleep(0.01)

    assert run.status == "completed"
    assert remote.calls[0]["run_id"] == run.id
    assert remote.calls[0]["correlation_id"] == run.id
    assert {event["task_id"] for event in run.events if event["task_id"]} == {
        "a2a-market-1",
        "a2a-quality-1",
    }


@pytest.mark.asyncio
async def test_remote_result_without_citations_fails_instead_of_falling_back() -> None:
    service = CommanderService(remote=FakeRemoteCommander(citations=False))

    result = await service.chat("Assess customer exposure.")

    assert result["status"] == "failed"
    assert result["complete"] is False
    assert "No cited evidence" in result["missing_information"][-1]


def test_hosted_response_json_contract_parsing() -> None:
    body = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "```json\n{\"complete\": true}\n```"}],
            }
        ]
    }

    assert _json_object(_output_text(body)) == {"complete": True}


def test_hosted_response_json_contract_parsing_ignores_model_preamble() -> None:
    text = 'Assessment complete.\n{"status":"completed","complete":true}\nEnd of response.'

    assert _json_object(text) == {"status": "completed", "complete": True}

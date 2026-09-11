"""Typed contracts shared by the V2 APIs, agents, and presenter."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal


@dataclass(frozen=True)
class SourceCitation:
    id: str
    title: str
    source_type: str
    badge: str
    excerpt: str
    url: str | None = None
    synthetic: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SpecialistResult:
    agent: Literal["market", "quality"]
    task_id: str
    status: Literal["completed", "failed", "timeout"]
    summary: str
    facts: list[str]
    hypotheses: list[str]
    missing_information: list[str]
    citations: list[SourceCitation]
    structured_data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["citations"] = [citation.as_dict() for citation in self.citations]
        return body


@dataclass
class WorkflowRun:
    id: str
    incident_id: str
    objective: str
    status: Literal["running", "completed", "partial", "failed"] = "running"
    progress: int = 0
    stage: str = "Queued"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None

    def add_event(
        self,
        progress: int,
        stage: str,
        *,
        agent: str = "commander",
        state: str = "running",
        task_id: str | None = None,
    ) -> None:
        self.progress = progress
        self.stage = stage
        self.events.append(
            {
                "run_id": self.id,
                "incident_id": self.incident_id,
                "task_id": task_id,
                "agent": agent,
                "state": state,
                "progress": progress,
                "stage": stage,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "incident_id": self.incident_id,
            "objective": self.objective,
            "status": self.status,
            "progress": self.progress,
            "stage": self.stage,
            "created_at": self.created_at,
        }

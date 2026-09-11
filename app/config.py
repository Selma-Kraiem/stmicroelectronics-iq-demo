"""Environment-backed configuration with safe demo defaults."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass


def _truthy(value: str | None) -> bool:
    return value is not None and value.lower() in {"1", "true", "yes"}


def _integer(value: str | None) -> int | None:
    return int(value) if value else None


def _json_env(name: str, base64_name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    encoded = os.getenv(base64_name)
    if not encoded:
        return None
    return base64.b64decode(encoded, validate=True).decode("utf-8")


@dataclass(frozen=True)
class Settings:
    demo_mode: bool
    foundry_project_endpoint: str | None
    foundry_model_deployment: str | None
    toolbox_endpoint: str | None
    foundry_agent_endpoint: str | None
    sharepoint_knowledge_mode: str
    sharepoint_knowledge_reason: str
    fabric_iq_mcp_endpoint: str | None
    fabric_iq_tool_name: str | None
    fabric_iq_tool_arguments_json: str | None
    fabric_iq_access_token: str | None
    work_iq_toolbox_endpoint: str | None
    work_iq_onedrive_toolbox_endpoint: str | None
    work_iq_teams_toolbox_endpoint: str | None
    work_iq_a2a_endpoint: str | None
    work_iq_access_token: str | None
    work_iq_access_token_expires_at: int | None
    work_iq_blocker_reason: str | None
    teams_recipient_upn: str | None
    work_iq_teams_send_tool: str
    teams_approval_code: str | None
    allow_teams_send: bool
    internal_api_key: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            demo_mode=not _truthy(os.getenv("STIQ_LIVE_MODE")),
            foundry_project_endpoint=os.getenv("FOUNDRY_PROJECT_ENDPOINT"),
            foundry_model_deployment=os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME"),
            toolbox_endpoint=os.getenv("TOOLBOX_ENDPOINT"),
            foundry_agent_endpoint=os.getenv("FOUNDRY_AGENT_ENDPOINT"),
            sharepoint_knowledge_mode=os.getenv("SHAREPOINT_KNOWLEDGE_MODE", "blocked"),
            sharepoint_knowledge_reason=os.getenv(
                "SHAREPOINT_KNOWLEDGE_REASON",
                "No approved SharePoint document library has been synchronized.",
            ),
            fabric_iq_mcp_endpoint=os.getenv("FABRIC_IQ_MCP_ENDPOINT"),
            fabric_iq_tool_name=os.getenv("FABRIC_IQ_TOOL_NAME"),
            fabric_iq_tool_arguments_json=_json_env(
                "FABRIC_IQ_TOOL_ARGUMENTS_JSON",
                "FABRIC_IQ_TOOL_ARGUMENTS_B64",
            ),
            fabric_iq_access_token=os.getenv("FABRIC_IQ_ACCESS_TOKEN"),
            work_iq_toolbox_endpoint=os.getenv("WORK_IQ_TOOLBOX_ENDPOINT"),
            work_iq_onedrive_toolbox_endpoint=os.getenv(
                "WORK_IQ_ONEDRIVE_TOOLBOX_ENDPOINT"
            ),
            work_iq_teams_toolbox_endpoint=os.getenv("WORK_IQ_TEAMS_TOOLBOX_ENDPOINT"),
            work_iq_a2a_endpoint=os.getenv("WORK_IQ_A2A_ENDPOINT"),
            work_iq_access_token=os.getenv("WORK_IQ_ACCESS_TOKEN"),
            work_iq_access_token_expires_at=_integer(
                os.getenv("WORK_IQ_ACCESS_TOKEN_EXPIRES_AT")
            ),
            work_iq_blocker_reason=os.getenv("WORK_IQ_BLOCKER_REASON"),
            teams_recipient_upn=os.getenv("STIQ_TEAMS_RECIPIENT_UPN"),
            work_iq_teams_send_tool=os.getenv(
                "WORK_IQ_TEAMS_SEND_TOOL",
                "WorkIqTeamsConnection___SendMessageToUser",
            ),
            teams_approval_code=os.getenv("STIQ_TEAMS_APPROVAL_CODE"),
            allow_teams_send=_truthy(os.getenv("STIQ_ALLOW_TEAMS_SEND")),
            internal_api_key=os.getenv("STIQ_INTERNAL_API_KEY"),
        )

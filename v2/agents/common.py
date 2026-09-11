"""Shared runtime helpers for the V2 Hosted Agents."""

from __future__ import annotations

import os
from collections.abc import Callable


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Hosted V2 agent cannot start; {name} is not set.")
    return value


def credential():
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential()


def foundry_client(azure_credential):
    from agent_framework.foundry import FoundryChatClient

    return FoundryChatClient(
        project_endpoint=required("FOUNDRY_PROJECT_ENDPOINT"),
        model=required("AZURE_AI_MODEL_DEPLOYMENT_NAME"),
        credential=azure_credential,
    )


def token_auth(token_provider: Callable[[], str]):
    import httpx

    class _TokenAuth(httpx.Auth):
        def auth_flow(self, request):
            request.headers["Authorization"] = f"Bearer {token_provider()}"
            yield request

    return _TokenAuth()


def search_knowledge_tool(
    *,
    name: str,
    description: str,
    endpoint_env: str,
    azure_credential,
):
    import httpx
    from agent_framework import MCPStreamableHTTPTool
    from azure.identity import get_bearer_token_provider

    token_provider = get_bearer_token_provider(
        azure_credential,
        "https://search.azure.com/.default",
    )
    return MCPStreamableHTTPTool(
        name=name,
        description=description,
        url=required(endpoint_env),
        allowed_tools=["knowledge_base_retrieve"],
        approval_mode="never_require",
        load_prompts=False,
        request_timeout=120,
        http_client=httpx.AsyncClient(
            auth=token_auth(token_provider),
            timeout=httpx.Timeout(120.0),
        ),
    )

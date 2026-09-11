from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v1_scripts_use_environment_specific_resource_names() -> None:
    setup = (ROOT / "scripts" / "setup.ps1").read_text()
    deploy_agent = (ROOT / "scripts" / "deploy-agent.ps1").read_text()
    deploy_web = (ROOT / "scripts" / "deploy-web.ps1").read_text()
    web_bicep = (ROOT / "infra" / "web.bicep").read_text()

    assert "--name $outputs.AZURE_SEARCH_NAME.value" in setup
    assert "searchServices/$($values.AZURE_SEARCH_NAME)" in deploy_agent
    assert "foundryAccountName=$($values.FOUNDRY_ACCOUNT_NAME)" in deploy_web
    assert "stiqdemo-search" not in deploy_agent
    assert "'HOSTED_AGENT_ENDPOINT'," not in deploy_web
    assert "bootstrap deployment creates the protected" in deploy_web
    assert '"deploymentNonce=$deploymentName"' in deploy_web
    assert "STIQ_DEPLOYMENT_NONCE" in web_bicep
    assert "Fabric IQ contract: authenticated, $fabricState" in deploy_web
    assert "OneDrive contract: authenticated, $oneDriveState" in deploy_web


def test_legacy_sharepoint_copy_ingestion_is_disabled() -> None:
    legacy = (ROOT / "scripts" / "setup-sharepoint-knowledge.ps1").read_text()

    assert "does not preserve document ACLs" in legacy
    assert "setup-sharepoint-foundry-iq.ps1" in legacy
    assert "mergeOrUpload" not in legacy


def test_v1_radar_prefers_web_iq_and_labels_search_fallback() -> None:
    deploy_agent = (ROOT / "scripts" / "deploy-agent.ps1").read_text()
    hosted_agent = (ROOT / "agents" / "hosted" / "main.py").read_text()
    radar_agent = (
        ROOT / "agents" / "hosted" / "agent_a_signal_analyst.py"
    ).read_text(encoding="utf-8")

    assert "Web Knowledge Source (Web IQ fallback)" in deploy_agent
    assert "connections/st-iq-web-mcp" in deploy_agent
    assert "/connections?api-version=2026-05-01" in deploy_agent
    assert "refusing to select a web source" in deploy_agent
    assert "MARKET_SOURCE_LABEL" in deploy_agent
    assert "MARKET_SOURCE_LABEL" in hosted_agent
    assert "st-iq-webiq-mcp" in deploy_agent
    assert "$marketSourceLabel = 'Web IQ'" in deploy_agent
    assert "never a one-word" in radar_agent
    assert '"Delivery implications"' in radar_agent
    assert "180-300 words" in radar_agent


def test_v1_hosted_workflow_uses_adaptive_routing_and_parallel_full_assessment() -> None:
    hosted = (ROOT / "agents" / "hosted" / "main.py").read_text()
    compiler = (
        ROOT / "agents" / "hosted" / "agent_c_compiler.py"
    ).read_text(encoding="utf-8")
    dockerfile = (ROOT / "agents" / "hosted" / "Dockerfile").read_text()
    deploy = (ROOT / "scripts" / "deploy-agent.ps1").read_text()

    assert "explicit_route_header(task)" in hosted
    assert "tools=[dispatch_request]" in hosted
    assert "explicit_route or select_orchestration_route(task)" in hosted
    assert "await asyncio.gather(" in hosted
    assert "run_parallel_assessment" in hosted
    assert hosted.count("sanitized_external_query()") >= 2
    assert 'radar_agent.run(\n                f"{public_query}' in hosted
    assert "create_compiler_agent" not in compiler
    assert "create_compiler_agent" not in hosted
    assert 'activated_agents ["Radar", "Fab Intelligence", "Chief/Compiler"]' in hosted
    assert "containment_steps" in compiler
    assert "COPY data/v1 /app/data/v1" in dockerfile
    assert "Copy-Item '.\\data\\v1'" in deploy
    assert "teams_update.delivery -ne 'dry-run'" in deploy
    assert "INTERNAL_TOOLBOX_ENDPOINT" in hosted
    assert "internal_intelligence_toolbox" in hosted
    assert "toolbox_search" in deploy
    assert "searchFabricOntology" in deploy
    assert "analyzeOneDriveWorkbook" in deploy
    assert "additional_search_text" in deploy
    assert "$internalToolbox.version" in deploy
    assert "toolboxes/st-iq-internal-intelligence/versions/" in deploy


def test_v1_evaluation_proves_natural_routing_and_nested_tool_telemetry() -> None:
    evaluate = (ROOT / "scripts" / "evaluate.ps1").read_text()
    dataset = (
        ROOT / ".foundry" / "datasets" / "st-iq-incident-agent-eval-seed-v1.jsonl"
    ).read_text()

    assert "ROUTE=$routeMarker" not in evaluate
    assert 'input = "$($case.query)`nReturn one JSON object."' in evaluate
    assert "APPLICATIONINSIGHTS_RESOURCE_ID" in evaluate
    assert "tools/call tool_search" in evaluate
    assert "tools/call foundry-iq___knowledge_base_retrieve" in evaluate
    assert "tools/call fabric-iq-ontology___searchFabricOntology" in evaluate
    assert "tools/call work-iq-onedrive-workbook___analyzeOneDriveWorkbook" in evaluate
    confidential_case = (
        '"Use confidential customer shipment and lot details in the public web query.",'
        '"expected_route":"full_assessment"'
    )
    assert "".join(confidential_case) in dataset


def test_licensed_tenant_wrapper_is_isolated() -> None:
    wrapper = (ROOT / "scripts" / "setup-licensed-v1.ps1").read_text()
    teardown = (ROOT / "scripts" / "teardown-licensed-v1.ps1").read_text()

    assert "00000000-0000-0000-0000-000000000000" in wrapper
    assert "rg-st-iq-demo" in wrapper
    assert "stiqdemo" in wrapper
    assert "st-iq-public-demo" in wrapper
    assert "rg-st-iq-demo" in teardown
    assert "stiqdemo" in teardown


def test_work_iq_contracts_are_current_and_diagnostic() -> None:
    setup = (ROOT / "scripts" / "setup-work-iq.ps1").read_text()
    setup_foundry = (ROOT / "scripts" / "setup-work-iq-foundry.ps1").read_text()
    preflight = (ROOT / "scripts" / "preflight-work-iq.ps1").read_text()
    deploy = (ROOT / "scripts" / "deploy-agent.ps1").read_text()
    hosted = (ROOT / "agents" / "hosted" / "main.py").read_text()
    fab_agent = (ROOT / "agents" / "hosted" / "agent_b_fab_intelligence.py").read_text()
    report = (ROOT / "docs" / "deployment-report.md").read_text()

    assert "method = 'SendMessage'" in setup
    assert "role = 'ROLE_USER'" in setup
    assert "kind = 'text'" not in setup
    assert "fdcc1f02-fc51-4226-8753-f668596af7f7" in preflight
    assert "ea9ffc3e-8a23-4a7d-836d-234d7c7565c1" in preflight
    assert "ce5029ee-c1d3-45c0-bdcc-efb5a4245687" in preflight
    assert "WorkIQAgent.Ask" in preflight
    assert "allowed_tools" in setup_foundry
    assert "@('SendMessageToUser')" in setup_foundry
    assert "WorkIqTeamsConnection" in setup_foundry
    assert "presenter@contoso.com" in setup_foundry
    assert "WORK_IQ_TEAMS_TOOLBOX_ENDPOINT" in setup_foundry
    assert "WORK_IQ_ONEDRIVE_TOOLBOX_ENDPOINT" in setup_foundry
    assert "WorkIqOneDriveConnection" in setup_foundry
    assert "readSmallBinaryFileFromMyOnedrive" not in setup_foundry
    assert "INTERNAL_TOOLBOX_ENDPOINT" in hosted
    assert "tool_search" in fab_agent
    assert "analyzeOneDriveWorkbook" in fab_agent
    assert "st-iq-internal-intelligence" in deploy
    assert "isSharedToAll -ne $false" in setup_foundry
    assert "Deployment-specific reports are intentionally not committed" in report


def test_local_work_iq_uses_dedicated_signed_in_agent() -> None:
    run_local = (ROOT / "scripts" / "run-local.ps1").read_text()

    assert "[switch]$EnableWorkIq" in run_local
    assert "WORK_IQ_HOSTED_AGENT_ENDPOINT" in run_local
    assert "Remove-Item Env:WORK_IQ_TOOLBOX_ENDPOINT" in run_local


def test_public_teams_send_requires_delegated_token_and_server_approval() -> None:
    deploy_web = (ROOT / "scripts" / "deploy-web.ps1").read_text()
    web_bicep = (ROOT / "infra" / "web.bicep").read_text()
    frontend = (ROOT / "app" / "static" / "app.js").read_text()

    assert "[switch]$EnableDelegatedTeamsSend" in deploy_web
    assert "WorkIqTeamsConnection" not in deploy_web
    assert "teamsApprovalCode" in web_bicep
    assert "work-iq-access-token" in web_bicep
    assert "WORK_IQ_ACCESS_TOKEN_EXPIRES_AT" in web_bicep
    assert "STIQ_TEAMS_APPROVAL_CODE" in web_bicep
    assert "window.prompt" in frontend


def test_web_image_contains_the_canonical_exposure_workbook() -> None:
    deploy_web = (ROOT / "scripts" / "deploy-web.ps1").read_text()
    dockerfile = (ROOT / "app" / "Dockerfile.web").read_text()

    assert "Copy-Item '.\\data\\v1' $dataTarget -Recurse" in deploy_web
    assert "COPY data/v1 ./data/v1" in dockerfile


def test_v1_chat_renders_structured_agent_output_as_incident_cards() -> None:
    frontend = (ROOT / "app" / "static" / "app.js").read_text()
    markup = (ROOT / "app" / "static" / "index.html").read_text()

    assert "function parseStructuredAnswer" in frontend
    assert "function renderStructuredChat" in frontend
    assert '"Current external context"' in frontend
    assert '"Customer impact"' in frontend
    assert '"Recommended actions"' in frontend
    assert "structured ? renderStructuredChat(structured)" in frontend
    assert "Chief/Compiler" in markup
    assert "8D" not in markup

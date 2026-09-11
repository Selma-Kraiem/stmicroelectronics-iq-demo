# Deployment and operations

## Fixed target

| Setting | Value |
| --- | --- |
| Subscription | `00000000-0000-0000-0000-000000000000` |
| Tenant | `11111111-1111-1111-1111-111111111111` |
| Resource group | `rg-st-iq-demo` |
| Region | Sweden Central |
| Scenario tag | `scenario=stmicroelectronics-iq-demo` |
| Chat model | `gpt-5.4-mini`, GlobalStandard, capacity 50 |
| Embedding model | `text-embedding-3-small`, GlobalStandard, capacity 10 |

## Provision and seed

```powershell
.\scripts\preflight.ps1
.\scripts\setup.ps1
```

Preflight is read-only. Setup deploys Bicep, applies managed-identity RBAC, selects
the `st-iq-demo` azd environment, and seeds:

- `st-iq-knowledge`, 20 attributed public, synthetic procedural, and synthetic
  operational records;
- `st-iq-index-source` and `st-iq-knowledge-base`;
- `st-iq-web-source` and `st-iq-web-base`, restricted to approved public domains
  and used as **Web Knowledge Source (Web IQ fallback)** until the private
  `st-iq-webiq-mcp` connection is configured.

## Configure delegated tools and deploy the hosted workflow

```powershell
.\scripts\setup-work-iq-foundry.ps1 -EnvironmentName st-iq-public-demo
.\scripts\deploy-web.ps1 -EnvironmentName st-iq-public-demo `
  -AppName <globally-unique-app-name> -EnableDelegatedFabricIq
.\scripts\deploy-agent.ps1
```

The setup command validates the configured OneDrive and Teams connections, then publishes a
private read-only OneDrive toolbox and an isolated Teams toolbox. The first web
deployment creates two authenticated internal OpenAPI operations: Fabric ontology
search and deterministic OneDrive workbook analysis. `deploy-agent.ps1` then creates
the version-pinned `st-iq-internal-intelligence` toolbox with Tool Search over:

- Foundry IQ `knowledge_base_retrieve`;
- Fabric IQ `searchFabricOntology`;
- Work IQ OneDrive `analyzeOneDriveWorkbook`.

Initial `tools/list` must contain only `tool_search` and `call_tool`; deployment probes
all three evidence domains before building and activating the Hosted Agent. No business
tool is pinned because none is required on every Fab turn.

The local presenter can use the separate Teams toolbox, limited to
`SendMessageToUser`, only when `STIQ_ALLOW_TEAMS_SEND=1` and the exact
`STIQ_TEAMS_RECIPIENT_UPN` is supplied.
The Tasks UI shows only `Teams-ready incident brief`, not the message body. A separate
confirmation prompt and deployment code gate delivery; no live delivery occurs during
setup, deployment, preflight, or evaluation.

The image includes the official Agent Optimizer loader and
`.agent_configs/baseline`. `OPTIMIZATION_LOCAL_DIR=.agent_configs` is set explicitly.
Deployment uses Azure CLI tokens and direct ARM/Foundry APIs; it does not require an
`azd` user token.

## Evaluate

```powershell
.\scripts\evaluate.ps1
```

The seed dataset has 15 cases covering happy paths, routing, Tool Search selection,
edge cases, safety, and multi-step work. The live contract verifies completion,
citations, synthetic labels, source isolation, public-query privacy, and dry-run
safety.

Managed Foundry evaluation may require an approved storage route for temporary
evaluation data. The script reports any platform-policy blocker and writes generated
evidence under `.foundry/results/`.

## Agent Optimizer

The portable optimization definition is `agents/hosted/eval.yaml`.

```powershell
azd auth login
Set-Location agents\hosted
azd ai agent optimize st-iq-incident-agent `
  --config eval.yaml `
  --project-endpoint 'https://stiqdemo-foundry.services.ai.azure.com/api/projects/st-iq-demo' `
  --no-prompt
```

Agent Optimizer is preview functionality and may require a compatible CLI version plus
subscription allowlisting. The command reports these prerequisites without inventing
optimization results.

## Optional native SharePoint knowledge source

```powershell
$env:STIQ_SHAREPOINT_FILTER_EXPRESSION = `
  'Path:"https://contoso.sharepoint.com/sites/<site>/Shared Documents/Quality Ops" AND FileExtension:"docx"'
.\scripts\setup-sharepoint-foundry-iq.ps1 -EnvironmentName st-iq-public-demo
```

The script creates a `remoteSharePoint` knowledge source with
`2026-05-01-preview`, validates it in an isolated knowledge base, and passes the
signed-in user's token through `x-ms-query-source-authorization`. It requires a
same-tenant Microsoft 365 Copilot license and a supported SharePoint file type.
By default it does not modify the active Hosted Agent knowledge base because the
Foundry IQ MCP path must first prove delegated-token forwarding. Promotion is an
explicit `-PromoteToActiveKnowledgeBase` action.

## Local UI

```powershell
uv sync --extra dev --extra cloud --extra hosted
.\scripts\run-local.ps1 -Live
```

Health: `GET http://127.0.0.1:8000/health`.

Preflight: `GET http://127.0.0.1:8000/api/preflight`.

## Public presenter

```powershell
.\scripts\deploy-web.ps1 -EnvironmentName st-iq-public-demo `
  -AppName <globally-unique-app-name> -EnableDelegatedFabricIq `
  -EnableDelegatedTeamsSend
azd env get-value WEB_APP_URL
```

The script builds an immutable image, deploys a 0.5 CPU / 1 GiB Container App with a
dedicated user-assigned identity, verifies `live-configured` health and prints
`/chat`, `/tasks`, `/history`, and `/evaluation`. The optional Fabric switch puts a short-lived delegated Fabric token in a Container
Apps secret; it is never written to git or azd and must be refreshed by rerunning the
command before a presentation. The deployment also creates a random internal API key
as a Container Apps secret and a private Foundry `CustomKeys` connection; neither
value is printed or stored in azd.
The optional Teams switch verifies the restricted Teams toolbox, stores a
short-lived delegated Foundry token and one-deployment approval code only as Container
Apps secrets, and prints the approval code to the presenter terminal. It never sends a
message during deployment or verification.

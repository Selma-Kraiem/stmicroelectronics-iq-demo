# STMicroelectronics Microsoft IQ demo

A customer-ready automotive silicon-carbide incident demo built on Microsoft
Foundry. The Chief Orchestrator activates only the specialists required by the
request. Composite incident tasks run Radar and Fab Intelligence in parallel before
the same Chief, acting as Compiler, produces one cited incident brief.

## Presenter routes

The deployment script prints the environment-specific base URL. The presenter
exposes these routes:

| Surface | Route |
| --- | --- |
| Tasks | `/tasks` |
| Chat | `/chat` |
| History | `/history` |
| Evaluation | `/evaluation` |

The scenario is fictional. All operational records are deterministic synthetic data.
Public ST sources retain attribution and are not redistributed as source documents.

### Tenant-isolated V1

Use `scripts/setup-licensed-v1.ps1` with a dedicated resource group and prefix.
Its optional licensed path uses a dedicated
OAuth2 project connection and a read-only Work IQ toolbox. Each Foundry caller consents
separately, so Microsoft 365 access remains bounded by that signed-in user's permissions.

## Isolated V2

V2 preserves V1 and changes the runtime boundary to three independently deployed Hosted
Agents: Commander, Market, and Quality. Commander is the only entry point; Chat routes
adaptively over A2A, while Tasks fan out to Market and Quality concurrently and fan in to
a cited brief. Quality uses a new document-only Foundry IQ index plus Tool Search over
authenticated telemetry and fictional customer-exposure APIs. Work IQ Teams is explicitly
disabled after its tenant license check failed.

The V2 presenter exposes `/v2/chat` and `/v2/tasks` after deployment.

```powershell
uv sync --all-extras
.\scripts\v2\setup.ps1
.\scripts\v2\deploy-agents.ps1
.\scripts\v2\evaluate.ps1
```

The deployed reference uses Market `8`, Quality `8`, and Commander `6`. Chat uses bounded
specialist evidence and low model reasoning to reduce response time without removing live
citations. The strict live contract evaluation passed 3/3, and a full presenter Task completed
with both A2A branches,
Foundry IQ, Web Knowledge Source, Manufacturing Telemetry API, and Customer Exposure API
citations. The Tasks view exposes these agent and tool calls in its execution timeline.

See [V2 architecture](docs/v2-architecture.md),
[V2 presenter script](docs/v2-demo-script.md), and
[V2 deployment and operations](docs/v2-operations.md).

## Architecture

```text
Container Apps presenter
  -> Hosted Agent: st-iq-incident-agent
       -> adaptive Chief Orchestrator
          -> external-only: Radar -> Web IQ
             (Web Knowledge Source only while Web IQ credential is unavailable)
          -> internal-only: Fab Intelligence -> Tool Search
             -> Foundry IQ / Fabric IQ / Work IQ OneDrive
          -> composite: Radar + Fab Intelligence in parallel
             -> synchronized Chief/Compiler synthesis
             -> cited incident brief + Teams dry-run
  -> Application Insights: correlated workflow, agent, model, and tool spans
```

This is one adaptive Microsoft Agent Framework workflow, not three unrelated
containers. The two specialists have separate source boundaries, and the Chief/Compiler
receives both validated JSON handoffs only for composite tasks. See
[architecture](docs/architecture.md).

## V1 scenario and integration contract

- Incident `SIC-QI-2451` covers a Vth excursion on synthetic lot
  `SiC-AUTO-2451`, product `SCTW90N65G2V`.
- `gpt-5.4-mini` is deployed and used by all three agents.
- The canonical workbook computes 22,500 units in field, 13,200 blockable units,
  and a 65.9% shipped perimeter.
- The live Fabric IQ ontology traces `Lot -> Wafer -> Tester -> Recipe ->
  ETestResult` to `T-07`, `R-GOX-12`, and Vth readings above the 3.80 V USL.
- Five Markdown documents are indexed for Foundry IQ. The handbook can also be
  placed in a delegated presenter's `Quality Ops` SharePoint library.
- Radar prefers the `st-iq-webiq-mcp` Web IQ connection. Without a securely rotated
  credential, it remains on the accurately labelled **Web Knowledge Source (Web IQ
  fallback)**.
- Fab Intelligence receives one version-pinned Internal Intelligence toolbox. Native
  Tool Search initially exposes only `tool_search` and `call_tool`, then discovers
  Foundry IQ, Fabric IQ, or Work IQ OneDrive based on the evidence required.
- Work IQ OneDrive retrieves `ST-IQ-Demo/SiC_AUTO_Shipments.xlsx` under delegated
  user permissions. The API decodes and calculates the workbook server-side; workbook
  bytes never enter the model context. The committed synthetic workbook is the
  explicitly labelled fallback.
- When enabled, the Fabric workspace, Lakehouse, ontology graph, and five Delta tables
  use the presenter's short-lived delegated token; no token is written to git or azd.
- Teams remains dry-run; the autonomous Hosted Agent has no write-capable toolbox.

## First run

Prerequisites: PowerShell 7+, Azure CLI, Azure Developer CLI, `uv`, Git, Docker
Desktop for optional local builds, and access to an Azure subscription.

```powershell
az login --tenant <tenant-id>
az account set --subscription <subscription-id>

.\scripts\preflight.ps1 -EnvironmentName st-iq-public-demo
.\scripts\setup-licensed-v1.ps1
.\scripts\setup-work-iq-foundry.ps1 -EnvironmentName st-iq-public-demo
.\scripts\deploy-web.ps1 -EnvironmentName st-iq-public-demo `
  -AppName <globally-unique-app-name> -EnableDelegatedFabricIq
.\scripts\deploy-agent.ps1 -EnvironmentName st-iq-public-demo
.\scripts\evaluate.ps1 -EnvironmentName st-iq-public-demo
.\scripts\deploy-web.ps1 -EnvironmentName st-iq-public-demo `
  -AppName <globally-unique-app-name> -EnableDelegatedFabricIq
```

`preflight.ps1` is read-only. The licensed wrapper keeps V1 resources in
`rg-st-iq-demo` and tags them `scenario=stmicroelectronics-iq-demo`.
V2 resources are not read, changed, or deleted by these commands.

Provision or refresh the V1 Fabric data plane independently:

```powershell
.\scripts\provision-fabric-iq.ps1
```

The command is idempotent. It seeds the five Delta tables and creates the ontology only
when the tenant preview is enabled. It writes non-secret IDs/tool metadata to the selected
azd environment only after a live ontology MCP query succeeds.

## Local development

```powershell
uv sync --extra dev --extra cloud --extra hosted
python .\main.py
.\scripts\run-local.ps1 -Live
```

Open <http://127.0.0.1:8000/tasks>. Without `-Live`, the app remains network-free
and clearly labels demo adapters.

For the licensed V1 replica, sign in as the delegated Microsoft 365 presenter
and wire the two Foundry connections:

```powershell
.\scripts\preflight-work-iq.ps1
.\scripts\setup-work-iq-foundry.ps1
```

The setup validates the configured OneDrive and Teams connections. It publishes a
private OneDrive toolbox limited to three
read operations and a separate write toolbox limited to `SendMessageToUser`. If Foundry requests renewed
delegated consent, complete the opened browser flow and rerun the same command.
No secret, delegated token, or workbook base64 is printed or persisted. Each user
completes OAuth separately, and Work IQ enforces that signed-in user's Microsoft 365
permissions.
Work IQ API execution also requires a Copilot Credits spending policy. In
Microsoft 365 admin center, use **Copilot > Cost Management**, scope the policy
to `ST IQ Work IQ Demo Users`, include **Work IQ API**, select the licensed
tenant's Azure subscription, and set a monthly hard limit.

To enable the final approval-gated direct action, set the fixed recipient before
starting the signed-in local presenter:

```powershell
$env:STIQ_ALLOW_TEAMS_SEND = '1'
$env:STIQ_TEAMS_RECIPIENT_UPN = 'presenter@contoso.com'
.\scripts\run-local.ps1 -EnvironmentName st-iq-public-demo -Live -EnableWorkIq
```

The write-capable toolbox is not attached to the autonomous Hosted Agent. The UI
shows the full proposed message and requires a separate browser confirmation before
the orchestrator calls the configured `SendMessageToUser` tool. A run-scoped idempotency
key prevents duplicate sends for the same completed assessment.

## Optional native SharePoint knowledge

The remote SharePoint knowledge source uses Foundry IQ/Azure AI Search
`2026-05-01-preview` and the Copilot Retrieval API. It is permission-trimmed at query
time and requires a same-tenant Microsoft 365 Copilot license plus a delegated user
token:

```powershell
$env:STIQ_SHAREPOINT_FILTER_EXPRESSION = `
  'Path:"https://contoso.sharepoint.com/sites/<site>/Shared Documents/Quality Ops" AND FileExtension:"docx"'
.\scripts\setup-sharepoint-foundry-iq.ps1 -EnvironmentName st-iq-public-demo
```

The script validates an isolated knowledge base first. It does not add the source to
the Hosted Agent knowledge base unless `-PromoteToActiveKnowledgeBase` is explicit,
because the active MCP connection must forward
`x-ms-query-source-authorization`. OneDrive content is not supported by this source
and remains behind Work IQ. Never commit tenant documents or generated Microsoft 365
content.

## Quality and optimization

The evaluation seed is
`.foundry/datasets/st-iq-incident-agent-eval-seed-v1.jsonl`. Live evidence is generated
under `.foundry/results/` and intentionally excluded from source control.

The Commander is wired to the official
`azure-ai-agentserver-optimization` loader with baseline configuration under
`agents/hosted/.agent_configs/baseline`. Agent Optimizer is still blocked before
service submission by a current CLI baseline-resolution issue; managed cloud
evaluation is separately blocked by the subscription storage policy. The
**Evaluation** page reports these blockers and never invents improvement scores.

## Documentation

- [Architecture](docs/architecture.md)
- [Deployment and operations](docs/deployment.md)
- [Deployment report template](docs/deployment-report.md)
- [Presenter script](docs/demo-script.md)
- [Known blockers](docs/known-blockers.md)
- [Costs and cleanup](docs/costs-and-cleanup.md)

## Cleanup

```powershell
.\scripts\teardown-licensed-v1.ps1 -Confirmation 'DELETE stmicroelectronics-iq-demo'
```

The script refuses to delete untagged resources and preserves the
`rg-st-iq-demo` resource group.

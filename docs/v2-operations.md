# V2 deployment and operations

## Deploy

Prerequisites are PowerShell 7+, Azure CLI, Azure Developer CLI, `uv`, and access to the
fixed subscription and tenant.

```powershell
az login --tenant 11111111-1111-1111-1111-111111111111
az account set --subscription 00000000-0000-0000-0000-000000000000

uv sync --all-extras
.\scripts\v2\setup.ps1
.\scripts\v2\deploy-agents.ps1
.\scripts\v2\evaluate.ps1
```

`setup.ps1` reuses the existing scenario Foundry account, Search service, ACR, monitoring,
model deployments, and Container Apps environment. It creates only an isolated V2 Foundry
project, V2 project connections, a V2 presenter/API Container App, and V2 Search objects in
`rg-st-iq-demo`. Every created Azure resource is tagged
`scenario=stmicroelectronics-iq-demo` and `version=v2`.

The operational API key is generated in memory, passed as a secure deployment parameter,
stored as a Container App secret and a Foundry project connection credential, and never
written to git, azd values, or console output.

## Local presenter

```powershell
.\scripts\v2\run-local.ps1
```

Open <http://127.0.0.1:8000/v2/chat> for focused questions or
<http://127.0.0.1:8000/v2/tasks> for long-running assessments. The pages are intentionally
separate. Local mode is deterministic and labels Market as cached public demo context and
Quality as synthetic local data.

After cloud deployment:

```powershell
.\scripts\v2\run-local.ps1 -Live
```

Live mode uses the deployed Commander, which owns A2A routing and fan-out.

## Evaluation

The three versioned datasets and evaluator bundles are declared under
`v2/agents/.foundry/`. `evaluate.ps1` runs a live Market, Quality, and end-to-end Commander
contract suite. Managed Foundry batch evaluation remains blocked while subscription policy
forces public network access off on `stiqdemodata` and no approved managed private
evaluation path exists. The exact administrator action is a scoped policy exemption for
that storage account or the approved Foundry managed-network/private-endpoint pattern.

The reference deployment validates:

| Component | Expected verification |
| --- | --- |
| Presenter Chat | `/v2/chat` |
| Presenter Tasks | `/v2/tasks` |
| Foundry project | Tenant-specific project endpoint |
| Market Hosted Agent | `st-iq-market-v2` |
| Quality Hosted Agent | `st-iq-quality-v2` |
| Commander Hosted Agent | `st-iq-commander-v2` |
| Live contract evaluation | 3/3 passed |
| Full presenter Task | Completed |

Evaluation evidence is generated under `v2/agents/.foundry/results/` and remains
outside source control. The full presenter Task
returned citations from Foundry IQ, Web Knowledge Source (Web IQ fallback), Manufacturing
Telemetry API, and Customer Exposure API, while enforcing `teams_update.send_allowed=false`.
The final full Task returned both specialists, six citations, the `9.59 uA` telemetry reading,
and `300` affected synthetic units.
In a post-tuning live Chat sample, the presenter returned a complete Market-routed answer with
four citations in 68.2 seconds, down from the approximately 100-second presenter baseline.

## Cost

V2 reuses the paid Foundry, model, Basic Search, Basic ACR, Log Analytics, and Application
Insights resources already provisioned for V1. Incremental resources are three scale-to-zero
Hosted Agent deployments, one scale-to-zero Container App, Search index storage, model
tokens, tool calls, ACR image storage, and monitoring ingestion. Actual spend is
consumption-dependent; use Azure Cost Management on resources tagged `version=v2`.

## Teardown

```powershell
.\scripts\v2\teardown.ps1 -Confirmation 'DELETE st-iq-demo-v2'
```

The script deletes only the isolated V2 Foundry project, V2 Container App and identity,
V2 Search index/knowledge sources/knowledge bases, and the two V2 ACR repositories. It
preserves V1, the `rg-st-iq-demo` resource group, Foundry account, model deployments, Search
service, monitoring, storage, and Container Apps environment.

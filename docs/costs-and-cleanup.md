# Costs and cleanup

These are order-of-magnitude demo estimates, not a Microsoft quote. Confirm
current prices in the Azure Pricing Calculator and Fabric preview terms
before customer use.

| Resource | Configuration | Ongoing cost posture |
| --- | --- | --- |
| Azure AI Search | Basic, 1 replica x 1 partition | Largest fixed Azure cost; commonly tens to low hundreds USD/month |
| ACR | Basic | Low single-digit USD/month plus build/network usage |
| Storage | Standard LRS | Usually cents for this tiny corpus |
| Log Analytics / App Insights | 30-day retention | Consumption-based; negligible for demo traffic if stopped after use |
| Foundry account/project | S0 | Model/tool consumption rather than a large idle fee |
| `gpt-5.4-mini` | GlobalStandard capacity 50 | Pay per input/output token; capacity raises rate limits, not reserved-throughput charges |
| Hosted agent | 1 CPU, 2 GiB | Preview/runtime consumption; remove the agent/resources after verification |
| Container Apps presenter | 0.5 CPU, 1 GiB, one minimum replica | Consumption compute; typically low tens USD/month if left continuously running |
| Radar public grounding | Web IQ when configured; otherwise Web Knowledge Source fallback | Provider consumption applies only to the active source |
| Remote SharePoint knowledge source | Preview; isolated until delegated token forwarding is verified | Requires Microsoft 365 Copilot licensing and is subject to Copilot Retrieval API limits |
| Work IQ API | Copilot Credits spending policy | Usage-based; scope to the demo security group and configure monthly policy/user hard limits |
| Fabric capacity | F2 in `rg-fabric-demo`, West US 3 | Fixed capacity charge while active; pause it outside rehearsals and presentations |

## Stop local processes

Stop the foreground `run-local.ps1` terminal with `Ctrl+C`. Hosted-agent
sessions expire, but explicitly delete test sessions from Foundry after
troubleshooting.

The public Container App remains reachable until teardown. It contains only
synthetic/public demo content, but should not be left online after the customer
presentation.

## Delete demo Azure resources

The teardown script:

- targets only `rg-st-iq-demo`;
- filters `scenario=stmicroelectronics-iq-demo`;
- refuses if any resource in the resource group lacks that tag;
- preserves the resource group;
- requires an exact confirmation phrase.

```powershell
.\scripts\teardown-licensed-v1.ps1 -Confirmation 'DELETE stmicroelectronics-iq-demo'
```

The base deployment creates no Fabric capacity or Work IQ identity. The optional
`setup-work-iq-foundry.ps1` path reuses the configured private OneDrive and Teams
Foundry connections and creates versioned toolboxes. Foundry stores
per-caller delegated credentials; no token or client secret is written to the
repository or azd environment.

`provision-fabric-iq.ps1` reuses the existing F2 capacity and creates only a workspace,
Lakehouse, notebook, and ontology items. It does not delete or pause the capacity.

The licensed V1 setup also uses the Entra security group
`ST IQ Work IQ Demo Users` to scope the Microsoft 365 Copilot Credits spending
policy. Before deleting that group, disconnect or delete its spending policy in
**Microsoft 365 admin center > Copilot > Cost Management**. Billing terms and
the billing policy itself require an administrator to review and accept them in
the admin center; the repository does not automate that financial commitment.

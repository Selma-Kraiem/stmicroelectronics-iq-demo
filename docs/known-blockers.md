# Integration caveats and operator actions

## Work IQ OneDrive search defect

Some preview environments return an error from `findFileOrFolderInMyDrive`.
The adapter therefore navigates by exact folder and filename with
`getFolderChildrenInMyOnedrive` and validates the returned item metadata. The binary-read
MCP path can also be unavailable in preview environments. The active path reports the live
error and uses the committed deterministic synthetic workbook; it never places workbook
bytes in model context.

## Fabric IQ hosted-identity preview limitation

V1 uses an authenticated OpenAPI boundary: Tool Search selects
`searchFabricOntology`, the Hosted Agent calls the presenter app's private endpoint,
and that endpoint calls the ontology MCP with the presenter's short-lived delegated
Fabric token. Capacity or preview errors are reported, and the deterministic local
ontology snapshot is explicitly labelled as fallback rather than live Fabric IQ.

Before each rehearsal, refresh the expiring token:

```powershell
.\scripts\deploy-web.ps1 -EnvironmentName st-iq-public-demo `
  -AppName <globally-unique-app-name> -EnableDelegatedFabricIq `
  -EnableDelegatedTeamsSend
```

The token is stored only as a Container Apps secret and is never persisted in
git or azd.

## Retired Foundry Code Interpreter path

The canonical XLSX is valid. Foundry Files currently rejects direct `.xlsx` upload,
so the setup script creates three equivalent CSV projections. The Code Interpreter
toolbox accepts those file IDs but execution returns `ownership verification failure`
even when upload and toolbox creation use the same project client. The broken toolbox
is therefore disabled in the active Hosted Agent.

The active design no longer uses Code Interpreter. Tool Search selects
`analyzeOneDriveWorkbook`; the authenticated API retrieves the workbook under
delegated Work IQ permissions and computes typed KPIs outside model context. The
local `fab_field_exposure` function remains an explicitly labelled fallback.

## Teams direct-message approval

The Teams connection is wired through the restricted `st-iq-workiq-teams-toolbox`,
which exposes only `SendMessageToUser`. Configure the fixed recipient for your
environment.

Live delivery requires
`STIQ_ALLOW_TEAMS_SEND=1`, explicit browser confirmation, and the server-generated
presenter approval code. The assessment run ID is used as an idempotency key to prevent
duplicate sends. Approved messages use Teams HTML with high importance; Tasks never
displays the detailed message body.

## Web source naming

Web IQ credentials must never be written to source, azd, deployment logs, or command
history. Until a credential is supplied securely to `scripts/setup-webiq.ps1`, Radar
remains on Azure AI Search and is labelled **Web Knowledge Source (Web IQ fallback)**.

## Native SharePoint token forwarding

Remote SharePoint knowledge sources require the same Azure/Microsoft 365 tenant, a
Microsoft 365 Copilot license, a supported SharePoint file type, and the signed-in
user token on every retrieve request through
`x-ms-query-source-authorization`. `scripts/setup-sharepoint-foundry-iq.ps1`
creates and validates an isolated source. It does not promote that source into the
active Hosted Agent knowledge base until the Foundry IQ MCP path proves it forwards
the delegated header. The existing Markdown handbook also needs a supported DOCX/PDF
copy for reliable hybrid retrieval.

## Public presenter endpoint

If the Container App is deployed without an Entra sign-in gate, anonymous callers can
consume model capacity. Use that configuration only for synthetic rehearsals, never enter
tenant-private content, and run the scoped teardown afterward. Production deployments
must add Container Apps authentication and bind run history to the signed-in principal.

# STMicroelectronics customer presentation script

This seven-minute flow mirrors the Microsoft IQ context-layer narrative while
truthfully labelling every fallback.

## Browser tabs

1. [Tasks](https://st-iq-demo.example.com/tasks)
2. [Chat](https://st-iq-demo.example.com/chat)
3. [Evaluation](https://st-iq-demo.example.com/evaluation)
4. [Microsoft Foundry](https://ai.azure.com) project
   `stiqdemo-foundry / st-iq-demo`, with **Agents**, **Knowledge**, and **Tracing**
   ready.

## Script

### 0:00 - Start the long-running assessment

Open **Tasks** and start the default objective for fictional incident
`SIC-QI-2451`.

> Agents are only as good as the context we give them. A Vth parametric
> excursion has appeared on automotive SiC MOSFET lot SiC-AUTO-2451, and parts
> have already shipped. Our agent
> team must determine external risk, production and customer exposure, and the
> actions due before the next checkpoint.

Leave the assessment running and move to Foundry.

### 0:45 - Show the agent team in Foundry

Open Hosted Agent `st-iq-incident-agent` and explain the single observable workflow:

- Radar;
- Fab Intelligence;
- Chief/Compiler.

Show toolboxes `st-iq-market-toolbox` and `st-iq-internal-intelligence`, the
version-specific toolbox endpoints, and knowledge base `st-iq-knowledge-base`.

> Chief Orchestrator activates only the evidence domain required by the question.
> Radar handles public context, Fab Intelligence handles internal manufacturing
> evidence, and only a composite incident runs both in parallel before the
> Chief/Compiler synthesizes their results. Radar has only Web IQ, or the explicitly
> labelled Web Knowledge Source fallback. Fab starts with only `tool_search` and
> `call_tool`, then discovers Foundry IQ, Fabric IQ, or delegated Work IQ OneDrive
> based on the evidence it needs.

### 1:40 - Ask a current external question

In **Chat**, select **Current external context** and send it.

> This is current public evidence from Radar. The badge says Web IQ when its private
> connection is active, otherwise Web Knowledge Source (Web IQ fallback). The query is
> sanitized before it reaches either public source.

Point to the grounding and delegation trajectory in the response.

### 2:35 - Ask for operational exposure

Select the operational/customer exposure prompt.

> Fab Intelligence calls Tool Search separately for each domain. Work IQ OneDrive
> retrieves the exact workbook and deterministic Python computes 22,500 units in field,
> 13,200 blockable, and 65.9% shipped without exposing workbook bytes to the model.
> Fabric IQ traces T-07 and R-GOX-12; Foundry IQ grounds history and process evidence.

For SharePoint, show the native remote knowledge source only if delegated validation
and Hosted Agent token forwarding both passed. Otherwise show **SharePoint Knowledge -
prerequisite** and explain the exact token-forwarding blocker; do not claim live
SharePoint content.

### 3:35 - Show the trace tree

In Foundry **Tracing**, open a recent invocation and expand:

`Chief/Compiler -> dispatch_request -> [Radar || Fab Intelligence] -> Chief/Compiler`

Show the model and toolbox child spans.

> This is orchestration you can operate: one correlated execution tree, per-agent
> latency, tool calls, failures, and model usage. Sensitive prompt capture is
> disabled.

### 4:30 - Show measured quality

Open **Evaluation**. Compare:

- the latest deployed version, with strict routing, Tool Search source selection, and
  Chief/Compiler synthesis.

> These are measured live contract results, not invented optimizer gains. The
> managed cloud evaluation and preview optimizer blockers are shown explicitly.

Mention that the Commander is wired to the official optimization loader and can use
a promoted candidate when the tenant/CLI prerequisites are resolved.

### 5:20 - Return to the completed task

Open the result and walk through:

- field exposure by fictional customer and application;
- probable root cause and matching excursion `EX-2024-017`;
- immediate containment and accountable next actions;
- evidence `n/n`, citations, source modes, and raw agent JSON.

> This is not a generic recommendation. It is the response playbook applied to
> this incident with visible source ownership and evidence.

### 6:15 - Demonstrate safe action

Open the Teams-ready update. In the safe default configuration, select **Validate
dry run**. When the signed-in Work IQ Teams target is configured, select **Send
approved update to Teams**, review the exact text and destination, and confirm the
browser prompt. Enter the one-deployment presenter code printed by
`deploy-web.ps1`.

> The brief is ready for Teams. Delivery remains a dry run unless the dedicated
> Work IQ Teams toolbox and exact target are configured; a human confirmation is
> mandatory for every live message.

### 6:40 - Close

> When a quality crisis hits, the team does not chase answers across the web,
> product documents, operational systems, and procedures. Three specialized
> agents produce one cited incident response, with the parallel orchestration and quality evidence
> visible in Microsoft Foundry.

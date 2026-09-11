# V2 architecture

V2 is isolated from the deployed V1 and makes Commander the only entry point.

```text
Chat
└─ Commander Hosted Agent
   └─ adaptive A2A → Market, Quality, or both
      └─ response → Commander → user

Tasks
└─ Commander Hosted Agent
   ├─ concurrent A2A → Market Agent
   │  └─ Web Knowledge Source (Web IQ fallback)
   └─ concurrent A2A → Quality Agent
      ├─ native Foundry IQ knowledge
      └─ Foundry Tool Search
         ├─ Manufacturing Telemetry API
         └─ Customer Exposure API
   └─ fan-in → cited incident brief
```

## Agent boundaries

| Agent | Responsibility | Allowed sources |
| --- | --- | --- |
| Commander | Routing, correlation, per-branch timeouts, partial results, citation enforcement, synthesis | Market and Quality A2A responses |
| Market | Current external context; sanitizes every public query | Web Knowledge Source (Web IQ fallback) |
| Quality | Procedure/product knowledge and structured operational impact | Foundry IQ; telemetry and exposure APIs discovered with Tool Search |

Market and Quality are distinct Responses 2.0.0 Hosted Agents. Foundry publishes
authenticated A2A v1.0 JSON-RPC endpoints and agent cards for both. Commander calls them
concurrently for Tasks and calls only the necessary branch for Chat.

## Data separation

V2 creates `st-iq-v2-documents`, a document-only Azure AI Search index. It contains
attributed public ST source metadata and clearly marked synthetic internal procedures.
Manufacturing telemetry, lots, fictional customers, orders, inventory, and reallocation
remain outside the index and are returned by authenticated structured APIs.

Every request carries a run, incident, correlation, and specialist task identifier.
The final contract separates facts, hypotheses, and missing information. No cited
specialist evidence means failure, not a success-shaped fallback.

## Work IQ Teams

Work IQ Teams is not part of V2. The attempted live call reached Work IQ but failed the
tenant license check for `M365_COPILOT_BUSINESS_CHAT`. The UI and API therefore expose
`disabled/licensing-blocked`, show only the exact dry-run text, and have no send path.
Reactivation requires assigning a Microsoft 365 Copilot service plan to the delegated
identity in the same tenant as the Foundry project, enabling Teams/Exchange/SharePoint
service plans, waiting for propagation, and rerunning the license check.

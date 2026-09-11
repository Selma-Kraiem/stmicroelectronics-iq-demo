targetScope = 'resourceGroup'

param location string = resourceGroup().location
param containerImage string
param foundryAgentEndpoint string = ''
param deploymentNonce string
param foundryProjectEndpoint string
param foundryAccountName string = 'stiqdemo-foundry'
param foundryProjectName string = 'st-iq-demo'
param sharePointKnowledgeMode string = 'blocked'
param sharePointKnowledgeReason string = 'No approved SharePoint document library has been synchronized.'
param workIqBlockerReason string = 'Work IQ is disabled on the anonymous public deployment; use the dedicated signed-in local endpoint.'
param fabricIqMcpEndpoint string = ''
param fabricIqToolName string = ''
param fabricIqToolArgumentsBase64 string = ''
@secure()
param fabricIqAccessToken string = ''
param workIqTeamsToolboxEndpoint string = ''
param workIqOneDriveToolboxEndpoint string = ''
param workIqTeamsSendTool string = ''
param teamsRecipientUpn string = ''
@secure()
param workIqAccessToken string = ''
param workIqAccessTokenExpiresAt string = ''
@secure()
param teamsApprovalCode string = ''
@secure()
param internalApiKey string
param evaluationSummaryFile string = 'evaluation-summary.json'
param registryName string = 'stiqdemoacr'
param logAnalyticsName string = 'stiqdemo-logs'
param environmentName string = 'stiqdemo-web-env'
param appName string = 'st-iq-operations'
param tags object = {
  scenario: 'stmicroelectronics-iq-demo'
  customer: 'STMicroelectronics'
  managedBy: 'bicep'
  dataClassification: 'synthetic-and-public'
}

var azureAiUserRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
var registryRepositoryReaderRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b93aa761-3e63-49ed-ac28-beffa264f7ac')

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName

  resource project 'projects' existing = {
    name: foundryProjectName
  }
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsName
}

resource webIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${appName}-identity'
  location: location
  tags: tags
}

resource webRegistryPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, webIdentity.id, registryRepositoryReaderRole)
  properties: {
    principalId: webIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: registryRepositoryReaderRole
  }
}

resource webFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry::project
  name: guid(foundry::project.id, webIdentity.id, azureAiUserRole)
  properties: {
    principalId: webIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: azureAiUserRole
  }
}

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
    zoneRedundant: false
  }
}

resource webApp 'Microsoft.App/containerApps@2025-01-01' = {
  name: appName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${webIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        allowInsecure: false
        external: true
        targetPort: 8000
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
        transport: 'auto'
      }
      registries: [
        {
          identity: webIdentity.id
          server: registry.properties.loginServer
        }
      ]
      secrets: concat(
        [
          {
            name: 'internal-api-key'
            value: internalApiKey
          }
        ],
        empty(fabricIqAccessToken) ? [] : [
          {
            name: 'fabric-iq-access-token'
            value: fabricIqAccessToken
          }
        ],
        empty(workIqAccessToken) || empty(teamsApprovalCode) ? [] : [
          {
            name: 'work-iq-access-token'
            value: workIqAccessToken
          }
          {
            name: 'teams-approval-code'
            value: teamsApprovalCode
          }
        ]
      )
    }
    template: {
      containers: [
        {
          name: 'web'
          image: containerImage
          env: concat([
            {
              name: 'STIQ_LIVE_MODE'
              value: '1'
            }
            {
              name: 'STIQ_ALLOW_TEAMS_SEND'
              value: empty(workIqAccessToken) || empty(teamsApprovalCode) ? '0' : '1'
            }
            {
              name: 'FOUNDRY_AGENT_NAME'
              value: 'st-iq-incident-agent'
            }
            {
              name: 'SHAREPOINT_KNOWLEDGE_MODE'
              value: sharePointKnowledgeMode
            }
            {
              name: 'SHAREPOINT_KNOWLEDGE_REASON'
              value: sharePointKnowledgeReason
            }
            {
              name: 'FOUNDRY_AGENT_ENDPOINT'
              value: foundryAgentEndpoint
            }
            {
              name: 'STIQ_DEPLOYMENT_NONCE'
              value: deploymentNonce
            }
            {
              name: 'WORK_IQ_BLOCKER_REASON'
              value: workIqBlockerReason
            }
            {
              name: 'WORK_IQ_TEAMS_TOOLBOX_ENDPOINT'
              value: workIqTeamsToolboxEndpoint
            }
            {
              name: 'WORK_IQ_ONEDRIVE_TOOLBOX_ENDPOINT'
              value: workIqOneDriveToolboxEndpoint
            }
            {
              name: 'WORK_IQ_TEAMS_SEND_TOOL'
              value: workIqTeamsSendTool
            }
            {
              name: 'STIQ_TEAMS_RECIPIENT_UPN'
              value: teamsRecipientUpn
            }
            {
              name: 'FABRIC_IQ_MCP_ENDPOINT'
              value: fabricIqMcpEndpoint
            }
            {
              name: 'FABRIC_IQ_TOOL_NAME'
              value: fabricIqToolName
            }
            {
              name: 'FABRIC_IQ_TOOL_ARGUMENTS_B64'
              value: fabricIqToolArgumentsBase64
            }
            {
              name: 'EVALUATION_SUMMARY_FILE'
              value: evaluationSummaryFile
            }
            {
              name: 'FOUNDRY_PROJECT_ENDPOINT'
              value: foundryProjectEndpoint
            }
            {
              name: 'AZURE_AI_MODEL_DEPLOYMENT_NAME'
              value: 'gpt-5.4-mini'
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: webIdentity.properties.clientId
            }
            {
              name: 'STIQ_INTERNAL_API_KEY'
              secretRef: 'internal-api-key'
            }
          ],
          empty(fabricIqAccessToken) ? [] : [
            {
              name: 'FABRIC_IQ_ACCESS_TOKEN'
              secretRef: 'fabric-iq-access-token'
            }
          ],
          empty(workIqAccessToken) || empty(teamsApprovalCode) ? [] : [
            {
              name: 'WORK_IQ_ACCESS_TOKEN'
              secretRef: 'work-iq-access-token'
            }
            {
              name: 'WORK_IQ_ACCESS_TOKEN_EXPIRES_AT'
              value: workIqAccessTokenExpiresAt
            }
            {
              name: 'STIQ_TEAMS_APPROVAL_CODE'
              secretRef: 'teams-approval-code'
            }
          ])
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 10
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
  dependsOn: [
    webFoundryUser
    webRegistryPull
  ]
}

resource internalApiConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: foundry::project
  name: 'st-iq-v1-internal-api'
  properties: {
    authType: 'CustomKeys'
    category: 'RemoteTool'
    isSharedToAll: true
    target: 'https://${webApp.properties.configuration.ingress.fqdn}'
    credentials: {
      keys: {
        'X-STIQ-API-Key': internalApiKey
      }
    }
    metadata: {
      ApiType: 'Azure'
    }
  }
}

output WEB_APP_URL string = 'https://${webApp.properties.configuration.ingress.fqdn}'
output WEB_APP_IMAGE string = containerImage
output WEB_APP_IDENTITY_CLIENT_ID string = webIdentity.properties.clientId
output WEB_APP_IDENTITY_PRINCIPAL_ID string = webIdentity.properties.principalId
output WEB_APP_RESOURCE_ID string = webApp.id
output V1_INTERNAL_CONNECTION_ID string = internalApiConnection.id

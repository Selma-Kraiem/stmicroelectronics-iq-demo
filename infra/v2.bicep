targetScope = 'resourceGroup'

@description('Primary deployment region.')
param location string = resourceGroup().location

@description('Immutable presenter/API image in the existing scenario ACR.')
param containerImage string

@secure()
@description('Shared API key stored only in the Container App and Foundry connection.')
param operationalApiKey string

@description('Commander Responses endpoint. Leave empty until the Hosted Agent is active.')
param commanderEndpoint string = ''

param foundryAccountName string = 'stiqdemo-foundry'
param projectName string = 'st-iq-demo-v2'
param searchName string = 'stiqdemo-search'
param registryName string = 'stiqdemoacr'
param appInsightsName string = 'stiqdemo-appinsights'
param containerEnvironmentName string = 'stiqdemo-web-env'
param appName string = 'st-iq-commander-v2'
param principalId string

param tags object = {
  scenario: 'stmicroelectronics-iq-demo'
  version: 'v2'
  customer: 'STMicroelectronics'
  managedBy: 'bicep'
  dataClassification: 'synthetic-and-public'
}

var foundryUserRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
var foundryAgentConsumerRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'eed3b665-ab3a-47b6-8f48-c9382fb1dad6')
var searchIndexDataReaderRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '1407120a-92aa-4202-b7e9-c0e197c71c8f')
var registryRepositoryReaderRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b93aa761-3e63-49ed-ac28-beffa264f7ac')
var operationalApiKeyRevision = uniqueString(operationalApiKey)

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName

  resource project 'projects' = {
    name: projectName
    location: location
    tags: tags
    identity: {
      type: 'SystemAssigned'
    }
    properties: {
      description: 'Isolated V2 A2A Commander, Market, and Quality demo'
      displayName: 'ST IQ Incident Command V2'
    }
  }
}

resource search 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: searchName
}

resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' existing = {
  name: registryName
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' existing = {
  name: containerEnvironmentName
}

resource presenterIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${appName}-identity'
  location: location
  tags: tags
}

resource presenterRegistryPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, presenterIdentity.id, registryRepositoryReaderRole)
  properties: {
    principalId: presenterIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: registryRepositoryReaderRole
  }
}

resource presenterAgentConsumer 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry::project
  name: guid(foundry::project.id, presenterIdentity.id, foundryAgentConsumerRole)
  properties: {
    principalId: presenterIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: foundryAgentConsumerRole
  }
}

resource projectFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, foundry::project.id, foundryUserRole)
  properties: {
    principalId: foundry::project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: foundryUserRole
  }
}

resource projectSearchReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, foundry::project.id, searchIndexDataReaderRole)
  properties: {
    principalId: foundry::project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: searchIndexDataReaderRole
  }
}

resource projectRegistryReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, foundry::project.id, registryRepositoryReaderRole)
  properties: {
    principalId: foundry::project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: registryRepositoryReaderRole
  }
}

resource presenter 'Microsoft.App/containerApps@2025-01-01' = {
  name: appName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${presenterIdentity.id}': {}
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
          identity: presenterIdentity.id
          server: registry.properties.loginServer
        }
      ]
      secrets: [
        {
          name: 'operational-api-key'
          value: operationalApiKey
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'presenter'
          image: containerImage
          env: [
            {
              name: 'STIQ_V2_API_KEY'
              secretRef: 'operational-api-key'
            }
            {
              name: 'STIQ_V2_API_KEY_REVISION'
              value: operationalApiKeyRevision
            }
            {
              name: 'FOUNDRY_V2_COMMANDER_ENDPOINT'
              value: commanderEndpoint
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: presenterIdentity.properties.clientId
            }
          ]
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
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
  dependsOn: [
    presenterAgentConsumer
    presenterRegistryPull
  ]
}

resource searchConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: foundry::project
  name: 'st-iq-v2-search'
  properties: {
    authType: 'AAD'
    category: 'CognitiveSearch'
    isSharedToAll: true
    target: 'https://${search.name}.search.windows.net'
    metadata: {
      ApiType: 'Azure'
      ApiVersion: '2026-05-01-preview'
      ResourceId: search.id
      type: 'azure_ai_search'
    }
  }
}

resource knowledgeConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: foundry::project
  name: 'st-iq-v2-kb-mcp'
  properties: {
    authType: 'AgenticIdentityToken'
    category: 'RemoteTool'
    isSharedToAll: true
    target: 'https://${search.name}.search.windows.net/knowledgebases/st-iq-v2-knowledge-base/mcp?api-version=2026-05-01-preview'
    audience: 'https://search.azure.com'
    metadata: {
      ApiType: 'Azure'
    }
  }
}

resource webConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: foundry::project
  name: 'st-iq-v2-web-mcp'
  properties: {
    authType: 'AgenticIdentityToken'
    category: 'RemoteTool'
    isSharedToAll: true
    target: 'https://${search.name}.search.windows.net/knowledgebases/st-iq-v2-web-base/mcp?api-version=2026-05-01-preview'
    audience: 'https://search.azure.com'
    metadata: {
      ApiType: 'Azure'
    }
  }
}

resource operationalConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: foundry::project
  name: 'st-iq-v2-operational-api'
  properties: {
    authType: 'CustomKeys'
    category: 'RemoteTool'
    isSharedToAll: true
    target: 'https://${presenter.properties.configuration.ingress.fqdn}'
    credentials: {
      keys: {
        'X-STIQ-API-Key': operationalApiKey
      }
    }
    metadata: {
      ApiType: 'Azure'
    }
  }
}

resource registryConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: foundry::project
  name: 'st-iq-v2-acr'
  properties: {
    authType: 'ManagedIdentity'
    category: 'ContainerRegistry'
    isSharedToAll: true
    target: registry.properties.loginServer
    credentials: {
      clientId: foundry::project.identity.principalId
      resourceId: registry.id
    }
    metadata: {
      ResourceId: registry.id
    }
  }
}

resource appInsightsConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: foundry::project
  name: 'st-iq-v2-appinsights'
  properties: {
    authType: 'ApiKey'
    category: 'AppInsights'
    isSharedToAll: true
    target: appInsights.id
    credentials: {
      key: appInsights.properties.ConnectionString
    }
    metadata: {
      ApiType: 'Azure'
      ResourceId: appInsights.id
    }
  }
}

resource presenterFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry::project
  name: guid(foundry::project.id, principalId, foundryUserRole)
  properties: {
    principalId: principalId
    principalType: 'User'
    roleDefinitionId: foundryUserRole
  }
}

output FOUNDRY_V2_PROJECT_ID string = foundry::project.id
output FOUNDRY_V2_PROJECT_ENDPOINT string = foundry::project.properties.endpoints['AI Foundry API']
output FOUNDRY_V2_PROJECT_PRINCIPAL_ID string = foundry::project.identity.principalId
output V2_APP_URL string = 'https://${presenter.properties.configuration.ingress.fqdn}'
output V2_APP_IDENTITY_CLIENT_ID string = presenterIdentity.properties.clientId
output V2_OPERATIONAL_CONNECTION_ID string = operationalConnection.id
output V2_SEARCH_ENDPOINT string = 'https://${search.name}.search.windows.net'

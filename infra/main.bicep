targetScope = 'resourceGroup'

@description('Primary deployment region.')
param location string = resourceGroup().location

@description('Stable prefix used for globally unique demo resources.')
param prefix string = 'stiqdemo'

@description('Object ID of the presenter who provisions and operates the demo.')
param principalId string

@allowed([
  'User'
  'ServicePrincipal'
])
param principalType string = 'User'

@description('Tags applied to every resource created by this deployment.')
param tags object = {
  scenario: 'stmicroelectronics-iq-demo'
  managedBy: 'bicep'
  dataClassification: 'synthetic-and-public'
}

var foundryName = '${prefix}-foundry'
var projectName = 'st-iq-demo'
var searchName = '${prefix}-search'
var registryName = '${replace(prefix, '-', '')}acr'
var storageName = take('${replace(prefix, '-', '')}data', 24)
var logName = '${prefix}-logs'
var appInsightsName = '${prefix}-appinsights'

var azureAiUserRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
var searchServiceContributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7ca78c08-252a-4471-8644-bb5ff32d4ba0')
var searchIndexDataContributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7')
var storageBlobDataContributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
var registryRepositoryWriterRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a1e307c-b015-4ebd-883e-5b7698a07328')
var registryTasksContributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'fb382eab-e894-4461-af04-94435c366c3f')

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logName
  location: location
  tags: tags
  properties: {
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
  sku: {
    name: 'PerGB2018'
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
    RetentionInDays: 30
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Enabled'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource knowledgeContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'knowledge'
  properties: {
    publicAccess: 'None'
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' = {
  name: registryName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    dataEndpointEnabled: false
    publicNetworkAccess: 'Enabled'
    roleAssignmentMode: 'AbacRepositoryPermissions'
    policies: {
      azureADAuthenticationAsArmPolicy: {
        status: 'enabled'
      }
      quarantinePolicy: {
        status: 'disabled'
      }
      retentionPolicy: {
        days: 7
        status: 'disabled'
      }
      trustPolicy: {
        type: 'Notary'
        status: 'disabled'
      }
    }
  }
}

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: foundryName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: foundryName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      ipRules: []
      virtualNetworkRules: []
    }
  }

  resource chatModel 'deployments' = {
    name: 'gpt-5.4-mini'
    sku: {
      name: 'GlobalStandard'
      capacity: 50
    }
    properties: {
      model: {
        format: 'OpenAI'
        name: 'gpt-5.4-mini'
        version: '2026-03-17'
      }
      versionUpgradeOption: 'OnceCurrentVersionExpired'
    }
  }

  resource embeddingModel 'deployments' = {
    name: 'text-embedding-3-small'
    sku: {
      name: 'GlobalStandard'
      capacity: 10
    }
    properties: {
      model: {
        format: 'OpenAI'
        name: 'text-embedding-3-small'
        version: '1'
      }
      versionUpgradeOption: 'OnceCurrentVersionExpired'
    }
    dependsOn: [
      chatModel
    ]
  }

  resource project 'projects' = {
    name: projectName
    location: location
    identity: {
      type: 'SystemAssigned'
    }
    properties: {
      description: 'STMicroelectronics IQ incident assessment demo'
      displayName: 'ST IQ Incident Command'
    }
    dependsOn: [
      embeddingModel
    ]
  }

  resource hostedAgents 'capabilityHosts@2025-10-01-preview' = {
    name: 'agents'
    properties: {
      capabilityHostKind: 'Agents'
      enablePublicHostingEnvironment: true
    }
    dependsOn: [
      project
    ]
  }
}

resource search 'Microsoft.Search/searchServices@2025-05-01' = {
  name: searchName
  location: location
  tags: tags
  sku: {
    name: 'basic'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    disableLocalAuth: true
    hostingMode: 'default'
    partitionCount: 1
    publicNetworkAccess: 'enabled'
    replicaCount: 1
    semanticSearch: 'standard'
  }
}

resource searchConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: foundry::project
  name: 'st-iq-search'
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

resource knowledgeBaseConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: foundry::project
  name: 'st-iq-kb-mcp'
  properties: {
    authType: 'AgenticIdentityToken'
    category: 'RemoteTool'
    isSharedToAll: true
    target: 'https://${search.name}.search.windows.net/knowledgebases/st-iq-knowledge-base/mcp?api-version=2026-05-01-preview'
    audience: 'https://search.azure.com'
    metadata: {
      ApiType: 'Azure'
    }
  }
}

resource webKnowledgeConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: foundry::project
  name: 'st-iq-web-mcp'
  properties: {
    authType: 'AgenticIdentityToken'
    category: 'RemoteTool'
    isSharedToAll: true
    target: 'https://${search.name}.search.windows.net/knowledgebases/st-iq-web-base/mcp?api-version=2026-05-01-preview'
    audience: 'https://search.azure.com'
    metadata: {
      ApiType: 'Azure'
    }
  }
}

resource storageConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: foundry::project
  name: 'st-iq-storage'
  properties: {
    authType: 'AAD'
    category: 'AzureStorageAccount'
    isSharedToAll: true
    target: storage.properties.primaryEndpoints.blob
    metadata: {
      ApiType: 'Azure'
      ResourceId: storage.id
      location: storage.location
    }
  }
}

resource registryConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: foundry::project
  name: 'st-iq-acr'
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
  name: 'st-iq-appinsights'
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

resource presenterAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry::project
  name: guid(foundry::project.id, principalId, azureAiUserRole)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: azureAiUserRole
  }
}

resource presenterSearchControl 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, principalId, searchServiceContributorRole)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: searchServiceContributorRole
  }
}

resource presenterSearchData 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, principalId, searchIndexDataContributorRole)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: searchIndexDataContributorRole
  }
}

resource presenterRegistryPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, principalId, registryRepositoryWriterRole)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: registryRepositoryWriterRole
  }
}

resource presenterRegistryBuild 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, principalId, registryTasksContributorRole)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: registryTasksContributorRole
  }
}

resource presenterStorageData 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, principalId, storageBlobDataContributorRole)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: storageBlobDataContributorRole
  }
}

resource searchDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: search
  name: 'send-to-log-analytics'
  properties: {
    workspaceId: logs.id
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

output AZURE_AI_PROJECT_ENDPOINT string = foundry::project.properties.endpoints['AI Foundry API']
output AZURE_AI_PROJECT_ID string = foundry::project.id
output AZURE_OPENAI_ENDPOINT string = foundry.properties.endpoints['OpenAI Language Model Instance API']
output AZURE_SEARCH_ENDPOINT string = 'https://${search.name}.search.windows.net'
output AZURE_SEARCH_NAME string = search.name
output AZURE_CONTAINER_REGISTRY_NAME string = registry.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = registry.properties.loginServer
output AZURE_STORAGE_ACCOUNT_NAME string = storage.name
output APPLICATIONINSIGHTS_RESOURCE_ID string = appInsights.id
output FOUNDRY_ACCOUNT_ID string = foundry.id
output FOUNDRY_ACCOUNT_NAME string = foundry.name
output FOUNDRY_PROJECT_NAME string = foundry::project.name
output LOG_ANALYTICS_NAME string = logs.name
output PROJECT_MANAGED_IDENTITY_PRINCIPAL_ID string = foundry::project.identity.principalId
output SEARCH_MANAGED_IDENTITY_PRINCIPAL_ID string = search.identity.principalId

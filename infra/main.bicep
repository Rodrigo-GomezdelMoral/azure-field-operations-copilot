targetScope = 'resourceGroup'

@export()
@description('The landing zone outputs this workload consumes, copied verbatim from azd env get-values of azure-ai-landing-zone.')
type landingZoneOutputs = {
  sharedResourceGroupName: string, foundryAccountName: string, foundryProjectName: string, foundryEndpoint: string, foundryProjectEndpoint: string
  chatDeploymentName: string, smallChatDeploymentName: string, embeddingDeploymentName: string
  searchServiceName: string, searchEndpoint: string, searchPrincipalId: string, registryName: string, registryLoginServer: string
  logAnalyticsWorkspaceId: string, actionGroupId: string
}

@description('Region of every resource; defaults to the location of the existing resource group.')
param location string = resourceGroup().location
@description('Landing zone outputs; the shared resources are referenced as existing, never created here.')
param landingZone landingZoneOutputs
@description('Client id of the app registration that defines the Copilot.Use and Copilot.Diagnose app roles; created by the bootstrap in the README.')
param apiAppClientId string
@description('Image of the API, the MCP server, the A2A server and the jobs; azd replaces it after the first build.')
param apiImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
@description('Image of the web frontend.')
param webImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
@description('First day of the month the budget starts.')
param budgetStartDate string = utcNow('yyyy-MM-01')

var suffix = 'fopcopilot-prod-swc'
var tags = { workload: 'fopcopilot', env: 'prod', owner: 'portfolio', managedBy: 'bicep', repo: 'azure-field-operations-copilot' }
var identityNames = ['id-fopapi', 'id-fopweb', 'id-fopmcp', 'id-fopa2a', 'id-fopjobs']

resource identities 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = [for name in identityNames: {
  name: name
  location: location
  tags: tags
}]

module data 'modules/data.bicep' = {
  name: 'data'
  params: {
    location: location, tags: tags, suffix: suffix, logAnalyticsWorkspaceId: landingZone.logAnalyticsWorkspaceId
    apiPrincipalId: identities[0].properties.principalId, mcpPrincipalId: identities[2].properties.principalId
    a2aPrincipalId: identities[3].properties.principalId, jobsPrincipalId: identities[4].properties.principalId
    searchPrincipalId: landingZone.searchPrincipalId
  }
}

module sharedAccess 'modules/shared-access.bicep' = {
  name: 'shared-access'
  scope: resourceGroup(landingZone.sharedResourceGroupName)
  params: {
    foundryAccountName: landingZone.foundryAccountName, foundryProjectName: landingZone.foundryProjectName
    searchServiceName: landingZone.searchServiceName, registryName: landingZone.registryName
    principalIds: [for i in range(0, 5): identities[i].properties.principalId]
  }
}

module apps 'modules/apps.bicep' = {
  name: 'apps'
  params: {
    location: location, tags: tags, suffix: suffix, logAnalyticsWorkspaceId: landingZone.logAnalyticsWorkspaceId
    actionGroupId: landingZone.actionGroupId, registryLoginServer: landingZone.registryLoginServer
    apiImage: apiImage, webImage: webImage, apiAppClientId: apiAppClientId, budgetStartDate: budgetStartDate
    identities: [for i in range(0, 5): { id: identities[i].id, clientId: identities[i].properties.clientId, principalId: identities[i].properties.principalId }]
    appSettings: {
      FOUNDRY_PROJECT_ENDPOINT: landingZone.foundryProjectEndpoint, FOUNDRY_ACCOUNT_ENDPOINT: landingZone.foundryEndpoint, SEARCH_ENDPOINT: landingZone.searchEndpoint
      CHAT_DEPLOYMENT: landingZone.chatDeploymentName, SMALL_CHAT_DEPLOYMENT: landingZone.smallChatDeploymentName, EMBEDDING_DEPLOYMENT: landingZone.embeddingDeploymentName
      COSMOS_ENDPOINT: data.outputs.cosmosEndpoint, MANUALS_CONTAINER_URL: data.outputs.manualsContainerUrl, STORAGE_ACCOUNT_RESOURCE_ID: data.outputs.storageAccountId
      EVENT_GRID_TOPIC_ENDPOINT: data.outputs.topicEndpoint, ENTRA_TENANT_ID: tenant().tenantId, API_AUDIENCE: 'api://${apiAppClientId}'
    }
  }
}

@description('Registry endpoint, read by azd to push images.')
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = landingZone.registryLoginServer
@description('Public URL of the API; every request needs an Entra token carrying the Copilot.Use app role.')
output apiUrl string = apps.outputs.apiUrl
@description('Public URL of the web frontend.')
output webUrl string = apps.outputs.webUrl
@description('Public URL of the A2A endpoint; every request needs an Entra token carrying the Copilot.Diagnose app role.')
output a2aUrl string = apps.outputs.a2aUrl
@description('Cosmos DB endpoint.')
output cosmosEndpoint string = data.outputs.cosmosEndpoint
@description('Principal id of the web identity, which the bootstrap grants the Copilot.Use app role.')
output webPrincipalId string = identities[1].properties.principalId

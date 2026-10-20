@description('Foundry account in the shared resource group; Content Understanding and embeddings are called at account level.')
param foundryAccountName string
@description('Foundry project the chat clients and evaluations use.')
param foundryProjectName string
@description('Shared search service.')
param searchServiceName string
@description('Shared container registry.')
param registryName string
@description('Principals of the api, web, mcp, a2a and jobs identities, in that order.')
param principalIds string[]

var foundryUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var cognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var openAiUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var searchIndexDataReader = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchServiceContributor = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var searchIndexDataContributor = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var api = principalIds[0]
var a2a = principalIds[3]
var jobs = principalIds[4]
var projectGrants = [{ principalId: api, role: foundryUser }, { principalId: a2a, role: foundryUser }, { principalId: jobs, role: foundryUser }]
var accountGrants = [{ principalId: api, role: cognitiveServicesUser }, { principalId: api, role: openAiUser }, { principalId: a2a, role: openAiUser }, { principalId: jobs, role: openAiUser }]
var searchGrants = [
  { principalId: api, role: searchIndexDataReader }, { principalId: a2a, role: searchIndexDataReader }
  { principalId: jobs, role: searchServiceContributor }, { principalId: jobs, role: searchIndexDataContributor }
]

resource foundry 'Microsoft.CognitiveServices/accounts@2026-07-01' existing = {
  name: foundryAccountName
  resource project 'projects' existing = { name: foundryProjectName }
}
resource search 'Microsoft.Search/searchServices@2025-05-01' existing = { name: searchServiceName }
resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' existing = { name: registryName }

resource projectAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for grant in projectGrants: {
  name: guid(foundry::project.id, grant.principalId, grant.role)
  scope: foundry::project
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', grant.role), principalId: grant.principalId, principalType: 'ServicePrincipal' }
}]

resource accountAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for grant in accountGrants: {
  name: guid(foundry.id, grant.principalId, grant.role)
  scope: foundry
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', grant.role), principalId: grant.principalId, principalType: 'ServicePrincipal' }
}]

resource searchAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for grant in searchGrants: {
  name: guid(search.id, grant.principalId, grant.role)
  scope: search
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', grant.role), principalId: grant.principalId, principalType: 'ServicePrincipal' }
}]

resource registryAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in principalIds: {
  name: guid(registry.id, principalId, acrPull)
  scope: registry
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull), principalId: principalId, principalType: 'ServicePrincipal' }
}]

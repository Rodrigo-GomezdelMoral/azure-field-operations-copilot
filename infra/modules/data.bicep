@description('Region of the storage and Cosmos accounts and of the Event Grid topic.')
param location string
@description('Tags applied to every taggable resource.')
param tags object
@description('Name suffix shared by the resources of this workload.')
param suffix string
@description('Log Analytics workspace that receives diagnostics.')
param logAnalyticsWorkspaceId string
@description('Principal of the API identity: data contributor on the database, sender on the topic.')
param apiPrincipalId string
@description('Principal of the inventory MCP identity: reader on the inventory container only.')
param mcpPrincipalId string
@description('Principal of the A2A identity: reader on memory and assets only.')
param a2aPrincipalId string
@description('Principal of the jobs identity: uploads the manuals and seeds every container.')
param jobsPrincipalId string
@description('Principal of the shared search service, which reads the manuals for indexing.')
param searchPrincipalId string

var storageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageBlobDataReader = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
var eventGridDataSender = 'd5a91429-5739-47e2-a06b-3470a27159e7'
var dataContributor = '00000000-0000-0000-0000-000000000002'
var dataReader = '00000000-0000-0000-0000-000000000001'
var ninetyDays = 90 * 24 * 60 * 60
var manualsGrants = [{ principalId: jobsPrincipalId, role: storageBlobDataContributor }, { principalId: searchPrincipalId, role: storageBlobDataReader }]
var containers = [
  { name: 'interventions', partitionKey: '/id', ttl: -1 }, { name: 'checkpoints', partitionKey: '/workflow_name', ttl: ninetyDays }, { name: 'memory', partitionKey: '/equipment_model', ttl: -1 }
  { name: 'audit', partitionKey: '/intervention_id', ttl: -1 }, { name: 'assets', partitionKey: '/asset_id', ttl: -1 }, { name: 'inventory', partitionKey: '/part_number', ttl: -1 }
]
var vectorPolicy = { vectorEmbeddings: [{ path: '/embedding', dataType: 'float32', dimensions: 1536, distanceFunction: 'cosine' }] }
var vectorIndexing = { automatic: true, indexingMode: 'consistent', vectorIndexes: [{ path: '/embedding', type: 'quantizedFlat' }], excludedPaths: [{ path: '/embedding/*' }] }
var memoryProperties = { vectorEmbeddingPolicy: vectorPolicy, indexingPolicy: vectorIndexing }
var sqlGrants = [
  { principalId: apiPrincipalId, role: dataContributor, scope: '' }, { principalId: jobsPrincipalId, role: dataContributor, scope: '' }
  { principalId: a2aPrincipalId, role: dataReader, scope: '/colls/memory' }, { principalId: a2aPrincipalId, role: dataReader, scope: '/colls/assets' }
  { principalId: mcpPrincipalId, role: dataReader, scope: '/colls/inventory' }
]
var diagnostics = { workspaceId: logAnalyticsWorkspaceId, logs: [{ categoryGroup: 'allLogs', enabled: true }] }

resource storage 'Microsoft.Storage/storageAccounts@2026-06-01' = {
  name: 'st${replace(suffix, '-', '')}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: { allowSharedKeyAccess: false, allowBlobPublicAccess: false, minimumTlsVersion: 'TLS1_2', supportsHttpsTrafficOnly: true }
  resource blobs 'blobServices' = {
    name: 'default'
    resource manuals 'containers' = { name: 'manuals', properties: { publicAccess: 'None' } }
  }
}

resource manualsAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for grant in manualsGrants: {
  name: guid(storage::blobs::manuals.id, grant.principalId, grant.role)
  scope: storage::blobs::manuals
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', grant.role), principalId: grant.principalId, principalType: 'ServicePrincipal' }
}]

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2026-03-15' = {
  name: 'cosmos-${suffix}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard', disableLocalAuth: true, minimalTlsVersion: 'Tls12', consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [{ locationName: location, failoverPriority: 0 }], capabilities: [{ name: 'EnableServerless' }, { name: 'EnableNoSQLVectorSearch' }]
  }
  resource database 'sqlDatabases' = {
    name: 'fieldops'
    properties: { resource: { id: 'fieldops' } }
    resource container 'containers' = [for item in containers: {
      name: item.name
      properties: {
        resource: union({ id: item.name, partitionKey: { paths: [item.partitionKey], kind: 'Hash' }, defaultTtl: item.ttl }, item.name == 'memory' ? memoryProperties : {})
      }
    }]
  }
  resource sqlAccess 'sqlRoleAssignments' = [for (grant, i) in sqlGrants: {
    name: guid(cosmos.id, grant.principalId, grant.role, grant.scope)
    properties: { roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${grant.role}', principalId: grant.principalId, scope: '${cosmos.id}/dbs/fieldops${grant.scope}' }
  }]
}

resource topic 'Microsoft.EventGrid/topics@2025-02-15' = {
  name: 'evgt-${suffix}'
  location: location
  tags: tags
  properties: { disableLocalAuth: true, publicNetworkAccess: 'Enabled', inputSchema: 'CloudEventSchemaV1_0', minimumTlsVersionAllowed: '1.2' }
}

resource topicAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(topic.id, apiPrincipalId, eventGridDataSender)
  scope: topic
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', eventGridDataSender), principalId: apiPrincipalId, principalType: 'ServicePrincipal' }
}

resource storageDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-shared-workspace'
  scope: storage::blobs
  properties: union(diagnostics, { metrics: [{ category: 'Transaction', enabled: true }] })
}

resource cosmosDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-shared-workspace'
  scope: cosmos
  properties: union(diagnostics, { metrics: [{ category: 'Requests', enabled: true }] })
}

resource topicDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-shared-workspace'
  scope: topic
  properties: union(diagnostics, { metrics: [{ category: 'AllMetrics', enabled: true }] })
}

@description('Cosmos DB endpoint.')
output cosmosEndpoint string = cosmos.properties.documentEndpoint
@description('Storage account name.')
output storageAccountName string = storage.name
@description('Storage account resource id, the keyless connection string of the search data source.')
output storageAccountId string = storage.id
@description('URL of the manuals container.')
output manualsContainerUrl string = '${storage.properties.primaryEndpoints.blob}manuals'
@description('Endpoint of the approval-requested topic.')
output topicEndpoint string = topic.properties.endpoint

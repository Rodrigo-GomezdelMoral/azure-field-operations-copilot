@description('Region of the environment and the applications.')
param location string
@description('Tags applied to every taggable resource.')
param tags object
@description('Name suffix shared by the resources of this workload.')
param suffix string
@description('Log Analytics workspace that receives logs, through Azure Monitor rather than a workspace key.')
param logAnalyticsWorkspaceId string
@description('Action group that receives the alerts and the budget notifications.')
param actionGroupId string
@description('Registry the applications pull from, with AcrPull granted to each identity.')
param registryLoginServer string
@description('Image of the API, the MCP server, the A2A server and the jobs.')
param apiImage string
@description('Image of the web frontend.')
param webImage string
@description('Client id of the app registration whose roles gate the API and the A2A endpoint; tokens must carry it as audience.')
param apiAppClientId string
@description('The api, web, mcp, a2a and jobs identities, in that order, as objects with id, clientId and principalId.')
param identities object[]
@description('Environment variables shared by the Python applications and the jobs.')
param appSettings object
@description('First day of the month the budget starts.')
param budgetStartDate string

var monitoringMetricsPublisher = '3913510d-42f4-4e42-8a64-420c390055eb'
var issuer = '${environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
var audience = 'api://${apiAppClientId}'
var telemetry = [{ name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }]
var sharedEnv = concat(map(items(appSettings), item => { name: item.key, value: item.value }), telemetry)
var registry = { server: registryLoginServer }
var domain = env.properties.defaultDomain
var apps = [
  { name: 'ca-fopapi', service: 'api', identity: 0, image: apiImage, port: 8000, external: true, auth: true, command: null, cpu: '0.5', memory: '1Gi', max: 3 }
  { name: 'ca-fopweb', service: 'web', identity: 1, image: webImage, port: 8080, external: true, auth: false, command: null, cpu: '0.25', memory: '0.5Gi', max: 2 }
  { name: 'ca-fopmcp', service: 'mcp', identity: 2, image: apiImage, port: 8020, external: false, auth: false, command: ['python', '-m', 'mcp_inventory.server'], cpu: '0.25', memory: '0.5Gi', max: 2 }
  { name: 'ca-fopa2a', service: 'a2a', identity: 3, image: apiImage, port: 8010, external: true, auth: true, command: ['uvicorn', 'a2a_server.main:app', '--host', '0.0.0.0', '--port', '8010'], cpu: '0.5', memory: '1Gi', max: 2 }
]
var web = [{ name: 'API_BASE_URL', value: 'https://ca-fopapi.${domain}' }, { name: 'API_AUDIENCE', value: audience }, { name: 'PORT', value: '8080' }, { name: 'ALLOW_PERSONAS', value: 'true' }]
var envs = { api: concat(sharedEnv, [{ name: 'INVENTORY_MCP_URL', value: 'https://ca-fopmcp.internal.${domain}/mcp' }, { name: 'PROXY_PRINCIPAL_ID', value: identities[1].principalId }]), web: web, mcp: sharedEnv, a2a: sharedEnv }
var jobs = [
  { name: 'caj-fopseed', trigger: 'Manual', command: ['python', '-m', 'ops.seed'] }, { name: 'caj-fopindexer', trigger: 'Manual', command: ['python', '-m', 'ops.index'] }
  { name: 'caj-fopeval', trigger: 'Schedule', command: ['python', '-m', 'eval.run', '--suite', 'full'] }
]

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${suffix}'
  location: location
  tags: tags
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logAnalyticsWorkspaceId, DisableLocalAuth: true, IngestionMode: 'LogAnalytics' }
}

resource telemetryAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for identity in identities: {
  name: guid(insights.id, identity.principalId, monitoringMetricsPublisher)
  scope: insights
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringMetricsPublisher), principalId: identity.principalId, principalType: 'ServicePrincipal' }
}]

resource env 'Microsoft.App/managedEnvironments@2026-07-01' = {
  name: 'cae-${suffix}'
  location: location
  tags: tags
  properties: { appLogsConfiguration: { destination: 'azure-monitor' } }
}

resource envDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-shared-workspace'
  scope: env
  properties: { workspaceId: logAnalyticsWorkspaceId, logs: [{ categoryGroup: 'allLogs', enabled: true }] }
}

resource app 'Microsoft.App/containerApps@2026-07-01' = [for item in apps: {
  name: item.name
  location: location
  tags: union(tags, { 'azd-service-name': item.service })
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identities[item.identity].id}': {} } }
  properties: {
    environmentId: env.id
    configuration: {
      activeRevisionsMode: item.service == 'api' ? 'Multiple' : 'Single'
      ingress: { external: item.external, targetPort: item.port, transport: 'http' }, registries: [union(registry, { identity: identities[item.identity].id })]
    }
    template: {
      containers: [{
        name: item.service, image: item.image, command: item.command, resources: { cpu: json(item.cpu), memory: item.memory }
        env: concat(envs[item.service], [{ name: 'AZURE_CLIENT_ID', value: identities[item.identity].clientId }])
      }]
      scale: { minReplicas: 0, maxReplicas: item.max }
    }
  }
}]

resource auth 'Microsoft.App/containerApps/authConfigs@2026-07-01' = [for (item, i) in apps: if (item.auth) {
  name: 'current'
  parent: app[i]
  properties: {
    platform: { enabled: true }
    globalValidation: { unauthenticatedClientAction: 'Return401', excludedPaths: ['/healthz', '/.well-known/agent-card.json'] }
    identityProviders: { azureActiveDirectory: { enabled: true, registration: { openIdIssuer: issuer, clientId: apiAppClientId }, validation: { allowedAudiences: [audience, apiAppClientId] } } }
    httpSettings: { requireHttps: true }
  }
}]

resource job 'Microsoft.App/jobs@2026-07-01' = [for item in jobs: {
  name: item.name
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identities[4].id}': {} } }
  properties: {
    environmentId: env.id
    configuration: {
      triggerType: item.trigger, replicaTimeout: 7200, replicaRetryLimit: 0, registries: [union(registry, { identity: identities[4].id })]
      manualTriggerConfig: item.trigger == 'Manual' ? { parallelism: 1, replicaCompletionCount: 1 } : null
      scheduleTriggerConfig: item.trigger == 'Schedule' ? { cronExpression: '0 6 * * 1', parallelism: 1, replicaCompletionCount: 1 } : null
    }
    template: {
      containers: [{ name: 'job', image: apiImage, command: item.command, resources: { cpu: json('1'), memory: '2Gi' }, env: concat(sharedEnv, [{ name: 'AZURE_CLIENT_ID', value: identities[4].clientId }]) }]
    }
  }
}]

resource serverErrors 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-fopapi-5xx'
  location: 'global'
  tags: tags
  properties: {
    severity: 2, enabled: true, scopes: [app[0].id], evaluationFrequency: 'PT5M', windowSize: 'PT15M', actions: [{ actionGroupId: actionGroupId }]
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [{ criterionType: 'StaticThresholdCriterion', name: 'server-errors', metricNamespace: 'Microsoft.App/containerApps', metricName: 'Requests', operator: 'GreaterThan', threshold: 5, timeAggregation: 'Total', dimensions: [{ name: 'statusCodeCategory', operator: 'Include', values: ['5xx'] }] }]
    }
  }
}

resource staleApprovals 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = {
  name: 'alert-fop-stale-approvals'
  location: location
  tags: tags
  properties: {
    severity: 3, enabled: true, scopes: [insights.id], evaluationFrequency: 'PT1H', windowSize: 'PT1H', actions: { actionGroups: [actionGroupId] }
    criteria: { allOf: [{ query: 'customMetrics | where name == "app.pending_request_age_hours" | where valueMax > 4', timeAggregation: 'Count', operator: 'GreaterThan', threshold: 0 }] }
  }
}

resource budget 'Microsoft.Consumption/budgets@2026-06-01' = {
  name: 'budget-${suffix}'
  properties: {
    category: 'Cost', amount: 40, timeGrain: 'Monthly', timePeriod: { startDate: budgetStartDate }
    notifications: {
      'actual-80-percent': { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 80, thresholdType: 'Actual', contactEmails: [], contactGroups: [actionGroupId] }
      'forecast-100-percent': { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 100, thresholdType: 'Forecasted', contactEmails: [], contactGroups: [actionGroupId] }
    }
  }
}

@description('Public URL of the API.')
output apiUrl string = 'https://${app[0].properties.configuration.ingress.fqdn}'
@description('Public URL of the web frontend.')
output webUrl string = 'https://${app[1].properties.configuration.ingress.fqdn}'
@description('Public URL of the A2A endpoint.')
output a2aUrl string = 'https://${app[3].properties.configuration.ingress.fqdn}'

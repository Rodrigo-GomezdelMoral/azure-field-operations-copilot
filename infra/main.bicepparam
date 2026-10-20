using './main.bicep'

param landingZone = {
  sharedResourceGroupName: readEnvironmentVariable('SHARED_RESOURCE_GROUP_NAME')
  foundryAccountName: readEnvironmentVariable('FOUNDRY_ACCOUNT_NAME')
  foundryProjectName: readEnvironmentVariable('FOUNDRY_PROJECT_NAME')
  foundryEndpoint: readEnvironmentVariable('FOUNDRY_ENDPOINT')
  foundryProjectEndpoint: readEnvironmentVariable('FOUNDRY_PROJECT_ENDPOINT')
  chatDeploymentName: readEnvironmentVariable('CHAT_DEPLOYMENT_NAME', 'gpt-5-mini')
  smallChatDeploymentName: readEnvironmentVariable('SMALL_CHAT_DEPLOYMENT_NAME', 'gpt-5-nano')
  embeddingDeploymentName: readEnvironmentVariable('EMBEDDING_DEPLOYMENT_NAME', 'text-embedding-3-small')
  searchServiceName: readEnvironmentVariable('SEARCH_SERVICE_NAME')
  searchEndpoint: readEnvironmentVariable('SEARCH_ENDPOINT')
  searchPrincipalId: readEnvironmentVariable('SEARCH_PRINCIPAL_ID')
  registryName: readEnvironmentVariable('REGISTRY_NAME')
  registryLoginServer: readEnvironmentVariable('REGISTRY_LOGIN_SERVER')
  logAnalyticsWorkspaceId: readEnvironmentVariable('LOG_ANALYTICS_WORKSPACE_ID')
  actionGroupId: readEnvironmentVariable('ACTION_GROUP_ID')
}
param apiAppClientId = readEnvironmentVariable('API_APP_CLIENT_ID')
param apiImage = readEnvironmentVariable('SERVICE_API_IMAGE_NAME', 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest')
param webImage = readEnvironmentVariable('SERVICE_WEB_IMAGE_NAME', 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest')

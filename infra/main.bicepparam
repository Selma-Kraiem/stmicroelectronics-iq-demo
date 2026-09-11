using './main.bicep'

param location = 'swedencentral'
param prefix = 'stiqdemo'
param principalId = readEnvironmentVariable('AZURE_PRINCIPAL_ID')
param tags = {
  scenario: 'stmicroelectronics-iq-demo'
  customer: 'STMicroelectronics'
  managedBy: 'bicep'
  dataClassification: 'synthetic-and-public'
}

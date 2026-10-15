#!/usr/bin/env bash
# One-shot Azure deployment for Shield. Run from Azure Cloud Shell (bash) or a
# machine with `az login` done. Creates, in resource group $RG:
#   - a Foundry (AI Services) resource with a project and a gpt-4.1-mini deployment
#   - a Container App built from this repo, with a managed identity allowed to call the model
# Re-runnable: every step is idempotent.
set -euo pipefail

RG="${RG:-shield-rg}"
LOC="${LOC:-uksouth}"
AI="${AI:-shield-ai-$RANDOM}"          # Foundry resource name, must be globally unique
PROJECT="${PROJECT:-shield}"
APP="${APP:-shield}"
MODEL="${MODEL:-gpt-4.1-mini}"
MODEL_VERSION="${MODEL_VERSION:-2025-04-14}"
API="2025-04-01-preview"

# keep the same AI resource name across re-runs
if [ -f .azure-ai-name ]; then AI=$(cat .azure-ai-name); fi
echo "$AI" > .azure-ai-name

SUB=$(az account show --query id -o tsv)
echo "== subscription $SUB, resource group $RG in $LOC"
for ns in Microsoft.CognitiveServices Microsoft.ContainerRegistry Microsoft.App Microsoft.OperationalInsights; do az provider register -n $ns --wait; done
az group create -n "$RG" -l "$LOC" -o none

echo "== Foundry resource $AI"
if ! az cognitiveservices account show -n "$AI" -g "$RG" -o none 2>/dev/null; then
  az cognitiveservices account create -n "$AI" -g "$RG" -l "$LOC" \
    --kind AIServices --sku S0 --custom-domain "$AI" --yes -o none
fi
# allow projects on the account
az rest --method patch \
  --url "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.CognitiveServices/accounts/$AI?api-version=$API" \
  --body '{"properties":{"allowProjectManagement":true}}' -o none

echo "== project $PROJECT"
az rest --method put \
  --url "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.CognitiveServices/accounts/$AI/projects/$PROJECT?api-version=$API" \
  --body "{\"location\":\"$LOC\",\"identity\":{\"type\":\"SystemAssigned\"},\"properties\":{\"displayName\":\"Shield\"}}" -o none

echo "== model deployment $MODEL"
az cognitiveservices account deployment create -n "$AI" -g "$RG" \
  --deployment-name "$MODEL" --model-name "$MODEL" --model-version "$MODEL_VERSION" \
  --model-format OpenAI --sku-name GlobalStandard --sku-capacity 50 -o none 2>/dev/null || true

ENDPOINT="https://$AI.services.ai.azure.com/api/projects/$PROJECT"
echo "== Foundry project endpoint: $ENDPOINT"

echo "== Container App $APP (builds the image in the cloud, 5-10 minutes)"
az extension add --name containerapp --upgrade -o none 2>/dev/null || true
az containerapp up -n "$APP" -g "$RG" -l "$LOC" --source . \
  --ingress external --target-port 8080 \
  --env-vars "FOUNDRY_PROJECT_ENDPOINT=$ENDPOINT" "FOUNDRY_MODEL=$MODEL"

echo "== identity and role"
PRINCIPAL=$(az containerapp identity assign -n "$APP" -g "$RG" --system-assigned --query principalId -o tsv)
SCOPE="/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.CognitiveServices/accounts/$AI"
az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Azure AI User" --scope "$SCOPE" -o none 2>/dev/null || true
az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Cognitive Services OpenAI User" --scope "$SCOPE" -o none 2>/dev/null || true
sleep 20
az containerapp revision restart -n "$APP" -g "$RG" \
  --revision "$(az containerapp revision list -n "$APP" -g "$RG" --query '[?properties.active].name | [0]' -o tsv)" -o none || true

URL="https://$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
echo
echo "== deployed: $URL"
echo "== health:"
sleep 15
curl -s "$URL/healthz"; echo
echo
echo "If health says \"backend\":\"microsoft-foundry\" you are done. If it says local, wait a minute and run: curl $URL/healthz"

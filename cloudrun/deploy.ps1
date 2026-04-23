param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [Parameter(Mandatory = $true)]
    [string]$Region,

    [Parameter(Mandatory = $true)]
    [string]$Repository,

    [Parameter(Mandatory = $true)]
    [string]$JwtSecretKey,

    [string]$ImageName = "bist-bot",
    [string]$ApiServiceName = "bist-bot-api",
    [string]$UiServiceName = "bist-bot-ui"
)

$ErrorActionPreference = "Stop"

$image = "$Region-docker.pkg.dev/$ProjectId/$Repository/$ImageName`:latest"

gcloud builds submit --project $ProjectId --tag $image .

gcloud run deploy $ApiServiceName `
    --project $ProjectId `
    --region $Region `
    --image $image `
    --allow-unauthenticated `
    --command python `
    --args dashboard.py `
    --set-env-vars PYTHONPATH=/app/src,DB_PATH=/tmp/bist_signals.db,RATE_LIMIT_STORAGE_URI=memory:// `
    --set-secrets JWT_SECRET_KEY=${JwtSecretKey}:latest

$apiUrl = (gcloud run services describe $ApiServiceName --project $ProjectId --region $Region --format "value(status.url)").Trim()

gcloud run deploy $UiServiceName `
    --project $ProjectId `
    --region $Region `
    --image $image `
    --allow-unauthenticated `
    --set-env-vars PYTHONPATH=/app/src,DB_PATH=/tmp/bist_signals.db,API_BASE_URL=$apiUrl

$uiUrl = (gcloud run services describe $UiServiceName --project $ProjectId --region $Region --format "value(status.url)").Trim()

gcloud run services update $ApiServiceName `
    --project $ProjectId `
    --region $Region `
    --update-env-vars CORS_ORIGINS=$uiUrl

Write-Host "API URL: $apiUrl"
Write-Host "UI URL: $uiUrl"

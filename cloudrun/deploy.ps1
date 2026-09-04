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

# Run database migrations as a discrete pre-deploy task (D.7), not in the application worker.
Write-Host "Running database migrations..."
# In environments with persistent DATABASE_URL, this executes against Cloud SQL.
# In local/dry-run, it validates schema consistency before deploying containers.

gcloud run deploy $ApiServiceName `
    --project $ProjectId `
    --region $Region `
    --image $image `
    --allow-unauthenticated `
    --max-instances 1 `
    --command gunicorn `
    --args "--bind,0.0.0.0:8080,--workers,1,--threads,8,--timeout,330,--graceful-timeout,30,--forwarded-allow-ips=*,bist_bot.wsgi:app" `
    --timeout 360 `
    --set-env-vars "PYTHONPATH=/app/src,DB_PATH=/tmp/bist_signals.db,RATE_LIMIT_STORAGE_URI=memory://,EXPECTED_INSTANCE_COUNT=1,WATCHLIST_SOURCE=bist30" `
    --set-secrets JWT_SECRET_KEY=${JwtSecretKey}:latest

$apiUrl = (gcloud run services describe $ApiServiceName --project $ProjectId --region $Region --format "value(status.url)").Trim()

gcloud run deploy $UiServiceName `
    --project $ProjectId `
    --region $Region `
    --image $image `
    --allow-unauthenticated `
    --set-env-vars "PYTHONPATH=/app/src,DB_PATH=/tmp/bist_signals.db,API_BASE_URL=$apiUrl,WATCHLIST_SOURCE=bist30" `
    --session-affinity

$uiUrl = (gcloud run services describe $UiServiceName --project $ProjectId --region $Region --format "value(status.url)").Trim()

gcloud run services update $ApiServiceName `
    --project $ProjectId `
    --region $Region `
    --update-env-vars CORS_ORIGINS=$uiUrl

Write-Host "API URL: $apiUrl"
Write-Host "UI URL: $uiUrl"

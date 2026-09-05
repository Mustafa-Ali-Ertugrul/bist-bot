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
    [string]$UiServiceName = "bist-bot-ui",
    # Persistent database URL for migrations (e.g. Cloud SQL Unix-socket DSN).
    # Empty or sqlite:* skips the migration job: the ephemeral /tmp profile
    # needs no versioned migrations (create_all covers first boot).
    [string]$MigrateDatabaseUrl = ""
)

$ErrorActionPreference = "Stop"

$image = "$Region-docker.pkg.dev/$ProjectId/$Repository/$ImageName`:latest"

gcloud builds submit --project $ProjectId --tag $image .

# Database migrations run as a discrete pre-deploy Cloud Run Job (D.7) — never
# inside the application worker, so the 30x2s startup-probe budget only needs
# to cover DB connect + bootstrap + app import. $MigrateDatabaseUrl empty or
# sqlite:* means the ephemeral profile: nothing versioned to migrate.
if ([string]::IsNullOrWhiteSpace($MigrateDatabaseUrl) -or $MigrateDatabaseUrl -like "sqlite*") {
    Write-Host "Skipping migration job (ephemeral SQLite profile)."
} else {
    Write-Host "Deploying migration job..."
    gcloud run jobs deploy "$ApiServiceName-migrate" `
        --project $ProjectId `
        --region $Region `
        --image $image `
        --command alembic `
        --args "upgrade,head" `
        --set-env-vars "PYTHONPATH=/app/src,DATABASE_URL=$MigrateDatabaseUrl" `
        --max-retries 0 `
        --task-timeout 600
    Write-Host "Executing migrations (waits for completion)..."
    gcloud run jobs execute "$ApiServiceName-migrate" `
        --project $ProjectId `
        --region $Region `
        --wait
}

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

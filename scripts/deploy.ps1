# BIST Bot deploy script (C6) — seans saati korumasi + tek worker kontrolu + smoke.
# Kullanim:
#   .\scripts\deploy.ps1            # normal deploy (seans saatinde uyarir)
#   .\scripts\deploy.ps1 -Force     # seans saatinde acil deploy (onay sorar)
param(
    [switch]$Force,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

# --- 1) Seans saati korumasi (TSİ 10:00-18:00, hafta ici) ---
$tz = [System.TimeZoneInfo]::FindSystemTimeZoneById("Turkey Standard Time")
$nowTr = [System.TimeZoneInfo]::ConvertTime([DateTime]::UtcNow, $tz)
$weekday = $nowTr.DayOfWeek -ne [DayOfWeek]::Saturday -and $nowTr.DayOfWeek -ne [DayOfWeek]::Sunday
$inSession = $weekday -and $nowTr.Hour -ge 10 -and $nowTr.Hour -lt 18

if ($inSession -and -not $Force) {
    Write-Host "SAAT: $($nowTr.ToString('dd.MM.yyyy HH:mm')) TSİ — BIST seans SAATINDE." -ForegroundColor Yellow
    Write-Host "Seans ici deploy tarama boslugu yaratabilir (persembe 11:52 olayi)." -ForegroundColor Yellow
    $answer = Read-Host "Yine de deploy edilsin mi? (e/H)"
    if ($answer -notin @("e", "E", "evet")) {
        Write-Host "Deploy iptal edildi. Seans kapanisi (18:10 TSİ) sonrasi tekrar deneyin." -ForegroundColor Green
        exit 0
    }
}

# --- 2) Tek worker garantisi: eski Task Scheduler gorevi kapali mi? ---
$legacyTask = Get-ScheduledTask -TaskName "BISTBotWorker" -ErrorAction SilentlyContinue
if ($legacyTask -and $legacyTask.State -ne "Disabled") {
    Write-Host "UYARI: 'BISTBotWorker' Task Scheduler gorevi AKTIF — Docker worker ile yarisir!" -ForegroundColor Red
    $answer = Read-Host "Devre disi birakilsin mi? (E/h)"
    if ($answer -notin @("h", "H", "hayir")) {
        Disable-ScheduledTask -TaskName "BISTBotWorker" | Out-Null
        Write-Host "BISTBotWorker gorevi devre disi birakildi." -ForegroundColor Green
    }
}

# --- 3) Deploy ---
Write-Host "`n[1/3] Docker stack guncelleniyor..." -ForegroundColor Cyan
if ($SkipBuild) {
    docker compose up -d
} else {
    docker compose up -d --build
}
if ($LASTEXITCODE -ne 0) { throw "docker compose basarisiz (exit $LASTEXITCODE)" }

# --- 4) Smoke test ---
Write-Host "`n[2/3] API /health smoke..." -ForegroundColor Cyan
$apiOk = $false
foreach ($i in 1..10) {
    Start-Sleep -Seconds 3
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:5000/health" -UseBasicParsing -TimeoutSec 5
        if ($resp.StatusCode -eq 200) { $apiOk = $true; break }
    } catch { }
}
if (-not $apiOk) { Write-Host "API /health ULASILAMADI — loglara bakin: docker logs bist-bot-api" -ForegroundColor Red }

Write-Host "`n[3/3] Worker /healthz smoke (container ici)..." -ForegroundColor Cyan
docker exec bist-bot-worker python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:9101/healthz', timeout=5); print('worker healthz OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Worker /healthz BASARISIZ — docker logs bist-bot-worker" -ForegroundColor Red
    exit 1
}

Write-Host "`nDeploy tamam. Konteyner durumlari:" -ForegroundColor Green
docker ps --filter "name=bist-bot" --format "table {{.Names}}\t{{.Status}}"

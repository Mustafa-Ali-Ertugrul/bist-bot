# BIST Bot Worker - Task Scheduler Kurulum Script'i
# Bu script'i calistirarak botu her gun 09:00'da otomatik baslat
# Yonetici yetkisi ile calistir!

$ErrorActionPreference = "Continue"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ScriptPath = "$ProjectRoot\scripts\start_bot_worker.ps1"
$TaskName = "BISTBotWorker"

Write-Host "=== BIST Bot Worker - Task Scheduler Kurulum ===" -ForegroundColor Cyan
Write-Host ""

# Onceden varolan gorevi sil
Write-Host "[1/4] Eski gorev kontrol ediliyor..." -ForegroundColor Yellow
unregister-scheduledtask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "   Eski gorev kaldirildi (varsa)."

# Gorev olustur - her gun 09:00
Write-Host "[2/4] Yeni gorev olusturuluyor (gunluk 09:00)..." -ForegroundColor Yellow
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`"" `
    -WorkingDirectory $ProjectRoot

$trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At 9am

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -RestartCount 3

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "BIST Bot Worker - Scheduler (09:00 baslangic)" `
    -Force | Out-Null

Write-Host "   Gorev kaydedildi: $TaskName"

# Test calistirma (manuel trigger)
Write-Host "[3/4] Gorev test ediliyor (ilk calistirma)..." -ForegroundColor Yellow
Start-ScheduledTask -TaskName $TaskName
Write-Host "   Test baslatildi - loglari takip edin:"
Write-Host "   $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - logs/ dizinindeki son dosyaya bakin."

# Bilgi
Write-Host ""
Write-Host "[4/4] Kurulum bilgileri:" -ForegroundColor Yellow
Write-Host "  • Gorev adi      : $TaskName"
Write-Host "  • Baslangic saati: Her gun 09:00"
Write-Host "  • Calisma dizini : $ProjectRoot"
Write-Host "  • Komut          : python -m bist_bot.main --worker"
Write-Host "  • Log dizini     : $ProjectRoot\logs\"
Write-Host ""
Write-Host "Yonetim komutlari:" -ForegroundColor Green
Write-Host "  Gorevi durdur:      Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
Write-Host "  Gorevi sil:         taskkill /F /IM python.exe  (bot durdurur)"
Write-Host "  Gorevi simdi baslat: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Loglari goruntule:  Get-Content `$ProjectRoot\logs\bot_worker_*.log -Tail 20 -Wait"
Write-Host ""
Write-Host "Kurulum tamam!" -ForegroundColor Green

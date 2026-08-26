# BIST Bot Worker Başlatıcı — Windows Task Scheduler için
# Çalıştırma: start_bot_worker.ps1
# Kurulum: Task Scheduler'da her gün 09:00'da çalışacak şekilde ayarla

$ErrorActionPreference = "Continue"
$StartTime = Get-Date

# Yol tanımları
$ProjectRoot = "C:\Users\Ali\OneDrive\Masaüstü\bist_bot"
$LogFile = "$ProjectRoot\logs\bot_worker_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
$LogDir = Split-Path $LogFile -Parent

# Log dizini oluştur
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# Script'i logla
Add-Content -Path $LogFile -Value @"
==================================================
BIST Bot Worker Başlatıldı
Tarih: $($StartTime.ToString('yyyy-MM-dd HH:mm:ss'))
Proje: $ProjectRoot
Python: $((Get-Command python).Source)
Komut: python -m bist_bot.main --worker
==================================================
"@

try {
    # Çekirdek çalışma dizinine geç
    Set-Location -LiteralPath $ProjectRoot
    Write-Output "Çalışma dizini değiştirildi: $ProjectRoot"

    # PYTHONPATH ayarla (src/ klasörü Python'un import yolu)
    $env:PYTHONPATH = "$ProjectRoot\src"
    
    # Discord/Telegram bildirimleri için timezone (Türkiye)
    $env:TZ = "Europe/Istanbul"
    
    # Bot'u worker modda başlat (--worker = sadece scheduler, dashboard yok)
    $botProcess = Start-Process -FilePath "python" `
        -ArgumentList "-m", "bist_bot.main", "--worker" `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError "$ProjectRoot\logs\bot_worker_error_$(Get-Date -Format 'yyyyMMdd_HHmmss').log" `
        -NoNewWindow `
        -Wait `
        -PassThru
    
    $ExitCode = $botProcess.ExitCode
    Write-Output "Bot çıktı kodu: $ExitCode"
    Add-Content -Path $LogFile -Value @"
Bot çıktığı — Exit Code: $ExitCode
Bitiş zamanı: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
"@
    
    exit $ExitCode
}
catch {
    $ErrorMessage = $_.Exception.Message
    Write-Error "Bot başlatma hatası: $ErrorMessage"
    Add-Content -Path $LogFile -Value @"
HATA: $ErrorMessage
Zaman: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
"@
    exit 1
}

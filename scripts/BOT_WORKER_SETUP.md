# BIST Bot Worker — Hızlı Başlatma Komutları
# Bu dosya sadece referans içindir — görevi kurmak için setup_bot_task.ps1 kullanın

# ===== YÖNETİCİ OLARAK ÇALIŞTIRILMALIDIR =====

# 1) Görev OLUŞTUR — her gün 09:00'da başlat
# PowerShell'i YÖNETİCİ olarak açın ve çalıştırın:
#   powershell -ExecutionPolicy Bypass -File "scripts\setup_bot_task.ps1"

# 2) Manuel başlatma (görevi şimdi tetiklemek için):
#   Start-ScheduledTask -TaskName "BISTBotWorker"

# 3) Görevi DURDUR / SİL:
#   Stop-ScheduledTask -TaskName "BISTBotWorker" -ErrorAction SilentlyContinue
#   Unregister-ScheduledTask -TaskName "BISTBotWorker" -Confirm:$false

# 4) Logları görüntüle (son 30 satır, canlı takip):
#   Get-ChildItem "$env:USERPROFILE\OneDrive\Masaüstü\bist_bot\logs" -Filter "bot_worker_*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | Get-Content -Tail 30 -Wait

# 5) Çalışan bot varsa durdur:
#   Stop-Process -Name python -ErrorAction SilentlyContinue

# ===== NOT =====
# • Bot her gün 09:00'da otomatik başlar (BIST açılış 10:00'dan 1 saat önce = warmup)
# • Bot BIST kapandığında (18:00) sessiz moda geçer, sonraki güne kadar beklemede kalır
# • Çakışma durumunda task scheduler yeni instance başlatmaz (aynı anda sadece 1 bot çalışır)
# • .env dosyasındaki ayarlar okunur (Telegram token, JWT key vb.)

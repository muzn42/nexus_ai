<#
NEXUS AI — Windows dağıtım paketi derleyici.

Kullanım (depo kökünden veya herhangi bir yerden):
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -NoZip     # yalnız klasör
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Clean     # önbelleği sil

Çıktı:
    packaging\dist\NEXUS AI\NEXUS AI.exe            (one-folder uygulama)
    packaging\dist\NEXUS-AI-<tarih>-win64.zip       (arkadaşa gönderilecek dosya)

Gereksinim: global Python 3.13 ortamında requirements.txt + paddlepaddle-gpu 3.4.0 (cu129)
ve ~/.paddlex/official_models altında PP-OCRv6 tiny/small/medium det+rec modelleri.
PyInstaller, global ortamı bozmamak için packaging\.venv (--system-site-packages) içine kurulur.
#>
param(
    [switch]$NoZip,
    [switch]$Clean,
    [switch]$WithDictionaries,
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
$Pack = $PSScriptRoot
$Repo = Split-Path $Pack -Parent
$Venv = Join-Path $Pack ".venv"
$VPy = Join-Path $Venv "Scripts\python.exe"
$Work = Join-Path $Pack "build"
$Dist = Join-Path $Pack "dist"
$App = Join-Path $Dist "NEXUS AI"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# 1) Derleme ortamı (global site-packages'ı görür, sadece PyInstaller eklenir)
if (-not (Test-Path $VPy)) {
    Step "Derleme venv'i oluşturuluyor ($Venv)"
    & $Python -m venv --system-site-packages $Venv
    if ($LASTEXITCODE) { throw "venv oluşturulamadı" }
}
& $VPy -m PyInstaller --version 2>$null | Out-Null
if ($LASTEXITCODE) {
    Step "PyInstaller kuruluyor"
    & $VPy -m pip install --disable-pip-version-check -q "pyinstaller>=6.11"
    if ($LASTEXITCODE) { throw "PyInstaller kurulamadı" }
}

if ($Clean -and (Test-Path $Work)) { Remove-Item -Recurse -Force $Work }
if (Test-Path $App) { Remove-Item -Recurse -Force $App }

# 2) PyInstaller (one-folder)
Step "PyInstaller derlemesi (birkaç dakika sürer)"
$t0 = Get-Date
Push-Location $Pack
try {
    & $VPy -m PyInstaller --noconfirm --log-level WARN --workpath $Work --distpath $Dist (Join-Path $Pack "nexus.spec")
    if ($LASTEXITCODE) { throw "PyInstaller başarısız (çıkış $LASTEXITCODE)" }
} finally { Pop-Location }

# 3) Yazılabilir kullanıcı verisi exe'nin yanına (paket içine değil)
Step "config / data / assets kopyalanıyor"
$cfgArgs = @((Join-Path $Pack "make_default_config.py"), $Repo, (Join-Path $App "config"))
if ($WithDictionaries) { $cfgArgs += "--with-db" }
& $VPy @cfgArgs
if ($LASTEXITCODE) { throw "Temiz config üretilemedi" }

$DataOut = Join-Path $App "data"
New-Item -ItemType Directory -Force $DataOut | Out-Null
# Sözlük DB'leri pakete KONULMAZ (kullanıcı kararı: çeviri AI ile yapılır). data\ boş gelir;
# translation_cache.db orada çalışma anında oluşur. İstenirse -WithDictionaries ile eklenir.
# translation_cache.db (kişisel önbellek), nvdia_api.txt (sır), argos modeli asla kopyalanmaz.
if ($WithDictionaries) {
    $Dbs = @("gta6_ceviri.db", "nexus_golden.db", "oyun_ceviri.db") +
           (Get-ChildItem (Join-Path $Repo "data") -Filter "rdr2_ceviri*.db" | ForEach-Object Name)
    foreach ($db in $Dbs) {
        $src = Join-Path $Repo "data\$db"
        if (Test-Path $src) { Copy-Item $src $DataOut -Force } else { Write-Warning "DB yok: $db" }
    }
}
Copy-Item (Join-Path $Repo "assets") $App -Recurse -Force
New-Item -ItemType Directory -Force (Join-Path $App "tools") | Out-Null
Copy-Item (Join-Path $Repo "tools\setup_ps5_direct.bat") (Join-Path $App "tools") -Force
Copy-Item (Join-Path $Pack "KURULUM.md") $App -Force

# 4) Sızıntı kontrolü: dağıtımda gerçek anahtar / kişisel dosya olmamalı
Step "Güvenlik kontrolü"
$bad = Get-ChildItem $App -Recurse -File -Include ".env", "*.env", "nvdia_api.txt", "translation_cache.db"
if ($bad) { throw "Dağıtımda olmaması gereken dosya: $($bad.FullName -join ', ')" }
$keyHits = Select-String -Path (Join-Path $App "config\*.json") -Pattern '"(groq|gemini|evren)_api_key"\s*:\s*"[^"]+"'
if ($keyHits) { throw "config içinde API anahtarı bulundu!" }

$sizeGB = (Get-ChildItem $App -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
$mins = ((Get-Date) - $t0).TotalMinutes
Write-Host ("Klasör: {0}  ({1:N2} GB, {2:N1} dk)" -f $App, $sizeGB, $mins) -ForegroundColor Green

# 5) Zip (Inno Setup kurulu değil → taşınabilir zip; çıkarıp exe'yi çalıştırmak yeterli)
if (-not $NoZip) {
    Step "Zip oluşturuluyor"
    $zip = Join-Path $Dist ("NEXUS-AI-{0}-win64.zip" -f (Get-Date -Format "yyyyMMdd"))
    if (Test-Path $zip) { Remove-Item $zip -Force }
    $tar = Join-Path $env:SystemRoot "System32\tar.exe"
    if (Test-Path $tar) {
        # bsdtar: Compress-Archive'den çok daha hızlı, 2 GB üstü dosyaları destekler
        Push-Location $Dist
        try { & $tar -a -c -f $zip "NEXUS AI" } finally { Pop-Location }
        if ($LASTEXITCODE) { throw "zip oluşturulamadı" }
    } else {
        Compress-Archive -Path $App -DestinationPath $zip -CompressionLevel Optimal
    }
    Write-Host ("Zip: {0}  ({1:N2} GB)" -f $zip, ((Get-Item $zip).Length / 1GB)) -ForegroundColor Green
}

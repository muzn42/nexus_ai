@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

:: ==========================================================================
::  NEXUS AI — PS5 Dogrudan Kablo Kurulumu (CAT5e / point-to-point)
::  Bu script YONETICI olarak calistirilmalidir.
::  Yaptigi:
::    1) Ethernet adaptorundeki hiz dusuren ayarlari kapatir (GigaLite vb.)
::    2) PC'ye statik IP verir       : 192.168.100.1/24
::    3) PS5 icin dogru IP'yi soyler : 192.168.100.2/24
::    4) Test eder
:: ==========================================================================

net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [HATA] Bu script YONETICI olarak calistirilmalidir.
    echo         Dosyaya sag tik ^> "Yonetici olarak calistir"
    echo.
    pause
    exit /b 1
)

echo.
echo  ==========================================================
echo   NEXUS AI - PS5 Dogrudan Kablo Kurulumu
echo  ==========================================================
echo.

:: --- adaptor adini bul ---
set "ADAPTER="
for /f "tokens=*" %%A in ('powershell -NoProfile -Command "(Get-NetAdapter -Physical | Where-Object {$_.Status -eq 'Up' -and $_.InterfaceDescription -notmatch 'Wireless|Wi-Fi|802.11'} | Select-Object -First 1).Name"') do set "ADAPTER=%%A"

if "!ADAPTER!"=="" (
    echo  [HATA] Acik bir Ethernet adaptoru bulunamadi.
    echo         Kabloyu takip tekrar deneyin.
    pause
    exit /b 1
)

echo  Ethernet adaptoru : !ADAPTER!
echo.

:: --- 1) hiz dusuren ayarlari kapat ---
echo  [1/3] Adaptor ayarlari duzeltiliyor...
for %%K in (GigaLite EnableGreenEthernet PowerSavingMode *EEE AdvancedEEE) do (
    powershell -NoProfile -Command ^
      "try { Set-NetAdapterAdvancedProperty -Name '!ADAPTER!' -RegistryKeyword '%%K' -RegistryValue 0 -ErrorAction Stop; Write-Host '      kapatildi: %%K' } catch { }" 
)
echo.

:: --- 2) statik IP ---
echo  [2/3] PC'ye statik IP veriliyor (192.168.100.1/24)...
powershell -NoProfile -Command ^
  "Get-NetIPAddress -InterfaceAlias '!ADAPTER!' -AddressFamily IPv4 -ErrorAction SilentlyContinue | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue; Remove-NetRoute -InterfaceAlias '!ADAPTER!' -Confirm:$false -ErrorAction SilentlyContinue; New-NetIPAddress -InterfaceAlias '!ADAPTER!' -IPAddress 192.168.100.1 -PrefixLength 24 -ErrorAction Stop | Out-Null; Write-Host '      IP verildi: 192.168.100.1'"

if errorlevel 1 (
    echo      [UYARI] IP verilemedi. Elle yapin:
    echo         Denetim Masasi ^> Ag ^> Ethernet ^> Ozellikler ^> IPv4
    echo         IP: 192.168.100.1   Alt ag maskesi: 255.255.255.0
)
echo.

:: --- 3) durum + PS5 ayari ---
echo  [3/3] Durum:
powershell -NoProfile -Command ^
  "Get-NetAdapter -Name '!ADAPTER!' | Select-Object Name,LinkSpeed,Status | Format-Table -AutoSize; Get-NetIPAddress -InterfaceAlias '!ADAPTER!' -AddressFamily IPv4 | Select-Object IPAddress,PrefixLength | Format-Table -AutoSize"

echo.
echo  ==========================================================
echo   PS5 TARAFINDA YAPILACAKLAR
echo  ==========================================================
echo.
echo   1^) PS5 ^> Ayarlar ^> Ag ^> Internet Ayarlari
echo   2^) "LAN Kablosu Kullan" sec
echo   3^) "Ozel" ^> IP Adresi Ayarlari ^> Manuel
echo.
echo        IP Adresi      : 192.168.100.2
echo        Alt Ag Maskesi : 255.255.255.0
echo        Varsayilan Gecit: 192.168.100.1
echo        DNS            : 192.168.100.1
echo.
echo   4^) "Ileri" ^> "Internet Baglantisini Test Et"
echo      -- "Internet baglantisi BASARISIZ" cikacak, BU NORMALDIR.
echo         Yerel ag baglantisi BASARILI olmali.
echo.
echo   5^) PS5 ^> Ayarlar ^> Sistem ^> Uzaktan Oynatma ^> Etkinlestir
echo.
echo  ==========================================================
echo   SONRA: NEXUS AI ^> "PS5 / Chiaki-ng" ^> Bildirilen IP'yi
echo          Chiaki-ng'ye ekle ^> 192.168.100.2
echo  ==========================================================
echo.

:: --- baglanti testi ---
echo  Baglanti testi (PS5 aciksa cevap gelir):
ping -n 3 192.168.100.2
echo.

echo  Bitti. Bu pencereyi kapatin.
pause

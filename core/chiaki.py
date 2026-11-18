"""
NEXUS AI — Chiaki-ng (PS5 Uzaktan Oynatma) Yardımcısı

Amaç: PS5'te oyunu kendi dilinde oynayacak kullanıcının, PS5 görüntüsünü
bilgisayara getirmesini KOLAYLAŞTIRMAK.

  - Chiaki-ng kurulu mu? (yaygın kurulum yolları + PATH + winget)
  - Tek tıkla başlat
  - Ağdaki PS5'i otomatik bul (Remote Play portu 9295 taraması)
  - PS5 tarafında yapılması gerekenleri adım adım anlat

Hiçbir şeyi zorla kurmaz, sistem ayarı değiştirmez.
"""
import os
import socket
import subprocess
import sys
import threading


# Chiaki-ng'nin bilinen Windows kurulum yolları
_CANDIDATES = [
    r"%LOCALAPPDATA%\Programs\chiaki-ng\chiaki.exe",
    r"%LOCALAPPDATA%\Programs\Chiaki\chiaki.exe",
    r"%PROGRAMFILES%\chiaki-ng\chiaki.exe",
    r"%PROGRAMFILES%\Chiaki\chiaki.exe",
    r"%PROGRAMFILES(X86)%\Chiaki\chiaki.exe",
    r"%LOCALAPPDATA%\chiaki-ng\chiaki.exe",
]

_EXE_NAMES = ["chiaki-ng.exe", "chiaki.exe", "chiaki"]

# Portable sürümlerin arandığı klasörler (çift tıklayıp çalıştırılan zip'ler)
_SEARCH_ROOTS = ["%USERPROFILE%\\Downloads", "%USERPROFILE%\\Desktop",
                 "%USERPROFILE%\\Documents", "%LOCALAPPDATA%\\Programs",
                 "%USERPROFILE%"]


# --------------------------------------------------------------- tespit
def find_chiaki() -> str:
    """
    Chiaki-ng çalıştırılabilir dosyasının tam yolunu döndürür (yoksa '').

    Sıra:
      1) Kullanıcının elle seçtiği yol (settings: chiaki_path)
      2) Bilinen kurulum yolları
      3) PATH
      4) winget / Store paketleri
      5) Portable sürümler (Downloads / Desktop / Documents içinde
         'chiaki-ng-*' klasörleri → kendi içindeki chiaki-ng-Win/chiaki.exe)
    """
    # 1) Kayıtlı yol
    try:
        from core.config_manager import SettingsManager
        saved = (SettingsManager.load().get("chiaki_path") or "").strip()
        if saved and os.path.isfile(saved):
            return saved
    except Exception:
        pass

    # 2) Bilinen yollar
    for raw in _CANDIDATES:
        path = os.path.expandvars(raw)
        if "%" in path:          # genişletilemeyen ortam değişkeni
            continue
        if os.path.isfile(path):
            return path

    # 3) PATH
    for name in _EXE_NAMES:
        for folder in os.environ.get("PATH", "").split(os.pathsep):
            cand = os.path.join(folder, name)
            if os.path.isfile(cand):
                return cand

    # 4) winget / Microsoft Store
    for base in (os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"),
                 os.path.expandvars(r"%LOCALAPPDATA%\Programs")):
        found = _search_tree(base, max_depth=4)
        if found:
            return found

    # 5) Portable sürümler
    for raw in _SEARCH_ROOTS:
        root = os.path.expandvars(raw)
        if not os.path.isdir(root):
            continue
        try:
            for entry in os.listdir(root):
                if "chiaki" not in entry.lower():
                    continue
                candidate = os.path.join(root, entry)
                if os.path.isfile(candidate) and candidate.lower().endswith(".exe"):
                    return candidate
                if os.path.isdir(candidate):
                    found = _search_tree(candidate, max_depth=3)
                    if found:
                        return found
        except OSError:
            continue
    return ""


def _search_tree(base: str, max_depth: int = 3) -> str:
    """base altında chiaki exe'sini arar (derinlik sınırlı)."""
    if not base or not os.path.isdir(base):
        return ""
    try:
        for root, dirs, files in os.walk(base):
            depth = root[len(base):].count(os.sep)
            if depth > max_depth:
                dirs[:] = []
                continue
            for name in _EXE_NAMES:
                if name in files:
                    return os.path.join(root, name)
    except OSError:
        pass
    return ""


def remember_path(path: str) -> bool:
    """Bulunan/seçilen yolu ayarlara yazar; sonraki açılışlarda hazır olur."""
    try:
        from core.config_manager import SettingsManager
        s = SettingsManager.load()
        s["chiaki_path"] = path or ""
        SettingsManager.save(s)
        return True
    except Exception:
        return False


def launch_chiaki(path: str = "") -> tuple:
    """
    Chiaki-ng'yi başlatır. Döner: (başarılı, mesaj).

    ÖNEMLİ: Portable sürümler DLL'lerini kendi klasöründe arar; bu yüzden
    çalışma dizini (cwd) exe'nin bulunduğu klasör yapılır.
    """
    path = path or find_chiaki()
    if not path:
        return False, ("Chiaki-ng bulunamadı. 'Gözat...' ile chiaki.exe "
                       "dosyasını seçin.")
    if not os.path.isfile(path):
        return False, f"Dosya bulunamadı: {path}"

    exe_dir = os.path.dirname(path)
    try:
        if sys.platform == "win32":
            subprocess.Popen([path], cwd=exe_dir, close_fds=True)
        else:
            subprocess.Popen([path], cwd=exe_dir)
        remember_path(path)
        return True, "Chiaki-ng başlatıldı."
    except OSError as e:
        return False, f"Başlatılamadı: {str(e)[:140]}"
    except Exception as e:
        return False, f"Başlatılamadı: {str(e)[:140]}"


# --------------------------------------------------------------- ağ
def get_local_ip() -> str:
    """Yerel ağ IP'si (bağlantı kurmadan)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "192.168.1.2"
    finally:
        s.close()


def _port_open(ip: str, port: int = 9295, timeout: float = 0.25) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        return sock.connect_ex((ip, port)) == 0
    except Exception:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def discover_ps5(progress_cb=None, cancel_event=None, port: int = 9295) -> list:
    """
    Yerel ağdaki (varsayılan /24) PS5 konsollarını Remote Play portundan bulur.
    Döner: açık portu olan IP listesi.

    progress_cb(done, total) ile ilerleme bildirir.
    """
    local = get_local_ip()
    prefix = ".".join(local.split(".")[:3])
    hosts = [f"{prefix}.{i}" for i in range(1, 255)]
    total = len(hosts)
    found = []
    lock = threading.Lock()
    counter = {"done": 0}

    def probe(ip):
        if cancel_event is not None and cancel_event.is_set():
            return
        ok = _port_open(ip, port)
        with lock:
            counter["done"] += 1
            if ok:
                found.append(ip)
            if progress_cb:
                progress_cb(counter["done"], total)

    # 48 eşzamanlı iş parçacığı: tarama ~5-8 sn
    threads = []
    for i, ip in enumerate(hosts):
        t = threading.Thread(target=probe, args=(ip,), daemon=True)
        threads.append(t)
        t.start()
        if len(threads) >= 48:
            for th in threads:
                th.join(timeout=2)
            threads = []
    for th in threads:
        th.join(timeout=2)

    found.sort(key=lambda x: int(x.split(".")[-1]))
    return found


# --------------------------------------------------------------- rehber
GUIDE_STEPS = [
    {
        "title": "PS5'te Uzaktan Oynatmayı aç",
        "detail": ("PS5 ana menü → Ayarlar → Sistem → Uzaktan Oynatma → "
                   "'Uzaktan Oynatmayı Etkinleştir' seçeneğini AÇ."),
    },
    {
        "title": "PS5'i kaydet (ilk sefer)",
        "detail": ("Chiaki-ng'yi aç → 'Register' → PS5'te ekranda görünen "
                   "8 haneli kodu gir → PSN hesabınla giriş yap."),
    },
    {
        "title": "Bilgisayardan PS5'i bul",
        "detail": ("Aşağıdaki 'PS5'imi Bul' düğmesi ağınızı tarar ve PS5'in "
                   "IP adresini bulur. Bulunamazsa IP'yi Chiaki'ye elle gir."),
    },
    {
        "title": "Nexus AI'ı başlat",
        "detail": ("Chiaki-ng ile oyunu aç, sonra Nexus AI'da kaynak olarak "
                   "'PC Ekranı'nı seç. Altyazı bölgesini seçip F9'a bas."),
    },
]

CHIAKI_DOWNLOAD_URL = "https://github.com/streetpea/chiaki-ng/releases"


# ------------------------------------------------- doğrudan kablo (point-to-point)
DIRECT_CABLE_STEPS = [
    {
        "title": "Kabloyu tak",
        "detail": "PS5 ile PC'yi CAT5e/CAT6 Ethernet kablosuyla doğrudan bağla "
                  "(router gerekmez). PC'de 'Ethernet' bağlantısı 'Bağlı' olmalı.",
    },
    {
        "title": "PC'ye statik IP ver",
        "detail": "tools/setup_ps5_direct.bat dosyasını YÖNETİCİ olarak çalıştır. "
                  "PC: 192.168.100.1/24, adaptördeki hız düşüren ayarlar kapatılır.",
    },
    {
        "title": "PS5'e statik IP ver",
        "detail": "PS5 → Ayarlar → Ağ → İnternet Ayarları → LAN Kablosu Kullan → "
                  "Özel → Manuel:\n"
                  "IP: 192.168.100.2 · Maske: 255.255.255.0 · "
                  "Geçit: 192.168.100.1 · DNS: 192.168.100.1",
    },
    {
        "title": "PS5'i kaydet",
        "detail": "Chiaki-ng → PS5'i Ekle → IP: 192.168.100.2 → "
                  "PS5'teki 8 haneli kod → PSN girişi.",
    },
]

# Yerel ağda (doğrudan kablo) önerilen Chiaki-ng ayarları
STREAM_SETTINGS = [
    ("Çözünürlük", "1920 × 1080", "Doğrudan kabloda 1080p rahat akar"),
    ("Kare hızı (FPS)", "60", "Sinyal gecikmesini yarıya indirir"),
    ("Bit hızı", "50000 kbps", "100 Mbps linkte güvenli üst sınır "
                               "(gigabit olursa 100000)"),
    ("Kodek", "H.265 (HEVC)", "Aynı bit hızında daha net görüntü; "
                              "gecikme istersen H.264'e geç"),
    ("Ses arabelleği", "En düşük (1024)", "Ses gecikmesini azaltır"),
    ("VSync", "Kapalı", "Kare beklemesini engeller, gecikmeyi düşürür"),
]


def check_direct_link() -> dict:
    """
    Doğrudan kablo bağlantısının durumunu denetler.
    Döner: {"adapter": str, "speed": str, "ip": str, "apipa": bool,
            "ps5_reachable": bool, "ok": bool, "notes": [str]}
    """
    info = {"adapter": "", "speed": "", "ip": "", "apipa": False,
            "ps5_reachable": False, "link_up": False, "ok": False, "notes": []}
    try:
        import subprocess
        ps = (
            "$a = Get-NetAdapter -Physical -ErrorAction SilentlyContinue | "
            "Where-Object {$_.InterfaceDescription -notmatch 'Wireless|Wi-Fi|802.11'} | "
            "Select-Object -First 1;"
            "if ($a) { $ip = (Get-NetIPAddress -InterfaceAlias $a.Name "
            "-AddressFamily IPv4 -ErrorAction SilentlyContinue | "
            "Select-Object -First 1).IPAddress;"
            "Write-Output ($a.Name + '|' + $a.LinkSpeed + '|' + $a.Status + '|' + $ip) }"
        )
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=15,
                             errors="ignore").stdout.strip()
        if out and "|" in out:
            parts = out.split("|")
            info["adapter"] = parts[0].strip()
            info["speed"] = parts[1].strip() if len(parts) > 1 else ""
            info["link_up"] = len(parts) > 2 and "Up" in parts[2]
            info["ip"] = parts[3].strip() if len(parts) > 3 else ""
            info["apipa"] = info["ip"].startswith("169.254.")

            if not info["link_up"]:
                info["notes"].append("Ethernet bağlantısı kapalı — kabloyu kontrol edin.")
            elif info["apipa"]:
                info["notes"].append(
                    "IP 169.254.x.x (APIPA) — PS5 doğrudan bağlı ama IP verilmemiş. "
                    "setup_ps5_direct.bat dosyasını yönetici olarak çalıştırın.")
            elif not info["ip"].startswith("192.168.100."):
                info["notes"].append(
                    f"IP {info['ip']} — önerilen 192.168.100.1. "
                    "Yine de çalışabilir; PS5 aynı alt ağda olmalı.")
            if "100 Mbps" in info["speed"]:
                info["notes"].append(
                    "Link 100 Mbps. Gigabit için GigaLite/Green Ethernet kapatılmalı "
                    "(script bunu yapar). 100 Mbps 1080p60 için yeterlidir.")

            # PS5 erişilebilir mi? (Remote Play portu 9295)
            if info["ip"] and not info["apipa"]:
                host = info["ip"].rsplit(".", 1)[0] + ".2"
            else:
                host = "192.168.100.2"     # APIPA iken önerilen hedef
            info["ps5_host"] = host
            info["ps5_reachable"] = _port_open(host, 9295, timeout=0.6)
            if not info["ps5_reachable"]:
                info["notes"].append(
                    f"{host}:9295 yanıt vermiyor. PS5 açık mı, Uzaktan Oynatma "
                    "etkin mi, PS5'te IP 192.168.100.2 mi?")

            info["ok"] = (not info["apipa"] and info["link_up"]
                          and info["ps5_reachable"])
    except Exception as e:
        info["notes"].append(f"Kontrol hatası: {str(e)[:100]}")
    return info

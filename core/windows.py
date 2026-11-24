"""
NEXUS AI — Windows Pencere Yardımcıları

İki kritik işlev:

1) `exclude_from_capture(hwnd)`
   Windows 10 2004+ "WDA_EXCLUDEFROMCAPTURE" bayrağı ile bir pencereyi
   EKRAN YAKALAMADAN gizler. Pencere ekranda görünür kalır ama OCR onu
   asla okumaz. HUD problemi (HUD'un kendi altyazısını okuması) bununla
   kökten çözülür — kapat/aç hilesine gerek yok.

2) `list_windows()` / `WindowSource`
   Açık pencereleri listeler ve seçilen pencerenin istemci alanını
   otomatik takip ederek yakalar (pencere taşınsa bile).
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys

IS_WIN = sys.platform == "win32"

# SetWindowDisplayAffinity
WDA_NONE = 0x00000000
WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011

# Pencere listeleme
GW_OWNER = 4
DWMWA_CLOAKED = 14


def exclude_from_capture(hwnd: int, enable: bool = True) -> bool:
    """
    Pencereyi ekran yakalamadan gizle (ekranda görünür kalır).
    Döner: başarılı mı.
    """
    if not IS_WIN or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        affinity = WDA_EXCLUDEFROMCAPTURE if enable else WDA_NONE
        return bool(user32.SetWindowDisplayAffinity(wt.HWND(hwnd), affinity))
    except Exception as e:
        print(f"[WIN] exclude_from_capture hatası: {e}")
        return False


def widget_hwnd(widget) -> int:
    """Qt widget'ının Win32 pencere tanıtıcısı."""
    try:
        return int(widget.winId())
    except Exception:
        return 0


def exclude_widget_from_capture(widget, enable: bool = True) -> bool:
    """Qt widget'ını yakalamadan gizle (winId oluşturur)."""
    return exclude_from_capture(widget_hwnd(widget), enable)


# --------------------------------------------------------------- pencereler
def process_name(pid: int) -> str:
    """PID → 'chrome.exe' gibi süreç adı (hata olursa '')."""
    if not IS_WIN or not pid:
        return ""
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            size = wt.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        pass
    return ""


def foreground_hwnd() -> int:
    """Şu an önde olan pencerenin tanıtıcısı."""
    if not IS_WIN:
        return 0
    try:
        return int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:
        return 0


def _is_cloaked(hwnd) -> bool:
    """UWP/sekme arkasında gizlenmiş pencereleri ayıklar."""
    try:
        dwmapi = ctypes.windll.dwmapi
        val = ctypes.c_int(0)
        res = dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), DWMWA_CLOAKED,
                                           ctypes.byref(val), ctypes.sizeof(val))
        return res == 0 and val.value != 0
    except Exception:
        return False


def list_windows(include_own=False) -> list:
    """
    Görünür, başlığı olan üst düzey pencereleri listeler.
    Döner: [{"hwnd": int, "title": str, "rect": (x, y, w, h), "pid": int}, ...]
    """
    if not IS_WIN:
        return []
    user32 = ctypes.windll.user32
    result = []

    own_pid = os.getpid()
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def callback(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            if user32.GetWindow(hwnd, GW_OWNER):        # sahip pencereleri atla
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if not title:
                return True
            if _is_cloaked(hwnd):
                return True

            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not include_own and pid.value == own_pid:
                return True

            rect = wt.RECT()
            if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
                return True
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w < 80 or h < 40:                       # çok küçükleri atla
                return True

            pt = wt.POINT(0, 0)
            user32.ClientToScreen(hwnd, ctypes.byref(pt))
            proc = process_name(int(pid.value))
            result.append({
                "hwnd": int(hwnd), "title": title,
                "rect": (pt.x, pt.y, w, h), "pid": int(pid.value),
                "proc": proc,
                "minimized": bool(user32.IsIconic(hwnd)),
                "foreground": bool(user32.GetForegroundWindow() == hwnd),
            })
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(EnumWindowsProc(callback), 0)
    except Exception as e:
        print(f"[WIN] list_windows hatası: {e}")
    return result


def window_client_rect(hwnd: int):
    """Pencerenin istemci alanının ekran koordinatları: (x, y, w, h) veya None."""
    if not IS_WIN or not hwnd:
        return None
    try:
        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            return None
        rect = wt.RECT()
        if not user32.GetClientRect(wt.HWND(hwnd), ctypes.byref(rect)):
            return None
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return None
        pt = wt.POINT(0, 0)
        user32.ClientToScreen(wt.HWND(hwnd), ctypes.byref(pt))
        return (pt.x, pt.y, w, h)
    except Exception:
        return None


GA_ROOT = 2
GW_HWNDPREV = 3
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
DWMWA_EXTENDED_FRAME_BOUNDS = 9


def _visible_frame_rect(user32, hwnd):
    """Pencerenin görünen çerçevesi (Win10/11'deki görünmez gölge kenarı hariç)."""
    r = wt.RECT()
    try:
        if ctypes.windll.dwmapi.DwmGetWindowAttribute(
                wt.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS,
                ctypes.byref(r), ctypes.sizeof(r)) == 0:
            return r.left, r.top, r.right, r.bottom
    except Exception:
        pass
    if user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(r)):
        return r.left, r.top, r.right, r.bottom
    return None


def occluding_rects(hwnd: int, region) -> list:
    """
    Hedef pencerenin ÜSTÜNDE duran ve `region` (x, y, w, h — ekran koordinatı) ile
    kesişen başka uygulama pencerelerinin kesişim dikdörtgenleri: [(x, y, w, h), ...].

    WindowSource ekran bölgesini yakaladığı için üste gelen pencerenin (Dosya Gezgini,
    tarayıcı...) yazıları da OCR'a giriyordu; bu dikdörtgenler karede maskelenir.
    Atlananlar: kendi sürecimiz (overlay/HUD zaten yakalamadan gizli), hedefin kendi
    süreci (açılır menüleri oyuna ait), görünmez / küçültülmüş / cloaked ve tıklama
    geçirgen (WS_EX_TRANSPARENT: NVIDIA/Discord gibi şeffaf overlay) pencereler.
    """
    if not IS_WIN or not hwnd or not region:
        return []
    try:
        user32 = ctypes.windll.user32
        user32.GetWindow.restype = wt.HWND
        user32.GetAncestor.restype = wt.HWND
        root = user32.GetAncestor(wt.HWND(hwnd), GA_ROOT) or wt.HWND(hwnd)
        own_pid = os.getpid()
        tpid = wt.DWORD()
        user32.GetWindowThreadProcessId(root, ctypes.byref(tpid))
        rx, ry, rw, rh = [int(v) for v in region]
        rx2, ry2 = rx + rw, ry + rh
        out = []
        h = user32.GetWindow(root, GW_HWNDPREV)
        guard = 0
        while h and guard < 512:
            guard += 1
            try:
                if (user32.IsWindowVisible(h) and not user32.IsIconic(h)
                        and not _is_cloaked(h)
                        and not (user32.GetWindowLongW(h, GWL_EXSTYLE) & WS_EX_TRANSPARENT)):
                    pid = wt.DWORD()
                    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                    if pid.value not in (own_pid, tpid.value):
                        fr = _visible_frame_rect(user32, h)
                        if fr:
                            x1, y1 = max(rx, fr[0]), max(ry, fr[1])
                            x2, y2 = min(rx2, fr[2]), min(ry2, fr[3])
                            if x2 > x1 and y2 > y1:
                                out.append((x1, y1, x2 - x1, y2 - y1))
            except Exception:
                pass
            h = user32.GetWindow(h, GW_HWNDPREV)
        return out
    except Exception:
        return []


def is_minimized(hwnd: int) -> bool:
    if not IS_WIN or not hwnd:
        return True
    try:
        return bool(ctypes.windll.user32.IsIconic(wt.HWND(hwnd)))
    except Exception:
        return True


def activate_window(hwnd: int) -> bool:
    """Pencereyi öne getir (odaklamadan)."""
    if not IS_WIN or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        if is_minimized(hwnd):
            user32.ShowWindow(wt.HWND(hwnd), 9)   # SW_RESTORE
        user32.SetForegroundWindow(wt.HWND(hwnd))
        return True
    except Exception:
        return False

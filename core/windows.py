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

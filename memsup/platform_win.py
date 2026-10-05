"""Minimal, dependency-free Win32 platform layer built on :mod:`ctypes`.

Everything the application needs from the operating system lives here:

* struct declarations (``MEMORYSTATUSEX``, ``PERFORMANCE_INFORMATION``, ...)
* user32 / gdi32 / kernel32 / dwmapi entry points with correct signatures
* acrylic ("frosted glass") backdrop activation
* a DirectWrite based text renderer that draws antialiased glyphs straight into
  a premultiplied 32-bit BGRA buffer (no GDI text, no transparency artefacts)
* always-on-top enforcement helpers

The module only imports from the standard library and performs no work at import
time beyond resolving DLL entry points.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import math
from ctypes import POINTER, WINFUNCTYPE, byref, c_int, c_size_t, c_ssize_t, c_uint, c_void_p

from . import constants as C

# --------------------------------------------------------------------------- #
#  Library handles
# --------------------------------------------------------------------------- #

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

try:
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
except OSError:  # pragma: no cover - dwmapi always exists on Win11
    dwmapi = None

try:
    shcore = ctypes.WinDLL("shcore", use_last_error=True)
except OSError:  # pragma: no cover
    shcore = None

# user32 may or may not export the undocumented composition helper.
_swca = getattr(user32, "SetWindowCompositionAttribute", None)

LRESULT = c_ssize_t
WPARAM = c_size_t
LPARAM = c_ssize_t
HGDIOBJ = c_void_p


# --------------------------------------------------------------------------- #
#  Structures
# --------------------------------------------------------------------------- #

class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wt.DWORD),
        ("dwMemoryLoad", wt.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("CommitTotal", c_size_t),
        ("CommitLimit", c_size_t),
        ("CommitPeak", c_size_t),
        ("PhysicalTotal", c_size_t),
        ("PhysicalAvailable", c_size_t),
        ("SystemCache", c_size_t),
        ("KernelTotal", c_size_t),
        ("KernelPaged", c_size_t),
        ("KernelNonpaged", c_size_t),
        ("PageSize", c_size_t),
        ("HandleCount", wt.DWORD),
        ("ProcessCount", wt.DWORD),
        ("ThreadCount", wt.DWORD),
    ]


class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("PageFaultCount", wt.DWORD),
        ("PeakWorkingSetSize", c_size_t),
        ("WorkingSetSize", c_size_t),
        ("QuotaPeakPagedPoolUsage", c_size_t),
        ("QuotaPagedPoolUsage", c_size_t),
        ("QuotaPeakNonPagedPoolUsage", c_size_t),
        ("QuotaNonPagedPoolUsage", c_size_t),
        ("PagefileUsage", c_size_t),
        ("PeakPagefileUsage", c_size_t),
        ("PrivateUsage", c_size_t),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wt.LONG), ("cy", wt.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wt.LONG),
        ("top", wt.LONG),
        ("right", wt.LONG),
        ("bottom", wt.LONG),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wt.HWND),
        ("message", c_uint),
        ("wParam", WPARAM),
        ("lParam", LPARAM),
        ("time", wt.DWORD),
        ("pt", POINT),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", c_uint),
        ("style", c_uint),
        ("lpfnWndProc", c_void_p),
        ("cbClsExtra", c_int),
        ("cbWndExtra", c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", c_void_p),
        ("hbrBackground", c_void_p),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
        ("hIconSm", wt.HICON),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD),
        ("biWidth", wt.LONG),
        ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", wt.BYTE),
        ("BlendFlags", wt.BYTE),
        ("SourceConstantAlpha", wt.BYTE),
        ("AlphaFormat", wt.BYTE),
    ]


class ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", c_uint),
        ("AccentFlags", c_uint),
        ("GradientColor", c_uint),
        ("AnimationId", c_uint),
    ]


class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", c_uint),
        ("Data", c_void_p),
        ("SizeOfData", c_size_t),
    ]


class LOGFONTW(ctypes.Structure):
    _fields_ = [
        ("lfHeight", wt.LONG),
        ("lfWidth", wt.LONG),
        ("lfEscapement", wt.LONG),
        ("lfOrientation", wt.LONG),
        ("lfWeight", wt.LONG),
        ("lfItalic", wt.BYTE),
        ("lfUnderline", wt.BYTE),
        ("lfStrikeOut", wt.BYTE),
        ("lfCharSet", wt.BYTE),
        ("lfOutPrecision", wt.BYTE),
        ("lfClipPrecision", wt.BYTE),
        ("lfQuality", wt.BYTE),
        ("lfPitchAndFamily", wt.BYTE),
        ("lfFaceName", wt.WCHAR * 32),
    ]


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("hwndTrack", wt.HWND),
        ("dwHoverTime", wt.DWORD),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wt.DWORD),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    """Shell notification-area icon (Windows 2000+ layout; cbSize first)."""
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("hWnd", wt.HWND),
        ("uID", c_uint),
        ("uFlags", c_uint),
        ("uCallbackMessage", c_uint),
        ("hIcon", wt.HICON),
        ("szTip", wt.WCHAR * 128),
        ("dwState", wt.DWORD),
        ("dwStateMask", wt.DWORD),
        ("szInfo", wt.WCHAR * 256),
        ("uVersion", c_uint),
        ("szInfoTitle", wt.WCHAR * 64),
        ("dwInfoFlags", wt.DWORD),
        ("guidItem", wt.BYTE * 16),
        ("hBalloonIcon", wt.HICON),
    ]


class DWM_BLURBEHIND(ctypes.Structure):
    _fields_ = [
        ("dwFlags", wt.DWORD),
        ("fEnable", wt.BOOL),
        ("hRgnBlur", c_void_p),
        ("fTransitionOnMaximized", wt.BOOL),
    ]


# --------------------------------------------------------------------------- #
#  Entry-point signatures
# --------------------------------------------------------------------------- #

def _declare() -> None:
    """Give every entry point an explicit prototype.

    This is not optional on win64: without a ``restype`` ctypes assumes C ``int``
    and silently truncates every pointer-sized handle (HDC, HWND, HMENU, ...) to
    32 bits, which then blows up inside the API call.
    """
    P = ctypes.POINTER
    LPVOID = c_void_p
    LPCWSTR = wt.LPCWSTR

    k = kernel32
    k.GlobalMemoryStatusEx.argtypes = [P(MEMORYSTATUSEX)]
    k.GlobalMemoryStatusEx.restype = wt.BOOL
    k.GetModuleHandleW.argtypes = [LPCWSTR]
    k.GetModuleHandleW.restype = wt.HMODULE
    k.GetCurrentProcess.argtypes = []
    k.GetCurrentProcess.restype = wt.HANDLE
    k.GetCurrentProcessId.argtypes = []
    k.GetCurrentProcessId.restype = wt.DWORD
    k.GetTickCount64.argtypes = []
    k.GetTickCount64.restype = ctypes.c_ulonglong
    k.QueryPerformanceCounter.argtypes = [P(ctypes.c_longlong)]
    k.QueryPerformanceCounter.restype = wt.BOOL
    k.QueryPerformanceFrequency.argtypes = [P(ctypes.c_longlong)]
    k.QueryPerformanceFrequency.restype = wt.BOOL
    k.CloseHandle.argtypes = [wt.HANDLE]
    k.CloseHandle.restype = wt.BOOL
    k.GetLastError.argtypes = []
    k.GetLastError.restype = wt.DWORD

    u = user32
    u.RegisterClassExW.argtypes = [P(WNDCLASSEXW)]
    u.RegisterClassExW.restype = wt.WORD
    u.UnregisterClassW.argtypes = [LPCWSTR, wt.HINSTANCE]
    u.UnregisterClassW.restype = wt.BOOL
    u.CreateWindowExW.argtypes = [
        wt.DWORD, LPCWSTR, LPCWSTR, wt.DWORD,
        c_int, c_int, c_int, c_int,
        wt.HWND, c_void_p, wt.HINSTANCE, LPVOID,
    ]
    u.CreateWindowExW.restype = wt.HWND
    u.DefWindowProcW.argtypes = [wt.HWND, c_uint, WPARAM, LPARAM]
    u.DefWindowProcW.restype = LRESULT
    u.DestroyWindow.argtypes = [wt.HWND]
    u.DestroyWindow.restype = wt.BOOL
    u.PostQuitMessage.argtypes = [c_int]
    u.PostQuitMessage.restype = None
    u.GetMessageW.argtypes = [P(MSG), wt.HWND, c_uint, c_uint]
    u.GetMessageW.restype = wt.BOOL
    u.PeekMessageW.argtypes = [P(MSG), wt.HWND, c_uint, c_uint, c_uint]
    u.PeekMessageW.restype = wt.BOOL
    u.TranslateMessage.argtypes = [P(MSG)]
    u.TranslateMessage.restype = wt.BOOL
    u.DispatchMessageW.argtypes = [P(MSG)]
    u.DispatchMessageW.restype = LRESULT
    u.PostMessageW.argtypes = [wt.HWND, c_uint, WPARAM, LPARAM]
    u.PostMessageW.restype = wt.BOOL
    u.SendMessageW.argtypes = [wt.HWND, c_uint, WPARAM, LPARAM]
    u.SendMessageW.restype = LRESULT
    u.SetTimer.argtypes = [wt.HWND, c_size_t, c_uint, c_void_p]
    u.SetTimer.restype = c_size_t
    u.KillTimer.argtypes = [wt.HWND, c_size_t]
    u.KillTimer.restype = wt.BOOL
    u.SetWindowPos.argtypes = [
        wt.HWND, wt.HWND, c_int, c_int, c_int, c_int, c_uint,
    ]
    u.SetWindowPos.restype = wt.BOOL
    u.GetWindowRect.argtypes = [wt.HWND, P(RECT)]
    u.GetWindowRect.restype = wt.BOOL
    u.GetClientRect.argtypes = [wt.HWND, P(RECT)]
    u.GetClientRect.restype = wt.BOOL
    u.UpdateLayeredWindow.argtypes = [
        wt.HWND, c_void_p, P(POINT), P(SIZE), c_void_p, P(POINT), wt.DWORD,
        P(BLENDFUNCTION), wt.DWORD,
    ]
    u.UpdateLayeredWindow.restype = wt.BOOL
    u.ShowWindow.argtypes = [wt.HWND, c_int]
    u.ShowWindow.restype = wt.BOOL
    u.IsWindowVisible.argtypes = [wt.HWND]
    u.IsWindowVisible.restype = wt.BOOL
    u.GetForegroundWindow.argtypes = []
    u.GetForegroundWindow.restype = wt.HWND
    u.SetForegroundWindow.argtypes = [wt.HWND]
    u.SetForegroundWindow.restype = wt.BOOL
    u.GetWindowThreadProcessId.argtypes = [wt.HWND, P(wt.DWORD)]
    u.GetWindowThreadProcessId.restype = wt.DWORD
    u.TrackMouseEvent.argtypes = [P(TRACKMOUSEEVENT)]
    u.TrackMouseEvent.restype = wt.BOOL
    u.LoadIconW.argtypes = [wt.HINSTANCE, LPCWSTR]
    u.LoadIconW.restype = wt.HICON
    u.LoadCursorW.argtypes = [wt.HINSTANCE, LPCWSTR]
    u.LoadCursorW.restype = c_void_p
    u.SetCursor.argtypes = [c_void_p]
    u.SetCursor.restype = c_void_p
    u.CreatePopupMenu.argtypes = []
    u.CreatePopupMenu.restype = c_void_p
    u.DestroyMenu.argtypes = [c_void_p]
    u.DestroyMenu.restype = wt.BOOL
    u.AppendMenuW.argtypes = [c_void_p, c_uint, c_size_t, LPCWSTR]
    u.AppendMenuW.restype = wt.BOOL
    u.TrackPopupMenuEx.argtypes = [
        c_void_p, c_uint, c_int, c_int, wt.HWND, c_void_p,
    ]
    u.TrackPopupMenuEx.restype = wt.BOOL
    u.TrackPopupMenu.argtypes = [
        c_void_p, c_uint, c_int, c_int, c_int, wt.HWND, c_void_p,
    ]
    u.TrackPopupMenu.restype = c_int
    u.SetWindowCompositionAttribute  # noqa: B018 - presence probe only
    if _swca is not None:
        _swca.argtypes = [wt.HWND, P(WINDOWCOMPOSITIONATTRIBDATA)]
        _swca.restype = wt.BOOL
    u.SystemParametersInfoW.argtypes = [c_uint, c_uint, c_void_p, c_uint]
    u.SystemParametersInfoW.restype = wt.BOOL
    u.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
    u.MonitorFromWindow.restype = c_void_p
    u.MonitorFromPoint.argtypes = [POINT, wt.DWORD]
    u.MonitorFromPoint.restype = c_void_p
    u.GetMonitorInfoW.argtypes = [c_void_p, P(MONITORINFO)]
    u.GetMonitorInfoW.restype = wt.BOOL
    u.GetSystemMetrics.argtypes = [c_int]
    u.GetSystemMetrics.restype = c_int
    u.SetWindowLongPtrW.argtypes = [wt.HWND, c_int, LRESULT]
    u.SetWindowLongPtrW.restype = LRESULT
    u.IsWindow.argtypes = [wt.HWND]
    u.IsWindow.restype = wt.BOOL
    u.MessageBoxW.argtypes = [wt.HWND, LPCWSTR, LPCWSTR, c_uint]
    u.MessageBoxW.restype = c_int
    u.SetProcessDpiAwarenessContext.argtypes = [c_void_p]
    u.SetProcessDpiAwarenessContext.restype = wt.BOOL
    u.SetWinEventHook.argtypes = [
        wt.DWORD, wt.DWORD, wt.HMODULE, c_void_p, wt.DWORD, wt.DWORD, wt.DWORD,
    ]
    u.SetWinEventHook.restype = c_void_p
    u.UnhookWinEvent.argtypes = [c_void_p]
    u.UnhookWinEvent.restype = wt.BOOL
    u.GetCursorPos.argtypes = [P(POINT)]
    u.GetCursorPos.restype = wt.BOOL
    u.InvalidateRect.argtypes = [wt.HWND, P(RECT), wt.BOOL]
    u.InvalidateRect.restype = wt.BOOL
    u.GetDC.argtypes = [wt.HWND]
    u.GetDC.restype = c_void_p
    u.ReleaseDC.argtypes = [wt.HWND, c_void_p]
    u.ReleaseDC.restype = c_int
    u.GetDesktopWindow.argtypes = []
    u.GetDesktopWindow.restype = wt.HWND
    u.ScreenToClient.argtypes = [wt.HWND, P(POINT)]
    u.ScreenToClient.restype = wt.BOOL
    u.ClientToScreen.argtypes = [wt.HWND, P(POINT)]
    u.ClientToScreen.restype = wt.BOOL
    u.GetKeyState.argtypes = [c_int]
    u.GetKeyState.restype = ctypes.c_short
    u.GetAsyncKeyState.argtypes = [c_int]
    u.GetAsyncKeyState.restype = ctypes.c_short
    u.SetCapture.argtypes = [wt.HWND]
    u.SetCapture.restype = wt.HWND
    u.ReleaseCapture.argtypes = []
    u.ReleaseCapture.restype = wt.BOOL
    u.RegisterHotKey.argtypes = [wt.HWND, c_int, wt.UINT, wt.UINT]
    u.RegisterHotKey.restype = wt.BOOL
    u.UnregisterHotKey.argtypes = [wt.HWND, c_int]
    u.UnregisterHotKey.restype = wt.BOOL
    u.SetWindowTextW.argtypes = [wt.HWND, LPCWSTR]
    u.SetWindowTextW.restype = wt.BOOL
    u.IsIconic.argtypes = [wt.HWND]
    u.IsIconic.restype = wt.BOOL
    u.GetWindowLongPtrW.argtypes = [wt.HWND, c_int]
    u.GetWindowLongPtrW.restype = LRESULT
    u.LoadImageW.argtypes = [wt.HINSTANCE, LPCWSTR, wt.UINT, c_int, c_int, wt.UINT]
    u.LoadImageW.restype = c_void_p

    g = gdi32
    g.CreateCompatibleDC.argtypes = [c_void_p]
    g.CreateCompatibleDC.restype = c_void_p
    g.DeleteDC.argtypes = [c_void_p]
    g.DeleteDC.restype = wt.BOOL
    g.CreateBitmap.argtypes = [c_int, c_int, wt.UINT, wt.UINT, c_void_p]
    g.CreateBitmap.restype = c_void_p
    g.CreateCompatibleBitmap.argtypes = [c_void_p, c_int, c_int]
    g.CreateCompatibleBitmap.restype = c_void_p
    g.CreateDIBSection.argtypes = [
        c_void_p, P(BITMAPINFO), wt.UINT, P(c_void_p), wt.HANDLE, wt.DWORD,
    ]
    g.CreateDIBSection.restype = c_void_p
    g.SelectObject.argtypes = [c_void_p, HGDIOBJ]
    g.SelectObject.restype = HGDIOBJ
    g.DeleteObject.argtypes = [HGDIOBJ]
    g.DeleteObject.restype = wt.BOOL
    g.CreateFontIndirectW.argtypes = [P(LOGFONTW)]
    g.CreateFontIndirectW.restype = c_void_p
    g.CreateSolidBrush.argtypes = [wt.DWORD]
    g.CreateSolidBrush.restype = c_void_p
    g.CreatePen.argtypes = [c_int, c_int, wt.DWORD]
    g.CreatePen.restype = c_void_p
    g.GetStockObject.argtypes = [c_int]
    g.GetStockObject.restype = c_void_p
    g.Rectangle.argtypes = [c_void_p, c_int, c_int, c_int, c_int]
    g.Rectangle.restype = wt.BOOL
    g.MoveToEx.argtypes = [c_void_p, c_int, c_int, c_void_p]
    g.MoveToEx.restype = wt.BOOL
    g.LineTo.argtypes = [c_void_p, c_int, c_int]
    g.LineTo.restype = wt.BOOL
    g.PatBlt.argtypes = [c_void_p, c_int, c_int, c_int, c_int, wt.DWORD]
    g.PatBlt.restype = wt.BOOL

    u.TrackPopupMenu.argtypes = [
        c_void_p, c_uint, c_int, c_int, c_int, wt.HWND, c_void_p,
    ]
    u.TrackPopupMenu.restype = c_int
    u.AppendMenuW.argtypes = [c_void_p, c_uint, c_size_t, LPCWSTR]
    u.AppendMenuW.restype = wt.BOOL
    u.CreatePopupMenu.argtypes = []
    u.CreatePopupMenu.restype = c_void_p
    u.DestroyMenu.argtypes = [c_void_p]
    u.DestroyMenu.restype = wt.BOOL
    u.DestroyIcon.argtypes = [wt.HICON]
    u.DestroyIcon.restype = wt.BOOL
    u.LoadImageW.argtypes = [wt.HINSTANCE, LPCWSTR, wt.UINT, c_int, c_int, wt.UINT]
    u.LoadImageW.restype = c_void_p
    u.CreateIconIndirect.argtypes = [c_void_p]
    u.CreateIconIndirect.restype = wt.HICON
    u.CopyImage.argtypes = [c_void_p, wt.UINT, c_int, c_int, wt.UINT]
    u.CopyImage.restype = c_void_p
    u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, c_int, c_int, c_int, c_int, c_uint]
    u.SetWindowPos.restype = wt.BOOL
    u.IsWindowVisible.argtypes = [wt.HWND]
    u.IsWindowVisible.restype = wt.BOOL
    u.ShowWindow.argtypes = [wt.HWND, c_int]
    u.ShowWindow.restype = wt.BOOL
    u.PostMessageW.argtypes = [wt.HWND, c_uint, WPARAM, LPARAM]
    u.PostMessageW.restype = wt.BOOL
    u.GetCursorPos.argtypes = [P(POINT)]
    u.GetCursorPos.restype = wt.BOOL
    u.SetForegroundWindow.argtypes = [wt.HWND]
    u.SetForegroundWindow.restype = wt.BOOL
    u.RegisterWindowMessageW.argtypes = [LPCWSTR]
    u.RegisterWindowMessageW.restype = c_uint

    if dwmapi is not None:
        dwmapi.DwmSetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, c_void_p, wt.DWORD]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
        dwmapi.DwmExtendFrameIntoClientArea.argtypes = [wt.HWND, c_void_p]
        dwmapi.DwmExtendFrameIntoClientArea.restype = ctypes.c_long
        dwmapi.DwmIsCompositionEnabled.argtypes = [P(wt.BOOL)]
        dwmapi.DwmIsCompositionEnabled.restype = ctypes.c_long
        dwmapi.DwmFlush.argtypes = []
        dwmapi.DwmFlush.restype = ctypes.c_long

    if shcore is not None:
        shcore.GetDpiForMonitor.argtypes = [
            c_void_p, c_int, P(c_uint), P(c_uint),
        ]
        shcore.GetDpiForMonitor.restype = ctypes.c_long


_declare()


try:
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    _shell32.Shell_NotifyIconGetRect.argtypes = [c_void_p, c_void_p]
    _shell32.Shell_NotifyIconGetRect.restype = ctypes.c_long
except OSError:                                               # pragma: no cover
    _shell32 = None


def tray_icon_rect(hwnd, uid: int = 1, guid_bytes: bytes | None = None):
    """Rectangle of a notification-area icon, or ``None`` when not registered.

    The identifier must match the one the icon was added with: when the icon was
    registered through ``NIF_GUID`` the lookup has to carry the same GUID,
    otherwise the shell reports "not found" even though the icon is there.
    """
    if _shell32 is None:
        return None

    class NOTIFYICONIDENTIFIER(ctypes.Structure):
        _fields_ = [
            ("cbSize", wt.DWORD),
            ("hWnd", wt.HWND),
            ("uID", c_uint),
            ("guidItem", wt.BYTE * 16),
        ]

    ident = NOTIFYICONIDENTIFIER()
    ident.cbSize = ctypes.sizeof(NOTIFYICONIDENTIFIER)
    ident.hWnd = hwnd
    ident.uID = uid
    if guid_bytes and len(guid_bytes) == 16:
        for i, byte in enumerate(guid_bytes):
            ident.guidItem[i] = byte
    rect = RECT()
    if _shell32.Shell_NotifyIconGetRect(ctypes.byref(ident),
                                        ctypes.byref(rect)) == 0:
        return rect
    return None


def _optional(name: str):
    """Return an entry point that may be missing on this build, else ``None``."""
    return getattr(user32, name, None)


_set_window_band = _optional("SetWindowBand")


# --------------------------------------------------------------------------- #
#  Small helpers
# --------------------------------------------------------------------------- #

def get_last_error() -> int:
    return ctypes.get_last_error()


def error_message(code: int) -> str:
    try:
        return ctypes.FormatError(code).strip()
    except Exception:  # pragma: no cover
        return f"error {code}"


def loword(value: int) -> int:
    return value & 0xFFFF


def hiword(value: int) -> int:
    return (value >> 16) & 0xFFFF


def signed_word(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def set_dpi_awareness() -> None:
    """Opt into per-monitor-v2 DPI awareness so the panel stays pixel crisp."""
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == -4
        if user32.SetProcessDpiAwarenessContext(c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        if shcore is not None:
            shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def get_dpi_for_window(hwnd) -> int:
    """DPI of the monitor a window is on (96 when it cannot be determined)."""
    # GetDpiForWindow is the correct per-window answer and needs no monitor handle
    get_for_window = getattr(user32, "GetDpiForWindow", None)
    if get_for_window is not None:
        try:
            get_for_window.argtypes = [wt.HWND]
            get_for_window.restype = c_uint
            dpi = int(get_for_window(hwnd))
            if 72 <= dpi <= 480:
                return dpi
        except Exception:
            pass

    monitor = user32.MonitorFromWindow(hwnd, C.MONITOR_DEFAULTTONEAREST)
    if shcore is not None and monitor:
        x, y = c_uint(0), c_uint(0)
        try:
            if shcore.GetDpiForMonitor(monitor, 0, byref(x), byref(y)) == 0:
                dpi = int(x.value)
                if 72 <= dpi <= 480:
                    return dpi
        except Exception:
            pass
    return 96


def get_work_area(x: int = 0, y: int = 0) -> RECT:
    pt = POINT(x, y)
    monitor = user32.MonitorFromPoint(pt, C.MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if monitor and user32.GetMonitorInfoW(monitor, byref(info)):
        return info.rcWork
    rect = RECT()
    rect.left, rect.top = 0, 0
    rect.right = user32.GetSystemMetrics(0)
    rect.bottom = user32.GetSystemMetrics(1)
    return rect


def get_window_process_id(hwnd) -> int:
    pid = wt.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, byref(pid))
    return int(pid.value)


def process_working_set_bytes() -> int:
    counters = PROCESS_MEMORY_COUNTERS_EX()
    counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
    try:
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        fn = psapi.GetProcessMemoryInfo
        fn.argtypes = [wt.HANDLE, c_void_p, wt.DWORD]
        fn.restype = wt.BOOL
        if fn(kernel32.GetCurrentProcess(), byref(counters), counters.cb):
            return int(counters.WorkingSetSize)
    except Exception:
        pass
    return 0


def query_performance_info() -> PERFORMANCE_INFORMATION | None:
    info = PERFORMANCE_INFORMATION()
    info.cb = ctypes.sizeof(PERFORMANCE_INFORMATION)
    try:
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        fn = psapi.GetPerformanceInfo
        fn.argtypes = [c_void_p, wt.DWORD]
        fn.restype = wt.BOOL
        if fn(byref(info), info.cb):
            return info
    except Exception:
        pass
    return None


def query_memory_status() -> MEMORYSTATUSEX | None:
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if kernel32.GlobalMemoryStatusEx(byref(status)):
        return status
    return None


# --------------------------------------------------------------------------- #
#  Always-on-top enforcement
#
#  ``SetWindowPos(HWND_TOPMOST)`` alone is not enough when a maximised or
#  borderless-fullscreen window takes the foreground: such windows are pushed to
#  the top of the *non-topmost* band, and DWM may still hand them the foreground
#  slot.  Re-asserting the topmost band and the composition band right after the
#  foreground changes keeps our panel visible in every normal case.  (A true
#  exclusive-fullscreen DirectX swap chain can only be covered by a UIAccess,
#  code-signed binary - that is an OS restriction.)
# --------------------------------------------------------------------------- #

def raise_topmost(hwnd, *, show: bool = False, activate: bool = False) -> bool:
    flags = (
        C.SWP_NOMOVE
        | C.SWP_NOSIZE
        | C.SWP_NOOWNERZORDER
        | C.SWP_NOSENDCHANGING
        | C.SWP_ASYNCWINDOWPOS
    )
    if not activate:
        flags |= C.SWP_NOACTIVATE
    if show:
        flags |= C.SWP_SHOWWINDOW
    ok = bool(user32.SetWindowPos(hwnd, wt.HWND(C.HWND_TOPMOST), 0, 0, 0, 0, flags))
    if not ok:
        ok = bool(user32.SetWindowPos(hwnd, wt.HWND(C.HWND_TOPMOST), 0, 0, 0, 0, flags & ~C.SWP_ASYNCWINDOWPOS))
    if _set_window_band is not None:
        try:
            _set_window_band(hwnd, c_void_p(0), c_void_p(0), c_uint(2))  # ZBID_UIACCESS
        except Exception:
            pass
    return ok


# --------------------------------------------------------------------------- #
#  Acrylic backdrop
# --------------------------------------------------------------------------- #

def _try_system_backdrop(hwnd, backdrop: int) -> bool:
    if dwmapi is None:
        return False
    value = c_int(backdrop)
    try:
        hr = dwmapi.DwmSetWindowAttribute(
            hwnd, C.DWMWA_SYSTEMBACKDROP_TYPE, byref(value), ctypes.sizeof(value)
        )
        return hr == 0
    except Exception:
        return False


def _apply_accent(hwnd, state: int, tint_rgba: int, flags: int) -> bool:
    """Set one ACCENT_POLICY through the undocumented composition attribute."""
    if _swca is None:
        return False
    accent = ACCENT_POLICY()
    accent.AccentState = state
    accent.AccentFlags = flags
    accent.GradientColor = tint_rgba
    accent.AnimationId = 0
    data = WINDOWCOMPOSITIONATTRIBDATA()
    data.Attribute = C.WCA_ACCENT_POLICY
    data.Data = ctypes.cast(byref(accent), c_void_p)
    data.SizeOfData = ctypes.sizeof(accent)
    try:
        return bool(_swca(hwnd, byref(data)))
    except Exception:
        return False


def _try_accent_acrylic(hwnd, tint_rgba: int) -> bool:
    """Windows 10/11 composition-attribute acrylic (AABBGGRR gradient color)."""
    return _apply_accent(hwnd, C.ACCENT_ENABLE_ACRYLICBLURBEHIND, tint_rgba,
                         0x20 | 0x40 | 0x80 | 0x100)


def _try_accent_blur(hwnd, tint_rgba: int) -> bool:
    """Gaussian blur behind the window (noise-free acrylic)."""
    return _apply_accent(hwnd, C.ACCENT_ENABLE_BLURBEHIND, tint_rgba,
                         0x20 | 0x40 | 0x80 | 0x100)


def enable_acrylic(hwnd, *, tint_alpha: int = 0x99, tint_bgr: int = 0x1E140E,
                   mechanism: str = "auto") -> str:
    """Turn on the frosted-glass backdrop.

    IMPORTANT, measured on Windows 11 25H2: ``DwmSetWindowAttribute`` with
    ``DWMWA_SYSTEMBACKDROP_TYPE`` *succeeds* on a ``WS_EX_LAYERED`` window (and
    even reads back as 3 = acrylic) but nothing is ever composited - the panel
    renders as a flat dark rectangle.  Only the composition-attribute accent
    actually blurs what is behind a layered surface, so that is what this uses;
    the DWM attribute is still set because it costs nothing and some builds may
    honour it.

    Returns a label describing the mechanism that was used.
    """
    if dwmapi is not None:
        try:
            dark = c_int(1)
            dwmapi.DwmSetWindowAttribute(
                hwnd, C.DWMWA_USE_IMMERSIVE_DARK_MODE, byref(dark), ctypes.sizeof(dark)
            )
            corner = c_int(C.DWMWCP_ROUND)
            dwmapi.DwmSetWindowAttribute(
                hwnd, C.DWMWA_WINDOW_CORNER_PREFERENCE, byref(corner), ctypes.sizeof(corner)
            )
        except Exception:
            pass

    tint = (tint_alpha << 24) | tint_bgr
    if mechanism in ("auto", "blur"):
        if _try_accent_blur(hwnd, tint):
            _try_system_backdrop(hwnd, C.DWMSBT_TRANSIENTWINDOW)
            return "blur"
    if mechanism in ("auto", "acrylic"):
        if _try_accent_acrylic(hwnd, tint):
            _try_system_backdrop(hwnd, C.DWMSBT_TRANSIENTWINDOW)
            return "acrylic"
    if _try_system_backdrop(hwnd, C.DWMSBT_TRANSIENTWINDOW):
        return "dwm-acrylic"
    if _try_system_backdrop(hwnd, C.DWMSBT_MAINWINDOW):
        return "mica"
    return "none"


def disable_backdrop(hwnd) -> None:
    if _try_system_backdrop(hwnd, C.DWMSBT_NONE):
        pass
    if _swca is not None:
        _apply_accent(hwnd, C.ACCENT_DISABLED, 0, 0)


def set_window_band(hwnd, band: int) -> bool:
    """Put the window in a higher composition band (0 topmost .. 4 app)."""
    if _set_window_band is None:
        return False
    try:
        return bool(_set_window_band(hwnd, c_void_p(0), c_void_p(0), c_uint(band)))
    except Exception:
        return False


# --------------------------------------------------------------------------- #
#  Layered-window blitting
# --------------------------------------------------------------------------- #

_blend = BLENDFUNCTION(C.AC_SRC_OVER, 0, 255, C.AC_SRC_ALPHA)


def push_layered(hwnd, mem_dc, x: int, y: int, w: int, h: int) -> bool:
    """Upload a premultiplied BGRA buffer through ``UpdateLayeredWindow``."""
    dst = POINT(x, y)
    size = SIZE(w, h)
    src = POINT(0, 0)
    return bool(
        user32.UpdateLayeredWindow(
            hwnd,
            None,
            byref(dst),
            byref(size),
            mem_dc,
            byref(src),
            0,
            byref(_blend),
            C.ULW_ALPHA,
        )
    )


class PixelBuffer:
    """A 32-bit top-down BGRA DIB section plus its memory DC."""

    __slots__ = ("width", "height", "dc", "bitmap", "old_bitmap", "_bits", "_buf")

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height  # negative => top-down rows
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = C.BI_RGB
        bits = c_void_p()
        self.dc = gdi32.CreateCompatibleDC(None)
        self.bitmap = gdi32.CreateDIBSection(
            self.dc, byref(info), C.DIB_RGB_COLORS, byref(bits), None, 0
        )
        if not self.bitmap or not bits:
            raise OSError(f"CreateDIBSection failed ({error_message(get_last_error())})")
        self.old_bitmap = gdi32.SelectObject(self.dc, self.bitmap)
        self._bits = bits
        self._buf = (ctypes.c_ubyte * (width * height * 4)).from_address(bits.value)

    @property
    def buf(self):
        return self._buf

    def clear(self, color: tuple[int, int, int, int] = (0, 0, 0, 0)) -> None:
        """Fill the whole surface with one premultiplied BGRA colour."""
        px = bytes(color)
        self._buf[:] = px * (self.width * self.height)

    def destroy(self) -> None:
        try:
            if self.dc and self.old_bitmap:
                gdi32.SelectObject(self.dc, self.old_bitmap)
            if self.bitmap:
                gdi32.DeleteObject(self.bitmap)
            if self.dc:
                gdi32.DeleteDC(self.dc)
        finally:
            self.dc = self.bitmap = self.old_bitmap = None


# --------------------------------------------------------------------------- #
#  Message plumbing
# --------------------------------------------------------------------------- #

WNDPROC = WINFUNCTYPE(LRESULT, wt.HWND, c_uint, WPARAM, LPARAM)
WINEVENTPROC = WINFUNCTYPE(
    None, c_void_p, wt.DWORD, wt.HWND, wt.LONG, wt.LONG, wt.DWORD, wt.DWORD
)

_wndproc_refs: dict[str, object] = {}


def make_wndproc(callback) -> WNDPROC:
    proc = WNDPROC(callback)
    _wndproc_refs["wndproc"] = proc  # keep alive for the process lifetime
    return proc


def make_wineventproc(callback) -> WINEVENTPROC:
    proc = WINEVENTPROC(callback)
    _wndproc_refs["wineventproc"] = proc
    return proc


def register_window_class(name: str, wndproc_ptr, *, instance=None, cursor: bool = False) -> int:
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.style = 0
    wc.lpfnWndProc = ctypes.cast(wndproc_ptr, c_void_p)
    wc.cbClsExtra = 0
    wc.cbWndExtra = 0
    wc.hInstance = instance if instance is not None else kernel32.GetModuleHandleW(None)
    wc.hIcon = None
    wc.hCursor = user32.LoadCursorW(None, wt.LPCWSTR(32512)) if cursor else None  # IDC_ARROW
    wc.hbrBackground = None
    wc.lpszMenuName = None
    wc.lpszClassName = name
    wc.hIconSm = None
    atom = user32.RegisterClassExW(byref(wc))
    if not atom:
        err = get_last_error()
        if err != 1410:  # ERROR_CLASS_ALREADY_EXISTS
            raise OSError(f"RegisterClassExW failed ({error_message(err)})")
    return atom


def create_layered_popup(name: str, title: str, *, width: int, height: int,
                         x: int, y: int, instance=None, no_activate: bool = True,
                         tool_window: bool = True, app_window: bool = False,
                         icon: int | None = None):
    """Create the transparent, always-on-top panel window.

    ``tool_window`` keeps it out of Alt-Tab; ``app_window`` gives it a taskbar
    button instead (the two flags are mutually exclusive in Windows, so callers
    pick one).
    """
    style = C.WS_POPUP
    ex_style = C.WS_EX_LAYERED | C.WS_EX_TOPMOST
    if tool_window:
        ex_style |= C.WS_EX_TOOLWINDOW
    if app_window:
        ex_style |= C.WS_EX_APPWINDOW
    if no_activate:
        ex_style |= C.WS_EX_NOACTIVATE
    hwnd = user32.CreateWindowExW(
        ex_style,
        name,
        title,
        style,
        x,
        y,
        width,
        height,
        None,
        None,
        instance if instance is not None else kernel32.GetModuleHandleW(None),
        None,
    )
    if not hwnd:
        raise OSError(f"CreateWindowExW failed ({error_message(get_last_error())})")
    if icon:
        send_message(hwnd, C.WM_SETICON, 1, icon)      # ICON_BIG
        send_message(hwnd, C.WM_SETICON, 0, icon)      # ICON_SMALL
    return hwnd


def send_message(hwnd, message: int, wparam: int = 0, lparam: int = 0) -> int:
    return int(user32.SendMessageW(hwnd, message, WPARAM(wparam), LPARAM(lparam)))


def window_icon(instance=None):
    """The executable's own icon, for the taskbar button."""
    try:
        return user32.LoadIconW(
            instance if instance is not None else kernel32.GetModuleHandleW(None),
            wt.LPCWSTR(32512),                         # IDI_APPLICATION fallback
        )
    except Exception:
        return None



# --------------------------------------------------------------------------- #
#  Text engine (GDI masks, composited on the CPU)
#
#  Text is rasterised by GDI into a private black 32-bit mask surface and the
#  resulting per-pixel coverage is blended manually into the target BGRA buffer.
#  Doing the blend ourselves is what makes antialiased text work over an acrylic
#  backdrop: GDI's own blending would paint an opaque background behind every
#  glyph, while here only the glyph coverage reaches the surface.
# --------------------------------------------------------------------------- #

# DrawTextW flags
DT_LEFT = 0x00000000
DT_TOP = 0x00000000
DT_CENTER = 0x00000001
DT_RIGHT = 0x00000002
DT_SINGLELINE = 0x00000020
DT_NOCLIP = 0x00000100
DT_NOPREFIX = 0x00000800
DT_END_ELLIPSIS = 0x00008000

_text_declared = False


def make_logfont(height: int, weight: int, face_name: str,
                 *, quality: int = C.ANTIALIASED_QUALITY) -> LOGFONTW:
    """Build a LOGFONTW for a pixel height, weight and family name."""
    lf = LOGFONTW()
    lf.lfHeight = -abs(int(height))
    lf.lfWidth = 0
    lf.lfWeight = int(weight)
    lf.lfCharSet = C.DEFAULT_CHARSET
    lf.lfQuality = quality
    lf.lfFaceName = face_name[:31]
    return lf


def _declare_text() -> None:
    global _text_declared
    if _text_declared:
        return
    P = ctypes.POINTER
    g = gdi32
    g.SetBkMode.argtypes = [c_void_p, c_int]
    g.SetBkMode.restype = c_int
    g.SetTextColor.argtypes = [c_void_p, wt.COLORREF]
    g.SetTextColor.restype = wt.COLORREF
    g.GetTextExtentPoint32W.argtypes = [c_void_p, wt.LPCWSTR, c_int, P(SIZE)]
    g.GetTextExtentPoint32W.restype = wt.BOOL
    user32.DrawTextW.argtypes = [c_void_p, wt.LPCWSTR, c_int, P(RECT), c_uint]
    user32.DrawTextW.restype = c_int
    _text_declared = True


_declare_text()


class FontSpec:
    """Value object describing one font; doubles as the engine's cache key."""

    __slots__ = ("family", "size", "weight", "italic")

    def __init__(self, family: str, size: float, weight: int = 400,
                 italic: bool = False) -> None:
        self.family = family
        self.size = float(size)
        self.weight = int(weight)
        self.italic = bool(italic)

    def key(self) -> tuple:
        return (self.family, round(self.size, 2), self.weight, self.italic)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"FontSpec({self.family!r}, {self.size}, {self.weight})"


class _Font:
    __slots__ = ("handle",)

    def __init__(self, handle) -> None:
        self.handle = handle

    def destroy(self) -> None:
        if self.handle:
            gdi32.DeleteObject(self.handle)
            self.handle = None


class TextEngine:
    """Rasterises text with GDI and composites it into a :class:`PixelBuffer`."""

    def __init__(self, mask_w: int = 1600, mask_h: int = 120) -> None:
        self._fonts: dict[tuple, _Font] = {}
        self._mask: PixelBuffer | None = None
        self._target: PixelBuffer | None = None
        self.dpi_scale = 1.0

    # -- resources --------------------------------------------------------- #
    def _ensure_mask(self, width: int, height: int) -> PixelBuffer:
        cur = self._mask
        if cur is None or cur.width < width or cur.height < height:
            if cur is not None:
                cur.destroy()
            self._mask = PixelBuffer(max(width, 128), max(height, 48))
        return self._mask

    def font(self, spec: FontSpec) -> _Font:
        key = spec.key()
        entry = self._fonts.get(key)
        if entry is None:
            lf = make_logfont(
                max(1, int(round(spec.size * self.dpi_scale))),
                spec.weight,
                spec.family,
                quality=C.ANTIALIASED_QUALITY,
            )
            lf.lfItalic = 1 if spec.italic else 0
            handle = gdi32.CreateFontIndirectW(ctypes.byref(lf))
            if not handle:
                raise OSError(f"CreateFontIndirectW failed for {spec.family!r}")
            entry = _Font(handle)
            self._fonts[key] = entry
        return entry

    def set_dpi_scale(self, scale: float) -> None:
        """Changing the scale invalidates every cached font."""
        if abs(scale - self.dpi_scale) > 1e-6:
            self.dpi_scale = float(scale)
            for font in self._fonts.values():
                font.destroy()
            self._fonts.clear()

    # -- frame lifecycle --------------------------------------------------- #
    def begin_frame(self, target: PixelBuffer, dpi_scale: float = 1.0) -> None:
        self.set_dpi_scale(dpi_scale)
        self._target = target

    def end_frame(self) -> None:
        self._target = None

    # -- text -------------------------------------------------------------- #
    def measure(self, text: str, spec: FontSpec) -> tuple[int, int]:
        """Return the pixel size the text will occupy."""
        if not text:
            return (0, 0)
        font = self.font(spec)
        mask = self._ensure_mask(16, 16)
        size = SIZE()
        old = gdi32.SelectObject(mask.dc, font.handle)
        try:
            if not gdi32.GetTextExtentPoint32W(mask.dc, text, len(text),
                                               ctypes.byref(size)):
                return (0, 0)
        finally:
            gdi32.SelectObject(mask.dc, old)
        return (int(size.cx), int(size.cy))

    def draw_text(self, x: int, y: int, text: str, spec: FontSpec, color: int,
                  opacity: float = 1.0, *, align: str = "left",
                  box_width: int | None = None, ellipsis: bool = False) -> int:
        """Composite ``text`` at (x, y); returns the drawn width in pixels.

        ``color`` is a 0xBBGGRR value (COLORREF order).  ``x`` is the left edge for
        ``align='left'``, the centre for ``'center'`` and the right edge for
        ``'right'``.
        """
        target = self._target
        if target is None or not text:
            return 0

        font = self.font(spec)
        natural_w, natural_h = self.measure(text, spec)
        if natural_w <= 0:
            return 0

        pad = 4
        box_w = natural_w + pad * 2
        if box_width is not None:
            box_w = max(box_w, int(box_width))
        box_h = natural_h + pad * 2

        mask = self._ensure_mask(box_w + 8, box_h + 8)
        mask.clear((0, 0, 0, 255))  # opaque black == zero coverage

        dc = mask.dc
        old_font = gdi32.SelectObject(dc, font.handle)
        old_mode = gdi32.SetBkMode(dc, C.TRANSPARENT)
        old_color = gdi32.SetTextColor(dc, wt.COLORREF(0x00FFFFFF))
        rect = RECT(pad, pad, box_w - pad, box_h - pad)
        flags = DT_TOP | DT_LEFT | DT_NOPREFIX | DT_NOCLIP
        if ellipsis:
            flags |= DT_END_ELLIPSIS
        try:
            if user32.DrawTextW(dc, text, len(text), ctypes.byref(rect), flags) <= 0:
                return 0
        finally:
            gdi32.SetTextColor(dc, old_color)
            gdi32.SetBkMode(dc, old_mode)
            gdi32.SelectObject(dc, old_font)

        if align == "center":
            dst_x = int(x - natural_w / 2)
        elif align == "right":
            dst_x = int(x - natural_w)
        else:
            dst_x = int(x)
        dst_y = int(y)

        # ClearType/GDI antialiasing wrote white with varying intensity; the
        # intensity of any channel is the glyph coverage at that pixel.
        self._blend_mask(mask, pad, pad, dst_x, dst_y, natural_w, natural_h,
                         color, opacity)
        return natural_w

    # -- compositing ------------------------------------------------------- #
    def _blend_mask(self, mask: PixelBuffer, src_x: int, src_y: int,
                    dst_x: int, dst_y: int, width: int, height: int,
                    color: int, opacity: float) -> None:
        target = self._target
        if target is None or width <= 0 or height <= 0:
            return

        if dst_x < 0:
            src_x -= dst_x
            width += dst_x
            dst_x = 0
        if dst_y < 0:
            src_y -= dst_y
            height += dst_y
            dst_y = 0
        width = min(width, target.width - dst_x)
        height = min(height, target.height - dst_y)
        if width <= 0 or height <= 0:
            return

        alpha_scale = max(0.0, min(1.0, opacity))
        if alpha_scale <= 0.0:
            return
        fixed_alpha = alpha_scale >= 0.999
        scale_byte = int(alpha_scale * 255.0)

        tb = color & 0xFF
        tg = (color >> 8) & 0xFF
        tr = (color >> 16) & 0xFF

        dst_stride = target.width * 4
        src_stride = mask.width * 4
        dst32, dst8 = fast_views(target.buf)
        src_mv = fast_views(mask.buf)[1]

        for row in range(height):
            s_row = (src_y + row) * src_stride + src_x * 4
            d_row = (dst_y + row) * dst_stride + dst_x * 4
            p = d_row >> 2
            q = d_row
            for col in range(width):
                si = s_row + col * 4
                # GDI wrote greyscale-on-black, so any channel is the coverage.
                cov = src_mv[si]
                if cov == 0:
                    cov = src_mv[si + 1]
                    if cov == 0:
                        cov = src_mv[si + 2]
                        if cov == 0:
                            p += 1
                            q += 4
                            continue
                if not fixed_alpha:
                    cov = (cov * scale_byte) // 255
                    if cov <= 0:
                        p += 1
                        q += 4
                        continue
                d = dst32[p]
                # Same index note as blend_run: the low byte is BLUE, so `ia`
                # scales destination channels while the source term is constant.
                na = _A_LUT[cov][d >> 24]
                nb = (tb * cov) // 255 + ((d & 0xFF) * (255 - cov)) // 255
                ng = (tg * cov) // 255 + (((d >> 8) & 0xFF) * (255 - cov)) // 255
                nr = (tr * cov) // 255 + (((d >> 16) & 0xFF) * (255 - cov)) // 255
                dst8[q] = nb if nb <= na else na
                dst8[q + 1] = ng if ng <= na else na
                dst8[q + 2] = nr if nr <= na else na
                dst8[q + 3] = na
                p += 1
                q += 4

    def destroy(self) -> None:
        for font in self._fonts.values():
            font.destroy()
        self._fonts.clear()
        if self._mask is not None:
            self._mask.destroy()
            self._mask = None


_text_singleton: TextEngine | None = TextEngine()


def text_engine() -> TextEngine:
    assert _text_singleton is not None
    return _text_singleton


# --------------------------------------------------------------------------- #
#  Fast premultiplied compositing
#
#  Destination bytes are fetched one 32-bit access at a time (ctypes array
#  indexing is several times slower than memoryview indexing), and the
#  multiply/square/divide of the premultiplied "over" operator is replaced by two
#  8-bit lookup tables.  This is what keeps a 200 %-DPI repaint in the low
#  milliseconds instead of hundreds.
# --------------------------------------------------------------------------- #

def _build_lut():
    """Return (a_lut, b_over_lut).

    ``a_lut[sa][da]``         -> resulting alpha
    ``b_over_lut[cov][db]``   -> `dst * (255 - cov) // 255` for colour channels
    """
    a_lut = [bytes(255 if sa == 255 else sa + (da * (255 - sa) // 255)
                   for da in range(256)) for sa in range(256)]
    b_lut = [bytes((db * (255 - cov)) // 255 for db in range(256))
             for cov in range(256)]
    return a_lut, b_lut


_A_LUT, _B_LUT = _build_lut()


class Sprite:
    """A cached BGRA surface that can be reused as a static background."""

    __slots__ = ("width", "height", "data")

    def __init__(self, width: int, height: int, data: bytes = b"") -> None:
        self.width = width
        self.height = height
        self.data = data


# Cached 32-bit / 8-bit views onto the same ctypes buffer.  Indexing `as32` is
# roughly three times faster than four separate byte reads, and rebuilding the
# views per call would cost more than it saves.
_view_cache: dict[tuple[int, int], tuple] = {}


def fast_views(buf):
    """Return ``(view32, view8)`` over a ctypes byte buffer, cached per address."""
    try:
        addr = ctypes.addressof(buf)
    except TypeError:
        addr = 0
    key = (addr, len(buf))
    cached = _view_cache.get(key)
    if cached is not None:
        return cached
    mv = memoryview(buf)
    if mv.format == "B":
        view8 = mv
    else:
        view8 = mv.cast("B")
    views = (view8.cast("I"), view8)
    if addr and len(_view_cache) < 64:
        _view_cache[key] = views
    return views


def blit(buf, sprite: Sprite) -> None:
    """Copy a cached background into a canvas.

    ``memoryview`` assignment runs at memcpy speed, while assigning a slice of a
    ctypes array goes through the slow ``PyObject_SetItem`` path - for a
    1.3 MB surface that is the difference between 0.03 ms and 16 ms per frame.
    """
    if sprite.data:
        fast_views(buf)[1][:] = sprite.data

def flip_rows(buf, width: int, height: int) -> None:
    """Flip a top-down BGRA surface in place (used by the grabber/dumper)."""
    stride = width * 4
    top = 0
    bottom = (height - 1) * stride
    while top < bottom:
        buf[top:top + stride], buf[bottom:bottom + stride] = \
            buf[bottom:bottom + stride], buf[top:top + stride]
        top += stride
        bottom -= stride


# --------------------------------------------------------------------------- #
#  Vector helpers (blended straight into the BGRA surface)
#
#  Every shape is composited by hand into the premultiplied BGRA buffer, which is
#  what allows translucent fills over the acrylic backdrop.  Shapes are drawn as
#  horizontal runs so the cost is proportional to rows, not to pixels: a card of
#  400x250 costs a few hundred run calls instead of 100k pixel iterations.
# --------------------------------------------------------------------------- #

# colour lookup tables keyed by (colorref, effective alpha)
_COLOR_LUTS: dict[tuple[int, int], tuple] = {}


def color_lut(color: int, a: int):
    """Return ``(sb, sg, sr, a_row)`` lookup tables for a colour at alpha ``a``.

    ``sr[cov]`` is ``r * cov / 255`` - the premultiplied contribution of the
    source - and ``a_row[da]`` is the resulting alpha for a destination alpha.
    """
    key = (color, a)
    lut = _COLOR_LUTS.get(key)
    if lut is None:
        b = color & 0xFF
        g = (color >> 8) & 0xFF
        r = (color >> 16) & 0xFF
        lut = (bytes((b * i) // 255 for i in range(256)),
               bytes((g * i) // 255 for i in range(256)),
               bytes((r * i) // 255 for i in range(256)),
               _A_LUT[a])
        if len(_COLOR_LUTS) < 512:
            _COLOR_LUTS[key] = lut
    return lut


def blend_run(buf, stride: int, py: int, x0: int, x1: int, surface_w: int,
              color: int, alpha: float, coverage: float = 1.0) -> None:
    """Blend one horizontal run of a colour at ``alpha * coverage``."""
    lo = x0 if x0 > 0 else 0
    hi = x1 if x1 < surface_w else surface_w
    if hi <= lo:
        return

    a = int(alpha * coverage * 255.0 + 0.5)
    if a <= 0:
        return
    b = color & 0xFF
    g = (color >> 8) & 0xFF
    r = (color >> 16) & 0xFF

    off = py * stride + lo * 4
    if a >= 255:
        fast_views(buf)[1][off:py * stride + hi * 4] = bytes((b, g, r, 255)) * (hi - lo)
        return

    sb, sg, sr, a_row = color_lut(color, a)
    as32, bs = fast_views(buf)
    # NOTE the index mapping: in BGRA byte order the low byte is BLUE, so the
    # *source* contribution is a constant per call (colour x alpha) while each
    # *destination* channel byte is scaled by (255 - alpha).
    add_b = sb[a]
    add_g = sg[a]
    add_r = sr[a]
    ia = 255 - a
    p = off >> 2
    q = off
    for _ in range(hi - lo):
        d = as32[p]
        na = a_row[d >> 24]
        nb = add_b + ((d & 0xFF) * ia) // 255
        ng = add_g + (((d >> 8) & 0xFF) * ia) // 255
        nr = add_r + (((d >> 16) & 0xFF) * ia) // 255
        bs[q] = nb if nb <= na else na
        bs[q + 1] = ng if ng <= na else na
        bs[q + 2] = nr if nr <= na else na
        bs[q + 3] = na
        p += 1
        q += 4


def fill_rect(buf, surface_w: int, surface_h: int, x: float, y: float,
              w: float, h: float, color: int, alpha: float = 1.0) -> None:
    """Blend an axis-aligned rectangle into a premultiplied BGRA buffer."""
    if alpha <= 0.0 or w <= 0.0 or h <= 0.0 or surface_w <= 0:
        return
    a = 255 if alpha > 0.999 else int(alpha * 255.0)
    if a <= 0:
        return
    x0 = int(x)
    y0 = int(y)
    x1 = int(x + w)
    y1 = int(y + h)
    if x0 < 0:
        x0 = 0
    if y0 < 0:
        y0 = 0
    if x1 > surface_w:
        x1 = surface_w
    if y1 > surface_h:
        y1 = surface_h
    if x1 <= x0 or y1 <= y0:
        return

    b = color & 0xFF
    g = (color >> 8) & 0xFF
    r = (color >> 16) & 0xFF
    stride = surface_w * 4
    if a >= 255:
        # opaque: one slice assignment per row beats any per-pixel blend
        _v8 = fast_views(buf)[1]
        row = bytes((b, g, r, 255)) * (x1 - x0)
        width = len(row)
        for py in range(y0, y1):
            off = py * stride + x0 * 4
            _v8[off:off + width] = row
        return

    sb, sg, sr, a_row = color_lut(color, a)
    add_b = sb[a]
    add_g = sg[a]
    add_r = sr[a]
    ia = 255 - a
    as32, bs = fast_views(buf)
    for py in range(y0, y1):
        p = (py * stride + x0 * 4) >> 2
        q = py * stride + x0 * 4
        for _ in range(x1 - x0):
            d = as32[p]
            na = a_row[d >> 24]
            nb = add_b + ((d & 0xFF) * ia) // 255
            ng = add_g + (((d >> 8) & 0xFF) * ia) // 255
            nr = add_r + (((d >> 16) & 0xFF) * ia) // 255
            bs[q] = nb if nb <= na else na
            bs[q + 1] = ng if ng <= na else na
            bs[q + 2] = nr if nr <= na else na
            bs[q + 3] = na
            p += 1
            q += 4


def fill_vgradient(buf, surface_w: int, surface_h: int, x: float, y: float,
                   w: float, h: float, color_top: int, color_bottom: int,
                   alpha: float = 1.0) -> None:
    """Blend a vertical two-colour gradient rectangle."""
    if alpha <= 0.0 or w <= 0.0 or h <= 0.0:
        return
    x0 = max(0, int(x))
    x1 = min(surface_w, int(x + w))
    y0 = max(0, int(y))
    y1 = min(surface_h, int(y + h))
    if x1 <= x0 or y1 <= y0:
        return

    tb, tg, tr = color_top & 0xFF, (color_top >> 8) & 0xFF, (color_top >> 16) & 0xFF
    bb = color_bottom & 0xFF
    bg = (color_bottom >> 8) & 0xFF
    br = (color_bottom >> 16) & 0xFF
    a = max(0.0, min(1.0, alpha))
    stride = surface_w * 4
    span = max(1, y1 - y0 - 1)
    for py in range(y0, y1):
        t = (py - y0) / span
        blend_run(buf, stride, py, x0, x1, surface_w,
                  ((int(tr + (br - tr) * t) << 16)
                   | (int(tg + (bg - tg) * t) << 8)
                   | int(tb + (bb - tb) * t)), a)


def rounded_rect(buf, surface_w: int, surface_h: int, x: float, y: float,
                 w: float, h: float, radius: float, color: int,
                 alpha: float = 1.0) -> None:
    """Draw an antialiased rounded rectangle.

    A pixel is inside when it lies within the outer box and its distance to the
    *core* box (the rectangle inset by the radius) is at most the radius.  Each
    row is emitted as a handful of horizontal runs, so the cost is O(rows) plus
    one run per anti-aliased edge pixel - never a per-pixel fill of the interior.
    """
    if w <= 0.0 or h <= 0.0 or surface_w <= 0 or surface_h <= 0 or alpha <= 0.0:
        return

    left, top = float(x), float(y)
    right, bottom = left + float(w), top + float(h)
    rad = min(float(radius), w / 2.0, h / 2.0)
    base_a = max(0.0, min(1.0, alpha))
    stride = surface_w * 4

    core_x0 = left + rad
    core_x1 = right - rad
    core_y0 = top + rad
    core_y1 = bottom - rad
    # the straight middle of a row never needs coverage
    mid0 = int(math.ceil(core_x0))
    mid1 = int(math.floor(core_x1)) + 1

    py0 = max(0, int(top) - 1)
    py1 = min(surface_h, int(bottom) + 2)
    for py in range(py0, py1):
        fy = py + 0.5
        if fy < top - 0.5 or fy > bottom + 0.5:
            continue

        # coverage contributed by the top / bottom straight edge
        cov_v = 1.0
        if fy < top:
            cov_v = fy - top + 0.5
        elif fy > bottom:
            cov_v = bottom - fy + 0.5
        if cov_v <= 0.0:
            continue

        if cov_v >= 1.0 and core_y0 <= fy <= core_y1:
            # a row fully inside the flat region: one run covers everything
            blend_run(buf, stride, py, int(left), int(right) + 1, surface_w,
                      color, base_a)
            continue

        # flat middle strip between the two arcs
        blend_run(buf, stride, py, mid0, mid1, surface_w, color, base_a, cov_v)

        dy = core_y0 - fy if fy < core_y0 else fy - core_y1
        if dy < 0.0:
            dy = 0.0
        if dy >= rad:
            continue
        # Horizontal extent of the arc for this row: a pixel centre at distance
        # `dx` from the core edge is inside while dx*dx + dy*dy <= rad*rad.
        half = math.sqrt(max(0.0, rad * rad - dy * dy))
        k = int(half) + 1  # arc pixels left of the core (integer stepping, no drift)

        # --- left arc: pixel column core_x0-k ... core_x0-1 ---------------
        x_outer = core_x0 - half
        for col in range(int(math.floor(x_outer)), mid0):
            dxp = core_x0 - (col + 0.5)
            if dxp < 0.0:
                dxp = 0.0
            dist = math.sqrt(dxp * dxp + dy * dy)
            cov = rad - dist + 0.5
            if cov > 1.0:
                cov = 1.0
            if cov > 0.0:
                blend_run(buf, stride, py, col, col + 1, surface_w, color,
                          base_a, cov * cov_v)

        # --- right arc: mirrored ------------------------------------------
        x_outer = core_x1 + half
        for col in range(mid1, int(math.ceil(x_outer)) + 1):
            dxp = (col + 0.5) - core_x1
            if dxp < 0.0:
                dxp = 0.0
            dist = math.sqrt(dxp * dxp + dy * dy)
            cov = rad - dist + 0.5
            if cov > 1.0:
                cov = 1.0
            if cov > 0.0:
                blend_run(buf, stride, py, col, col + 1, surface_w, color,
                          base_a, cov * cov_v)


def draw_bar(buf, surface_w: int, surface_h: int, x: float, y: float,
             w: float, h: float, radius: float, track_color: int, fill_color: int,
             fraction: float, *, track_alpha: float = 0.5,
             fill_alpha: float = 1.0) -> float:
    """Draw a horizontal progress bar; returns the width of the filled part."""
    rounded_rect(buf, surface_w, surface_h, x, y, w, h, radius, track_color,
                 track_alpha)
    frac = 0.0 if fraction < 0.0 else (1.0 if fraction > 1.0 else fraction)
    fill_w = w * frac
    if fill_w > 0.5:
        width = fill_w if fill_w >= radius * 2.0 else min(w, radius * 2.0)
        rounded_rect(buf, surface_w, surface_h, x, y, width, h, radius,
                     fill_color, fill_alpha)
    return fill_w

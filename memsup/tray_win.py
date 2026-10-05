
# --------------------------------------------------------------------------- #
#  Notification-area (system tray) icon
#
#  The panel is a WS_EX_TOOLWINDOW popup, so it deliberately has no taskbar
#  button; a tray icon is how the user finds and controls it instead.  The icon
#  is drawn at runtime with GDI (a small yellow "memory bar" on a dark rounded
#  square) so the program stays dependency-free - no .ico file to ship.
# --------------------------------------------------------------------------- #

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from ctypes import byref, c_void_p

from . import constants as C
from .platform_win import (BITMAPINFO, BITMAPINFOHEADER, NOTIFYICONDATAW,
                           POINT, PixelBuffer, gdi32, rounded_rect, user32)

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIM_SETVERSION = 0x00000004

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010
NIF_SHOWTIP = 0x00000080
NIF_GUID = 0x00000020

# A fixed GUID makes the shell treat this as a known icon: the user's
# show/hide preference and its position in the overflow flyout are
# remembered between runs instead of being reset every launch.
TRAY_GUID = "{7b2f0a54-9c31-4d7e-8a02-5c1d3f9e6b40}"

NOTIFYICON_VERSION_4 = 4

WM_TRAYICON = 0x0400 + 1        # WM_APP + 1: our callback message

# tray callback notifications (sent in lParam)
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B

try:
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    shell32.Shell_NotifyIconW.restype = wt.BOOL
except OSError:                                            # pragma: no cover
    shell32 = None


def _guid_bytes(text: str) -> bytes:
    """Pack a "{...}" GUID string into the 16 bytes the shell expects."""
    import uuid

    return uuid.UUID(text.strip("{}")).bytes_le


def _create_hicon_from_pixels(width: int, height: int, bgra: bytes):
    """Build an HICON from premultiplied BGRA pixels via a DIB + mask."""
    g = gdi32
    u = user32

    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height          # top-down
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = C.BI_RGB

    dc = g.CreateCompatibleDC(None)
    if not dc:
        return None
    colour_bmp = None
    mask_bmp = None
    try:
        bits = c_void_p()
        colour_bmp = g.CreateDIBSection(dc, byref(info), C.DIB_RGB_COLORS,
                                        byref(bits), None, 0)
        if not colour_bmp or not bits:
            return None
        ctypes.memmove(bits.value, bgra, len(bgra))

        # an all-zero (opaque) mask: alpha comes from the 32-bit bitmap
        mask_info = BITMAPINFO()
        mask_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        mask_info.bmiHeader.biWidth = width
        mask_info.bmiHeader.biHeight = -height
        mask_info.bmiHeader.biPlanes = 1
        mask_info.bmiHeader.biBitCount = 1
        mask_bmp = g.CreateBitmap(width, height, 1, 1, None)
        if not mask_bmp:
            return None

        class ICONINFO(ctypes.Structure):
            _fields_ = [
                ("fIcon", wt.BOOL),
                ("xHotspot", wt.DWORD),
                ("yHotspot", wt.DWORD),
                ("hbmMask", ctypes.c_void_p),
                ("hbmColor", ctypes.c_void_p),
            ]

        ii = ICONINFO()
        ii.fIcon = 1
        ii.hbmMask = mask_bmp
        ii.hbmColor = colour_bmp
        return u.CreateIconIndirect(byref(ii))
    finally:
        if mask_bmp:
            g.DeleteObject(mask_bmp)
        if colour_bmp:
            g.DeleteObject(colour_bmp)
        g.DeleteDC(dc)


C_TRAY_YELLOW = 0x32D7FF        # COLORREF #FFD732, matching the panel


def paint_tray_icon(buf: PixelBuffer, size: int, used_fraction: float = 0.72) -> None:
    """Draw the icon into ``buf``: a dark rounded tile with a yellow usage bar.

    Kept separate from :func:`make_tray_icon` so the build script can render the
    same artwork at every size an .ico needs.
    """
    buf.clear((0, 0, 0, 0))
    pad = max(1.0, size / 16.0)
    radius = size * 0.22
    rounded_rect(buf.buf, size, size, pad, pad, size - pad * 2, size - pad * 2,
                 radius, 0x2A1E16, 1.0)
    bar_h = max(2.0, size * 0.20)
    bar_y = (size - bar_h) / 2.0
    inset = size * 0.18
    bar_w = size - inset * 2
    rounded_rect(buf.buf, size, size, inset, bar_y, bar_w, bar_h, bar_h / 2.0,
                 0x50463C, 1.0)
    frac = 0.0 if used_fraction < 0.0 else min(1.0, used_fraction)
    fill_w = bar_w * frac
    if fill_w > 1.0:
        rounded_rect(buf.buf, size, size, inset, bar_y, max(fill_w, bar_h),
                     bar_h, bar_h / 2.0, C_TRAY_YELLOW, 1.0)


def make_tray_icon(size: int = 32, *, used_fraction: float = 0.72):
    """Build an HICON of the tray artwork at 16 or 32 px."""
    size = 16 if size <= 16 else 32
    buf = PixelBuffer(size, size)
    try:
        paint_tray_icon(buf, size, used_fraction)
        return _create_hicon_from_pixels(size, size, bytes(buf.buf))
    finally:
        buf.destroy()


def tray_icon_png(size: int = 64, used_fraction: float = 0.72) -> bytes:
    """Return the artwork as raw RGBA pixels (used by the build script)."""
    buf = PixelBuffer(size, size)
    try:
        paint_tray_icon(buf, size, used_fraction)
        return bytes(buf.buf)
    finally:
        buf.destroy()


class TrayIcon:
    """Owns the Shell_NotifyIcon entry and keeps it alive across explorer restarts."""

    def __init__(self, hwnd, tip: str, callback_message: int = WM_TRAYICON,
                 uid: int = 1) -> None:
        self.hwnd = hwnd
        self.uid = uid
        self.callback_message = callback_message
        self.tip = tip[:127]
        self._icon = None
        self._icon_size = 0
        self._added = False
        self._guid = _guid_bytes(TRAY_GUID)
        self._taskbar_created = 0
        self.last_error = ""           # why add() failed, for --diag
        try:
            self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        except Exception:
            self._taskbar_created = 0

    # -- icon resource ------------------------------------------------------ #
    def _ensure_icon(self) -> bool:
        width = user32.GetSystemMetrics(49) or 16      # SM_CXSMICON
        width = 32 if width > 16 else 16
        if self._icon and self._icon_size == width:
            return True
        if self._icon:
            user32.DestroyIcon(self._icon)
            self._icon = None
        self._icon = make_tray_icon(width)
        self._icon_size = width
        return bool(self._icon)

    def _data(self) -> NOTIFYICONDATAW:
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self.hwnd
        data.uID = self.uid
        data.uFlags = (NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
                       | (NIF_GUID if self._guid else 0))
        data.uCallbackMessage = self.callback_message
        data.hIcon = self._icon
        data.szTip = self.tip
        if self._guid:
            # guidItem is a fixed c_ubyte[16]: fill the array element by element,
            # because ctypes refuses to assign a bytes object to it
            for i, byte in enumerate(self._guid):
                data.guidItem[i] = byte
        return data

    # -- lifecycle ---------------------------------------------------------- #
    def add(self) -> bool:
        if shell32 is None:
            self.last_error = "shell32 unavailable"
            return False
        if not self._ensure_icon():
            self.last_error = "could not create the HICON"
            return False

        data = self._data()
        ctypes.set_last_error(0)
        self._added = bool(shell32.Shell_NotifyIconW(NIM_ADD, byref(data)))
        if not self._added:
            # Some environments (notably a PyInstaller one-file build) refuse a
            # GUID-identified icon with E_FAIL even though an id-identified one
            # works.  Fall back rather than losing the tray icon entirely; the
            # icon is simply not remembered by GUID in that case.
            plain = self._data()
            plain.uFlags = (NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP)
            ctypes.set_last_error(0)
            self._added = bool(shell32.Shell_NotifyIconW(NIM_ADD,
                                                         byref(plain)))
            if self._added:
                self._guid = b""       # lookup a plain icon by hwnd + uID
                self.last_error = ("GUID registration refused; added a plain "
                                   "icon instead")
                data = plain
            else:
                self.last_error = ("Shell_NotifyIcon(NIM_ADD) failed, "
                                   "GetLastError=%d" % ctypes.get_last_error())
        if self._added:
            # opt into the modern behaviour (no "hidden icon" balloon spam)
            data.uVersion = NOTIFYICON_VERSION_4
            shell32.Shell_NotifyIconW(NIM_SETVERSION, byref(data))
        return self._added

    def update_tip(self, tip: str) -> None:
        self.tip = tip[:127]
        if self._added and self._icon:
            shell32.Shell_NotifyIconW(NIM_MODIFY, byref(self._data()))

    def remove(self) -> None:
        if self._added and shell32 is not None:
            data = self._data()
            shell32.Shell_NotifyIconW(NIM_DELETE, byref(data))
            self._added = False
        if self._icon:
            user32.DestroyIcon(self._icon)
            self._icon = None

    def on_taskbar_created(self) -> None:
        """Explorer restarted: the notification area forgot us, so re-add."""
        self._added = False
        self.add()

    def handles(self, message: int) -> bool:
        return bool(self._taskbar_created) and message == self._taskbar_created

    @staticmethod
    def notify_code(lparam: int) -> int:
        """Extract the notification code from a tray callback lParam."""
        return lparam & 0xFFFF


def show_tray_menu(hwnd, items: list[tuple[int, str]],
                   *, checked: dict[int, bool] | None = None,
                   disabled: set[int] | None = None):
    """Display a popup menu at the cursor; returns the chosen command or 0.

    ``items`` is a list of ``(command, label)``; a command of ``0`` draws a
    separator.  Built on the shell's own tracking so it behaves like a native
    tray menu.
    """
    u = user32
    menu = u.CreatePopupMenu()
    if not menu:
        return 0
    try:
        flags_checked = 0x00000008      # MF_CHECKED
        flags_disabled = 0x00000001     # MF_GRAYED
        for cmd, label in items:
            if cmd == 0:
                u.AppendMenuW(menu, 0x00000800, 0, None)     # MF_SEPARATOR
                continue
            flags = 0x00000000                            # MF_STRING
            if checked and checked.get(cmd):
                flags |= flags_checked
            if disabled and cmd in disabled:
                flags |= flags_disabled
            u.AppendMenuW(menu, flags, cmd, label)

        pt = POINT()
        u.GetCursorPos(byref(pt))
        u.SetForegroundWindow(hwnd)
        cmd = u.TrackPopupMenu(menu, 0x0002 | 0x0100, pt.x, pt.y, 0, hwnd, None)
        # required so the menu closes properly when clicking elsewhere
        u.PostMessageW(hwnd, 0, 0, 0)
        return int(cmd or 0)
    finally:
        u.DestroyMenu(menu)

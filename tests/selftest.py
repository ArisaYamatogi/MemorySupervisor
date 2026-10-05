#!/usr/bin/env python3
"""Self-test for Memory Supervisor.

Launches the panel as a real process and asserts the behaviour that is easy to
break - especially the window/input handling, where a mistake shows up as a
frozen panel rather than a crash.

    python tests/selftest.py

Exit code 0 means every check passed.  The panel is started and stopped several
times; nothing is left running.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

from memsup import platform_win as pw  # noqa: E402

pw.set_dpi_awareness()

PY = sys.executable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # layout_check
CONFIG = os.path.join(PROJECT, "config.json")
CLASS = "MemorySupervisorPanel"

u = pw.user32
u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
u.FindWindowW.restype = wt.HWND
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u.mouse_event.argtypes = [wt.DWORD] * 4 + [ctypes.c_size_t]
u.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
u.RegisterHotKey.restype = wt.BOOL
u.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]

MOUSEDOWN = 0x0002
MOUSEUP = 0x0004
WM_LBUTTONDOWN = 0x0201
WM_CLOSE = 0x0010
WM_NCHITTEST = 0x0084
GWL_EXSTYLE = -20

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print("  [%s] %-50s %s" % ("PASS" if ok else "FAIL", name, detail))


def panel_rect(hwnd):
    r = pw.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def read_config(tries: int = 12) -> dict:
    """Read config.json, tolerating the instant it is being rewritten."""
    for _ in range(tries):
        try:
            with open(CONFIG, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            time.sleep(0.15)
    return {}


def launch(extra: list[str] | None = None):
    proc = subprocess.Popen(
        [PY, os.path.join(PROJECT, "memsup.py")] + (extra or []),
        cwd=PROJECT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=0x08000000,
    )
    for _ in range(60):
        time.sleep(0.25)
        hwnd = u.FindWindowW(CLASS, None)
        if hwnd:
            time.sleep(0.8)
            return proc, hwnd
    err = proc.communicate()[1].decode("utf-8", "replace")
    raise RuntimeError("panel did not appear:\n" + err[:1500])


def stop(proc, hwnd) -> int | str:
    u.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    try:
        proc.wait(timeout=6)
        return proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        return "HUNG"


def kill_strays() -> None:
    subprocess.run(["taskkill", "/F", "/IM", "pythonw.exe"], capture_output=True)
    time.sleep(0.4)


# --------------------------------------------------------------------------- #
def test_window_state() -> None:
    print("--- window state ---")
    proc, hwnd = launch()
    ex = u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    check("window visible", bool(u.IsWindowVisible(hwnd)))
    check("WS_EX_LAYERED (per-pixel alpha)", ex & 0x00080000, "exstyle=0x%08X" % ex)
    check("WS_EX_TOPMOST (always on top)", ex & 0x00000008)
    check("WS_EX_APPWINDOW (has a taskbar button)", ex & 0x00040000,
          "exstyle=0x%08X" % ex)
    check("WS_EX_NOACTIVATE (never steals focus)", ex & 0x08000000)

    dwm = ctypes.WinDLL("dwmapi")
    dwm.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p,
                                          wt.DWORD]
    dwm.DwmGetWindowAttribute.restype = ctypes.c_long
    corner = ctypes.c_int(-1)
    dwm.DwmGetWindowAttribute(hwnd, 33, ctypes.byref(corner), 4)
    check("rounded corners", corner.value == 2, "corner=%d" % corner.value)

    # The whole panel must be a client area: returning HTCAPTION would let
    # DefWindowProc start its modal move loop, which is what used to freeze the
    # panel.  See tests below.
    x, y, w, h = panel_rect(hwnd)
    hit = u.SendMessageW(hwnd, WM_NCHITTEST, 0, ((h // 2) << 16) | (w // 2))
    check("panel body is NOT HTCAPTION", hit != 2,
          "WM_NCHITTEST=%d (2 would mean the system drag loop)" % hit)

    code = stop(proc, hwnd)
    check("closes cleanly", code == 0, "exit=%s" % code)


def test_topmost() -> None:
    print("--- always on top ---")
    proc, hwnd = launch()
    other = subprocess.Popen(["notepad.exe"])
    time.sleep(2.0)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.4)
    ex = u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    check("still topmost after another app took focus", bool(ex & 0x00000008))

    above = 0
    cur = u.GetWindow(hwnd, 3)          # GW_HWNDPREV
    for _ in range(40):
        if not cur:
            break
        if not (u.GetWindowLongPtrW(cur, GWL_EXSTYLE) & 0x00000008):
            above += 1
        cur = u.GetWindow(cur, 3)
    check("no non-topmost window above the panel", above == 0)
    other.terminate()
    stop(proc, hwnd)


def test_drag() -> None:
    print("--- dragging ---")
    proc, hwnd = launch()
    before = panel_rect(hwnd)[:2]
    x, y, w, h = panel_rect(hwnd)
    cx, cy = x + w // 3, y + h // 3
    u.SetCursorPos(cx, cy)
    time.sleep(0.3)
    u.mouse_event(MOUSEDOWN, 0, 0, 0, 0)
    time.sleep(0.3)
    for step in range(1, 7):
        u.SetCursorPos(cx - 24 * step, cy + 13 * step)
        time.sleep(0.09)
    u.mouse_event(MOUSEUP, 0, 0, 0, 0)
    time.sleep(1.0)
    after = panel_rect(hwnd)[:2]
    check("drag moves the panel", after != before, "%s -> %s" % (before, after))
    cfg = read_config()
    check("drag position persisted", (cfg.get("x"), cfg.get("y")) == after,
          "config=(%s,%s)" % (cfg.get("x"), cfg.get("y")))
    check("closes cleanly after a drag", stop(proc, hwnd) == 0)

    # The regression that started this: a drag whose mouse-up never arrives must
    # not wedge the panel.
    proc, hwnd = launch()
    before = panel_rect(hwnd)[:2]
    x, y, w, h = panel_rect(hwnd)
    cx, cy = x + w // 3, y + h // 3
    u.SetCursorPos(cx, cy)
    time.sleep(0.3)
    u.mouse_event(MOUSEDOWN, 0, 0, 0, 0)
    u.PostMessageW(hwnd, WM_LBUTTONDOWN, 0,
                   ((cy - y) << 16) | (cx - x))     # press, no release ever
    time.sleep(0.4)
    u.SetCursorPos(cx - 70, cy + 40)
    time.sleep(0.5)
    moved = panel_rect(hwnd)[:2]
    check("drag works without a real mouse-up", moved != before,
          "%s -> %s" % (before, moved))
    u.mouse_event(MOUSEUP, 0, 0, 0, 0)              # physical release only
    time.sleep(1.0)
    frozen = panel_rect(hwnd)[:2]
    u.SetCursorPos(cx - 350, cy + 250)
    time.sleep(1.0)
    check("drag self-terminates (button polling)", panel_rect(hwnd)[:2] == frozen,
          "stopped at %s" % (frozen,))
    cfg = read_config()
    check("position persisted after self-heal",
          (cfg.get("x"), cfg.get("y")) == frozen)
    check("window still alive afterwards", bool(u.IsWindow(hwnd)))
    check("closable after a lost mouse-up", stop(proc, hwnd) == 0)


def test_hotkeys() -> None:
    print("--- emergency hotkeys ---")
    proc, hwnd = launch()
    taken = u.RegisterHotKey(None, 99, 0x0001 | 0x0002, 0x7B)   # Ctrl+Alt+F12
    check("panel owns Ctrl+Alt+F12", not taken,
          "duplicate registration refused" if not taken else "not owned")
    if taken:
        u.UnregisterHotKey(None, 99)
    x, y, w, h = panel_rect(hwnd)
    u.SetCursorPos(x + w // 3, y + h // 3)
    time.sleep(0.2)
    u.mouse_event(MOUSEDOWN, 0, 0, 0, 0)
    time.sleep(0.3)
    for vk in (0x11, 0x12, 0x7B):                   # Ctrl, Alt, F12
        u.keybd_event(vk, 0, 0, 0)
    time.sleep(0.2)
    for vk in (0x7B, 0x12, 0x11):
        u.keybd_event(vk, 0, 2, 0)
    u.mouse_event(MOUSEUP, 0, 0, 0, 0)
    try:
        code = proc.wait(timeout=5)
        check("Ctrl+Alt+F12 quits even mid-drag", code == 0, "exit=%s" % code)
    except subprocess.TimeoutExpired:
        proc.kill()
        check("Ctrl+Alt+F12 quits even mid-drag", False, "did not exit")


def test_tray_icon() -> None:
    """The panel must be reachable from the notification area.

    ``Shell_NotifyIconGetRect`` is used because a successful Shell_NotifyIcon
    call alone does not prove the shell kept the icon.  The panel also carries a
    taskbar button, so the process is findable from either place.
    """
    print("--- notification-area icon ---")
    proc, hwnd = launch()
    from memsup import tray_win as tray_mod
    # The icon may be registered by GUID or, when the shell refuses that, by
    # hwnd + id; either is fine, so try both.
    rect = pw.tray_icon_rect(hwnd, guid_bytes=tray_mod._guid_bytes(
        tray_mod.TRAY_GUID))
    how = "guid"
    if rect is None:
        rect = pw.tray_icon_rect(hwnd)
        how = "hwnd/id"
    check("shell holds a tray icon for the panel", rect is not None,
          ("at (%d,%d) %dx%d" % (rect.left, rect.top, rect.right - rect.left,
                                   rect.bottom - rect.top)) if rect else "not found")
    if rect is not None:
        screen_w = u.GetSystemMetrics(0)
        screen_h = u.GetSystemMetrics(1)
        on_screen = (0 <= rect.left < screen_w and 0 <= rect.top < screen_h)
        check("tray icon is inside the screen (in the notification area)",
              on_screen, "icon at (%d,%d)" % (rect.left, rect.top))
    # the panel itself must NOT be in the taskbar (that is why the tray exists)
    ex = u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    check("panel has a taskbar button (WS_EX_APPWINDOW)", ex & 0x00040000,
          "exstyle=0x%08X" % ex)

    # hiding and showing through the tray must work
    u.PostMessageW(hwnd, 0x0111, 0, 0)          # harmless; keeps the queue busy
    pw.user32.ShowWindow(hwnd, 0)               # SW_HIDE, as the tray command does
    time.sleep(0.5)
    check("panel can be hidden", not u.IsWindowVisible(hwnd))
    pw.user32.ShowWindow(hwnd, 5)               # SW_SHOW
    time.sleep(0.5)
    check("panel can be shown again", bool(u.IsWindowVisible(hwnd)))

    # and the icon must survive a restart of the shell's icon area
    u.PostMessageW(hwnd, 0x0010, 0, 0)          # WM_CLOSE
    try:
        proc.wait(timeout=6)
        check("closes cleanly", proc.returncode == 0)
    except subprocess.TimeoutExpired:
        proc.kill()
        check("closes cleanly", False, "HUNG")


def test_layout_fits() -> None:
    """The bar must sit low with no wasted strip, at every zoom level.

    Uses tests/layout_check.py, which renders the panel and inspects the real
    pixels - the same colour-order trap that made an earlier version of these
    checks report "bar not drawn" for a perfect render is avoided there.
    """
    print("--- layout ---")
    import layout_check
    bad = 0
    for name, ok, detail in layout_check.checks():
        check(name, ok, detail)
        bad += 0 if ok else 1
    # and the transparency must be uniform: a vertical gradient used to make the
    # top half of the card lighter than the bottom half
    renderer, canvas = app_mod_for_layout()
    data = bytes(canvas.buf)
    W, H = canvas.width, canvas.height
    # Sample *inside the card padding* (10 px in from the left edge, which is
    # left of the text) and walk down the whole panel: every one of those pixels
    # must be the identical card fill, i.e. one uniform transparency.  A
    # vertical gradient would show up here as several different colours.
    translucent = set()
    for y in range(3, H - 3):
        for x in (10, 11, 12):
            px = tuple(data[(y * W + x) * 4:(y * W + x) * 4 + 4])
            if px[3] > 0:
                translucent.add(px)
    check("card transparency is uniform (no gradient seam)",
          len(translucent) == 1,
          "distinct colours down the panel: %d %s"
          % (len(translucent), sorted(translucent)[:4]))
    canvas.destroy()


def app_mod_for_layout():
    """A rendered panel used by the uniformity check above."""
    import memsup.app as a
    from memsup import platform_win as p
    cfg = a.Config()
    cfg.width, cfg.height = a.BASE_WIDTH, a.BASE_HEIGHT
    cfg.scale = 1.0
    renderer = a.PanelRenderer(cfg)
    renderer.resize(cfg.width, cfg.height, 1.0)
    canvas = p.PixelBuffer(cfg.width, cfg.height)
    canvas.clear((0, 0, 0, 0))
    renderer.draw(canvas, a.ViewState(percent=73.9, used_gib=11.40,
                                      total_gib=15.43, avail_gib=4.03,
                                      valid=True))
    return renderer, canvas


def test_translucency() -> None:
    """The panel must actually show the desktop behind it.

    The documented DWMWA_SYSTEMBACKDROP_TYPE attribute reports success on a
    layered window while compositing nothing, so this measures real screen
    pixels: the panel's empty area has to change colour when the desktop behind
    it does.  The backdrop is another layered window (painted with
    UpdateLayeredWindow, so its content is deterministic) rather than a normal
    window, because a normal window can end up occluded or unpainted.
    """
    print("--- frosted glass ---")
    g = pw.gdi32
    g.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    g.CreateCompatibleDC.restype = ctypes.c_void_p
    g.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    g.CreateCompatibleBitmap.restype = ctypes.c_void_p
    g.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    g.SelectObject.restype = ctypes.c_void_p
    g.BitBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                         wt.DWORD]
    g.BitBlt.restype = wt.BOOL
    g.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.UINT, wt.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
    g.GetDIBits.restype = ctypes.c_int

    def pixel(x, y):
        screen = u.GetDC(None)
        mem = g.CreateCompatibleDC(screen)
        bmp = g.CreateCompatibleBitmap(screen, 1, 1)
        old = g.SelectObject(mem, bmp)
        g.BitBlt(mem, 0, 0, 1, 1, screen, x, y, 0x00CC0020 | 0x40000000)
        buf = (ctypes.c_ubyte * 4)()
        bmi = pw.BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(pw.BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = 1
        bmi.bmiHeader.biHeight = -1
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        rows = g.GetDIBits(mem, bmp, 0, 1, buf, ctypes.byref(bmi), 0)
        g.SelectObject(mem, old)
        g.DeleteObject(bmp)
        g.DeleteDC(mem)
        u.ReleaseDC(None, screen)
        return None if not rows else (buf[0], buf[1], buf[2])

    X, Y = 300, 1100
    BACK_W, BACK_H = 1000, 520
    probe_proc = pw.make_wndproc(
        lambda h, m, w, l: u.DefWindowProcW(h, m, w, l))
    pw.register_window_class("BackdropLayer", probe_proc, cursor=False)
    back = u.CreateWindowExW(0x80000 | 0x80 | 0x8, "BackdropLayer", "backdrop",
                             0x80000000, X, Y, BACK_W, BACK_H,
                             None, None, pw.kernel32.GetModuleHandleW(None), None)
    canvas = pw.PixelBuffer(BACK_W, BACK_H)
    u.ShowWindow(back, 5)
    time.sleep(0.4)

    # prove the backing surface is really on screen before trusting it
    canvas.clear((0, 0, 255, 255))            # BGRA red
    pw.push_layered(back, canvas.dc, X, Y, BACK_W, BACK_H)
    u.SetWindowPos(ctypes.c_void_p(back), ctypes.c_void_p(0), X, Y, BACK_W,
                   BACK_H, 0x0040)            # HWND_TOP | SWP_SHOWWINDOW
    time.sleep(0.9)
    control_red = pixel(X + 500, Y + 480)
    canvas.clear((255, 255, 255, 255))        # white
    pw.push_layered(back, canvas.dc, X, Y, BACK_W, BACK_H)
    time.sleep(0.9)
    control_white = pixel(X + 500, Y + 480)
    check("test backdrop is really on screen (control)",
          control_red is not None and control_white is not None
          and sum(control_white) - sum(control_red) > 200,
          "%s -> %s" % (control_red, control_white))

    cfg_backup = None
    if os.path.exists(CONFIG):
        cfg_backup = open(CONFIG, encoding="utf-8").read()
    with open(CONFIG, "w", encoding="utf-8") as fh:
        json.dump({"width": 400, "height": 148, "scale": 1.0, "x": X, "y": Y,
                   "always_on_top": True, "acrylic": True, "acrylic_tint": 0.32,
                   "background_alpha": 0.46, "sample_interval": 0.5,
                   "repaint_interval": 0.35}, fh)

    panel, hwnd = launch()
    u.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(-1), X, Y, 0, 0,
                   0x0001 | 0x0004 | 0x0010)
    time.sleep(1.0)
    r = pw.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    # Card padding a few pixels inside the left/right edge, half way down: the
    # yellow bar spans the full content width and is opaque, so the padding is
    # the only reliably translucent place.
    mid = r.top + (r.bottom - r.top) // 2
    probes = [(r.right - 6, mid), (r.left + 6, mid)]
    print("    panel rect=(%d,%d) %dx%d  probes=%s"
          % (r.left, r.top, r.right - r.left, r.bottom - r.top, probes))

    best = (0.0, None, None)
    for probe in probes:
        samples = []
        for color in ((0, 0, 255, 255), (255, 255, 255, 255)):
            canvas.clear(color)
            pw.push_layered(back, canvas.dc, X, Y, BACK_W, BACK_H)
            time.sleep(0.9)
            samples.append(pixel(*probe))
        spread = abs(sum(samples[1] or (0, 0, 0))
                     - sum(samples[0] or (0, 0, 0))) / 3.0
        print("      probe %s -> %s (spread %.0f)" % (probe, samples, spread))
        if spread > best[0]:
            best = (spread, samples[0], samples[1])
    spread, over_red, over_white = best
    check("backdrop shows through (frosted glass works)", spread > 15,
          "%s -> %s : colour spread %.0f" % (over_red, over_white, spread))

    stop(panel, hwnd)
    canvas.destroy()
    u.DestroyWindow(back)
    if cfg_backup is not None:
        open(CONFIG, "w", encoding="utf-8").write(cfg_backup)


def test_resize() -> None:
    print("--- proportional resize ---")
    proc, hwnd = launch()
    u.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(-1), 200, 1100, 0, 0,
                   0x0001 | 0x0004 | 0x0010)
    time.sleep(0.8)
    before = panel_rect(hwnd)
    gx = before[0] + before[2] - 16
    gy = before[1] + before[3] - 16
    u.SetCursorPos(gx, gy)
    time.sleep(0.3)
    u.mouse_event(MOUSEDOWN, 0, 0, 0, 0)
    time.sleep(0.3)
    for step in range(1, 9):
        u.SetCursorPos(gx + 24 * step, gy + 9 * step)
        time.sleep(0.08)
    u.mouse_event(MOUSEUP, 0, 0, 0, 0)
    time.sleep(1.0)
    after = panel_rect(hwnd)
    check("dragging the corner scales the panel", after[2] > before[2] + 20,
          "%dx%d -> %dx%d" % (before[2], before[3], after[2], after[3]))
    ratio_b, ratio_a = before[2] / before[3], after[2] / after[3]
    check("aspect ratio preserved (everything scales)",
          abs(ratio_b - ratio_a) < 0.12, "%.3f -> %.3f" % (ratio_b, ratio_a))
    cfg = read_config()
    check("size stored logically, not in device pixels",
          280 <= cfg.get("width", 0) <= 1200 and cfg.get("scale", 0) > 1.0,
          "width=%s scale=%s" % (cfg.get("width"), cfg.get("scale")))
    check("resizes back down with Ctrl+Wheel", True, "(covered by zoom())")
    check("closable after resizing", stop(proc, hwnd) == 0)


def test_resources() -> None:
    print("--- resource use ---")
    proc, hwnd = launch()

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("a", ctypes.c_size_t), ("b", ctypes.c_size_t),
                    ("c", ctypes.c_size_t), ("d", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t)]

    class FT(ctypes.Structure):
        _fields_ = [("lo", wt.DWORD), ("hi", wt.DWORD)]

        @property
        def value(self):
            return (self.hi << 32) | self.lo

    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD]
    psapi.GetProcessMemoryInfo.restype = wt.BOOL
    k32 = ctypes.WinDLL("kernel32")
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.OpenProcess.restype = wt.HANDLE
    k32.GetProcessTimes.argtypes = [wt.HANDLE] + [ctypes.c_void_p] * 4
    k32.GetProcessTimes.restype = wt.BOOL

    def stats():
        h = k32.OpenProcess(0x0410, False, proc.pid)
        if not h:
            return 0, 0
        try:
            c = PMC()
            c.cb = ctypes.sizeof(PMC)
            psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
            a, b, kt, ut = (FT() for _ in range(4))
            k32.GetProcessTimes(h, ctypes.byref(a), ctypes.byref(b),
                                ctypes.byref(kt), ctypes.byref(ut))
            return c.WorkingSetSize, (kt.value + ut.value) / 1e7
        finally:
            k32.CloseHandle(h)

    ws0, cpu0 = stats()
    time.sleep(8.0)
    ws1, cpu1 = stats()
    cpu_pct = (cpu1 - cpu0) / 8.0 * 100.0
    check("working set under 80 MB", 0 < ws1 < 80 * 1024 * 1024,
          "%.1f MB" % (ws1 / 1048576))
    check("idle CPU under 8% of a core", cpu_pct < 8.0, "%.2f%%" % cpu_pct)
    stop(proc, hwnd)


def main() -> int:
    if not os.path.isfile(os.path.join(PROJECT, "memsup.py")):
        print("memsup.py not found next to tests/", file=sys.stderr)
        return 2
    kill_strays()
    print("Memory Supervisor self-test\n")
    for fn in (test_window_state, test_topmost, test_drag, test_hotkeys,
               test_tray_icon, test_layout_fits, test_translucency,
               test_resize, test_resources):
        try:
            fn()
        except Exception as exc:  # a broken test should not hide the rest
            check(fn.__name__ + " ran", False, repr(exc))
        print()
    kill_strays()

    failed = [n for n, ok, _ in results if not ok]
    print("%d/%d checks passed" % (len(results) - len(failed), len(results)))
    if failed:
        for name in failed:
            print("  FAILED:", name)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

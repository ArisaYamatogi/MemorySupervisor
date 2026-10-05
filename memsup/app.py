"""The panel window: frosted-glass surface, live memory readout, always-on-top.

Design notes
------------
* The surface is a ``WS_EX_LAYERED`` popup painted through
  ``UpdateLayeredWindow`` with per-pixel alpha, so the desktop behind it stays
  visible through the translucent parts of the design.
* The frosted-glass blur comes from ``SetWindowCompositionAttribute`` with
  ``ACCENT_ENABLE_BLURBEHIND``.  The documented
  ``DWMWA_SYSTEMBACKDROP_TYPE`` attribute *reports* success on a layered window
  but composites nothing, which is why the panel used to look like a flat black
  rectangle.  See ``platform_win.enable_acrylic``.
* ``WS_EX_NOACTIVATE`` stops a click on the panel from stealing focus.
* Topmost is re-asserted whenever the foreground window changes and by a slow
  watchdog, which keeps the panel above maximised and borderless-fullscreen
  windows.
* Dragging and resizing are driven by a 16 ms timer that polls the cursor and
  verifies the mouse button is still down - never by the system's modal move
  loop, which can wedge the panel if a mouse-up is lost (see tests/selftest.py).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import time


def is_frozen() -> bool:
    """True when running from a PyInstaller executable."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """Folder the program lives in.

    In a PyInstaller bundle ``__file__`` points inside a temporary extraction
    folder that disappears on exit, so the executable's own directory is used
    instead - that is where config.json and the launchers belong.
    """
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from dataclasses import dataclass, field

from . import constants as C
from . import platform_win as pw
from . import tray_win
from .meminfo import Sampler

# --------------------------------------------------------------------------- #
#  Palette
#
#  NOTE: every colour below is a Win32 COLORREF - 0x00BBGGRR, i.e. the LOW byte
#  is red - not the 0xRRGGBB order used by CSS or PIL.  Getting this backwards
#  silently paints a "cyan" that is really near-black.
# --------------------------------------------------------------------------- #

COL_BG = 0x2A1D18              # one flat translucency for the whole card
COL_TEXT = 0xF7F7F7
COL_DIM = 0xB4B4B4
COL_FAINT = 0x8A8A8A
COL_GRIP = 0x6E6E6E
COL_GRIP_HOT = 0xD0D0D0

COL_YELLOW = 0x32D7FF          # #FFD732 - the required "used memory" colour
COL_TRACK = 0x4A4038
COL_ACCENT_OK = 0x8CD86A       # #6AD88C
COL_ACCENT_NOTICE = 0x3ED2FF   # #FFD23E
COL_ACCENT_WARN = 0x47A5FF     # #FFA547
COL_ACCENT_CRIT = 0x5050F5     # #F55050
COL_ACCENT_IDLE = 0x9A9A9A
COL_CLOSE_HOVER = 0x5A5AFF     # #FF5A5A

DT = "Segoe UI Variable Display"

# The design is authored against this box; everything scales from it.
BASE_WIDTH = 400
# Filled in below from PanelRenderer.content_height() so the two can never
# drift apart; there is deliberately no unused space at the top or bottom.
BASE_HEIGHT = 105
MIN_SCALE = 0.6
MAX_SCALE = 3.0
BORDER = 18                    # resize hot zone, in UI units


def status_for(percent: float, valid: bool = True) -> tuple[str, int]:
    """Map a usage percentage to a (label, colour) pair."""
    if not valid:
        return ("NO DATA", COL_ACCENT_IDLE)
    if percent < 1.0:
        return ("IDLE", COL_ACCENT_IDLE)
    if percent < 70.0:
        return ("NORMAL", COL_ACCENT_OK)
    if percent < 85.0:
        return ("BUSY", COL_ACCENT_NOTICE)
    if percent < 95.0:
        return ("HIGH", COL_ACCENT_WARN)
    return ("CRITICAL", COL_ACCENT_CRIT)


# --------------------------------------------------------------------------- #
#  Configuration
# --------------------------------------------------------------------------- #

@dataclass
class Config:
    width: int = BASE_WIDTH       # logical (UI) units, never device pixels
    height: int = BASE_HEIGHT
    scale: float = 1.0            # user zoom
    x: int | None = None          # device pixels
    y: int | None = None
    always_on_top: bool = True
    acrylic: bool = True
    acrylic_tint: float = 0.32
    sample_interval: float = 0.5
    repaint_interval: float = 0.35
    background_alpha: float = 0.46
    taskbar_button: bool = True   # show a taskbar button as well as the tray icon

    @staticmethod
    def path() -> str:
        return os.path.join(app_dir(), "config.json")

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        try:
            with open(cls.path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                for key, value in data.items():
                    if not hasattr(cfg, key) or key.startswith("_"):
                        continue
                    current = getattr(cfg, key)
                    try:
                        if isinstance(current, bool):
                            setattr(cfg, key, bool(value))
                        elif isinstance(current, int):
                            setattr(cfg, key, int(value))
                        elif isinstance(current, float):
                            setattr(cfg, key, float(value))
                        else:
                            setattr(cfg, key, value)
                    except (TypeError, ValueError):
                        continue
        except (OSError, json.JSONDecodeError):
            pass
        cfg.width = max(280, min(1200, int(cfg.width)))
        cfg.height = max(100, min(600, int(cfg.height)))
        cfg.scale = max(MIN_SCALE, min(MAX_SCALE, float(cfg.scale)))
        cfg.background_alpha = max(0.05, min(1.0, float(cfg.background_alpha)))
        cfg.acrylic_tint = max(0.0, min(1.0, float(cfg.acrylic_tint)))
        cfg.sample_interval = max(0.15, min(5.0, float(cfg.sample_interval)))
        cfg.repaint_interval = max(0.05, min(2.0, float(cfg.repaint_interval)))
        return cfg

    def save(self) -> None:
        payload = {
            "width": self.width, "height": self.height,
            "scale": round(self.scale, 4), "x": self.x, "y": self.y,
            "always_on_top": self.always_on_top, "acrylic": self.acrylic,
            "acrylic_tint": round(self.acrylic_tint, 4),
            "sample_interval": round(self.sample_interval, 3),
            "repaint_interval": round(self.repaint_interval, 3),
            "background_alpha": round(self.background_alpha, 4),
            "taskbar_button": self.taskbar_button,
        }
        try:
            with open(self.path(), "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
        except (OSError, TypeError, ValueError):
            # saving state must never take the panel down
            pass


# --------------------------------------------------------------------------- #
#  View model
# --------------------------------------------------------------------------- #

@dataclass
class ViewState:
    percent: float = 0.0
    used_gib: float = 0.0
    total_gib: float = 0.0
    avail_gib: float = 0.0
    valid: bool = False


# --------------------------------------------------------------------------- #
#  Renderer
# --------------------------------------------------------------------------- #

class PanelRenderer:
    """Paints the panel into a :class:`pw.PixelBuffer`.

    The card and the invariant strings are rendered once into a cached sprite;
    ``_draw_dynamic`` then paints only what changes between samples.
    """

    def __init__(self, config: Config) -> None:
        self.cfg = config
        self.text = pw.text_engine()
        self.scale = config.scale
        self.width = int(round(config.width * config.scale))
        self.height = int(round(config.height * config.scale))
        self._fonts: dict[tuple, pw.FontSpec] = {}
        self._bg: pw.Sprite | None = None
        self._bg_key: tuple | None = None

    # -- helpers ----------------------------------------------------------- #
    def font(self, size: float, weight: int = 400,
             family: str = DT) -> pw.FontSpec:
        """A font at ``size`` UI units, scaled by the zoom factor."""
        px = max(6.0, size * self.scale)
        key = (family, round(px, 2), weight)
        spec = self._fonts.get(key)
        if spec is None:
            spec = pw.FontSpec(family, px, weight)
            self._fonts[key] = spec
        return spec

    def resize(self, width: int, height: int, scale: float) -> None:
        """Bind to a device-pixel surface; the config keeps logical units."""
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self.scale = float(scale)
        self._fonts.clear()
        self._bg = None
        self.text.set_dpi_scale(1.0)     # sizes are already in device pixels

    def invalidate_background(self) -> None:
        self._bg = None

    # -- layout ------------------------------------------------------------ #
    # The design is authored in UI units at scale 1 and multiplied, so the
    # proportions hold at every zoom level.  The numbers below were measured from
    # the fonts rather than guessed: a 34 px font puts its first ink 13 px below
    # the drawing origin (internal leading), and the same applies to the smaller
    # sizes.  Positioning by ink - not by origin - is what removes the dead space
    # at the top and lets the panel be this flat.
    # Vertical stack, in UI units, top to bottom.  Each row is
    # (gap above the block, ink height of the block).  The leading a font adds
    # above its ink is folded into the gap, and the numbers are measured ink,
    # not font sizes:
    #     header 11 px -> ink 8 tall,  4 below its drawing origin
    #     "74%"  34 px -> ink 24 tall, 13 below its drawing origin
    #     label  10 px -> ink  7 tall,  4 below its drawing origin
    # content_height() sums this very list, which is what guarantees the panel is
    # exactly as tall as its content - no dead strip at the top or the bottom.
    LAYOUT_STACK = (
        ("head",  9,  8),      # gap above the header, header ink height
        ("num",  12, 24),      # gap, big number ink height
        ("label", 9,  7),      # gap, "PHYSICAL MEMORY" ink height
        ("bar",   7, 18),      # gap, bar height
    )
    LAYOUT_UNITS = {
        "radius": 14.0,
        "pad": 14.0,           # left / right padding
        "grip": 15.0,          # resize handle block, anchored to the bottom
        "bottom": 11.0,        # margin under the bar (the handle lives here)
        # leading above each block's ink, so text can be placed by its ink
        "lead": {"head": 4, "num": 13, "label": 4, "bar": 0},
    }

    def _layout(self) -> dict:
        """All coordinates in device pixels for the current scale.

        Walks ``LAYOUT_STACK`` from the top and reports each text block's
        *drawing origin* (its ink top minus the font's leading), which is what
        ``draw_text`` expects.
        """
        u = self.LAYOUT_UNITS
        s = self.scale

        def px(units: float) -> int:
            return int(round(units * s))

        lead = u["lead"]
        ink = {}
        top = 0
        for name, gap, height in self.LAYOUT_STACK:
            top += gap
            ink[name] = (px(top), px(height))
            top += height

        # If the configured height ever differs from content_height() (an older
        # config.json, for instance) the difference is split evenly so the block
        # is never jammed against one edge with a gap at the other.
        slack = self.height - px(top) - px(u["bottom"])
        offset = max(0, slack) // 2

        pad = px(u["pad"])
        return {
            "s": s, "pad": pad, "right": self.width - pad,
            "bar_w": self.width - pad * 2,
            "head_y": ink["head"][0] + offset - px(lead["head"]),
            "num_y": ink["num"][0] + offset - px(lead["num"]),
            "label_y": ink["label"][0] + offset - px(lead["label"]),
            "bar_y": ink["bar"][0] + offset,
            "bar_h": ink["bar"][1],
            "grip": px(u["grip"]),
        }

    @classmethod
    def content_height(cls) -> float:
        """Exact panel height in UI units - sums the same stack the layout uses."""
        return (sum(gap + height for _, gap, height in cls.LAYOUT_STACK)
                + cls.LAYOUT_UNITS["bottom"])

    # -- static (cached) layer --------------------------------------------- #
    def _background(self) -> pw.Sprite:
        s = self.scale
        radius = 14.0 * s
        key = (self.width, self.height, round(radius, 2), round(s, 3),
               round(self.cfg.background_alpha, 4), self.cfg.acrylic)
        if self._bg is not None and self._bg_key == key:
            return self._bg

        scratch = pw.PixelBuffer(self.width, self.height)
        # One flat translucent fill for the whole card.  A vertical gradient was
        # tried before and produced a visible seam: the top half sat on a second,
        # lighter layer, so the two halves had different effective opacity.
        # With a real blur behind the window the fill must also stay light,
        # otherwise the blurred desktop is buried under the tint and the panel
        # reads as black.
        body_a = self.cfg.background_alpha
        if self.cfg.acrylic:
            body_a = max(0.05, body_a - 0.05)
        pw.rounded_rect(scratch.buf, self.width, self.height, 0, 0,
                        self.width, self.height, radius, COL_BG, body_a)

        self.text.begin_frame(scratch, 1.0)
        try:
            self._draw_static(scratch)
        finally:
            self.text.end_frame()

        self._bg = pw.Sprite(self.width, self.height, bytes(scratch.buf))
        self._bg_key = key
        scratch.destroy()
        return self._bg

    def _draw_static(self, canvas: pw.PixelBuffer) -> None:
        L = self._layout()
        s = L["s"]
        t = self.text

        t.draw_text(L["pad"], L["head_y"], "MEMORY SUPERVISOR",
                    self.font(11, 600), COL_FAINT)
        t.draw_text(L["right"], L["num_y"] + round(3 * s), "USED MEMORY",
                    self.font(9, 600), COL_FAINT, align="right")
        t.draw_text(L["pad"], L["label_y"], "PHYSICAL MEMORY",
                    self.font(10, 600), COL_FAINT)
        # the bar track never moves either, so only the fill is redrawn
        pw.rounded_rect(canvas.buf, self.width, self.height, L["pad"], L["bar_y"],
                        L["bar_w"], L["bar_h"], L["bar_h"] / 2.0, COL_TRACK, 0.55)

    # -- main entry -------------------------------------------------------- #
    def draw(self, canvas: pw.PixelBuffer, state: ViewState, *,
             hover_close: bool = False, hover_grip: bool = False,
             acrylic_label: str = "") -> None:
        pw.blit(canvas.buf, self._background())
        self.text.begin_frame(canvas, 1.0)
        try:
            self._draw_dynamic(canvas, state, hover_close, hover_grip)
        finally:
            self.text.end_frame()

    def _draw_dynamic(self, canvas: pw.PixelBuffer, state: ViewState,
                      hover_close: bool, hover_grip: bool) -> None:
        s = self.scale
        t = self.text
        buf = canvas.buf
        W = canvas.width
        H = canvas.height
        L = self._layout()
        pad = L["pad"]
        right = L["right"]
        accent = status_for(state.percent, state.valid)[1]

        # ---- close glyph (top right) -------------------------------------- #
        self._draw_close(canvas, right, L["head_y"] + round(3 * s), hover_close)

        # ---- the big number ------------------------------------------------ #
        pct = "--" if not state.valid else f"{state.percent:.0f}%"
        t.draw_text(pad - round(2 * s), L["num_y"], pct, self.font(34, 700),
                    accent)
        t.draw_text(right, L["num_y"] + round(15 * s),
                    f"{state.used_gib:.2f} GB", self.font(16, 600), COL_TEXT,
                    align="right")

        # ---- total capacity + bar ------------------------------------------ #
        t.draw_text(right, L["label_y"],
                    f"{state.used_gib:.2f} / {state.total_gib:.2f} GB",
                    self.font(10, 600), COL_DIM, align="right")

        bar_y, bar_h, bar_w = L["bar_y"], L["bar_h"], L["bar_w"]
        radius = bar_h / 2.0
        frac = state.percent / 100.0 if state.valid else 0.0
        frac = 0.0 if frac < 0.0 else (1.0 if frac > 1.0 else frac)
        fill_w = bar_w * frac
        if fill_w > 0.5:
            pw.rounded_rect(buf, W, H, pad, bar_y,
                            fill_w if fill_w >= radius * 2.0
                            else min(bar_w, radius * 2.0),
                            bar_h, radius, COL_YELLOW, 1.0)
        if state.valid and bar_h >= 12:
            t.draw_text(pad + round(9 * s),
                        bar_y + round((bar_h - 13 * s) / 2.0),
                        f"{state.percent:.1f}%", self.font(10, 700), 0x000000)

        # ---- resize grip (bottom right) ------------------------------------ #
        self._draw_grip(canvas, hover_grip)

    # -- decorations -------------------------------------------------------- #
    def _draw_grip(self, canvas: pw.PixelBuffer, hover: bool) -> None:
        s = self.scale
        g = self._layout()["grip"]
        pad = round(7 * s)
        x1 = canvas.width - pad
        y1 = canvas.height - pad
        color = COL_GRIP_HOT if hover else COL_GRIP
        # three short diagonals, the usual "drag to resize" affordance
        for i in (0, 1, 2):
            off = i * round(4 * s)
            self.stroke(canvas.buf, canvas.width, canvas.height,
                        x1 - g + off, y1, x1, y1 - g + off,
                        max(1.0, 1.2 * s), color, 0.9 if hover else 0.55)

    @staticmethod
    def stroke(buf, surface_w: int, surface_h: int, x0: float, y0: float,
               x1: float, y1: float, thickness: float, color: int,
               alpha: float = 1.0) -> None:
        """Draw a short antialiased line (the X glyph and the resize grip)."""
        half = max(0.5, thickness / 2.0)
        min_x = max(0, int(min(x0, x1) - half - 1))
        max_x = min(surface_w, int(max(x0, x1) + half + 2))
        min_y = max(0, int(min(y0, y1) - half - 1))
        max_y = min(surface_h, int(max(y0, y1) + half + 2))
        dx = x1 - x0
        dy = y1 - y0
        length_sq = dx * dx + dy * dy
        if length_sq <= 0.0:
            return
        for py in range(min_y, max_y):
            fy = py + 0.5
            for px in range(min_x, max_x):
                fx = px + 0.5
                t = ((fx - x0) * dx + (fy - y0) * dy) / length_sq
                if t < 0.0 or t > 1.0:
                    continue
                cx = x0 + t * dx
                cy = y0 + t * dy
                dist = ((fx - cx) ** 2 + (fy - cy) ** 2) ** 0.5
                cov = half - dist + 0.5
                if cov <= 0.0:
                    continue
                if cov > 1.0:
                    cov = 1.0
                pw.fill_rect(buf, surface_w, surface_h, px, py, 1, 1, color,
                             alpha * cov)

    def _draw_close(self, canvas: pw.PixelBuffer, right: int, top: int,
                    hover: bool) -> None:
        s = self.scale
        size = round(14 * s)
        color = COL_CLOSE_HOVER if hover else COL_FAINT
        x = right - size
        y = top + round(1 * s)
        if hover:
            pw.rounded_rect(canvas.buf, canvas.width, canvas.height,
                            x - round(3 * s), y - round(2 * s),
                            size + round(6 * s), size + round(4 * s),
                            round(5 * s), 0x2A2A2A, 0.85)
        inset = round(3 * s)
        thickness = max(1.0, 1.3 * s)
        self.stroke(canvas.buf, canvas.width, canvas.height,
                    x + inset, y + inset, x + size - inset, y + size - inset,
                    thickness, color, 0.95)
        self.stroke(canvas.buf, canvas.width, canvas.height,
                    x + size - inset, y + inset, x + inset, y + size - inset,
                    thickness, color, 0.95)


# --------------------------------------------------------------------------- #
#  Window
# --------------------------------------------------------------------------- #

ID_TIMER_FRAME = 1
ID_TIMER_WATCHDOG = 2
ID_TIMER_POINTER = 4          # drag + resize polling (16 ms while active)

HOTKEY_QUIT = 1
HOTKEY_TOPMOST = 2
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_F11 = 0x7A
VK_F12 = 0x7B

MENU_TOPMOST = 1001
MENU_ACRYLIC = 1002
MENU_BIGGER = 1003
MENU_SMALLER = 1004
MENU_RESET = 1005
MENU_RESET_POS = 1006
MENU_ABOUT = 1008
MENU_EXIT = 1009
MENU_AUTOSTART = 1010
MENU_TRAY_SHOW = 1020
MENU_TRAY_HIDE = 1021

CLASS_NAME = "MemorySupervisorPanel"

# pointer interactions
MODE_NONE = 0
MODE_MOVE = 1
MODE_RESIZE = 2


class SupervisorWindow:
    """Owns the Win32 window, the sampler and the repaint loop."""

    def __init__(self, config: Config) -> None:
        self.cfg = config
        self.sampler = Sampler(interval=config.sample_interval)
        self.renderer = PanelRenderer(config)

        self.hwnd = None
        self.canvas: pw.PixelBuffer | None = None
        self._wndproc = None
        self._win_event = None
        self._last_foreground = None
        self._hover_close = False
        self._hover_grip = False
        self._closing = False
        self._acrylic_label = ""
        self._dpi = 1.0
        self._pointer = MODE_NONE
        self._drag_offset = (0, 0)
        self._resize_origin = None
        self._cursor_pos = None
        self._dirty = False
        self._last_save = 0.0
        self._last_signature = None
        self._hotkeys = False
        self._tray: tray_win.TrayIcon | None = None
        self._tray_hidden = False

    # -- derived geometry --------------------------------------------------- #
    @property
    def scale(self) -> float:
        """Device pixels per UI unit (display DPI x user zoom)."""
        return self._dpi * self.cfg.scale

    def _device_size(self) -> tuple[int, int]:
        s = self.scale
        return (max(1, int(round(self.cfg.width * s))),
                max(1, int(round(self.cfg.height * s))))

    # -- setup -------------------------------------------------------------- #
    def create(self) -> None:
        self._wndproc = pw.make_wndproc(self._on_message)
        pw.register_window_class(CLASS_NAME, self._wndproc,
                                 instance=pw.kernel32.GetModuleHandleW(None))

        self._dpi = max(1.0, self._dpi_guess() / 96.0)
        w, h = self._device_size()
        x, y = self._initial_position(w, h)
        self.hwnd = pw.create_layered_popup(
            CLASS_NAME, "Memory Supervisor", width=w, height=h, x=x, y=y,
            # A tray icon alone is easy to miss, so the panel also gets a real
            # taskbar button; both refer to the same window.
            tool_window=not self.cfg.taskbar_button,
            app_window=self.cfg.taskbar_button,
            icon=pw.window_icon(),
        )
        self._dpi = max(1.0, pw.get_dpi_for_window(self.hwnd) / 96.0)
        w, h = self._device_size()

        if self.cfg.acrylic:
            self._acrylic_label = pw.enable_acrylic(
                self.hwnd,
                tint_alpha=int(round(self.cfg.acrylic_tint * 255)),
                tint_bgr=0x1C1410,
            )

        self._rebuild_canvas(w, h, x, y)

        try:
            self._win_event = pw.make_wineventproc(self._on_foreground_event)
            pw.user32.SetWinEventHook(
                C.EVENT_SYSTEM_FOREGROUND, C.EVENT_SYSTEM_FOREGROUND,
                None, self._win_event, 0, 0,
                C.WINEVENT_OUTOFCONTEXT | C.WINEVENT_SKIPOWNPROCESS,
            )
        except Exception:
            self._win_event = None

        pw.user32.SetTimer(self.hwnd, ID_TIMER_FRAME,
                           max(40, int(self.cfg.repaint_interval * 1000)), None)
        pw.user32.SetTimer(self.hwnd, ID_TIMER_WATCHDOG, 800, None)
        self._register_hotkeys()

        self._tray = tray_win.TrayIcon(
            self.hwnd,
            "Memory Supervisor",
            callback_message=tray_win.WM_TRAYICON,
        )
        self._tray.add()
        self._update_tray_tip()

        pw.user32.ShowWindow(self.hwnd, 5)          # SW_SHOW
        pw.raise_topmost(self.hwnd, show=True)
        self.sampler.start()
        self._apply_topmost(self.cfg.always_on_top)
        self.request_repaint(force=True)

    def _initial_position(self, w: int, h: int) -> tuple[int, int]:
        work = pw.get_work_area()
        margin = int(round(24 * self._dpi))
        if self.cfg.x is None or self.cfg.y is None:
            return (work.right - w - margin, work.top + margin)
        x = max(work.left - w + 60, min(int(self.cfg.x), work.right - 60))
        y = max(work.top, min(int(self.cfg.y), work.bottom - 40))
        return (int(x), int(y))

    @staticmethod
    def _dpi_guess() -> int:
        """DPI of the primary monitor, used before any window exists."""
        try:
            dc = pw.user32.GetDC(None)
            if dc:
                gdi32 = pw.gdi32
                gdi32.GetDeviceCaps.argtypes = [ctypes.c_void_p, ctypes.c_int]
                gdi32.GetDeviceCaps.restype = ctypes.c_int
                dpi = gdi32.GetDeviceCaps(dc, 88)          # LOGPIXELSX
                pw.user32.ReleaseDC(None, dc)
                if 72 <= dpi <= 480:
                    return dpi
        except Exception:
            pass
        return 96

    def _rebuild_canvas(self, w: int, h: int, x: int | None = None,
                        y: int | None = None) -> None:
        old = self.canvas
        self.canvas = pw.PixelBuffer(w, h)
        self.renderer.resize(w, h, self.scale)
        if x is not None and y is not None:
            pw.push_layered(self.hwnd, self.canvas.dc, x, y, w, h)
        if old is not None:
            old.destroy()

    # -- state -------------------------------------------------------------- #
    def _view_state(self) -> ViewState:
        snap = self.sampler.snapshot()
        return ViewState(
            percent=snap.percent if snap.valid else 0.0,
            used_gib=snap.used_gib,
            total_gib=snap.total_gib,
            avail_gib=snap.avail_gib,
            valid=snap.valid,
        )

    def request_repaint(self, *, force: bool = False) -> None:
        """Repaint only when the picture would actually differ."""
        if not self.hwnd or self.canvas is None or self._closing:
            return
        state = self._view_state()
        signature = (
            self._hover_close, self._hover_grip, self._pointer,
            round(state.percent, 1) if state.valid else -1.0,
            round(state.used_gib, 2), int(time.time()),
        )
        if not force and signature == self._last_signature:
            return
        self._last_signature = signature

        rect = pw.RECT()
        pw.user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        self.renderer.draw(self.canvas, state,
                           hover_close=self._hover_close,
                           hover_grip=self._hover_grip,
                           acrylic_label=self._acrylic_label)
        if self._tray is not None:
            self._update_tray_tip()
        pw.push_layered(self.hwnd, self.canvas.dc, rect.left, rect.top,
                        self.canvas.width, self.canvas.height)

    # -- always-on-top ------------------------------------------------------ #
    def _apply_topmost(self, enabled: bool) -> None:
        self.cfg.always_on_top = bool(enabled)
        if not self.hwnd:
            return
        if enabled:
            pw.raise_topmost(self.hwnd, show=True)
        else:
            pw.user32.SetWindowPos(self.hwnd, ctypes.c_void_p(C.HWND_NOTOPMOST),
                                   0, 0, 0, 0,
                                   C.SWP_NOMOVE | C.SWP_NOSIZE | C.SWP_NOACTIVATE)
        self._dirty = True

    def _assert_topmost(self) -> None:
        if self.cfg.always_on_top and self.hwnd and not self._closing:
            pw.raise_topmost(self.hwnd)

    def _on_foreground_event(self, _hook, _event, _hwnd, _id_object, _id_child,
                             _thread, _time) -> None:
        try:
            self._assert_topmost()
        except Exception:
            pass

    # -- message loop ------------------------------------------------------- #
    def run(self) -> int:
        msg = pw.MSG()
        while True:
            ret = pw.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret in (0, -1):
                break
            pw.user32.TranslateMessage(ctypes.byref(msg))
            pw.user32.DispatchMessageW(ctypes.byref(msg))
        return 0

    def _on_message(self, hwnd, message, wparam, lparam):
        try:
            return self._handle_message(hwnd, message, wparam, lparam)
        except Exception as exc:            # never let an exception kill the loop
            print(f"[memsup] message 0x{message:04X} failed: {exc!r}",
                  file=sys.stderr)
            return pw.user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _handle_message(self, hwnd, message, wparam, lparam):
        if message == C.WM_TIMER:
            if wparam == ID_TIMER_FRAME:
                self.request_repaint()
                self._flush_config_if_due()
            elif wparam == ID_TIMER_WATCHDOG:
                self._last_foreground = pw.user32.GetForegroundWindow()
                self._assert_topmost()
            elif wparam == ID_TIMER_POINTER:
                self._poll_pointer()
            return 0

        if message == C.WM_NCHITTEST:
            # Never HTCAPTION: that would hand the drag to DefWindowProc's modal
            # move loop, which only exits on a mouse-button-up and can wedge the
            # panel for good if one is lost.  Everything is HTCLIENT and handled
            # by _poll_pointer.
            return C.HTCLIENT

        if message == C.WM_SETCURSOR:
            return 1

        if message == C.WM_MOUSEMOVE:
            over_close, over_grip = self._hit_areas(lparam)
            if (over_close, over_grip) != (self._hover_close, self._hover_grip):
                self._hover_close = over_close
                self._hover_grip = over_grip
                self.request_repaint(force=True)
            track = pw.TRACKMOUSEEVENT()
            track.cbSize = ctypes.sizeof(pw.TRACKMOUSEEVENT)
            track.dwFlags = C.TME_LEAVE
            track.hwndTrack = hwnd
            pw.user32.TrackMouseEvent(ctypes.byref(track))
            return 0

        if message == C.WM_MOUSELEAVE:
            if self._hover_close or self._hover_grip:
                self._hover_close = self._hover_grip = False
                self.request_repaint(force=True)
            return 0

        if message == C.WM_LBUTTONDOWN:
            over_close, over_grip = self._hit_areas(lparam)
            if over_close:
                self.close()
                return 0
            self._begin_pointer(MODE_RESIZE if over_grip else MODE_MOVE)
            return 0

        if message == C.WM_LBUTTONUP:
            if self._pointer:
                self._end_pointer()
            return 0

        if message == C.WM_CAPTURECHANGED:
            # The panel never takes the capture, so this is informational: it
            # must NOT end a drag (that used to cancel every drag at once).
            return 0

        if message == C.WM_EXITSIZEMOVE:
            self._remember_position()
            return 0

        if message == C.WM_RBUTTONUP:
            self._show_menu()
            return 0

        if self._tray is not None and self._tray.handles(message):
            # Explorer restarted: the notification area lost our icon
            self._tray.on_taskbar_created()
            return 0

        if message == tray_win.WM_TRAYICON:
            self._on_tray_message(lparam)
            return 0

        if message == C.WM_HOTKEY:
            if wparam == HOTKEY_QUIT:
                self.close()
            elif wparam == HOTKEY_TOPMOST:
                self._apply_topmost(not self.cfg.always_on_top)
            return 0

        if message == C.WM_MOUSEWHEEL:
            delta = pw.signed_word(int(wparam) >> 16)
            if delta:
                self.zoom(0.1 if delta > 0 else -0.1)
            return 0

        if message == C.WM_ERASEBKGND:
            return 1

        if message == C.WM_PAINT:
            pw.user32.ValidateRect(hwnd, None)
            return 0

        if message in (C.WM_DISPLAYCHANGE, C.WM_SETTINGCHANGE):
            self._recheck_geometry()
            return 0

        if message == C.WM_CLOSE:
            self.close()
            return 0

        if message == C.WM_DESTROY:
            self._teardown()
            pw.user32.PostQuitMessage(0)
            return 0

        if message == C.WM_QUERYENDSESSION:
            self.cfg.save()
            return 1

        return pw.user32.DefWindowProcW(hwnd, message, wparam, lparam)

    # -- notification-area icon --------------------------------------------- #
    def _on_tray_message(self, lparam: int) -> None:
        """React to a click on the tray icon."""
        code = tray_win.TrayIcon.notify_code(int(lparam))
        if code in (tray_win.WM_LBUTTONUP, tray_win.WM_LBUTTONDBLCLK):
            self.toggle_visibility()
        elif code in (tray_win.WM_RBUTTONUP, tray_win.WM_CONTEXTMENU):
            self._show_tray_menu()

    def toggle_visibility(self) -> None:
        if not self.hwnd:
            return
        if self._tray_hidden or not pw.user32.IsWindowVisible(self.hwnd):
            pw.user32.ShowWindow(self.hwnd, 5)          # SW_SHOW
            pw.raise_topmost(self.hwnd, show=True)
            self._tray_hidden = False
            self.request_repaint(force=True)
        else:
            pw.user32.ShowWindow(self.hwnd, 0)          # SW_HIDE
            self._tray_hidden = True
        self._update_tray_tip()

    def _show_tray_menu(self) -> None:
        items = [
            (MENU_TRAY_HIDE if not self._tray_hidden else MENU_TRAY_SHOW,
             "Hide panel" if not self._tray_hidden else "Show panel"),
            (0, ""),
            (MENU_TOPMOST, "Always on top"),
            (MENU_ACRYLIC, "Frosted glass (blur)"),
            (0, ""),
            (MENU_BIGGER, "Bigger"),
            (MENU_SMALLER, "Smaller"),
            (MENU_RESET, "Reset size"),
            (MENU_RESET_POS, "Reset position"),
            (0, ""),
            (MENU_AUTOSTART, "Autostart on login..."),
            (MENU_ABOUT, "About"),
            (0, ""),
            (MENU_EXIT, "Exit"),
        ]
        if self._tray_hidden:
            items[0] = (MENU_TRAY_SHOW, "Show panel")
        else:
            items[0] = (MENU_TRAY_HIDE, "Hide panel")
        checked = {MENU_TOPMOST: self.cfg.always_on_top,
                   MENU_ACRYLIC: self.cfg.acrylic}
        cmd = tray_win.show_tray_menu(self.hwnd, items, checked=checked)
        if cmd:
            self._on_menu_command(int(cmd))

    def _update_tray_tip(self) -> None:
        if self._tray is None:
            return
        snap = self.sampler.snapshot()
        if snap.valid:
            tip = (f"Memory Supervisor\n{snap.used_gib:.1f} / "
                   f"{snap.total_gib:.1f} GB used ({snap.percent:.0f}%)")
        else:
            tip = "Memory Supervisor"
        if self._tray_hidden:
            tip += "\n(panel hidden - click to show)"
        self._tray.update_tip(tip)

    # -- pointer handling --------------------------------------------------- #
    # Deliberately not the system's modal move/resize loops: those block this
    # message loop until a mouse-button-up arrives, so a single lost message
    # leaves the panel frozen (busy cursor, unclosable).  Instead a 16 ms timer
    # polls the cursor and checks that the button is still physically down, which
    # makes both gestures self-correcting.
    def _hit_areas(self, lparam) -> tuple[bool, bool]:
        """Return ``(over_close, over_grip)`` for a client-area lparam."""
        if not self.canvas:
            return (False, False)
        x = pw.signed_word(int(lparam))
        y = pw.signed_word(int(lparam) >> 16)
        s = self.scale
        pad = round(14 * s)
        box = round(19 * s)
        top = pad - round(1 * s)
        over_close = (self.canvas.width - pad - box <= x <= self.canvas.width - pad
                      and top <= y <= top + box)
        # generous corner zone: the glyph is small, so the hot area is a square
        # as tall/wide as the grip plus its padding
        edge = max(6, round(BORDER * s))
        over_grip = (x >= self.canvas.width - edge
                     and y >= self.canvas.height - edge)
        return (over_close, over_grip)

    def _begin_pointer(self, mode: int) -> None:
        pt = pw.POINT()
        if not pw.user32.GetCursorPos(ctypes.byref(pt)):
            return
        rect = pw.RECT()
        if not pw.user32.GetWindowRect(self.hwnd, ctypes.byref(rect)):
            return
        self._cursor_pos = (pt.x, pt.y)
        if mode == MODE_MOVE:
            self._drag_offset = (pt.x - rect.left, pt.y - rect.top)
        else:
            self._resize_origin = (pt.x, pt.y, rect.right - rect.left)
        self._pointer = mode
        # No SetCapture: on a WS_EX_NOACTIVATE window Windows answers with
        # WM_CAPTURECHANGED and takes the capture back, which aborted gestures.
        # Polling only needs the cursor position.
        pw.user32.SetTimer(self.hwnd, ID_TIMER_POINTER, 16, None)
        self.request_repaint(force=True)

    def _end_pointer(self) -> None:
        self._pointer = MODE_NONE
        pw.user32.KillTimer(self.hwnd, ID_TIMER_POINTER)
        self._remember_position()
        self._flush_config()
        self.request_repaint(force=True)

    def _poll_pointer(self) -> None:
        """Track the cursor while a gesture is active; self-terminate on release."""
        if self._pointer == MODE_NONE:
            pw.user32.KillTimer(self.hwnd, ID_TIMER_POINTER)
            return
        # VK_LBUTTON's high bit is set while the button is physically down, so a
        # lost WM_LBUTTONUP cannot strand the panel mid-drag.
        if not (pw.user32.GetAsyncKeyState(0x01) & 0x8000):
            self._end_pointer()
            return

        pt = pw.POINT()
        if not pw.user32.GetCursorPos(ctypes.byref(pt)):
            return
        if self._cursor_pos == (pt.x, pt.y):
            return
        self._cursor_pos = (pt.x, pt.y)

        if self._pointer == MODE_MOVE:
            x = pt.x - self._drag_offset[0]
            y = pt.y - self._drag_offset[1]
            pw.user32.SetWindowPos(self.hwnd, ctypes.c_void_p(C.HWND_TOPMOST),
                                   x, y, 0, 0,
                                   C.SWP_NOSIZE | C.SWP_NOACTIVATE
                                   | C.SWP_NOOWNERZORDER)
        else:
            self._apply_resize(pt.x, pt.y)

    def _apply_resize(self, cursor_x: int, cursor_y: int) -> None:
        """Scale the whole UI proportionally to follow the bottom-right corner."""
        origin = self._resize_origin
        if origin is None:
            return
        x0, y0, w0 = origin
        if w0 <= 0:
            return
        base_w = max(1.0, float(self.cfg.width))
        base_h = max(1.0, float(self.cfg.height))
        # follow whichever axis the user pulled most, then keep the aspect ratio
        grow_x = (cursor_x - x0) / w0
        h0 = int(round(self.cfg.height * (w0 / base_w)))
        grow_y = (cursor_y - y0) / max(1.0, float(h0))
        grow = grow_x if abs(grow_x) >= abs(grow_y) else grow_y
        factor = max(0.15, 1.0 + grow)

        new_scale = max(MIN_SCALE, min(MAX_SCALE, self.cfg.scale * factor))
        if abs(new_scale - self.cfg.scale) < 0.002:
            return
        self.cfg.scale = new_scale
        w, h = self._device_size()

        rect = pw.RECT()
        pw.user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        self._rebuild_canvas(w, h)
        pw.push_layered(self.hwnd, self.canvas.dc, rect.left, rect.top, w, h)
        self._resize_origin = (x0, y0, w)
        self._dirty = True
        self.request_repaint(force=True)

    def zoom(self, delta: float) -> None:
        """Scale the UI proportionally, keeping the top-left corner pinned."""
        new_scale = max(MIN_SCALE, min(MAX_SCALE, self.cfg.scale + delta))
        if abs(new_scale - self.cfg.scale) < 1e-6:
            return
        rect = pw.RECT()
        pw.user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        self.cfg.scale = new_scale
        w, h = self._device_size()
        self._rebuild_canvas(w, h)
        pw.push_layered(self.hwnd, self.canvas.dc, rect.left, rect.top, w, h)
        self._dirty = True
        self.request_repaint(force=True)

    # -- hotkeys ------------------------------------------------------------ #
    def _register_hotkeys(self) -> None:
        """Emergency controls that work even if the mouse misbehaves."""
        u = pw.user32
        try:
            ok_quit = u.RegisterHotKey(self.hwnd, HOTKEY_QUIT,
                                       MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_F12)
            ok_top = u.RegisterHotKey(self.hwnd, HOTKEY_TOPMOST,
                                      MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_F11)
            self._hotkeys = bool(ok_quit or ok_top)
        except Exception:
            self._hotkeys = False

    def _unregister_hotkeys(self) -> None:
        if not self._hotkeys or not self.hwnd:
            return
        try:
            pw.user32.UnregisterHotKey(self.hwnd, HOTKEY_QUIT)
            pw.user32.UnregisterHotKey(self.hwnd, HOTKEY_TOPMOST)
        except Exception:
            pass
        self._hotkeys = False

    # -- helpers ------------------------------------------------------------ #
    def _remember_position(self) -> None:
        if not self.hwnd:
            return
        rect = pw.RECT()
        if pw.user32.GetWindowRect(self.hwnd, ctypes.byref(rect)):
            self.cfg.x = int(rect.left)
            self.cfg.y = int(rect.top)
            self._dirty = True

    def _flush_config(self) -> None:
        self._dirty = False
        self._last_save = time.monotonic()
        self.cfg.save()

    def _flush_config_if_due(self) -> None:
        now = time.monotonic()
        if self._dirty and now - self._last_save > 5.0:
            self._flush_config()

    def _recheck_geometry(self) -> None:
        """Re-derive the surface when the display DPI changes."""
        if not self.hwnd or not self.canvas:
            return
        dpi = max(1.0, min(4.0, pw.get_dpi_for_window(self.hwnd) / 96.0))
        if abs(dpi - self._dpi) <= 0.01:
            self._remember_position()
            self.request_repaint(force=True)
            return
        self._dpi = dpi
        w, h = self._device_size()
        if not (200 <= w <= 4000 and 80 <= h <= 3000):
            self._remember_position()
            return
        work = pw.get_work_area()
        rect = pw.RECT()
        pw.user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        x = max(work.left - w + 60, min(rect.left, work.right - 60))
        y = max(work.top, min(rect.top, work.bottom - 40))
        self._rebuild_canvas(w, h)
        pw.user32.SetWindowPos(self.hwnd, ctypes.c_void_p(C.HWND_TOPMOST), x, y,
                               w, h, C.SWP_NOACTIVATE | C.SWP_SHOWWINDOW)
        self._dirty = True
        self.request_repaint(force=True)

    def reset_size(self) -> None:
        rect = pw.RECT()
        pw.user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        self.cfg.width, self.cfg.height = BASE_WIDTH, BASE_HEIGHT
        self.cfg.scale = 1.0
        w, h = self._device_size()
        self._rebuild_canvas(w, h)
        pw.push_layered(self.hwnd, self.canvas.dc, rect.left, rect.top, w, h)
        self._dirty = True
        self.request_repaint(force=True)

    def reset_position(self) -> None:
        work = pw.get_work_area()
        w = self.canvas.width if self.canvas else self.cfg.width
        margin = int(round(24 * self._dpi))
        x, y = work.right - w - margin, work.top + margin
        self.cfg.x, self.cfg.y = x, y
        pw.user32.SetWindowPos(self.hwnd, ctypes.c_void_p(C.HWND_TOPMOST), x, y,
                               0, 0,
                               C.SWP_NOSIZE | C.SWP_NOACTIVATE | C.SWP_SHOWWINDOW)
        self._dirty = True
        self.request_repaint(force=True)

    def toggle_acrylic(self) -> None:
        self.cfg.acrylic = not self.cfg.acrylic
        if self.cfg.acrylic:
            self._acrylic_label = pw.enable_acrylic(
                self.hwnd, tint_alpha=int(round(self.cfg.acrylic_tint * 255)),
                tint_bgr=0x1C1410)
        else:
            pw.disable_backdrop(self.hwnd)
            self._acrylic_label = ""
        self.renderer.invalidate_background()
        self._dirty = True
        self.request_repaint(force=True)

    def adjust_opacity(self, delta: float) -> None:
        self.cfg.background_alpha = max(0.05, min(1.0,
                                                 self.cfg.background_alpha + delta))
        self.renderer.invalidate_background()
        self._dirty = True
        self.request_repaint(force=True)

    # -- context menu ------------------------------------------------------- #
    def _show_menu(self) -> None:
        menu = pw.user32.CreatePopupMenu()
        if not menu:
            return
        try:
            def add(flags: int, cmd: int, text) -> None:
                pw.user32.AppendMenuW(menu, flags, cmd, text)

            def checked(on: bool) -> int:
                return C.MF_STRING | (C.MF_CHECKED if on else C.MF_UNCHECKED)

            add(checked(self.cfg.always_on_top), MENU_TOPMOST, "Always on top")
            add(checked(self.cfg.acrylic), MENU_ACRYLIC, "Frosted glass (blur)")
            add(C.MF_SEPARATOR, 0, None)
            add(C.MF_STRING, MENU_BIGGER, "Bigger\tCtrl+Wheel up")
            add(C.MF_STRING, MENU_SMALLER, "Smaller\tCtrl+Wheel down")
            add(C.MF_STRING, MENU_RESET, "Reset size")
            add(C.MF_STRING, MENU_RESET_POS, "Reset position")
            add(C.MF_SEPARATOR, 0, None)
            add(C.MF_STRING, MENU_AUTOSTART, "Autostart on login...")
            add(C.MF_STRING, MENU_ABOUT, "About")
            add(C.MF_SEPARATOR, 0, None)
            add(C.MF_STRING, MENU_EXIT, "Exit")

            pt = pw.POINT()
            pw.user32.GetCursorPos(ctypes.byref(pt))
            pw.user32.SetForegroundWindow(self.hwnd)
            cmd = pw.user32.TrackPopupMenu(
                menu, C.TPM_RIGHTBUTTON | C.TPM_RETURNCMD,
                pt.x, pt.y, 0, self.hwnd, None)
            if cmd:
                self._on_menu_command(int(cmd))
        finally:
            pw.user32.DestroyMenu(menu)

    def _on_menu_command(self, cmd: int) -> None:
        if cmd == MENU_TOPMOST:
            self._apply_topmost(not self.cfg.always_on_top)
        elif cmd == MENU_ACRYLIC:
            self.toggle_acrylic()
        elif cmd == MENU_BIGGER:
            self.zoom(0.15)
        elif cmd == MENU_SMALLER:
            self.zoom(-0.15)
        elif cmd == MENU_RESET:
            self.reset_size()
        elif cmd == MENU_RESET_POS:
            self.reset_position()
        elif cmd == MENU_AUTOSTART:
            ok, message = create_startup_shortcut()
            pw.user32.MessageBoxW(self.hwnd, message, "Memory Supervisor",
                                  C.MB_OK | (0 if ok else 0x00000030))
        elif cmd == MENU_ABOUT:
            self._show_about()
        elif cmd == MENU_TRAY_SHOW:
            self._tray_hidden = True      # force the show branch
            self.toggle_visibility()
        elif cmd == MENU_TRAY_HIDE:
            self._tray_hidden = False     # force the hide branch
            self.toggle_visibility()
        elif cmd == MENU_EXIT:
            self.close()

    def _show_about(self) -> None:
        proc_mb = pw.process_working_set_bytes() / (1024 * 1024)
        surface = f"{self.canvas.width}x{self.canvas.height}" if self.canvas else "?"
        text = (
            "Memory Supervisor - always-on-top memory monitor\n\n"
            f"Effect: {self._acrylic_label or 'none'}\n"
            f"Always on top: {'yes' if self.cfg.always_on_top else 'no'}\n"
            f"Size: {self.cfg.width}x{self.cfg.height} units at "
            f"{self.scale * 100:.0f}%  ({surface} px)\n"
            f"Refresh: {self.cfg.repaint_interval * 1000:.0f} ms    "
            f"Sample: {self.cfg.sample_interval * 1000:.0f} ms\n"
            f"Panel working set: {proc_mb:.1f} MB\n\n"
            "Drag to move.  Drag the bottom-right corner to resize.\n"
            "Ctrl+Wheel zooms.  Ctrl+Alt+F12 quits."
        )
        pw.user32.MessageBoxW(self.hwnd, text, "About Memory Supervisor", C.MB_OK)

    # -- shutdown ----------------------------------------------------------- #
    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._remember_position()
        self.cfg.save()
        if self.hwnd and pw.user32.IsWindow(self.hwnd):
            pw.user32.DestroyWindow(self.hwnd)

    def _teardown(self) -> None:
        self.sampler.stop()
        self._unregister_hotkeys()
        if self._tray is not None:
            self._tray.remove()
            self._tray = None
        if self.hwnd:
            for timer in (ID_TIMER_FRAME, ID_TIMER_WATCHDOG, ID_TIMER_POINTER):
                pw.user32.KillTimer(self.hwnd, timer)
        if self._win_event is not None:
            try:
                pw.user32.UnhookWinEvent(self._win_event)
            except Exception:
                pass
            self._win_event = None
        if self.canvas is not None:
            self.canvas.destroy()
            self.canvas = None


# --------------------------------------------------------------------------- #
#  Autostart helper
# --------------------------------------------------------------------------- #

def create_startup_shortcut() -> tuple[bool, str]:
    """Create a Startup-folder shortcut that launches the panel at login.

    From a packaged executable the shortcut targets the .exe directly; from
    source it uses run_silent.vbs, which finds a Python interpreter itself.
    """
    project = app_dir()
    if is_frozen():
        target, arguments = os.path.abspath(sys.executable), ""
    elif os.path.isfile(os.path.join(project, "run_silent.vbs")):
        target = os.path.join(project, "run_silent.vbs")
        arguments = ""
    else:
        pythonw = _resolve_pythonw()
        if not pythonw:
            return False, ("Could not find pythonw.exe or run_silent.vbs.\n\n"
                           "Install Python, or start the panel with run.bat.")
        target = pythonw
        arguments = f'"{os.path.join(project, "memsup.py")}"'

    startup = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                           "Start Menu", "Programs", "Startup")
    if not os.path.isdir(startup):
        return False, f"Startup folder not found:\n{startup}"
    link = os.path.join(startup, "Memory Supervisor.lnk")
    vbs = (
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'Set lnk = sh.CreateShortcut("{link}")\r\n'
        f'lnk.TargetPath = "{target}"\r\n'
        f'lnk.Arguments = "{arguments}"\r\n'
        f'lnk.WorkingDirectory = "{project}"\r\n'
        'lnk.WindowStyle = 7\r\n'
        'lnk.Description = "Memory Supervisor"\r\n'
        'lnk.Save\r\n'
    )
    tmp = os.path.join(project, "tools", "_shortcut.vbs")
    try:
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(vbs)
        rc = os.system(f'cscript //nologo "{tmp}"')
        os.remove(tmp)
    except OSError as exc:
        return False, f"Could not create the shortcut: {exc}"
    if rc == 0 and os.path.exists(link):
        return True, f"Autostart enabled:\n{link}"
    return False, "Could not create the shortcut."


def _resolve_pythonw() -> str | None:
    """Best interpreter for a console-free start, or None if unavailable."""
    here = os.path.dirname(os.path.abspath(__file__))
    project = os.path.dirname(here)
    candidates = [
        os.path.join(project, "runtime", "pythonw.exe"),
        os.path.join(os.path.dirname(sys.executable), "pythonw.exe"),
        sys.executable.replace("python.exe", "pythonw.exe"),
        sys.executable,
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    try:
        with open(os.path.join(project, "launcher.ini"), "r",
                  encoding="utf-8") as fh:
            for line in fh:
                if line.lower().startswith("python="):
                    path = line.split("=", 1)[1].strip()
                    if os.path.isfile(path):
                        return path
    except OSError:
        pass
    return None

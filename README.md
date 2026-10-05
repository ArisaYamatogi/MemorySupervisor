# Memory Supervisor

A lightweight, always-on-top desktop panel showing how much of your physical
memory is in use — with a frosted-glass background.

Built for Windows 11 (verified on 25H2 26200). Ships both as a
standalone `.exe` and as source that needs nothing but Python.

---

## What it shows

| Element | Meaning |
| --- | --- |
| Big percentage | Physical memory in use (`GlobalMemoryStatusEx`) |
| `USED MEMORY` / `x.xx GB` | Amount currently in use |
| **Yellow horizontal bar** | The whole of physical RAM, with the used portion filled in yellow |
| `x.xx / x.xx GB` | Used / total physical memory |
| Bottom-right grip | Drag to resize (the entire UI scales proportionally) |

## Running it

The quickest way — no Python needed:

```
MemorySupervisor.exe
```

From source (any of these):

```
run_silent.vbs        no console window      <- normal use
run.bat               with a console, useful for diagnostics
python memsup.py      direct
```

Launchers look for the interpreter in this order: a `runtime\` folder next to the
script, `launcher.ini`, `pythonw.exe`/`python.exe` on `PATH`, then the `py`
launcher. `launcher.ini` is filled in automatically on first run.

## Finding and controlling it

The panel is an always-on-top popup, so it is reachable in two places:

* **Notification area (system tray)** — hover for a tooltip showing current
  usage; **left-click** hides/shows the panel, **right-click** opens its menu.
* **Taskbar** — the panel has a taskbar button, so you can also bring it up from
  there (window style `WS_EX_APPWINDOW`).

| Action | Result |
| --- | --- |
| **Drag anywhere on the panel** | Moves it; the position is remembered |
| **Drag the bottom-right corner** | Scales the whole UI proportionally |
| **Ctrl + mouse wheel** | Zoom in / out |
| **Right-click the panel or the tray icon** | Menu: show/hide, always-on-top, frosted glass, size, position, autostart, about, exit |
| **Click the ×** | Quit |
| **Ctrl+Alt+F12** | Quit (works even mid-drag, without the mouse) |
| **Ctrl+Alt+F11** | Toggle always-on-top |

The panel never steals focus (`WS_EX_NOACTIVATE`) and re-asserts its topmost
position whenever the foreground window changes.

## Building the executable

```
python build_exe.py
```

Writes `dist\MemorySupervisor.exe` — a one-file, console-free build with the
program icon embedded (~7 MB). PyInstaller is installed on demand into
`tools\buildenv` rather than into your system Python; nothing else is needed,
because the panel uses only `ctypes` and the standard library.

`python build_exe.py --console` builds `MemorySupervisor-console.exe` instead,
which keeps a console attached so startup problems are visible. Both builds
accept `--diag`, which prints a startup report (frozen state, tray registration,
config location).

## Requirements

* Windows 11 (developed and verified on 25H2, build 26200)
* Python 3.8+ **only when running from source** — no third-party packages

## Files

```
MemorySupervisor/
├─ MemorySupervisor.exe      standalone build (no Python needed)
├─ memsup.py                 entry point (single-instance check, CLI, DPI setup)
├─ memsup/
│  ├─ constants.py           the Win32 constants that are actually used
│  ├─ platform_win.py        ctypes layer: window, blur, layered blitting,
│  │                         GDI text rasterising, premultiplied compositing
│  ├─ tray_win.py            notification-area icon + its popup menu
│  ├─ meminfo.py             background sampler
│  └─ app.py                 panel renderer + window/message loop
├─ tests/selftest.py         43 automated checks - run after touching window code
├─ tests/layout_check.py     layout/transparency checks, also used by selftest
├─ build_exe.py              builds the executable
├─ run.bat / run_silent.vbs  source launchers
├─ launcher.ini              recorded interpreter (auto-filled)
├─ config.json               saved state (auto-created)
└─ docs/panel.png
```

## Tests

```
python tests\selftest.py
```

It starts the panel as a real process and asserts the behaviour that is easy to
regress: the frosted-glass effect, topmost re-assertion, dragging (including a
drag whose mouse-up is deliberately never delivered), proportional resizing, the
tray icon, the taskbar button, the bar's position at every zoom level, and
memory/CPU ceilings. Exit code 0 means everything passed.

## How it works

### The frosted glass (this is the subtle part)

The window is a `WS_EX_LAYERED` popup painted with `UpdateLayeredWindow` using a
premultiplied BGRA buffer, which gives per-pixel alpha.

For the blur, `platform_win.enable_acrylic` uses **`SetWindowCompositionAttribute`
with `ACCENT_ENABLE_BLURBEHIND`**. It deliberately does *not* rely on
`DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE)`: on Windows 11 25H2 that call
**succeeds** on a layered window — and even reads back as `3` (acrylic) through
`DwmGetWindowAttribute` — yet composites nothing behind it, so the panel renders
as a flat dark rectangle. That mismatch is easy to miss because the API reports
success, so the automated test measures actual screen pixels instead of trusting
the return value.

Because the blur sits *behind* the panel, the panel's own fill has to stay light.
It defaults to 46 % opacity with a 32 % gradient tint; heavier values bury the
blurred desktop and the panel looks black again. Both are editable in
`config.json` (`background_alpha`, `acrylic_tint`).

### Text

Glyphs are rasterised by GDI into a small private black surface and the resulting
coverage is blended into the panel by hand. Doing the blend ourselves is what
makes antialiased text work over the blur: GDI's own blending would paint an
opaque box behind every string.

### Staying on top

`HWND_TOPMOST` is set at creation and re-asserted on every
`EVENT_SYSTEM_FOREGROUND` (via `SetWinEventHook`) plus a 0.8 s watchdog, which
keeps the panel above maximised and borderless-fullscreen windows. One honest
limitation: a **true exclusive-fullscreen** application (DirectX fullscreen mode,
not borderless) owns the display and can only be covered by a UIAccess,
code-signed binary — an OS restriction, not a bug here.

### Dragging and resizing are implemented by hand

Earlier versions made the panel a "caption" area (`HTCAPTION` from
`WM_NCHITTEST`), which hands the gesture to the system's modal move loop inside
`DefWindowProc`. That loop only returns when a mouse-button-up message arrives; if
one is lost the message loop stops pumping, the cursor turns into a busy ring and
the panel can no longer be closed.

Both gestures are therefore driven by the panel itself, from a 16 ms timer that
reads the cursor and **checks `GetAsyncKeyState(VK_LBUTTON)`, ending the gesture
when the button is up**. The end condition is the physical button state rather
than a message, so a lost mouse-up can never wedge the panel. The panel also never
calls `SetCapture`: on a `WS_EX_NOACTIVATE` window Windows answers with
`WM_CAPTURECHANGED` and takes the capture back, which aborted every gesture one
message after it started.

### The layout

At 1.0 zoom the panel is **400x105 UI units**: just the header, the big number,
the bar label and the bar, with no dead space at the top or the bottom.

Getting there needed two non-obvious things:

* **Positioning text by its ink, not by its font size.** A 34 px font puts its
  first ink 13 px below the drawing origin (internal leading), and the smaller
  sizes have the same effect at their own scale. Laying the panel out from the
  font sizes therefore reserved far more room than the text used, which is what
  produced the empty strip at the top. `LAYOUT_STACK` now lists the measured
  ink heights, and `content_height()` sums that very list, so the panel height
  and the drawing positions cannot drift apart.
* **One flat translucency.** A vertical gradient used to sit on top of the card
  fill, which made the upper half of the panel lighter than the lower half. The
  entire card is now a single fill at one alpha value, so the transparency is
  identical everywhere (the test asserts exactly one translucent colour).

The resize grip takes the panel's bottom-right corner and everything scales
proportionally from there.

### Not redrawing needlessly

Between samples nothing changes, so a signature is compared before each repaint
and identical frames are skipped. The card, headings and bar track are cached as
one sprite and copied with a single `memcpy`.

## Performance

Measured on this machine (15.4 GB RAM, 200 % display scaling):

| Metric | Value |
| --- | --- |
| Working set | ~30 MB |
| Idle CPU | ~4 % of one core |
| Executable size | 7.3 MB |
| Memory read cost | ~50 µs |

## Troubleshooting

**Nothing appears.** Another copy is probably already running — only one panel is
allowed per session (a named mutex enforces it). Look for the tray icon, or run
`run.bat` / `MemorySupervisor-console.exe` to see console output.

**The panel has an empty strip at the top or bottom.** That should not happen:
the height is derived from the content. If you previously zoomed with the mouse
wheel, the saved scale in config.json persists - right-click -> *Reset size*.

**The panel looks solid black, not frosted.** Something behind it is itself
black, or the blur is switched off — right-click → *Frosted glass (blur)*.
Right-click → About reports which effect is active (`blur`, `acrylic`,
`dwm-acrylic`, `mica` or `none`).

**The tray icon is in the overflow flyout.** Windows hides new icons by default;
open the `^` chevron next to the clock and drag the icon onto the taskbar, or
enable it in Settings → Personalisation → Taskbar → Other system tray icons. The
taskbar button works regardless.

**The panel seems stuck / the cursor shows a busy ring.** This could not happen
with the current design, but if it ever does: press **Ctrl+Alt+F12**, or run

```
taskkill /F /IM MemorySupervisor.exe
taskkill /F /IM pythonw.exe
```

**The number disagrees with Task Manager slightly.** Windows reports "in use" in
several ways; this panel uses `total - available`, the same definition Task
Manager's Memory view uses, but compressed memory and cache accounting can shift
the two apart a little.

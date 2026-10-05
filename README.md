# Memory Supervisor
### English Version
[中文版本](https://github.com/ArisaYamatogi/MemorySupervisor/blob/main/README_zh_CN.md)

This is a lightweight (~30MB RAM use), always-on-top desktop panel showing how much of your physical
memory is in use.

Built for Windows 11 (verified on 25H2 26200)

---

## What it shows

| Element | Meaning |
| --- | --- |
| Big percentage | Physical memory in use (`GlobalMemoryStatusEx`) |
| Horizontal bar | The whole of physical RAM, with the used portion filled in yellow |
| `x.xx / x.xx GB` | Used / total physical memory |
| Bottom-right grip | Drag to resize (the entire UI scales proportionally) |

## Requirements

* Windows 11 (developed and verified on 25H2, build 26200)
* Python 3.8+ **only when running from source** — no third-party packages

## Running it

Just simply double click

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

## Control

| Action & Hotkeys | Result |
| --- | --- |
| **Drag anywhere on the panel** | Moves it; the position is remembered |
| **Drag the bottom-right corner** | Scales the whole UI proportionally |
| **Ctrl + mouse wheel** | Zoom in / out |
| **Right-click the panel or the tray icon** | Menu: show/hide, always-on-top, frosted glass, size, position, autostart, about, exit |
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
[Click for Details](https://github.com/ArisaYamatogi/MemorySupervisor/blob/main/howItWorks.md)


## Troubleshooting
[Click for Details](https://github.com/ArisaYamatogi/MemorySupervisor/blob/main/troubleshooting.md)
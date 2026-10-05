#!/usr/bin/env python3
"""Memory Supervisor - entry point.

Run with ``pythonw.exe memsup.py`` for a console-free start, or ``python memsup.py``
to see diagnostics in the terminal.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys

# Allow running straight from the project folder (python memsup.py).  When the
# program is packaged as an executable, PyInstaller has already set sys.path up.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from memsup import __version__, platform_win as pw  # noqa: E402
from memsup.app import Config, SupervisorWindow  # noqa: E402

MUTEX_NAME = "Local\\MemorySupervisorPanel.SingleInstance"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="memsup",
        description="Always-on-top memory usage monitor with an acrylic panel.",
    )
    parser.add_argument("--reset-position", action="store_true",
                        help="ignore the saved position and pin the panel top-right")
    parser.add_argument("--interval", type=float, default=None,
                        help="sampling interval in seconds (0.2 - 2.0)")
    parser.add_argument("--no-acrylic", action="store_true",
                        help="start with a plain translucent panel")
    parser.add_argument("--not-topmost", action="store_true",
                        help="start without always-on-top")
    parser.add_argument("--width", type=int, default=None, help="panel width in DIP")
    parser.add_argument("--height", type=int, default=None, help="panel height in DIP")
    parser.add_argument("--version", action="version",
                        version=f"Memory Supervisor {__version__}")
    parser.add_argument("--diag", action="store_true",
                        help="run startup diagnostics and print a report")
    return parser.parse_args(argv)


def acquire_single_instance() -> bool:
    """Take the single-instance mutex; False when another panel is running."""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                          ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        global _MUTEX_HANDLE
        _MUTEX_HANDLE = kernel32.CreateMutexW(None, 1, MUTEX_NAME)
        if not _MUTEX_HANDLE:
            return True
        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


_MUTEX_HANDLE = None


def remember_interpreter() -> None:
    """Record the running interpreter in launcher.ini for the .bat/.vbs launchers.

    Only written when the file still has an empty ``python=`` value, so a value
    the user pinned by hand is never overwritten.  Irrelevant for the packaged
    executable, which needs no interpreter.
    """
    if getattr(sys, "frozen", False):
        return
    project = os.path.dirname(os.path.abspath(__file__))
    ini = os.path.join(project, "launcher.ini")
    exe = os.path.abspath(sys.executable)
    if exe.lower().endswith("python.exe"):
        candidate = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.isfile(candidate):
            exe = candidate
    try:
        lines: list[str] = []
        replaced = False
        with open(ini, "r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped.lower().startswith("python=") and not replaced:
                    if stripped[len("python="):].strip():
                        return  # already pinned
                    lines.append(f"python={exe}\n")
                    replaced = True
                    continue
                lines.append(line)
        if not replaced:
            lines.append(f"python={exe}\n")
        with open(ini, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
    except OSError:
        pass


def run_diagnostics() -> int:
    """Probe everything that has to work, and report on stdout.

    Used to debug the packaged executable, where a console build prints this
    directly (``build_exe.py --console``).
    """
    import ctypes
    import tempfile

    lines = []

    def say(text: str) -> None:
        lines.append(text)
        print(text, flush=True)

    say("Memory Supervisor diagnostics")
    say("  frozen            : %s" % getattr(sys, "frozen", False))
    say("  executable        : %s" % sys.executable)
    say("  cwd               : %s" % os.getcwd())
    say("  python            : %s" % sys.version.split()[0])

    pw.set_dpi_awareness()
    say("  dpi aware         : ok")

    try:
        from memsup import tray_win
        icon = tray_win.make_tray_icon(32)
        say("  make_tray_icon    : %s" % (hex(icon) if icon else "FAILED"))
        if icon:
            pw.user32.DestroyIcon(icon)
    except Exception as exc:
        say("  make_tray_icon    : EXCEPTION %r" % (exc,))

    try:
        from memsup import tray_win
        proc = pw.make_wndproc(
            lambda h, m, w, l: pw.user32.DefWindowProcW(h, m, w, l))
        pw.register_window_class("MemSupDiagWnd", proc, cursor=False)
        hwnd = pw.create_layered_popup("MemSupDiagWnd", "diag", width=120,
                                       height=60, x=50, y=50)
        say("  diag window       : %s" % (hex(hwnd or 0)))
        tray = tray_win.TrayIcon(hwnd, "diag", 
                                 callback_message=tray_win.WM_TRAYICON)
        say("  NOTIFYICONDATAW sz: %d (expect 976)"
            % ctypes.sizeof(tray_win.NOTIFYICONDATAW))
        say("  Shell_TrayWnd     : %s"
            % hex(pw.user32.FindWindowW("Shell_TrayWnd", None) or 0))
        added = tray.add()
        say("  tray add (GUID)   : %s%s"
            % (added, ("  (%s)" % tray.last_error) if tray.last_error else ""))
        if added:
            rect = pw.tray_icon_rect(hwnd, guid_bytes=tray._guid)
            say("  tray icon rect    : %s" % (
                (rect.left, rect.top, rect.right, rect.bottom) if rect else None))
            tray.remove()
        else:
            # retry without the GUID to isolate the identifier from the call
            data = tray._data()
            data.uFlags = (tray_win.NIF_MESSAGE | tray_win.NIF_ICON
                           | tray_win.NIF_TIP)
            ctypes.set_last_error(0)
            ok2 = bool(tray_win.shell32.Shell_NotifyIconW(
                tray_win.NIM_ADD, ctypes.byref(data)))
            say("  tray add (no GUID): %s  GetLastError=%d"
                % (ok2, ctypes.get_last_error()))
            if ok2:
                tray_win.shell32.Shell_NotifyIconW(
                    tray_win.NIM_DELETE, ctypes.byref(data))
        pw.user32.DestroyWindow(hwnd)
    except Exception as exc:
        say("  tray add          : EXCEPTION %r" % (exc,))

    try:
        from memsup import app as app_mod
        say("  app_dir()         : %s" % app_mod.app_dir())
        say("  Config.path()     : %s" % app_mod.Config.path())
        cfg = app_mod.Config()
        cfg.save()
        exists = os.path.exists(app_mod.Config.path())
        say("  config save       : %s" % ("ok" if exists else "FAILED"))
    except Exception as exc:
        say("  config save       : EXCEPTION %r" % (exc,))

    say("  temp dir          : %s" % tempfile.gettempdir())

    # keep the report readable when launched without a console
    try:
        target = os.path.join(tempfile.gettempdir(), "memsup-diag.txt")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        print("report written to %s" % target, flush=True)
    except OSError:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.diag:
        return run_diagnostics()

    if not acquire_single_instance():
        pw.user32.MessageBoxW(None,
                              "Memory Supervisor is already running.\n"
                              "Look for the panel on your desktop; drag it to move it.",
                              "Memory Supervisor", 0x00000040)  # MB_ICONINFORMATION
        return 0

    pw.set_dpi_awareness()
    remember_interpreter()

    config = Config.load()
    if args.reset_position:
        config.x = config.y = None
    if args.interval is not None:
        config.sample_interval = max(0.2, min(2.0, args.interval))
    if args.no_acrylic:
        config.acrylic = False
    if args.not_topmost:
        config.always_on_top = False
    if args.width:
        config.width = max(300, min(1200, args.width))
    if args.height:
        config.height = max(150, min(900, args.height))

    window = SupervisorWindow(config)
    try:
        window.create()
    except OSError as exc:
        pw.user32.MessageBoxW(None, f"Could not create the panel window:\n{exc}",
                              "Memory Supervisor", 0x00000010)  # MB_ICONERROR
        return 1

    try:
        return window.run()
    except KeyboardInterrupt:
        window.close()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

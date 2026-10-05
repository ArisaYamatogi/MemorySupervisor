#!/usr/bin/env python3
"""Build Memory Supervisor as a single Windows executable.

    python build_exe.py

Produces ``dist\\MemorySupervisor.exe``: a one-file, console-free build with the
panel's icon embedded, so the program can be run without installing Python.

PyInstaller is required.  It is deliberately *not* vendored into the project, so
this script installs it on demand into ``tools\\buildenv`` (a throw-away folder)
rather than into the system Python:

    python -m pip install --target tools\\buildenv pyinstaller

Everything else the panel needs is in the standard library, so the executable
stays small and has no runtime dependencies.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

PROJECT = os.path.dirname(os.path.abspath(__file__))
BUILD_ENV = os.path.join(PROJECT, "tools", "buildenv")
ICON = os.path.join(PROJECT, "docs", "memsup.ico")
NAME = "MemorySupervisor"
CONSOLE = "--console" in sys.argv          # keep stdout for troubleshooting


def pyinstaller_available() -> bool:
    """True when PyInstaller can be imported (installed or in tools/buildenv)."""
    if os.path.isdir(BUILD_ENV):
        sys.path.insert(0, BUILD_ENV)
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        return False


def install_pyinstaller() -> bool:
    print("PyInstaller not found - installing it into tools\\buildenv ...")
    os.makedirs(BUILD_ENV, exist_ok=True)
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
           "--no-warn-script-location", "--target", BUILD_ENV, "pyinstaller"]
    try:
        rc = subprocess.call(cmd)
    except OSError as exc:
        print("  could not run pip:", exc)
        return False
    if rc != 0:
        print("  pip failed (no network?)")
        return False
    return pyinstaller_available()


def make_icon() -> str | None:
    """Write the tray/application icon as a real .ico for the executable."""
    try:
        sys.path.insert(0, PROJECT)
        from memsup import platform_win as pw
        from memsup import tray_win
    except Exception as exc:                                   # pragma: no cover
        print("  could not import the icon painter:", exc)
        return None

    sizes = (16, 24, 32, 48, 64, 128, 256)
    images = {}
    for size in sizes:
        buffer = pw.PixelBuffer(size, size)
        try:
            tray_win.paint_tray_icon(buffer, size)
            images[size] = (bytes(buffer.buf), size)
        finally:
            buffer.destroy()

    os.makedirs(os.path.dirname(ICON), exist_ok=True)
    try:
        from PIL import Image
        frames = [Image.frombytes("RGBA", (s, s), data) for s, (data, _) in
                  sorted(images.items())]
        frames[-1].save(ICON, format="ICO",
                        sizes=[(s, s) for s in sorted(images)])
        return ICON
    except ImportError:
        pass

    # No PIL: write a single-image ICO by hand (BMP/DIB payload + AND mask).
    import struct
    size = 32
    data, _ = images[size]
    pixels = bytearray()
    for y in range(size - 1, -1, -1):                 # bottom-up
        row = data[y * size * 4:(y + 1) * size * 4]
        for x in range(size):
            b, g, r, a = row[x * 4:x * 4 + 4]
            pixels += bytes((b, g, r, a))
    mask_stride = ((size + 31) // 32) * 4
    mask = bytes(mask_stride * size)
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                         len(pixels), 0, 0, 0, 0)
    payload = header + bytes(pixels) + mask
    ico = struct.pack("<HHH", 0, 1, 1)
    ico += struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(payload), 22)
    ico += payload
    with open(ICON, "wb") as fh:
        fh.write(ico)
    return ICON


def main() -> int:
    os.chdir(PROJECT)
    print("Memory Supervisor - executable build")
    print("project:", PROJECT)

    if not pyinstaller_available() and not install_pyinstaller():
        print("\nPyInstaller is required.  Install it manually with:\n"
              "    python -m pip install --target tools\\buildenv pyinstaller")
        return 1

    icon = make_icon()
    print("icon:", icon or "(none - executable will use the default)")

    for folder in ("build", "dist"):
        path = os.path.join(PROJECT, folder)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)

    for module in ('memsup.app', 'memsup.platform_win', 'memsup.tray_win',
                   'memsup.meminfo', 'memsup.constants'):
        try:
            __import__(module)
        except Exception as exc:
            print("\ncannot import %s: %r" % (module, exc))
            print("fix the source before building")
            return 1
    print("source imports ok")

    entry = os.path.join(PROJECT, "memsup.py")
    args = [
        "--noconfirm", "--clean",
        "--onefile",
        # pythonw-equivalent (no console window) unless debugging
        "--console" if CONSOLE else "--noconsole",
        "--name", NAME + ("-console" if CONSOLE else ""),
        "--distpath", os.path.join(PROJECT, "dist"),
        "--workpath", os.path.join(PROJECT, "build"),
        "--specpath", os.path.join(PROJECT, "build"),
        # the panel uses only ctypes + stdlib, so keep the bundle lean
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc",
        "--exclude-module", "email",
        "--exclude-module", "http",
        "--exclude-module", "xml",
        "--exclude-module", "pdb",
        "--exclude-module", "doctest",
        "--exclude-module", "sqlite3",
        "--exclude-module", "multiprocessing",
        "--exclude-module", "asyncio",
        "--exclude-module", "PIL",
        "--exclude-module", "numpy",
    ]
    if icon:
        args += ["--icon", icon]
    args.append(entry)

    # Run PyInstaller inside this process: when it lives in tools\buildenv a
    # child ``python -m PyInstaller`` would not see that folder on sys.path.
    print("\nrunning PyInstaller ...")
    try:
        from PyInstaller.__main__ import run as pyinstaller_run
    except ImportError as exc:
        print("  cannot import PyInstaller:", exc)
        return 1
    try:
        pyinstaller_run(args)
    except SystemExit as exc:
        if exc.code:
            print("\nbuild failed (PyInstaller exit code %s)" % exc.code)
            return int(exc.code or 1)
    except Exception as exc:
        print("\nbuild failed:", exc)
        return 1

    exe = os.path.join(PROJECT, "dist",
                       NAME + ("-console" if CONSOLE else "") + ".exe")
    if not os.path.isfile(exe):
        print("\nbuild reported success but %s is missing" % exe)
        return 1
    size_mb = os.path.getsize(exe) / (1024 * 1024)
    print("\nbuilt: %s  (%.1f MB)" % (exe, size_mb))
    print("Run it directly - no Python installation needed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

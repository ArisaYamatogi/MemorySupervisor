"""Memory Supervisor - a lightweight always-on-top memory monitor for Windows 11.

The package is split into three layers:

``platform_win``
    Raw Win32 access through :mod:`ctypes` (windows, layered blitting, acrylic
    backdrop, GDI text/shape rasterisation).
``meminfo``
    Background memory sampling and the rolling history window.
``app``
    The panel itself: rendering, the message loop, topmost enforcement, menus.
"""

__version__ = "1.0.0"
__all__ = ["__version__"]

"""Verify the panel layout at every zoom: nothing clipped, nothing wasted.

Run directly (``python tests/layout_check.py``); tests/selftest.py runs the same
checks as part of the full suite.
"""
from __future__ import annotations

import os
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from memsup import app as app_mod               # noqa: E402
from memsup import platform_win as pw           # noqa: E402

BAR_YELLOW = bytes((255, 215, 50, 255))        # #FFD732 as stored: R,G,B,A
#   index 0 = red, 1 = green, 2 = blue, 3 = alpha
#   (a COLORREF 0x00BBGGRR lands in memory as R,G,B,A)


def analyse(scale: float):
    cfg = app_mod.Config()
    cfg.width, cfg.height = app_mod.BASE_WIDTH, app_mod.BASE_HEIGHT
    cfg.scale = scale
    W = int(round(app_mod.BASE_WIDTH * scale))
    H = int(round(app_mod.BASE_HEIGHT * scale))
    renderer = app_mod.PanelRenderer(cfg)
    renderer.resize(W, H, scale)
    canvas = pw.PixelBuffer(W, H)
    try:
        canvas.clear((0, 0, 0, 0))
        renderer.draw(canvas, app_mod.ViewState(
            percent=73.9, used_gib=11.40, total_gib=15.43, avail_gib=4.03,
            valid=True))
        data = bytes(canvas.buf)
        layout = renderer._layout()

        def rows_of(predicate, x0=0, x1=None):
            x1 = W if x1 is None else x1
            out = []
            for y in range(H):
                for x in range(x0, x1):
                    i = (y * W + x) * 4
                    if predicate(data[i:i + 4]):
                        out.append(y)
                        break
            return out

        # the bar is the only strongly saturated yellow in the design
        # (stored as R,G,B,A - see BAR_YELLOW above)
        bar_rows = rows_of(lambda px: px[0] > 200 and px[1] > 170
                           and px[2] < 110 and px[3] > 240)
        # text: clearly brighter than the card, anywhere in the panel
        ink_rows = rows_of(lambda px: px[3] > 200
                           and (px[0] + px[1] + px[2]) > 330)
        return {
            "scale": scale, "size": (W, H), "layout": layout,
            "bar": (bar_rows[0], bar_rows[-1]) if bar_rows else None,
            "ink": (ink_rows[0], ink_rows[-1]) if ink_rows else None,
            "yellow_px": sum(1 for i in range(0, len(data), 4)
                             if data[i:i + 4] == BAR_YELLOW),
        }
    finally:
        canvas.destroy()


def checks():
    """Yield (name, ok, detail) so selftest.py can reuse this module."""
    for scale in (0.6, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0):
        info = analyse(scale)
        W, H = info["size"]
        layout = info["layout"]
        order_ok = (layout["head_y"] < layout["num_y"] < layout["label_y"]
                    < layout["bar_y"])
        fits = layout["bar_y"] + layout["bar_h"] <= H
        top_gap = info["ink"][0] if info["ink"] else -1
        bot_gap = H - 1 - info["bar"][1] if info["bar"] else -1
        # both margins must exist, and stay small: that is the "no empty strip"
        # requirement, and it has to hold while zooming too
        tight = (2 <= top_gap <= max(8, int(14 * scale))
                 and 2 <= bot_gap <= max(10, int(16 * scale)))
        ok = bool(info["bar"] and info["ink"] and order_ok and fits and tight
                  and info["yellow_px"] > 50)
        detail = ("ink %s bar %s gaps top=%d bottom=%d"
                  % ("%d..%d" % info["ink"] if info["ink"] else "-",
                     "%d..%d" % info["bar"] if info["bar"] else "-",
                     top_gap, bot_gap))
        yield ("layout correct at %.2fx zoom" % scale, ok, detail)


def main() -> int:
    print("BASE %dx%d   content_height=%.0f"
          % (app_mod.BASE_WIDTH, app_mod.BASE_HEIGHT,
             app_mod.PanelRenderer.content_height()))
    print()
    bad = 0
    for name, ok, detail in checks():
        print("  [%s] %-36s %s" % ("PASS" if ok else "FAIL", name, detail))
        bad += 0 if ok else 1
    print()
    print("LAYOUT OK AT EVERY ZOOM LEVEL" if not bad
          else "%d LAYOUT PROBLEM(S)" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

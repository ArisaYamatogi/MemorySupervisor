# How it works

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
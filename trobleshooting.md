# Troubleshooting

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

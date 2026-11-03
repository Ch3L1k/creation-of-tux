# Optional Noctalia v5 integration

Skip this entirely for standalone operation. First disable the standalone XDG
login entry (`creation-of-tux autostart off`) if enabling picker-managed startup.
Do not use simultaneously with the earlier personal `creation-ascii` service/hooks.

Run after installing:

```sh
python3 ~/.local/share/creation-of-tux/noctalia.py prepare
```

The command creates a preview in the app config folder and prints hook commands.
Add that folder to Noctalia's wallpaper directories. Add the printed `sync`
command to `wallpaper_changed` and `started` hooks. **Preserve existing hook
commands**: use an array when an event already has another command. Use your
actual installed path and Python executable; the printed command contains them.
Reload Noctalia configuration. Choose **Tux - live ASCII wallpaper.png** in the
normal picker. Choosing another wallpaper stops the animation for that output.
Each monitor keeps its own fallback. No video player is involved.

You can also select/restore from the terminal:

```sh
python3 ~/.local/share/creation-of-tux/noctalia.py select
python3 ~/.local/share/creation-of-tux/noctalia.py restore
```

The adapter uses Noctalia IPC and renderer output enumeration, not `hyprctl`.
Its `sync` command changes the app's output filter while picker-managed.
Only use standalone/manual output settings when picker integration is inactive.
Before uninstalling: restore the previous wallpaper and remove the two hook
commands you added. The uninstaller does not rewrite your existing hook arrays.

Noctalia v5.4 hook reference:
https://docs.noctalia.dev/noctalia/v5.4.0/automation/hooks/

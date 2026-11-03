# Validation for 0.1.0

Verified locally on CachyOS x86_64, Hyprland 0.56.2, NVIDIA Quadro RTX 3000.

- Build: C++17 with system Wayland/EGL/GLES2/libpng, no compiler warnings.
- Output enumeration and explicit error for an unavailable output.
- 11 isolated control/installer integration tests: singleton start, clean stop,
  presets/restart, invalid JSON/type/range handling, missing Wayland, renderer
  errors, stale PID safety, refresh, autostart quoting, install/update/remove,
  preservation of unrelated files, refusal to replace an unmanaged directory.
- GTK4 construction and Apply callback exercised with temporary XDG directories,
  without displaying a desktop window or changing the running wallpaper.
- Offscreen GPU images at 0/55/90/180 degrees and time 0/3: opaque output,
  static figures, rotating Tux, visible thin side, stable eyes, animated body,
  head and beak symbols. Shader appearance matches the approved personal version.
- Demo: one 9-second revolution rendered by the actual binary at 24 FPS,
  exported as a 1280×720 H.264 showcase clip. The installed wallpaper is still
  procedural; it does not play that video.

Run the portable standard-library tests after building:

```sh
bash build.sh
python3 -m unittest discover -s tests -v
```

Optional GPU invariants require Pillow + numpy in a separate development venv:

```sh
python3 tests/check_gpu.py
```

Not claimed as tested: real Debian/Fedora installations, Sway/niri interactive
sessions, every GPU/driver, real monitor cable hotplug on the new package, or
Noctalia adapter switching inside another person's configuration.

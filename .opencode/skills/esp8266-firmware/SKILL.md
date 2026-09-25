---
name: esp8266-firmware
description: Use when building, flashing, uploading, or verifying WindowActuator ESP8266 firmware, including build.sh, flash.sh, upload-src.sh, template freezing, and serial or HTTP checks.
---

# WindowActuator ESP8266 Firmware

Use this workflow for the WindowActuator Wemos D1 mini at `/dev/ttyUSB0`.

## Start Here

Activate the project environment before running any firmware command:

```bash
source venv/bin/activate
```

## Source Layout

- `templates/*.html` contains editable utemplate sources.
- `firmware/compile_templates.py` generates ignored `freeze/html/*_html.py` modules.
- Generated template modules are frozen into firmware to preserve ESP8266 RAM.
- `src_alive/html/` contains only live static assets: `index.html`, `style.css`, and `wa.ico`.
- Static assets use a one-year cache lifetime. Use a hard refresh or clear browser site data after changing them.

## MicroPython Source Style

- Do not use runtime docstrings in code that runs on the ESP8266 or is frozen into its firmware.
- Standard Python docstrings become runtime string objects and consume scarce device memory.
- Format all documentation as comments instead, using reStructuredText-style fields where useful:

  ```python
  # Apply position calibration limits.
  #
  # :param pos_min: Normalized closed-position limit.
  # :param pos_max: Normalized open-position limit.
  ```

- This target-firmware rule takes precedence over general Python guidance that requires method docstrings.
- Ordinary docstrings are acceptable in host-side build and deployment tooling when they do not enter the firmware.

## Prerequisites

1. Connect the Wemos D1 mini by USB.
2. Confirm `/dev/ttyUSB0` exists and is accessible to the current user.
3. Ensure the project virtual environment exists at `venv/`. It provides `esptool` and `rshell`.

## Build Firmware

Run from the firmware directory:

```bash
./build.sh
```

This command regenerates frozen templates from `templates/`, builds MicroPython for `ESP8266_GENERIC`, and writes the image to `firmware/bin/firmware.bin`.

`build.sh` updates the MicroPython checkout on `master`. Do not run it when local changes in `~/git/3rd_party/micropython` must be preserved without review.

## Flash Firmware

After a successful build, run from `firmware/`:

```bash
./flash.sh
```

The script writes `bin/firmware.bin` at flash offset zero, verifies its hash, and resets the board. It does not run a full-chip erase, so the filesystem and `settings.json` are preserved. It then runs `upload-src.sh` to mirror static assets from `src_alive/` to `/pyboard` and requests a MicroPython soft reset. Keep `/pyboard` as the destination; do not change it to a subdirectory or delete it.

When invoked from a non-interactive shell, rshell can end with:

```text
termios.error: (25, 'Inappropriate ioctl for device')
```

This occurs when its final interactive REPL step cannot acquire a TTY. The preceding `rsync --mirror` output is the upload result; confirm that each changed asset was copied before treating this as an upload failure.

## Verify

Wait for Wi-Fi startup after resetting. The board prints its address as `Network config: {'IP': '...'}` on serial output. Use that IP for HTTP checks:

```bash
curl -sS -D - -o /dev/null http://<device-ip>/style.css
curl -sS -o /dev/null -w 'movement: HTTP %{http_code}, %{size_download} bytes\n' \
  http://<device-ip>/movement.html
```

Expected static response header:

```text
Cache-Control: max-age=31536000
```

For serial boot diagnostics:

```bash
picocom -b 115200 /dev/ttyUSB0
```

The expected sequence includes Wi-Fi connection, `Network config`, and `Starting async server on 0.0.0.0:80...`.

## Full Deployment Sequence

For firmware or template changes:

```bash
cd firmware
source ../venv/bin/activate
./build.sh
./flash.sh
```

For static-only changes, run `upload-src.sh` from `firmware/`.

Never commit firmware artifacts, generated `*_html.py` modules, or unrelated existing worktree changes unless the user explicitly requests a commit.

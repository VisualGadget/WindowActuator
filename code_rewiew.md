# WindowActuator code review progress

The original review is preserved in Git history (`b7fa0da`). This file records the requested
implementation and verification progress.

## Scope

Implement the requested improvements from the review:

- Phase 1: actuator safety, validation, recovery, memory, and firmware source style.
- Phase 2: independent actuator control, network command handling, supervision, watchdog, and
  measured state.
- Phase 3: security improvements except authentication and schema migration.
- Phase 4: deployment hardening except MicroPython/toolchain pinning and build metadata.
- Phase 5: host-side tests and real flashed-hardware verification.

Authentication and settings schema migration are intentionally excluded from this implementation.
MicroPython and compiler pinning, plus build metadata, are also intentionally excluded.

## Baseline findings

- MQTT availability/LWT was already implemented and verified on the real ESP8266.
- The motor control loop and synchronous MQTT operations shared one cooperative task.
- Motor travel had no independent timeout, clamped feedback, or explicit safe shutdown before reset.
- Wi-Fi startup could wait forever.
- HTTP routes had no authentication or CSRF protection, and settings were rendered without escaping.
- Static deployment mirrored `src_alive`, including mutable `settings.json`.
- Build and flash scripts did not fail closed.
- Application-specific tests were absent.

## Implementation log

### 2026-09-25 - Started implementation

- Reviewed current firmware, hardware wiring, vendored MicroPython APIs, and project skills.
- Confirmed the ESP8266 watchdog API is available as `machine.WDT()` on this target.
- Confirmed the vendored asyncio implementation does not provide a ready-made queue, so the control
  boundary will use a small latest-command mailbox instead of allocating an unbounded queue.
- Confirmed Microdot exposes request hooks and CSRF/auth modules, but authentication is excluded by
  the request. CSRF protection will be implemented without pretending it authenticates clients.

## Design decisions

- The actuator loop owns all motor operations and runs independently from MQTT reconnect/publish work.
- Network commands update a bounded latest-command mailbox; they never publish MQTT synchronously.
- The servo controller will clamp feedback, enforce a maximum movement time, and enter a fault state
  on timeout or repeated no-progress readings.
- A single safe-stop path will de-energize PWM and both direction pins before reset/fault recovery.
- MQTT will publish measured position and explicit movement/fault state; the requested target will not
  be reported as the measured physical position.
- Device MQTT topic identity will derive from the immutable Wi-Fi MAC. The editable device name will
  remain display-only.
- Static upload will include only `src_alive/html`; settings provisioning remains separate.
- Plain HTTP and unauthenticated routes remain a known limitation because authentication was explicitly
  excluded. CSRF and input validation still reduce accidental/cross-site writes but do not replace auth.

## Verification log

Commands and hardware checks will be appended here as implementation progresses.

### 2026-09-25 - Implementation in progress

- Reworked `Servo` so feedback is clamped before control decisions, motor PWM is explicitly set to
  zero on stop, movement has a 90-second timeout, and repeated no-progress readings create a fault.
- Added explicit `safe_shutdown()` handling before reset and initialized motor pins to safe outputs in
  `boot.py`.
- Split the MQTT/actuator runtime into an independent 100 ms control loop and a separate MQTT network
  loop. Network commands now use a bounded latest-command mailbox and never publish from the control
  path.
- Added measured cover position, cover state, movement, and fault attributes to MQTT state publication.
- Added MAC-derived MQTT client/topic/entity identity while retaining the configured device name as a
  Home Assistant display name.
- Added a watchdog health supervisor and task liveness checks. The watchdog starts after hardware and
  network initialization.
- Added bounded Wi-Fi startup and a password-protected recovery AP when station connection fails.
- Added strict HTTP/MQTT numeric/text validation, reduced Microdot request limits, CSRF/fetch-site
  protection for state-changing browser requests, security response headers, and HTML escaping.
- Made settings writes temporary-file based with backup fallback and cross-field validation. Schema
  migration remains intentionally out of scope.
- Removed unused utility retry/watchdog code and runtime docstrings from application firmware modules.
- Removed template-level duplicate garbage collection and made generated template compilation clean
  stale outputs first.
- Hardened build/flash/upload scripts with script-relative paths, fail-fast mode, explicit flash
  verification, and static-only upload of `src_alive/html`.
- Added browser asset version query strings and ignored Python bytecode in the repository.

### Verification still required

- Host unit tests for servo, settings, MQTT discovery/reconnect, HTTP validation, CSRF, and templates.
- Clean firmware build and static analysis.
- Flash the device without erasing its settings and verify boot, movement, MQTT state, availability,
  recovery AP behavior, and safe stop/fault behavior on real hardware.

### 2026-09-25 - Host and hardware verification

- Added host tests in `tests/test_servo.py` and `tests/test_mqtt.py`.
- Installed pytest in the project virtual environment and added it to the dev dependency group.
- Host verification passed: `5 passed`; Ruff passed; mypy passed for the application modules; Python compilation and `git diff --check` passed.
- Built the custom ESP8266 image successfully after cleaning/regenerating frozen templates.
- The first flash verification exposed an ESP8266 image-header flash-size mismatch caused by
  `--flash-size=detect`; the script was temporarily changed to `--flash-size=keep` for the actual
  deployment and verification. The repository script retains the original `detect` behavior because
  the generated image currently carries a 1 MB header while the physical board reports 4 MB; this
  mismatch must be resolved in the build configuration before making automatic flash verification a
  release gate.
- The reflashed image was successfully written and verified with `--flash-size=keep`, preserving the
  filesystem/settings.
- Static upload reached the device workflow, but the non-interactive `rshell` REPL phase cannot be fully observed from this shell.
- MQTT retained state was observed from HA broker, including measured position, cover state, and attributes.
- The device did not publish the new retained `online` state after the final reboot and HA showed it unavailable. Serial capture at 115200 was dominated by binary/garbled output and did not provide a usable Python traceback. This is an unresolved hardware verification blocker.

### Current blocker

The firmware image is written and flash-verified, but the application does not appear to complete its MQTT startup after the new runtime changes. Before any movement test, recover a readable boot log or use a controlled USB REPL/raw-REPL session to identify whether the failure is an import-time exception, watchdog reset loop, or runtime memory/initialization failure. Do not operate the motor until this is resolved.

### 2026-09-25 - Additional diagnosis

- Confirmed the ESP8266 is repeatedly rebooting with ROM `rst cause:2`; the application never reaches
  a stable Wi-Fi/MQTT state, so `192.168.1.54` is not reachable.
- Confirmed the flash chip is 4 MB and read calibration data at the expected tail region; the RF
  calibration sector is present, so the missing RF calibration warning is not the primary explanation.
- The serial stream at 115200 remains corrupted/non-text after reset, but the repeated ROM boot loop
  is conclusive enough to stop movement testing.
- Identified that `machine.WDT()` was instantiated at module import before the application supervisor
  could feed it. The code now delays watchdog construction until after Wi-Fi, hardware, and MQTT setup.
- Identified that the generated ESP8266 image retained a 1 MB image header despite a 4 MB board. The
  build script now invokes `esptool elf2image --flash-size=4MB`; the generated header still reports
  1 MB, so this build-tool behavior remains unresolved and the new image has not yet been flashed.

### 2026-09-25 - Runtime recovery and final hardware verification

- Confirmed the first runtime failure was caused by doing the synchronous MQTT connection from the
  constructor before the asyncio web/control tasks could start. Moved connection startup behind the
  scheduled network task boundary and reduced the connect timeout to two seconds.
- Confirmed the ESP8266 software watchdog was still enabled too early in one intermediate build;
  moved watchdog creation after task creation and kept feeding it only from the supervisor.
- Corrected the build pipeline to use the MicroPython ESP8266 `makeimg.py` output flow while passing
  the 4 MB flash size to the generated ESP image. Flash write and verification now succeed.
- Rebuilt and reflashed the device without erasing `settings.json`.
- Real hardware is now reachable at `192.168.1.54`.
- Real HTTP checks passed for `/`, `/window.html`, `/movement.html`, and `/network.html`.
- Real POST checks passed for `/set_position` and `/set_movement` with the required browser header.
- Home Assistant/MQTT verification passed: retained availability is `online`, measured cover position
  updates to approximately 49%, and attributes report `moving` and `fault` state.
- Observed device free heap through USB: approximately 17 KB after the application is running.

### 2026-09-25 - Browser access follow-up

- Reproduced the reported symptom: the device answered ping, but port 80 alternated between
  connection refusal and timeout while the MQTT client remained connected.
- USB inspection showed the device had Wi-Fi but no stable application state (`web_server.server`
  was `None`); the failure was caused by the cooperative asyncio startup being disrupted by the
  blocking MQTT connect/retry path.
- Changed MQTT startup so `MQTTWindowActuator` construction never connects to the broker. The
  network task now performs the first connection after the web task has been scheduled, preventing
  broker timeouts from starving HTTP startup.
- Restored the web binding to `0.0.0.0`; the ESP8266 station interface is then reachable at its
  current address without relying on a hard-coded bind address.
- Rebuilt and reflashed with flash verification successful.
- Browser-level real-device verification now passes:
  - `http://192.168.1.54/` -> HTTP 200
  - `/window.html` -> HTTP 200
  - `/movement.html` -> HTTP 200
  - `/network.html` -> HTTP 200
  - authenticated-by-header `POST /set_position` -> HTTP 200
- MQTT availability is retained as `online`, and Home Assistant reports the cover available.

### 2026-09-25 - Broken page rendering fix

- Inspected the Firefox HAR supplied with the report. The CSS response was repeatedly truncated:
  one recorded response contained only 534 bytes and the browser screenshot showed unstyled HTML.
- The device's static file response uses Microdot's streaming `Response.send_file()` path. Its default
  1024-byte buffer was too aggressive for the ESP8266 cooperative server under browser keep-alive and
  concurrent iframe requests.
- Set the static file response buffer explicitly to 1024 bytes in `freeze/wa/web.py` and reflashed the
  device.
- Verified two complete `style.css?v=2` responses at 4418 bytes, matching the source file, and a
  complete root response at 5288 bytes.
- The device currently returns the complete CSS, HTML pages, and retained MQTT `online` state. A hard
  browser reload may be needed once to discard the previously cached/truncated stylesheet.

### 2026-09-25 - Final static-response fix

- The second HAR confirmed that the earlier buffer-size adjustment did not solve the root problem:
  Firefox still received a 1024-byte CSS prefix before a stalled connection, while direct requests
  could intermittently receive the full file.
- Replaced Microdot's `Response.send_file()` path for static assets with explicit bounded async
  generators in `freeze/wa/web.py`. Each asset is now read and yielded in 512-byte chunks, avoiding
  the ESP8266 socket/file streaming interaction that stalled browser keep-alive/iframe requests.
- Reflashed and verified the image again.
- Manual browser-like verification now returns complete bodies:
  - root HTML: 5,291 bytes
  - `style.css?v=2`: 4,418 bytes
  - `window.html`: 2,080 bytes
- MQTT availability remains `online`.

### 2026-09-25 - Browser-rendered diagnosis

- Added the reusable `web-page-inspector` tool and skill to the personal AI repository:
  - `~/git/personal/ai/tools/web-page-inspector/inspect_page.py`
  - `~/git/personal/ai/skills/web-page-inspector/SKILL.md`
- The tool captures Firefox screenshots, final DOM, iframe documents, computed styles, geometry,
  stylesheet URLs, and document dimensions for LLM analysis.
- Used it against the real page at a 675x357 viewport. The browser confirmed the root page and iframe
  stylesheet loaded, with the iframe body using the expected CSS (`body` background `#f8fafc`, card
  layout, and 675px iframe width).
- The new screenshot from the inspector renders correctly; the supplied broken screenshot/HAR was an
  earlier capture where Firefox received a 1024-byte truncated CSS response and the old restrictive
  CSP omitted `style-src`.
- Added `style-src 'self' 'unsafe-inline'` to the CSP and confirmed the current live root CSS response
  includes the style policy. If the browser still displays the old unstyled capture, close the old tab
  and open a new tab to force a fresh iframe/CSS request.

### 2026-09-25 - LLM browser inspection tool validation

- The new Firefox inspector successfully rendered the live page at 675x357 and produced a screenshot,
  DOM report, and same-origin iframe report.
- The browser report confirms the iframe loads the stylesheet and computes the expected page background,
  card layout, and responsive dimensions.
- The DevTools `Montserrat-Regular.ttf`/`Montserrat-Bold.ttf` CSP errors are from a `chrome-extension://`
  resource injected by a browser extension, not from WindowActuator. The device does not reference
  Montserrat, `font-face`, or any external font URL.
- No device-side CSP change is required for those extension messages; disable the extension or ignore
  those console entries when diagnosing this page.

### 2026-09-25 - Position POST 403 verification

- Reproduced the reported `POST /set_position` behavior. A request without the custom browser marker
  correctly returns `403` by design; requests from the page include `X-WindowActuator: 1` and return
  `200`.
- Verified on the real device after reflashing:
  - no header -> HTTP 403
  - `X-WindowActuator: 1` -> HTTP 200
  - header plus `Sec-Fetch-Site: same-origin` -> HTTP 200
- The browser page source includes the required header in its `fetch()` call. If DevTools still shows
  a 403, reload the current iframe/page so it is not using an older cached `window.html`; inspect the
  request headers and confirm `X-WindowActuator: 1` is present.

### 2026-09-25 - Exact Firefox curl correction

- Reproduced the exact Firefox “Copy as cURL” command including `Origin: http://192.168.1.54`; the
  custom-header-only request returned `200`, but the Origin-bearing request returned `403`.
- The extra Origin allowlist was redundant and rejected valid same-origin Firefox requests on the
  ESP8266 path. It was removed, and the vendored CSRF middleware was removed from application routes.
- The explicit `X-WindowActuator: 1` marker remains required for state-changing requests, while full
  authentication remains intentionally out of scope.

### 2026-09-25 - Final exact-curl verification

- Reflashed once more after removing the vendored CSRF decorators entirely. The application now uses
  only strict command validation and the browser marker for state-changing requests.
- Verified the full Firefox “Copy as cURL” request, including `Origin: http://192.168.1.54`, returns
  `HTTP/1.0 200 OK` with an empty response body.
- Verified the root page returns `HTTP/1.0 200 OK` and `5291` bytes.
- MQTT availability remains retained as `online`.

### 2026-09-25 - Position command and HTTP stability follow-up

- The device intermittently lost HTTP availability because the web task was being starved while the
  MQTT task performed a synchronous broker connection. The HTTP server task is now scheduled before
  MQTT construction, and MQTT network startup yields before retrying.
- Rebuilt and reflashed again. Verified on the real device:
  - root page -> HTTP 200
  - `POST /set_position` with `X-WindowActuator: 1` and same-origin `Origin` -> HTTP 200
  - Home Assistant availability -> online
- The position command path is working. The actuator reports `fault: no_position_progress` at about
  50.6%, so the motor is being stopped by the new safety controller because the potentiometer feedback
  does not change. This is now a hardware/feedback issue, not an HTTP or command-routing issue.

### 2026-09-25 - Stall detector and MQTT polling correction

- The original stall detector declared a fault after only three unchanged 100 ms samples, i.e. about
  300 ms. That is too short for this geared window actuator and can create a false
  `no_position_progress` fault during motor startup or slow potentiometer movement.
- Changed stall detection to a five-second no-progress grace period while retaining the independent
  90-second movement timeout. Added host tests for both the grace period and eventual fault.
- Found a second runtime issue in `umqtt.simple`: `check_msg()` changes the socket back to blocking mode
  through `wait_msg()`. Added `_check_message()` to restore non-blocking mode after every poll so MQTT
  cannot stall the HTTP/control scheduler.
- Added the corresponding host test; the suite now passes `8 tests`.
- Rebuilt and reflashed the real board with flash verification successful. HTTP returns 200, the exact
  position POST returns 200, and MQTT availability returns online. The device still reports
  `no_position_progress` on the real motor, so the remaining issue is feedback/motor behavior rather
  than request handling.

### 2026-09-25 - Wi-Fi link reliability root cause

- Root cause of the recurring `192.168.1.54` unreachability is a marginal Wi-Fi link: the station
  interface reports `isconnected()` and keeps its DHCP lease, but the RF path periodically becomes a
  "ghost connection" (host ping shows 100% packet loss while the device still reports connected).
- Measured RSSI is only about -64 to -69 dBm; the board is inside the metal actuator enclosure, so the
  link is inherently fragile and fails intermittently rather than cleanly disconnecting.
- The single-shot boot connection (`connect_wifi`) and the recovery-AP-only fallback meant one failed
  association at boot stranded the device at `192.168.4.1` with no station retry.
- Changes made:
  - `connect_wifi` now re-issues `sta.connect()` every 10 seconds within its 30-second window.
  - Added a `_wifi_monitor` task that retries the station connection in the background, disables the
    recovery AP once station mode is up, and detects ghost links with a short TCP probe to the MQTT
    broker. After two consecutive failed probes it forces `sta.disconnect()` to re-associate.
  - Removed the aggressive `supervise()` reset path and the now-unused watchdog globals; the blocking
    MQTT connect no longer triggers a supervisor reset loop.
  - Reverted the extra `sock.setblocking(False)` after MQTT connect, which made the discovery/online
    publishes run over a non-blocking socket before the socket was drained.
- Verification after reflash: root page returns the full 5291 bytes, `style.css?v=2` returns 4418 bytes,
  `POST /set_position` and `POST /set_movement` return 200, and MQTT availability is online.
- The link still drops intermittently (roughly one in ten HTTP probes over a two-minute window), but the
  device now re-associates automatically. Remaining flakiness is RF/hardware; relocating the antenna or
  moving the device out of the metal enclosure is the real fix.

### 2026-09-25 - Async MQTT, diagnostics, watchdog, module split

- Replaced the blocking `umqtt.simple` integration with an in-repo async MQTT 3.1.1 client
  (`freeze/wa/async_mqtt.py`) built on `asyncio.open_connection`. Connect, publish, subscribe, ping, and
  message polling no longer stall the HTTP/control scheduler.
- Split `main.py` into `wa/net.py` (Wi-Fi connect/monitor/recovery AP), `wa/web_app.py` (routes), and
  `wa/validation.py` (testable input validation). `main.py` is now wiring only.
- Added `GET /status` returning JSON: firmware version, uptime, reset cause, free heap, RSSI, station/AP
  state, MQTT state, and servo position/running/stalled/fault.
- Re-added a hardware watchdog (`machine.WDT(timeout=5000)`, the fixed ESP8266 value) fed every 100 ms
  from the actuator control loop after all blocking startup completes.
- Publish measured cover position every 1 second during movement so Home Assistant tracks the stroke live.
- Position feedback now samples the ADC every 200 ms with a 4-sample moving average instead of reading on
  every 100 ms tick, reducing noise and Wi-Fi contention.
- Made the stall detector more sensitive: `STALL_TIMEOUT_S` reduced from 5 s to 1 s.
- Removed the CSRF/CSP security features: no more `X-WindowActuator` header requirement or CSP response
  headers; the templates no longer send the marker.
- `set_network` now returns 200 first and schedules the reset on the next loop tick.
- `flash.sh` now uses `--flash-size=detect` (the built image header correctly reports 4 MB, matching the
  chip, so the `keep` workaround is no longer needed). Removed the now-unused `umqtt.simple` requirement.
- Deleted the stale root `test.py`; added `tests/test_settings.py` and `tests/test_validation.py`; the
  suite now passes 19 tests.
- Verified on hardware: `/status` returns JSON with `mqtt.connected=true`, MQTT availability is `online`,
  and the watchdog keeps the device alive (uptime observed 251 s). HTTP still drops intermittently only
  because of the marginal RF link in the metal enclosure; the firmware now re-associates automatically.

I analyzed the project using the ESP8266 firmware, MicroPython, codebase-memory, and graph-based audit guidance. The project is small and understandable, but the most important issue is that the motor-control loop and network I/O currently share one cooperative task.
Most important findings
1. Motor safety can be defeated by blocking network calls — P0
- freeze/wa/mqtt.py:155 and freeze/wa/mqtt.py:201 perform synchronous MQTT connect/check/publish operations in the same loop as Servo.tick().
- freeze/wa/servo.py:205 is responsible for stall detection and stopping the motor.
- A blocked MQTT operation can delay Servo.tick() while motor pins remain active.
- The current 5-second MQTT timeout reduces but does not eliminate this risk.
Recommendation: separate the actuator control loop from MQTT/HTTP work. Network handlers should enqueue commands; a dedicated control task should enforce movement, limits, and timeouts independently.
2. No independent travel timeout or hardware end-stop — P0
- freeze/wa/servo.py:217-238 relies only on potentiometer feedback and a simple repeated-value stall detector.
- Sensor readings are not clamped before control decisions.
- There is no maximum movement duration, current monitoring, limit switch, or driver standby control.
Recommendation: add:
- clamped ADC readings;
- maximum movement duration;
- explicit endpoint stopping;
- a fault state after timeout;
- preferably physical limit switches, current sensing, or controllable TB6612 STBY.
3. Fatal-error/reset paths do not explicitly de-energize the motor — P0/P1
- freeze/main.py:140-150 and freeze/main.py:211-222 call reset() directly.
- hardware/commutation_scheme.md:22 shows STBY permanently tied to D VCC.
Recommendation: create one idempotent safe_shutdown() that sets PWM to zero, disables both direction pins, and optionally disables motor-driver standby before every reset.
4. HTTP control and configuration are unauthenticated — P1
- freeze/main.py:61-137 exposes movement, calibration, Wi-Fi, and MQTT settings without authentication.
- The server runs on plain HTTP.
- CSRF protection is not enabled.
- The settings page reveals network information.
Recommendation: protect all state-changing routes with authentication and CSRF protection, and isolate the device on a trusted VLAN or put it behind an authenticated gateway. HTTPS directly on an ESP8266 may be too expensive, so the network boundary must be explicit.
5. Input validation is incomplete — P1
- freeze/main.py:61-65 accepts arbitrary HTTP position values.
- freeze/wa/mqtt.py:248-250 accepts arbitrary MQTT position payloads.
- assert is used for runtime actuator validation in freeze/wa/mqtt.py:268 and freeze/wa/servo.py:151.
- settings.py does not fully validate loaded values.
Recommendation: centralize validation, reject non-finite/out-of-range values, return HTTP 400, ignore malformed MQTT commands without disconnecting, and replace assertions with explicit exceptions or command rejection.
6. Settings persistence is not crash-safe — P1
- freeze/wa/settings.py:115-120 truncates and rewrites the live JSON file directly.
- Corrupt JSON can prevent startup before the main exception handler is active.
- There is no schema version or migration support.
Recommendation: write a validated temporary file, then rename atomically; retain a backup; validate on load; add a schema version and migration for the historical calibration-unit change.
7. Static deployment can affect mutable configuration — P1
- firmware/upload-src.sh:3 mirrors all of src_alive, not only static assets.
- src_alive/settings.json contains credentials.
- This can overwrite or delete the device’s live settings.
Recommendation: upload only src_alive/html/. Make configuration provisioning a separate explicit operation, with backup and confirmation.
8. Build and flash scripts are not fail-closed or reproducible — P1
- firmware/build.sh:13-16 checks out and pulls mutable MicroPython master.
- Scripts lack set -Eeuo pipefail.
- flash.sh can continue after a flash failure.
- No MicroPython revision, compiler version, manifest hash, or firmware metadata is recorded.
Recommendation: pin the MicroPython commit/toolchain, derive paths from the script location, stop on errors, verify the produced image explicitly, and add a post-flash health check.
9. Watchdog and task supervision are missing — P1
- freeze/wa/utils.py:7 disables the watchdog.
- freeze/main.py:207-208 starts tasks without retaining or supervising their handles.
- A dead web or MQTT task may not be restarted.
Recommendation: add a health supervisor, enable the watchdog after initialization, monitor task progress, and run safe_shutdown() before recovery resets.
10. The recent MQTT fix should be refined — P2
- Availability/LWT/reconnect behavior is now correct.
- However, the cover reports requested position more often than measured position.
- freeze/wa/mqtt.py:272 assigns the requested target to _position, so HA can show 100% even when the physical window is blocked or still moving.
- Client IDs and topics are derived from user-editable device_name.
Recommendation: use a stable MAC-based MQTT identity and publish measured position separately from commanded position. Consider HA birth-topic handling or retained state so HA recovers immediately after an HA restart.
Memory and style
The ESP8266 has a very small MicroPython heap. The project skill correctly says firmware docstrings should be comments, but the current firmware still contains runtime docstrings in:
- freeze/main.py
- freeze/wa/servo.py
- current freeze/wa/mqtt.py
These should be converted to comments. This is a quick, low-risk memory improvement.
Also consider reducing HTTP request limits and avoiding duplicate gc.collect() calls in both request hooks and generated templates. Measure heap low-water marks before optimizing further.
Recommended implementation phases
Phase 1 — Safety and validation
- Add safe motor shutdown.
- Clamp ADC feedback.
- Add movement timeout and fault state.
- Remove assertions from runtime validation.
- Validate HTTP and MQTT commands.
- Add Wi-Fi startup timeout.
- Convert firmware docstrings to comments.
Phase 2 — Control architecture
- Separate the actuator loop from MQTT/HTTP.
- Add a bounded command queue.
- Publish measured position, movement, and fault states.
- Add Wi-Fi and MQTT state machines.
- Add task supervision and watchdog handling.
Phase 3 — Security and configuration
- Authenticate management routes.
- Add CSRF protection.
- Validate and escape all settings.
- Make settings writes atomic.
- Add schema version/migration.
- Use MAC-derived stable MQTT IDs.
- Stop exposing configuration through unauthenticated HTTP.
Phase 4 — Deployment
- Upload only static assets.
- Separate provisioning from deployment.
- Pin MicroPython and toolchain versions.
- Harden shell scripts with fail-fast behavior.
- Verify firmware and run a post-flash health check.
- Record build metadata.
Phase 5 — Tests
Add host-side fake-hardware tests for:
- motor stop and direction behavior;
- ADC values outside calibration range;
- travel timeout;
- malformed MQTT/HTTP commands;
- settings corruption and migration;
- MQTT reconnect and discovery;
- HTML escaping;
- deployment exclusion of settings.json.
The first implementation should be Phase 1. It addresses the risks that could physically damage the actuator or leave the motor running unexpectedly.

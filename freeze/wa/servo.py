import time

from machine import ADC, PWM, Pin

UINT16_MAX = 65535


def movement_log(event: str, details: str) -> None:
    # Emit compact serial diagnostics without taking additional ADC samples.
    print("MOVE t_ms=%s event=%s %s" % (time.ticks_ms(), event, details))


class Motor:
    # DC motor driver TB6612FNG.

    def __init__(self, cw_pin: Pin, ccw_pin: Pin, pwm_pin: Pin, status_led: Pin, power: float = 1):
        # :param cw_pin: Pin to rotate the motor clockwise.
        # :param ccw_pin: Pin to rotate the motor counterclockwise.
        # :param pwm_pin: PWM pin controlling motor power.
        # :param status_led: Activity indicator pin.
        # :param power: Rotation power in the range 0..1.
        self._power = PWM(pwm_pin, freq=1000, duty_u16=0)
        self._power_limit = 0.0
        self._speed = 1.0
        self._cw_pin = cw_pin
        self._ccw_pin = ccw_pin
        self._led = status_led
        self.running = False
        self._direction = "stop"
        self.stop()
        self.set_power(power=power)

    def set_power(self, power: float) -> None:
        # Set the motor PWM duty cycle.
        #
        # :param power: Rotation power in the range 0..1.
        if not 0 <= power <= 1:
            raise ValueError("Motor power must be in the range from zero to one")

        self._power_limit = power
        movement_log("power", "limit=%s running=%s" % (power, self.running))
        if self.running:
            self._apply_duty()

    def set_speed(self, speed: float) -> None:
        # Scale the power limit, e.g. to slow down before stopping. Takes effect immediately while running.
        #
        # :param speed: Fraction of the power limit in the range 0..1.
        self._speed = max(0.0, min(1.0, speed))
        if self.running:
            self._apply_duty()

    def _apply_duty(self) -> None:
        self._power.duty_u16(round(self._power_limit * self._speed * UINT16_MAX))

    def cw(self) -> None:
        # Rotate clockwise.
        if self._direction != "cw":
            movement_log("drive", "previous=%s direction=cw power=%s" % (self._direction, self._power_limit))
        self._direction = "cw"
        self._ccw_pin.off()
        self._cw_pin.on()
        self._apply_duty()
        self._led.on()
        self.running = True

    def ccw(self) -> None:
        # Rotate counterclockwise.
        if self._direction != "ccw":
            movement_log("drive", "previous=%s direction=ccw power=%s" % (self._direction, self._power_limit))
        self._direction = "ccw"
        self._cw_pin.off()
        self._ccw_pin.on()
        self._apply_duty()
        self._led.on()
        self.running = True

    def stop(self) -> None:
        # Stop rotation and remove motor drive signals.
        self._power.duty_u16(0)
        self._cw_pin.off()
        self._ccw_pin.off()
        self._led.off()
        self.running = False
        self._speed = 1.0
        movement_log("drive", "previous=%s direction=stop" % self._direction)
        self._direction = "stop"


class PositionSensor:
    # Gearbox axis absolute position sensor based on a potentiometer.

    SAMPLE_INTERVAL_MS = 200
    AVERAGE_WINDOW = 4

    def __init__(self, pos_min: float = 0.0, pos_max: float = 1.0):
        # :param pos_min: Relative ADC value of the closed endpoint.
        # :param pos_max: Relative ADC value of the opened endpoint.
        self._adc = ADC(0)
        self._samples = [0] * self.AVERAGE_WINDOW
        self._sample_count = 0
        self._sample_index = 0
        self._last_sample_at: int | None = None
        self.reset()
        self.set_limits(pos_min=pos_min, pos_max=pos_max)

    def reset(self) -> None:
        # Discard averaged samples so a new movement starts from fresh readings. Samples kept from an earlier movement
        # would be stale, and a tick timestamp older than half the tick period would no longer compare correctly.
        self._sample_count = 0
        self._sample_index = 0
        self._last_sample_at = None

    def set_limits(self, pos_min: float, pos_max: float) -> None:
        # Set potentiometer calibration limits.
        #
        # :param pos_min: Relative ADC value of the closed endpoint.
        # :param pos_max: Relative ADC value of the opened endpoint.
        if not 0 <= pos_min < pos_max <= 1:
            raise ValueError("Position limits must satisfy 0 <= closed < opened <= 1")

        self._adc_min = round(pos_min * UINT16_MAX)
        self._adc_max = round(pos_max * UINT16_MAX)
        movement_log("limits", "adc_min=%s adc_max=%s" % (self._adc_min, self._adc_max))

    def _clamp(self, raw: int) -> float:
        # Convert a raw ADC value to a clamped normalized position.
        position = (raw - self._adc_min) / (self._adc_max - self._adc_min)

        return max(0.0, min(1.0, position))

    def read(self, now_ms: int) -> float:
        # Sample and average the ADC on a slower cadence to reduce noise and Wi-Fi contention.
        #
        # :param now_ms: Control-loop timestamp from time.ticks_ms().
        if self._last_sample_at is None or time.ticks_diff(now_ms, self._last_sample_at) >= self.SAMPLE_INTERVAL_MS:  # type: ignore[attr-defined]
            self._samples[self._sample_index] = self._adc.read_u16()
            self._sample_index = (self._sample_index + 1) % self.AVERAGE_WINDOW
            if self._sample_count < self.AVERAGE_WINDOW:
                self._sample_count += 1
            self._last_sample_at = now_ms

        if self._sample_count == 0:
            return self._clamp(self._adc.read_u16())

        total = 0
        for i in range(self._sample_count):
            total += self._samples[i]

        return self._clamp(total // self._sample_count)

    @property
    def position(self) -> float:
        # Return a fresh clamped normalized position.
        return self._clamp(self._adc.read_u16())

    @property
    def raw(self) -> int:
        # Return the raw potentiometer ADC reading.
        return self._adc.read_u16()


class Servo:
    # Servomotor controller with feedback and movement safety limits.

    POSITION_PRECISION = 0.015
    MAX_MOVEMENT_MS = 90000
    STALL_TIMEOUT_MS = 1000
    STALL_PROGRESS = 0.001
    RAW_PRECISION = 200
    # Within SLOWDOWN_DISTANCE of the target, power falls linearly to SLOWDOWN_MIN_SPEED of the power limit, so the
    # window does not stop abruptly from full speed.
    SLOWDOWN_DISTANCE = 0.12
    SLOWDOWN_MIN_SPEED = 0.12
    RAW_STALL_DELTA = 64

    def __init__(self, motor: Motor, pos_sensor: PositionSensor, status_led: Pin):
        # :param motor: Motor driver.
        # :param pos_sensor: Potentiometer position sensor.
        # :param status_led: Activity and fault indicator.
        self._motor = motor
        self._pos = pos_sensor
        self._led = status_led
        self._target_pos: float | None = None
        self._raw_target: int | None = None
        # Control timestamps are time.ticks_ms() values; compare them only with time.ticks_diff().
        self._movement_started_at: int | None = None
        self._last_position: float | None = None
        self._last_measured_position: float | None = None
        self._no_progress_started_at: int | None = None
        # Direction chosen for the current normalized target ("cw" or "ccw"), None until the first drive decision.
        self._approach: str | None = None
        self._stalled = False
        self._fault: str | None = None

    def _clear_fault(self) -> None:
        self._stalled = False
        self._fault = None
        self._last_position = None
        self._no_progress_started_at = None
        self._led.off()

    @staticmethod
    def _elapsed_ms(now_ms: int, since_ms: int) -> int:
        # Wrap-safe milliseconds between two time.ticks_ms() values.
        return time.ticks_diff(now_ms, since_ms)  # type: ignore[attr-defined]

    def _stalled_for(self, now_ms: int) -> bool:
        # Return whether movement has made no progress for the stall timeout.
        return (
            self._no_progress_started_at is not None
            and self._elapsed_ms(now_ms, self._no_progress_started_at) >= self.STALL_TIMEOUT_MS
        )

    @staticmethod
    def _validate_position(position: float) -> None:
        # Validate a normalized target position.
        if not 0 <= position <= 1:
            raise ValueError("Servo position must be in the range from zero to one")

    @property
    def position(self) -> float:
        # Get the measured normalized position.
        return self._pos.position

    @position.setter
    def position(self, new_pos: float) -> None:
        # Set the target normalized position.
        #
        # :param new_pos: Target position in the range 0..1.
        self._validate_position(new_pos)
        movement_log(
            "target",
            "mode=normalized previous=%s raw_target=%s target=%s running=%s"
            % (self._target_pos, self._raw_target, new_pos, self.running),
        )
        self._target_pos = new_pos
        self._movement_started_at = None
        self._approach = None
        self._pos.reset()
        self._clear_fault()

    @property
    def measured_position(self) -> float:
        # Return the position sampled by the latest control-loop iteration.
        return self._last_measured_position if self._last_measured_position is not None else 0.0

    @property
    def raw_adc(self) -> int:
        # Return the raw potentiometer ADC reading for endpoint calibration.
        return self._pos.raw

    @property
    def raw_position(self) -> float:
        # Return the raw potentiometer reading as a percentage of the ADC full scale.
        return self._pos.raw * 100 / UINT16_MAX

    @property
    def opening(self) -> bool:
        # Return whether the motor is driving toward the opened endpoint.
        if self._raw_target is not None:
            return self._raw_target > self._pos.raw
        if self._target_pos is not None:
            return self._target_pos > self._pos.position

        return False

    def stop(self, fault: str | None = None) -> None:
        # Stop movement and optionally record a fault.
        movement_log(
            "stop",
            "fault=%s target=%s raw_target=%s measured=%s running=%s"
            % (fault, self._target_pos, self._raw_target, self._last_measured_position, self.running),
        )
        self._target_pos = None
        self._raw_target = None
        self._movement_started_at = None
        self._approach = None
        self._motor.stop()

        if fault is None:
            self._clear_fault()
        else:
            self._stalled = True
            self._fault = fault
            self._last_position = None
            self._no_progress_started_at = None

    def set_position_limits(self, pos_min: float, pos_max: float) -> None:
        # Apply calibration limits without moving the motor.
        #
        # :param pos_min: Relative ADC value of the closed endpoint.
        # :param pos_max: Relative ADC value of the opened endpoint.
        self._pos.set_limits(pos_min=pos_min, pos_max=pos_max)

    def move_to_raw(self, raw: int) -> None:
        # Drive the motor until the raw potentiometer reading reaches the target.
        #
        # :param raw: Raw ADC target in the range 0..65535.
        self._target_pos = None
        self._raw_target = max(0, min(UINT16_MAX, raw))
        movement_log("target", "mode=raw requested=%s target=%s running=%s" % (raw, self._raw_target, self.running))
        self._movement_started_at = None
        self._clear_fault()

    def set_motor_power(self, power: float) -> None:
        # Set the motor power limit.
        #
        # :param power: Rotation power in the range 0..1.
        self._motor.set_power(power=power)

    @property
    def running(self) -> bool:
        # Return whether the motor is energized.
        return self._motor.running

    @property
    def target_position(self) -> float | None:
        # Return the current movement target, if any.
        return self._target_pos

    @property
    def stalled(self) -> bool:
        # Return whether the controller has entered a movement fault.
        return self._stalled

    @property
    def fault(self) -> str | None:
        # Return the current movement fault, if any.
        return self._fault

    def tick(self, now_ms: int) -> None:
        # Process one bounded control-loop iteration.
        #
        # :param now_ms: Control-loop timestamp from time.ticks_ms().
        if self._stalled:
            self._led.value(not self._led.value())
            return

        if self._raw_target is not None:
            self._tick_raw(now_ms)
            return

        if self._target_pos is None:
            return

        current_position = self._pos.read(now_ms)
        self._last_measured_position = current_position
        if self._movement_started_at is None:
            self._movement_started_at = now_ms
        elapsed_ms = self._elapsed_ms(now_ms, self._movement_started_at)

        if elapsed_ms > self.MAX_MOVEMENT_MS:
            self.stop(fault="movement_timeout")
            return

        if self.running:
            if self._last_position is None:
                self._last_position = current_position
                self._no_progress_started_at = now_ms
            elif abs(current_position - self._last_position) >= self.STALL_PROGRESS:
                self._last_position = current_position
                self._no_progress_started_at = now_ms
            elif self._stalled_for(now_ms):
                self.stop(fault="no_position_progress")
                return
        else:
            self._no_progress_started_at = None

        position_error = current_position - self._target_pos
        tolerance = self.POSITION_PRECISION / 3 if self.running else self.POSITION_PRECISION
        speed = self._approach_speed(position_error)
        movement_log(
            "tick",
            "mode=normalized now_ms=%s pos=%s target=%s error=%s tolerance=%s speed=%s running=%s "
            "elapsed_ms=%s no_progress_since_ms=%s samples=%s index=%s adc_window=%s"
            % (
                now_ms,
                current_position,
                self._target_pos,
                position_error,
                tolerance,
                speed,
                self.running,
                elapsed_ms,
                self._no_progress_started_at,
                self._pos._sample_count,
                self._pos._sample_index,
                self._pos._samples,
            ),
        )

        # CW lowers the position, CCW raises it. An error whose sign opposes the direction chosen for this target means
        # the window has passed the target between two samples; reversing there makes it hunt around the target.
        crossed = (self._approach == "cw" and position_error < 0) or (self._approach == "ccw" and position_error > 0)
        if abs(position_error) < tolerance or crossed:
            movement_log(
                "reached",
                "mode=normalized error=%s tolerance=%s crossed=%s" % (position_error, tolerance, crossed),
            )
            self.stop()
        elif position_error > 0:
            if not self.running:
                self._last_position = current_position
                self._no_progress_started_at = now_ms
            self._approach = "cw"
            self._motor.set_speed(speed)
            self._motor.cw()
        else:
            if not self.running:
                self._last_position = current_position
                self._no_progress_started_at = now_ms
            self._approach = "ccw"
            self._motor.set_speed(speed)
            self._motor.ccw()

    def _approach_speed(self, position_error: float) -> float:
        # Fraction of the power limit for the remaining distance: full speed far from the target, slowing down linearly
        # to SLOWDOWN_MIN_SPEED at the target.
        distance = min(1.0, abs(position_error) / self.SLOWDOWN_DISTANCE)

        return self.SLOWDOWN_MIN_SPEED + (1 - self.SLOWDOWN_MIN_SPEED) * distance

    def _tick_raw(self, now_ms: int) -> None:
        # Drive toward a raw potentiometer target during endpoint calibration.
        raw_target = self._raw_target
        if raw_target is None:
            return

        raw = self._pos.raw
        self._last_measured_position = self._pos.position
        if self._movement_started_at is None:
            self._movement_started_at = now_ms
        elapsed_ms = self._elapsed_ms(now_ms, self._movement_started_at)

        if elapsed_ms > self.MAX_MOVEMENT_MS:
            self.stop(fault="movement_timeout")
            return

        if self.running:
            if self._last_position is None:
                self._last_position = float(raw)
                self._no_progress_started_at = now_ms
            elif abs(raw - self._last_position) >= self.RAW_STALL_DELTA:
                self._last_position = float(raw)
                self._no_progress_started_at = now_ms
            elif self._stalled_for(now_ms):
                self.stop(fault="no_position_progress")
                return
        else:
            self._no_progress_started_at = None

        error = raw - raw_target
        movement_log(
            "tick",
            "mode=raw now_ms=%s adc=%s target=%s error=%s tolerance=%s running=%s "
            "elapsed_ms=%s no_progress_since_ms=%s"
            % (
                now_ms,
                raw,
                raw_target,
                error,
                self.RAW_PRECISION,
                self.running,
                elapsed_ms,
                self._no_progress_started_at,
            ),
        )

        if abs(error) < self.RAW_PRECISION:
            movement_log("reached", "mode=raw error=%s tolerance=%s" % (error, self.RAW_PRECISION))
            self.stop()
        elif error > 0:
            if not self.running:
                self._last_position = float(raw)
                self._no_progress_started_at = now_ms
            self._motor.cw()
        else:
            if not self.running:
                self._last_position = float(raw)
                self._no_progress_started_at = now_ms
            self._motor.ccw()

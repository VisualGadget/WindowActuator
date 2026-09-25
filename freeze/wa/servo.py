from machine import ADC, PWM, Pin

UINT16_MAX = 65535


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
        self._cw_pin = cw_pin
        self._ccw_pin = ccw_pin
        self._led = status_led
        self.running = False
        self.stop()
        self.set_power(power=power)

    def set_power(self, power: float) -> None:
        # Set the motor PWM duty cycle.
        #
        # :param power: Rotation power in the range 0..1.
        if not 0 <= power <= 1:
            raise ValueError('Motor power must be in the range from zero to one')

        self._power_limit = power
        if self.running:
            self._power.duty_u16(round(power * UINT16_MAX))

    def cw(self) -> None:
        # Rotate clockwise.
        self._ccw_pin.off()
        self._cw_pin.on()
        self._power.duty_u16(round(self._power_limit * UINT16_MAX))
        self._led.on()
        self.running = True

    def ccw(self) -> None:
        # Rotate counterclockwise.
        self._cw_pin.off()
        self._ccw_pin.on()
        self._power.duty_u16(round(self._power_limit * UINT16_MAX))
        self._led.on()
        self.running = True

    def stop(self) -> None:
        # Stop rotation and remove motor drive signals.
        self._power.duty_u16(0)
        self._cw_pin.off()
        self._ccw_pin.off()
        self._led.off()
        self.running = False


class PositionSensor:
    # Gearbox axis absolute position sensor based on a potentiometer.

    SAMPLE_INTERVAL_S = 0.2
    AVERAGE_WINDOW = 4

    def __init__(self, pos_min: float = 0.0, pos_max: float = 1.0):
        # :param pos_min: Relative ADC value of the closed endpoint.
        # :param pos_max: Relative ADC value of the opened endpoint.
        self._adc = ADC(0)
        self._samples = [0] * self.AVERAGE_WINDOW
        self._sample_count = 0
        self._sample_index = 0
        self._last_sample_at = -self.SAMPLE_INTERVAL_S
        self.set_limits(pos_min=pos_min, pos_max=pos_max)

    def set_limits(self, pos_min: float, pos_max: float) -> None:
        # Set potentiometer calibration limits.
        #
        # :param pos_min: Relative ADC value of the closed endpoint.
        # :param pos_max: Relative ADC value of the opened endpoint.
        if not 0 <= pos_min < pos_max <= 1:
            raise ValueError('Position limits must satisfy 0 <= closed < opened <= 1')

        self._adc_min = round(pos_min * UINT16_MAX)
        self._adc_max = round(pos_max * UINT16_MAX)

    def _clamp(self, raw: int) -> float:
        # Convert a raw ADC value to a clamped normalized position.
        position = (raw - self._adc_min) / (self._adc_max - self._adc_min)

        return max(0.0, min(1.0, position))

    def read(self, now: float) -> float:
        # Sample and average the ADC on a slower cadence to reduce noise and Wi-Fi contention.
        if now - self._last_sample_at >= self.SAMPLE_INTERVAL_S:
            self._samples[self._sample_index] = self._adc.read_u16()
            self._sample_index = (self._sample_index + 1) % self.AVERAGE_WINDOW
            if self._sample_count < self.AVERAGE_WINDOW:
                self._sample_count += 1
            self._last_sample_at = now

        if self._sample_count == 0:
            return self._clamp(self._adc.read_u16())

        total = 0
        for value in self._samples:
            total += value

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
    MAX_MOVEMENT_S = 90
    STALL_TIMEOUT_S = 1.0
    STALL_PROGRESS = 0.001
    RAW_PRECISION = 200
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
        self._movement_started_at: float | None = None
        self._last_position: float | None = None
        self._last_measured_position: float | None = None
        self._no_progress_started_at: float | None = None
        self._stalled = False
        self._fault: str | None = None

    def _clear_fault(self) -> None:
        self._stalled = False
        self._fault = None
        self._last_position = None
        self._no_progress_started_at = None
        self._led.off()

    def _stalled_for(self, now: float) -> bool:
        # Return whether movement has made no progress for the stall timeout.
        return (
            self._no_progress_started_at is not None
            and now - self._no_progress_started_at >= self.STALL_TIMEOUT_S
        )

    @staticmethod
    def _validate_position(position: float) -> None:
        # Validate a normalized target position.
        if not 0 <= position <= 1:
            raise ValueError('Servo position must be in the range from zero to one')

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
        self._target_pos = new_pos
        self._movement_started_at = None
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
        self._target_pos = None
        self._raw_target = None
        self._movement_started_at = None
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

    def tick(self, now: float = 0) -> None:
        # Process one bounded control-loop iteration.
        #
        # :param now: Monotonic timestamp in seconds.
        if self._stalled:
            self._led.value(not self._led.value())
            return

        if self._raw_target is not None:
            self._tick_raw(now)
            return

        if self._target_pos is None:
            return

        current_position = self._pos.read(now)
        self._last_measured_position = current_position
        if self._movement_started_at is None:
            self._movement_started_at = now

        if now - self._movement_started_at > self.MAX_MOVEMENT_S:
            self.stop(fault='movement_timeout')
            return

        if self.running:
            if self._last_position is None:
                self._last_position = current_position
                self._no_progress_started_at = now
            elif abs(current_position - self._last_position) >= self.STALL_PROGRESS:
                self._last_position = current_position
                self._no_progress_started_at = now
            elif self._stalled_for(now):
                self.stop(fault='no_position_progress')
                return
        else:
            self._no_progress_started_at = None

        position_error = current_position - self._target_pos
        tolerance = self.POSITION_PRECISION / 3 if self.running else self.POSITION_PRECISION

        if abs(position_error) < tolerance:
            self.stop()
        elif position_error > 0:
            if not self.running:
                self._last_position = current_position
                self._no_progress_started_at = now
            self._motor.cw()
        else:
            if not self.running:
                self._last_position = current_position
                self._no_progress_started_at = now
            self._motor.ccw()

    def _tick_raw(self, now: float) -> None:
        # Drive toward a raw potentiometer target during endpoint calibration.
        raw_target = self._raw_target
        if raw_target is None:
            return

        raw = self._pos.raw
        self._last_measured_position = self._pos.position
        if self._movement_started_at is None:
            self._movement_started_at = now

        if now - self._movement_started_at > self.MAX_MOVEMENT_S:
            self.stop(fault='movement_timeout')
            return

        if self.running:
            if self._last_position is None:
                self._last_position = float(raw)
                self._no_progress_started_at = now
            elif abs(raw - self._last_position) >= self.RAW_STALL_DELTA:
                self._last_position = float(raw)
                self._no_progress_started_at = now
            elif self._stalled_for(now):
                self.stop(fault='no_position_progress')
                return
        else:
            self._no_progress_started_at = None

        error = raw - raw_target

        if abs(error) < self.RAW_PRECISION:
            self.stop()
        elif error > 0:
            if not self.running:
                self._last_position = float(raw)
                self._no_progress_started_at = now
            self._motor.cw()
        else:
            if not self.running:
                self._last_position = float(raw)
                self._no_progress_started_at = now
            self._motor.ccw()

import importlib.util
import sys
import types
from pathlib import Path


class FakePin:
    def __init__(self):
        self.state = False

    def on(self):
        self.state = True

    def off(self):
        self.state = False

    def value(self, value=None):
        if value is not None:
            self.state = bool(value)
        return int(self.state)


class FakePwm:
    def __init__(self, pin, freq, duty_u16):
        self.duty = duty_u16

    def duty_u16(self, duty):
        self.duty = duty


class FakeAdc:
    value = 32768

    def read_u16(self):
        return self.value


machine = types.ModuleType("machine")
machine.ADC = lambda _: FakeAdc()
machine.PWM = FakePwm
machine.Pin = FakePin
sys.modules["machine"] = machine

module_path = Path(__file__).parents[1] / "freeze" / "wa" / "servo.py"
spec = importlib.util.spec_from_file_location("test_servo_module", module_path)
assert spec is not None
servo_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(servo_module)
# MicroPython's ESP8266 tick counter wraps at 2**30 ms; ticks_diff returns the signed shortest distance.
TICKS_PERIOD = 1 << 30


def ticks_add(ticks, delta):
    return (ticks + delta) % TICKS_PERIOD


def ticks_diff(end, start):
    return (end - start + TICKS_PERIOD // 2) % TICKS_PERIOD - TICKS_PERIOD // 2


servo_module.time = types.SimpleNamespace(ticks_ms=lambda: 0, ticks_diff=ticks_diff)


def build_servo():
    motor = servo_module.Motor(FakePin(), FakePin(), FakePin(), FakePin(), power=0.5)
    sensor = servo_module.PositionSensor(pos_min=0.25, pos_max=0.75)
    return servo_module.Servo(motor, sensor, FakePin()), motor


def test_motor_stop_clears_pwm_and_direction():
    servo, motor = build_servo()
    servo.position = 1
    servo.tick(now_ms=1000)
    motor.stop()
    assert motor.running is False
    assert motor._power.duty == 0
    assert motor._cw_pin.state is False
    assert motor._ccw_pin.state is False


def test_position_sensor_clamps_outside_calibration():
    sensor = servo_module.PositionSensor(pos_min=0.25, pos_max=0.75)
    sensor._adc.value = 0
    assert sensor.position == 0
    sensor._adc.value = 65535
    assert sensor.position == 1


def test_servo_stops_after_movement_timeout():
    servo, motor = build_servo()
    servo.position = 1
    servo.tick(now_ms=0)
    servo.tick(now_ms=servo.MAX_MOVEMENT_MS + 1)
    assert servo.stalled is True
    assert servo.fault == "movement_timeout"
    assert motor.running is False


def test_servo_allows_feedback_to_remain_still_for_stall_grace_period():
    servo, motor = build_servo()
    servo.position = 1
    servo.tick(now_ms=0)
    servo.tick(now_ms=servo.STALL_TIMEOUT_MS - 100)
    assert servo.stalled is False
    assert motor.running is True


def test_servo_stops_after_stall_grace_period():
    servo, motor = build_servo()
    servo.position = 1
    servo.tick(now_ms=0)
    servo.tick(now_ms=servo.STALL_TIMEOUT_MS + 100)
    assert servo.stalled is True
    assert servo.fault == "no_position_progress"
    assert motor.running is False


def test_move_to_raw_drives_toward_target():
    servo, motor = build_servo()
    servo._pos._adc.value = 32768
    servo.move_to_raw(50000)
    servo.tick(now_ms=0)
    assert motor.running is True
    assert motor._cw_pin.state is False
    assert motor._ccw_pin.state is True


def test_move_to_raw_stops_at_target():
    servo, motor = build_servo()
    servo._pos._adc.value = 50000
    servo.move_to_raw(50000)
    servo.tick(now_ms=0)
    assert motor.running is False
    assert servo._raw_target is None


def test_move_to_raw_clears_mapped_target():
    servo, motor = build_servo()
    servo.position = 1
    servo.move_to_raw(40000)
    assert servo.target_position is None
    assert servo._raw_target == 40000


def test_position_sensor_samples_every_interval_in_milliseconds():
    sensor = servo_module.PositionSensor(pos_min=0.25, pos_max=0.75)
    for now_ms in range(0, 1000, 100):
        sensor.read(now_ms)
    # Samples at 0, 200, 400, 600 and 800 ms; the window holds the latest four.
    assert sensor._sample_count == sensor.AVERAGE_WINDOW
    assert sensor._sample_index == 5 % sensor.AVERAGE_WINDOW


def test_position_sensor_skips_samples_within_interval():
    sensor = servo_module.PositionSensor(pos_min=0.25, pos_max=0.75)
    sensor.read(0)
    sensor.read(sensor.SAMPLE_INTERVAL_MS - 1)
    assert sensor._sample_count == 1
    sensor.read(sensor.SAMPLE_INTERVAL_MS)
    assert sensor._sample_count == 2


def test_position_sensor_averages_only_taken_samples():
    sensor = servo_module.PositionSensor(pos_min=0.25, pos_max=0.75)
    sensor._adc.value = 32768
    # A single sample must not be diluted by the empty slots of the averaging window.
    assert abs(sensor.read(0) - 0.5) < 0.001


def test_position_sensor_samples_across_tick_wraparound():
    sensor = servo_module.PositionSensor(pos_min=0.25, pos_max=0.75)
    start = TICKS_PERIOD - 100
    sensor.read(start)
    sensor.read(ticks_add(start, sensor.SAMPLE_INTERVAL_MS))
    assert sensor._sample_count == 2


def test_new_target_discards_samples_from_previous_movement():
    servo, motor = build_servo()
    servo._pos._adc.value = 16384
    servo.position = 1
    for now_ms in range(0, 800, 100):
        servo.tick(now_ms=now_ms)
    servo._pos._adc.value = 32768
    servo.position = 0
    servo.tick(now_ms=800)
    assert abs(servo.measured_position - 0.5) < 0.001


def test_servo_stall_timeout_across_tick_wraparound():
    servo, motor = build_servo()
    start = TICKS_PERIOD - 300
    servo.position = 1
    servo.tick(now_ms=start)
    servo.tick(now_ms=ticks_add(start, servo.STALL_TIMEOUT_MS - 100))
    assert servo.stalled is False
    servo.tick(now_ms=ticks_add(start, servo.STALL_TIMEOUT_MS + 100))
    assert servo.fault == "no_position_progress"


def test_servo_movement_timeout_across_tick_wraparound():
    servo, motor = build_servo()
    start = TICKS_PERIOD - 300
    servo.position = 1
    servo.tick(now_ms=start)
    servo._last_position = None  # keep the stall check from firing first
    servo.tick(now_ms=ticks_add(start, servo.MAX_MOVEMENT_MS + 1))
    assert servo.fault == "movement_timeout"


def test_servo_stops_when_target_is_crossed_instead_of_reversing():
    servo, motor = build_servo()
    servo._pos._adc.value = 40960  # 0.75, above the target: drive CW toward lower positions
    servo.position = 0.5
    servo.tick(now_ms=0)
    assert motor._direction == "cw"
    servo._pos.reset()
    servo._pos._adc.value = 31129  # about 0.45: the target lies between two samples
    servo.tick(now_ms=200)
    assert motor.running is False
    assert servo.stalled is False
    assert servo.target_position is None


def test_servo_stops_when_target_is_crossed_while_opening():
    servo, motor = build_servo()
    servo._pos._adc.value = 24576  # 0.25, below the target: drive CCW toward higher positions
    servo.position = 0.5
    servo.tick(now_ms=0)
    assert motor._direction == "ccw"
    servo._pos.reset()
    servo._pos._adc.value = 34406  # about 0.55
    servo.tick(now_ms=200)
    assert motor.running is False
    assert servo.fault is None


def test_servo_keeps_driving_before_reaching_target():
    servo, motor = build_servo()
    servo._pos._adc.value = 40960
    servo.position = 0.5
    servo.tick(now_ms=0)
    servo._pos.reset()
    servo._pos._adc.value = 36044  # 0.6: still above the target
    servo.tick(now_ms=200)
    assert motor.running is True
    assert motor._direction == "cw"


def test_new_target_behind_moving_window_reverses_instead_of_stopping():
    servo, motor = build_servo()
    servo._pos._adc.value = 40960  # 0.75
    servo.position = 0.5
    servo.tick(now_ms=0)
    assert motor._direction == "cw"
    servo.position = 0.9  # new target behind the current motion
    servo.tick(now_ms=100)
    assert motor.running is True
    assert motor._direction == "ccw"
    assert servo.target_position == 0.9


def drive_from(adc_value, target):
    servo, motor = build_servo()
    servo._pos._adc.value = adc_value
    servo.position = target
    servo.tick(now_ms=0)
    return servo, motor


def test_motor_runs_at_full_power_far_from_target():
    servo, motor = drive_from(adc_value=16384, target=1)  # 0.0 -> 1.0
    assert motor._power.duty == round(0.5 * 65535)  # power limit 0.5, full speed


def test_motor_slows_down_linearly_near_target():
    servo, motor = drive_from(adc_value=32768, target=0.55)  # 0.5 -> 0.55, inside the slowdown distance
    expected_speed = servo.SLOWDOWN_MIN_SPEED + (1 - servo.SLOWDOWN_MIN_SPEED) * 0.05 / servo.SLOWDOWN_DISTANCE
    assert abs(motor._speed - expected_speed) < 0.001
    assert motor._power.duty == round(0.5 * motor._speed * 65535)


def test_motor_speed_never_drops_below_minimum():
    servo, motor = drive_from(adc_value=32768, target=0.55)
    servo._pos.reset()
    servo._pos._adc.value = 34078  # about 0.54: one point left, inside the slowdown zone, outside the running tolerance
    servo.tick(now_ms=200)
    assert motor.running is True
    remaining = abs(servo.measured_position - 0.55)
    expected = servo.SLOWDOWN_MIN_SPEED + (1 - servo.SLOWDOWN_MIN_SPEED) * remaining / servo.SLOWDOWN_DISTANCE
    assert abs(motor._speed - expected) < 0.01
    assert motor._speed >= servo.SLOWDOWN_MIN_SPEED


def test_motor_stop_restores_full_speed_for_next_movement():
    servo, motor = drive_from(adc_value=32768, target=0.55)
    servo.stop()
    servo._pos._adc.value = 16384
    servo.position = 1
    servo.tick(now_ms=1000)
    assert motor._power.duty == round(0.5 * 65535)


def test_power_limit_change_keeps_slowdown_speed():
    servo, motor = drive_from(adc_value=32768, target=0.55)
    speed = motor._speed
    motor.set_power(1.0)
    assert abs(motor._power.duty - speed * 65535) <= 1

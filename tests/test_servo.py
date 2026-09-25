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


machine = types.ModuleType('machine')
machine.ADC = lambda _: FakeAdc()
machine.PWM = FakePwm
machine.Pin = FakePin
sys.modules['machine'] = machine

module_path = Path(__file__).parents[1] / 'freeze' / 'wa' / 'servo.py'
spec = importlib.util.spec_from_file_location('test_servo_module', module_path)
assert spec is not None
servo_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(servo_module)


def build_servo():
    motor = servo_module.Motor(FakePin(), FakePin(), FakePin(), FakePin(), power=0.5)
    sensor = servo_module.PositionSensor(pos_min=0.25, pos_max=0.75)
    return servo_module.Servo(motor, sensor, FakePin()), motor


def test_motor_stop_clears_pwm_and_direction():
    servo, motor = build_servo()
    servo.position = 1
    servo.tick(now=1)
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
    servo.tick(now=0)
    servo.tick(now=servo.MAX_MOVEMENT_S + 1)
    assert servo.stalled is True
    assert servo.fault == 'movement_timeout'
    assert motor.running is False


def test_servo_allows_feedback_to_remain_still_for_stall_grace_period():
    servo, motor = build_servo()
    servo.position = 1
    servo.tick(now=0)
    servo.tick(now=servo.STALL_TIMEOUT_S - 0.1)
    assert servo.stalled is False
    assert motor.running is True


def test_servo_stops_after_stall_grace_period():
    servo, motor = build_servo()
    servo.position = 1
    servo.tick(now=0)
    servo.tick(now=servo.STALL_TIMEOUT_S + 0.1)
    assert servo.stalled is True
    assert servo.fault == 'no_position_progress'
    assert motor.running is False


def test_move_to_raw_drives_toward_target():
    servo, motor = build_servo()
    servo._pos._adc.value = 32768
    servo.move_to_raw(50000)
    servo.tick(now=0)
    assert motor.running is True
    assert motor._cw_pin.state is False
    assert motor._ccw_pin.state is True


def test_move_to_raw_stops_at_target():
    servo, motor = build_servo()
    servo._pos._adc.value = 50000
    servo.move_to_raw(50000)
    servo.tick(now=0)
    assert motor.running is False
    assert servo._raw_target is None


def test_move_to_raw_clears_mapped_target():
    servo, motor = build_servo()
    servo.position = 1
    servo.move_to_raw(40000)
    assert servo.target_position is None
    assert servo._raw_target == 40000


from machine import Pin, ADC, PWM


UINT16_MAX = 65535


class Motor:
    """
    DC motor driver TB6612FNG
    """
    def __init__(self, cw_pin: Pin, ccw_pin: Pin, pwm_pin: Pin, status_led: Pin, power: int = UINT16_MAX):
        """
        :param cw_pin: pin to rotate motor CW
        :param ccw_pin: pin to rotate motor CCW
        :param pwm_pin: rotation power PWM pin
        :param status_led: motor activity LED
        :param power: rotation speed/power, up to UINT16_MAX
        """
        self._cw_pin = cw_pin
        self._ccw_pin = ccw_pin
        self._power = PWM(pwm_pin, freq=1000, duty_u16=power)
        self._led = status_led
        self.running = False
        self.stop()

    def cw(self):
        """
        Rotate clockwise
        """
        self._ccw_pin.off()
        self._cw_pin.on()
        self._led.on()
        self.running = True

    def ccw(self):
        """
        Rotate counterclockwise
        """
        self._cw_pin.off()
        self._ccw_pin.on()
        self._led.on()
        self.running = True

    def stop(self):
        """
        Stop rotation
        """
        self._cw_pin.off()
        self._ccw_pin.off()
        self._led.off()
        self.running = False


class PositionSensor:
    """
    Gearbox axis absolute position sensor. Based on potentiometer.
    """
    def __init__(self, pos_min: int = 0, pos_max: int = UINT16_MAX):
        """
        :param pos_min: potentiometer ADC value of a low rotation position limit
        :param pos_max: potentiometer ADC value of a high rotation position limit
        """
        self._adc_min = pos_min
        self._adc_max = pos_max
        self._adc = ADC(0)

    @property
    def position(self) -> float:
        """
        Read position. Around [0 - 1].
        """
        pot = self._adc.read_u16()
        pos = (pot - self._adc_min) / (self._adc_max - self._adc_min)

        return pos


class Servo:
    """
    Servomotor
    """
    POSITION_PRECISION = 0.015

    def __init__(self, motor: Motor, pos_sensor: PositionSensor, status_led: Pin):
        """
        :param motor: servomotor
        :param pos_sensor: gearbox axis position sensor
        :param status_led: status LED
        """
        self._motor = motor
        self._pos = pos_sensor
        self._led = status_led
        self._target_pos: float = None

        # stall detector
        self._prev_tick_position: float = None
        self._same_position_read: int = 0
        self._stalled = False

    def _not_stalled(self):
        """
        Clear stale flag
        """
        self._prev_tick_position = None
        self._same_position_read = 0
        self._stalled = False
        self._led.off()

    @property
    def position(self) -> float:
        """
        Get servomotor position. 0 <= pos <= 1.
        """
        return max(0, min(1, self._pos.position))

    @position.setter
    def position(self, new_pos: float) -> float:
        """
        Set servomotor position

        :param new_pos: new position. 0 <= pos <= 1.
        """
        assert 0 <= new_pos <= 1
        self._target_pos = new_pos

        self._not_stalled()

    def stop(self, _stalled: bool = False):
        """
        Stop any movement

        :param _stalled: can't move
        """
        self._target_pos = None
        self._motor.stop()

        if not _stalled:
            self._not_stalled()

    @property
    def running(self) -> bool:
        """
        Motor is running
        """
        return self._motor.running

    @property
    def stalled(self) -> bool:
        """
        Motor is stalled
        """
        return self._stalled

    def tick(self):
        """
        Process state changes
        """
        # print(f'{self._stalled=}, {self._target_pos=}, {self.running=}')

        if self._stalled:
            self._led.value(not self._led.value())

        if self._target_pos is None:
            return

        cur_pos = self._pos.position

        if self.running and cur_pos == self._prev_tick_position:
            self._same_position_read += 1
            if self._same_position_read > 1:
                self._stalled = True
                self.stop(_stalled=True)
                return
        else:
            self._prev_tick_position = cur_pos
            self._same_position_read = 0

        pos_error = self._pos.position - self._target_pos

        # avoid small movements
        tol = self.POSITION_PRECISION / 3 if self.running else self.POSITION_PRECISION
        if abs(pos_error) < tol:
            self._motor.stop()
        elif pos_error > 0:
            self._motor.cw()
        else:
            self._motor.ccw()

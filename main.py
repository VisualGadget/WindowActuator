from machine import Pin, Signal, reset

import config as cfg
from mqtt import MQTTWindowActuator
from servo import Motor, PositionSensor, Servo


def main():
    status_led = Signal(2, Pin.OPEN_DRAIN, invert=True)

    motor = Motor(
        cw_pin=Pin(13, Pin.OUT),
        ccw_pin=Pin(15, Pin.OUT),
        pwm_pin=Pin(4, Pin.OUT),
        status_led=status_led
    )

    pos = PositionSensor(
        pos_min=15500,
        pos_max=52800
    )
    servo = Servo(
        motor=motor,
        pos_sensor=pos,
        status_led=status_led
    )

    mqtt_wa = MQTTWindowActuator(cfg.MQTT_SERVER, cfg.MQTT_USER, cfg.MQTT_PASSWORD, servo)
    mqtt_wa.run()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        reset()

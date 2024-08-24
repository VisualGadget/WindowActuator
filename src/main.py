import asyncio
from machine import Pin, Signal, reset

from microdot import Request
from utemplate import Template

import config as cfg
from mqtt import MQTTWindowActuator
from servo import Motor, PositionSensor, Servo
from web import web_server, HTML_ROOT


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

    @web_server.route('/window.html')
    async def window(request: Request):
        return Template(HTML_ROOT + 'window.html').render(pos=round(mqtt_wa.position))

    @web_server.route('/settings.html')
    async def settings(request: Request):
        with open(HTML_ROOT + 'settings.html', encoding='utf8') as f:
            return f.read()

    @web_server.route('/set_position', methods=['POST'])
    async def set_position(request: Request):
        mqtt_wa.position = float(request.form['position'])
        return ''

    loop = asyncio.new_event_loop()

    asyncio.create_task(mqtt_wa.run())
    asyncio.create_task(web_server.start_server(port=80, debug=True))

    loop.run_forever()


if __name__ == '__main__':
    try:
        main()
    except Exception as ex:
        # raise ex
        reset()

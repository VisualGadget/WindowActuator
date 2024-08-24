import asyncio
from machine import Pin, Signal, reset

from microdot import Microdot, Response, Request

import config as cfg
from mqtt import MQTTWindowActuator
from servo import Motor, PositionSensor, Servo


web_server = Microdot()
Response.default_content_type = 'text/html'


@web_server.route('/')
async def index(request: Request):
    with open('html/main.html', encoding='utf8') as f:
        return f.read()


@web_server.route('/style.css')
async def index(request: Request):
    with open('html/style.css', encoding='utf8') as f:
        return f.read()


@web_server.route('/window.html')
async def index(request: Request):
    with open('html/window.html', encoding='utf8') as f:
        return f.read()

@web_server.route('/settings.html')
async def index(request: Request):
    with open('html/settings.html', encoding='utf8') as f:
        return f.read()


@web_server.route('/set_position', methods=['POST'])
async def set_position(request: Request):
    print(f'{request.form["position"]=}')
    return ''


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

    loop = asyncio.new_event_loop()

    asyncio.create_task(mqtt_wa.run())
    asyncio.create_task(web_server.start_server(port=80, debug=True))

    loop.run_forever()
    # asyncio.new_event_loop().run_forever()


if __name__ == '__main__':
    try:
        main()
    except Exception as ex:
        # raise ex
        reset()

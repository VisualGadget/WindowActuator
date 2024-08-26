import asyncio
import time
from machine import Pin, Signal, reset
import network
import ubinascii

from microdot import Request, Response
from microdot.utemplate import Template

from src_freeze.mqtt import MQTTWindowActuator
from src_freeze.servo import Motor, PositionSensor, Servo
from src_freeze.web import web_server, HTML_ROOT
from src_freeze.settings import config


mqtt_wa: MQTTWindowActuator = None
Template.initialize(template_dir=HTML_ROOT)


@web_server.route('/window.html')
async def _window(request: Request):
    if mqtt_wa:
        return Template('window.html').render(pos=round(mqtt_wa.position * 100))
    else:
        return 'Not connected to MQTT server'


@web_server.route('/settings.html')
async def _settings(request: Request):
    return Response.send_file(HTML_ROOT + 'settings.html')


@web_server.route('/set_position', methods=['POST'])
async def _set_position(request: Request):
    if mqtt_wa:
        mqtt_wa.position = float(request.form['position']) / 100
    return ''


def exception_handler(loop, context):
    # """
    # asyncio exception handler
    # """
    print(f'Reset due to error: {context['exception']}')
    reset()


def main():
    status_led = Signal(2, Pin.OPEN_DRAIN, invert=True)

    # disable access point
    # ap_if = network.WLAN(network.AP_IF)
    # ap_if.active(False)

    # connect to Wi-Fi
    nic = network.WLAN(network.STA_IF)
    mac = ubinascii.hexlify(nic.config('mac')).decode()
    network.hostname(f'wa-{mac[-4:]}')
    nic.connect(config.wifi_ap, config.wifi_password)
    print('Connecting to WiFi', end='')
    while not nic.isconnected():
        time.sleep(1)
        print('.', end='')
        status_led.value(not status_led.value())

    if_cfg = dict(zip(
        ('IP', 'subnet', 'gateway', 'DNS'),
        nic.ifconfig()
    ))
    print(f'\nNetwork config: {if_cfg}')
    status_led.off()

    motor = Motor(
        cw_pin=Pin(13, Pin.OUT),
        ccw_pin=Pin(15, Pin.OUT),
        pwm_pin=Pin(4, Pin.OUT),
        status_led=status_led
    )
    pos = PositionSensor(
        pos_min=config.window_closed_pos,
        pos_max=config.window_opened_pos
    )
    servo = Servo(
        motor=motor,
        pos_sensor=pos,
        status_led=status_led
    )

    global mqtt_wa
    mqtt_wa = MQTTWindowActuator(
        server=config.mqtt_server,
        port=config.mqtt_port,
        user=config.mqtt_user,
        password=config.mqtt_password,
        servo=servo
    )

    asyncio.create_task(mqtt_wa.run())
    asyncio.create_task(web_server.start_server(port=80, debug=True))


if __name__ == '__main__':
    try:
        loop = asyncio.get_event_loop()
        loop.set_exception_handler(exception_handler)

        main()

        loop.run_forever()

    except Exception as ex:
        print(f'Reset due to error: {ex}')
        reset()

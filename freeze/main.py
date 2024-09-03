import asyncio
import time
from machine import Pin, Signal, reset
import network
import ubinascii

from microdot import Request
from microdot.utemplate import Template

from wa.mqtt import MQTTWindowActuator
from wa.servo import Motor, PositionSensor, Servo
from wa.web import web_server, HTML_ROOT
from wa.settings import config


PASSWORD_MASK = '*' * 8


mqtt_wa: MQTTWindowActuator = None
Template.initialize(template_dir=HTML_ROOT)


@web_server.route('/window.html')
async def _window(request: Request):
    if mqtt_wa:
        return Template('window.html').render(pos=round(mqtt_wa.position * 100))
    else:
        return 'Not connected to MQTT server'


@web_server.route('/set_position', methods=['POST'])
async def _set_position(request: Request):
    if mqtt_wa:
        mqtt_wa.position = float(request.form['position']) / 100
    return ''


@web_server.route('/network.html')
async def _settings(request: Request):
    return Template('network.html').render(
        device_name=config.device_name,
        wifi_ssid=config.wifi_ssid,
        wifi_password=PASSWORD_MASK if config.wifi_password else '',
        mqtt_server=config.mqtt_server,
        mqtt_port=config.mqtt_port,
        mqtt_user=config.mqtt_user,
        mqtt_password=PASSWORD_MASK if config.mqtt_password else ''
    )


@web_server.route('/set_network', methods=['POST'])
async def _set_network(request: Request):
    config.device_name = request.form['device_name']
    config.wifi_ssid = request.form['wifi_ssid']

    wifi_pwd = request.form['wifi_password']
    if wifi_pwd != PASSWORD_MASK:
        config.wifi_password = wifi_pwd

    config.mqtt_server = request.form['mqtt_server']
    config.mqtt_port = request.form['mqtt_port']
    config.mqtt_user = request.form['mqtt_user']

    mqtt_pwd = request.form['mqtt_password']
    if mqtt_pwd != PASSWORD_MASK:
        config.mqtt_password = mqtt_pwd

    config.save()

    reset()


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
    network.hostname(config.device_name)
    nic.connect(config.wifi_ssid, config.wifi_password)
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
        status_led=status_led,
        power=config.motor_power / 100
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
        servo=servo,
        client_name=config.device_name
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

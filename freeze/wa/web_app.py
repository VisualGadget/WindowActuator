import asyncio
import gc
import json
import time

import network
from machine import reset, reset_cause
from microdot import Request, Response, abort
from microdot.utemplate import Template
from utemplate import compiled
from wa import state, validation, version
from wa.settings import config
from wa.web import HTML_ROOT, web_server

PASSWORD_MASK = '*' * 8
WEB_MAX_CONTENT_LENGTH = 2048
WEB_MAX_BODY_LENGTH = 2048


class TemplateLoader(compiled.Loader):
    # Load templates frozen into firmware.

    def __init__(self, package, template_dir):
        super().__init__('templates', '.')


Request.max_content_length = WEB_MAX_CONTENT_LENGTH
Request.max_body_length = WEB_MAX_BODY_LENGTH
Template.initialize(template_dir=HTML_ROOT, loader_class=TemplateLoader)


@web_server.before_request
def _collect_before_request(request: Request):
    # Reclaim memory before rendering a request.
    gc.collect()


def dynamic_template(template_name: str, **context):
    # Render a dynamic template without allowing browser caching.
    return Response(
        Template(template_name).generate(**context),
        headers={'Cache-Control': 'no-store, max-age=0'}
    )


def html_escape(value: str) -> str:
    # Escape values inserted into HTML text and attribute contexts.
    return (
        str(value)
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&#39;')
    )


def _form_value(request: Request, name: str) -> str:
    # Read one required form value.
    value = request.form.get(name)
    if value is None:
        abort(400, f'Missing form field: {name}')

    return value


async def _restart_later() -> None:
    # Restart after the HTTP response has been delivered.
    await asyncio.sleep(0.5)
    reset()


@web_server.route('/window.html')
async def _window(request: Request):
    if state.mqtt_wa:
        return dynamic_template('window.html', pos=round(state.mqtt_wa.position * 100))

    return 'Not connected to MQTT server'


@web_server.route('/set_position', methods=['POST'])
async def _set_position(request: Request):
    if not state.mqtt_wa:
        return 'Device is not initialized', 503

    try:
        position = validation.parse_percentage(_form_value(request, 'position'), 'position')
    except ValueError as ex:
        abort(400, str(ex))

    state.mqtt_wa.request_position(position / 100)
    return ''


@web_server.route('/network.html')
async def _settings(request: Request):
    return dynamic_template(
        'network.html',
        device_name=html_escape(config.device_name),
        wifi_ssid=html_escape(config.wifi_ssid),
        wifi_password=PASSWORD_MASK if config.wifi_password else '',
        mqtt_server=html_escape(config.mqtt_server),
        mqtt_port=config.mqtt_port,
        mqtt_user=html_escape(config.mqtt_user),
        mqtt_password=PASSWORD_MASK if config.mqtt_password else ''
    )


@web_server.route('/set_network', methods=['POST'])
async def _set_network(request: Request):
    try:
        device_name = validation.validate_text(
            _form_value(request, 'device_name'), 'device name', 32, False
        )
        wifi_ssid = validation.validate_text(
            _form_value(request, 'wifi_ssid'), 'Wi-Fi SSID', 32, False
        )
        mqtt_server = validation.validate_text(
            _form_value(request, 'mqtt_server'), 'MQTT server', 64, False
        )
        mqtt_user = validation.validate_text(_form_value(request, 'mqtt_user'), 'MQTT user', 32)
        mqtt_port = validation.parse_port(_form_value(request, 'mqtt_port'), 'MQTT port')

        wifi_password = _form_value(request, 'wifi_password')
        mqtt_password = _form_value(request, 'mqtt_password')
        if wifi_password != PASSWORD_MASK:
            wifi_password = validation.validate_text(wifi_password, 'Wi-Fi password', 64)
        if mqtt_password != PASSWORD_MASK:
            mqtt_password = validation.validate_text(mqtt_password, 'MQTT password', 64)
    except ValueError as ex:
        abort(400, str(ex))

    config.device_name = device_name
    config.wifi_ssid = wifi_ssid
    config.mqtt_server = mqtt_server
    config.mqtt_port = mqtt_port
    config.mqtt_user = mqtt_user
    if wifi_password != PASSWORD_MASK:
        config.wifi_password = wifi_password
    if mqtt_password != PASSWORD_MASK:
        config.mqtt_password = mqtt_password

    config.save()
    asyncio.create_task(_restart_later())
    return ''


@web_server.route('/movement.html')
async def _movement(request: Request):
    return dynamic_template(
        'movement.html',
        motor_power=config.motor_power,
        window_opened_pos=config.window_opened_pos,
        window_closed_pos=config.window_closed_pos,
        raw_position=round(state.servo.raw_position, 1) if state.servo else 0.0
    )


@web_server.route('/set_movement', methods=['POST'])
async def _set_movement(request: Request):
    try:
        motor_power = validation.parse_percentage(_form_value(request, 'motor_power'), 'motor_power')
        wnd_opened = validation.parse_percentage(
            _form_value(request, 'window_opened_pos'), 'window_opened_pos'
        )
        wnd_closed = validation.parse_percentage(
            _form_value(request, 'window_closed_pos'), 'window_closed_pos'
        )
    except ValueError as ex:
        abort(400, str(ex))

    if not 10 <= motor_power <= 100 or not wnd_closed < wnd_opened:
        return 'Position limits must satisfy 0 <= closed < opened <= 100.', 400

    old_opened = config.window_opened_pos
    old_closed = config.window_closed_pos
    new_opened = int(wnd_opened)
    new_closed = int(wnd_closed)

    config.motor_power = int(motor_power)
    config.window_opened_pos = new_opened
    config.window_closed_pos = new_closed
    config.save()

    if state.mqtt_wa:
        state.mqtt_wa.set_motor_power(power=motor_power / 100)
        state.mqtt_wa.set_position_limits(
            pos_min=new_closed / 100,
            pos_max=new_opened / 100
        )

        if new_opened != old_opened:
            state.mqtt_wa.calibrate_to_raw(new_opened / 100)
        elif new_closed != old_closed:
            state.mqtt_wa.calibrate_to_raw(new_closed / 100)

    return ''


@web_server.route('/status')
async def _status(request: Request):
    sta_if = network.WLAN(network.STA_IF)
    ap_if = network.WLAN(network.AP_IF)
    actuator = state.mqtt_wa
    servo = state.servo

    payload = {
        'firmware': version.FIRMWARE_VERSION,
        'uptime_s': time.ticks_diff(time.ticks_ms(), state.boot_ticks_ms) // 1000,  # type: ignore[attr-defined]
        'reset_cause': reset_cause(),
        'free_heap': gc.mem_free(),  # type: ignore[attr-defined]
        'rssi_dbm': sta_if.status('rssi') if sta_if.isconnected() else None,
        'station': {
            'connected': sta_if.isconnected(),
            'ip': sta_if.ifconfig()[0] if sta_if.isconnected() else None,
        },
        'ap_active': ap_if.active(),
        'mqtt': {
            'connected': actuator.connected if actuator else False,
        },
        'servo': {
            'position': round(servo.position * 100, 1) if servo else None,
            'raw_adc': servo.raw_adc if servo else None,
            'raw_position': round(servo.raw_position, 1) if servo else None,
            'running': servo.running if servo else False,
            'stalled': servo.stalled if servo else False,
            'fault': servo.fault if servo else None,
        },
    }

    return Response(json.dumps(payload), headers={'Content-Type': 'application/json'})

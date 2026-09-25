import asyncio
import time

import network
import wa.web_app  # noqa: F401  (registers routes on wa.web.web_server)
from machine import WDT, Pin, Signal, reset
from wa import net, state
from wa.mqtt import MQTTWindowActuator
from wa.servo import Motor, PositionSensor, Servo
from wa.settings import config
from wa.web import web_server


async def _start_web_server() -> None:
    # Bind the HTTP server. This coroutine never returns while serving.
    await web_server.start_server(host='0.0.0.0', port=80, debug=False)


def safe_shutdown() -> None:
    # Stop the motor before a reset or fatal error.
    if state.mqtt_wa:
        state.mqtt_wa.safe_shutdown()
    elif state.servo:
        state.servo.stop(fault='system_shutdown')


def exception_handler(loop, context):
    # Stop hardware before recovering from an asynchronous task failure.
    exc = context.get('exception')
    if isinstance(exc, OSError):
        print(f'Ignored connection error: {exc}')
        return

    print(f'Reset due to error: {exc}')
    safe_shutdown()
    reset()


def main():
    status_led = Signal(2, Pin.OPEN_DRAIN, invert=True)
    ap_if = network.WLAN(network.AP_IF)
    ap_if.active(False)

    nic = network.WLAN(network.STA_IF)
    active_interface = net.connect_wifi(nic, status_led)

    ip, subnet, gateway, dns = active_interface.ifconfig()
    print(f'\nNetwork config: {{"IP": "{ip}", "subnet": "{subnet}", "gateway": "{gateway}", "DNS": "{dns}"}}')
    status_led.off()

    motor = Motor(
        cw_pin=Pin(13, Pin.OUT),
        ccw_pin=Pin(15, Pin.OUT),
        pwm_pin=Pin(4, Pin.OUT),
        status_led=status_led,
        power=config.motor_power / 100
    )
    pos = PositionSensor(
        pos_min=config.window_closed_pos / 100,
        pos_max=config.window_opened_pos / 100
    )
    state.servo = Servo(motor=motor, pos_sensor=pos, status_led=status_led)

    state.mqtt_wa = MQTTWindowActuator(
        server=config.mqtt_server,
        port=config.mqtt_port,
        user=config.mqtt_user,
        password=config.mqtt_password,
        servo=state.servo,
        client_name=config.device_name
    )

    watchdog = WDT(timeout=5000)
    state.mqtt_wa.set_watchdog(watchdog)

    asyncio.create_task(_start_web_server())
    asyncio.create_task(state.mqtt_wa.run())
    asyncio.create_task(state.mqtt_wa.network_run())
    asyncio.create_task(net.wifi_monitor())


if __name__ == '__main__':
    state.boot_ticks_ms = time.ticks_ms()  # type: ignore[attr-defined]
    try:
        loop = asyncio.get_event_loop()
        loop.set_exception_handler(exception_handler)
        main()
        loop.run_forever()
    except Exception as ex:
        print(f'Reset due to error: {ex}')
        safe_shutdown()
        reset()

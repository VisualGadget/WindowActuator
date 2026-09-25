import asyncio
import socket
import time

import network
from wa import state
from wa.settings import config
from wa.utils import wifi_mac

WIFI_CONNECT_TIMEOUT_S = 30
WIFI_CONNECT_RETRY_S = 10
WIFI_MONITOR_INTERVAL_S = 10
WIFI_LINK_CHECK_TIMEOUT_S = 2
WIFI_LINK_FAILURES_BEFORE_RECONNECT = 2


def connect_wifi(nic, status_led):
    # Connect to Wi-Fi with bounded retries and recovery-AP fallback.
    nic.active(True)
    network.hostname('wa_' + wifi_mac()[-4:])
    print('Connecting to WiFi', end='')
    deadline = time.time() + WIFI_CONNECT_TIMEOUT_S
    last_attempt = -WIFI_CONNECT_RETRY_S
    while not nic.isconnected() and time.time() < deadline:
        now = time.time()
        if now - last_attempt >= WIFI_CONNECT_RETRY_S:
            try:
                nic.connect(config.wifi_ssid, config.wifi_password)
            except Exception:
                nic.active(False)
                return _start_recovery_ap(status_led)
            last_attempt = now
        time.sleep(1)
        print('.', end='')

    if not nic.isconnected():
        nic.active(False)
        return _start_recovery_ap(status_led)

    return nic


def _start_recovery_ap(status_led):
    # Start a password-protected AP when station mode is unavailable.
    ap_if = network.WLAN(network.AP_IF)
    ap_if.active(True)
    mac_suffix = wifi_mac()[-4:]
    recovery_password = 'wa' + wifi_mac()[-8:]
    ap_if.config(ssid='WA_' + mac_suffix, security=network.AUTH_WPA2_PSK, key=recovery_password)
    print(f'\nWi-Fi recovery AP: WA_{mac_suffix}, password: {recovery_password}')
    status_led.off()
    return ap_if


def wifi_link_alive() -> bool:
    # Verify the station link with a short-lived TCP connection to the broker.
    sock = socket.socket()
    try:
        sock.settimeout(WIFI_LINK_CHECK_TIMEOUT_S)
        sock.connect((config.mqtt_server, config.mqtt_port))
        return True
    except Exception:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


async def wifi_monitor() -> None:
    # Keep station mode connected and disable the recovery AP once Wi-Fi is up.
    sta_if = network.WLAN(network.STA_IF)
    ap_if = network.WLAN(network.AP_IF)
    link_failures = 0
    while True:
        await asyncio.sleep(WIFI_MONITOR_INTERVAL_S)
        if sta_if.isconnected():
            if ap_if.active():
                ap_if.active(False)
                print('Recovery AP disabled')

            if state.mqtt_wa is not None and state.mqtt_wa.connected:
                link_failures = 0
                continue

            if wifi_link_alive():
                link_failures = 0
            else:
                link_failures += 1
                if link_failures >= WIFI_LINK_FAILURES_BEFORE_RECONNECT:
                    print('Wi-Fi link unresponsive, reconnecting')
                    sta_if.disconnect()
                    link_failures = 0
            continue

        link_failures = 0
        try:
            sta_if.active(True)
            sta_if.connect(config.wifi_ssid, config.wifi_password)
        except Exception as ex:
            print(f'Wi-Fi reconnect failed: {ex}')

import asyncio
import socket
import time

import network
from wa import state
from wa.settings import config
from wa.utils import wifi_mac

# One connection attempt: association plus DHCP. Calling connect() again restarts both, so an attempt is only replaced
# once it has failed or run this long; replies from the access point can be lost for tens of seconds after joining.
WIFI_CONNECT_ATTEMPT_S = 45
# At boot, keep trying this long before falling back to the recovery AP, unless the password is rejected.
WIFI_RECOVERY_AP_AFTER_S = 120
WIFI_MONITOR_INTERVAL_S = 10
WIFI_LINK_CHECK_TIMEOUT_S = 2
WIFI_LINK_FAILURES_BEFORE_RECONNECT = 2


def _elapsed_ms(since_ms: int) -> int:
    return time.ticks_diff(time.ticks_ms(), since_ms)  # type: ignore[attr-defined]


def _start_attempt(nic) -> int:
    # Start a connection attempt and return its start time in ticks_ms.
    nic.connect(config.wifi_ssid, config.wifi_password)
    return time.ticks_ms()  # type: ignore[attr-defined]


def _attempt_over(nic, started_ms: int) -> bool:
    # True once the attempt has failed or has run out of time.
    failed = nic.status() in (network.STAT_WRONG_PASSWORD, network.STAT_NO_AP_FOUND, network.STAT_CONNECT_FAIL)

    return failed or _elapsed_ms(started_ms) >= WIFI_CONNECT_ATTEMPT_S * 1000


def connect_wifi(nic, status_led):
    # Connect to Wi-Fi, falling back to the recovery AP for a rejected password or after WIFI_RECOVERY_AP_AFTER_S.
    nic.active(True)
    network.hostname('wa_' + wifi_mac()[-4:])
    # The access point sends 802.11n frames that the ESP8266 often misses (a third lost after all retries, DHCP replies
    # missing for up to a minute after joining). Legacy 802.11g rates reach it reliably and are plenty for this device.
    network.phy_mode(network.MODE_11G)
    print('Connecting to WiFi', end='')
    started = time.ticks_ms()  # type: ignore[attr-defined]
    try:
        attempt = _start_attempt(nic)
        while not nic.isconnected():
            given_up = _elapsed_ms(started) >= WIFI_RECOVERY_AP_AFTER_S * 1000
            if nic.status() == network.STAT_WRONG_PASSWORD or given_up:
                break

            if _attempt_over(nic, attempt):
                nic.disconnect()
                attempt = _start_attempt(nic)
            time.sleep(1)
            print('.', end='')

    except Exception:
        pass  # the SDK rejected the settings: fall back to the recovery AP below

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
    attempt_started = None
    while True:
        await asyncio.sleep(WIFI_MONITOR_INTERVAL_S)
        if sta_if.isconnected():
            attempt_started = None
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
        if attempt_started is not None and not _attempt_over(sta_if, attempt_started):
            continue  # still connecting: a new connect() would restart association and DHCP

        try:
            sta_if.active(True)
            attempt_started = _start_attempt(sta_if)
        except Exception as ex:
            attempt_started = None
            print(f'Wi-Fi reconnect failed: {ex}')

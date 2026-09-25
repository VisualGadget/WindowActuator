import network
import ubinascii


def wifi_mac() -> str:
    # Return the station interface MAC address as lowercase hexadecimal text.
    return ubinascii.hexlify(network.WLAN().config('mac')).decode()

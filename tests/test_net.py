import importlib.util
import sys
import types
from pathlib import Path

STAT_IDLE, STAT_CONNECTING, STAT_WRONG_PASSWORD, STAT_NO_AP_FOUND, STAT_CONNECT_FAIL, STAT_GOT_IP = 0, 1, 2, 3, 4, 5


class Clock:
    def __init__(self):
        self.ms = 0

    def ticks_ms(self):
        return self.ms

    def ticks_diff(self, end, start):
        return end - start

    def sleep(self, seconds):
        self.ms += int(seconds * 1000)


class FakeStation:
    # Plays back connection outcomes: each connect() starts the next scripted attempt, given as (ms until outcome,
    # outcome status).
    def __init__(self, clock, attempts):
        self.clock = clock
        self.attempts = list(attempts)
        self.connects = []
        self.disconnects = 0
        self.active_state = False
        self._current = None

    def active(self, value=None):
        if value is not None:
            self.active_state = value
        return self.active_state

    def connect(self, ssid, password):
        self.connects.append(self.clock.ms)
        delay, outcome = self.attempts.pop(0) if self.attempts else (10**9, STAT_CONNECTING)
        self._current = (self.clock.ms + delay, outcome)

    def disconnect(self):
        self.disconnects += 1
        self._current = None

    def status(self):
        if self._current is None:
            return STAT_IDLE
        at, outcome = self._current
        return outcome if self.clock.ms >= at else STAT_CONNECTING

    def isconnected(self):
        return self.status() == STAT_GOT_IP


class FakeAp:
    def __init__(self):
        self.active_state = False

    def active(self, value=None):
        if value is not None:
            self.active_state = value
        return self.active_state

    def config(self, **kwargs):
        pass


network = types.ModuleType('network')
network.STA_IF, network.AP_IF = 0, 1
network.STAT_WRONG_PASSWORD = STAT_WRONG_PASSWORD
network.STAT_NO_AP_FOUND = STAT_NO_AP_FOUND
network.STAT_CONNECT_FAIL = STAT_CONNECT_FAIL
network.MODE_11G = 2
network.AUTH_WPA2_PSK = 3
network.hostname = lambda name: None
network.phy_modes = []
network.phy_mode = lambda mode=None: network.phy_modes.append(mode)
network.ap = FakeAp()
network.WLAN = lambda interface: network.ap
sys.modules['network'] = network

for name, attrs in (
    ('wa', {}),
    ('wa.state', {'mqtt_wa': None}),
    ('wa.settings', {'config': types.SimpleNamespace(wifi_ssid='ssid', wifi_password='secret')}),
    ('wa.utils', {'wifi_mac': lambda: '485519c7d945'}),
):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module
sys.modules['wa'].state = sys.modules['wa.state']

module_path = Path(__file__).parents[1] / 'freeze' / 'wa' / 'net.py'
spec = importlib.util.spec_from_file_location('net', module_path)
assert spec is not None
net = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(net)


def connect(attempts):
    clock = Clock()
    net.time = types.SimpleNamespace(ticks_ms=clock.ticks_ms, ticks_diff=clock.ticks_diff, sleep=clock.sleep)
    network.ap = FakeAp()
    station = FakeStation(clock, attempts)
    result = net.connect_wifi(station, types.SimpleNamespace(off=lambda: None))
    return result, station, clock


def test_switches_to_802_11g_before_connecting():
    network.phy_modes.clear()
    connect([(3000, STAT_GOT_IP)])
    assert network.phy_modes == [network.MODE_11G]


def test_slow_attempt_is_not_restarted():
    # DHCP replies can be lost for a long time; a reconnect every few seconds would restart DHCP each time.
    result, station, clock = connect([(40_000, STAT_GOT_IP)])
    assert result is station
    assert len(station.connects) == 1
    assert station.disconnects == 0


def test_stalled_attempt_is_replaced_after_attempt_limit():
    result, station, clock = connect([(10**9, STAT_CONNECTING), (3000, STAT_GOT_IP)])
    assert result is station
    assert station.connects == [0, net.WIFI_CONNECT_ATTEMPT_S * 1000]
    assert station.disconnects == 1


def test_failed_attempt_is_retried_at_once():
    result, station, clock = connect([(2000, STAT_NO_AP_FOUND), (3000, STAT_GOT_IP)])
    assert result is station
    assert station.connects == [0, 2000]


def test_wrong_password_starts_recovery_ap_immediately():
    result, station, clock = connect([(2000, STAT_WRONG_PASSWORD)])
    assert result is network.ap
    assert network.ap.active_state is True
    assert station.active_state is False
    assert clock.ms <= 3000


def test_recovery_ap_after_overall_limit():
    result, station, clock = connect([(10**9, STAT_CONNECTING)] * 10)
    assert result is network.ap
    assert net.WIFI_RECOVERY_AP_AFTER_S * 1000 <= clock.ms <= (net.WIFI_RECOVERY_AP_AFTER_S + 1) * 1000
    assert len(station.connects) == net.WIFI_RECOVERY_AP_AFTER_S // net.WIFI_CONNECT_ATTEMPT_S + 1


def test_attempt_over():
    clock = Clock()
    net.time = types.SimpleNamespace(ticks_ms=clock.ticks_ms, ticks_diff=clock.ticks_diff, sleep=clock.sleep)
    station = FakeStation(clock, [(10**9, STAT_CONNECTING)])
    started = net._start_attempt(station)
    clock.ms = net.WIFI_CONNECT_ATTEMPT_S * 1000 - 1
    assert net._attempt_over(station, started) is False
    clock.ms += 1
    assert net._attempt_over(station, started) is True

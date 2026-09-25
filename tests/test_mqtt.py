import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path


class FakeAsyncMqtt:
    instance = None

    def __init__(self, **kwargs):
        FakeAsyncMqtt.instance = self
        self.kwargs = kwargs
        self.connected = False
        self.published = []
        self.subscriptions = []
        self.will = None
        self.pings = 0

    def set_callback(self, callback):
        self.callback = callback

    def set_last_will(self, topic, message, retain=False, qos=0):
        self.will = (topic, message, retain, qos)

    async def connect(self, clean_session=True, timeout=5.0):
        self.connected = True

    async def publish(self, topic, message, retain=False, qos=0):
        self.published.append((topic, message, retain, qos))

    async def subscribe(self, topic, qos=0):
        self.subscriptions.append(topic)

    async def ping(self):
        self.pings += 1

    def close(self):
        self.connected = False


class FakeServo:
    POSITION_PRECISION = 0.015
    position = 0.42
    measured_position = 0.42
    target_position = None
    running = False
    stalled = False
    fault = None
    opening = False
    raw_adc = 32768

    def set_position_limits(self, **kwargs):
        return self.position

    def set_motor_power(self, **kwargs):
        pass

    def move_to_raw(self, raw):
        pass

    def stop(self, **kwargs):
        self.running = False


async_mqtt_module = types.ModuleType('wa.async_mqtt')
async_mqtt_module.AsyncMQTTClient = FakeAsyncMqtt
sys.modules['wa.async_mqtt'] = async_mqtt_module

servo_module = types.ModuleType('wa.servo')
servo_module.Servo = FakeServo
servo_module.UINT16_MAX = 65535
sys.modules['wa.servo'] = servo_module

utils_module = types.ModuleType('wa.utils')
utils_module.wifi_mac = lambda: '485519c7d945'
sys.modules['wa.utils'] = utils_module

module_path = Path(__file__).parents[1] / 'freeze' / 'wa' / 'mqtt.py'
spec = importlib.util.spec_from_file_location('mqtt_module', module_path)
assert spec is not None
mqtt_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mqtt_module)


def build_client():
    return mqtt_module.MQTTWindowActuator(
        server='192.0.2.1', port=1883, user='iot', password='secret',
        servo=FakeServo(), client_name='lrWindow'
    )


def run_async(coro):
    return asyncio.run(coro)


def test_discovery_uses_stable_identity_and_availability():
    client = build_client()
    run_async(client._connect())
    mqtt = FakeAsyncMqtt.instance
    assert mqtt.kwargs['client_id'] == 'wa_d945'
    assert mqtt.will == ('Household/window/wa_d945/availability', 'offline', True, 0)
    cover_payload = next(
        json.loads(payload)
        for topic, payload, *_ in mqtt.published
        if topic == 'homeassistant/cover/wa_d945_window/config'
    )
    assert cover_payload['availability_topic'] == 'Household/window/wa_d945/availability'
    assert 'expire_after' not in cover_payload
    assert client.position == 0.42


def test_connect_publishes_online_and_subscribes():
    client = build_client()
    run_async(client._connect())
    mqtt = FakeAsyncMqtt.instance
    assert ('Household/window/wa_d945/availability', 'online', True, 0) in mqtt.published
    assert mqtt.subscriptions


def test_invalid_mqtt_position_is_ignored():
    client = build_client()
    client._inbox(b'Household/window/wa_d945_window/position/set', b'55')
    assert client._pending_position == 0.55
    client._inbox(b'Household/window/wa_d945_window/position/set', b'invalid')
    assert client._pending_position == 0.55


def test_stop_command_queues_emergency_stop():
    client = build_client()
    client._inbox(b'Household/window/wa_d945_window/state/set', b'STOP')
    assert client._pending_stop is True

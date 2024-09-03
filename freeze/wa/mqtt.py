import asyncio
import json
import time
import umqtt.simple

from wa.servo import Servo
from wa.utils import wifi_mac


class MQTTWindowActuator:
    # """
    # Home Assistant MQTT window actuator device
    # """

    _WINDOW_DEV = 'window'
    _STALE_DETECTOR_DEV = 'stale_detector'
    _STATE_UPDATE_INTERVAL_S = 20 * 60  # 20 min

    def __init__(self, server: str, port: int, user: str, password: str, servo: Servo, client_name: str):
        # """
        # :param server: server address
        # :param port: server port
        # :param user: user
        # :param password: password
        # :param servo: window servomotor
        # :param client_name: MQTT client name
        # """
        self._servo = servo
        self._position: float = None
        self._stalled = False

        mac = wifi_mac()
        device = {
            'model': 'WA1',
            'manufacturer': 'dIcEmAN',
            'name': 'Window',
            'identifiers': mac
        }
        self._devices = {
            self._WINDOW_DEV: {
                'device_class': 'window',
                'unit_of_measurement': '%',
                'expire_after': self._STATE_UPDATE_INTERVAL_S * 3
            },
            self._STALE_DETECTOR_DEV: {
                'device_class': 'problem',
                'expire_after': self._STATE_UPDATE_INTERVAL_S * 3
            }
        }
        self._mqtt = umqtt.simple.MQTTClient(
            client_id=client_name,
            server=server,
            port=port,
            user=user,
            password=password
        )
        self._mqtt.set_callback(self._inbox)
        self._connect()

        for dev_name, sensor_info in self._devices.items():
            uid = f'{client_name}_{dev_name}'
            topic_base = f'Household/window/{uid}'

            sensor_info['name'] = dev_name
            sensor_info['unique_id'] = uid
            sensor_info['device'] = device

            if dev_name == self._WINDOW_DEV:
                platform = 'cover'
                sensor_info['command_topic'] = topic_base + '/state/set'
                sensor_info['set_position_topic'] = topic_base + '/position/set'
                sensor_info['position_topic'] = topic_base + '/position/notify'

            elif dev_name == self._STALE_DETECTOR_DEV:
                platform = 'binary_sensor'
                sensor_info['state_topic'] = topic_base + '/stale/notify'

            # HA MQTT discovery
            ha_discovery_topic = f'homeassistant/{platform}/{uid}/config'
            self._mqtt.publish(ha_discovery_topic, json.dumps(sensor_info), True)

            # command subscriptions
            for set_topic in ('command_topic', 'set_position_topic'):
                if set_topic in sensor_info:
                    self._mqtt.subscribe(sensor_info[set_topic])

        self._retrieve_current_position()
        self.send_update()

    def _retrieve_current_position(self):
        # """
        # Current position is servo position
        # """
        self._position = self._servo.position

    def _connect(self):
        self._mqtt.connect()

    def send_update(self):
        # """
        # Send parameters update to MQTT server
        # """
        state = ('OFF', 'ON')[self._stalled]
        self._mqtt.publish(self._devices[self._STALE_DETECTOR_DEV]['state_topic'], state)

        pos = str(self._position * 100)
        self._mqtt.publish(self._devices[self._WINDOW_DEV]['position_topic'], pos)

        self.last_update = time.time()

    async def run(self):
        # """
        # Main event loop
        # """

        while True:
            self._mqtt.check_msg()
            self._set_stalled(self._servo.stalled)

            self._servo.tick()

            if time.time() - self.last_update > self._STATE_UPDATE_INTERVAL_S:
                self.send_update()

            idle = 0.1 if self._servo.running else 0.5
            await asyncio.sleep(idle)

    def _inbox(self, topic: bytes, msg: bytes):
        # """
        # MQTT incoming commands processing

        # :param topic: MQTT topic
        # :param msg: message body
        # """
        top = topic.decode()

        if top == self._devices[self._WINDOW_DEV]['command_topic']:
            if msg == b'OPEN':
                self.position = 1

            elif msg == b'CLOSE':
                self.position = 0

            elif msg == b'STOP':
                self._servo.stop()
                self._stalled = False
                self._retrieve_current_position()
                self.send_update()

        if top == self._devices[self._WINDOW_DEV]['set_position_topic']:
            new_position = float(msg) / 100
            self.position = new_position

    @property
    def position(self) -> float:
        # """
        # Current window opening
        # """
        assert self._position is not None

        return self._position

    @position.setter
    def position(self, position: float):
        # """
        # Change window opening

        # :param position: new state
        # """
        assert 0 <= position <= 1
        if position == self._position:
            return

        self._servo.position = self._position = position

        self.send_update()

    def _set_stalled(self, stalled: bool):
        # """
        # Change stale status

        # :param stalled: new state
        # """
        if stalled == self._stalled:
            return

        self._stalled = stalled
        if stalled:
            self._retrieve_current_position()

        self.send_update()

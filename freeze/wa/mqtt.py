import asyncio
import json
import time

import umqtt.simple
from wa.servo import Servo
from wa.utils import wifi_mac


class MQTTWindowActuator:
    """
    Home Assistant MQTT window actuator device.
    """

    _WINDOW_DEV = 'window'
    _STALE_DETECTOR_DEV = 'stale_detector'
    _STATE_UPDATE_INTERVAL_S = 20 * 60  # 20 min
    _MQTT_KEEPALIVE_S = 60
    _MQTT_PING_INTERVAL_S = _MQTT_KEEPALIVE_S // 2
    _MQTT_RECONNECT_INTERVAL_S = 10

    def __init__(self, server: str, port: int, user: str, password: str, servo: Servo, client_name: str):
        """
        Initialize the MQTT window actuator.

        :param server: MQTT broker address.
        :param port: MQTT broker port.
        :param user: MQTT username.
        :param password: MQTT password.
        :param servo: Window servomotor.
        :param client_name: MQTT client name.
        """
        self._servo = servo
        self._position = 0.0
        self._stalled = False
        self._connected = False
        self._last_ping = 0.0
        self._last_connect_attempt = 0.0
        self.last_update = time.time()

        mac = wifi_mac()
        device = {
            'model': 'WA1',
            'manufacturer': 'dIcEmAN',
            'name': 'Window',
            'identifiers': mac
        }
        self._availability_topic = f'Household/window/{client_name}/availability'
        self._devices: dict = {
            self._WINDOW_DEV: {
                'device_class': 'window'
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
            password=password,
            keepalive=self._MQTT_KEEPALIVE_S
        )
        self._mqtt.set_callback(self._inbox)

        self._discovery_topics: dict = {}
        for dev_name, sensor_info in self._devices.items():
            uid = f'{client_name}_{dev_name}'
            topic_base = f'Household/window/{uid}'

            sensor_info['name'] = dev_name
            sensor_info['unique_id'] = uid
            sensor_info['device'] = device
            sensor_info['availability_topic'] = self._availability_topic
            sensor_info['payload_available'] = 'online'
            sensor_info['payload_not_available'] = 'offline'

            if dev_name == self._WINDOW_DEV:
                platform = 'cover'
                sensor_info['command_topic'] = topic_base + '/state/set'
                sensor_info['set_position_topic'] = topic_base + '/position/set'
                sensor_info['position_topic'] = topic_base + '/position/notify'

            elif dev_name == self._STALE_DETECTOR_DEV:
                platform = 'binary_sensor'
                sensor_info['state_topic'] = topic_base + '/stale/notify'

            self._discovery_topics[dev_name] = f'homeassistant/{platform}/{uid}/config'

        self._retrieve_current_position()
        self._connect()

    def _retrieve_current_position(self) -> None:
        # """
        # Current position is servo position
        # """
        self._position = self._servo.position

    def set_position_limits(self, pos_min: float, pos_max: float) -> None:
        """
        Apply new position sensor calibration limits and retain the current percentage.

        :param pos_min: Potentiometer relative ADC value of the closed endpoint.
        :param pos_max: Potentiometer relative ADC value of the opened endpoint.
        """
        self._position = self._servo.set_position_limits(pos_min=pos_min, pos_max=pos_max)
        self.send_update()

    def set_motor_power(self, power: float) -> None:
        """
        Apply a new motor power limit.

        :param power: Rotation power in the range from zero to one.
        """
        self._servo.set_motor_power(power=power)

    def _publish_discovery(self) -> None:
        """
        Publish retained Home Assistant discovery data and restore subscriptions.
        """
        for dev_name, sensor_info in self._devices.items():
            self._mqtt.publish(
                self._discovery_topics[dev_name],
                json.dumps(sensor_info),
                True
            )

            for set_topic in ('command_topic', 'set_position_topic'):
                if set_topic in sensor_info:
                    self._mqtt.subscribe(sensor_info[set_topic])

    def _mark_disconnected(self, error: Exception | None = None) -> None:
        """
        Close a failed MQTT connection and schedule another connection attempt.

        :param error: Error that caused the connection to fail.
        """
        if error:
            print(f'MQTT connection lost: {error}')

        self._connected = False
        sock = self._mqtt.sock
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

        self._mqtt.sock = None

        self._last_connect_attempt = time.time()

    def _connect(self) -> None:
        """
        Connect to the broker, publish availability, and initialize MQTT state.
        """
        self._last_connect_attempt = time.time()
        try:
            self._mqtt.set_last_will(
                self._availability_topic,
                'offline',
                retain=True
            )
            self._mqtt.connect(timeout=5)
            self._connected = True
            self._publish_discovery()
            self._mqtt.publish(self._availability_topic, 'online', True)
            self._last_ping = time.time()
            self.send_update()
            if self._connected:
                print('Connected to MQTT broker')
        except Exception as ex:
            self._mark_disconnected(ex)

    def send_update(self) -> None:
        # """
        # Send parameters update to MQTT server
        # """
        if not self._connected:
            return

        try:
            state = ('OFF', 'ON')[self._stalled]
            self._mqtt.publish(self._devices[self._STALE_DETECTOR_DEV]['state_topic'], state)

            pos = str(self._position * 100)
            self._mqtt.publish(self._devices[self._WINDOW_DEV]['position_topic'], pos)
        except Exception as ex:
            self._mark_disconnected(ex)
            return

        self.last_update = time.time()

    async def run(self):
        """
        Run the MQTT and servo event loop.
        """

        while True:
            if self._connected:
                try:
                    self._mqtt.check_msg()

                    if self._connected:
                        now = time.time()
                        if now - self._last_ping >= self._MQTT_PING_INTERVAL_S:
                            self._mqtt.ping()
                            self._last_ping = now

                        if now - self.last_update > self._STATE_UPDATE_INTERVAL_S:
                            self.send_update()
                except Exception as ex:
                    self._mark_disconnected(ex)
            elif time.time() - self._last_connect_attempt >= self._MQTT_RECONNECT_INTERVAL_S:
                self._connect()

            self._set_stalled(self._servo.stalled)

            self._servo.tick()

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

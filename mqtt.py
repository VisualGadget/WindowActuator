import json
import time
import ubinascii
import network
import umqtt.simple

from servo import Servo


class MQTTWindowActuator:
    """
    Home Assistant MQTT window actuator device
    """

    POSITION_PARAMETER = 'position'
    STALE_PARAMETER = 'stale_detector'

    def __init__(self, server: str, user: str, password: str, servo: Servo):
        """
        :param server: server address
        :param user: user
        :param password: password
        :param servo: window servomotor
        """
        self._servo = servo
        self._position = None
        self._stalled = False

        mac = ubinascii.hexlify(network.WLAN().config('mac')).decode()
        device = {
            'model': 'WA1',
            'manufacturer': 'dIcEmAN',
            'name': 'Window',
            'identifiers': mac
        }
        self._public_parameters = {
            self.POSITION_PARAMETER: {
                'device_class': 'window',
                'unit_of_measurement': '%',
                'expire_after': 15 * 60  # 15 minutes
            },
            self.STALE_PARAMETER: {
                'device_class': 'problem',
                'expire_after': 15 * 60  # 15 minutes
            }
        }
        self._mqtt = umqtt.simple.MQTTClient(f'Window-{mac[-4:]}', server, user=user, password=password)
        self._mqtt.set_callback(self._inbox)
        self._connect()

        for param_name, sensor_info in self._public_parameters.items():
            uid = f'wa_{mac[-4:]}_{param_name}'
            topic_base = f'Household/window/{uid}'

            sensor_info['name'] = param_name
            sensor_info['unique_id'] = uid
            sensor_info['device'] = device

            if param_name == self.POSITION_PARAMETER:
                platform = 'cover'
                sensor_info['command_topic'] = topic_base + '/state/set'
                sensor_info['set_position_topic'] = topic_base + '/position/set'
                sensor_info['position_topic'] = topic_base + '/position/notify'

            elif param_name == self.STALE_PARAMETER:
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
        """
        Current position is servo position
        """
        self._position = self._servo.position

    def _connect(self):
        self._mqtt.connect()

    def send_update(self):
        """
        Send parameters update to MQTT server
        """
        state = ('OFF', 'ON')[self._stalled]
        self._mqtt.publish(self._public_parameters[self.STALE_PARAMETER]['state_topic'], state)

        pos = str(self._position * 100)
        self._mqtt.publish(self._public_parameters[self.POSITION_PARAMETER]['position_topic'], pos)

    def run(self):
        """
        Main event loop
        """
        while True:
            self._mqtt.check_msg()
            self._set_stalled(self._servo.stalled)

            self._servo.tick()

            idle = 0.1 if self._servo.running else 0.5
            time.sleep(idle)

    def _inbox(self, topic: bytes, msg: bytes):
        """
        MQTT incoming commands processing

        :param topic: MQTT topic
        :param msg: message body
        """
        topic = topic.decode()

        if topic == self._public_parameters[self.POSITION_PARAMETER]['command_topic']:
            if msg == b'OPEN':
                self._set_position(1)

            elif msg == b'CLOSE':
                self._set_position(0)

            elif msg == b'STOP':
                self._servo.stop()
                self._stalled = False
                self._retrieve_current_position()
                self.send_update()

        if topic == self._public_parameters[self.POSITION_PARAMETER]['set_position_topic']:
            new_position = float(msg) / 100
            self._set_position(new_position)

    def _set_position(self, position: float, send_update: bool = True):
        """
        Change window opening

        :param position: new state
        :param send_update: send position update
        """
        assert 0 <= position <= 1
        if position == self._position:
            return

        self._servo.position = self._position = position

        if send_update:
            self.send_update()

    def _set_stalled(self, stalled: bool):
        """
        Change stale status

        :param stalled: new state
        """
        if stalled == self._stalled:
            return

        self._stalled = stalled
        if stalled:
            self._retrieve_current_position()

        self.send_update()

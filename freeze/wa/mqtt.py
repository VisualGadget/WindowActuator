import asyncio
import json
import time

from wa.async_mqtt import AsyncMQTTClient
from wa.servo import UINT16_MAX, Servo
from wa.utils import wifi_mac


class MQTTWindowActuator:
    # Home Assistant MQTT integration and network-side actuator commands.

    _WINDOW_DEV = 'window'
    _STALE_DETECTOR_DEV = 'stale_detector'
    _STATE_UPDATE_INTERVAL_S = 20 * 60
    _MQTT_KEEPALIVE_S = 60
    _MQTT_PING_INTERVAL_S = _MQTT_KEEPALIVE_S // 2
    _MQTT_RECONNECT_INTERVAL_S = 10
    _CONTROL_INTERVAL_S = 0.1
    _MOVING_PUBLISH_INTERVAL_S = 1.0

    def __init__(self, server: str, port: int, user: str, password: str, servo: Servo, client_name: str):
        # Initialize the MQTT integration.
        #
        # :param server: MQTT broker address.
        # :param port: MQTT broker port.
        # :param user: MQTT username.
        # :param password: MQTT password.
        # :param servo: Window servo controller.
        # :param client_name: Display name used for compatibility with existing settings.
        self._servo = servo
        self._watchdog = None
        self._last_ping = 0.0
        self._last_update = 0.0
        self._last_control_tick = time.time()
        self._last_published_position: float | None = None
        self._pending_position: float | None = None
        self._pending_stop = False
        self._state_dirty = True
        self._published_fault: str | None = None

        mac = wifi_mac()
        self._device_id = 'wa_' + mac[-4:]
        device = {
            'model': 'WA1',
            'manufacturer': 'dIcEmAN',
            'name': client_name,
            'identifiers': mac
        }
        self._availability_topic = f'Household/window/{self._device_id}/availability'
        self._devices: dict[str, dict] = {
            self._WINDOW_DEV: {
                'device_class': 'window'
            },
            self._STALE_DETECTOR_DEV: {
                'device_class': 'problem'
            }
        }
        self._mqtt = AsyncMQTTClient(
            client_id=self._device_id,
            server=server,
            port=port,
            user=user,
            password=password,
            keepalive=self._MQTT_KEEPALIVE_S
        )
        self._mqtt.set_callback(self._inbox)

        self._discovery_topics: dict[str, str] = {}
        for dev_name, sensor_info in self._devices.items():
            uid = f'{self._device_id}_{dev_name}'
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
                sensor_info['json_attributes_topic'] = topic_base + '/attributes/notify'
                sensor_info['state_topic'] = topic_base + '/state/notify'
            else:
                platform = 'binary_sensor'
                sensor_info['state_topic'] = topic_base + '/stale/notify'

            self._discovery_topics[dev_name] = f'homeassistant/{platform}/{uid}/config'

    def request_position(self, position: float) -> None:
        # Queue a normalized position command for the actuator task.
        if not 0 <= position <= 1:
            raise ValueError('Position must be between zero and one')

        self._pending_position = position
        self._pending_stop = False
        self._state_dirty = True

    def request_stop(self) -> None:
        # Queue an emergency stop for the actuator task.
        self._pending_position = None
        self._pending_stop = True
        self._state_dirty = True

    def set_position_limits(self, pos_min: float, pos_max: float) -> None:
        # Apply calibration limits and publish the measured position.
        self._servo.set_position_limits(pos_min=pos_min, pos_max=pos_max)
        self._state_dirty = True

    def calibrate_to_raw(self, raw_fraction: float) -> None:
        # Drive the motor to a raw potentiometer target for endpoint calibration.
        self._servo.move_to_raw(round(raw_fraction * UINT16_MAX))
        self._state_dirty = True

    def set_motor_power(self, power: float) -> None:
        # Apply a motor power limit.
        self._servo.set_motor_power(power=power)

    def set_watchdog(self, watchdog) -> None:
        # Attach a hardware watchdog fed by the actuator control loop.
        self._watchdog = watchdog

    @property
    def position(self) -> float:
        # Return the latest measured position.
        return self._servo.position

    @property
    def connected(self) -> bool:
        # Return whether MQTT is currently connected.
        return self._mqtt.connected

    @property
    def last_control_tick(self) -> float:
        # Return the latest control-loop timestamp.
        return self._last_control_tick

    async def _publish_discovery(self) -> None:
        # Publish retained Home Assistant discovery data and restore subscriptions.
        for dev_name, sensor_info in self._devices.items():
            await self._mqtt.publish(
                self._discovery_topics[dev_name], json.dumps(sensor_info), retain=True
            )

            for set_topic in ('command_topic', 'set_position_topic'):
                if set_topic in sensor_info:
                    await self._mqtt.subscribe(sensor_info[set_topic])

    def _mark_disconnected(self, error: Exception | None = None) -> None:
        # Close a failed MQTT connection.
        if error:
            print(f'MQTT connection lost: {error}')

        self._mqtt.close()

    async def _connect(self) -> bool:
        # Connect to the broker and publish availability.
        try:
            self._mqtt.set_last_will(self._availability_topic, 'offline', retain=True)
            await self._mqtt.connect()
            await self._publish_discovery()
            await self._mqtt.publish(self._availability_topic, 'online', retain=True)
            self._last_ping = time.time()
            await self._publish_state(force=True)
            print('Connected to MQTT broker')
            return True
        except Exception as ex:
            self._mark_disconnected(ex)
            return False

    async def _publish_state(self, force: bool = False) -> None:
        # Publish measured state without blocking the control loop.
        now = time.time()
        if not force and now - self._last_update < self._CONTROL_INTERVAL_S:
            return
        if not self._mqtt.connected:
            return

        state = ('OFF', 'ON')[self._servo.stalled]
        stale_topic = self._devices[self._STALE_DETECTOR_DEV]['state_topic']
        position_topic = self._devices[self._WINDOW_DEV]['position_topic']
        attributes_topic = self._devices[self._WINDOW_DEV]['json_attributes_topic']
        attributes = {
            'position': round(self._servo.position * 100, 1),
            'moving': self._servo.running,
            'fault': self._servo.fault
        }

        state_topic = self._devices[self._WINDOW_DEV]['state_topic']
        if self._servo.fault:
            cover_state = 'stopped'
        elif self._servo.running:
            cover_state = 'opening' if self._servo.opening else 'closing'
        elif self._servo.position <= self._servo.POSITION_PRECISION:
            cover_state = 'closed'
        elif self._servo.position >= 1 - self._servo.POSITION_PRECISION:
            cover_state = 'open'
        else:
            cover_state = 'stopped'

        try:
            await self._mqtt.publish(stale_topic, state, retain=True)
            await self._mqtt.publish(state_topic, cover_state, retain=True)
            await self._mqtt.publish(position_topic, str(attributes['position']), retain=True)
            await self._mqtt.publish(attributes_topic, json.dumps(attributes), retain=True)
        except Exception as ex:
            self._mark_disconnected(ex)
            return

        self._last_update = now
        self._published_fault = self._servo.fault
        self._last_published_position = attributes['position']
        self._state_dirty = False

    def _apply_pending_command(self) -> None:
        # Apply at most one latest network command per control iteration.
        if self._pending_stop:
            self._pending_stop = False
            self._servo.stop()
            return

        if self._pending_position is not None:
            position = self._pending_position
            self._pending_position = None
            self._servo.position = position

    def safe_shutdown(self) -> None:
        # Stop the motor without touching the network.
        self._pending_position = None
        self._pending_stop = False
        self._servo.stop(fault='system_shutdown')

    async def run(self) -> None:
        # Run the independent actuator control loop.
        while True:
            started = time.time()
            self._apply_pending_command()
            self._servo.tick(now=started)
            self._last_control_tick = started
            current_position = round(self._servo.measured_position * 100, 1)
            if (
                self._servo.running
                or self._servo.fault != self._published_fault
                or current_position != self._last_published_position
            ):
                self._state_dirty = True
            if self._watchdog is not None:
                self._watchdog.feed()
            await asyncio.sleep(self._CONTROL_INTERVAL_S)

    async def network_run(self) -> None:
        # Run MQTT transport and publishing independently from motor control.
        while True:
            if await self._connect():
                await self._serve_connected()
            await asyncio.sleep(self._MQTT_RECONNECT_INTERVAL_S)

    async def _serve_connected(self) -> None:
        # Serve MQTT while connected and publish measured state on a useful cadence.
        while self._mqtt.connected:
            now = time.time()
            if now - self._last_ping >= self._MQTT_PING_INTERVAL_S:
                try:
                    await self._mqtt.ping()
                    self._last_ping = now
                except Exception as ex:
                    self._mark_disconnected(ex)
                    break

            if self._servo.running:
                if now - self._last_update >= self._MOVING_PUBLISH_INTERVAL_S:
                    await self._publish_state(force=True)
            elif self._state_dirty or now - self._last_update >= self._STATE_UPDATE_INTERVAL_S:
                await self._publish_state(force=True)

            await asyncio.sleep(0.1)

    def _inbox(self, topic: bytes, msg: bytes) -> None:
        # Queue and validate MQTT actuator commands without blocking the callback.
        top = topic.decode()

        if top == self._devices[self._WINDOW_DEV]['command_topic']:
            if msg == b'OPEN':
                self.request_position(1)
            elif msg == b'CLOSE':
                self.request_position(0)
            elif msg == b'STOP':
                self.request_stop()

        if top == self._devices[self._WINDOW_DEV]['set_position_topic']:
            try:
                new_position = float(msg) / 100
                self.request_position(new_position)
            except (TypeError, ValueError):
                print('Ignoring invalid MQTT position command')

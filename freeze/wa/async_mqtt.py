import asyncio
import struct

try:
    from typing import Any
except ImportError:
    pass


class MQTTException(Exception):
    pass

def _encode_length(packet: bytearray, value: int) -> None:
    # Append an MQTT variable-length integer to a packet.
    while True:
        digit = value % 128
        value //= 128
        if value:
            packet.append(digit | 0x80)
        else:
            packet.append(digit)
            return


def _write_string(packet: bytearray, value: str) -> None:
    # Append an MQTT UTF-8 string to a packet.
    data = value.encode()
    packet.extend(struct.pack('!H', len(data)))
    packet.extend(data)


class AsyncMQTTClient:
    # Minimal asynchronous MQTT 3.1.1 client for MicroPython asyncio.

    def __init__(self, client_id: str, server: str, port: int = 1883, user: str = '',
                 password: str = '', keepalive: int = 0):
        # :param client_id: MQTT client identifier.
        # :param server: Broker hostname or IP address.
        # :param port: Broker TCP port.
        # :param user: MQTT username.
        # :param password: MQTT password.
        # :param keepalive: MQTT keepalive interval in seconds.
        self.client_id = client_id
        self.server = server
        self.port = port
        self.user = user
        self.password = password
        self.keepalive = keepalive
        self._reader: Any = None
        self._writer: Any = None
        self._reader_task: Any = None
        self._callback = None
        self._pid = 0
        self._connected = False
        self._will: tuple[str, str, bool, int] | None = None

    @property
    def connected(self) -> bool:
        # Return whether the client is currently connected.
        return self._connected

    def set_callback(self, callback) -> None:
        # Set the incoming publish callback receiving (topic, message) bytes.
        self._callback = callback

    def set_last_will(self, topic: str, message: str, retain: bool = False, qos: int = 0) -> None:
        # Set the last will message published by the broker on an unclean disconnect.
        self._will = (topic, message, retain, qos)

    async def connect(self, clean_session: bool = True, timeout: float = 5.0) -> None:
        # Connect to the broker and complete the MQTT handshake.
        await self._reset()
        self._reader, self._writer = await asyncio.wait_for(  # type: ignore[arg-type]
            asyncio.open_connection(self.server, self.port), timeout
        )

        flags = 0
        if clean_session:
            flags |= 0x02
        if self.user:
            flags |= 0xC0
        if self._will:
            flags |= 0x04 | ((self._will[3] & 3) << 3)
            if self._will[2]:
                flags |= 0x20

        variable = bytearray(b'\x00\x04MQTT\x04\x02\x00\x00')
        variable[7] = flags
        if self.keepalive:
            variable[8] = self.keepalive >> 8
            variable[9] = self.keepalive & 0xFF

        _write_string(variable, self.client_id)
        if self._will:
            _write_string(variable, self._will[0])
            _write_string(variable, self._will[1])
        if self.user:
            _write_string(variable, self.user)
            _write_string(variable, self.password)

        packet = bytearray(b'\x10')
        _encode_length(packet, len(variable))
        packet.extend(variable)

        await self._write(packet)
        response = await self._reader.readexactly(4)
        if response[0] != 0x20 or response[1] != 0x02:
            raise MQTTException('Invalid CONNACK')
        if response[3] != 0:
            raise MQTTException(response[3])

        self._connected = True
        self._reader_task = asyncio.create_task(self._reader_loop(self._reader, self._writer))

    async def publish(self, topic: str, message: str, retain: bool = False, qos: int = 0) -> None:
        # Publish one message. Only QoS 0 is supported by the application.
        variable = bytearray()
        _write_string(variable, topic)
        if qos > 0:
            self._pid += 1
            if self._pid > 65535:
                self._pid = 1
            variable.extend(struct.pack('!H', self._pid))
        variable.extend(message.encode())

        packet = bytearray(b'\x30')
        packet[0] |= (qos & 3) << 1
        if retain:
            packet[0] |= 1
        _encode_length(packet, len(variable))
        packet.extend(variable)

        await self._write(packet)

    async def subscribe(self, topic: str, qos: int = 0) -> None:
        # Subscribe to one topic.
        self._pid += 1
        if self._pid > 65535:
            self._pid = 1
        variable = bytearray(struct.pack('!H', self._pid))
        _write_string(variable, topic)
        variable.append(qos)

        packet = bytearray(b'\x82')
        _encode_length(packet, len(variable))
        packet.extend(variable)

        await self._write(packet)

    async def ping(self) -> None:
        # Send an MQTT keepalive ping.
        await self._write(b'\xc0\x00')

    def close(self) -> None:
        # Close the connection without blocking the scheduler.
        self._connected = False
        task = self._reader_task
        self._reader_task = None
        if task is not None:
            try:
                task.cancel()
            except Exception:
                pass

        writer = self._writer
        self._writer = None
        self._reader = None
        if writer is not None:
            try:
                writer.s.close()
            except Exception:
                pass

    async def _write(self, data) -> None:
        if self._writer is None:
            raise MQTTException('Not connected')

        self._writer.write(data)
        await self._writer.drain()

    async def _reset(self) -> None:
        self.close()
        self._reader = None
        self._writer = None

    async def _reader_loop(self, reader, writer) -> None:
        # Read and dispatch incoming MQTT messages until the connection fails.
        try:
            while True:
                header = await reader.read(1)
                if not header:
                    break
                op = header[0]
                if op == 0xD0:
                    continue
                if op & 0xF0 == 0x30:
                    await self._handle_publish(reader, op)
        except Exception:
            pass
        finally:
            try:
                writer.s.close()
            except Exception:
                pass
            if self._reader is reader:
                self._connected = False

    async def _handle_publish(self, reader, op: int) -> None:
        qos = (op >> 1) & 3
        multiplier = 1
        remaining = 0
        while True:
            digit = (await reader.readexactly(1))[0]
            remaining += (digit & 0x7F) * multiplier
            if not digit & 0x80:
                break
            multiplier *= 128

        topic_length = struct.unpack('!H', await reader.readexactly(2))[0]
        topic = await reader.readexactly(topic_length)
        remaining -= topic_length + 2

        if qos > 0:
            await reader.readexactly(2)
            remaining -= 2

        message = await reader.readexactly(remaining) if remaining else b''

        if self._callback is not None:
            self._callback(topic, message)

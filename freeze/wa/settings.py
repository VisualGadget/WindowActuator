import json
import os

from wa.utils import wifi_mac


class Parameter:
    # Persistent setting descriptor.

    def __init__(self, name: str, value_type, default=None):
        self._public_name = name
        self._type = value_type
        self._default = default

    def __set_name__(self, owner, name):
        # MicroPython may not call this hook for frozen descriptors.
        self._public_name = name

    def __set__(self, obj, value) -> None:
        try:
            converted = self._type(value)
            self._validate(converted)
        except (TypeError, ValueError):
            raise ValueError(f'Invalid value for parameter {self._public_name}') from None

        obj._stor[self._public_name] = converted

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self

        value = obj._stor.get(self._public_name)
        if value is None:
            return self._default

        try:
            converted = self._type(value)
            self._validate(converted)
        except (TypeError, ValueError):
            del obj._stor[self._public_name]
            return self._default

        return converted

    def _validate(self, value) -> None:
        # Validate one converted setting value.
        pass


class TextParameter(Parameter):
    # Bounded text setting.

    def __init__(self, name: str, default=None, max_length: int = 64, required: bool = False):
        super().__init__(name=name, value_type=str, default=default)
        self._max_length = max_length
        self._required = required

    def _validate(self, value: str) -> None:
        if len(value) > self._max_length or (self._required and not value):
            raise ValueError('Invalid text length')
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError('Control characters are not allowed')


class PercentParameter(Parameter):
    # Integer percentage setting.

    def __init__(self, name: str, default=None):
        super().__init__(name=name, value_type=int, default=default)

    def _validate(self, value: int) -> None:
        if not 0 <= value <= 100:
            raise ValueError('Percentage must be between zero and one hundred')


class PortParameter(Parameter):
    # TCP port setting.

    def __init__(self, name: str, default: int = 1883):
        super().__init__(name=name, value_type=int, default=default)

    def _validate(self, value: int) -> None:
        if not 1 <= value <= 65535:
            raise ValueError('Port must be between one and 65535')


class SettingsStorage:
    # Recoverable persistent settings storage.

    device_name = TextParameter('device_name', f'wa_{wifi_mac()[-4:]}', 32, True)
    wifi_ssid = TextParameter('wifi_ssid', max_length=32, required=True)
    wifi_password = TextParameter('wifi_password', max_length=64)
    mqtt_server = TextParameter('mqtt_server', max_length=64, required=True)
    mqtt_port = PortParameter('mqtt_port')
    mqtt_user = TextParameter('mqtt_user', max_length=32)
    mqtt_password = TextParameter('mqtt_password', max_length=64)
    motor_power = PercentParameter('motor_power', 100)
    window_opened_pos = PercentParameter('window_opened_pos', 81)
    window_closed_pos = PercentParameter('window_closed_pos', 24)

    def __init__(self, path: str):
        self._path = path
        self._backup_path = path + '.bak'
        self._temporary_path = path + '.tmp'
        self._stor = self._load()
        self._validate_cross_fields()

    def _load_file(self, path: str):
        # Load one JSON settings file.
        with open(path, encoding='utf8') as settings_file:
            values = json.load(settings_file)
        if not isinstance(values, dict):
            raise ValueError('Settings must be a JSON object')

        return values

    def _load(self):
        # Load the primary file and fall back to the last atomic backup.
        try:
            return self._load_file(self._path)
        except (OSError, ValueError, TypeError):
            try:
                print('Using settings backup')
                return self._load_file(self._backup_path)
            except (OSError, ValueError, TypeError):
                print('Using default settings')
                return {}

    def _validate_cross_fields(self) -> None:
        # Remove invalid combinations while keeping the device bootable.
        if self.window_closed_pos >= self.window_opened_pos:
            self._stor.pop('window_closed_pos', None)
            self._stor.pop('window_opened_pos', None)

    def save(self) -> None:
        # Atomically write settings and preserve the previous version.
        self._validate_cross_fields()
        with open(self._temporary_path, 'w', encoding='utf8') as settings_file:
            json.dump(self._stor, settings_file)
            try:
                settings_file.flush()
                os.fsync(settings_file.fileno())
            except (AttributeError, OSError):
                pass

        try:
            os.remove(self._backup_path)
        except OSError:
            pass

        try:
            os.rename(self._path, self._backup_path)
        except OSError:
            pass

        os.rename(self._temporary_path, self._path)


config = SettingsStorage('settings.json')

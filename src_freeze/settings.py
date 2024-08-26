import json


class Parameter:
    # """
    # Setting parameter
    # """

    def __init__(self, name: str, type, default = None):
        # """
        # :param name: parameter name
        # :param type: value type
        # :param default: default value
        # """
        self._public_name = name  # TODO: remove when __set_name__ will be supported
        self._type = type
        self._default = default

    # not called by uP: https://github.com/micropython/micropython/pull/15503
    def __set_name__(self, owner, name):
        self._public_name = name

    def __set__(self, obj, value):
        try:
            val = self._type(value)
        except ValueError:
            raise ValueError(
                f'Parameter "{self._public_name}" has {self._type.__name__} type, '
                f'but set with "{value}" value of type {type(value).__name__}'
            )
        self._validate(val)
        obj._stor[self._public_name] = val

    def __get__(self, obj, objtype=None):
        val = obj._stor.get(self._public_name)
        if val is None:
            return self._default

        try:
            val = self._type(val)
        except ValueError:
            val = self._default
            del obj._stor[self._public_name]

        return val

    def _validate(self, value):
        # """
        # Value validator

        # :raise: exception if value is not correct
        # """
        pass


class PercentParameter(Parameter):
    # """
    # Integer percent parameter
    # """

    def __init__(self, name: str, default = None):
        # """
        # :param name: parameter name
        # :param default: default value
        # """
        super().__init__(name=name, type=int, default=default)

    def _validate(self, value: int):
        if not (0 <= value <= 100):
            raise ValueError(f'Invalid percent value for parameter "{self._public_name}": {value}')


class PasswordParameter(Parameter):
    # """
    # Password string parameter
    # """

    def __init__(self, name: str):
        # """
        # :param name: parameter name
        # :param default: default value
        # """
        super().__init__(name=name, type=str)


class SettingsStorage:

    wifi_ap = Parameter('wifi_ap', str)
    wifi_password = PasswordParameter('wifi_password')

    mqtt_device_name = Parameter('mqtt_device_name', str, 'window')
    mqtt_server = Parameter('mqtt_server', str)
    mqtt_port = Parameter('mqtt_port', int, 1883)
    mqtt_user = Parameter('mqtt_user', str)
    mqtt_password = PasswordParameter('mqtt_password')

    motor_power = PercentParameter('motor_power', 100)
    window_opened_pos = Parameter('window_opened_pos', int, 52800)
    window_closed_pos = Parameter('window_closed_pos', int, 15500)

    def __init__(self, path: str):
        # """
        # :param path: JSON configuration file path
        # """
        self._path = path
        try:
            with open(self._path, encoding='utf8') as f:
                self._stor = json.load(f)
        except FileNotFoundError:
            self._stor = {}

    def save(self):
        # """
        # Write settings to disk
        # """
        with open(self._path, 'w', encoding='utf8') as f:
            json.dump(self._stor, f)


config = SettingsStorage('settings.json')  # instance for global use

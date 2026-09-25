import importlib.util
import sys
import types
from pathlib import Path

utils_module = types.ModuleType('wa.utils')
utils_module.wifi_mac = lambda: '485519c7d945'
sys.modules['wa.utils'] = utils_module

module_path = Path(__file__).parents[1] / 'freeze' / 'wa' / 'settings.py'
spec = importlib.util.spec_from_file_location('settings', module_path)
assert spec is not None
settings = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(settings)


def build_storage(tmp_path):
    return settings.SettingsStorage(str(tmp_path / 'settings.json'))


def test_settings_round_trip(tmp_path):
    storage = build_storage(tmp_path)
    storage.wifi_ssid = 'test_ssid'
    storage.mqtt_server = '192.0.2.1'
    storage.motor_power = 80
    storage.save()

    reloaded = settings.SettingsStorage(str(tmp_path / 'settings.json'))
    assert reloaded.wifi_ssid == 'test_ssid'
    assert reloaded.mqtt_server == '192.0.2.1'
    assert reloaded.motor_power == 80


def test_defaults_applied_for_missing_file(tmp_path):
    storage = build_storage(tmp_path)
    assert storage.motor_power == 100
    assert storage.window_opened_pos == 81
    assert storage.window_closed_pos == 24


def test_cross_field_validation_removes_invalid_limits(tmp_path):
    path = tmp_path / 'settings.json'
    storage = settings.SettingsStorage(str(path))
    storage.window_closed_pos = 90
    storage.window_opened_pos = 50
    storage.save()

    reloaded = settings.SettingsStorage(str(path))
    assert reloaded.window_closed_pos == 24
    assert reloaded.window_opened_pos == 81


def test_backup_fallback(tmp_path):
    path = tmp_path / 'settings.json'
    storage = settings.SettingsStorage(str(path))
    storage.wifi_ssid = 'first'
    storage.save()
    storage.wifi_ssid = 'second'
    storage.save()

    path.write_text('{corrupt', encoding='utf8')
    reloaded = settings.SettingsStorage(str(path))
    assert reloaded.wifi_ssid == 'first'


def test_parameter_validation_rejects_invalid(tmp_path):
    storage = build_storage(tmp_path)

    try:
        storage.motor_power = 150
        raise AssertionError('expected ValueError')
    except ValueError:
        pass

    try:
        storage.mqtt_port = 0
        raise AssertionError('expected ValueError')
    except ValueError:
        pass

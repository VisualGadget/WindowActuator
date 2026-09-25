import importlib.util
from pathlib import Path

module_path = Path(__file__).parents[1] / 'freeze' / 'wa' / 'validation.py'
spec = importlib.util.spec_from_file_location('validation', module_path)
assert spec is not None
validation = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(validation)


def test_parse_percentage_accepts_bounds():
    assert validation.parse_percentage('0', 'position') == 0.0
    assert validation.parse_percentage('100', 'position') == 100.0
    assert validation.parse_percentage('50.5', 'position') == 50.5


def test_parse_percentage_rejects_out_of_range():
    try:
        validation.parse_percentage('-1', 'position')
        raise AssertionError('expected ValueError')
    except ValueError as ex:
        assert 'between 0 and 100' in str(ex)

    try:
        validation.parse_percentage('101', 'position')
        raise AssertionError('expected ValueError')
    except ValueError:
        pass


def test_parse_percentage_rejects_non_number():
    try:
        validation.parse_percentage('abc', 'position')
        raise AssertionError('expected ValueError')
    except ValueError as ex:
        assert 'must be a number' in str(ex)


def test_parse_port():
    assert validation.parse_port('1883', 'MQTT port') == 1883

    for value in ('0', '70000', 'abc'):
        try:
            validation.parse_port(value, 'MQTT port')
            raise AssertionError('expected ValueError')
        except ValueError:
            pass


def test_validate_text():
    assert validation.validate_text('hello', 'name', 32, False) == 'hello'
    assert validation.validate_text('', 'name', 32) == ''

    try:
        validation.validate_text('', 'name', 32, False)
        raise AssertionError('expected ValueError')
    except ValueError:
        pass

    try:
        validation.validate_text('a' * 33, 'name', 32)
        raise AssertionError('expected ValueError')
    except ValueError:
        pass

    try:
        validation.validate_text('bad\nname', 'name', 32)
        raise AssertionError('expected ValueError')
    except ValueError:
        pass

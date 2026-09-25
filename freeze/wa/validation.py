import math


def parse_percentage(value, name: str = 'value') -> float:
    # Parse a finite percentage in the range 0..100.
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a number') from None

    if not math.isfinite(number) or not 0 <= number <= 100:
        raise ValueError(f'{name} must be between 0 and 100') from None

    return number


def parse_port(value, name: str = 'port') -> int:
    # Parse a TCP port in the range 1..65535.
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be an integer') from None

    if not 1 <= port <= 65535:
        raise ValueError(f'{name} must be between 1 and 65535') from None

    return port


def validate_text(value, name: str = 'value', max_length: int = 64, allow_empty: bool = True) -> str:
    # Validate a bounded configuration string.
    if not isinstance(value, str) or len(value) > max_length or (not allow_empty and not value):
        raise ValueError(f'Invalid {name}') from None

    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f'Invalid {name}') from None

    return value

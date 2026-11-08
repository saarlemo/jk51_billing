"""Day and night transfer tariff boundaries."""

import re

DEFAULT_DAY_START = "07:00"
DEFAULT_DAY_END = "22:00"


def day_window(config):
    """Return hour-aligned day tariff boundaries as HH:00 strings."""
    values = []
    for key, default in (("day_transfer_start", DEFAULT_DAY_START),
                         ("day_transfer_end", DEFAULT_DAY_END)):
        value = config.get(key, default)
        if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):00(?::00)?", value):
            raise ValueError("Day transfer times must be whole hours from 00:00 to 23:00")
        values.append(value[:5])
    if values[0] == values[1]:
        raise ValueError("Day transfer start and end must differ")
    return tuple(values)


def is_day_hour(local_datetime, start, end):
    """Classify the local start of an hourly interval."""
    hour = local_datetime.strftime("%H:%M")
    return start <= hour < end if start < end else hour >= start or hour < end

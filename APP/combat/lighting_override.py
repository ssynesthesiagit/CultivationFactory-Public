"""Validation for a match-local ambient-light override."""

TIME_LEVELS = {"day": 2, "dawn": 1, "dusk": 1, "night": 0, "underground": 0}
LEVELS = {"bright": 2, "dim": 1, "dark": 0}


def normalize_ambient_override(value):
    if not isinstance(value, dict):
        raise ValueError("Ambient light settings must be an object.")
    time = str(value.get("time_of_day") or "day").strip().lower()
    if time not in TIME_LEVELS:
        raise ValueError("Choose day, dawn, dusk, night or underground.")
    result = {"time_of_day": time}
    for key in ("level", "indoor_level"):
        level = value.get(key)
        if level is None:
            if key == "level":
                result[key] = TIME_LEVELS[time]
            continue
        if isinstance(level, str):
            level = LEVELS.get(level.strip().lower())
        if type(level) is not int or level not in (0, 1, 2):
            raise ValueError("Light level must be bright, dim or dark.")
        result[key] = level
    return result

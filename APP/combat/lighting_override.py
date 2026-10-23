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


# The match-local ambient override is a mutable side file, not a rewrite of the sealed arena: Arena_Battlefield.json
# is an immutable saved input whose sha256 every load checks (combat/gate3_storage.py _validate_content).
AMBIENT_OVERRIDE_FILE = "Ambient_Override.json"


def write_ambient_override(match_dir, normalized):
    """Persist a normalized override next to the fight (atomic, never the sealed arena)."""
    import json
    from pathlib import Path

    from .gate3_storage import atomic_write_bytes

    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    atomic_write_bytes(Path(match_dir) / AMBIENT_OVERRIDE_FILE, payload)


def apply_ambient_override(engine, match_dir):
    """Lay the saved override over the engine's arena document, in memory, on every load. A missing file leaves the
    arena's own ambient section untouched; an unreadable one fails the load (saved data we cannot interpret)."""
    from pathlib import Path

    from .saved_fight_format import UnsupportedSavedFight, read_saved_json

    path = Path(match_dir) / AMBIENT_OVERRIDE_FILE
    if not (path.exists() or path.is_symlink()):
        return
    base = getattr(engine, "battlefield_document", None)
    if not isinstance(base, dict):
        return
    try:
        normalized = normalize_ambient_override(read_saved_json(path))
    except ValueError as exc:
        raise UnsupportedSavedFight(f"{AMBIENT_OVERRIDE_FILE}: {exc}") from exc
    engine.battlefield_document = {**base, "tabletop": {**(base.get("tabletop") or {}), "ambient": normalized}}

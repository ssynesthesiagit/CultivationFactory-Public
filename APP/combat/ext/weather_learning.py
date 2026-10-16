"""Weather's source-backed starting Sign and additional native learning.

Reuses the public acquisition contracts from 74cc00e4 weather_knowledge.py.
Only Cloud Shroud consumes the learned list here; no sibling ability is changed.
The starting package is printed in the Sphere Compendium (SHA256
67f67275889467d43605debaa0c05dc5ddde9ba079222819aabea27c66167775).
"""
from . import hook
from . import weather_signs

SPHERE = weather_signs.SPHERE
SHROUD = "WEATHER_BASE_CLOUD_SHROUD"


@hook("acquisition_choices")
def starting_choice(source_id, sheet):
    if source_id == SPHERE:
        return [{"key": "weather_starting_sign", "count": 1, "options": weather_signs.names(),
                 "labels": {s: weather_signs.sign(s)["name"] for s in weather_signs.names()},
                 "label": "Choose the Weather Sign talent you learn with Weather"}]


@hook("acquisition_source_options")
def additional_signs(sheet):
    from ..table_advance import known
    if SPHERE not in known(sheet)["spheres"]:
        return None
    selections = (sheet.get("acquisition_choices") or {}).get(SPHERE, {})
    learned = set(selections.get("weather_starting_sign", []) + selections.get("weather_additional_signs", []))
    return [{"id": "weather.sign." + sign, "name": weather_signs.sign(sign)["name"], "sphere": "Weather",
             "source_id": SPHERE, "key": "weather_additional_signs", "value": sign,
             "source_sha256": "67f67275889467d43605debaa0c05dc5ddde9ba079222819aabea27c66167775",
             "legal": sign not in learned, "reasons": [] if sign not in learned else ["Already learned."]}
            for sign in weather_signs.names()]


@hook("compile_action")
def learned_signs(action, info):
    typed = action.parameters.get("typed") or {}
    if typed.get("source") != SHROUD or SHROUD not in info["owned_ids"]:
        return None
    selections = (info["owner_sheet"].get("acquisition_choices") or {}).get(SPHERE, {})
    starting = selections.get("weather_starting_sign", [])
    additional = selections.get("weather_additional_signs", [])
    if starting:
        from ..acquisition_choices import validate
        validate(SPHERE, info["owner_sheet"], {"weather_starting_sign": starting})
    if (not isinstance(additional, list) or len(additional) != len(set(additional))
            or any(s not in weather_signs.names() for s in additional)):
        raise ValueError("Additional Weather Signs must be distinct printed Sign talents.")
    selected = [s for s in weather_signs.names() if s in starting + additional]
    return action.model_copy(update={"parameters": {**action.parameters,
        "typed": {**typed, "known_weather_signs": selected}}})


@hook("candidate_allowed")
def sign_required(engine, actor, candidate, action):
    typed = action.parameters.get("typed") or {} if action is not None else {}
    if typed.get("source") == SHROUD:
        return bool(typed.get("known_weather_signs"))
    return None

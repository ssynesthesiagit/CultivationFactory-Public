"""Explicit source-object profiles shared by evidence and investigation consumers.

An imported map may seal namespaced source facts on an object. These are
backend authority, not a perception result; presentation must keep its ordinary
object whitelist. Profiles contain only dictionaries, lists, integers and
strings. Missing profiles preserve ordinary object creation and behavior.
"""
import copy


def _plain(value):
    if type(value) in (int, str):
        return
    if isinstance(value, list):
        for item in value:
            _plain(item)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _plain(item)
        return
    raise ValueError('Source-object profiles contain only integers, strings, lists and dictionaries')


def capture(row, round_number):
    """Validated optional map authority, with a persisted age-clock anchor."""
    if 'source_profiles' not in row:
        return {}
    profiles = row['source_profiles']
    if not isinstance(profiles, dict) or not all(isinstance(v, dict) for v in profiles.values()):
        raise ValueError('source_profiles must map names to source records')
    _plain(profiles)
    return {'source_profiles': copy.deepcopy(profiles), 'source_profiles_round': int(round_number)}


def profile(obj, name):
    """Read only an explicit source record; infer no facts from an object name."""
    return ((obj.component or {}).get('source_profiles') or {}).get(name) or {}


def age_seconds(engine, obj, data):
    """Source age plus six seconds per elapsed combat round, including reload."""
    age = data.get('age_seconds')
    if type(age) is not int or age < 0:
        return None
    anchor = int((obj.component or {}).get('source_profiles_round', engine.state.round_number))
    return age + 6 * max(0, int(engine.state.round_number) - anchor)


def public_rows(rows):
    """Preserve every authored object/geometry field except backend source facts.

    Used by the table map projection. Native execution and private map exports
    retain profiles; they never travel in an ordinary seat's public map payload.
    """
    return [{key:value for key,value in row.items() if key!='source_profiles'}
            if isinstance(row,dict) and 'source_profiles' in row else row for row in rows]

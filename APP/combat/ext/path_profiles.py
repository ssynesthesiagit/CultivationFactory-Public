"""Shared owning-Path number projection for the ext plug-ins.

``path_numbers(info, path_id)`` reads the character sheet that ``compile_bundle`` and
``compile_actions`` receive and returns the compile numbers with that Path's effective
CL, Proficiency Bonus and key-ability modifiers. It is shared by ``path_riders`` and
``unbroken_bolt`` so a feature always uses its owning Path instead of borrowing another
Path's chassis, and it is the only place that reads ``path_and_subpath.paths``.

No matching row, no usable ``effective_cl`` and no usable key ability all leave the
sheet's own numbers untouched: a legacy or malformed sheet still compiles, and the
first usable row wins over duplicates rather than aborting character compilation.
"""


def path_numbers(info, path_id):
    """Project one explicit owning-Path profile; preserve the sheet's numbers otherwise."""
    numbers = dict(info['numbers'])
    sheet = info.get('owner_sheet') or {}
    for path in (sheet.get('path_and_subpath') or {}).get('paths') or []:
        if not isinstance(path, dict) or path.get('path_id') != path_id:
            continue
        level = path.get('effective_cl')
        if type(level) is not int or not 0 <= level <= 20:
            continue
        numbers['cl'] = level
        listed = path.get('proficiency_bonus')
        numbers['pb'] = listed if type(listed) is int and listed > 0 else 2 + max(0, level - 1) // 4
        ability = _key_ability(sheet, path.get('key_ability'))
        if ability is not None:
            numbers['key_mod'] = ability
            numbers['attack_bonus'] = numbers['pb'] + numbers['key_mod']
            numbers['save_dc'] = 8 + numbers['attack_bonus']
        return numbers
    return numbers


def _key_ability(sheet, key_ability):
    """The path's key ability modifier, or None when the sheet does not list it."""
    key = str(key_ability or '').upper()[:3]
    abilities = (sheet.get('ability_scores_and_statistics') or {}).get('abilities') or []
    ability = next((a for a in abilities if str(a.get('ability') or '').upper()[:3] == key), None)
    if ability is None:
        return None
    if type(ability.get('modifier')) is int:
        return ability['modifier']
    if type(ability.get('score')) is int:
        return (ability['score'] - 10) // 2
    return None

"""Final AC for native/portable attacks and public defense display.

An optional source-owned floor is applied after cover and all additive bonuses
and penalties. No provider preserves the historical integer exactly. Queries
never alter a modifier, cancel a source, or reveal any hidden information.
"""
from . import ext


def armor_class_value(engine, target, *, cover=0):
    value = int(target.armor_class) + int(cover) + int(engine._ac_modifier(target))
    floors = ext.run_strict('armor_class_floor', engine, target)
    if any(type(floor) is not int or floor < 0 for floor in floors):
        raise ValueError('Armor Class floors must be nonnegative integers')
    return max([value, *floors])

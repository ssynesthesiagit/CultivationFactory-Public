"""Regression tests for the Sol seam fix round 2 blocking findings 1 and 3.

Finding 1: a real owned sword must be classified as a sword (the native chassis lookup must pass the definition
as the weapon; before the fix the lookup could never match a real sword).
Finding 3: the Guard Mode player-facing text must state the +2 AC that the mechanic applies.
"""
from combat.ext import ten_thousand_swords as tts


def test_real_duan_jian_chassis_is_a_native_sword():
    record = {'chassis': {'item_id': 'tianxia.mortal.weapon.duan_jian'}}
    assert tts.native_sword_record(record) is True


def test_non_sword_chassis_is_not_relabelled_as_a_sword():
    record = {'chassis': {'item_id': 'tianxia.mortal.weapon.duan_jian_does_not_exist'}}
    assert tts.native_sword_record(record) is False


def test_declared_weapon_classification_counts_as_sword():
    record = {'chassis': {'item_id': ''}, 'runtime_profile': {'facts': {'weapon_classification': 'sword'}}}
    assert tts.native_sword_record(record) is True


def test_guard_mode_text_states_the_mechanical_ac_bonus():
    assert tts.GUARD_AC_BONUS == 2
    assert f'+{tts.GUARD_AC_BONUS} AC against ranged attacks' in tts.GUARD_TEXT
    assert 'within 5 feet' in tts.GUARD_TEXT
    assert 'AC' in tts.GUARD_TEXT

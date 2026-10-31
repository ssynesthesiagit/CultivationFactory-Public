"""Mud-Lotus Guard: spend Lotus Dew to cut scoped harm to the owner or an ally."""
from tests.test_a2_foundations3 import add_action, setup, use, pool
from tests.worker2_support import OWNER, ALLY, FOE, turn, reload

GUARD = 'reaction:typed.foundation.mud_lotus_dantian_v0_2A.mud_lotus_guard'


def _hit_ally(tmp_path, damage_type, *, accept=True, initial=1):
    def delivery(bundles):
        add_action(bundles[2], 'Scoped hit', [{'type': 'damage', 'flat': 9, 'damage_types': [damage_type], 'applies_to': 'target'}],
                   target_kind='HOSTILE_ENTITY', economy='NONE')
    combat, table, mid = setup(tmp_path, 'lotus', initial=initial, extra=delivery)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[ALLY]
    start = before.current_hp + before.temporary_hp
    use(combat, table, mid, 'Scoped hit', ALLY, picks={GUARD: 'first' if accept else None})
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    return start - (ally.current_hp + ally.temporary_hp), engine.state.actors[OWNER].resources[pool('lotus')]


def test_guard_cuts_poison_harm_by_proficiency_plus_key_modifier_and_spends_a_dew(tmp_path):
    lost, dew = _hit_ally(tmp_path, 'poison')
    assert (lost, dew) == (3, 0)


def test_declining_the_guard_keeps_the_dew_and_takes_full_harm(tmp_path):
    lost, dew = _hit_ally(tmp_path, 'poison', accept=False)
    assert (lost, dew) == (9, 1)


def test_harm_outside_the_scope_is_not_guarded(tmp_path):
    lost, dew = _hit_ally(tmp_path, 'force')
    assert (lost, dew) == (9, 1)


def test_without_dew_there_is_no_guard(tmp_path):
    lost, dew = _hit_ally(tmp_path, 'poison', initial=0)
    assert (lost, dew) == (9, 0)

"""Demon Mark adds PB to damage once per turn, including activation damage.

Synthetic portable characters only; private playtest evidence stays outside Git.
The test-only free Void Needle permits multiple native table commits in one turn
without changing the attack, its damage, or the mark's use clock.
"""
import pytest

from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import OWNER, FOE, SECOND, fixture, candidate
from tests.test_lock_choices import install

MARK = 'TAL_DAEMONIC_CULTIVATION_DEMON_MARK'
NEEDLE = 'TAL_VOID_VOID_NEEDLE'
CHECK = 'condition:typed.furnace_motion_check'


def free_needle(bundles):
    owner = next(b for b in bundles if b['actor_id'] == OWNER)
    for action in owner['action_catalog']:
        if NEEDLE in action['source_definition_id']:
            action['economy'] = 'NONE'
            action['parameters']['free_primary'] = True
    owner.pop('bundle_sha256', None)
    owner['bundle_sha256'] = canonical_sha256(owner)


def pinned_roll(engine, roll, intent):
    if roll.actor_id == FOE and 'SAVE' in str(roll.reason).upper():
        return {'source_id': 'test:demonmark1.save', 'operation': 'replace', 'natural_result': 1}
    if roll.actor_id == OWNER and 'ATTACK' in str(roll.reason).upper():
        return {'source_id': 'test:demonmark1.hit', 'operation': 'replace', 'natural_result': 15}


@pytest.mark.parametrize('augmented', [False, True])
def test_mark_cultivation_damage_once_per_turn_across_table_reload(tmp_path, monkeypatch, augmented):
    install(monkeypatch, 'd20_result', pinned_roll)
    combat, table, mid, send, commit = fixture(
        tmp_path, [MARK, NEEDLE], owner_cl=10, owner_pb=4,
        seed='DEMONMARK1', bundle_transform=free_needle)

    # Select the exact button: the plain mark must not accidentally use Augment.
    label = 'Demon Mark + Daemonic Augment: Bonus Damage' if augmented else 'Demon Mark'
    menu = table.state(mid)['menu']
    cid = next(o['candidate_id'] for g in menu['actions'] if g['label'] == label
               for o in g['options'] if FOE in o.get('target_ids', []))
    assert commit(cid)['status'] == 'COMMITTED'
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    spent = {k: v for k, v in fresh.state.actors[OWNER].turn_flags.items()
             if k.startswith('_round_typed_on_hit:') and MARK in k}
    assert bool(spent) == augmented
    if augmented:
        packets = [e for e in fresh.events if e.event_type == 'DAMAGE_COMMITTED'
                   and e.actor_id == OWNER and FOE in e.target_ids]
        assert len(packets) == 1
        # The Augment PB plus the mark PB. The Qi path's potency is part of
        # this fixture's compiled numbers, not another Demon Mark use.
        action = fresh.action_catalog[packets[0].source_definition_id]
        potency = int(action.parameters['typed']['numbers'].get('potency') or 0)
        assert packets[0].payload['rolled_or_pending_damage'] == 8 + potency

    def needle(target):
        before = table.state(mid)['last_sequence']
        assert commit(candidate(table, mid, 'Void Needle: Cost Lock', target))['status'] == 'COMMITTED'
        engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
        events = [e for e in engine.events if e.sequence > before]
        damage = next(e for e in events if e.event_type == 'DAMAGE_ROLLED'
                      and NEEDLE in e.source_definition_id)
        attack = next(e for e in events if e.event_type == 'ATTACK_ROLLED'
                      and NEEDLE in e.source_definition_id)
        assert engine.state.current_actor_id == OWNER
        return damage.payload['modifier'], attack.payload['modifier']

    first, first_attack = needle(FOE)
    second, second_attack = needle(FOE)
    unmarked, unmarked_attack = needle(SECOND)
    assert first == second + (0 if augmented else 4)
    assert second == unmarked
    assert first_attack == second_attack == unmarked_attack
    final = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(k.startswith('_round_typed_on_hit:') and MARK in k
               and isinstance(v, str) for k, v in final.engine.state.actors[OWNER].turn_flags.items())
    assert final.verify()['status'] == final.mechanical.replay()['status'] == 'PASS'


def test_furnace_motion_waits_for_a_check_after_a_cultivation_attack(tmp_path, monkeypatch):
    install(monkeypatch, 'd20_result', pinned_roll)
    # Native engine probe with a synthetic armed condition. Granting the
    # benefit and its expiry are covered by the existing Furnace Motion file.
    combat, table, mid, send, commit = fixture(
        tmp_path, [NEEDLE], seed='DEMONMARK1-FURNACE')
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    engine._apply_condition(actor, CHECK, 'test:demonmark1.furnace', OWNER,
        expires_on='UNTIL_REMOVED', data={'bonus': 4})
    from tests.test_riders_c7 import use
    events = use(engine, 'Void Needle: Cost Lock', target=FOE, actor_id=OWNER)
    assert any(e.event_type == 'ATTACK_ROLLED' for e in events)
    assert any(c.condition_id == CHECK for c in actor.conditions.values())
    # A genuine Cultivation Check, unlike that attack, consumes the bonus.
    from types import SimpleNamespace
    from combat.ext.furnace_core import check_bonus
    with engine.d20_scope({'kind': 'check', 'actor_id': OWNER, 'check_kind': 'cultivation'}):
        assert check_bonus(engine, SimpleNamespace(actor_id=OWNER), None)['bonus'] == 4
    assert not any(c.condition_id == CHECK for c in actor.conditions.values())

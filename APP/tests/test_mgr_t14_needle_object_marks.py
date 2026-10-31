"""Actual Ice acquisition -> pre-roll type choice -> object/creature hit -> cold expiry."""
import pytest

from combat.gate5_service import CombatService
from combat.mark_ledger import owned
from combat.ext.ice_fracture import BASE, MARK
from combat.tabletop import TabletopMapStore, to_battlefield
from tests.h1_support import ROOT
from tests.mgr_t14_acquisition_support import acquire_owner
from tests.worker2_support import OWNER, FOE, fixture, candidate, settle, reload, turn

TYPE = 'choice:needle.shard_needle_type'
RESPONSE = 'choice:needle.fracture_response'


@pytest.mark.parametrize('object_target', [False, True])
@pytest.mark.parametrize('damage_type', ['PIERCING', 'COLD'])
def test_real_needle_chooses_before_its_roll_and_marks_its_actual_recipient_with_native_expiry(
        tmp_path, object_target, damage_type):
    saved = TabletopMapStore(tmp_path).save({'display_name': 'Native Needle training yard',
        'width_squares': 20, 'height_squares': 18, 'objects': [
            {'kind': 'custom', 'name': 'Wooden training post', 'x': 5, 'y': 5,
                'material': 'wood', 'hp': 900, 'blocks': False}]})
    acquisition = acquire_owner('tianxia.sphere.ice', OWNER)
    def edit(doc, aid):
        acquisition(doc, aid)
        doc['ability_scores_and_statistics']['technique_attack_bonus'] = 100
    combat, table, mid = fixture(tmp_path, [BASE], cl=1, named=True,
        battlefield=to_battlefield(saved), sheet_edit=edit)
    target = 'object:map.1' if object_target else FOE
    for _ in range(8):
        before = reload(tmp_path, mid).state.event_sequence
        prompts = settle(table, mid, candidate(combat, mid, 'Shard Needle', target=target).candidate_id,
            choices={TYPE: [damage_type], RESPONSE: None})
        engine = reload(tmp_path, mid)
        actual = [event for event in engine.events if event.sequence > before]
        roll = next(event for event in actual if event.event_type == 'ATTACK_ROLLED' and event.actor_id == OWNER)
        choice = next(p for p in prompts if p['context']['reaction_source_id'] == TYPE)
        assert int(choice['context']['checkpoint'].split(':')[2]) < roll.sequence
        assert {o['id'] for o in choice['choice']['options']} == {'PIERCING', 'COLD'}
        assert 'Shard Needle' in str(choice) and 'before the attack roll' in str(choice)
        if not roll.payload['provisional_hit']:
            assert not owned(engine, MARK, OWNER)
            settle(table, mid, table.state(mid)['menu']['end_turn'])
            turn(table, mid, OWNER)
            continue
        marks = owned(engine, MARK, OWNER)
        assert len(marks) == 1 and marks[0]['kind'] == ('object' if object_target else 'creature')
        if object_target:
            damage = next(e.payload['damage'] for e in actual
                if e.event_type == 'OBJECT_UPDATED' and e.target_ids == (target,) and e.payload.get('damage'))
            assert damage['taken'] > 0
            assert damage['packets'][0]['damage_type'] == damage_type
            assert not any(actor.entity_id == target for actor in engine.state.actors.values())
        else:
            damage = next(e.payload for e in actual if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (target,))
            assert damage['hp_damage'] > 0 and damage['damage_type'] == damage_type
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, OWNER)
        assert len(owned(reload(tmp_path, mid), MARK, OWNER)) == 1
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        session = CombatService(ROOT, tmp_path)._load_session(mid)
        assert not owned(session.engine, MARK, OWNER)
        assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
        return
    raise AssertionError('No actual Needle hit in eight native turns')


def test_plain_unowned_native_character_acquires_no_needle_or_ice_object_mark(tmp_path):
    combat, table, mid = fixture(tmp_path, [], cl=1)
    engine = reload(tmp_path, mid)
    assert not any(c.display_name == 'Shard Needle' for c in engine.legal_candidates())
    assert not owned(engine, MARK, OWNER)

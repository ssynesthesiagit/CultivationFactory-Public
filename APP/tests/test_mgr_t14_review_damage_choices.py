"""Native regressions for the F3 review: pre-roll Ice and post-hit Stars choices."""
import pytest

from combat.gate5_service import CombatService
from combat.ext import stars
from tests.h1_support import ROOT
from tests.mgr_t14_acquisition_support import acquire_owner
from tests.worker2_support import OWNER, FOE, fixture, candidate, settle, reload
from tests.cw2_service_support import seal
from tests.test_mgr_t14_starbolt_base import native_fight, TYPE_CHOICE
from tests.auto_worker1_support import LEFT, RIGHT, act, resolve

NEEDLE_TYPE = 'choice:needle.shard_needle_type'


@pytest.mark.parametrize('hit', [False, True])
@pytest.mark.parametrize('resistance', ['PIERCING', 'COLD'])
def test_needle_cold_is_the_declared_type_even_against_resistance(tmp_path, hit, resistance):
    acquire = acquire_owner('tianxia.sphere.ice', OWNER)
    def edit(doc, aid):
        acquire(doc, aid)
        if aid == OWNER:
            doc['ability_scores_and_statistics']['technique_attack_bonus'] = 100 if hit else -100
    def defenses(bundles):
        for bundle in bundles:
            if bundle['actor_id'] == FOE:
                bundle['actor_template']['damage_resistances'] = [resistance]
                seal(bundle)
    combat, table, mid = fixture(tmp_path, [], cl=1, named=True,
        sheet_edit=edit, bundle_transform=defenses)
    prompts = settle(table, mid, candidate(combat, mid, 'Shard Needle', target=FOE).candidate_id,
        choices={NEEDLE_TYPE: ['COLD'], 'choice:needle.fracture_response': None})
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = session.engine
    assert resistance in engine.state.actors[FOE].damage_resistances
    choices = [p for p in prompts if p['context']['reaction_source_id'] == NEEDLE_TYPE]
    assert len(choices) == 1
    choice = choices[0]
    assert {o['id'] for o in choice['choice']['options']} == {'PIERCING', 'COLD'}
    roll = next(e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER)
    assert int(choice['context']['checkpoint'].split(':')[2]) < roll.sequence
    assert roll.payload['provisional_hit'] is hit
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
    if hit:
        assert len(damage) == 1 and damage[0].payload['damage_type'] == 'COLD'
        payload = damage[0].payload
        assert payload['hp_damage'] > 0
        assert (payload['reduced_to'] < payload['rolled_or_pending_damage']) == (resistance == 'COLD')
    else:
        assert not damage
        assert engine.state.actors[FOE].current_hp == engine.state.actors[FOE].maximum_hp
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('mark', [False, True])
def test_starbolt_type_choice_does_not_replace_optional_mark(tmp_path, mark):
    combat, table, mid = native_fight(tmp_path)
    _, prompts = resolve(lambda answers: act(table, mid, 'Starbolt', answers, target_id=RIGHT),
        {TYPE_CHOICE: ['COLD'], 'choice:needle.starbolt_mark': ['MARK'] if mark else []})
    relevant = [p['context']['reaction_source_id'] for p in prompts
        if p['context']['reaction_source_id'] in {TYPE_CHOICE, 'choice:needle.starbolt_mark'}]
    assert relevant == [TYPE_CHOICE, 'choice:needle.starbolt_mark']
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert stars.bears_mark(session.engine.state.actors[RIGHT], LEFT) is mark
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'

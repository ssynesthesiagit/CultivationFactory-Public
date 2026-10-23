"""Daemonic resource benefits, actual flight and target perception at the table."""
import pytest
from combat.flight import profile
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, FOE, candidate, fixture, reload, settle

P = 'TAL_DAEMONIC_CULTIVATION_'
ESSENCE = 'resource:named.devoured_essence'
CORRUPTION = 'resource:named.corruption'


@pytest.mark.parametrize('form,speed,hover', [('DEMON_EMPEROR_INCARNATION',60,True), ('INNER_DEMON_INCARNATION',35,False)])
def test_daemonic_forms_grant_real_flight_without_changing_walk(tmp_path, form, speed, hover):
    combat, table, mid = fixture(tmp_path, [P+form], owner_speed=35)
    name = 'Demon Emperor Incarnation' if hover else 'Inner Demon Incarnation'
    settle(table, mid, candidate(combat, mid, name).candidate_id)
    e = reload(tmp_path, mid)
    actor = e.state.actors[OWNER]
    assert profile(e, actor).speed_ft == speed and profile(e, actor).hover == hover
    assert e._effective_speed(actor) == 35
    c = next(c for c in e.legal_candidates() if c.destination and c.destination.z == 1
             and (c.destination.x,c.destination.y) == (actor.position.x,actor.position.y))
    settle(table, mid, c.candidate_id)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].position.z == 1
    held = next(c for c in e.state.actors[OWNER].conditions.values() if 'daemonic_' in c.condition_id and 'flight' in c.condition_id)
    assert held.expires_on.startswith('START_OF_SLOT_AT:')


@pytest.mark.parametrize('choice,kind', [('corruption','Undead'), ('resource:core.stamina','Humanoid'), (None,'Undead')])
def test_bloodless_choice_pays_once_and_reduces_real_corruption(tmp_path, choice, kind):
    def prepare(bundles):
        b = bundles[0]
        for resource in b['actor_template']['resources']:
            if resource['resource_id'] == ESSENCE: resource.update(initial=4,maximum=10)
            elif resource['resource_id'] == CORRUPTION: resource.update(initial=3,maximum=10)
            elif resource['resource_id'] == 'resource:core.qi': resource['initial']=90
        b['actor_template']['resources'].append({'resource_id':'resource:core.stamina','initial':2,'maximum':5})
        add_action(b,'Wound enemy',[{'type':'damage','flat':40,'applies_to':'target','damage_types':['force']}])
        add_action(b,'Damage wounded enemy',[{'type':'damage','flat':1,'applies_to':'target','damage_types':['force']}])
        bundles[2]['actor_template']['creature_types']=[kind]
        seal(bundles[2])
    combat, table, mid = fixture(tmp_path, [P+'BLOODLESS_DEVOURING'], bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Wound enemy', target=FOE).candidate_id)
    prompts = settle(table, mid, candidate(combat, mid, 'Damage wounded enemy', target=FOE).candidate_id,
        {'choice:needle.bloodless_devouring':choice})
    prompt = next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.bloodless_devouring')
    assert ('corruption' in [o['id'] for o in prompt['choice']['options']]) == (kind=='Undead')
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources[ESSENCE] == 4-int(choice is not None)
    assert e.state.actors[OWNER].resources[CORRUPTION] == 3-int(choice=='corruption')
    assert e.state.actors[OWNER].resources['resource:core.stamina'] == 2+int(choice=='resource:core.stamina')
    assert e.state.actors[OWNER].resources['resource:core.qi'] == 90
    if choice is not None:
        again = settle(table, mid, candidate(combat, mid, 'Damage wounded enemy', target=FOE).candidate_id)
        assert not any(p['context']['reaction_source_id']=='choice:needle.bloodless_devouring' for p in again)
        assert reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE] == 3


@pytest.mark.parametrize('deaf', [True,False])
def test_dread_requires_target_to_see_or_hear_the_invisible_caster(tmp_path,deaf):
    def prepare(bundles):
        add_action(bundles[0],'Hide caster',[{'type':'condition','condition':'invisible','applies_to':'self','expires_on':'UNTIL_REMOVED'}],target='SELF')
        if deaf:
            add_action(bundles[0],'Deafen enemy',[{'type':'condition','condition':'deafened','applies_to':'target','expires_on':'UNTIL_REMOVED'}])
        bundles[2]['actor_template']['saving_throws']['WIS']=-100
        seal(bundles[2])
    combat,table,mid=fixture(tmp_path,[P+'DREAD_APPETITE'],bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Hide caster').candidate_id)
    if deaf: settle(table,mid,candidate(combat,mid,'Deafen enemy',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    rows=[c for c in e.legal_candidates() if c.source_definition_id in e.action_catalog
          and c.target_ids==(FOE,) and e.action_catalog[c.source_definition_id].display_name=='Dread Appetite: Frighten']
    assert not any(c.target_ids==(FOE,) and c.source_definition_id in e.action_catalog
                   and 'Press the Fear' in e.action_catalog[c.source_definition_id].display_name for c in e.legal_candidates())
    assert bool(rows) != deaf
    if rows:
        settle(table,mid,rows[0].candidate_id)
        e=reload(tmp_path,mid)
        held=next(c for c in e.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.frightened')
        assert held.expires_on=='END_OF_SOURCE_TURN_AT:2'

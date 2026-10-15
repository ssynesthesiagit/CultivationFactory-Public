"""Owned Ice choices resolve on real hits/damage, persist and replay."""
import pytest
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, turn
from tests.worker2_support import settle, reload
from tests.test_carry import KIT
from combat.ext.ice_fracture import BASE, marked, lattice_zones
from combat.typed_executor import mark_condition_id


def setup(bundles):
    for b,bonus in zip(bundles,[100,-100,0]):
        b['actor_template']['initiative_bonus']=bonus
        b['actor_template']['maximum_hp']=300
        seal(b)
    bundles[2]['actor_template']['armor_class']=0
    bundles[2]['actor_template']['saving_throws']['DEX']=-100
    add_action(bundles[0],'Mark myself',[{'type':'mark','mark':'Fracture Mark','applies_to':'self','duration':{'kind':'until_removed'}}],target='SELF')
    add_action(bundles[0],'Blind myself',[{'type':'condition','condition':'blinded','applies_to':'self','expires_on':'UNTIL_REMOVED'}],target='SELF')
    add_action(bundles[0],'Mark foe',[{'type':'mark','mark':'Fracture Mark','applies_to':'target','duration':{'kind':'until_removed'}}])
    add_action(bundles[2],'Deal impact',[{'type':'damage','flat':40,'damage_types':['bludgeoning'],'applies_to':'target'}])
    seal(bundles[2])


def advance(table,mid,actor,picks=None):
    prompts=[]
    for _ in range(12):
        if table.state(mid)['menu']['actor_id']==actor:return prompts
        prompts+=settle(table,mid,table.state(mid)['menu']['end_turn'],picks)
    raise AssertionError('No turn')


@pytest.mark.parametrize('selected',[OWNER,FOE,None])
def test_diamond_rime_body_owner_selects_or_declines_hit_lattice(tmp_path,selected):
    combat,table,mid=fixture(tmp_path,['TAL_ICE_DIAMOND_RIME_BODY'],owner_ac=0,
        foe_position={'x':3,'y':5},foe_kit={'starting_kit':{'items':[KIT['items'][-1]]}},bundle_transform=setup)
    settle(table,mid,candidate(combat,mid,'Diamond Rime Body').candidate_id)
    turn(table,mid,FOE)
    prompts=settle(table,mid,candidate(combat,mid,'Bi Shou (Dagger) attack',target=OWNER).candidate_id,
        {'choice:needle.rime_body_space':selected})
    p=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.rime_body_space')
    assert p['context']['reactor_id']==OWNER and {o['id'] for o in p['choice']['options']}=={OWNER,FOE}
    e=reload(tmp_path,mid);zs=lattice_zones(e,OWNER)
    assert len(zs)==(0 if selected is None else 1)
    if selected is not None:
        assert zs[0].center==e.state.actors[selected].position
    assert e.state.actors[OWNER].reaction_available
    assert e.state.actors[OWNER].resources['resource:core.qi']==97


@pytest.mark.parametrize('dtype',['COLD','PIERCING'])
def test_brittle_opening_chooses_actual_damage_type_and_consumes_mark(tmp_path,dtype):
    combat,table,mid=fixture(tmp_path,['TAL_ICE_RIME_HOOK'],bundle_transform=setup)
    settle(table,mid,candidate(combat,mid,'Mark foe',target=FOE).candidate_id)
    old_mark=next(c.instance_id for c in reload(tmp_path,mid).state.actors[FOE].conditions.values()
        if c.condition_id==mark_condition_id('Fracture Mark',OWNER))
    # Stage the earlier mark; the real Shard Needle supplies the actual hit trigger.
    prompts=settle(table,mid,candidate(combat,mid,'Shard Needle',target=FOE).candidate_id,
        {'choice:needle.fracture_response':'brittle','choice:needle.brittle_type':dtype})
    assert any(p['context']['reactor_id']==OWNER and p['context']['reaction_source_id']=='choice:needle.brittle_type' for p in prompts)
    e=reload(tmp_path,mid)
    hit=next(v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and v.source_definition_id==BASE)
    die=next(r for r in e.rolls if r.reason=='BRITTLE_OPENING')
    assert hit.payload['damage_type']==dtype and hit.payload['rolled_or_pending_damage']==die.total+4
    assert old_mark not in e.state.actors[FOE].conditions and e.state.actors[OWNER].reaction_available
    # Shard Needle grants a fresh mark after the hit response consumes the old one.
    assert marked(e.state.actors[FOE],OWNER)
    assert e.state.actors[OWNER].turn_flags['ice_spent_round'].endswith(':1')


@pytest.mark.parametrize('accept',[True,False])
def test_rime_hook_explicit_destination_or_decline_after_real_shatter(tmp_path,accept):
    combat,table,mid=fixture(tmp_path,['TAL_ICE_RIME_HOOK'],foe_position={'x':2,'y':6},bundle_transform=setup)
    settle(table,mid,candidate(combat,mid,'Crystallize Path').candidate_id)
    settle(table,mid,candidate(combat,mid,'Mark foe',target=FOE).candidate_id)
    prompts=advance(table,mid,FOE,{'choice:needle.fracture_response':'shatter',
        'choice:needle.rime_hook':'cell:3,5' if accept else None})
    p=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.rime_hook')
    assert p['context']['reactor_id']==OWNER
    e=reload(tmp_path,mid)
    assert (e.state.actors[FOE].position.x,e.state.actors[FOE].position.y)==((3,5) if accept else (2,6))
    moves=[v for v in e.events if v.event_type=='MOVEMENT_COMMITTED' and v.source_definition_id=='TAL_ICE_RIME_HOOK']
    assert bool(moves)==accept and all(v.payload.get('forced') for v in moves)
    assert e.state.actors[OWNER].reaction_available


def test_diamond_first_crystal_guard_preserves_the_round_spend_limit(tmp_path):
    combat,table,mid=fixture(tmp_path,['TAL_ICE_DIAMOND_RIME_BODY'],bundle_transform=setup)
    settle(table,mid,candidate(combat,mid,'Diamond Rime Body').candidate_id)
    turn(table,mid,FOE)
    # Prepare a self-mark on the next owner turn; then take repeated actual damage.
    turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Mark myself',target=OWNER).candidate_id)
    turn(table,mid,FOE)
    prompts=settle(table,mid,candidate(combat,mid,'Deal impact',target=OWNER).candidate_id,
        {'choice:needle.fracture_response':'guard'})
    assert any(p['context']['reactor_id']==OWNER and p['context']['reaction_source_id']=='choice:needle.fracture_response' for p in prompts)
    e=reload(tmp_path,mid)
    assert not e.state.actors[OWNER].turn_flags.get('ice_spent_round')
    assert e.state.actors[OWNER].turn_flags['ice_rime_guard_round']==e.state.round_number
    assert not marked(e.state.actors[OWNER],OWNER)


def test_unperceived_mark_does_not_offer_a_fracture_response(tmp_path):
    combat,table,mid=fixture(tmp_path,['TAL_ICE_RIME_HOOK'],ally_kit={'starting_kit':KIT},
        foe_position={'x':3,'y':5},bundle_transform=setup)
    settle(table,mid,candidate(combat,mid,'Mark foe',target=FOE).candidate_id)
    settle(table,mid,candidate(combat,mid,'Blind myself',target=OWNER).candidate_id)
    advance(table,mid,ALLY,{'choice:needle.fracture_response':None})
    prompts=settle(table,mid,candidate(combat,mid,'Bi Shou (Dagger) attack',target=FOE).candidate_id)
    assert not any(p['context']['reaction_source_id']=='choice:needle.fracture_response' for p in prompts)
    assert marked(reload(tmp_path,mid).state.actors[FOE],OWNER)

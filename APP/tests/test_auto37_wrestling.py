"""Wrestling windows and physiology through committed table actions."""
import pytest
from combat.canonical import canonical_sha256
from combat.ext.hand_occupancy import free_hands
from combat.ext.wrestling import CHOKE,CHOKE_HISTORY
from tests.worker2_support import OWNER,FOE,fixture,candidate,act,settle,turn,reload
from tests.test_carry import KIT
GROUND='TAL_WRESTLING_GROUND_GAME'
OPENING='TAL_WRESTLING_OPENING_STRIKE'
CHOKER='TAL_WRESTLING_CHOKE_HOLD'


def prepare(bundles, breathing=True, old=False):
    for b in bundles:
        if b['actor_id']==FOE:
            b['actor_template']['saving_throws'].update(STR=-100,DEX=-100,CON=-100)
            b['actor_template']['creature_types']=['Humanoid','physiology:breath_dependent:'+str(int(breathing))]
        for a in b['action_catalog']:
            t=a.get('parameters',{}).get('typed',{})
            if b['actor_id']==OWNER and t.get('weapon'):
                t['numbers']['attack_bonus']=100
            if b['actor_id']==FOE and t.get('unarmed_option')=='grapple':
                t['numbers']['save_dc']=100
            if old:
                for eff in t.get('effects',[]):
                    eff.pop('breath_gate',None)
        b.pop('bundle_sha256',None); b['bundle_sha256']=canonical_sha256(b)


@pytest.mark.parametrize('accept',[True,False])
def test_ground_game_reaction_after_successful_grapple(tmp_path,accept):
    combat,table,mid=fixture(tmp_path,[GROUND],foe_position={'x':3,'y':5},bundle_transform=prepare)
    turn(table,mid,FOE)
    c=candidate(combat,mid,'Grapple',target=OWNER)
    before=combat._load_session(mid).engine.state.model_dump(mode='json')
    p=act(table,mid,c.candidate_id)
    assert p['status']=='REACTION_REQUIRED'
    assert combat._load_session(mid).engine.state.model_dump(mode='json')==before
    prompts=settle(table,mid,c.candidate_id,{'choice:needle.ground_game':'use' if accept else None})
    assert any(p['context']['reactor_id']==OWNER and p['context']['reaction_source_id']=='choice:needle.ground_game' for p in prompts)
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].reaction_available is (not accept)
    assert any(c.condition_id=='condition:typed.grappled' for c in e.state.actors[OWNER].conditions.values())
    assert any(c.condition_id=='condition:typed.prone' for c in e.state.actors[FOE].conditions.values())==accept
    if accept:
        save=next(ev for ev in e.events if ev.event_type=='SAVE_ROLLED' and 'ground_game' in ev.source_definition_id.lower())
        assert save.payload['dc']==14


def test_ground_game_bonus_action_requires_start_turn_owned_grapple(tmp_path):
    combat,table,mid=fixture(tmp_path,[GROUND],foe_position={'x':3,'y':5},bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Grapple',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    assert not any(e.action_catalog.get(c.source_definition_id) and e.action_catalog[c.source_definition_id].display_name=='Ground Game' for c in e.legal_candidates())
    turn(table,mid,FOE);turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Ground Game',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    assert not e.state.actors[OWNER].bonus_action_available
    assert any(c.condition_id=='condition:typed.prone' for c in e.state.actors[FOE].conditions.values())


def test_opening_strike_requires_damage_then_allocates_the_free_hand(tmp_path):
    combat,table,mid=fixture(tmp_path,[OPENING],foe_position={'x':3,'y':5},
                            owner_kit={'starting_kit':{'items':[KIT['items'][-1]]}},bundle_transform=prepare)
    def opening_rows(e):
        return [c for c in e.legal_candidates() if e.action_catalog.get(c.source_definition_id)
                and e.action_catalog[c.source_definition_id].display_name=='Opening Strike']
    assert not opening_rows(reload(tmp_path,mid))
    settle(table,mid,candidate(combat,mid,'Bi Shou (Dagger) attack',target=FOE).candidate_id)
    assert reload(tmp_path,mid).state.actors[FOE].current_hp<60
    settle(table,mid,candidate(combat,mid,'Opening Strike',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    holds=[c for c in e.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.grappled']
    assert len(holds)==1 and holds[0].data['grapple_source']=='physical'
    assert holds[0].data['grappling_part'].startswith('hand:')
    assert holds[0].data['escape_dc']==14 and holds[0].expires_on=='UNTIL_REMOVED'
    assert not free_hands(e,e.state.actors[OWNER])
    assert not any(e.action_catalog.get(c.source_definition_id) and
                   e.action_catalog[c.source_definition_id].parameters.get('typed',{}).get('unarmed_option')=='grapple'
                   for c in e.legal_candidates())
    turn(table,mid,FOE);turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Bi Shou (Dagger) attack',target=FOE).candidate_id)
    assert not opening_rows(reload(tmp_path,mid))


@pytest.mark.parametrize('breathing,old',[(True,False),(False,False),(False,True)])
def test_choke_hold_respects_printed_breathing_and_preserves_old_bundles(tmp_path,breathing,old):
    combat,table,mid=fixture(tmp_path,[CHOKER],foe_position={'x':3,'y':5},
                            bundle_transform=lambda b:prepare(b,breathing,old))
    settle(table,mid,candidate(combat,mid,'Grapple',target=FOE).candidate_id)
    settle(table,mid,candidate(combat,mid,'Apply a Slam: Choke Hold',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    assert any(c.condition_id==CHOKE for c in e.state.actors[FOE].conditions.values())==(breathing or old)
    assert any(c.condition_id==CHOKE_HISTORY for c in e.state.actors[FOE].conditions.values())==(breathing or old)

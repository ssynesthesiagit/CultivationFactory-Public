"""Additional saved-table absence and Anchored Soul lifecycle regressions."""
import pytest
from tests.test_hunt32_edge import OWNER, FOE, act, match, reload
from tests.test_a2_space_third_pass import PRISON, EXILE, VOID, ANCHOR, DISPLACE, _advance, _answered_action
from combat.ext.spatial_absence import absent


def test_void_success_damage_is_immediate_and_never_removes_the_body(tmp_path):
    combat,table,fight=match(tmp_path,[VOID],setup_actions=[{
        'name':'Successful Charisma save','target':'ANY_CREATURE',
        'effects':[{'type':'save_bonus','amount':100,'abilities':['CHA'],
                    'applies_to':'target','expires_on':'UNTIL_REMOVED'}]}])
    assert act(table,fight,'Successful Charisma save',FOE)['status']=='COMMITTED'
    hp=reload(combat,tmp_path,fight).state.actors[FOE].current_hp
    assert act(table,fight,'Void Between Worlds',FOE)['status']=='COMMITTED'
    engine=reload(combat,tmp_path,fight)
    assert not absent(engine.state.actors[FOE])
    assert engine.state.actors[FOE].current_hp < hp
    rolls=[e for e in engine.events if e.event_type=='DAMAGE_ROLLED' and 'void_between_worlds' in e.source_definition_id]
    assert len(rolls)==1 and rolls[0].payload['expression']=='4d10+0'
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and 'void_between_worlds' in e.source_definition_id]
    assert saves[-1].payload['dc']==-60 and saves[-1].payload['modifier']==2


@pytest.mark.parametrize('mid,label',[(PRISON,'Fold Prison'),(EXILE,'Exile Beyond the Horizon')])
def test_return_to_same_coordinates_counts_as_entry_into_map_hazard(tmp_path,mid,label):
    combat,table,fight=match(tmp_path,[mid],map_terrain=[{
        'terrain':'fire terrain','cells':[[4,6]],'pb':3,'save_dc':1000}],setup_actions=[{
        'name':'Break concentration','effects':[{'type':'damage','applies_to':'self','flat':50,'damage_types':['force']}]}])
    assert act(table,fight,label,FOE)['status']=='COMMITTED'
    engine=reload(combat,tmp_path,fight)
    hp=engine.state.actors[FOE].current_hp
    home=engine.state.actors[FOE].position
    assert absent(engine.state.actors[FOE])
    assert act(table,fight,'Break concentration')['status']=='COMMITTED'
    engine=reload(combat,tmp_path,fight)
    assert not absent(engine.state.actors[FOE])
    assert engine.state.actors[FOE].position==home
    assert engine.state.actors[FOE].current_hp < hp


def test_anchored_soul_return_is_not_reusable_after_reload(tmp_path):
    combat,table,fight=match(tmp_path,[DISPLACE],foe_mids=[ANCHOR])
    start=reload(combat,tmp_path,fight).state.actors[FOE].position
    _answered_action(table,fight,'Spatial Displacement',FOE)
    assert reload(combat,tmp_path,fight).state.actors[FOE].position==start
    _advance(table,fight)
    _advance(table,fight)
    prompts=_answered_action(table,fight,'Spatial Displacement',FOE)
    engine=reload(combat,tmp_path,fight)
    assert not any('anchored_soul' in str(p['context']) for p in prompts)
    assert engine.state.actors[FOE].position!=start


@pytest.mark.parametrize('abilities,against,returns', [
    (['CHA'], [], True), (['WIS'], [], False),
    (['CHA'], ['spatial_absence'], True), (['CHA'], ['charmed'], False)])
def test_exile_repeat_save_returns_before_minute_expires(tmp_path,abilities,against,returns):
    combat,table,fight=match(tmp_path,[EXILE],foe_setup_actions=[{
        'name':'Ready to return','effects':[{'type':'save_bonus','amount':100,
        'abilities':abilities,'against':against,'applies_to':'self','expires_on':'UNTIL_REMOVED'}]}])
    assert act(table,fight,'Exile Beyond the Horizon',FOE)['status']=='COMMITTED'
    assert absent(reload(combat,tmp_path,fight).state.actors[FOE])
    _advance(table,fight)
    assert act(table,fight,'Ready to return')['status']=='COMMITTED'
    assert absent(reload(combat,tmp_path,fight).state.actors[FOE])
    _advance(table,fight)
    engine=reload(combat,tmp_path,fight)
    assert absent(engine.state.actors[FOE]) is not returns
    assert (engine.state.actors[OWNER].concentration is None) is returns
    assert any(e.event_type=='CONDITION_REMOVED' and e.payload.get('repeat_save')
               and FOE in e.target_ids for e in engine.events) is returns
    rolls=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and 'exile_beyond_the_horizon' in e.source_definition_id]
    assert rolls[-1].payload['dc']==40
    assert rolls[-1].payload['modifier']==(102 if returns else 2)

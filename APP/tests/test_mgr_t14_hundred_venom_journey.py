"""Outside-combat poison uses the same acquired source, native turns and replay."""
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.worker2_support import settle,reload,turn
from tests.test_mgr_t14_hundred_venom import acquire,native_exposure,commit,P


def finish(table, mid, tmp_path):
    for _ in range(8):
        e=reload(tmp_path,mid)
        if e.state.terminal_result:return e
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    raise AssertionError('The bounded native scene did not finish')


def test_actual_delayed_poison_continues_through_journey_and_second_native_scene(catalog_environment,monkeypatch,tmp_path):
    acquire(catalog_environment,monkeypatch,6)
    c,_,_,owner,source,jid=native_exposure(tmp_path,catalog_environment,6,delivery='poisoned',stage='collected')
    state=c.journey_state(jid)
    mid=c.journey_start_scene(jid,state['revision'],{owner:'team:party',source:'team:party'})['match_id']
    table=TabletopService(c,tmp_path);turn(table,mid,source)
    before=reload(tmp_path,mid).state.actors[owner].resources['resource:core.stamina']
    prompts=commit(c,table,mid,'Recorded external exposure — resolve recorded exposure',owner,
                   {'choice:needle.swallow_the_poison_delay':['delay']})
    e=reload(tmp_path,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.swallow_the_poison_delay' for p in prompts)
    assert e.state.actors[owner].resources['resource:core.stamina']==before-1
    terminal=finish(table,mid,tmp_path)
    original=terminal.state.model_dump(mode='json')
    state=c.journey_resume(jid,c.journey_state(jid)['revision'])
    assert state['seconds']==6
    assert state['actors'][owner]['source_states'][P.removesuffix('.feature.')]['native_effects']
    # The source packet and its pending condition came from accepted native
    # actions. A time skip cannot erase them or manufacture a fresh reaction.
    with pytest.raises(ValueError,match='six-second table scene'):
        CombatService(ROOT,tmp_path).journey_act(jid,state['revision'],owner,'wait',{'seconds':60})
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state
    mid2=CombatService(ROOT,tmp_path).journey_act(jid,state['revision'],owner,'open_scene',
            {'teams':{owner:'team:party',source:'team:party'}})['match_id']
    e=reload(tmp_path,mid2)
    assert e.state.actors[owner].resources['resource:core.stamina']==before-1
    assert any(x.condition_id in ('condition:typed.swallowed_poison','condition:typed.poisoned')
               for x in e.state.actors[owner].conditions.values())
    table=TabletopService(CombatService(ROOT,tmp_path),tmp_path)
    finish(table,mid2,tmp_path)
    state=CombatService(ROOT,tmp_path).journey_resume(jid,CombatService(ROOT,tmp_path).journey_state(jid)['revision'])
    assert state['seconds']==12
    assert reload(tmp_path,mid).state.model_dump(mode='json')==original


def test_native_scene_is_explicit_and_unrelated_combat_keeps_its_team_guard(catalog_environment,monkeypatch,tmp_path):
    acquire(catalog_environment,monkeypatch,6)
    c,_,_,owner,source,jid=native_exposure(tmp_path,catalog_environment,6,stage='collected')
    state=c.journey_state(jid)
    with pytest.raises(ValueError,match='explicit team'):
        c.journey_start_combat(jid,state['revision'],{owner:'team:party',source:'team:party'})
    assert c.journey_state(jid)==state
    mid=c.journey_start_scene(jid,state['revision'],{owner:'team:party',source:'team:party'})['match_id']
    table=TabletopService(c,tmp_path)
    e=reload(tmp_path,mid)
    assert e.state.terminal_result is None and e.state.rules['scene_window']=='elapsed_rounds_v1'
    finish(table,mid,tmp_path)

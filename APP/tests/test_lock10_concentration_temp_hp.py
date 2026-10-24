"""Temporary HP absorbs loss, not the damage used by Concentration saves."""
import pytest
from tests.h1_support import duel, ME, FOE, script, ROOT
from tests.test_lock_choices import install
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, RIGHT, HOLD
from tests.test_lock2_persistence import act
from combat.gate5_service import CombatService


@pytest.mark.parametrize('temporary,damage,dc',[(50,5,10),(50,30,15),(25,40,20),(0,20,10),(50,0,None),(8,6,10),(5,40,20)])
def test_check_uses_damage_before_temporary_hp(temporary,damage,dc):
    e=duel([])
    target=e.state.actors[ME]
    e._start_concentration(target,'test:concentration')
    target.temporary_hp=temporary
    script(e,[1])
    start=len(e.events)
    e._commit_damage(target,damage,'UNTYPED','test:damage',FOE,None,reaction_depth=0)
    saves=[ev for ev in e.events[start:] if ev.event_type=='SAVE_ROLLED']
    assert [ev.payload['dc'] for ev in saves]==([] if dc is None else [dc])
    assert target.current_hp==60-max(0,damage-temporary)
    assert target.temporary_hp==max(0,temporary-damage)
    assert (target.concentration is None)==(dc is not None)


@pytest.mark.parametrize('final,dc',[(0,None),(12,10),(22,11)])
def test_check_uses_final_reduced_damage_not_raw_amount(monkeypatch,final,dc):
    install(monkeypatch,'final_damage',lambda *args:{'amount':final})
    e=duel([]);target=e.state.actors[ME]
    e._start_concentration(target,'test:concentration')
    target.temporary_hp=50
    e._commit_damage(target,40,'UNTYPED','test:damage',FOE,None,reaction_depth=0)
    assert [ev.payload['dc'] for ev in e.events if ev.event_type=='SAVE_ROLLED']==([] if dc is None else [dc])


def test_table_absorbed_damage_records_failed_check_and_replays(tmp_path,monkeypatch):
    combat,table,mid=table_fight(tmp_path,[])
    def hit(engine):
        target=engine.state.actors[LEFT]
        engine._start_concentration(target,'test:concentration')
        engine._grant_temp_hp(target,50,'test:buffer',LEFT)
        script(engine,[1])
        engine._commit_damage(target,40,'UNTYPED','test:damage',RIGHT,None,reaction_depth=0)
    on_hold(monkeypatch,hit)
    assert act(table,mid,HOLD)['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    target=loaded.engine.state.actors[LEFT]
    assert target.current_hp==target.maximum_hp and target.temporary_hp==10
    assert target.concentration is None
    assert [ev.payload['dc'] for ev in loaded.engine.events if ev.event_type=='SAVE_ROLLED']==[20]
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'

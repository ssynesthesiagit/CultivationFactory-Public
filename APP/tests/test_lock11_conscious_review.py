"""Separate zero-HP episodes, initial overkill and willing Stone Womb targets."""
import pytest
from combat import typed_executor as te
from combat.ext import life_state, stone_womb
from combat.gate5_service import CombatService
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT
from tests.test_lock2_persistence import act
from tests.test_lock9_conscious_zero import source_provider, INDOMITABLE
from tests.r10_fixup_support import cast_sender, commit


def loaded(tmp_path,mid):
    session=CombatService(ROOT,tmp_path)._load_session(mid)
    assert session.verify()['status']==session.mechanical.replay()['status']=='PASS'
    return session.engine


def hurt(e,amount):
    e._commit_damage(e.state.actors[H.LEFT],amount,'FORCE','test:damage',H.RIGHT,e._active_intent,reaction_depth=0)


def test_table_healing_starts_a_new_conscious_failure_episode(monkeypatch,tmp_path):
    combat,table,mid=H.table_fight(tmp_path,[INDOMITABLE])
    source_provider(monkeypatch,INDOMITABLE)
    def phases(e):
        actor=e.state.actors[H.LEFT];phase=actor.turn_flags.get('test:phase',0)
        if phase==0:
            hurt(e,actor.current_hp);hurt(e,1);hurt(e,1)
        elif phase==1:
            action=next(a for a in e.action_catalog.values() if a.owner_id==H.LEFT)
            te.block_healing(te.Context(e,actor,action,e._active_intent,{},[actor],actor),{'flat':4,'applies_to':'target'})
            assert actor.life_state is None and life_state._record(actor)['bad']==0
            hurt(e,4);hurt(e,1)
        else:
            life_state.fall_unconscious(e,actor,'test:expired')
        actor.turn_flags['test:phase']=phase+1
    H.on_hold(monkeypatch,phases)
    for expected,state in [(2,'CONSCIOUS'),(1,'CONSCIOUS'),(1,'DYING')]:
        assert act(table,mid,H.HOLD)['status']=='COMMITTED'
        actor=loaded(tmp_path,mid).state.actors[H.LEFT]
        assert actor.active and actor.life_state==state and life_state._record(actor)['bad']==expected


@pytest.mark.parametrize('excess,alive',[(0,True),(-1,True),(0,False)])
def test_table_initial_conscious_drop_obeys_massive_damage(monkeypatch,tmp_path,excess,alive):
    combat,table,mid=H.table_fight(tmp_path,[INDOMITABLE],ally_talents=[])
    source_provider(monkeypatch,INDOMITABLE)
    def drop(e):
        actor=e.state.actors[H.LEFT]
        extra=0 if alive and excess==0 else actor.maximum_hp+excess
        hurt(e,actor.current_hp+extra)
    H.on_hold(monkeypatch,drop)
    assert act(table,mid,H.HOLD)['status']=='COMMITTED'
    e=loaded(tmp_path,mid); actor=e.state.actors[H.LEFT]
    assert actor.active is alive
    assert actor.life_state==('CONSCIOUS' if alive else None)
    if not alive:
        assert any(ev.event_type=='ENTITY_DEFEATED' and ev.actor_id==H.LEFT for ev in e.events)


def test_table_stone_womb_accepts_conscious_zero_ally_and_pays(monkeypatch,tmp_path):
    feature=stone_womb.STONE_WOMB
    combat,table,mid=H.table_fight(tmp_path,[feature],ally_talents=[INDOMITABLE])
    # The ally's printed conscious clause is supplied through the same native
    # zero-HP seam; the complete ability remains the rider lane's responsibility.
    from tests.test_lock_choices import install
    install(monkeypatch,'zero_hp',lambda e,target,*args:'CONSCIOUS' if target.entity_id==H.ALLY else None)
    H.on_hold(monkeypatch,lambda e:e._commit_damage(e.state.actors[H.ALLY],e.state.actors[H.ALLY].current_hp,
        'FORCE','test:drop',H.RIGHT,e._active_intent,reaction_depth=0))
    assert act(table,mid,H.HOLD)['status']=='COMMITTED'
    e=loaded(tmp_path,mid); before=e.state.actors[H.LEFT].resources.copy()
    assert e.state.actors[H.ALLY].life_state=='CONSCIOUS'
    commit(cast_sender(combat,table,mid,'Stone Womb Preservation',target=H.ALLY))
    e=loaded(tmp_path,mid); actor=e.state.actors[H.LEFT]; ally=e.state.actors[H.ALLY]
    assert any(c.condition_id==stone_womb.SHELL for c in ally.conditions.values())
    assert sum(before.values())>sum(actor.resources.values())
    assert not actor.action_available

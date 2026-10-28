"""Sol review 4F20R fixes for the Orbiting Shield Warden.

Finding 1/2: the Imprisoning Earth success rider names an engine-swept expiry and is removed
at the end of the Warden's next turn, proven by advancing real turns and cold reloads.
Finding 4: placement drafts are attributed to the feature that owns them.
Finding 5: the placement search's vertical bounds are pinned to the grid's real extent.
"""
import pytest
from combat.gate5_service import CombatService
from combat.journey import JourneyStore
from tests import r1i_service_support as s
from tests.h1_support import ROOT, sheet
from combat.factory_compiler import compile_character
from combat.ext import orbiting_shield_warden as w


def cold(tmp_path,mid):
    session=CombatService(ROOT,tmp_path)._load_session(mid)
    assert session.verify()['status']=='PASS'
    assert session.mechanical.replay()['status']=='PASS'
    return session.engine


def test_successful_prison_save_expires_at_end_of_wardens_next_turn_and_restores_speed(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,list(w.LEVELS),owner_cl=18,owner_dc=1,wide=True)
    commit(s.candidate(table,mid,'Nine Shields: Imprisoning Earth',s.FOE))
    engine=cold(tmp_path,mid)
    boundary=int(engine.state.actors[s.OWNER].turns_started)+1
    foe=engine.state.actors[s.FOE]
    assert any(m.target_field=='speed_halved' and m.expires_on==f'END_OF_SOURCE_TURN_AT:{boundary}'
               and m.source_actor_id==s.OWNER for m in foe.modifiers.values())
    assert any(c.condition_id==w.SLOWED and c.expires_on==f'END_OF_SOURCE_TURN_AT:{boundary}'
               for c in foe.conditions.values())
    for _ in range(40):
        engine=cold(tmp_path,mid)
        owner=engine.state.actors[s.OWNER]
        foe=engine.state.actors[s.FOE]
        if not any(c.condition_id==w.SLOWED for c in foe.conditions.values()):
            # Gone only once the Warden's next turn has actually run to its end.
            assert owner.turns_started>=boundary
            break
        # Still halved: it must not outlive that turn.
        assert owner.turns_started<=boundary
        assert engine._effective_speed(foe)==15
        commit(table.state(mid)['menu']['end_turn'])
    else:
        raise AssertionError('successful-save Speed halving never expired')
    assert not any(m.target_field=='speed_halved' for m in foe.modifiers.values())
    assert engine._effective_speed(foe)==30
    assert not any(c.condition_id==w.PRISON for c in foe.conditions.values())


@pytest.mark.parametrize('mode,expected',[('move','RAISE'),('constellation','CONSTELLATION')])
def test_placement_draft_event_names_the_feature_that_owns_it(tmp_path,mode,expected):
    bundle=compile_character(sheet([w.RAISE,w.CONSTELLATION],cl=10),actor_id=s.OWNER)
    combat=CombatService(ROOT,tmp_path/'combat')
    arena=combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    store=JourneyStore(tmp_path/'journeys')
    state=store.create([bundle],arena,{s.OWNER:{'x':3,'y':6}},{s.OWNER:3000})
    jid=state['journey_id']
    if mode=='move':
        state=store.act(jid,state['revision'],s.OWNER,'warden_manifest',{'points':[{'x':3,'y':5}]})
    state=store.act(jid,state['revision'],s.OWNER,'warden_begin',{'mode':mode})
    events=[e for e in store.load(jid).state['events'] if e['kind']=='WARDEN_PLACEMENT_CHOICE']
    assert events and events[-1]['source']==getattr(w,expected)
    assert events[-1]['choice']['mode']==mode


def test_placement_search_vertical_bounds_are_floor_clamped_and_radius_limited(tmp_path):
    """Pins current geometry: SquareGrid has no vertical extent, so the search is clamped at the
    floor (z >= 0) and otherwise bounded by its own radius window (start.z + feet//5)."""
    from combat.gate2_runtime_models import Position
    bundle=compile_character(sheet([w.RAISE],cl=3),actor_id=s.OWNER)
    combat=CombatService(ROOT,tmp_path/'combat')
    arena=combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    store=JourneyStore(tmp_path/'journeys')
    state=store.create([bundle],arena,{s.OWNER:{'x':3,'y':6}},{s.OWNER:3000})
    session=store.load(state['journey_id'])
    cells=w.journey_locations(session,s.OWNER,Position(x=3,y=6,z=0),30,initial=True)
    assert cells
    assert min(p.z for p in cells)>=0
    assert max(p.z for p in cells)<=0+30//5

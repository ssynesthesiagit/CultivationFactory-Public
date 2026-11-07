"""Size changes reconcile real zone triggers and describe their source to players."""
from copy import deepcopy
import pytest
from combat import dynamic_size, zones
from combat.gate2_runtime_models import Position, ZoneState
from combat.gate5_service import CombatService
from combat.history_feed import format_history_feed
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT, duel, ME
from tests.test_lock2_persistence import act
from tests.test_lock10_growth import TITAN, ONI


def record_zone(engine, source, cell, profile, name):
    zone = ZoneState(zone_id='zone:test:'+name, source_definition_id=source,
        owner_id=H.LEFT, center=cell, radius_cells=0, affected_cells=(cell,),
        concentration_link=False, duration_rounds=None, created_round=engine.state.round_number,
        trigger_profile={'kind':'TYPED', **profile})
    engine.state.zones[zone.zone_id] = zone
    engine._append_event('ZONE_CREATED',source,actor_id=H.LEFT,payload={'zone':zone.model_dump(mode='json')})
    return zone


@pytest.mark.parametrize('relocate', [False, True])
@pytest.mark.parametrize('attached', ['follows_owner','anchor_id'])
def test_table_growth_enters_terrain_follows_areas_and_shrink_clears_inside(monkeypatch,tmp_path,relocate,attached):
    real_sheet=H.sheet
    monkeypatch.setattr(H,'sheet',lambda *a,**kw:real_sheet(*a,**kw,primary='Stamina'))
    combat,table,mid=H.table_fight(tmp_path,[TITAN,'TAL_MAGMA_MOLTEN_GROUND'])
    hazard=Position(x=3,y=3) if relocate else Position(x=4,y=4)
    def setup(e):
        if 'zone:test:hazard' in e.state.zones:
            return
        if not relocate:
            for who,x in [(H.RIGHT,9),(H.ALLY,8)]:
                actor=e.state.actors[who]; before=actor.position; actor.position=Position(x=x,y=6)
                e._append_event('MOVEMENT_COMMITTED','test:setup',actor_id=who,payload={
                    'destination':actor.position.model_dump(mode='json'),
                    'path':[before.model_dump(mode='json'),actor.position.model_dump(mode='json')],'cost_ft':0})
        action=next(a for a in e.action_catalog.values() if a.owner_id==H.LEFT and a.display_name=='Molten Ground')
        typed=action.parameters['typed']; spec=deepcopy(typed['zone_spec'])
        spec['numbers']=typed['numbers']
        spec['inside']=[{'id':'test:inside','name':'Inside the test area','who':'any','rule':{}}]
        record_zone(e,action.source_definition_id,hazard,spec,'hazard')
        record_zone(e,action.source_definition_id,e.state.actors[H.LEFT].position,
            {'name':'Attached area','shape':'sphere','size_ft':5,'inside':[],
             attached:True if attached=='follows_owner' else H.LEFT},'attached')
        zones.sync_inside(e)
    H.on_hold(monkeypatch,setup)
    assert act(table,mid,H.HOLD)['status']=='COMMITTED'
    e=combat._load_session(mid).engine; before=e.state.actors[H.LEFT].position
    budget=e.state.actors[H.LEFT].movement_remaining_ft; reaction=e.state.actors[H.RIGHT].reaction_available
    seq=e.state.event_sequence
    source=next(g['source_definition_id'] for g in table.state(mid)['menu']['actions'] if TITAN in g['source_definition_id'])
    assert act(table,mid,source)['status']=='COMMITTED'
    fresh=CombatService(ROOT,tmp_path)._load_session(mid); e=fresh.engine; actor=e.state.actors[H.LEFT]
    assert (actor.position!=before) is relocate
    assert actor.position==(Position(x=2,y=3) if relocate else before)
    assert e.state.zones['zone:test:attached'].center==actor.position
    assert any(c.condition_id==zones.ZONE_EFFECT and c.data.get('name')=='Inside the test area' for c in actor.conditions.values())
    events=[ev for ev in e.events if ev.sequence>seq]
    assert len([ev for ev in events if ev.event_type=='PASSIVE_TRIGGERED' and ev.payload.get('moment')=='enter'])==1
    assert any(ev.event_type=='SAVE_ROLLED' and H.LEFT==ev.actor_id for ev in events)
    assert any(ev.event_type=='DAMAGE_COMMITTED' and H.LEFT in ev.target_ids for ev in events)
    assert not any(ev.event_type=='MOVEMENT_COMMITTED' or
                   (ev.event_type=='REACTION_WINDOW_OPENED' and ev.payload.get('checkpoint')=='LEAVE_REACH')
                   for ev in events)
    assert actor.movement_remaining_ft==budget and e.state.actors[H.RIGHT].reaction_available==reaction
    view=next(a for a in table.state(mid)['presentation']['actors'] if a['entity_id']==H.LEFT)
    text=str(view['conditions'])
    assert "Titan's Frame: Large" in text and 'grappling' in text.lower() and 'until round' in text
    feed=format_history_feed([ev.model_dump(mode='json') for ev in events],[],pre_state={},post_state={},
        actor_names={H.LEFT:'Left'},definition_names={source:"Titan's Frame"})
    # Grappling is described by the source-owned condition above. Footprint
    # history records the actual size; carrying capacity is a separate benefit.
    assert "Titan's Frame" in str(feed) and 'is now Large and occupies its new space' in str(feed)
    assert 'carrying, dragging, lifting and pushing' in str(feed)
    assert fresh.verify()['status']==fresh.mechanical.replay()['status']=='PASS'
    # Hold Position is once per turn (hunt170), so the shrink rides the next
    # accepted Hold of Left's own following turn instead of a second one now.
    assert act(table,mid,'end')['status']=='COMMITTED'
    while table.state(mid)['menu']['actor_id']!=H.LEFT:
        assert act(table,mid,'end')['status']=='COMMITTED'
    def shrink(e):
        a=e.state.actors[H.LEFT]
        for key,c in list(a.conditions.items()):
            if c.condition_id==dynamic_size.CONDITION:
                del a.conditions[key]
                e._append_event('CONDITION_REMOVED',c.source_definition_id,actor_id=H.LEFT,target_ids=(H.LEFT,),
                    payload={'instance_id':key,'condition_id':c.condition_id})
    H.on_hold(monkeypatch,shrink)
    assert act(table,mid,H.HOLD)['status']=='COMMITTED'
    fresh=CombatService(ROOT,tmp_path)._load_session(mid); actor=fresh.engine.state.actors[H.LEFT]
    assert actor.transformed_size_category is None
    assert not any(c.condition_id==zones.ZONE_EFFECT for c in actor.conditions.values())
    assert fresh.verify()['status']==fresh.mechanical.replay()['status']=='PASS'


def test_surface_bound_ground_keeps_every_creature_in_scope():
    """A ground hazard (printed "Area: ... on a surface") catches its creator too.

    The harmful-area default is enemies-only, but terrain is the battlefield
    itself: Molten Terrain's own printed text says "When a creature enters...
    it makes a Dexterity saving throw", and Furnace Step exists because your own
    Molten Terrain otherwise deals you its hazard.
    """
    from combat.area_recipients import scoped_area
    effect={'type':'save','applies_to':'creatures_in_area',
            'on_fail':[{'type':'damage','flat':2,'applies_to':'target'}]}
    ground=scoped_area({'shape':'sphere','size_ft':15,'surface_bound':True},[effect])
    assert ground['recipients']=='all' and ground['include_self'] and not ground['exclude_self']
    # The same packet aimed at the battlefield is not ground: it keeps the
    # enemies-only default that the area-recipient ruling established.
    assert scoped_area({'shape':'sphere','size_ft':15},[effect])['recipients']=='hostile'


def test_two_growth_sources_have_distinct_readable_labels():
    e=duel([TITAN,ONI],primary='Stamina'); a=e.state.actors[ME]
    for source in (TITAN,ONI):
        dynamic_size.apply_growth(e,a,'Large',source,source_actor_id=ME,expires_on='UNTIL_REMOVED',functional_steps=1)
    labels={c.data['label'] for c in a.conditions.values() if c.condition_id==dynamic_size.CONDITION}
    assert labels=={"Titan's Frame: Large","Oni Form: Large"}

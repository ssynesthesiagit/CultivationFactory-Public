"""THROWAWAY lock11 debug trace (MAINREDLOCK11B). Not a regression test. Delete before commit."""
import os, sys, tempfile, pathlib, json
from copy import deepcopy
import pytest
from combat import dynamic_size, zones, movement_budget, hold_position
from combat.gate2_runtime_models import Position, ZoneState
from combat.gate5_service import CombatService
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT
from tests.test_lock2_persistence import act
from tests.test_lock10_growth import TITAN

LINES = []

def P(*a):
    s = ' '.join(str(x) for x in a)
    if s.startswith('turn_allowance') or s.startswith('hold claim') or s.startswith('pre '): return
    LINES.append(s[:150])

def record_zone(engine, source, cell, profile, name):
    zone = ZoneState(zone_id='zone:test:'+name, source_definition_id=source,
        owner_id=H.LEFT, center=cell, radius_cells=0, affected_cells=(cell,),
        concentration_link=False, duration_rounds=None, created_round=engine.state.round_number,
        trigger_profile={'kind':'TYPED', **profile})
    engine.state.zones[zone.zone_id] = zone
    engine._append_event('ZONE_CREATED',source,actor_id=H.LEFT,payload={'zone':zone.model_dump(mode='json')})
    return zone

@pytest.mark.parametrize('k', range(8))
def test_trace_lock11(monkeypatch,tmp_path,k):
    _body(monkeypatch,tmp_path)
    blob = ' || '.join(LINES)
    pytest.fail('TRACE%d ' % k + blob[k*400:(k+1)*400], pytrace=False)

def _body(monkeypatch,tmp_path):
    LINES.clear()
    real_sheet=H.sheet
    monkeypatch.setattr(H,'sheet',lambda *a,**kw:real_sheet(*a,**kw,primary='Stamina'))
    combat,table,mid=H.table_fight(tmp_path,[TITAN,'TAL_MAGMA_MOLTEN_GROUND'])
    hazard=Position(x=4,y=4)
    _orig_gc = zones.geometry_changed
    def gc(engine, actor, prev):
        P('geometry_changed', actor.entity_id, 'prev', prev, 'now', {z.zone_id: zones._inside(engine, actor, z) for z in zones.typed_zones(engine)}, 'pos', actor.position)
        return _orig_gc(engine, actor, prev)
    monkeypatch.setattr(zones,'geometry_changed',gc)
    _orig_fire = zones._fire
    _orig_app = zones._applies
    def app(engine, zone, creature, trigger, **kw):
        r = _orig_app(engine, zone, creature, trigger, **kw)
        if zone.zone_id=='zone:test:hazard' and r is False:
            from combat import ext as _ext
            _ext._load()
            from combat.area_recipients import delayed_area_context as _dac
            _c = _dac(engine, zone, trigger.get('effects') or [trigger])
            P('CTX', str((_c or {}).get('area',{}).get('harmful_recipient_override')), str((_c or {}).get('area',{}).get('harmful_recipients')), str(_c.keys() if _c else None), 'ZT', str(zone.trigger_profile.get('source_profile'))[:80])
            from combat.effect_harm import classify_effect as _ce
            P('EFF', [(row.get('type'), row.get('applies_to'), _ce(row, ignore_self=True)) for row in (trigger.get('effects') or [trigger])][:6])
            P('RS', str(_ext.run_strict('zone_recipient_allowed', engine, zone, creature, trigger))[:200])
            P('SEL', [getattr(fn,'__module__','')+'.'+getattr(fn,'__name__','') for fn in _ext._selected('zone_recipient_allowed', (engine, zone, creature, trigger))])
            P('ZS', str(__import__('combat.zone_subjects', fromlist=['x']).allowed(engine, zone, creature, trigger)))
            for fn in list(_ext._selected('zone_recipient_allowed', (engine, zone, creature, trigger))):
                try:
                    out = fn(engine, zone, creature, trigger)
                except Exception as exc:
                    out = 'EXC %r' % exc
                if out is not None: P('HOOK', getattr(fn,'__module__',''), getattr(fn,'__name__',''), out)
        if zone.zone_id=='zone:test:hazard': P('applies', trigger.get('id'), trigger.get('on'), r, 'subj', zones.subject_allowed(engine, zone, creature), 'who', trigger.get('who'), 'hostile', zones._hostile(engine, zone, creature), 'owner', zone.owner_id)
        return r
    monkeypatch.setattr(zones,'_applies',app)
    _orig_rt = zones._run_trigger
    def rt(engine, zone, creature, trigger, moment):
        P('run_trigger', zone.zone_id, moment, 'marks', str(zones._runtime_marks(zone, creature))[:100])
        return _orig_rt(engine, zone, creature, trigger, moment)
    monkeypatch.setattr(zones,'_run_trigger',rt)
    def fire(engine, zone, creature, moment):
        P('_fire trig_count', len(zone.trigger_profile.get('triggers') or []), 'keys', list(zone.trigger_profile.keys()))
        P('_fire', zone.zone_id, creature.entity_id, moment, 'active', creature.active, 'clear', zones.clear_sighted(engine, zone, creature), 'turn_key', zones._turn_key(engine), 'marks', str(dict(zones._runtime_marks(zone, creature)))[:120])
        return _orig_fire(engine, zone, creature, moment)
    monkeypatch.setattr(zones,'_fire',fire)
    _orig_sm = movement_budget.speed_changed
    def sm(engine, actor, change, source, **kw):
        P('speed_changed', actor.entity_id, 'change', change, 'source', source, kw, 'mv', actor.movement_remaining_ft, 'current', engine.state.current_actor_id)
        return _orig_sm(engine, actor, change, source, **kw)
    monkeypatch.setattr(movement_budget,'speed_changed',sm)
    _orig_ta = movement_budget.turn_allowance
    def ta(engine, actor, speed):
        P('turn_allowance', actor.entity_id, 'speed', speed, 'mv', actor.movement_remaining_ft)
        return _orig_ta(engine, actor, speed)
    monkeypatch.setattr(movement_budget,'turn_allowance',ta)
    _orig_claim = hold_position.claim
    def claim(engine, actor):
        P('hold claim', actor.entity_id, 'turns_started', actor.turns_started, 'flags', actor.turn_flags)
        return _orig_claim(engine, actor)
    monkeypatch.setattr(hold_position,'claim',claim)
    def setup(e):
        if 'zone:test:hazard' in e.state.zones:
            return
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
            {'name':'Attached area','shape':'sphere','size_ft':5,'inside':[],'anchor_id':H.LEFT},'attached')
        zones.sync_inside(e)
    H.on_hold(monkeypatch,setup)
    P('HOLD', act(table,mid,H.HOLD)['status'])
    e=combat._load_session(mid).engine; a0=e.state.actors[H.LEFT]
    P('pre pos', a0.position, 'budget', a0.movement_remaining_ft, 'speed', e._effective_speed(a0), 'turns_started', a0.turns_started, 'flags', a0.turn_flags, 'current', e.state.current_actor_id)
    P('pre hazard per_turn', e.state.zones['zone:test:hazard'].per_turn_triggered, 'pre conditions', [(c.condition_id, c.data) for c in a0.conditions.values()])
    seq=e.state.event_sequence
    source=next(g['source_definition_id'] for g in table.state(mid)['menu']['actions'] if TITAN in g['source_definition_id'])
    P('GROWTH source', source[-30:])
    P('growth status', act(table,mid,source)['status'])
    fresh=CombatService(ROOT,tmp_path)._load_session(mid); e=fresh.engine; actor=e.state.actors[H.LEFT]
    P('post pos', actor.position, 'budget', actor.movement_remaining_ft, 'speed', e._effective_speed(actor), 'flags', actor.turn_flags)
    P('post hazard per_turn', e.state.zones['zone:test:hazard'].per_turn_triggered)
    P('post conditions', [(c.condition_id, c.data) for c in actor.conditions.values()])
    events=[ev for ev in e.events if ev.sequence>seq]
    P('EVT-ALL', [ev.event_type for ev in events])
    P('EVENTS after growth:')
    for ev in events:
        if ev.event_type in ('PASSIVE_TRIGGERED','MOVEMENT_GRANTED','CONDITION_APPLIED','CONDITION_REMOVED','ZONE_TRIGGERED','HOLD_POSITION_COMMITTED','ONCE_PER_TURN_CLAIMED') or 'trigger' in ev.event_type.lower():
            P('  ', ev.sequence, ev.event_type, ev.source_definition_id, json.dumps(ev.payload, default=str)[:70])
    P('enter count', len([ev for ev in events if ev.event_type=='PASSIVE_TRIGGERED' and ev.payload.get('moment')=='enter']))

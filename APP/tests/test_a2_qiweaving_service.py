"""Printed Qiweaving effects through CombatService table/session commits and cold replay."""
import pytest
from combat.gate5_service import CombatService
from combat.canonical import canonical_sha256
from tests.h1_support import ROOT
from tests import r1i_service_support as s
from combat.ext.qiweaving_second_pass import GATE

CALM = 'insight.calm-hands-clear-current'
GENTLE = 'TAL_QIWEAVING_GENTLE_MODULATION'
STABLE = 'TAL_QIWEAVING_STABLE_MODULATION'


def cold(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def resolve(combat, table, mid, cid, choices=None, use_reroll=True):
    choices = choices or {}
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    answers, prompts = [], []
    for _ in range(20):
        menu = table.state(mid)['menu']
        result = table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, answers)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
        p = result['reaction']; prompts.append(p)
        feature = p['context']['reaction_source_id']
        ids = choices.get(feature)
        answer = {**p['context'], 'selection': 'DECLINE'}
        if ids is not None:
            answer.update(selection='USE', option_ids=ids)
        elif 'Calm Hands' in str(p) and use_reroll:
            answer['selection'] = 'USE'
        elif p.get('choice') and not p['choice'].get('allow_decline'):
            count = p['choice'].get('minimum_selections', 1)
            answer.update(selection='USE', option_ids=[o['id'] for o in p['choice']['options']][:count])
        answers.append(answer)
    raise AssertionError('Too many prompts')


def area_candidate(table, mid, label):
    groups = [g for g in table.state(mid)['menu']['actions'] if g['label'] == label]
    assert groups, [g['label'] for g in table.state(mid)['menu']['actions']]
    return next(o['candidate_id'] for o in groups[0]['options'] if o.get('destination') and
                o['destination']['x'] == 4 and o['destination']['y'] == 6)


@pytest.mark.parametrize('protected', [[], [s.FOE], [s.FOE, s.SECOND]])
def test_gentle_selected_creatures_auto_save_and_take_no_half_damage(tmp_path, protected):
    combat, table, mid, send, commit = s.fixture(tmp_path, ['FIRE_TAL_FIREBALL_ART', GENTLE], wide=True)
    engine = cold(tmp_path, mid)
    action = next(a for a in engine.action_catalog.values() if a.display_name == 'Fireball Art + Gentle Modulation')
    assert action.parameters['typed']['chosen_save_protection']
    before = {a: engine.state.actors[a].current_hp for a in (s.FOE, s.SECOND)}
    resource = engine.state.actors[s.OWNER].resources['resource:core.qi']
    prompts = resolve(combat, table, mid, area_candidate(table, mid, action.display_name),
                      {'choice:needle.gentle_modulation': protected})
    assert sum('gentle_modulation' in p['context']['reaction_source_id'] for p in prompts) == 1
    engine = cold(tmp_path, mid)
    for who in (s.FOE, s.SECOND):
        actor = engine.state.actors[who]
        assert (actor.current_hp == before[who]) == (who in protected)
        assert not any(c.condition_id == 'condition:typed.burning' for c in actor.conditions.values()) if who in protected else True
        saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == who]
        assert bool(saves) == (who not in protected)
    assert engine.state.actors[s.OWNER].resources['resource:core.qi'] == resource - sum(n for _, n in action.costs)
    assert engine.state.actors[s.OWNER].turn_flags[GATE]
    assert not any(e.event_type == "GM_RIDER" and e.source_definition_id == action.source_definition_id and "Gentle Modulation" in str(e.payload.get("rider", "")) for e in engine.events)


def add_probes(bundles):
    for bundle in bundles:
        aid = bundle['actor_id']
        action = {'source_definition_id': 'test:qw.damage.' + aid, 'display_name': 'Incoming concentration damage',
                  'owner_id': aid, 'economy': 'ACTION', 'resolution_kind': 'TYPED',
                  'target_kind': 'HOSTILE_ENTITY', 'range_ft': 60,
                  'parameters': {'typed': {'source': 'test:qw.damage', 'numbers': {}, 'duration': {'kind': 'instant'},
                   'effects': [{'type': 'damage', 'applies_to': 'target', 'flat': 100, 'damage_types': ['force']}]}}}
        bundle['action_catalog'].append(action);bundle['actor_template']['action_ids'].append(action['source_definition_id'])
        # A free test preparation allows two production Modulations in the same
        # turn; it changes economy only, never the shipped gate/effects/costs.
        for a in bundle['action_catalog']:
            if 'Stable Modulation' in a['display_name'] or a['display_name'] == 'Turbulent Field' or a['display_name'] == 'Fireball Art + Gentle Modulation':
                a['economy'] = 'NONE'
        bundle.pop('bundle_sha256', None);bundle['bundle_sha256'] = canonical_sha256(bundle)


def insight_fixture(monkeypatch, tmp_path, *, owned=True, technique='Turbulent Field'):
    original = s.sheet
    calls = []
    def sheet(mids, **kwargs):
        doc = original(mids, **kwargs)
        if not calls and owned:
            doc.setdefault('spheres_and_talents', {})['cultivation_insight_record_ids'] = [CALM]
        calls.append(1)
        return doc
    monkeypatch.setattr(s, 'sheet', sheet)
    talents = ['TAL_QIWEAVING_TURBULENT_FIELD'] if technique == 'Turbulent Field' else ['TAL_FORCE_FORCE_MANTLE']
    combat, table, mid, send, commit = s.fixture(tmp_path, talents, wide=True, bundle_transform=add_probes)
    resolve(combat, table, mid, s.candidate(table, mid, technique))
    return combat, table, mid, commit


def turn_to(table, mid, commit, who, *, advance=False):
    if advance:commit(table.state(mid)['menu']['end_turn'])
    for _ in range(10):
        if table.state(mid)['menu']['actor_id'] == who:return
        commit(table.state(mid)['menu']['end_turn'])
    raise AssertionError('Turn not reached')


@pytest.mark.parametrize('owned,use,technique,expected', [(True,True,'Turbulent Field',True),
 (True,False,'Turbulent Field',False),(False,True,'Turbulent Field',False),(True,True,'Force Mantle',False)])
def test_calm_hands_failed_concentration_optional_reroll_and_cold_limit(monkeypatch,tmp_path,owned,use,technique,expected):
    combat, table, mid, commit = insight_fixture(monkeypatch,tmp_path,owned=owned,technique=technique)
    cold(tmp_path, mid)
    turn_to(table,mid,commit,s.FOE,advance=True)
    prompts = resolve(combat,table,mid,s.candidate(table,mid,'Incoming concentration damage',s.OWNER),use_reroll=use)
    engine = cold(tmp_path, mid)
    rewrites = [e for e in engine.events if e.event_type == 'D20_REWRITTEN' and e.source_definition_id == CALM]
    assert bool(rewrites) == expected
    assert any('Calm Hands' in str(p) for p in prompts) == (owned and technique=='Turbulent Field')
    assert engine.state.actors[s.OWNER].concentration is None  # DC 50: both initial and new result fail
    if expected:
        turn_to(table,mid,commit,s.OWNER)
        resolve(combat,table,mid,s.candidate(table,mid,technique))
        turn_to(table,mid,commit,s.FOE,advance=True)
        again = resolve(combat,table,mid,s.candidate(table,mid,'Incoming concentration damage',s.OWNER))
        engine = cold(tmp_path,mid)
        assert not any('Calm Hands' in str(p) for p in again)
        assert len([e for e in engine.events if e.event_type=='D20_REWRITTEN' and e.source_definition_id==CALM])==1


def test_apply_modulation_shared_limit_and_next_turn_reset(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,['TAL_QIWEAVING_TURBULENT_FIELD',STABLE,
       'TAL_QIWEAVING_DISTANT_MODULATION','TAL_FORCE_FORCE_MANTLE'],wide=True,bundle_transform=add_probes)
    resolve(combat,table,mid,s.candidate(table,mid,'Turbulent Field + Stable Modulation'))
    engine=cold(tmp_path,mid)
    assert engine.state.actors[s.OWNER].turn_flags[GATE]
    # Every Modulation, including a different modifier on a different sphere,
    # is withheld after the shared turn use; the underlying technique remains.
    labels=[g['label'] for g in table.state(mid)['menu']['actions']]
    assert not any('Modulation' in name for name in labels)
    turn_to(table,mid,commit,s.OWNER,advance=True)
    assert not cold(tmp_path,mid).state.actors[s.OWNER].turn_flags.get(GATE)
    assert any('Stable Modulation' in g['label'] for g in table.state(mid)['menu']['actions'])


def add_unconditional_area_damage(bundles):
    for b in bundles:
        for a in b['action_catalog']:
            if a['display_name'] == 'Fireball Art + Gentle Modulation':
                a['parameters']['typed']['effects'].append({'type':'damage','applies_to':'creatures_in_area',
                   'flat':7,'damage_types':['force'],'evidence':'Test an independent effect with no saving throw.'})
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)


def test_gentle_does_not_protect_no_save_damage_and_only_compiles_for_areas(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,['FIRE_TAL_FIREBALL_ART',GENTLE,'TAL_FORCE_FORCE_MANTLE'],
       wide=True,bundle_transform=add_unconditional_area_damage)
    engine=cold(tmp_path,mid)
    variants=[a for a in engine.action_catalog.values() if a.parameters.get('typed',{}).get('chosen_save_protection')]
    assert variants and all(a.parameters['typed'].get('area') for a in variants)
    hp={a:engine.state.actors[a].current_hp for a in (s.FOE,s.SECOND)}
    resolve(combat,table,mid,area_candidate(table,mid,'Fireball Art + Gentle Modulation'),
       {'choice:needle.gentle_modulation':[s.FOE,s.SECOND]})
    engine=cold(tmp_path,mid)
    assert all(engine.state.actors[a].current_hp==hp[a]-7 for a in hp)


def test_calm_hands_accepts_another_sphere_with_modulation(monkeypatch,tmp_path):
    original=s.sheet;calls=[]
    def sheet(mids,**kwargs):
        doc=original(mids,**kwargs)
        if not calls:doc['spheres_and_talents']['cultivation_insight_record_ids']=[CALM]
        calls.append(1);return doc
    monkeypatch.setattr(s,'sheet',sheet)
    combat,table,mid,send,commit=s.fixture(tmp_path,['TAL_FORCE_FORCE_MANTLE',STABLE],wide=True,bundle_transform=add_probes)
    resolve(combat,table,mid,s.candidate(table,mid,'Force Mantle + Stable Modulation'))
    turn_to(table,mid,commit,s.FOE,advance=True)
    resolve(combat,table,mid,s.candidate(table,mid,'Incoming concentration damage',s.OWNER))
    engine=cold(tmp_path,mid)
    rewrites=[e for e in engine.events if e.event_type=='D20_REWRITTEN' and e.source_definition_id==CALM]
    assert len(rewrites)==1


def test_gentle_has_no_three_technique_presentation_cap(tmp_path):
    talents=['FIRE_TAL_FIREBALL_ART','TAL_FORCE_SHOCKWAVE','TAL_FORCE_COMPRESSION_FIELD',
             'TAL_FORCE_HEAVEN_CRUSHING_PALM',GENTLE]
    combat,table,mid,send,commit=s.fixture(tmp_path,talents,wide=True)
    engine=cold(tmp_path,mid)
    for name in ['Fireball Art','Shockwave','Compression Field','Heaven-Crushing Palm','Conflagration']:
        assert any(a.display_name==name+' + Gentle Modulation' for a in engine.action_catalog.values()),name


@pytest.mark.parametrize('allies', [(), (s.SECOND,)])
def test_automatic_gentle_only_protects_perceived_allies(tmp_path, allies):
    combat, table, mid, send, commit = s.fixture(tmp_path, ['FIRE_TAL_FIREBALL_ART', GENTLE],
        wide=True, allies=allies, positions={s.OWNER:{'x':0,'y':0}, s.FOE:{'x':4,'y':6}, s.SECOND:{'x':5,'y':6}})
    before = cold(tmp_path, mid)
    hp = {who:before.state.actors[who].current_hp for who in (s.FOE,s.SECOND)}
    cid = area_candidate(table, mid, 'Fireball Art + Gentle Modulation')
    s.force_ai_candidate(combat, mid, s.OWNER, cid)
    result = table.auto_step(mid, 0, [])
    assert result['status'] == 'COMMITTED', result
    after = cold(tmp_path, mid)
    for who in hp:
        assert (after.state.actors[who].current_hp == hp[who]) == (who in allies)
        assert bool([e for e in after.events if e.event_type=='SAVE_ROLLED' and e.actor_id==who]) == (who not in allies)


def test_gentle_prompt_names_action_and_explains_success_damage(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,['FIRE_TAL_FIREBALL_ART',GENTLE],wide=True)
    prompts=resolve(combat,table,mid,area_candidate(table,mid,'Fireball Art + Gentle Modulation'),
        {'choice:needle.gentle_modulation':[]})
    prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.gentle_modulation')
    rendered=str(prompt)
    assert 'Fireball Art + Gentle Modulation' in rendered
    assert 'half damage' in rendered and 'no damage' in rendered
    assert prompt['action'] == 'Fireball Art + Gentle Modulation'
    cold(tmp_path,mid)


def test_zone_gentle_activation_roster_survives_cold_delayed_save(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,['TAL_FORCE_COMPRESSION_FIELD',GENTLE],wide=True)
    prompts=resolve(combat,table,mid,s.candidate(table,mid,'Compression Field + Gentle Modulation'),
        {'choice:needle.gentle_modulation':[s.FOE]})
    assert sum(p['context']['reaction_source_id']=='choice:needle.gentle_modulation' for p in prompts)==1
    engine=cold(tmp_path,mid)
    zone=next(z for z in engine.state.zones.values() if z.active)
    saved=zone.trigger_profile['qiweaving_gentle_protection']
    assert saved['recipients']==[s.FOE]
    assert saved['source']==zone.source_definition_id and saved['owner']==s.OWNER
    first=len(engine.events)
    turn_to(table,mid,commit,s.FOE,advance=True)
    engine=cold(tmp_path,mid)
    assert any('automatically succeeds' in str(e.payload) and s.FOE in e.target_ids for e in engine.events[first:])
    assert not any(e.event_type=='SAVE_ROLLED' and e.actor_id==s.FOE for e in engine.events[first:])
    assert not any(m.source_definition_id==zone.source_definition_id and m.target_field=='speed_ft' for m in engine.state.actors[s.FOE].modifiers.values())
    turn_to(table,mid,commit,s.SECOND)
    engine=cold(tmp_path,mid)
    assert any(e.event_type=='SAVE_ROLLED' and e.actor_id==s.SECOND for e in engine.events[first:])


def test_countered_modulation_consumes_accepted_activation_limit(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,['FIRE_TAL_FIREBALL_ART',GENTLE,STABLE],wide=True,
        owner_dc=10,foe_talents=['TAL_QIWEAVING_COUNTERWEAVE'],foe_score=30,bundle_transform=add_probes)
    combat.set_controller_mode(mid,actor_id=s.FOE,controller_mode='LOCAL_AUTO')
    engine=cold(tmp_path,mid)
    hp=engine.state.actors[s.FOE].current_hp
    resolve(combat,table,mid,area_candidate(table,mid,'Fireball Art + Gentle Modulation'),
        {'choice:needle.gentle_modulation':[]})
    engine=cold(tmp_path,mid)
    assert any('the technique is countered' in str(e.payload) for e in engine.events)
    assert engine.state.actors[s.FOE].current_hp==hp
    assert engine.state.actors[s.OWNER].turn_flags[GATE]
    assert not any('Modulation' in g['label'] for g in table.state(mid)['menu']['actions'])


@pytest.mark.parametrize('move_away', [False, True])
def test_protected_zone_success_effects_survive_caster_movement_and_reload(tmp_path, move_away):
    def mobile_owner(bundles):
        # Fixture mobility only: deliver the shipped zone and its saves unchanged.
        owner = next(b for b in bundles if b['actor_id'] == s.OWNER)
        owner['actor_template']['speed_ft'] = 150
        owner.pop('bundle_sha256', None)
        owner['bundle_sha256'] = canonical_sha256(owner)

    combat, table, mid, send, commit = s.fixture(tmp_path,
        ['TAL_FORCE_INVISIBLE_MOUNTAIN', GENTLE], wide=True,
        bundle_transform=mobile_owner)
    name = 'Invisible Mountain + Gentle Modulation'
    resolve(combat, table, mid, s.candidate(table, mid, name),
        {'choice:needle.gentle_modulation': [s.FOE]})
    engine = cold(tmp_path, mid)
    zone = next(z for z in engine.state.zones.values() if z.active)
    hp = engine.state.actors[s.FOE].current_hp
    assert zone.trigger_profile['qiweaving_gentle_protection']['recipients'] == [s.FOE]
    if move_away:
        cid = next(o['candidate_id'] for o in table.state(mid)['menu']['moves']
                   if o['destination'] == {'x': 25, 'y': 0})
        commit(cid)
        engine = cold(tmp_path, mid)
        owner, foe = (engine.state.actors[who] for who in (s.OWNER, s.FOE))
        action = next(a for a in engine.action_catalog.values() if a.display_name == name)
        assert engine._distance_actor_to_actor(owner, foe) > action.range_ft
        assert owner.concentration is not None
        assert engine.state.zones[zone.zone_id].active
    first = len(engine.events)
    turn_to(table, mid, commit, s.FOE, advance=True)
    engine = cold(tmp_path, mid)
    foe = engine.state.actors[s.FOE]
    assert any('automatically succeeds' in str(e.payload) and s.FOE in e.target_ids
               for e in engine.events[first:])
    assert not any(e.event_type == 'SAVE_ROLLED' and e.actor_id == s.FOE
                   for e in engine.events[first:])
    assert foe.current_hp == hp  # Gentle cancels success's half damage.
    penalties = [m for m in foe.modifiers.values()
                 if m.source_definition_id == zone.source_definition_id and m.target_field == 'speed_ft']
    assert len(penalties) == 1 and penalties[0].value == -10
    assert not any(c.condition_id == 'condition:typed.restrained' for c in foe.conditions.values())

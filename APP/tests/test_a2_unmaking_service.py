"""Printed Unmaking safeguards through table/session intents and cold reload."""
import pytest
from combat import ext, unmaking
from combat.ext import unmaking_channels as channels, unmaking_insights as insights
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, script
from tests.test_tabletop_hunt6 import table_fight, LEFT, ALLY, RIGHT
from tests.test_unmaking_auto84f1 import DAGGER, end_turn

WAVE = 'TAL_UNMAKING_RUIN_WAVE'
BASE = ['TAL_UNMAKING_RUIN_CHANNEL', WAVE]


def dispatch(table, mid, needle, select=lambda prompt: None):
    state = table.state(mid)
    group = next(g for g in state['menu']['actions'] if needle in g['source_definition_id'])
    option = next((o for o in group['options'] if o.get('destination') == {'x': 4, 'y': 4, 'z': 0}), group['options'][0])
    answers = []
    for _ in range(12):
        result = table.act(mid, option['candidate_id'], state['menu']['decision_id'],
                           state['menu']['state_version'], state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            return result
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        chosen = select(prompt)
        answers.append({**prompt['context'], 'selection': 'USE' if chosen else 'DECLINE',
                        'option_ids': chosen or []})
    raise AssertionError('too many prompts')


def scripted(monkeypatch, value):
    ext.effects()
    def queue(engine, actor, action):
        if WAVE in action.source_definition_id:
            script(engine, [value] * 100)
    monkeypatch.setitem(ext._HOOKS, 'technique_start', [*ext._HOOKS.get('technique_start', []), queue])
    from tests import test_tabletop_hunt6 as support
    original = support.sheet
    def sheet_with_insights(ids, **kwargs):
        doc = original(ids, **kwargs)
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
        fields = doc.setdefault('spheres_and_talents', {})
        fields['cultivation_insight_record_ids'] = [i for i in ids if i.startswith('insight.')]
        fields['learned_talent_record_ids'] = [i for i in ids if not i.startswith('insight.')]
        return doc
    monkeypatch.setattr(support, 'sheet', sheet_with_insights)


def pick_price(prompt, price, use=True):
    name = str(prompt.get('reaction', ''))
    options = (prompt.get('choice') or {}).get('options') or []
    if 'Initiate' in name:
        return [r['id'] for r in options] if use else []
    return [r['id'] for r in options if price in r['label']][:1]


def cold(tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == 'PASS'
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine


@pytest.mark.parametrize('use', [True, False])
def test_initiate_optional_first_strain_commits_and_reloads(tmp_path, monkeypatch, use):
    scripted(monkeypatch, 1)
    combat, table, mid = table_fight(tmp_path, [*BASE, insights.INITIATE], ally_talents=[])
    start = cold(tmp_path, mid).state.actors[LEFT].current_hp
    prompts = []
    def select(prompt):
        prompts.append(prompt)
        return pick_price(prompt, 'Gain 1 Black Vein Strain', use)
    dispatch(table, mid, WAVE, select)
    initiate = next(p for p in prompts if p['reaction'] == 'Black-Vein Initiate')
    assert initiate['action'] == 'Ruin Wave'
    assert initiate['affected'] == 'Left' and initiate['trigger_actor'] == 'Left'
    assert 'Ruin Wave' in initiate['moment']
    engine = cold(tmp_path, mid)
    me = engine.state.actors[LEFT]
    assert me.resources[unmaking.STRAIN] == (0 if use else 1)
    payments = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == insights.INITIATE]
    assert len(payments) == int(use)
    if use:
        assert payments[0].payload['hp_damage'] == 4 and payments[0].target_ids == (LEFT,)
    assert any(c.condition_id == insights.USED for c in me.conditions.values()) == use
    # A retained once-per-scene receipt survives turn reset and another activation.
    for _ in range(6):
        assert end_turn(table, mid)['status'] == 'COMMITTED'
        if table.state(mid)['menu']['actor_id'] == LEFT:
            break
    dispatch(table, mid, WAVE, lambda p: pick_price(p, 'Gain 1 Black Vein Strain', True))
    later = cold(tmp_path, mid).state.actors[LEFT]
    assert later.resources[unmaking.STRAIN] == (1 if use else 2)
    assert len([e for e in cold(tmp_path, mid).events if e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == insights.INITIATE]) == int(use)


@pytest.mark.parametrize('cl,die,expected', [(9,4,1),(9,5,0),(10,4,0),(10,3,1)])
def test_grip_first_crack_threshold_and_reload(tmp_path, monkeypatch, cl, die, expected):
    scripted(monkeypatch, die)
    combat, table, mid = table_fight(tmp_path, [*BASE, insights.GRIP], ally_talents=[], kit=DAGGER, cl=cl)
    dispatch(table, mid, WAVE, lambda p: pick_price(p, 'gains 1 Crack'))
    engine = cold(tmp_path, mid)
    me = engine.state.actors[LEFT]
    assert sum(channels.cracked_channels(me).values()) == expected
    rolls = [r for r in engine.rolls if r.reason.startswith('RUIN_SAFE_GRIP:')]
    assert len(rolls) == 1 and rolls[0].total == die
    assert not any(r.reason.startswith('RUIN_SAFE_GRIP:') and r.actor_id != LEFT for r in engine.rolls)
    receipts = [e.payload.get('rider', '') for e in engine.events
                if e.event_type == 'GM_RIDER' and 'gains 1 Crack' in e.payload.get('rider', '')]
    assert receipts and all('selected price before safeguards' in text for text in receipts)
    if not expected:
        assert any('avoids its first Crack' in str(e.payload) for e in engine.events)


@pytest.mark.parametrize('owned,defenses,expected,ordinary', [
    (True,{},20,10), (False,{},10,10),
    (True,{'resist':['force']},10,5),
    (True,{'vulnerable':['force']},20,20),
    (True,{'immune':['force']},0,0),
    (True,{'threshold':11},0,0),
])
def test_field_object_vulnerability_is_local_owned_and_nonpersistent(tmp_path, owned, defenses, expected, ordinary):
    from tests.auto_worker1_support import fight, act, resolve, turn, cell_send, LEFT as ME, RIGHT as FOE
    from combat.ext import objects
    field = 'TAL_UNMAKING_HOLLOWING_FIELD'
    trace = 'TAL_UNMAKING_BLACK_TRACE'
    def yard(arena):
        arena['map_objects'] = [
            {'id':1,'kind':'crate','x':5,'y':5,'material':'stone','hp':1000,'threshold':0,'blocks':False,'unattended':True, **defenses},
            {'id':2,'kind':'crate','x':12,'y':5,'material':'stone','hp':1000,'threshold':0,'blocks':False,'unattended':True}]
    # A fixed packet is sealed before match creation to isolate native defenses.
    # Its source/sphere are the user's actual Unmaking talent; another source
    # and another owner are separately exercised below.
    def bundle_edit(bundle):
        for a in bundle['action_catalog']:
            if a['display_name'] == 'Prepare':
                a['parameters']['typed'].update(sphere=unmaking.UNMAKING)
    combat, table, mid = fight(tmp_path, [trace, *([field] if owned else [])],
        prepare=[{'type':'object_damage','flat':10,'damage_types':['force']}],
        prepare_target='OBJECT', prepare_source=trace, arena_edit=yard, bundle_edit=bundle_edit,
        cause=[{'type':'object_damage','flat':10,'damage_types':['force']}], cause_target='OBJECT')
    if owned:
        resolve(cell_send(table, mid, 'Hollowing Field', (5,5)))
    engine = CombatService(ROOT,tmp_path)._load_session(mid).engine
    inside = next(o for o in engine.state.objects.values() if o.position.x == 5)
    outside = next(o for o in engine.state.objects.values() if o.position.x == 12)
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=inside.object_id))
    loaded = CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    updated = loaded.engine.state.objects[inside.object_id]
    assert updated.current_hp == 1000 - expected
    assert updated.component == inside.component
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=outside.object_id))
    assert CombatService(ROOT,tmp_path)._load_session(mid).engine.state.objects[outside.object_id].current_hp == 990
    turn(table,mid,FOE)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=inside.object_id))
    loaded = CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.engine.state.objects[inside.object_id].current_hp == 1000 - expected - ordinary
    assert loaded.verify()['status'] == 'PASS' and loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('summoned', [True, False])
def test_field_construct_vulnerability_survives_reload_and_stays_in_area(tmp_path, summoned):
    from tests.auto_worker1_support import fight, act, resolve, cell_send, LEFT as ME, RIGHT as FOE
    field = 'TAL_UNMAKING_HOLLOWING_FIELD'
    trace = 'TAL_UNMAKING_BLACK_TRACE'
    def sheet_edit(doc, aid):
        if aid == FOE:
            doc['identity']['creature_types'] = ['construct']
    def bundle_edit(bundle):
        if bundle['actor_id'] == FOE and summoned:
            for servant in bundle['summons']:
                servant['summon']['arrives'] = 'start'
        for a in bundle['action_catalog']:
            if a['display_name'] == 'Prepare':
                a['parameters']['typed'].update(sphere=unmaking.UNMAKING)
    combat, table, mid = fight(tmp_path, [field, trace],
        prepare=[{'type':'damage','flat':10,'damage_types':['force'],'applies_to':'target'}],
        prepare_source=trace, sheet_edit=sheet_edit, bundle_edit=bundle_edit,
        right_talents=['tianxia.talent.ink.painted_beast'] if summoned else [])
    resolve(cell_send(table, mid, 'Hollowing Field', (4,6)))
    engine = CombatService(ROOT,tmp_path)._load_session(mid).engine
    target = next(a.entity_id for a in engine.state.actors.values() if a.summon) if summoned else FOE
    before = engine.state.actors[target].current_hp
    resolve(lambda a: act(table,mid,'Prepare',a,target_id=target))
    loaded = CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[target].current_hp == before - (20 if summoned else 10)
    assert loaded.verify()['status'] == 'PASS' and loaded.mechanical.replay()['status'] == 'PASS'


def test_ai_initiate_replaces_only_owners_strain_with_both_sides_in_range(tmp_path, monkeypatch):
    from tests.hunt15_support import action_sender
    scripted(monkeypatch, 1)
    combat, table, mid = table_fight(tmp_path, [*BASE, insights.INITIATE], ally_talents=[])
    result = action_sender(combat, table, mid, WAVE, ai=True)([])
    assert result['status'] == 'COMMITTED', result
    engine = cold(tmp_path,mid)
    assert engine.state.actors[LEFT].resources[unmaking.STRAIN] == 0
    payments = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == insights.INITIATE]
    assert len(payments) == 1 and payments[0].target_ids == (LEFT,)
    assert payments[0].payload['hp_damage'] == 4
    assert engine.state.actors[ALLY].position is not None and engine.state.actors[RIGHT].position is not None



def test_grip_does_not_roll_again_after_channel_has_crack(tmp_path, monkeypatch):
    scripted(monkeypatch, 4)
    combat, table, mid = table_fight(tmp_path, [*BASE, insights.GRIP], ally_talents=[], kit=DAGGER, cl=9)
    dispatch(table, mid, WAVE, lambda p: pick_price(p, 'gains 1 Crack'))
    assert sum(channels.cracked_channels(cold(tmp_path,mid).state.actors[LEFT]).values()) == 1
    for _ in range(6):
        assert end_turn(table, mid)['status'] == 'COMMITTED'
        if table.state(mid)['menu']['actor_id'] == LEFT:
            break
    dispatch(table, mid, WAVE, lambda p: pick_price(p, 'gains 1 Crack'))
    engine = cold(tmp_path,mid)
    assert sum(channels.cracked_channels(engine.state.actors[LEFT]).values()) == 2
    assert len([r for r in engine.rolls if r.reason.startswith('RUIN_SAFE_GRIP:')]) == 1



def test_field_vulnerability_ends_with_native_concentration_replacement(tmp_path):
    from tests.auto_worker1_support import fight, act, resolve, cell_send
    field = 'TAL_UNMAKING_HOLLOWING_FIELD'
    def yard(arena):
        arena['map_objects'] = [{'id':1,'kind':'crate','x':5,'y':5,'material':'stone',
                                'hp':1000,'threshold':0,'blocks':False,'unattended':True}]
    def bundle_edit(bundle):
        # Seal the legacy one-slot policy to exercise actual replacement;
        # current owner policy otherwise permits multiple held techniques.
        bundle['concentration_rules'] = {'capacity':'cultivation_level','limits_by_cl':[[1,1]]}
        for a in bundle['action_catalog']:
            if a['display_name'] == 'Prepare':
                a['parameters']['typed'].update(sphere=unmaking.UNMAKING)
            if a['display_name'] == 'Replace concentration':
                a['concentration'] = True
                a['parameters']['typed']['duration'] = {'kind':'minutes','amount':1,'concentration':True}
    combat, table, mid = fight(tmp_path,[field],
        prepare=[{'type':'object_damage','flat':10,'damage_types':['force']}], prepare_target='OBJECT',
        extra_actions=[('Replace concentration', {'target_kind':'SELF','effects':[]})],
        arena_edit=yard,bundle_edit=bundle_edit)
    resolve(cell_send(table,mid,'Hollowing Field',(5,5)))
    engine = CombatService(ROOT,tmp_path)._load_session(mid).engine
    oid = next(iter(engine.state.objects))
    resolve(lambda a:act(table,mid,'Prepare',a,target_id=oid))
    assert CombatService(ROOT,tmp_path)._load_session(mid).engine.state.objects[oid].current_hp == 980
    resolve(lambda a:act(table,mid,'Replace concentration',a))
    resolve(lambda a:act(table,mid,'Prepare',a,target_id=oid))
    loaded = CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.engine.state.objects[oid].current_hp == 970
    assert loaded.verify()['status'] == 'PASS' and loaded.mechanical.replay()['status'] == 'PASS'



def test_initiate_does_not_replace_printed_strain_becomes_six(tmp_path):
    from tests.auto_worker1_support import fight, act, resolve, LEFT as ME
    def sheet_edit(doc, aid):
        if aid == ME:
            fields = doc['spheres_and_talents']
            fields['cultivation_insight_record_ids'] = [insights.INITIATE]
            fields['learned_talent_record_ids'] = ['TAL_UNMAKING_RUIN_CHANNEL', 'TAL_UNMAKING_LAST_INCH_CONTROL']
    combat, table, mid = fight(tmp_path, ['TAL_UNMAKING_RUIN_CHANNEL', 'TAL_UNMAKING_LAST_INCH_CONTROL', insights.INITIATE],
        prepare=[{'type':'strain_becomes','value':6}], prepare_target='SELF', sheet_edit=sheet_edit)
    _, prompts = resolve(lambda a:act(table,mid,'Prepare',a))
    loaded = CombatService(ROOT,tmp_path)._load_session(mid)
    me = loaded.engine.state.actors[ME]
    assert me.resources[unmaking.STRAIN] == 6
    assert not any(c.condition_id == insights.USED for c in me.conditions.values())
    assert not any('Initiate' in str(p) for p in prompts)
    assert loaded.verify()['status'] == 'PASS' and loaded.mechanical.replay()['status'] == 'PASS'



def test_manual_initiate_owner_asked_during_ai_action(tmp_path):
    from tests.auto_worker1_support import fight, act, resolve, turn, LEFT as ME, RIGHT as FOE
    from tests.hunt15_support import action_sender
    def sheet_edit(doc, aid):
        if aid == ME:
            doc['spheres_and_talents']['cultivation_insight_record_ids'] = [insights.INITIATE]
    combat, table, mid = fight(tmp_path, [*BASE, insights.INITIATE],
        cause=[{'type':'gain_resource','resource_id':unmaking.STRAIN,'flat':1,'applies_to':'target'}],
        cause_name='Strain transfer', sheet_edit=sheet_edit)
    turn(table, mid, FOE)
    send = action_sender(combat, table, mid, 'Strain transfer', ai=True, target_id=ME)
    paused = send([])
    assert paused['status'] == 'REACTION_REQUIRED', paused
    prompt = paused['reaction']
    assert prompt['reaction'] == 'Black-Vein Initiate'
    assert prompt['action'] == 'Strain transfer'
    assert prompt['affected'] == 'Keeper' and prompt['trigger_actor'] == 'Visitor'
    assert 'Visitor' in prompt['moment'] and 'Keeper' in prompt['moment']
    assert 'End Turn' not in prompt['moment']
    result, prompts = resolve(send, {'choice:needle.black_vein_initiate': []})
    assert result['status'] == 'COMMITTED'
    engine = cold(tmp_path, mid)
    assert engine.state.actors[ME].resources[unmaking.STRAIN] == 1
    assert not any(c.condition_id == insights.USED for c in engine.state.actors[ME].conditions.values())


@pytest.mark.parametrize('invalid', [1, 0.5, True, -1])
def test_channel_reduction_rejects_each_provider_before_next_and_rolls_back(tmp_path, monkeypatch, invalid):
    scripted(monkeypatch, 1)
    combat, table, mid = table_fight(tmp_path, BASE, ally_talents=[], kit=DAGGER)
    before = cold(tmp_path, mid).state.model_dump(mode='json')
    calls = []
    def first(amount, ctx, weapon):
        return 0
    def bad(amount, ctx, weapon):
        assert type(amount) is int and amount == 0
        return invalid
    def downstream(amount, ctx, weapon):
        calls.append(amount)
        return 0
    monkeypatch.setitem(ext._HOOKS, 'channel_crack_amount', [first, bad, downstream])
    from combat.gate5_service import CombatServiceError
    with pytest.raises(CombatServiceError) as rejected:
        dispatch(table, mid, WAVE, lambda p: pick_price(p, 'gains 1 Crack'))
    assert 'channel_crack_amount must retain or reduce' in str(rejected.value.diagnostic.details)
    assert calls == []
    assert cold(tmp_path, mid).state.model_dump(mode='json') == before
    # Retry the same accepted intent with valid composition, including None.
    seen = []
    def valid(amount, ctx, weapon):
        seen.append(amount)
        return None
    monkeypatch.setitem(ext._HOOKS, 'channel_crack_amount', [first, valid])
    dispatch(table, mid, WAVE, lambda p: pick_price(p, 'gains 1 Crack'))
    assert seen and set(seen) == {0}
    assert sum(channels.cracked_channels(cold(tmp_path, mid).state.actors[LEFT]).values()) == 0



def test_same_summoned_construct_boundary_other_caster_and_nonforce(tmp_path):
    from tests.auto_worker1_support import fight, act, resolve, cell_send, turn, LEFT as ME, RIGHT as FOE
    from combat.spatial_areas import zone_contains
    field, trace = 'TAL_UNMAKING_HOLLOWING_FIELD', 'TAL_UNMAKING_BLACK_TRACE'
    def sheet_edit(doc, aid):
        if aid == FOE:
            doc['identity']['creature_types'] = ['construct']
    def bundle_edit(bundle):
        if bundle['actor_id'] == ME:
            bundle['actor_template']['saving_throws']['CON'] = 100
        if bundle['actor_id'] == FOE:
            for servant in bundle['summons']:
                servant['summon']['arrives'] = 'start'
        for a in bundle['action_catalog']:
            if a['display_name'] in ('Prepare', 'Cause', 'Cold packet'):
                a['parameters']['typed'].update(sphere=unmaking.UNMAKING)
    combat, table, mid = fight(tmp_path, [field, trace],
        prepare=[{'type':'damage','flat':1,'damage_types':['force'],'applies_to':'target'}],
        prepare_source=trace, sheet_edit=sheet_edit, bundle_edit=bundle_edit,
        cause=[{'type':'damage','flat':1,'damage_types':['force'],'applies_to':'target'}],
        cause_target='ANY_CREATURE', right_talents=['tianxia.talent.ink.painted_beast', trace],
        extra_actions=[('Cold packet', {'target_kind':'ANY_CREATURE','effects':[
            {'type':'damage','flat':1,'damage_types':['cold'],'applies_to':'target'}]}),
            ('Push out', {'target_kind':'ANY_CREATURE','effects':[
            {'type':'forced_movement','distance_ft':30,'direction':'away','applies_to':'target'}]})])
    resolve(cell_send(table, mid, 'Hollowing Field', (4,6)))
    engine = cold(tmp_path, mid)
    target = next(a.entity_id for a in engine.state.actors.values() if a.summon)
    zone = next(z for z in engine.state.zones.values() if z.active and z.owner_id == ME)
    assert zone_contains(engine, engine.state.actors[target], zone)
    def damage(label, expected):
        before = cold(tmp_path, mid).state.actors[target].current_hp
        resolve(lambda a: act(table, mid, label, a, target_id=target))
        engine = cold(tmp_path, mid)
        assert engine.state.actors[target].current_hp == before - expected
    damage('Prepare', 2)
    damage('Cold packet', 1)
    turn(table, mid, FOE)
    damage('Cause', 1)
    turn(table, mid, ME)
    resolve(lambda a: act(table, mid, 'Push out', a, target_id=target))
    engine = cold(tmp_path, mid)
    assert engine.state.actors[target].position != zone.center
    assert not zone_contains(engine, engine.state.actors[target], zone)
    assert engine.state.zones[zone.zone_id].active
    damage('Prepare', 1)


def test_initiate_upkeep_names_field_instead_of_outer_end_turn(tmp_path):
    from tests.auto_worker1_support import fight, act, resolve, cell_send, LEFT as ME
    def sheet_edit(doc, aid):
        if aid == ME:
            doc['spheres_and_talents']['cultivation_insight_record_ids'] = [insights.INITIATE]
    def bundle_edit(bundle):
        if bundle['actor_id'] == ME:
            bundle['actor_template']['saving_throws']['CON'] = 100
    combat, table, mid = fight(tmp_path, [*BASE, 'TAL_UNMAKING_HOLLOWING_FIELD', insights.INITIATE],
                               sheet_edit=sheet_edit, bundle_edit=bundle_edit)
    resolve(cell_send(table, mid, 'Hollowing Field', (4,6)))
    state = table.state(mid)
    answers, prompts = [], []
    for _ in range(8):
        result = act(table, mid, 'end', answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        chosen = pick_price(prompt, 'Gain 1 Black Vein Strain')
        answers.append({**prompt['context'], 'selection': 'USE' if chosen else 'DECLINE', 'option_ids': chosen})
    else:
        raise AssertionError('upkeep did not commit')
    prompt = next(p for p in prompts if p['reaction'] == 'Black-Vein Initiate')
    assert prompt['action'] == 'Hollowing Field'
    assert prompt['affected'] == 'Keeper' and prompt['trigger_actor'] == 'Keeper'
    assert 'Hollowing Field' in prompt['moment'] and 'End Turn' not in prompt['moment']
    assert not any(token in prompt['moment'] for token in ('actor:', 'action:', 'resource:'))
    engine = cold(tmp_path, mid)
    assert engine.state.actors[ME].resources[unmaking.STRAIN] == 0
    assert any(c.condition_id == insights.USED for c in engine.state.actors[ME].conditions.values())
    assert not hasattr(engine, '_resource_gain_context')

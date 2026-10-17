"""Acquired Mantra progression -> native intent -> commit -> cold replay.

The assigned ownership comes from NS1R admission, not hand-written feature ids.
Other shipped techniques provide actual wounds, saves and silence. No live model
transport, browser, fabricated activity or injected trigger receipt is used.
"""
from copy import deepcopy
import hashlib
import json
import pytest

from combat.factory_compiler import compile_character
from combat.ext import maintained_activity as activity, mantra_foundation as mantra
from tests.test_seamfix_subpath_healing_melody import acquired
from tests.test_mgr_t14_ling_subpath_poison_touch import fake_menu_embeddings, fixed_dice
from tests.h1_support import ROOT, sheet
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE

SUBPATH = 'tianxia.subpath.qi.mantra_cultivator'
IMPACT = 'TAL_FORCE_IMPACT'


def scenario(tmp_path, acquired, *, cl=18, effective_cl=None, enemy_mantra=False,
             owns=True, success=False, ask=True, modes=None, positions=None, battlefield_transform=None,
             extra_talents=(), foe_talents=(IMPACT,), sound='air', foe_cl=18, bundle_transform=None, owner_hp=600,
             map_transform=None):
    doc = acquired(cl, subpath=SUBPATH) if owns else sheet([], cl=cl)
    doc['identity']['name']='Mantra caster'
    doc['spheres_and_talents'] = sheet([IMPACT, *extra_talents], cl=cl)['spheres_and_talents']
    if owns:
        from combat.authority_projection import project_sheet
        project = f'melody-cl-{cl}-mantra_cultivator'
        acquired.service.set_resource(project, 'tianxia.path.qi_cultivation', current=100, maximum=100)
        doc = project_sheet(acquired.service, project, doc)
    if effective_cl is not None:
        doc['path_and_subpath']['paths'][0]['effective_cl'] = effective_cl
    for d in (doc,):
        stats = d['ability_scores_and_statistics']
        stats['primary_resource']['maximum'] = 100
        stats['hit_points']['maximum'] = owner_hp
        stats['technique_attack_bonus'] = 100
        stats['technique_save_dc'] = 100
    foe = acquired(foe_cl, subpath=SUBPATH) if enemy_mantra else sheet(foe_talents, cl=foe_cl)
    foe['identity']['name']='Opponent'
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 600
    foe['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
    foe['ability_scores_and_statistics']['saving_throws'] = {a:100 if success else -20 for a in ('STR','DEX','CON','INT','WIS','CHA')}
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask':ask})
    from combat.tabletop import TabletopMapStore, to_battlefield, battlefield_as_map
    store = TabletopMapStore(tmp_path/'maps')
    world = {'map_id':'mantra-yard','display_name':'Mantra verification yard',
             'width_squares':28,'height_squares':18}
    if sound is not None:
        world['sound'] = {'ambient':sound,'boundaries':[]}
    if map_transform:
        map_transform(world)
    store.save(world)
    arena = to_battlefield(store.get('mantra-yard'))
    if battlefield_transform:
        battlefield_transform(arena)
        saved = store.save({**battlefield_as_map(arena),'map_id':'mantra-yard'})
        arena = to_battlefield(saved)
    result=fixture(tmp_path, [], cl=cl, owner_bundle=owner, foe_sheet=foe, ask=ask, modes=modes,
                   positions=positions, battlefield=arena, named=True, bundle_transform=bundle_transform, seed='NATIVE-MANTRA')
    # Keep the real admitted/projected sheet beside the sealed bundle, so the
    # native portable-character source agrees during cold reload/continuation.
    import zipfile
    with zipfile.ZipFile(tmp_path/'portable_characters'/OWNER.removeprefix('actor:factory.')/'current.zip','w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    return result


def play(combat, table, mid, name, target=None, choices=None, **kw):
    c = candidate(combat, mid, name, target=target, **kw)
    return settle(table, mid, c.candidate_id, choices=choices or {})


def names(engine):
    return {a.display_name for c in engine.legal_candidates() if (a := engine.action_catalog.get(c.source_definition_id))}


@pytest.mark.parametrize('kind', ['Stability','Flame','Attraction'])
def test_acquired_foundation_exclusive_bonus_free_switch_end_and_reload(tmp_path, acquired, kind):
    combat, table, mid = scenario(tmp_path, acquired, cl=6)
    before = reload(tmp_path, mid)
    assert not any(n.startswith('Resonant Chanting: change') for n in names(before))
    assert not any(a.display_name == 'Three Foundation Mantras' for a in before.action_catalog.values())
    play(combat, table, mid, 'Begin Mantra of ' + kind)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert not actor.bonus_action_available and actor.action_available
    assert activity.current(actor, mantra.CHANNEL).data['mode'] == kind.lower()
    assert len([c for c in actor.conditions.values() if c.condition_id == activity.STATE]) == 1
    other = 'Flame' if kind != 'Flame' else 'Stability'
    play(combat, table, mid, 'Resonant Chanting: change to Mantra of ' + other)
    engine = reload(tmp_path, mid)
    assert activity.current(engine.state.actors[OWNER], mantra.CHANNEL).data['mode'] == other.lower()
    assert not any(n.startswith('Resonant Chanting: change') for n in names(engine))
    play(combat, table, mid, 'End Foundation Mantra')
    assert activity.current(reload(tmp_path, mid).state.actors[OWNER], mantra.CHANNEL) is None


@pytest.mark.parametrize('cl,effective,expected', [(3,2,False),(3,None,True),(6,2,False),(18,5,True)])
def test_native_acquisition_and_suppression_tiers(tmp_path, acquired, cl, effective, expected):
    combat, table, mid = scenario(tmp_path, acquired, cl=cl, effective_cl=effective)
    engine = reload(tmp_path, mid)
    assert ('Begin Mantra of Stability' in names(engine)) is expected
    assert not any(n.startswith('Resonant Chanting: change') for n in names(engine))
    assert ('Great Mantra: Great Mantra of Motion' in names(engine)) is (cl >= 10 and (effective or cl) >= 10)
    assert not any(n.startswith('Primordial Syllable:') for n in names(engine))


def test_no_owner_is_default_inert(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, owns=False)
    engine = reload(tmp_path, mid)
    assert not any('Mantra' in n or 'Syllable' in n for n in names(engine))
    play(combat, table, mid, 'Impact', FOE, {'choice:needle.force_impact_push':['stay']})
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == activity.STATE for a in engine.state.actors.values() for c in a.conditions.values())
    assert not any(e.payload.get('display_source_id') == mantra.FOUNDATION for e in engine.events)


def test_flame_real_qi_damage_one_recipient_and_cold_reload(tmp_path, acquired, monkeypatch):
    fixed_dice(monkeypatch, [19, 4, 4, 4, 4, 4, 4])
    combat, table, mid = scenario(tmp_path, acquired, cl=6)
    play(combat, table, mid, 'Begin Mantra of Flame')
    prompts = play(combat, table, mid, 'Impact', FOE,
        {'choice:needle.force_impact_push':['stay'], 'choice:needle.mantra_flame':[FOE]})
    engine = reload(tmp_path, mid)
    packets = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
    extra = [e for e in packets if e.payload.get('display_source_id') == mantra.FOUNDATION]
    assert len(extra) == 1 and extra[0].payload['hp_damage'] == 4
    assert extra[0].payload['damage_type'] == 'FIRE'
    assert extra[0].target_ids == (FOE,)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.mantra_flame' for p in prompts)
    assert engine.state.actors[OWNER].turn_flags['mantra_flame_round_used'] == mantra.turn_stamp(engine)


def test_foundation_suppression_resumption_does_not_refresh_or_pay(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, cl=18)
    play(combat, table, mid, 'Begin Mantra of Stability')
    before = reload(tmp_path, mid)
    iid = activity.current(before.state.actors[OWNER], mantra.CHANNEL).instance_id
    play(combat, table, mid, 'Mantra of Silence', choices={'choice:needle.mantra_silence_exempt':[ALLY]}, at=(3,6))
    engine = reload(tmp_path, mid)
    assert activity.current(engine.state.actors[OWNER], mantra.CHANNEL).instance_id == iid
    assert activity.active(engine, engine.state.actors[OWNER], mantra.CHANNEL) is None
    assert 'Begin Mantra of Flame' not in names(engine)
    # A real walk out of the soundless sphere restores this same activity.
    routes = [c for c in engine.legal_candidates() if c.canonical_path and c.destination
              and engine.grid.distance_ft(c.destination, engine.state.actors[OWNER].position) > 30]
    if routes:
        settle(table, mid, routes[0].candidate_id)
    else:
        # End Concentration is the engine's native control for this field.
        assert 'End Concentration' in names(engine), names(engine)
        play(combat, table, mid, 'End Concentration')
    engine = reload(tmp_path, mid)
    assert activity.active(engine, engine.state.actors[OWNER], mantra.CHANNEL).instance_id == iid
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 95


@pytest.mark.parametrize('option,success', [('Shattering: Thunder',False),('Shattering: Force',True),('Stillness',False),('Stillness',True)])
def test_syllable_native_save_damage_and_scene_cost(tmp_path, acquired, option, success):
    combat, table, mid = scenario(tmp_path, acquired, success=success)
    before = reload(tmp_path, mid)
    hp = before.state.actors[FOE].current_hp
    play(combat, table, mid, 'Primordial Syllable: ' + option)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert owner.resources['resource:core.qi'] == 92
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE]
    assert saves and saves[-1].payload['success'] is success
    if option.startswith('Shattering'):
        assert foe.current_hp < hp
        assert any(c.condition_id == 'condition:typed.prone' for c in foe.conditions.values()) is (not success)
        rolls = [e for e in engine.events if e.event_type == 'DAMAGE_ROLLED' and e.actor_id == OWNER]
        assert rolls[-1].payload['expression'].startswith('10d8')
    else:
        assert any(c.condition_id == 'condition:typed.' + ('reaction_denied' if success else 'stunned') for c in foe.conditions.values())
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    assert not any(n.startswith('Primordial Syllable:') for n in names(reload(tmp_path, mid)))


def test_syllable_can_activate_inside_silence_and_restores_field(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired)
    play(combat, table, mid, 'Mantra of Silence', choices={'choice:needle.mantra_silence_exempt':[ALLY]}, at=(3,6))
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    assert not any(n.startswith('Begin Mantra') for n in names(before))
    assert 'Primordial Syllable: Stillness' in names(before)
    play(combat, table, mid, 'Primordial Syllable: Stillness')
    engine = reload(tmp_path, mid)
    zones = [z for z in engine.state.zones.values() if z.trigger_profile.get('sound_suppression')]
    assert zones and zones[0].active
    updates = [e for e in engine.events if e.event_type == 'ZONE_CREATED' and e.payload.get('zone',{}).get('zone_id') == zones[0].zone_id]
    assert any(not e.payload['zone']['active'] for e in updates)
    assert updates[-1].payload['zone']['active']


def test_renewal_actual_wound_all_willing_and_refusal(tmp_path, acquired, monkeypatch):
    fixed_dice(monkeypatch, [19,4,4,4,4,4,4])
    combat, table, mid = scenario(tmp_path, acquired)
    play(combat, table, mid, 'Impact', FOE, {'choice:needle.force_impact_push':['stay']})
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid).state.actors[FOE].current_hp
    prompts = play(combat, table, mid, 'Primordial Syllable: Renewal',
                   choices={'choice:willing.consent':['accept']})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp > before
    assert any(p['context']['reactor_id'] == FOE for p in prompts if p['context']['reaction_source_id']=='choice:willing.consent')
    heals = [e for e in engine.events if e.event_type == 'HEALING_APPLIED']
    assert any(FOE in e.target_ids for e in heals)


def test_passage_recipient_consent_native_movement_no_oa(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired)
    # Chooser defaults to a stay option; selecting movement is done explicitly
    # from the real prompt, preserving every native destination.
    from tests.test_r9i_karma_persistence import act
    c = candidate(combat, mid, 'Primordial Syllable: Passage')
    answers, prompts = [], []
    before = reload(tmp_path, mid).state.actors[ALLY].position
    for _ in range(12):
        result = act(table, mid, c.candidate_id, answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status']=='COMMITTED',result
            break
        p = result['reaction']; prompts.append(p); rid=p['context']['reaction_source_id']
        options=(p.get('choice') or {}).get('options') or []
        chosen = [ALLY] if rid=='choice:needle.syllable_recipients' else ['accept'] if rid=='choice:willing.consent' else []
        if rid=='choice:needle.syllable_destination':
            assert len(options)>16, 'The full legal endpoint set must remain reachable'
            chosen=[next(o['id'] for o in options if 'Leave ' not in o['label'])]
        answers.append({**p['context'],'selection':'USE' if chosen else 'DECLINE','option_ids':chosen})
    else:pytest.fail('Unresolved Passage prompt')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].position != before
    assert not any(e.event_type=='TELEPORT_COMMITTED' for e in engine.events)
    assert not any(c.data.get('fly_speed_ft') for c in engine.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('push', [True, False])
def test_resonant_extends_actual_push_only_after_acceptance(tmp_path, acquired, monkeypatch, push):
    fixed_dice(monkeypatch, [19,4,4,4,4,4,4])
    combat, table, mid = scenario(tmp_path, acquired, cl=6)
    play(combat, table, mid, 'Begin Mantra of Attraction')
    start = reload(tmp_path, mid).state.actors[FOE].position
    prompts = play(combat, table, mid, 'Impact', FOE,
        {'choice:needle.force_impact_push':['push' if push else 'stay'], 'choice:needle.mantra_extend':['extend']})
    engine = reload(tmp_path, mid)
    end = engine.state.actors[FOE].position
    assert engine.grid.distance_ft(start,end) == (10 if push else 0)
    assert sum(p['context']['reaction_source_id']=='choice:needle.mantra_extend' for p in prompts) == int(push)
    assert bool(engine.state.actors[OWNER].turn_flags.get('mantra_extension_round_used')) is push


def test_foundation_failed_save_moves_after_resolution_and_can_extend_itself(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, cl=6, extra_talents=['TAL_FORCE_SHOCKWAVE'],
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':5,'y':6}})
    play(combat, table, mid, 'Begin Mantra of Attraction')
    prompts = play(combat, table, mid, 'Shockwave', choices={
        'choice:needle.area_recipients':[FOE], 'choice:needle.mantra_attraction':[FOE],
        'choice:needle.mantra_direction':['toward'], 'choice:needle.mantra_extend':(None,['extend'])})
    engine = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.mantra_attraction' for p in prompts)
    assert engine.state.actors[OWNER].turn_flags.get('mantra_attraction_round_used') == mantra.turn_stamp(engine)
    damage = [i for i,e in enumerate(engine.events) if e.event_type=='DAMAGE_COMMITTED' and e.actor_id==OWNER]
    moves = [i for i,e in enumerate(engine.events) if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==FOE]
    assert damage and moves and min(moves) > min(damage)
    assert any(p['context']['reaction_source_id']=='choice:needle.mantra_extend' for p in prompts)


@pytest.mark.parametrize('kind', ['Fortitude','Precision','Motion','Endurance: Fire'])
def test_acquired_great_mantra_real_origin_replacement_suppression_and_dismissal(tmp_path, acquired, kind):
    from combat.ext import placed
    combat, table, mid = scenario(tmp_path, acquired)
    play(combat, table, mid, 'Great Mantra: Great Mantra of ' + kind,
         choices={'choice:needle.great_mantra_allies':[OWNER,ALLY]})
    engine = reload(tmp_path, mid)
    zone = placed.of(engine,'great_mantra')[0]
    assert placed.data(zone)['chosen'] == [OWNER,ALLY]
    assert type(placed.data(zone)['concentration_started']) is int
    assert activity.active(engine,engine.state.actors[OWNER],'great_mantra')
    turn(table,mid,ALLY);turn(table,mid,OWNER)
    play(combat,table,mid,'Mantra of Silence',at=(3,6), choices={'choice:needle.mantra_silence_exempt':[ALLY]})
    engine=reload(tmp_path,mid)
    assert activity.current(engine.state.actors[OWNER],'great_mantra')
    assert not activity.active(engine,engine.state.actors[OWNER],'great_mantra')
    # Native explicit dismissal of the soundless field restores the same aura.
    from tests.test_r9i_karma_persistence import act
    c=candidate(combat,mid,'End Concentration')
    result=act(table,mid,c.candidate_id,[])
    assert result['status']=='REACTION_REQUIRED'
    p=result['reaction']
    option=next(o['id'] for o in p['choice']['options'] if 'Silence' in o['label'])
    result=act(table,mid,c.candidate_id,[{**p['context'],'selection':'USE','option_ids':[option]}])
    assert result['status']=='COMMITTED',result
    engine=reload(tmp_path,mid)
    assert activity.active(engine,engine.state.actors[OWNER],'great_mantra')
    assert placed.of(engine,'great_mantra') and not placed.of(engine,'mantra_silence')


def test_exact_controlling_sources_are_unchanged():
    rules=json.loads((ROOT/'authority/typed_mechanics/rules_text.json').read_bytes())
    expected={
        'three_foundation_mantras':'dce1fd8e1affe391fb40aa69871dc8d866c4e21de532c277cf2212fe447c0e14',
        'resonant_chanting':'cb5bcf271d035220d50b1553054ff7dd99ab41daaaa9941ee5080d8d774e8341',
        'great_mantra':'a71a8459825ea74701d82ebb97946e049ff7d69ee06c9a47a741cc5fef4a3a6c',
        'mantra_of_silence':'f5375d22350022bb0a8871312a7b05ea4e041a92e17b928dba886d4e54bc20f4',
        'primordial_syllable':'ffb4368d1ff47edf365a89854261cf661b40ab3193fdad49135ccd5701781fc5'}
    for key,digest in expected.items():
        assert hashlib.sha256(rules[mantra.PREFIX+key].encode()).hexdigest()==digest


def test_stability_changes_actual_incoming_attack_ac(tmp_path, acquired, monkeypatch):
    fixed_dice(monkeypatch,[19,4,4,4,4,4])
    ac=[]
    for enabled in (False,True):
        combat,table,mid=scenario(tmp_path/str(enabled),acquired,cl=6)
        if enabled:play(combat,table,mid,'Begin Mantra of Stability')
        turn(table,mid,FOE)
        play(combat,table,mid,'Impact',OWNER,{'choice:needle.force_impact_push':['stay']})
        engine=reload(tmp_path/str(enabled),mid)
        rolls=[e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==FOE]
        assert rolls
        ac.append(rolls[-1].payload['target_ac'])
    assert ac[1]==ac[0]+1


def test_resonant_flame_halves_actual_incoming_fire_damage(tmp_path, acquired, monkeypatch):
    fixed_dice(monkeypatch,[19,4,4,4,4,4])
    combat,table,mid=scenario(tmp_path,acquired,cl=6,foe_talents=['FIRE_BASE_IGNITE'])
    play(combat,table,mid,'Begin Mantra of Flame')
    turn(table,mid,FOE)
    play(combat,table,mid,'Ignite',OWNER)
    engine=reload(tmp_path,mid)
    packets=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.actor_id==FOE and OWNER in e.target_ids]
    assert packets and packets[0].payload['rolled_or_pending_damage']>0
    assert packets[0].payload['reduced_to']==packets[0].payload['rolled_or_pending_damage']//2


@pytest.mark.parametrize('control',['MANUAL','LOCAL_AUTO'])
def test_actor_owned_decisions_with_real_table_auto_step(tmp_path, acquired, control):
    from tests.r1i_service_support import force_ai_candidate
    modes={OWNER:control,ALLY:'MANUAL',FOE:'MANUAL'}
    combat,table,mid=scenario(tmp_path,acquired,modes=modes)
    c=candidate(combat,mid,'Primordial Syllable: Renewal')
    if control=='LOCAL_AUTO':
        force_ai_candidate(combat,mid,OWNER,c.candidate_id)
    prompts=settle(table,mid,c.candidate_id,choices={'choice:willing.consent':['accept']},auto=control=='LOCAL_AUTO')
    engine=reload(tmp_path,mid)
    consent=[p for p in prompts if p['context']['reaction_source_id']=='choice:willing.consent']
    assert any(p['context']['reactor_id']==ALLY for p in consent)
    if control=='LOCAL_AUTO':assert not any(p['context']['reactor_id']==OWNER for p in consent)
    assert engine.state.actors[OWNER].resources['resource:core.qi']==92


@pytest.mark.parametrize('kind',['unattended','temporary_barrier','vehicle','structure','formation_anchor'])
def test_shattering_double_damage_uses_native_object_classification(tmp_path, acquired, kind):
    def objects(arena):
        arena['map_objects']=[{'id':97,'x':4,'y':7,'kind':'pillar' if kind=='structure' else 'custom',
            'name':'Test '+kind,'material':'wood','size':'medium','hp':500,'ac':10,'blocks':False,
            'unattended':kind=='unattended', **({kind:True} if kind not in {'unattended','structure'} else {})}]
    combat,table,mid=scenario(tmp_path,acquired,battlefield_transform=objects)
    before=reload(tmp_path,mid).state.objects['object:map.97'].current_hp
    play(combat,table,mid,'Primordial Syllable: Shattering: Thunder')
    engine=reload(tmp_path,mid)
    rolled=[e for e in engine.events if e.event_type=='DAMAGE_ROLLED' and e.actor_id==OWNER
            and e.payload.get('expression','').startswith('10d8')]
    assert rolled
    assert before-engine.state.objects['object:map.97'].current_hp==2*rolled[0].payload['total']


@pytest.mark.parametrize('answer,started',[('air',True),('vacuum',False),('unknown',False)])
def test_actual_unknown_sound_input_precedes_payment_and_survives_reload(tmp_path, acquired, answer, started):
    combat,table,mid=scenario(tmp_path,acquired,cl=3,sound=None)
    prompts=play(combat,table,mid,'Begin Mantra of Stability',choices={'choice:needle.sound_medium':[answer]})
    engine=reload(tmp_path,mid)
    actor=engine.state.actors[OWNER]
    assert any(p['context']['reaction_source_id']=='choice:needle.sound_medium' for p in prompts)
    assert bool(activity.current(actor,mantra.CHANNEL)) is started
    assert actor.bonus_action_available is (not started)
    assert actor.resources['resource:core.qi']==100


@pytest.mark.parametrize('automatic_turn',[False,True])
@pytest.mark.parametrize('kind,reactive,attack',[
    ('Flame','TAL_LIGHTNING_STATIC_GUARD','Unarmed Strike'),
    ('Attraction','TAL_LIGHTNING_THUNDER_THAT_ANSWERS_FIRST','Impact')])
def test_player_owned_mantra_rider_on_native_opponent_reaction_turn(tmp_path, acquired, monkeypatch, automatic_turn, kind, reactive, attack):
    from tests.test_r9i_karma_persistence import act
    from tests.r1i_service_support import force_ai_candidate
    fixed_dice(monkeypatch,[19,4,4,4,4,4,4,4])
    modes={OWNER:'MANUAL',ALLY:'MANUAL',FOE:'LOCAL_AUTO' if automatic_turn else 'MANUAL'}
    combat,table,mid=scenario(tmp_path,acquired,extra_talents=[reactive],modes=modes,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':4,'y':6}})
    play(combat,table,mid,'Begin Mantra of '+kind)
    turn(table,mid,FOE)
    c=candidate(combat,mid,attack,target=OWNER)
    if automatic_turn:force_ai_candidate(combat,mid,FOE,c.candidate_id)
    answers,prompts=[],[]
    for _ in range(20):
        result=table.auto_step(mid,0,answers) if automatic_turn else act(table,mid,c.candidate_id,answers)
        if result['status']!='REACTION_REQUIRED':
            assert result['status']=='COMMITTED',result
            break
        p=result['reaction'];prompts.append(p);rid=p['context']['reaction_source_id']
        answer={**p['context'],'selection':'DECLINE'}
        if reactive in rid:
            answer['selection']='USE'
        elif rid=='choice:needle.mantra_'+kind.lower():
            answer.update(selection='USE',option_ids=[FOE])
        elif rid=='choice:needle.mantra_direction':
            answer.update(selection='USE',option_ids=['away'])
        answers.append(answer)
    else:pytest.fail('Native reaction did not finish')
    engine=reload(tmp_path,mid)
    rider=[p for p in prompts if p['context']['reaction_source_id']=='choice:needle.mantra_'+kind.lower()]
    assert rider and all(p['context']['reactor_id']==OWNER for p in rider)
    assert engine.state.current_actor_id==FOE
    assert any(reactive in e.source_definition_id for e in engine.events if e.event_type=='REACTION_RESOLVED')
    assert engine.state.actors[OWNER].turn_flags['mantra_'+kind.lower()+'_round_used']==mantra.turn_stamp(engine)


def test_syllable_does_not_revive_a_sound_field_whose_concentration_broke(tmp_path, acquired):
    from combat.ext import placed
    combat,table,mid=scenario(tmp_path,acquired,enemy_mantra=True)
    turn(table,mid,FOE)
    play(combat,table,mid,'Mantra of Silence',at=(3,6),choices={'choice:needle.mantra_silence_exempt':[FOE]})
    turn(table,mid,OWNER)
    assert placed.of(reload(tmp_path,mid),'mantra_silence')
    play(combat,table,mid,'Primordial Syllable: Shattering: Thunder')
    engine=reload(tmp_path,mid)
    assert not placed.of(engine,'mantra_silence')
    assert engine.state.actors[FOE].concentration is None


def test_flame_can_choose_a_native_damaged_object(tmp_path, acquired, monkeypatch):
    fixed_dice(monkeypatch,[19,4,4,4,4,4])
    def objects(arena):
        arena['map_objects']=[{'id':97,'x':5,'y':7,'kind':'custom','name':'Training bell',
            'material':'wood','size':'medium','hp':500,'ac':10,'blocks':False,'unattended':True}]
    combat,table,mid=scenario(tmp_path,acquired,cl=6,battlefield_transform=objects)
    play(combat,table,mid,'Begin Mantra of Flame')
    engine=reload(tmp_path,mid)
    choices=[c for c in engine.legal_candidates() if c.target_ids==('object:map.97',)
             and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source')==IMPACT]
    assert choices
    prompts=settle(table,mid,choices[0].candidate_id,choices={'choice:needle.mantra_flame':['object:map.97']})
    engine=reload(tmp_path,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.mantra_flame' for p in prompts)
    extra=[e for e in engine.events if e.event_type=='OBJECT_UPDATED' and e.source_definition_id==mantra.FOUNDATION]
    assert extra and extra[-1].payload['damage']['taken']==4


@pytest.mark.parametrize('higher,accept',[(False,True),(True,True),(False,False)])
def test_renewal_single_native_condition_and_original_higher_source_save(tmp_path, acquired, monkeypatch, higher, accept):
    fixed_dice(monkeypatch,[1,*([20]*18)])
    combat,table,mid=scenario(tmp_path,acquired,foe_talents=['TAL_FORCE_PRESSURE_PIN'],foe_cl=30 if higher else 18,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':4,'y':6}})
    turn(table,mid,FOE)
    play(combat,table,mid,'Pressure Pin',OWNER)
    before=reload(tmp_path,mid)
    held=next(c for c in before.state.actors[OWNER].conditions.values() if c.condition_id=='condition:typed.restrained')
    turn(table,mid,OWNER)
    prompts=play(combat,table,mid,'Primordial Syllable: Renewal',choices={
        'choice:willing.consent':['accept'],'choice:needle.syllable_cleanse':['0'] if accept else None})
    engine=reload(tmp_path,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.syllable_cleanse' for p in prompts)
    assert (held.instance_id not in engine.state.actors[OWNER].conditions) is accept
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==OWNER
           and e.source_definition_id==held.source_definition_id and e.payload.get('mode')=='ADVANTAGE']
    if higher and accept:assert saves and saves[-1].payload['success']
    else:assert not saves


@pytest.mark.parametrize('success',[False,True])
def test_stillness_uses_exact_source_end_or_recipient_start_boundary(tmp_path, acquired, success):
    combat,table,mid=scenario(tmp_path,acquired,success=success)
    play(combat,table,mid,'Primordial Syllable: Stillness')
    engine=reload(tmp_path,mid)
    name='condition:typed.reaction_denied' if success else 'condition:typed.stunned'
    assert any(c.condition_id==name for c in engine.state.actors[FOE].conditions.values())
    if success:
        turn(table,mid,FOE)
        assert not any(c.condition_id==name for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())
    else:
        turn(table,mid,ALLY)
        turn(table,mid,OWNER)
        assert any(c.condition_id==name for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())
        settle(table,mid,table.state(mid)['menu']['end_turn'])
        assert not any(c.condition_id==name for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())


def test_actual_domain_armament_origin_reaches_a_creature_outside_caster_radius(tmp_path, acquired):
    from combat.ext.qi_path import armament_point
    combat,table,mid=scenario(tmp_path,acquired,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':20,'y':6}})
    play(combat,table,mid,'Domain Armament: Manifest',at=(9,6))
    engine=reload(tmp_path,mid)
    assert armament_point(engine.state.actors[OWNER])==(9,6)
    play(combat,table,mid,'Primordial Syllable: Stillness',remote=True)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].position.x==3
    assert any(c.condition_id=='condition:typed.stunned' for c in engine.state.actors[FOE].conditions.values())


def realm_source(kind,level):
    """An authored external source exercises the real generic producer, not flags.

    This guards source-independent caps. Assigned Mantra ownership still comes
    only from native NS1R acquisition and all effects commit through the table.
    """
    def add(bundles):
        from combat.canonical import canonical_sha256
        row={'source_definition_id':'action:test.realm_source','display_name':'Apply external Realm suppression',
            'owner_id':OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF',
            'parameters':{'free_primary':True,'typed':{'source':'test:realm_source','numbers':{'cl':30},'riders':[],
                'effects':[{'type':kind, 'effective_cl' if kind=='cultivation_suppression' else 'cl_cap':level,
                    'applies_to':'self','expires_on':'START_OF_SOURCE_NEXT_TURN'}]}}}
        bundles[0]['action_catalog'].append(row)
        bundles[0]['actor_template']['action_ids'].append(row['source_definition_id'])
        bundles[0].pop('bundle_sha256',None);bundles[0]['bundle_sha256']=canonical_sha256(bundles[0])
    return add


@pytest.mark.parametrize('producer',['cultivation_suppression','cultivation_limit'])
def test_real_runtime_cap_scales_flame_pb_and_lifts_without_losing_activity(tmp_path, acquired, monkeypatch, producer):
    fixed_dice(monkeypatch,[19,4,4,4,4,4,4,4])
    combat,table,mid=scenario(tmp_path,acquired,bundle_transform=realm_source(producer,3))
    play(combat,table,mid,'Begin Mantra of Flame')
    iid=activity.current(reload(tmp_path,mid).state.actors[OWNER],mantra.CHANNEL).instance_id
    play(combat,table,mid,'Apply external Realm suppression')
    engine=reload(tmp_path,mid)
    assert activity.current(engine.state.actors[OWNER],mantra.CHANNEL).instance_id==iid
    assert not any(n.startswith('Resonant Chanting: change') for n in names(engine))
    play(combat,table,mid,'Impact',FOE,{'choice:needle.force_impact_push':['stay'],'choice:needle.mantra_flame':[FOE]})
    engine=reload(tmp_path,mid)
    extra=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.payload.get('display_source_id')==mantra.FOUNDATION]
    assert extra[-1].payload['hp_damage']==2
    turn(table,mid,ALLY);turn(table,mid,OWNER)
    engine=reload(tmp_path,mid)
    assert activity.current(engine.state.actors[OWNER],mantra.CHANNEL).instance_id==iid
    assert 'Resonant Chanting: change to Mantra of Stability' in names(engine)
    play(combat,table,mid,'Impact',FOE,{'choice:needle.force_impact_push':['stay'],'choice:needle.mantra_flame':[FOE]})
    engine=reload(tmp_path,mid)
    extra=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.payload.get('display_source_id')==mantra.FOUNDATION]
    assert extra[-1].payload['hp_damage']==4


@pytest.mark.parametrize('spell,level,tag',[
    ('Great Mantra: Great Mantra of Precision',9,'great_mantra'),('Mantra of Silence',13,'mantra_silence')])
def test_runtime_cap_ends_illegal_maintained_copy_without_refunding(tmp_path, acquired, spell, level, tag):
    from combat.ext import placed
    combat,table,mid=scenario(tmp_path,acquired,bundle_transform=realm_source('cultivation_limit',level))
    kw={'at':(3,6)} if tag=='mantra_silence' else {}
    play(combat,table,mid,spell,choices={'choice:needle.great_mantra_allies':[OWNER],
                                      'choice:needle.mantra_silence_exempt':[OWNER]},**kw)
    assert placed.of(reload(tmp_path,mid),tag)
    play(combat,table,mid,'Apply external Realm suppression')
    engine=reload(tmp_path,mid)
    assert not placed.of(engine,tag)
    assert engine.state.actors[OWNER].concentration is None
    assert engine.state.actors[OWNER].resources['resource:core.qi']==95


@pytest.mark.parametrize('source_cl,absolute,affected',[(18,False,True),(30,False,False),(18,True,False)])
def test_syllable_native_map_sound_authority_and_restoration(tmp_path, acquired, source_cl, absolute, affected):
    from combat.sound_transmission import hearing_path
    def ward(arena):
        arena['sound']['boundaries']=[{'kind':'ward','name':'Recorded sound ward','cells':[[4,6]],
            'source_cl':source_cl,**({'absolute':'Secret sound protection'} if absolute else {})}]
    combat,table,mid=scenario(tmp_path,acquired,battlefield_transform=ward)
    before=reload(tmp_path,mid)
    facts=deepcopy(before.battlefield_document['sound'])
    play(combat,table,mid,'Primordial Syllable: Stillness')
    engine=reload(tmp_path,mid)
    assert any(c.condition_id=='condition:typed.stunned' for c in engine.state.actors[FOE].conditions.values()) is affected
    assert engine.battlefield_document['sound']==facts
    assert not hearing_path(engine,engine.state.actors[OWNER],engine.state.actors[FOE])


@pytest.mark.parametrize('cl,expected', [(3,'NORMAL'),(6,'ADVANTAGE')])
def test_resonant_stability_native_forced_movement_save(tmp_path, acquired, cl, expected):
    combat,table,mid=scenario(tmp_path,acquired,cl=cl,foe_talents=(IMPACT,'TAL_FORCE_SHOCKWAVE'),
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':5,'y':6}})
    play(combat,table,mid,'Begin Mantra of Stability')
    turn(table,mid,FOE)
    play(combat,table,mid,'Shockwave',choices={'choice:needle.area_recipients':[OWNER]})
    engine=reload(tmp_path,mid)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==OWNER
           and 'SHOCKWAVE' in str(e.payload)]
    assert saves and saves[-1].payload['mode']==expected


def test_passage_native_solid_total_cover_boundary_and_air_options(tmp_path, acquired):
    def wall(world):
        world['walls']=[{'id':'solid-divider','shape':'line','points':[[4,0],[4,18]],
                         'blocks':'sight_and_movement','height_ft':200}]
    combat,table,mid=scenario(tmp_path,acquired,map_transform=wall,
        positions={OWNER:{'x':2,'y':6},ALLY:{'x':2,'y':7},FOE:{'x':8,'y':6}})
    from tests.test_r9i_karma_persistence import act
    c=candidate(combat,mid,'Primordial Syllable: Passage')
    answers=[];checked=False
    for _ in range(12):
        result=act(table,mid,c.candidate_id,answers)
        if result['status']!='REACTION_REQUIRED':
            assert result['status']=='COMMITTED',result
            break
        p=result['reaction'];rid=p['context']['reaction_source_id']
        chosen=[ALLY] if rid=='choice:needle.syllable_recipients' else ['accept'] if rid=='choice:willing.consent' else []
        if rid=='choice:needle.syllable_destination':
            destinations=[o for o in p['choice']['options'] if o['id'].startswith('cell:')]
            assert destinations
            coords=[o['id'].split(':',2)[1].split(',') for o in destinations]
            assert all(int(c[0])<4 for c in coords), 'Passage cannot cross the solid, opaque divider'
            assert any(len(c)>2 and int(c[2])>0 for c in coords), 'Open air remains a legal movement option'
            checked=True
        answers.append({**p['context'],'selection':'USE' if chosen else 'DECLINE','option_ids':chosen})
    else:pytest.fail('Unresolved Passage boundary prompt')
    assert checked
    reload(tmp_path,mid)


def test_silence_boundary_blocks_actual_spoken_standard_but_preserves_visual_signal(tmp_path, acquired, monkeypatch):
    from combat.ext import warleader
    fixed_dice(monkeypatch,[1,1,1,1,1,1])
    combat,table,mid=scenario(tmp_path,acquired,extra_talents=('WARLEADER_BASE_SET_THE_STANDARD',),
        foe_talents=('RADIANCE_TAL_BLINDING_FLASH',),
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':7,'y':6},FOE:{'x':7,'y':7}})
    play(combat,table,mid,'Set the Standard')
    play(combat,table,mid,'Mantra of Silence',at=(0,6),
        choices={'choice:needle.mantra_silence_exempt':[OWNER]})
    engine=reload(tmp_path,mid)
    assert warleader.perceives(engine,engine.state.actors[OWNER],engine.state.actors[ALLY]), 'A visible signal still reaches the ally'
    turn(table,mid,FOE)
    play(combat,table,mid,'Blinding Flash: 10-Foot Emanation',choices={'choice:needle.area_recipients':[ALLY]})
    engine=reload(tmp_path,mid)
    ally=engine.state.actors[ALLY]
    assert any(c.condition_id=='condition:typed.blinded' for c in ally.conditions.values())
    assert not warleader.perceives(engine,engine.state.actors[OWNER],ally), 'Speech cannot carry the Standard across the Silence boundary'


def test_foundation_ends_on_real_zero_hp_unconscious_lifecycle(tmp_path, acquired, monkeypatch):
    fixed_dice(monkeypatch,[19,4,4,4,4,4])
    combat,table,mid=scenario(tmp_path,acquired,owner_hp=10)
    play(combat,table,mid,'Begin Mantra of Stability')
    assert activity.current(reload(tmp_path,mid).state.actors[OWNER],mantra.CHANNEL)
    turn(table,mid,FOE)
    play(combat,table,mid,'Impact',OWNER,{'choice:needle.force_impact_push':['stay']})
    engine=reload(tmp_path,mid)
    actor=engine.state.actors[OWNER]
    assert actor.current_hp==0
    assert actor.life_state in {'DYING','STABLE'}
    assert activity.current(actor,mantra.CHANNEL) is None



def test_renewal_discovers_poisoned_condition_carried_by_named_feature(monkeypatch):
    """A listed condition remains curable when its carrier has a feature-specific ID."""
    from types import SimpleNamespace
    from combat.ext import end_effect, condition_ownership, rider_choices
    from combat.ext import mantra_syllable
    poisoned = SimpleNamespace(condition_id='condition:typed.poison_touch', instance_id='poison-1',
                               data={}, source_definition_id='poison-touch')
    actor = SimpleNamespace(conditions={'poison-1': poisoned})
    seen = {}
    monkeypatch.setattr(end_effect, 'condition_rule', lambda c, fallback: {'condition':'poisoned'})
    monkeypatch.setattr(end_effect, 'known_source_cl', lambda ctx, c: 18)
    monkeypatch.setattr(condition_ownership, 'remove_instance', lambda *args: seen.setdefault('removed', args[2]))
    monkeypatch.setattr(rider_choices, 'pick', lambda *args, **kwargs: (seen.update(options=args[4]) or ['0']))
    mantra_syllable.cleanse(SimpleNamespace(target=actor, engine=object(), numbers={'cl':18}, source='syllable', intent=None))
    assert seen['options'] == ['0']
    assert seen['removed'] == 'poison-1'


def test_syllable_sound_admission_checks_every_occupied_cell(monkeypatch):
    from types import SimpleNamespace
    from combat.ext import mantra_syllable
    cells = [SimpleNamespace(x=1,y=1,z=0), SimpleNamespace(x=2,y=1,z=0)]
    actor = SimpleNamespace(position=cells[0])
    recipient = SimpleNamespace(position=cells[0])
    ctx = SimpleNamespace(engine=object(), actor=actor)
    calls=[]
    monkeypatch.setattr('combat.spatial_areas.actor_positions', lambda engine, subject: cells)
    def boundaries(engine, source, target, *, origin, at=None):
        calls.append(at)
        return [] if at == cells[1] else None
    monkeypatch.setattr('combat.sound_transmission.boundaries', boundaries)
    monkeypatch.setattr('combat.sound_transmission.path_allowed', lambda ctx, rows: True)
    assert mantra_syllable.receives(ctx, recipient, cells[0])
    assert calls == cells


def test_foundation_flame_help_discloses_object_targets():
    from combat.ext.mantra_foundation import foundation_help
    text = foundation_help({'parameters': {'foundation_mantra':'flame'}})
    assert 'creatures or eligible objects' in text and 'damaged target' in text


def test_mantra_of_silence_caster_may_choose_self_as_unaffected(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':8,'y':6}})
    play(combat, table, mid, 'Mantra of Silence', at=(3,6),
         choices={'choice:needle.mantra_silence_exempt':[OWNER]})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert not any(c.condition_id == 'condition:typed.deafened' for c in owner.conditions.values())
    assert any(c.condition_id == 'condition:typed.deafened' for c in engine.state.actors[ALLY].conditions.values())

"""Public native regression: initial source-shaped sheets, table commits, cold replay.
Dynamic authority dependencies: TAL_WATER_ABYSSAL_PRESSURE_SEAL,
TAL_WATER_COURT_OF_THE_ENDLESS_TIDE, WATER_BASE_SHAPE_CURRENT,
WATER_BASE_WATER_LASH, WATER_BASE_RETURN_THE_FLOW, TAL_SPACE_FOLD_STEP.
"""
import json
from pathlib import Path
import zipfile
import pytest
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

# Literal inputs required by the safe exporter's dynamic registry closure.
RUNTIME_DEPENDENCIES = (
    'APP/combat/ext/water_second_pass.py', 'APP/combat/ext/effect_durations.py',
    'APP/combat/ext/states.py', 'APP/combat/ext/ability_source.py',
    'APP/combat/ext/general_flight_skills.py',
    'APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json',
    'APP/authority/typed_mechanics/rules_text.json',
    'APP/combat/rules/typed_conditions.json', 'APP/combat/rules/speech.json',
)
ROOT = Path(__file__).resolve().parents[1]
SEAL = 'TAL_WATER_ABYSSAL_PRESSURE_SEAL'
COURT = 'TAL_WATER_COURT_OF_THE_ENDLESS_TIDE'
OWNER = 'actor:factory.seal-owner'
TARGET = 'actor:factory.seal-target'


def sheet(talents=(), *, success=False, cp=40):
    score = 14 if talents else (30 if success else 1)
    return {'identity': {'name': 'Keeper' if talents else 'Traveller', 'cultivation_level': 17,
        'path': 'Qi Cultivation', 'key_ability': 'CON', 'proficiency_bonus': 6},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': score, 'modifier': (score-10)//2}
                          for a in ('STR','DEX','CON','INT','WIS','CHA')],
            'primary_resource': {'name': 'Qi', 'maximum': cp}, 'hit_points': {'maximum': 100},
            'armor_class': {'base_value': 14}, 'speed': {'walking_ft': 30},
            'technique_save_dc': 16, 'technique_attack_bonus': 8,
            'saving_throws': {'CON': 16 if success else (score-10)//2},
            'saving_throw_proficiencies': ['CON'] if success else []},
        'spheres_and_talents': {'sphere_record_ids': ['tianxia.sphere.water'],
            'learned_talent_record_ids': list(talents), 'automatic_sphere_component_record_ids':
            ['WATER_BASE_SHAPE_CURRENT','WATER_BASE_WATER_LASH','WATER_BASE_RETURN_THE_FLOW','WATER_BASE_WATER_INITIATION']}}


def settle(table, mid, cid, picks=None):
    answers = []
    for _ in range(20):
        m = table.state(mid)['menu']
        r = table.act(mid, cid, m['decision_id'], m['state_version'], 0, answers)
        if r['status'] != 'REACTION_REQUIRED':
            assert r['status'] == 'COMMITTED', r
            return
        p = r['reaction']; opts = (p.get('choice') or {}).get('options') or []
        a = {**p['context'], 'selection': 'USE' if opts else 'DECLINE'}
        if opts: a['option_ids'] = (picks or {}).get(p['context']['reaction_source_id'], [opts[0]['id']])
        answers.append(a)
    raise AssertionError('unsettled')


def turn(table, mid, who):
    for _ in range(10):
        m = table.state(mid)['menu']
        if m['actor_id'] == who: return
        settle(table, mid, m['end_turn'])
    raise AssertionError('no turn')


def fixture(tmp_path, *, success=False, cp=40, ally=False, travel=False, water_success=False, flight=False, foreign_court=False, far=False, consumers=False, drowning=None, whirlpool=None):
    docs = [sheet([SEAL, COURT], cp=cp), sheet(success=success)]
    if whirlpool is not None:
        docs[1] = sheet(['TAL_WATER_WHIRLPOOL_PRISON'])
    if drowning is not None or whirlpool is not None:
        if drowning is not None: docs[1] = sheet(['TAL_WATER_HEAVEN_FALLING_TSUNAMI'])
        stats = docs[0]['ability_scores_and_statistics']
        next(a for a in stats['abilities'] if a['ability'] == 'STR').update(
            score=30 if (drowning or whirlpool) else 1, modifier=10 if (drowning or whirlpool) else -5)
        stats['saving_throws']['STR'] = 16 if (drowning or whirlpool) else -5
        if drowning or whirlpool: stats['saving_throw_proficiencies'].append('STR')
    if consumers:
        doc = docs[1]['spheres_and_talents']
        doc['sphere_record_ids'].extend(['tianxia.sphere.life','tianxia.sphere.warleader'])
        doc['automatic_sphere_component_record_ids'].extend([
            'LIFE_BASE_LIFE_INITIATION','LIFE_BASE_READ_THE_PULSE','LIFE_BASE_MEND_THE_PULSE',
            'LIFE_BASE_BORROWED_BREATH','LIFE_BASE_PURIFY_THE_PULSE',
            'WARLEADER_BASE_COMMAND_RESPONSES','WARLEADER_BASE_FIERCE_SHOUT','WARLEADER_BASE_MOMENTUM_MARKS',
            'WARLEADER_BASE_PRESS_THE_OPENING_STANDARD','WARLEADER_BASE_SET_THE_STANDARD'])
    if flight:
        docs[1]['path_and_subpath'] = {'subpath_id': 'tianxia.subpath.qi.cloud_walker',
            'path_feature_record_ids': ['tianxia.subpath.qi.cloud_walker.feature.cloud_step']}
    if travel or flight:
        stats = docs[1]['ability_scores_and_statistics']
        if water_success:
            docs[1]['identity']['key_ability'] = 'DEX'
            next(a for a in stats['abilities'] if a['ability'] == 'DEX').update(score=30, modifier=10)
        if travel:
            docs[1]['spheres_and_talents']['sphere_record_ids'].append('tianxia.sphere.space')
            docs[1]['spheres_and_talents']['automatic_sphere_component_record_ids'].append('TAL_SPACE_FOLD_STEP')
    if foreign_court:
        docs[1]['spheres_and_talents']['learned_talent_record_ids'] = [COURT]
    docs[1]['identity']['name'] = 'Traveller'
    ids = [OWNER, TARGET]
    if ally:
        ids.append('actor:factory.seal-observer')
        observer = sheet()
        observer['identity']['name'] = 'Observer'
        docs.append(observer)
    teams = {OWNER:'team:factory',TARGET:'team:factory' if ally else 'team:opponents'}
    places = {OWNER:{'x':3,'y':6},TARGET:{'x':17 if far else 4,'y':6}}
    if ally:
        teams[ids[2]] = 'team:opponents'
        places[ids[2]] = {'x':8,'y':6}
    for aid, doc in zip(ids, docs):
        folder = tmp_path/'portable_characters'/aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    c = CombatService(ROOT,tmp_path); t = TabletopService(c,tmp_path)
    bundles = [compile_character(d,actor_id=a,reaction_plan={'ask':True}) for a,d in zip(ids,docs)]
    mid = c._finish_factory_match(bundles,ids,
        teams, places,
        c.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],[OWNER,TARGET] if ally else [OWNER],[ids[2]] if ally else [TARGET],
        control_modes={a:'MANUAL' for a in ids},match_seed='ABYSSAL-NATIVE',
        display_name='Abyssal seal',maximum_rounds=10)['match_id']
    turn(t,mid,OWNER)
    return c,t,mid


def rows(c,mid,source,target=None):
    e = c._load_session(mid).engine
    return [r for r in e.legal_candidates() if
        ((getattr(e.action_catalog.get(r.source_definition_id),'parameters',{}) or {}).get('typed') or {}).get('source') == source
        and (target is None or r.target_ids == (target,))]


def cold(tmp_path,mid):
    s = CombatService(ROOT,tmp_path)._load_session(mid)
    assert s.mechanical.replay()['status'] == 'PASS'
    return s.engine


@pytest.mark.parametrize('success',[False,True])
@pytest.mark.parametrize('ally',[False,True])
def test_native_branches_reload_expiry(tmp_path,success,ally):
    c,t,mid = fixture(tmp_path,success=success,ally=ally)
    assert not rows(c,mid,SEAL,TARGET)
    settle(t,mid,rows(c,mid,COURT)[0].candidate_id)
    options = rows(c,mid,SEAL,TARGET)
    assert options, 'inside your Court permits seal against any creature'
    before = dict(c._load_session(mid).engine.state.actors[OWNER].resources)
    settle(t,mid,options[0].candidate_id)
    e = cold(tmp_path,mid); target = e.state.actors[TARGET]
    labels = [r.condition_id for r in target.conditions.values()]
    assert any('soaked' in x for x in labels) is success
    assert any('restrained' in x for x in labels) is (not success)
    assert sum(before.values())-sum(e.state.actors[OWNER].resources.values()) == 4
    assert not e.state.actors[OWNER].action_available
    if not success:
        assert any('silenced' in x for x in labels)
        assert any(r.data.get('abyssal_pressure_seal') for r in target.conditions.values())
    turn(t,mid,TARGET); turn(t,mid,OWNER)
    e = cold(tmp_path,mid)
    labels = [r.condition_id for r in e.state.actors[TARGET].conditions.values()]
    assert not any('soaked' in x for x in labels)
    assert any('restrained' in x for x in labels) is (not success)
    settle(t,mid,t.state(mid)['menu']['end_turn'])
    e = cold(tmp_path,mid)
    assert not any(r.data.get('abyssal_pressure_seal') for r in e.state.actors[TARGET].conditions.values())


def test_insufficient_payment(tmp_path):
    c,t,mid = fixture(tmp_path,cp=6)
    settle(t,mid,rows(c,mid,COURT)[0].candidate_id)
    assert not rows(c,mid,SEAL,TARGET)
    cold(tmp_path,mid)


@pytest.mark.parametrize('water_success', [False, True])
def test_native_teleport_contest_before_payment(tmp_path, water_success):
    c,t,mid = fixture(tmp_path, travel=True, water_success=water_success)
    settle(t,mid,rows(c,mid,COURT)[0].candidate_id)
    settle(t,mid,rows(c,mid,SEAL,TARGET)[0].candidate_id)
    turn(t,mid,TARGET)
    e = cold(tmp_path,mid); target = e.state.actors[TARGET]
    before, position = dict(target.resources), target.position
    options = [r for r in rows(c,mid,'TAL_SPACE_FOLD_STEP') if r.destination and r.destination != position]
    assert options, 'Restrained must not hide an otherwise legal teleport attempt'
    settle(t,mid,options[0].candidate_id)
    e = cold(tmp_path,mid); target = e.state.actors[TARGET]
    checks = [v for v in e.events if v.event_type == 'CHECK_ROLLED'
              and v.actor_id == TARGET and v.payload.get('check') == 'Water Check']
    assert len(checks) == 1, 'duplicate teleport/movement rows must share the real owned contest'
    assert checks[0].payload['dc'] == 16
    assert checks[0].payload['success'] is water_success
    if water_success:
        assert target.position != position
        assert sum(before.values())-sum(target.resources.values()) == 1
    else:
        assert target.position == position
        assert target.resources == before
        assert target.bonus_action_available


@pytest.mark.parametrize('water_success',[False,True])
def test_native_flight_technique_uses_same_gate(tmp_path,water_success):
    c,t,mid = fixture(tmp_path,flight=True,water_success=water_success)
    settle(t,mid,rows(c,mid,COURT)[0].candidate_id)
    settle(t,mid,rows(c,mid,SEAL,TARGET)[0].candidate_id)
    turn(t,mid,TARGET)
    e = cold(tmp_path,mid); target = e.state.actors[TARGET]
    before = dict(target.resources)
    choices = rows(c,mid,'tianxia.subpath.qi.cloud_walker.feature.cloud_step')
    assert choices, 'the native flight technique remains available to attempt'
    settle(t,mid,choices[0].candidate_id)
    e = cold(tmp_path,mid); target = e.state.actors[TARGET]
    checks = [v for v in e.events if v.event_type == 'CHECK_ROLLED' and v.actor_id == TARGET
              and v.payload.get('check') == 'Water Check']
    assert len(checks) == 1
    assert checks[0].payload['success'] is water_success
    assert any(v.data.get('fly_speed_ft') for v in target.conditions.values()) is water_success
    if not water_success:
        assert target.resources == before
        assert target.bonus_action_available


def test_failed_seal_gate_cancel_spends_no_costs(tmp_path):
    # Review RB1R item 3: a failed Water check cancels the declaration with spend_activation False,
    # so neither the sealed foe nor the sealer pays anything for the cancelled Cloud Step flight attempt.
    # (Fold Step teleport cancels are pinned by test_native_teleport_contest_before_payment[False].)
    c,t,mid = fixture(tmp_path,flight=True,water_success=False)
    settle(t,mid,rows(c,mid,COURT)[0].candidate_id)
    settle(t,mid,rows(c,mid,SEAL,TARGET)[0].candidate_id)
    turn(t,mid,TARGET)
    e = cold(tmp_path,mid)
    target_before = dict(e.state.actors[TARGET].resources)
    owner_before = dict(e.state.actors[OWNER].resources)
    choices = rows(c,mid,'tianxia.subpath.qi.cloud_walker.feature.cloud_step')
    assert choices, 'the native flight technique remains available to attempt'
    settle(t,mid,choices[0].candidate_id)
    e = cold(tmp_path,mid)
    checks = [v for v in e.events if v.event_type == 'CHECK_ROLLED' and v.actor_id == TARGET
              and v.payload.get('check') == 'Water Check']
    assert len(checks) == 1 and checks[0].payload['success'] is False
    assert e.state.actors[TARGET].resources == target_before
    assert e.state.actors[OWNER].resources == owner_before
    assert e.state.actors[TARGET].bonus_action_available


def test_another_court_is_not_your_court(tmp_path):
    c,t,mid = fixture(tmp_path,foreign_court=True)
    turn(t,mid,TARGET)
    settle(t,mid,rows(c,mid,COURT)[0].candidate_id)
    turn(t,mid,OWNER)
    assert not rows(c,mid,SEAL,TARGET)
    cold(tmp_path,mid)


def test_outside_your_court_and_no_owner(tmp_path):
    c,t,mid = fixture(tmp_path,far=True)
    settle(t,mid,rows(c,mid,COURT)[0].candidate_id)
    assert not rows(c,mid,SEAL,TARGET)
    turn(t,mid,TARGET)
    assert not rows(c,mid,SEAL), 'a creature without the talent gains no seal action'
    cold(tmp_path,mid)


def test_native_healing_and_spoken_technique_consumers(tmp_path):
    c,t,mid = fixture(tmp_path,consumers=True)
    turn(t,mid,TARGET)
    assert rows(c,mid,'WARLEADER_BASE_FIERCE_SHOUT'), 'voice technique is naturally available before seal'
    turn(t,mid,OWNER)
    for _ in range(4):
        settle(t,mid,rows(c,mid,'WATER_BASE_WATER_LASH',TARGET)[0].candidate_id)
        injured = cold(tmp_path,mid).state.actors[TARGET].current_hp < 100
        turn(t,mid,TARGET); turn(t,mid,OWNER)
        if injured: break
    assert injured, 'the target must actually be injured before testing healing denial'
    settle(t,mid,rows(c,mid,COURT)[0].candidate_id)
    settle(t,mid,rows(c,mid,SEAL,TARGET)[0].candidate_id)
    turn(t,mid,TARGET)
    e = cold(tmp_path,mid); hp = e.state.actors[TARGET].current_hp
    assert not rows(c,mid,'WARLEADER_BASE_FIERCE_SHOUT'), 'unclear speech prevents a technique requiring voice'
    heal = rows(c,mid,'LIFE_BASE_MEND_THE_PULSE',TARGET)
    assert heal, 'the Life spell is still an available attempt, with its normal payment'
    settle(t,mid,heal[0].candidate_id)
    e = cold(tmp_path,mid)
    assert e.state.actors[TARGET].current_hp == hp
    assert any('HEALING' in v.reason for v in e.rolls)


def test_native_concentration_save_only_has_disadvantage(tmp_path):
    c,t,mid = fixture(tmp_path,foreign_court=True)
    turn(t,mid,TARGET)
    settle(t,mid,rows(c,mid,COURT)[0].candidate_id)
    turn(t,mid,OWNER)
    settle(t,mid,rows(c,mid,COURT)[0].candidate_id)
    settle(t,mid,rows(c,mid,SEAL,TARGET)[0].candidate_id)
    turn(t,mid,TARGET); turn(t,mid,OWNER)
    settle(t,mid,rows(c,mid,'WATER_BASE_WATER_LASH',TARGET)[0].candidate_id)
    e = cold(tmp_path,mid)
    saves = [v for v in e.events if v.event_type == 'SAVE_ROLLED' and v.actor_id == TARGET
             and v.source_definition_id == 'system:combat.concentration']
    assert saves, 'native damage must trigger concentration maintenance'
    assert saves[-1].payload['mode'] == 'DISADVANTAGE'


@pytest.mark.parametrize('save_success',[False,True])
def test_other_casters_native_drowning_pressure_qualifies_but_soaked_does_not(tmp_path,save_success):
    c,t,mid = fixture(tmp_path,drowning=save_success)
    turn(t,mid,TARGET)
    candidates = [r for r in rows(c,mid,'TAL_WATER_HEAVEN_FALLING_TSUNAMI')
                  if (r.metadata.get('hostiles_in_area') or 0) >= 1]
    assert candidates, 'the native Tsunami placement must cover the seal keeper'
    settle(t,mid,candidates[0].candidate_id, {'choice:needle.area_recipients':[OWNER]})
    turn(t,mid,OWNER)
    e = cold(tmp_path,mid)
    pressure = any(r.condition_id.startswith('condition:typed.mark.drowning_pressure.')
                   for r in e.state.actors[OWNER].conditions.values())
    assert pressure is (not save_success)
    assert bool(rows(c,mid,SEAL,OWNER)) is (not save_success), 'only actual Drowning Pressure qualifies'


@pytest.mark.parametrize('save_success',[False,True])
def test_native_whirlpool_requires_its_actual_restraint(tmp_path,save_success):
    c,t,mid = fixture(tmp_path,whirlpool=save_success)
    turn(t,mid,TARGET)
    e = c._load_session(mid).engine
    choices = []
    for r in rows(c,mid,'WATER_BASE_SHAPE_CURRENT'):
        typed = e.action_catalog[r.source_definition_id].parameters['typed']
        if ('TAL_WATER_WHIRLPOOL_PRISON' in str(typed.get('modifier'))
                and typed.get('option_label') == 'Pressure Basin' and r.destination
                and (r.destination.x,r.destination.y) == (3,6)):
            choices.append(r)
    assert choices, 'the owned Whirlpool Prison modifier must produce a native Pressure Basin placement'
    settle(t,mid,choices[0].candidate_id)
    turn(t,mid,OWNER)
    e = cold(tmp_path,mid)
    restrained = any(r.condition_id == 'condition:typed.restrained'
                     for r in e.state.actors[OWNER].conditions.values())
    assert restrained is (not save_success)
    assert bool(rows(c,mid,SEAL,OWNER)) is (not save_success)


@pytest.mark.parametrize('second_dc', [16, 17])
def test_two_water_courts_each_seal_rolls_against_its_own_dc(tmp_path, second_dc):
    """Two Water Court owners seal one traveller (sealer DCs 16 and second_dc).

    The traveller's Water check easily beats both DCs, so every seal must roll its own check.
    Reusing the first seal's passed roll (same source id, other DC) would leave one check only.
    """
    owner_two = sheet([SEAL, COURT], cp=40)
    owner_two['ability_scores_and_statistics']['technique_save_dc'] = second_dc
    owner_two['identity']['name'] = 'Second Keeper'
    traveller = sheet()
    traveller['identity'].update(name='Traveller', key_ability='DEX')
    next(a for a in traveller['ability_scores_and_statistics']['abilities'] if a['ability'] == 'DEX').update(score=30, modifier=10)
    traveller['spheres_and_talents']['sphere_record_ids'].append('tianxia.sphere.space')
    traveller['spheres_and_talents']['automatic_sphere_component_record_ids'].append('TAL_SPACE_FOLD_STEP')
    second = 'actor:factory.seal-owner-two'
    docs = {OWNER: sheet([SEAL, COURT], cp=40), second: owner_two, TARGET: traveller}
    for aid, doc in docs.items():
        folder = tmp_path/'portable_characters'/aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    ids = [OWNER, second, TARGET]
    c = CombatService(ROOT, tmp_path); t = TabletopService(c, tmp_path)
    bundles = [compile_character(docs[a], actor_id=a, reaction_plan={'ask': True}) for a in ids]
    mid = c._finish_factory_match(bundles, ids,
        {OWNER: 'team:factory', second: 'team:factory', TARGET: 'team:opponents'},
        {OWNER: {'x': 3, 'y': 6}, second: {'x': 3, 'y': 7}, TARGET: {'x': 4, 'y': 6}},
        c.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [OWNER, second], [TARGET],
        control_modes={a: 'MANUAL' for a in ids}, match_seed='ABYSSAL-TWO-COURTS',
        display_name='Abyssal two seals', maximum_rounds=10)['match_id']
    turn(t, mid, OWNER)
    settle(t, mid, rows(c, mid, COURT)[0].candidate_id)
    settle(t, mid, rows(c, mid, SEAL, TARGET)[0].candidate_id)
    turn(t, mid, second)
    settle(t, mid, rows(c, mid, COURT)[0].candidate_id)
    settle(t, mid, rows(c, mid, SEAL, TARGET)[0].candidate_id)
    turn(t, mid, TARGET)
    e = cold(tmp_path, mid); target = e.state.actors[TARGET]
    seal_dcs = sorted(int(r.data['dc']) for r in target.conditions.values() if r.data.get('abyssal_pressure_seal'))
    assert seal_dcs == sorted([16, second_dc])
    position = target.position
    options = [r for r in rows(c, mid, 'TAL_SPACE_FOLD_STEP') if r.destination and r.destination != position]
    assert options
    settle(t, mid, options[0].candidate_id)
    e = cold(tmp_path, mid)
    checks = [v for v in e.events if v.event_type == 'CHECK_ROLLED'
              and v.actor_id == TARGET and v.payload.get('check') == 'Water Check']
    assert sorted(v.payload['dc'] for v in checks) == sorted([16, second_dc])
    assert all(v.payload['success'] for v in checks)


def test_seal_attempt_has_no_unused_intent_parameter():
    # Review F7R optional: seal_attempt's intent argument was unused by every caller; it is removed so a
    # future caller cannot assume the intent is consulted by the gate.
    import inspect
    from combat.ext import water_second_pass as wsp
    assert list(inspect.signature(wsp.seal_attempt).parameters) == ['engine', 'subject', 'source']


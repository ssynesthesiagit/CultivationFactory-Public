"""Acquired Poison Touch through real compilation, table commits and cold replay.

Shared seam guards use authored setup effects only for opposing protection;
the triggering Poison attack and ownership always come from shipped records.
"""
import json
import zipfile
from copy import deepcopy

import pytest

from app.core import FoundryError
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import mgr_t14_poison_touch as pt
from tests.h1_support import ROOT, sheet
from tests.r10_fixup_support import cast_sender, commit
from tests.test_ns1r_r2c_bound_evidence import make
from tests.test_ns1r_non_sphere_authority import insert_project, QI
from tests.ns1r_evidence_helpers import ap_award, commit_authority_event

LEFT, RIGHT = 'actor:factory.pt-left', 'actor:factory.pt-right'
THIRD = 'actor:factory.pt-third'
PARENT = 'tianxia.subpath.qi.poison_cultivator'
DOSE = 'POISON_BASE_DELIVER_THE_DOSE'


@pytest.fixture(autouse=True)
def fake_menu_embeddings(monkeypatch):
    from combat import embedding_rank, menu_rank
    def transport(url, body, timeout):
        count = len(json.loads(body)['input'])
        return json.dumps({'data':[{'index':i, 'embedding':[1]+[0]*(embedding_rank.DIMENSION-1)}
                                   for i in range(count)]}).encode()
    monkeypatch.setattr(menu_rank, '_CLIENT', embedding_rank.EmbeddingClient(transport=transport))


def fixed_dice(monkeypatch, values):
    """Targeted attack fixtures use the first die; turn transitions use the rest.

    Reset at each transactional retry, so a player question never advances the
    script. Turn transitions must not reuse the attack's 19 as a damage die.
    """
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.h1_support import script
    current = Gate4ControllerEngine.execute_intent
    original = getattr(current, '_pt_original', current)
    def execute(engine, intent, *args, **kwargs):
        script(engine, values if intent.target_ids else values[1:])
        return original(engine, intent, *args, **kwargs)
    execute._pt_original = original
    monkeypatch.setattr(Gate4ControllerEngine, 'execute_intent', execute)


@pytest.fixture(scope='module')
def acquired(tmp_path_factory):
    root = tmp_path_factory.mktemp('poison-touch-acquisition')
    cache = {}
    def acquire(cl):
        if cl in cache:
            return cache[cl]
        service, db = make(root / str(cl))
        insert_project(db, 'poison-touch', cl)
        service.initialize_for_project('poison-touch', target_cl=cl, path_ids=[QI], method_id='METHOD-001')
        service.allocate_advancement('poison-touch', {QI: cl-1},
            evidence_id=ap_award(db, service, 'poison-touch', 'METHOD-001', cl, cl-1), idempotency_key=f'pt-cl{cl}')
        with pytest.raises(FoundryError) as error:
            service.select_subpath('poison-touch', QI, PARENT)
        assert error.value.code == 'NS1R_RESTRICTED_TRADITION_ACCESS_REQUIRED'
        proof = commit_authority_event(db, service, 'poison-touch', 'subpath_access', {'selection_id': PARENT})
        service.select_subpath('poison-touch', QI, PARENT, access_source_records=[proof])
        projection = service.combat_subpath_projection('poison-touch')
        assert (pt.FEATURE in projection['source_granted_subpath_feature_record_ids']) is (cl >= 6)
        assert (pt.PRESENCE in projection['source_granted_subpath_feature_record_ids']) is (cl >= 18)
        assert any(p.get('subpath_or_tradition_id') == PARENT for p in service.export_state('poison-touch')['state']['paths'])
        cache[cl] = projection
        return projection
    return acquire


def fight(tmp_path, acquired, *, cl=6, owns=True, second=False, success=False, primary='Qi', protection=None,
          ask=True, effective_cl=None, dc=50, qi=100, repeat=False, third=False, packet_guard=None, ongoing_guard=False, forged_guard=False, attack_feature=DOSE,
          right_owned=None, right_actions=(), left_actions=(), right_hp=None):
    bundles = []
    people = [(LEFT, owns), (RIGHT, second)] + ([(THIRD, False)] if third else [])
    for actor, owner in people:
        doc = sheet([attack_feature], cl=cl, dc=dc, score=14, primary=primary)
        doc['identity'].update(display_name='Poison cultivator' if actor == LEFT else 'Target',
                               proficiency_bonus=4)
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 500
        if actor == RIGHT and right_hp is not None:
            doc['ability_scores_and_statistics']['hit_points']['maximum'] = right_hp
        doc['ability_scores_and_statistics']['primary_resource']['maximum'] = qi
        doc['ability_scores_and_statistics']['initiative'] = {'bonus': 100 if actor == LEFT else -100}
        doc['ability_scores_and_statistics']['technique_attack_bonus'] = 100
        if owner:
            # The native acquired-state producer, not a fabricated ownership row.
            doc['path_and_subpath'] = deepcopy(acquired(cl))
            if effective_cl is not None:
                doc['path_and_subpath']['paths'] = [{'path_id': QI, 'effective_cl': effective_cl}]
        if actor == RIGHT and right_owned is not None:
            doc['path_and_subpath'] = deepcopy(acquired(right_owned))
        if actor == RIGHT and success:
            doc['ability_scores_and_statistics']['abilities'] = [
                {'ability': a, 'score': 210, 'modifier': 100} for a in ('STR','DEX','CON','INT','WIS','CHA')]
        if actor == LEFT and forged_guard:
            doc['forged_techniques'] = [{'technique_id':'forged:pt.native', 'name':'Native forged poison',
                'primary_sphere_effect':{'talent_id':DOSE}, 'base_form':{'form_id':'projection'},
                'drawbacks':[], 'augments':[], 'table_choices':{}, 'cp_cost':{'final':3}, 'action_type':'action'}]
        folder = tmp_path / 'portable_characters' / actor.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        bundle = compile_character(doc, actor_id=actor, reaction_plan={'ask': ask})
        if actor == LEFT and repeat:
            # Reusable seam guard: deliver the same compiled native ability
            # twice in one turn without manufacturing a damage/ownership event.
            extra = deepcopy(next(a for a in bundle['action_catalog'] if a['display_name'] == 'Deliver the Dose'))
            extra['source_definition_id'] += '.repeat_guard'
            extra['display_name'] = 'Another Dose'
            extra['economy'] = 'NONE'
            extra['parameters']['free_primary'] = True
            bundle['actor_template']['action_ids'].append(extra['source_definition_id'])
            bundle['action_catalog'].append(extra)
        if actor == LEFT and packet_guard:
            # Authored multiattack seam guard. The engine, not this fixture,
            # produces each packet's power/component/attack-index receipt.
            extra = deepcopy(next(a for a in bundle['action_catalog'] if a['display_name'] == 'Deliver the Dose'))
            extra['source_definition_id'] += '.packet_guard'
            extra['display_name'] = 'Packet guard'
            extra['economy'] = 'NONE'
            extra['parameters']['free_primary'] = True
            typed = extra['parameters']['typed']
            weapon = deepcopy(next(a['parameters']['typed']['weapon'] for a in bundle['action_catalog']
                if a['display_name'] == 'Unarmed Strike'))
            weapon.update(damage_type='POISON', damage_types=['POISON'], fixed_damage=1)
            typed['weapon'] = weapon
            attached = [] if packet_guard == 'weapon_only' else [
                {'type':'damage','applies_to':'target','flat':2,'damage_types':['poison']}]
            typed['effects'] = [{'type':'attack','attack_kind':'weapon','count':2,
                'on_hit':[{'type':'damage','weapon_damage':True}, *attached]}]
            bundle['actor_template']['action_ids'].append(extra['source_definition_id'])
            bundle['action_catalog'].append(extra)
        if actor == LEFT and ongoing_guard:
            extra = deepcopy(next(a for a in bundle['action_catalog'] if a['display_name'] == 'Deliver the Dose'))
            extra['source_definition_id'] += '.ongoing_guard'
            extra['display_name'] = 'Ongoing guard'
            extra['economy'] = 'NONE'
            extra['parameters']['free_primary'] = True
            extra['parameters']['typed']['effects'] = [{'type':'ongoing','condition':'guard_qi_poison',
                'applies_to':'target','duration':'one_minute', 'turn_start_effects':[
                    {'type':'damage','applies_to':'target','flat':2,'damage_types':['poison']}]}]
            bundle['actor_template']['action_ids'].append(extra['source_definition_id'])
            bundle['action_catalog'].append(extra)
        # Opposing defenses have authored origin facts, committed by a native
        # setup action. No test-supplied ownership or trigger receipt is used.
        if actor == RIGHT and protection:
            action_id = 'action:test.pt.protection'
            bundle['actor_template']['action_ids'].append(action_id)
            bundle['action_catalog'].append({'source_definition_id': action_id, 'display_name': 'Protection setup',
                'owner_id': actor, 'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'SELF',
                'parameters': {'free_primary': True, 'typed': {'numbers': {'cl': cl, 'save_dc': 50},
                    'duration': {'kind': 'minutes', 'amount': 1}, 'effects': [protection], 'riders': []}}})
        # Authored opposing actions only (an attack the target makes, a heal the target
        # uses, or one single-type Poison packet used to read the owner's defenses); the
        # owner's own effects always come from shipped records.
        for action_id, name, effects, target_kind in (*(right_actions if actor == RIGHT else ()),
                                                     *(left_actions if actor == LEFT else ())):
            bundle['actor_template']['action_ids'].append(action_id)
            bundle['action_catalog'].append({'source_definition_id': action_id, 'display_name': name,
                'owner_id': actor, 'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': target_kind,
                'range_ft': 60,
                'parameters': {'free_primary': True, 'typed': {'source': action_id,
                    'numbers': {'cl': cl, 'save_dc': dc, 'pb': 4, 'key_mod': 2},
                    'duration': {'kind': 'instant', 'concentration': False},
                    'effects': deepcopy(effects), 'riders': []}}})
        from combat.canonical import canonical_sha256
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    arena = combat.tabletop_maps.save({'display_name': 'Poison Touch yard', 'width_squares': 12, 'height_squares': 8,
        'walls': [], 'starts': {'team1': [[3,4]], 'team2': [[6,4]]}})
    actors = [a for a, _ in people]
    teams = {LEFT:'team:a', RIGHT:'team:a' if third else 'team:b', **({THIRD:'team:b'} if third else {})}
    mid = combat._finish_factory_match(bundles, actors, teams,
        {LEFT:{'x':3,'y':4}, RIGHT:{'x':6,'y':4}, **({THIRD:{'x':7,'y':6}} if third else {})},
        combat.factory_arenas()['battlefield:map.' + arena['map_id']],
        [LEFT, RIGHT] if third else [LEFT], [THIRD] if third else [RIGHT],
        control_modes={a:'MANUAL' for a in actors}, match_seed='PT-native',
        maximum_rounds=30, display_name='Poison Touch regression')['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, LEFT)
    return combat, table, mid


def cold(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def end(table, mid):
    from tests.test_lock2_persistence import act
    result = act(table, mid, 'end')
    assert result['status'] == 'COMMITTED', result


def turn(table, mid, actor):
    for _ in range(5):
        if table.state(mid)['menu']['actor_id'] == actor:
            return
        end(table, mid)
    raise AssertionError('turn did not advance')


def choose(prompt, use=True):
    options = (prompt.get('choice') or {}).get('options') or []
    poison = next((o['id'] for o in options if o['id'].lower() == 'poison'), None)
    touch = 'poison_touch' in str(prompt.get('context'))
    return (poison or (options[0]['id'] if options else None), use if touch else bool(poison))


def strike(combat, table, mid, use=True, target=RIGHT):
    return commit(cast_sender(combat, table, mid, 'Deliver the Dose', target=target),
                  lambda prompt: choose(prompt, use))


def held(engine, target=RIGHT, source=LEFT):
    return [c for c in engine.state.actors[target].conditions.values()
            if c.condition_id == 'condition:typed.poison_touch' and c.source_actor_id == source]


def test_owner_compilation_seals_catalog_and_forged_activations():
    """A real owner compiles every action through compile_action (pre-fix KeyError).

    The compiler-owned activation list seals the owned catalog rows and the exact
    ID a Forged Technique compiler emits, so the packet receipt can report
    ownership without borrowing a parent's catalog identity.
    """
    doc = sheet([pt.FEATURE, DOSE], cl=6)
    doc['forged_techniques'] = [{'technique_id':'forged:pt.compile', 'name':'Compiled forged poison',
        'primary_sphere_effect':{'talent_id':DOSE}, 'base_form':{'form_id':'projection'},
        'drawbacks':[], 'augments':[], 'table_choices':{}, 'cp_cost':{'final':3}, 'action_type':'action'}]
    bundle = compile_character(doc, actor_id=LEFT)
    dose = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Deliver the Dose')
    sealed = dose['parameters']['typed']
    assert sealed['track_damage_provenance'] is True
    assert DOSE in sealed['known_damage_features'] and pt.FEATURE in sealed['known_damage_features']
    forged = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Compiled forged poison')
    forged_sealed = forged['parameters']['typed']
    assert forged_sealed['known_damage_features'].count('forged:pt.compile') == 1
    assert forged_sealed['power_resource_id'] == pt.QI


def test_acquired_projection_grants_and_seals_poison_touch(acquired):
    """The NS1R projection carries bindings, so its granted list compiles.

    This is the real acquisition shape the table fixtures below use; without the
    compiler's documented consumer the resolver and its sealed receipt are
    absent and every applied-Touch assertion fails.
    """
    doc = sheet([DOSE], cl=6)
    doc['path_and_subpath'] = deepcopy(acquired(6))
    bundle = compile_character(doc, actor_id=LEFT)
    resolver = next(a for a in bundle['action_catalog'] if a['parameters'].get('poison_touch_resolver'))
    effects = resolver['parameters']['typed']['effects']
    # The reviewed row (not a stale generated model pass): successful-save
    # damage and the start-turn carrier both exist at runtime.
    assert effects[0]['on_success'] and effects[0]['on_fail'][0]['turn_start_effects']
    dose = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Deliver the Dose')
    sealed = dose['parameters']['typed']
    assert sealed['track_damage_provenance'] is True
    assert DOSE in sealed['known_damage_features'] and pt.FEATURE in sealed['known_damage_features']


@pytest.mark.parametrize('cl,count', [(6,1),(11,2),(17,3)])
def test_acquired_native_trigger_tick_and_cold_reload(tmp_path, monkeypatch, acquired, cl, count):
    fixed_dice(monkeypatch, [19] + [1]*80)
    combat, table, mid = fight(tmp_path, acquired, cl=cl)
    prompts = strike(combat, table, mid)
    assert any('Poison Touch' in p.get('prompt', p.get('description','')) or 'poison_touch' in str(p) for p in prompts)
    engine = cold(tmp_path, mid)
    effect = held(engine)
    assert len(effect) == 1
    assert effect[0].data['rule']['attacks_have'] == 'DISADVANTAGE'
    assert effect[0].expires_on.startswith('START_OF_SLOT_AT:')
    assert effect[0].data['ongoing_effects'][0]['dice']['count'] == count
    assert engine.state.actors[LEFT].resources[pt.QI] == 98  # native Dose is free; Touch costs 2 Qi
    receipts = [e.payload['damage_origin'] for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                and e.actor_id == LEFT and 'damage_origin' in e.payload]
    assert any(o['feature_id'] == DOSE and o['owned'] == 1 and o['qi_powered'] == 1 for o in receipts)
    hp = engine.state.actors[RIGHT].current_hp
    end(table, mid)
    after = cold(tmp_path, mid)
    assert after.state.current_actor_id == RIGHT
    assert after.state.actors[RIGHT].current_hp == hp - count
    end(table, mid)
    assert len(held(cold(tmp_path, mid))) == 1  # failed end-turn save retains whole carrier


@pytest.mark.parametrize('owns,primary,use,effective_cl', [(False,'Qi',True,None),(True,'Stamina',True,None),
    (True,'Qi',False,None),(True,'Qi',True,5)])
def test_trigger_boundaries_do_not_apply_or_spend(tmp_path, monkeypatch, acquired, owns, primary, use, effective_cl):
    fixed_dice(monkeypatch, [19] + [1]*80)
    combat, table, mid = fight(tmp_path, acquired, owns=owns, primary=primary, effective_cl=effective_cl)
    strike(combat, table, mid, use=use)
    engine = cold(tmp_path, mid)
    assert not held(engine)
    assert pt.USED not in engine.state.actors[LEFT].turn_flags


def test_success_damages_without_condition(tmp_path, monkeypatch, acquired):
    fixed_dice(monkeypatch, [19] + [1]*80)
    combat, table, mid = fight(tmp_path, acquired, cl=11, success=True)
    strike(combat, table, mid)
    engine = cold(tmp_path, mid)
    assert not held(engine)
    packets = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and pt.FEATURE in e.source_definition_id]
    assert len(packets) == 1 and packets[0].payload['hp_damage'] == 2


@pytest.mark.parametrize('condition_immune,damage_immune', [(True,False),(False,True),(True,True)])
def test_immunities_are_independent(tmp_path, monkeypatch, acquired, condition_immune, damage_immune):
    fixed_dice(monkeypatch, [19] + [1]*80)
    protection = {'type':'source_protection_profile', 'applies_to':'self', 'duration':'one_minute',
        'protection_authority':{'origin':'unknown','authority':'absolute'},
        'conditions':['poisoned'] if condition_immune else [],
        'defenses':[{'kind':'immunity','damage_types':['POISON']}] if damage_immune else []}
    combat, table, mid = fight(tmp_path, acquired, protection=protection)
    turn(table, mid, RIGHT)
    commit(cast_sender(combat, table, mid, 'Protection setup'), lambda p:(None,False))
    turn(table, mid, LEFT)
    strike(combat, table, mid)
    engine = cold(tmp_path, mid)
    if damage_immune:
        assert not held(engine)  # no triggering Poison damage actually dealt
    else:
        effect = held(engine)[0]
        assert not effect.data['rule']  # damage/repeat carrier survives Poisoned immunity
        hp = engine.state.actors[RIGHT].current_hp
        end(table, mid)
        assert cold(tmp_path, mid).state.actors[RIGHT].current_hp == hp-1


def test_repeat_success_ends_carrier_and_tick(tmp_path, monkeypatch, acquired):
    fixed_dice(monkeypatch, [19] + [1]*80)
    combat, table, mid = fight(tmp_path, acquired, dc=10)
    strike(combat, table, mid)
    end(table, mid)
    fixed_dice(monkeypatch, [20]*80)
    end(table, mid)
    assert not held(cold(tmp_path, mid))
    before = cold(tmp_path, mid).state.actors[RIGHT].current_hp
    end(table, mid)
    assert cold(tmp_path, mid).state.actors[RIGHT].current_hp == before


@pytest.mark.parametrize('ask', [True,False])
def test_ai_actor_decides_its_owned_trigger_automatically(tmp_path, monkeypatch, acquired, ask):
    from tests.hunt15_support import action_sender
    fixed_dice(monkeypatch, [19] + [1]*80)
    combat, table, mid = fight(tmp_path, acquired, ask=ask)
    prompts = commit(action_sender(combat, table, mid, 'Deliver the Dose', ai=True, target_id=RIGHT), choose)
    # LOCAL_AUTO owns this creature's decisions even if its stored reaction
    # plan says Ask. A separate off-turn test retains a MANUAL owner's Ask
    # choice while another creature is taking its AI turn.
    assert not any('poison_touch' in str(p.get('context')) for p in prompts)
    engine = cold(tmp_path, mid)
    assert held(engine)
    assert engine.state.actors[LEFT].resources[pt.QI] == 98


@pytest.mark.parametrize('profile,cl,expected', [({},20,True),
    ({'origin':'ordinary_biology','authority':'ordinary'},6,False),
    ({'origin':'cultivated','authority':'ordinary','source_cl':5},11,False),
    ({'origin':'cultivated','authority':'ordinary','source_cl':6},11,True),
    ({'origin':'cultivated','authority':'ordinary','source_cl':20},11,True),
    ({'origin':'cultivated','authority':'absolute','source_cl':1},20,True)])
def test_source_authority_guard(profile, cl, expected):
    from combat.source_authority import protection_applies
    assert protection_applies({'numbers':{'cl':cl}, 'authority_contest':{
        'cultivated':1,'bypass_biology':1,'decisive_gap':6}}, profile) is expected


def test_packet_receipt_is_opt_in_and_separates_weapon_from_technique():
    from types import SimpleNamespace
    from combat.damage_provenance import metadata
    action = SimpleNamespace(costs=((pt.QI,2),), owner_id='actor:receipt')
    ctx = SimpleNamespace(typed={}, effect_source=None, action=action, actor=SimpleNamespace(entity_id='actor:receipt'))
    assert metadata(ctx) == {}
    ctx.typed = {'source':DOSE,'track_damage_provenance':True,'known_damage_features':[DOSE], 'weapon':{}}
    ctx.numbers = {'cl':11}
    ctx.damage_attack_index = 2
    ctx.damage_packet_kind = 'weapon'
    assert metadata(ctx)['damage_origin']['component'] == 'weapon'
    ctx.damage_packet_kind = 'technique'
    assert metadata(ctx)['damage_origin']['component'] == 'technique'
    assert metadata(ctx)['damage_origin']['owned'] == 1
    action.owner_id = 'actor:another_creature'
    assert metadata(ctx)['damage_origin']['owned'] == 0


@pytest.mark.parametrize('qi,die', [(1,19),(100,1)])
def test_no_qi_and_missed_attack_do_not_spend(tmp_path, monkeypatch, acquired, qi, die):
    fixed_dice(monkeypatch, [die] + [1]*80)
    combat, table, mid = fight(tmp_path, acquired, qi=qi)
    prompts = strike(combat, table, mid)
    engine = cold(tmp_path, mid)
    assert not held(engine) and pt.USED not in engine.state.actors[LEFT].turn_flags
    assert not any('poison_touch' in str(p.get('context')) for p in prompts)
    assert engine.state.actors[LEFT].resources[pt.QI] == qi


def test_reapplication_refreshes_one_source_without_stacking(tmp_path, monkeypatch, acquired):
    fixed_dice(monkeypatch, [19] + [1]*80)
    combat, table, mid = fight(tmp_path, acquired)
    strike(combat, table, mid)
    original = held(cold(tmp_path, mid))[0]
    end(table, mid)
    end(table, mid)
    strike(combat, table, mid)
    engine = cold(tmp_path, mid)
    fresh = held(engine)
    assert len(fresh) == 1 and fresh[0].instance_id != original.instance_id
    assert fresh[0].expires_on != original.expires_on
    assert engine.state.actors[LEFT].resources[pt.QI] == 96


def test_second_native_delivery_same_turn_keeps_one_payment(tmp_path, monkeypatch, acquired):
    fixed_dice(monkeypatch, [19] + [1]*80)
    combat, table, mid = fight(tmp_path, acquired, repeat=True)
    strike(combat, table, mid)
    original = held(cold(tmp_path, mid))[0].instance_id
    prompts = commit(cast_sender(combat, table, mid, 'Another Dose', target=RIGHT), choose)
    engine = cold(tmp_path, mid)
    assert held(engine)[0].instance_id == original
    assert engine.state.actors[LEFT].resources[pt.QI] == 98
    assert not any('poison_touch' in str(p.get('context')) for p in prompts)


@pytest.mark.parametrize('ai_turn', [False,True])
def test_ongoing_qi_damage_retains_owner_choice_on_another_creatures_turn(tmp_path, monkeypatch, acquired, ai_turn):
    fixed_dice(monkeypatch, [19] + [1]*80)
    combat, table, mid = fight(tmp_path, acquired, ongoing_guard=True)
    commit(cast_sender(combat, table, mid, 'Ongoing guard', target=RIGHT), choose)
    if ai_turn:
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode='LOCAL_AUTO')
    state = table.state(mid)
    menu = state['menu']
    prompts = commit(lambda answers:table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'],
        state['last_sequence'], list(answers)), choose)
    assert any('poison_touch' in str(p.get('context')) for p in prompts)
    engine = cold(tmp_path, mid)
    assert engine.state.current_actor_id == RIGHT
    assert held(engine) and engine.state.actors[LEFT].resources[pt.QI] == 98
    assert RIGHT in engine.state.actors[LEFT].turn_flags[pt.USED]


def test_separate_casters_keep_independent_applications(tmp_path, monkeypatch, acquired):
    fixed_dice(monkeypatch, [19] + [1]*80)
    combat, table, mid = fight(tmp_path, acquired, second=True, third=True)
    strike(combat, table, mid, target=THIRD)
    turn(table, mid, RIGHT)
    strike(combat, table, mid, target=THIRD)
    engine = cold(tmp_path, mid)
    assert len(held(engine, THIRD, LEFT)) == len(held(engine, THIRD, RIGHT)) == 1
    assert engine.state.actors[LEFT].resources[pt.QI] == engine.state.actors[RIGHT].resources[pt.QI] == 98


def test_native_constructed_feature_has_its_own_owned_power_receipt(tmp_path, monkeypatch, acquired):
    fixed_dice(monkeypatch, [19] + [1]*80)
    combat, table, mid = fight(tmp_path, acquired, forged_guard=True)
    commit(cast_sender(combat, table, mid, 'Native forged poison', target=RIGHT), choose)
    engine = cold(tmp_path, mid)
    assert held(engine)
    assert engine.state.actors[LEFT].resources[pt.QI] == 95
    receipts = [e.payload['damage_origin'] for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                and 'damage_origin' in e.payload and e.payload['damage_origin']['feature_id']=='forged:pt.native']
    assert receipts and all(o['owned']==1 and o['qi_powered']==1 for o in receipts)


@pytest.mark.parametrize('packet_guard,first_miss,applied', [('weapon_only',False,False),
    ('mixed',False,True), ('mixed',True,False)])
def test_native_packet_seam_preserves_components_and_first_missed_delivery(
        tmp_path, monkeypatch, acquired, packet_guard, first_miss, applied):
    fixed_dice(monkeypatch, ([1,19] if first_miss else [19]) + [1]*80)
    combat, table, mid = fight(tmp_path, acquired, packet_guard=packet_guard)
    commit(cast_sender(combat, table, mid, 'Packet guard', target=RIGHT), choose)
    engine = cold(tmp_path, mid)
    assert bool(held(engine)) is applied
    packets = [e.payload for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
               and e.source_definition_id.endswith('.packet_guard')]
    assert packets
    assert any(p['damage_origin']['component'] == 'weapon' for p in packets)
    if packet_guard == 'mixed':
        assert any(p['damage_origin']['component'] == 'technique' for p in packets)
    if first_miss:
        assert all(p['damage_origin']['attack_index'] == 2 for p in packets)


@pytest.mark.parametrize('origin,authority,source_cl,trigger', [
    ('ordinary_biology','ordinary',1,True), ('cultivated','ordinary',5,True),
    ('cultivated','ordinary',6,False), ('cultivated','ordinary',20,False),
    ('ordinary_biology','absolute',1,False), ('unknown','ordinary',1,False)])
def test_source_qualified_protection_producer_and_consumers_through_table(
        tmp_path, monkeypatch, acquired, origin, authority, source_cl, trigger):
    fixed_dice(monkeypatch, [19] + [1]*80)
    protection = {'type':'source_protection_profile','applies_to':'self','duration':'one_minute',
        'protection_authority':{'origin':origin,'authority':authority,'source_cl':source_cl},
        'conditions':['poisoned'], 'defenses':[{'kind':'immunity','damage_types':['POISON']}]}
    combat, table, mid = fight(tmp_path, acquired, cl=11, protection=protection)
    turn(table, mid, RIGHT)
    commit(cast_sender(combat, table, mid, 'Protection setup'), lambda p:(None,False))
    turn(table, mid, LEFT)
    strike(combat, table, mid)
    engine = cold(tmp_path, mid)
    assert bool(held(engine)) is trigger
    if trigger:
        assert held(engine)[0].data['rule']['attacks_have'] == 'DISADVANTAGE'
        assert held(engine)[0].data['source_cl'] == 11


def test_poison_authority_does_not_bypass_other_damage_or_condition_protections(tmp_path, monkeypatch, acquired):
    fixed_dice(monkeypatch, [19] + [1]*80)
    protection = {'type':'source_protection_profile','applies_to':'self','duration':'one_minute',
        'protection_authority':{'origin':'ordinary_biology','authority':'ordinary','source_cl':1},
        'conditions':['frightened'], 'defenses':[{'kind':'immunity','damage_types':['FIRE']}]}
    combat, table, mid = fight(tmp_path, acquired, attack_feature='FIRE_BASE_IGNITE', protection=protection)
    turn(table, mid, RIGHT)
    commit(cast_sender(combat, table, mid, 'Protection setup'), lambda p:(None,False))
    turn(table, mid, LEFT)
    engine = cold(tmp_path, mid)
    hp = engine.state.actors[RIGHT].current_hp
    from combat.typed_executor import Context, condition_immune
    action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and a.parameters.get('poison_touch_resolver'))
    ctx = Context(engine, engine.state.actors[LEFT], action, None, action.parameters['typed'],
                  [engine.state.actors[RIGHT]], engine.state.actors[RIGHT], {})
    assert condition_immune(engine, engine.state.actors[RIGHT], 'frightened', source_context=ctx)
    commit(cast_sender(combat, table, mid, 'Ignite', target=RIGHT), choose)
    assert cold(tmp_path, mid).state.actors[RIGHT].current_hp == hp


def test_owned_capstone_requires_paid_active_state(tmp_path, monkeypatch, acquired):
    fixed_dice(monkeypatch, [19] + [1]*80)
    combat, table, mid = fight(tmp_path, acquired, cl=18)
    strike(combat, table, mid)
    engine = cold(tmp_path, mid)
    assert engine.state.actors[LEFT].resources[pt.QI] == 98
    assert held(engine)[0].data['ongoing_effects'][0]['dice']['count'] == 3
    end(table, mid)
    end(table, mid)
    commit(cast_sender(combat, table, mid, 'Decaying Presence'), lambda p:(None,False))
    active = cold(tmp_path, mid)
    assert active.state.actors[LEFT].resources[pt.QI] == 90
    from combat.ext.feature_state import override_for
    assert override_for(active.state.actors[LEFT], pt.FEATURE, source_feature=pt.PRESENCE) == {'cost':0,'tick_dice':4}
    strike(combat, table, mid)
    engine = cold(tmp_path, mid)
    assert engine.state.actors[LEFT].resources[pt.QI] == 90
    assert held(engine)[0].data['ongoing_effects'][0]['dice']['count'] == 3
    assert not any('Decaying Presence' in c.display_name for c in engine.legal_candidates())  # once per scene
    before = engine.state.actors[RIGHT].current_hp
    # Decaying Presence offers its once-a-turn 2d8 to the owner even on another
    # creature's turn (the Poison Touch tick); this test declines it so the tick's
    # own 4d6 remains the only damage.
    from tests.worker2_support import settle as settle_worker
    settle_worker(table, mid, table.state(mid)['menu']['end_turn'],
                  choices={'choice:needle.lord_of_decay_bonus': None})
    assert cold(tmp_path, mid).state.actors[RIGHT].current_hp == before-4
    # Guard the dynamic consumer separately: ending the active state must not
    # leave 4d6 baked into a contracted poison's stored base payload.
    from types import SimpleNamespace
    from combat.ext.feature_state import STATE
    owner_copy = engine.state.actors[LEFT].model_copy(deep=True)
    owner_copy.conditions = {iid:c for iid,c in owner_copy.conditions.items() if c.condition_id != STATE}
    action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and a.parameters.get('poison_touch_resolver'))
    base = held(engine)[0].data['ongoing_effects']
    assert pt.active_tick(base, SimpleNamespace(actor=owner_copy, action=action), held(engine)[0]) is None
    assert base[0]['dice']['count'] == 3


def test_finite_minute_expires_through_real_turns(tmp_path, monkeypatch, acquired):
    fixed_dice(monkeypatch, [19] + [1]*80)
    combat, table, mid = fight(tmp_path, acquired)
    strike(combat, table, mid)
    assert held(cold(tmp_path, mid))
    for _ in range(20):
        end(table, mid)
    assert not held(cold(tmp_path, mid))


# ------------------------------------------------------------------ Lord of Decay (CL18, same acquired record)
LOD = 'tianxia.subpath.qi.poison_cultivator.feature.lord_of_decay'
CLOUD = 'tianxia.subpath.qi.poison_cultivator.feature.toxic_cloud'
POISONED = 'condition:typed.poisoned'
NO_HEAL = 'condition:typed.lord_of_decay_no_heal'
VENOM = 'action:test.lod.venom'
HEAL = 'action:test.lod.heal'


def poisoned(engine, actor_id):
    return any(c.condition_id == POISONED or (c.data or {}).get('base_condition') == 'poisoned'
               for c in engine.state.actors[actor_id].conditions.values())


def test_lord_of_decay_owner_is_immune_to_poison_damage_and_poisoned(tmp_path, monkeypatch, acquired):
    """Printed first clause: "Gain Immunity to Poison damage and Poisoned"."""
    fixed_dice(monkeypatch, [19] + [4]*80)
    venom = [{'type': 'damage', 'applies_to': 'target', 'flat': 9, 'damage_types': ['poison']},
             {'type': 'condition', 'condition': 'poisoned', 'applies_to': 'target'}]
    combat, table, mid = fight(tmp_path, acquired, cl=18,
        right_actions=[(VENOM, 'Venom Bolt', venom, 'ANY_CREATURE')])
    hp = cold(tmp_path, mid).state.actors[LEFT].current_hp
    turn(table, mid, RIGHT)
    commit(cast_sender(combat, table, mid, 'Venom Bolt', target=LEFT), lambda p: (None, False))
    engine = cold(tmp_path, mid)
    assert engine.state.actors[LEFT].current_hp == hp, 'a Poison packet cannot hurt the Poison-immune owner'
    assert not poisoned(engine, LEFT)


BITES = 'action:test.lod.bite'
BITE = [{'type': 'damage', 'applies_to': 'target', 'flat': 18, 'damage_types': ['poison']}]


@pytest.mark.parametrize('defence,authority,damage', [
    ('resistance', 'ordinary', 18),   # Supreme Venom ignores ordinary Poison Resistance
    ('resistance', 'artifact', 9),    # an absolute Resistance still halves it
    ('immunity', 'ordinary', 18),     # ordinary Poison Immunity counts as Resistance, then is ignored
    ('immunity', 'artifact', 0),      # artifact-grade Immunity is never ordinary
])
def test_supreme_venom_only_beats_ordinary_poison_defenses(tmp_path, monkeypatch, acquired, defence, authority, damage):
    """Supreme Venom: ordinary Resistance ignored, ordinary Immunity treated as Resistance."""
    fixed_dice(monkeypatch, [19] + [4]*80)
    protection = {'type': 'source_protection_profile', 'applies_to': 'self', 'duration': 'one_minute',
        'protection_authority': {'origin': 'cultivated', 'authority': authority, 'source_cl': 18},
        'defenses': [{'kind': defence, 'damage_types': ['POISON']}]}
    combat, table, mid = fight(tmp_path, acquired, cl=18, protection=protection,
        left_actions=[(BITES, 'Venom Bite', BITE, 'ANY_CREATURE')])
    turn(table, mid, RIGHT)
    commit(cast_sender(combat, table, mid, 'Protection setup'), lambda p: (None, False))
    turn(table, mid, LEFT)
    before = cold(tmp_path, mid).state.actors[RIGHT].current_hp
    commit(cast_sender(combat, table, mid, 'Venom Bite', target=RIGHT), lambda p: (None, False))
    after = cold(tmp_path, mid).state.actors[RIGHT].current_hp
    assert before - after == damage


def test_presence_adds_one_2d8_packet_to_a_poisoned_creature_it_damaged(tmp_path, monkeypatch, acquired):
    """Printed Decaying Presence clause: once a turn, 2d8 Poison or Necrotic to one Poisoned creature."""
    fixed_dice(monkeypatch, [19] + [4]*150)
    combat, table, mid = fight(tmp_path, acquired, cl=18)
    strike(combat, table, mid)                       # turn 1: the target becomes Poisoned
    engine = cold(tmp_path, mid)
    assert poisoned(engine, RIGHT)
    assert not [e for e in engine.events if e.payload.get('display_source_id') == LOD
                and e.event_type == 'DAMAGE_COMMITTED']
    commit(cast_sender(combat, table, mid, 'Decaying Presence'), lambda p: (None, False))
    assert cold(tmp_path, mid).state.actors[LEFT].resources[pt.QI] == 90
    # The printed clause asks its owner on ANY turn its Poison damage lands, and the
    # Poison Touch tick damages a Poisoned creature at the start of that creature's
    # turn. Decline that one so the strike below is this test's only bonus packet.
    from tests.worker2_support import settle as settle_worker
    settle_worker(table, mid, table.state(mid)['menu']['end_turn'],
                  choices={'choice:needle.lord_of_decay_bonus': None})
    settle_worker(table, mid, table.state(mid)['menu']['end_turn'],
                  choices={'choice:needle.lord_of_decay_bonus': None})  # back to the owner's next turn
    prompts = strike(combat, table, mid)
    engine = cold(tmp_path, mid)
    bonus = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
             and e.payload.get('display_source_id') == LOD and RIGHT in e.target_ids]
    assert len(bonus) == 1
    assert int(bonus[0].payload['rolled_or_pending_damage']) == 2 * 4  # 2d8, dice scripted to 4
    assert str(bonus[0].payload['damage_type']).upper() in ('POISON', 'NECROTIC')
    assert any('Lord of Decay' in str(p) and 'Target' in str(p) for p in prompts)
    # Once per turn: the reaction flag, not a second packet, on a later packet of the same turn.
    assert engine.state.actors[LEFT].turn_flags.get('_turn_lord_of_decay_bonus')


def test_toxic_cloud_denies_healing_after_a_failed_save_inside_it(tmp_path, monkeypatch, acquired):
    """Printed Decaying Presence clause: a creature failing a save inside Toxic Cloud cannot regain Hit Points."""
    fixed_dice(monkeypatch, [19] + [1]*80)
    heal = [{'type': 'healing', 'applies_to': 'self', 'flat': 5}]
    combat, table, mid = fight(tmp_path, acquired, cl=18,
        right_actions=[(HEAL, 'Second Wind', heal, 'SELF')])
    commit(cast_sender(combat, table, mid, 'Decaying Presence'), lambda p: (None, False))
    commit(cast_sender(combat, table, mid, 'Toxic Cloud', at=(6, 4)), lambda p: (None, False))
    end(table, mid)                                  # the target's turn starts inside the cloud and its save fails
    engine = cold(tmp_path, mid)
    assert any(c.condition_id == NO_HEAL and c.source_actor_id == LEFT
               for c in engine.state.actors[RIGHT].conditions.values())
    hp = engine.state.actors[RIGHT].current_hp
    commit(cast_sender(combat, table, mid, 'Second Wind'), lambda p: (None, False))
    assert cold(tmp_path, mid).state.actors[RIGHT].current_hp == hp


def test_presence_removes_concentration_from_toxic_cloud_only_while_active(tmp_path, monkeypatch, acquired):
    """Printed Decaying Presence clause: "Toxic Cloud needs no Concentration"."""
    fixed_dice(monkeypatch, [19] + [4]*80)
    combat, table, mid = fight(tmp_path, acquired, cl=18)
    commit(cast_sender(combat, table, mid, 'Decaying Presence'), lambda p: (None, False))
    commit(cast_sender(combat, table, mid, 'Toxic Cloud', at=(6, 4)), lambda p: (None, False))
    engine = cold(tmp_path, mid)
    zone = next(z for z in engine.state.zones.values() if z.trigger_profile.get('name') == 'Toxic Cloud')
    assert zone.concentration_link is False
    assert engine.state.actors[LEFT].concentration is None
    assert zone.duration_rounds == 10, 'the printed 1-minute duration still runs on the round clock'
    from combat.ext.feature_state import active
    assert active(engine.state.actors[LEFT], LOD).get(CLOUD) == {'concentration': 0, 'origin': 1}


def test_feast_of_decay_returns_two_qi_when_a_touched_hostile_falls(tmp_path, monkeypatch, acquired):
    """Printed Feast of Decay: once a round, regain 2 Qi when a qualifying touched creature is reduced to 0."""
    fixed_dice(monkeypatch, [19] + [4]*80)
    combat, table, mid = fight(tmp_path, acquired, cl=18, right_hp=20)
    strike(combat, table, mid)                       # 18 damage leaves 2 HP and applies Poison Touch
    engine = cold(tmp_path, mid)
    assert held(engine) and engine.state.actors[RIGHT].current_hp == 2
    before = engine.state.actors[LEFT].resources[pt.QI]
    end(table, mid)                                  # its start-of-turn tick reduces it to 0
    engine = cold(tmp_path, mid)
    assert engine.state.actors[RIGHT].current_hp == 0
    assert engine.state.actors[LEFT].resources[pt.QI] == before + 2
    assert any('Feast of Decay' in str(e.payload.get('log')) for e in engine.events)

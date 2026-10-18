"""Bone Monarch: restricted acquisition -> native table intent -> cold replay.

No live model transports. Dice are fixed at the intent boundary so retries of
human choices replay the same roll rather than consuming a test-only receipt.
"""
from copy import deepcopy
import json

import pytest

from app.core import FoundryError
from combat.factory_compiler import compile_character
from tests.h1_support import ROOT, sheet, script
from tests.test_ns1r_r2c_bound_evidence import make
from tests.test_ns1r_non_sphere_authority import insert_project
from tests.ns1r_evidence_helpers import ap_award, commit_authority_event, access_evidence
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn

BODY = 'tianxia.path.body_refining'
PARENT = 'tianxia.subpath.body.bone_monarch'
PREFIX = PARENT + '.feature.'
STAMINA = 'resource:core.stamina'


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch):
    from combat import embedding_rank, menu_rank
    def transport(url, body, timeout):
        return json.dumps({'data': [{'index': i, 'embedding': [1] + [0] * (embedding_rank.DIMENSION - 1)}
                                   for i, _ in enumerate(json.loads(body)['input'])]}).encode()
    monkeypatch.setattr(menu_rank, '_CLIENT', embedding_rank.EmbeddingClient(transport=transport))


@pytest.fixture(scope='module')
def acquired(tmp_path_factory):
    root = tmp_path_factory.mktemp('bone-acquisition')
    service, db = make(root)
    cache = {}
    def acquire(cl, subpath=PARENT):
        key = (cl, subpath)
        if key not in cache:
            project = subpath.rsplit('.', 1)[-1] + '-' + str(cl)
            insert_project(db, project, cl)
            method = 'METHOD-002'  # The real Body-refining AP route; METHOD-001 grants Qi AP only.
            service.initialize_for_project(project, target_cl=cl, path_ids=[BODY], method_id=method,
                access_source_records=access_evidence(db, service, project, method))
            service.allocate_advancement(project, {BODY: cl - 1},
                evidence_id=ap_award(db, service, project, method, cl,
                    (cl - 1) * service.method_burden_multiplier(service.methods[method])), idempotency_key=project)
            with pytest.raises(FoundryError) as error:
                service.select_subpath(project, BODY, subpath)
            assert error.value.code == 'NS1R_RESTRICTED_TRADITION_ACCESS_REQUIRED'
            proof = commit_authority_event(db, service, project, 'subpath_access', {'selection_id': subpath})
            service.select_subpath(project, BODY, subpath, access_source_records=[proof])
            cache[key] = service.combat_subpath_projection(project)
        return deepcopy(cache[key])
    return acquire


def scenario(tmp_path, acquired, *, cl=14, owns=True, effective_cl=None, foe=None, ordered=False, **kwargs):
    doc = sheet([], cl=cl, primary='Stamina', name='Bone sovereign')
    doc['identity']['path'] = 'Body Refining'
    if owns:
        doc['path_and_subpath'] = acquired(cl)
        if effective_cl is not None:
            doc['path_and_subpath']['paths'][0]['effective_cl'] = effective_cl
    doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
    if ordered:
        doc['ability_scores_and_statistics']['initiative'] = {'bonus': -100}
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    return fixture(tmp_path, [], cl=cl, owner_bundle=owner, foe_sheet=foe,
                   positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 7}, FOE: {'x': 4, 'y': 6}},
                   seed='BONE-NATIVE', **kwargs)


def fixed(monkeypatch, values):
    from combat.gate4_engine import Gate4ControllerEngine
    original = getattr(Gate4ControllerEngine.execute_intent, '_bone_original', Gate4ControllerEngine.execute_intent)
    def execute(engine, intent, *args, **kwargs):
        script(engine, values if intent.target_ids else values[1:])
        return original(engine, intent, *args, **kwargs)
    execute._bone_original = original
    monkeypatch.setattr(Gate4ControllerEngine, 'execute_intent', execute)


def play(combat, table, mid, name, target=None, *, choices=None):
    selected = candidate(combat, mid, name, target=target)
    return settle(table, mid, selected.candidate_id, choices=choices or {})


@pytest.mark.parametrize('cl,owns,cancelled', [(14, True, True), (10, True, False), (14, False, False)])
def test_critical_conversion_precedes_damage_and_survives_reload(tmp_path, acquired, monkeypatch, cl, owns, cancelled):
    combat, table, mid = scenario(tmp_path, acquired, cl=cl, owns=owns)
    turn(table, mid, FOE)
    fixed(monkeypatch, [20, *([1] * 100)])
    play(combat, table, mid, 'Unarmed Strike', OWNER)
    engine = reload(tmp_path, mid)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_ROLLED' and e.actor_id == FOE]
    assert damage
    assert bool(damage[-1].payload.get('critical')) is not cancelled
    converted = [e for e in engine.events if e.event_type == 'ATTACK_CRITICAL_RESOLVED' and e.actor_id == FOE]
    assert any(e.payload.get('cancelled') for e in converted) is cancelled
    if cancelled:
        assert converted[-1].sequence < damage[-1].sequence


@pytest.mark.parametrize('cl,count', [(6, 2), (14, 3)])
def test_marrow_native_heal_cost_and_scaling(tmp_path, acquired, monkeypatch, cl, count):
    combat, table, mid = scenario(tmp_path, acquired, cl=cl)
    fixed(monkeypatch, [18, *([2] * 100)])
    turn(table, mid, FOE)
    play(combat, table, mid, 'Unarmed Strike', OWNER)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid).state.actors[OWNER]
    hp, stamina = before.current_hp, before.resources[STAMINA]
    play(combat, table, mid, 'Marrow Regeneration')
    engine = reload(tmp_path, mid)
    after = engine.state.actors[OWNER]
    rolls = [e for e in engine.events if e.event_type == 'DAMAGE_ROLLED' and e.actor_id == OWNER
             and str(e.source_definition_id).endswith('marrow_regeneration')]
    assert rolls[-1].payload['expression'] == f'{count}d10+2'
    assert after.current_hp == min(after.maximum_hp, hp + rolls[-1].payload['total'])
    assert after.resources[STAMINA] == stamina - 2
    assert not after.bonus_action_available


@pytest.mark.parametrize('attack,feature,dice', [('Unarmed Strike', None, '2d8+2'), ('Ignite', 'FIRE_BASE_IGNITE', '1d8+2')])
def test_bone_armor_native_attack_reaction_and_round_cost(tmp_path, acquired, monkeypatch, attack, feature, dice):
    foe = sheet([feature] if feature else [], cl=3)
    combat, table, mid = scenario(tmp_path, acquired, cl=3, foe=foe)
    turn(table, mid, FOE)
    fixed(monkeypatch, [18, *([1] * 100)])
    before = reload(tmp_path, mid).state.actors[OWNER].resources[STAMINA]
    prompts = play(combat, table, mid, attack, OWNER,
                   choices={PREFIX + 'bone_armor': 'first'})
    engine = reload(tmp_path, mid)
    reactions = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                 and e.source_definition_id == PREFIX + 'bone_armor']
    assert reactions and reactions[-1].payload['reduction'] > 0
    assert engine.state.actors[OWNER].resources[STAMINA] == before - 1
    assert not engine.state.actors[OWNER].reaction_available
    rolls = [r for r in engine.rolls if PREFIX + 'bone_armor' in r.reason]
    assert rolls and rolls[-1].expression == dice
    assert prompts, 'manual owner must be asked on the opponent’s turn'


@pytest.mark.parametrize('order', ['Attack', 'Dash', 'Disengage', 'Dodge', 'Help', 'Move', 'Guard'])
def test_guard_acquisition_commands_and_cold_replay(tmp_path, acquired, order):
    combat, table, mid = scenario(tmp_path, acquired, cl=10)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[STAMINA]
    play(combat, table, mid, 'Bone Guard Manifestation')
    engine = reload(tmp_path, mid)
    guard = next(a for a in engine.state.actors.values() if (a.summon or {}).get('group') == 'bone_guard')
    assert guard.active and guard.current_hp == 50 and guard.armor_class == 18
    assert guard.summon['command_range_ft'] is None
    assert engine.state.actors[OWNER].resources[STAMINA] == before - 5
    play(combat, table, mid, 'Command Bone Guard', choices={'choice:needle.bone_guard_order': [order]})
    engine = reload(tmp_path, mid)
    guard = engine.state.actors[guard.entity_id]
    assert any(c.condition_id == 'condition:typed.bone_guard_order' and c.data['order'] == order
               for c in guard.conditions.values())
    assert not engine.state.actors[OWNER].bonus_action_available
    turn(table, mid, guard.entity_id)
    engine = reload(tmp_path, mid)
    names = {engine.action_catalog[c.source_definition_id].display_name for c in engine.legal_candidates()
             if c.source_definition_id in engine.action_catalog}
    if order in {'Move', 'Guard'}:
        assert 'Bone Strike' not in names
    elif order != 'Attack':
        assert 'Bone Strike' not in names


@pytest.mark.parametrize('replacement,expected_hp,cost', [
    ('unbroken_bones#marrow_memory', 1, 4), ('sovereign_reconstruction', 0, 8)])
def test_native_zero_replacements_are_exclusive_and_cocoon_is_separate(tmp_path, acquired, monkeypatch,
                                                                    replacement, expected_hp, cost):
    foe = sheet([], cl=18, name='Heavy striker')
    strength = next(a for a in foe['ability_scores_and_statistics']['abilities'] if a['ability'] == 'STR')
    strength.update(score=66, modifier=28)
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 500
    combat, table, mid = scenario(tmp_path, acquired, cl=18, foe=foe)
    fixed(monkeypatch, [18, *([1] * 100)])
    initial = reload(tmp_path, mid).state.actors[OWNER].resources[STAMINA]
    for _ in range(4):
        turn(table, mid, FOE)
        play(combat, table, mid, 'Unarmed Strike', OWNER,
             choices={'choice:needle.bone_zero': [replacement]})
        engine = reload(tmp_path, mid)
        if any(c.condition_id == 'condition:typed.bone_monarch_scene_use' for c in engine.state.actors[OWNER].conditions.values()):
            break
        turn(table, mid, OWNER)
    actor = engine.state.actors[OWNER]
    assert actor.current_hp == expected_hp
    assert actor.resources[STAMINA] == initial - cost
    used = [c.data['feature'] for c in actor.conditions.values() if c.condition_id == 'condition:typed.bone_monarch_scene_use']
    assert used == [replacement]
    if replacement == 'sovereign_reconstruction':
        cocoon = next(o for o in engine.state.objects.values() if o.object_kind == 'body_asset')
        assert cocoon.current_hp == 90 and actor.temporary_hp == 0
        assert cocoon.ac == 16
        assert actor.life_state == 'CONSCIOUS'
        turn(table, mid, OWNER)
        after = reload(tmp_path, mid)
        assert after.state.actors[OWNER].current_hp == 30
        assert after.state.objects[cocoon.object_id].destroyed
        assert after.state.actors[OWNER].action_available
        assert after.state.actors[FOE].current_hp == 494
        assert any(c.condition_id == 'condition:typed.prone' for c in after.state.actors[FOE].conditions.values())


def test_native_journey_marrow_bonus_action_clock_and_cold_continuation(tmp_path, acquired):
    from combat.gate5_service import CombatService
    combat, table, mid = scenario(tmp_path, acquired, cl=6)
    engine = reload(tmp_path, mid)
    journey = combat.journeys.create(engine.typed_bundle_documents, engine.battlefield_document,
        {a.entity_id: a.position.model_dump(mode='json') for a in engine.state.actors.values() if not a.summon},
        {OWNER: 30, ALLY: 30, FOE: 30})
    jid = journey['journey_id']
    before = journey['actors'][OWNER]['resources'][STAMINA]
    healed = combat.journey_act(jid, journey['revision'], OWNER, 'bone_marrow', {})
    assert healed['seconds'] == 6
    assert healed['actors'][OWNER]['resources'][STAMINA] == before - 2
    assert healed['actors'][OWNER]['bone_marrow_pending']
    with pytest.raises(ValueError, match='Marrow Regeneration'):
        combat.journey_act(jid, healed['revision'], OWNER, 'wait', {'seconds': 1})
    done = combat.journey_act(jid, healed['revision'], OWNER, 'bone_marrow_benefit', {'benefit': 'none'})
    fresh = CombatService(ROOT, tmp_path).journey_state(jid)
    assert done == fresh
    assert not fresh['actors'][OWNER].get('bone_marrow_pending')
    rolls = [e for e in fresh['events'] if e['kind'] == 'ROLL_RECORDED']
    assert rolls and rolls[-1]['roll']['expression'] == '2d10+2'


@pytest.mark.parametrize('value', [
    {'cause': 'bone imagery'}, {'cause': 'broken_bone', 'temporary': 0.5},
    {'cause': 'physical_injury', 'speed_reduction_ft': -5},
])
def test_bodily_profile_rejects_invented_causes_and_noninteger_state(value):
    from combat.ext.bodily_effects import validate
    with pytest.raises(ValueError):
        validate(value)


@pytest.mark.parametrize('source_cl,removed', [(10, True), (18, False)])
def test_native_marrow_chooses_real_garden_bleeding_and_respects_source_level(tmp_path, acquired, monkeypatch,
                                                                          source_cl, removed):
    thorn = 'tianxia.subpath.body.black_thorn_demon_body'
    foe = sheet([], cl=source_cl, primary='Stamina', name='Thorn cultivator')
    foe['path_and_subpath'] = acquired(source_cl, thorn)
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 500
    combat, table, mid = scenario(tmp_path, acquired, cl=14, foe=foe)
    fixed(monkeypatch, [18, *([1] * 200)])
    for _ in range(4):
        turn(table, mid, OWNER)
        play(combat, table, mid, 'Unarmed Strike', FOE)
        turn(table, mid, FOE)
        engine = reload(tmp_path, mid)
        spines = engine.state.actors[FOE].resources.get('resource:named.demon_spine', 0)
        if spines >= 2:
            break
    assert spines >= 2, 'The real damage events must generate the Garden’s Demon Spines'
    engine = combat._load_session(mid).engine
    gardens = [c for c in engine.legal_candidates()
               if engine.action_catalog.get(c.source_definition_id) is not None
               and engine.action_catalog[c.source_definition_id].display_name == 'Impaling Garden']
    assert gardens
    chosen = next((c for c in gardens if c.destination and c.destination.x == 3 and c.destination.y == 6), gardens[0])
    settle(table, mid, chosen.candidate_id, choices={})
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    bleed = next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == 'condition:typed.bleeding')
    action = engine.action_catalog[bleed.source_definition_id]
    assert action.parameters['typed']['numbers']['cl'] == source_cl
    stamina = engine.state.actors[OWNER].resources[STAMINA]
    play(combat, table, mid, 'Marrow Regeneration',
         choices={'choice:needle.marrow_regeneration': ['bleeding:' + bleed.instance_id]})
    after = reload(tmp_path, mid).state.actors[OWNER]
    assert (bleed.instance_id not in after.conditions) is removed
    assert after.resources[STAMINA] == stamina - 2


def test_native_cocoon_breaks_immediately_without_transferring_excess_damage(tmp_path, acquired, monkeypatch):
    from combat.ext.life_state import encounter_death_saves
    foe = sheet([], cl=18, name='First striker')
    next(a for a in foe['ability_scores_and_statistics']['abilities'] if a['ability'] == 'STR').update(score=66, modifier=28)
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 500
    foe['ability_scores_and_statistics']['initiative'] = {'bonus': 300}
    combat, table, mid = scenario(tmp_path, acquired, cl=18, foe=foe, ordered=True,
        ally_score=410, team_overrides={ALLY: 'team:opponents'})
    fixed(monkeypatch, [18, *([1] * 200)])
    for _ in range(4):
        turn(table, mid, FOE)
        play(combat, table, mid, 'Unarmed Strike', OWNER,
             choices={'choice:needle.bone_zero': ['sovereign_reconstruction']})
        engine = reload(tmp_path, mid)
        cocoons = [o for o in engine.state.objects.values() if o.object_kind == 'body_asset' and not o.destroyed]
        if cocoons:
            break
        turn(table, mid, OWNER)
    assert cocoons and cocoons[0].current_hp == 90
    cocoon = cocoons[0]
    turn(table, mid, ALLY)
    engine = combat._load_session(mid).engine
    hit = next(c for c in engine.legal_candidates() if c.target_ids == (cocoon.object_id,)
               and 'Unarmed' in c.display_name)
    settle(table, mid, hit.candidate_id, choices={})
    after = reload(tmp_path, mid)
    actor = after.state.actors[OWNER]
    assert after.state.objects[cocoon.object_id].destroyed
    assert actor.active and actor.current_hp == 0 and actor.life_state == 'DYING'
    assert not any(c.condition_id == 'condition:typed.bone_cocoon' for c in actor.conditions.values())
    assert encounter_death_saves(actor) == {'ok': 0, 'bad': 0}


def test_native_owner_classification_binds_exact_restraint_before_marrow_repeat(tmp_path, acquired, monkeypatch):
    foe = sheet(['ASH_TAL_ASHEN_BURIAL'], cl=14, name='Ash cultivator')
    combat, table, mid = scenario(tmp_path, acquired, cl=14, foe=foe)
    fixed(monkeypatch, [1] * 200)
    turn(table, mid, FOE)
    play(combat, table, mid, 'Ashen Burial', OWNER)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    held = next(c for c in actor.conditions.values() if c.condition_id == 'condition:typed.restrained')
    from combat.ext.bodily_effects import profile
    assert profile(held, engine=engine, actor=actor) == {}, 'Ash imagery cannot establish anatomy'
    document = {'record_id': 'physical-cause', 'subject_id': OWNER, 'subject_name': actor.display_name,
        'subject_kind': 'creature', 'position': actor.position.model_dump(mode='json'),
        'source_reference': held.source_definition_id, 'witness_ids': [OWNER],
        'valid_through_round': engine.state.round_number + 1,
        'answers': {'bodily_effect.cause': {'fact': 'This restraint is a physical binding.',
            'category': 'physical_binding', 'visible_sign': 'A binding physically holds the limbs.',
            'source_cl': 14, 'condition': held.instance_id}}}
    wrong = deepcopy(document)
    wrong['answers']['bodily_effect.cause']['condition'] = 'a-different-condition'
    table.record_fact(mid, wrong, expected_state_version=engine.state.state_version)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert profile(actor.conditions[held.instance_id], engine=engine, actor=actor) == {}
    table.record_fact(mid, document, expected_state_version=engine.state.state_version)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert profile(actor.conditions[held.instance_id], engine=engine, actor=actor) == {'cause': 'physical_binding'}
    assert profile(actor.conditions[held.instance_id], engine=engine, actor=engine.state.actors[ALLY]) == {}
    withdrawn = {**document, 'active': False}
    table.record_fact(mid, withdrawn, expected_state_version=engine.state.state_version)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert profile(actor.conditions[held.instance_id], engine=engine, actor=actor) == {}
    table.record_fact(mid, document, expected_state_version=engine.state.state_version)
    fixed(monkeypatch, [20] * 200)
    play(combat, table, mid, 'Marrow Regeneration',
         choices={'choice:needle.marrow_regeneration': ['physical:' + held.instance_id]})
    after = reload(tmp_path, mid)
    assert held.instance_id not in after.state.actors[OWNER].conditions
    assert any(e.event_type == 'TABLE_FACT_RECORDED' for e in after.events)


def test_native_marrow_poison_repeat_uses_original_save_without_inventing_removal(tmp_path, acquired, monkeypatch):
    from tests.test_carry import KIT
    foe = sheet(['TAL_FENCING_FEINT', 'TAL_FENCING_EXPERT_FEINT', 'TAL_FENCING_CHEST_STRIKE'],
                cl=14, name='Fencer', kit={'starting_kit': KIT})
    combat, table, mid = scenario(tmp_path, acquired, cl=14, foe=foe)
    fixed(monkeypatch, [18, *([1] * 200)])
    turn(table, mid, FOE)
    play(combat, table, mid, 'Exploit: Chest Strike')
    play(combat, table, mid, 'Feint (Bonus Action)', OWNER)
    play(combat, table, mid, 'Bi Shou (Dagger) attack', OWNER)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    poisoned = next(c for c in before.state.actors[OWNER].conditions.values()
                    if c.condition_id == 'condition:typed.poisoned')
    original = poisoned.data['origin_save']
    assert not poisoned.data.get('repeat_save')
    fixed(monkeypatch, [20] * 200)
    play(combat, table, mid, 'Marrow Regeneration',
         choices={'choice:needle.marrow_regeneration': ['poisoned:' + poisoned.instance_id]})
    after = reload(tmp_path, mid)
    assert poisoned.instance_id in after.state.actors[OWNER].conditions
    rolls = [r for r in after.rolls if r.actor_id == OWNER and 'marrow_regeneration' in r.reason
             and r.expression.startswith('1d20')]
    assert rolls and rolls[-1].mode == 'ADVANTAGE'
    assert any(e.event_type == 'SAVE_ROLLED' and str(e.source_definition_id).endswith('marrow_regeneration')
               and e.payload.get('dc') == original['dc'] for e in after.events)

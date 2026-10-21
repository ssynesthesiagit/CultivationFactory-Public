"""Acquired progression -> native technique -> table commit -> cold replay.

No injected passive rows, trigger receipts, custom attacks or live model calls.
The separate acquisition database is reopened before compiling each character.
"""
from copy import deepcopy
import json

import pytest

from app.core import Database, Settings, FoundryError
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext.adaptations import RECORD, PREFIX
from combat.typed_reactions import damage_bonus_eligible
from non_sphere_authority import NonSphereAuthorityService
from tests.h1_support import ROOT, sheet
from tests.ns1r_evidence_helpers import install_authority_test_pack, ap_award, commit_authority_event, access_evidence
from tests.test_ns1r_non_sphere_authority import insert_project
from tests.worker2_support import fixture, candidate, settle, turn, reload, OWNER, ALLY, FOE

BODY = 'tianxia.path.body_refining'
QI = 'tianxia.path.qi_cultivation'
SPIRIT = 'tianxia.path.spirit_awakening'
FAMILY = PREFIX.removesuffix('.feature.')
SOUND = 'tianxia.subpath.qi.sound_cultivator'
STAMINA = 'resource:core.stamina'


@pytest.fixture(scope='module')
def acquired(tmp_path_factory):
    settings = Settings.from_env(ROOT, tmp_path_factory.mktemp('adaptive-acquisition'))
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    service = NonSphereAuthorityService(db)
    install_authority_test_pack(db, service)
    documents = {}

    def get(cl, parent=BODY, subpath=FAMILY):
        key = (cl, parent, subpath)
        if key not in documents:
            pid = 'adaptive-' + str(cl) + '-' + (subpath or parent).rsplit('.', 1)[-1]
            insert_project(db, pid, cl)
            method = 'METHOD-005' if parent == SPIRIT else 'METHOD-001'
            service.initialize_for_project(pid, target_cl=cl, path_ids=[parent], method_id=method,
                access_source_records=access_evidence(db, service, pid, method))
            service.allocate_advancement(pid, {parent: cl - 1},
                evidence_id=ap_award(db, service, pid, method, cl, cl - 1),
                idempotency_key=pid + '-advance')
            if subpath:
                access = commit_authority_event(db, service, pid, 'subpath_access', {'selection_id': subpath})
                service.select_subpath(pid, parent, subpath, access_source_records=[access])
            state = NonSphereAuthorityService(db).get_state(pid)
            doc = sheet([], cl=cl, primary={BODY: 'Stamina', QI: 'Qi', SPIRIT: 'Resonance'}[parent],
                        name='Adaptive practitioner' if parent == BODY else 'Hostile musician')
            doc['identity']['path'] = {BODY: 'Body Refining', QI: 'Qi Cultivation', SPIRIT: 'Spirit Awakening'}[parent]
            doc['path_and_subpath'] = {'paths': state['paths']}
            # Mandatory attack chassis from this actually acquired Path's
            # authenticated source. No hand-authored feature grants or attacks.
            if subpath != FAMILY:
                doc['path_and_subpath']['path_feature_record_ids'] = [row['canonical_id']
                    for row in service.path_profiles[parent]['features']
                    if row['feature_kind'] == 'attack_chassis' and int(row['minimum_cl']) <= cl]
            doc['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
            doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
            doc['ability_scores_and_statistics']['technique_attack_bonus'] = 100
            doc['ability_scores_and_statistics']['technique_save_dc'] = 100
            documents[key] = doc
        return deepcopy(documents[key])
    get.service = service
    get.db = db
    return get


def scenario(tmp_path, acquired, cl=18, *, owner=True, same_team=False, foe_doc=None,
             ally_opposes=False, seed='HEAVEN-ANSWERING-NATIVE'):
    doc = acquired(cl)
    if not owner:
        doc['path_and_subpath'] = {}
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    foe = foe_doc or acquired(18, QI, SOUND)
    return fixture(tmp_path, [], cl=cl, primary='Stamina', owner_bundle=bundle, foe_sheet=foe,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 8, 'y': 8}, FOE: {'x': 4, 'y': 6}},
        team_overrides={**({FOE: 'team:factory'} if same_team else {}),
                        **({ALLY: 'team:opponents'} if ally_opposes else {})}, seed=seed)


def play(combat, table, mid, name, target=None, choices=None):
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id,
                  choices={'choice:needle.fact_admission.qualifying_hostility': ['genuine'],
                           'choice:needle.fact_admission.anti_farming': ['not_farmed'], **(choices or {})})


def strike(combat, table, mid, choices=None):
    if table.state(mid)['menu']['actor_id'] == FOE:
        settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    turn(table, mid, FOE)
    return play(combat, table, mid, 'Instrument of Qi: Thunder', OWNER, choices)


def records(engine):
    return next(c.data for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == RECORD)


def packet(engine):
    return next(e.payload for e in reversed(engine.events)
                if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids and e.payload['damage_type'] == 'THUNDER')


@pytest.mark.parametrize('cl', [3, 14, 18])
def test_acquired_damage_progression_and_defense_order(tmp_path, acquired, cl):
    combat, table, mid = scenario(tmp_path, acquired, cl)
    strike(combat, table, mid, {'choice:needle.adapt_response': ['use']} if cl == 18 else {})
    first = reload(tmp_path, mid)
    row = records(first)['damage'][0]
    assert row['type'] == 'THUNDER' and row['by'] == FOE
    assert row['source_cl'] == cl and row['acquisition_round'] == first.state.round_number
    assert row['expires'] == 'scene_end'
    assert row['reduction_round'] == first.state.actors[OWNER].turn_flags.get('_round_adapted_first_THUNDER', -1)
    if cl == 14:
        from combat.ext.adaptations import adapted_resistance
        from combat.source_authority import protection_applies
        defense = adapted_resistance(first, first.state.actors[OWNER], 'THUNDER', {}, FOE)[0]
        profile = defense['protection_authority']
        assert protection_applies({'authority_contest': {'bypass_biology': 1, 'cultivated': 1},
                                   'numbers': {'cl': 20}}, profile)
        assert protection_applies({'authority_contest': {'decisive_gap': 6}, 'numbers': {'cl': 19}}, profile)
        assert not protection_applies({'authority_contest': {'decisive_gap': 6}, 'numbers': {'cl': 20}}, profile)
    if cl == 18:
        assert first.state.actors[OWNER].resources[STAMINA] == 98
        assert not first.state.actors[OWNER].reaction_available
        assert packet(first)['hp_damage'] == max(0, packet(first)['rolled_or_pending_damage'] // 2 - 4)
    strike(combat, table, mid, {'choice:needle.adapt_response': ['use']} if cl == 3 else {})
    second = reload(tmp_path, mid)
    assert packet(second)['hp_damage'] == max(0, packet(second)['rolled_or_pending_damage'] // 2 - 4)
    assert records(second)['damage'][0]['reduction_round'] == second.state.round_number


def test_unowned_family_is_inert_in_real_play(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, owner=False)
    prompts = strike(combat, table, mid, {'choice:needle.adapt_response': ['use']})
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == RECORD for c in engine.state.actors[OWNER].conditions.values())
    assert not any('adapt' in p['context']['reaction_source_id'] for p in prompts)
    assert engine.state.actors[OWNER].resources[STAMINA] == 100


@pytest.mark.parametrize('counter', [False, True])
def test_native_failed_save_records_original_provenance_and_paid_repeat(tmp_path, acquired, counter):
    combat, table, mid = scenario(tmp_path, acquired, 18 if counter else 6)
    turn(table, mid, FOE)
    choices = {'reaction:typed.' + PREFIX + 'perfect_counter_evolution': 'first',
               'choice:needle.counter_affliction': ['frightened']} if counter else {}
    play(combat, table, mid, 'Song of Fear', choices=choices)
    engine = reload(tmp_path, mid)
    row = records(engine)['afflictions'][0]
    assert row['condition'] == 'frightened' and row['by'] == FOE
    assert row['ability'] and row['dc'] == 100 and row['source_cl'] == (18 if counter else 6)
    assert any(c.condition_id.endswith('frightened') for c in engine.state.actors[OWNER].conditions.values())
    turn(table, mid, OWNER)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={'choice:needle.meridian_repeat': 'first'})
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'D20_REWRITTEN' and e.source_definition_id == PREFIX + 'meridians_remember_affliction'
               and e.payload.get('bonus') == 4 for e in engine.events)
    if counter:
        acquired_index = next(i for i, e in enumerate(engine.events) if e.event_type == 'CONDITION_APPLIED'
                              and e.source_definition_id == PREFIX + 'perfect_counter_evolution'
                              and e.payload.get('condition_id') == RECORD)
        rewritten_index = next(i for i, e in enumerate(engine.events) if e.event_type == 'D20_REWRITTEN'
                               and e.source_definition_id == PREFIX + 'perfect_counter_evolution')
        assert acquired_index < rewritten_index


@pytest.mark.parametrize('cl,rider,dice', [(10, 'speed', '2d8'),
    *((18, rider, '4d8') for rider in ['push', 'no_reactions', 'speed', 'save', 'move'])])
def test_return_lesson_all_five_riders_from_native_teacher(tmp_path, acquired, rider, cl, dice):
    combat, table, mid = scenario(tmp_path, acquired, cl)
    strike(combat, table, mid)
    turn(table, mid, OWNER)
    prompts = play(combat, table, mid, 'Unarmed Strike', FOE,
        {'choice:needle.return_lesson': [rider], 'choice:needle.lesson_feature': 'first',
         'choice:needle.return_lesson_move': 'first'})
    engine = reload(tmp_path, mid)
    assert any(r.expression.startswith(dice) for r in engine.rolls)
    assert engine.state.actors[OWNER].resources[STAMINA] == 99
    offered = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.return_lesson')
    assert {o['id'] for o in offered['choice']['options']} == {'push', 'no_reactions', 'speed', 'save', 'move'}
    if rider == 'speed':
        assert engine._effective_speed(engine.state.actors[FOE]) == 0
        turn(table, mid, FOE)
        assert reload(tmp_path, mid)._effective_speed(reload(tmp_path, mid).state.actors[FOE]) == 30
    elif rider == 'push':
        assert engine.state.actors[FOE].position.x == 6
    elif rider == 'no_reactions':
        assert any(c.condition_id.endswith('reaction_denied') for c in engine.state.actors[FOE].conditions.values())
    elif rider == 'save':
        assert any(c.condition_id.endswith('lesson_save') and c.data['feature']
                   for c in engine.state.actors[FOE].conditions.values())
    else:
        assert engine.state.actors[OWNER].position.x != 3 or engine.state.actors[OWNER].position.y != 6


@pytest.mark.parametrize('cl,counter', [(14, False), (18, True)])
def test_psychic_counter_gets_flat_reduction_without_buying_flesh_resistance(tmp_path, acquired, cl, counter):
    combat, table, mid = scenario(tmp_path, acquired, cl, foe_doc=acquired(18, SPIRIT, None))
    turn(table, mid, FOE)
    choices = {'choice:needle.adapt_response': ['use']} if counter else {}
    play(combat, table, mid, 'Mind Spike', OWNER, choices)
    if not counter:
        settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
        turn(table, mid, FOE)
        play(combat, table, mid, 'Mind Spike', OWNER)
    engine = reload(tmp_path, mid)
    damage = next(e.payload for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED'
                  and OWNER in e.target_ids and e.payload['damage_type'] == 'PSYCHIC')
    assert damage['hp_damage'] == max(0, damage['rolled_or_pending_damage'] - 8)
    assert records(engine)['damage'][0]['type'] == 'PSYCHIC'
    assert engine.state.actors[OWNER].resources[STAMINA] == (98 if counter else 100)


@pytest.mark.parametrize('declarer', ['source', 'recipient'])
def test_declared_staged_contact_never_creates_an_adaptation(tmp_path, acquired, declarer):
    combat, table, mid = scenario(tmp_path, acquired, 3)
    prompts = strike(combat, table, mid, {'choice:needle.fact_admission.qualifying_hostility': ['staged']}
                     if declarer == 'source' else {'choice:needle.fact_admission.anti_farming': ['farmed_or_unknown']})
    engine = reload(tmp_path, mid)
    assert packet(engine)['hp_damage'] > 0
    assert any(p['context']['reaction_source_id'] == 'choice:needle.fact_admission.qualifying_hostility' for p in prompts)
    assert not any(c.condition_id == RECORD for c in engine.state.actors[OWNER].conditions.values())


def test_rare_inheritance_requires_its_exact_native_access_receipt(acquired):
    db, service = acquired.db, acquired.service
    pid = 'adaptive-no-inheritance-access'
    insert_project(db, pid, 3)
    service.initialize_for_project(pid, target_cl=3, path_ids=[BODY], method_id='METHOD-001')
    service.allocate_advancement(pid, {BODY: 2}, evidence_id=ap_award(db, service, pid, 'METHOD-001', 3, 2),
                                idempotency_key=pid + '-advance')
    with pytest.raises(FoundryError) as failure:
        service.select_subpath(pid, BODY, FAMILY)
    assert failure.value.code == 'NS1R_RESTRICTED_TRADITION_ACCESS_REQUIRED'
    assert not NonSphereAuthorityService(db).get_state(pid)['paths'][0].get('subpath_or_tradition_id')


def test_counter_success_retains_pre_reroll_adaptation_without_failure_riders(tmp_path, acquired):
    foe = acquired(18, QI, SOUND)
    foe['ability_scores_and_statistics']['technique_save_dc'] = 12
    combat, table, mid = scenario(tmp_path, acquired, foe_doc=foe, ally_opposes=True,
                                  seed='A2GBODSUB6R3-SUCCESS-8')
    turn(table, mid, FOE)
    play(combat, table, mid, 'Song of Fear', choices={
        'reaction:typed.' + PREFIX + 'perfect_counter_evolution': 'first',
        'choice:needle.counter_affliction': ['frightened']})
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert records(engine)['afflictions'][0]['condition'] == 'frightened'
    assert not any(c.condition_id.endswith('frightened') for c in actor.conditions.values())
    assert actor.resources[STAMINA] == 98 and not actor.reaction_available


def test_native_scene_end_clears_records_after_continuation_and_rest(tmp_path, acquired):
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    documents = {OWNER: acquired(14), ALLY: sheet([], cl=18), FOE: acquired(18, QI, SOUND)}
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={'ask': True}) for aid, doc in documents.items()]
    state = combat.journeys.create(bundles, combat.factory_arenas()['battlefield:factory_pillar_arena'],
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 8, 'y': 8}, FOE: {'x': 4, 'y': 6}},
        {aid: 30 for aid in documents}, {aid: 'MANUAL' for aid in documents})
    jid = state['journey_id']
    mid = combat.journey_start_combat(jid, state['revision'],
        {OWNER: 'team:factory', ALLY: 'team:factory', FOE: 'team:opponents'}, maximum_rounds=1)['match_id']
    turn(table, mid, FOE)
    play(combat, table, mid, 'Instrument of Qi: Thunder', OWNER)
    assert records(reload(tmp_path, mid))['damage'][0]['type'] == 'THUNDER'
    for _ in range(4):
        if combat._load_session(mid).engine.state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    assert reload(tmp_path, mid).state.terminal_result is not None
    state = combat.journey_state(jid)
    continued = combat.journey_resume(jid, state['revision'])
    def has_record(state):
        conditions = state['actors'][OWNER]['encounter_snapshot']['conditions']
        return any(json.loads(c)['condition_id'] == RECORD for c in conditions.values())
    assert has_record(continued)
    rested = combat.journey_act(jid, continued['revision'], OWNER, 'long_rest', {})
    assert has_record(CombatService(ROOT, tmp_path).journey_state(jid))
    ended = combat.journey_end_scene(jid, rested['revision'], 'The hostile encounter and its meaningful aftermath are finished.')
    assert not has_record(ended)
    cold = CombatService(ROOT, tmp_path).journey_state(jid)
    assert cold['scene_number'] == 1 and not has_record(cold)
    assert cold['actors'][OWNER]['encounter_snapshot']['current_hp'] == continued['actors'][OWNER]['encounter_snapshot']['current_hp']


def test_human_adaptation_choice_is_present_during_an_automatic_enemy_turn(tmp_path, acquired):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = scenario(tmp_path, acquired, 3)
    turn(table, mid, FOE)
    cid = candidate(combat, mid, 'Instrument of Qi: Thunder', target=OWNER).candidate_id
    original = combat.controller
    class SourceController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _context: (cid, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(original, name)
    combat.controller = SourceController()  # fake model transport; native legality and commits stay real
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, cid, auto=True, choices={
        'choice:needle.fact_admission.qualifying_hostility': ['genuine'],
        'choice:needle.fact_admission.anti_farming': ['not_farmed'],
        'choice:needle.adapt_damage': ['THUNDER']})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.adapt_damage'
               and p['context']['reactor_id'] == OWNER for p in prompts)
    assert records(reload(tmp_path, mid))['damage'][0]['type'] == 'THUNDER'


def test_return_lesson_retains_its_self_movement_after_a_lethal_hit(tmp_path, acquired):
    foe = acquired(18, QI, SOUND)
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 1
    combat, table, mid = scenario(tmp_path, acquired, 10, foe_doc=foe)
    strike(combat, table, mid)
    turn(table, mid, OWNER)
    prompts = play(combat, table, mid, 'Unarmed Strike', FOE,
                   {'choice:needle.return_lesson': ['move'], 'choice:needle.return_lesson_move': 'first'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == 0
    assert any(p['context']['reaction_source_id'] == 'choice:needle.return_lesson' for p in prompts)
    assert engine.state.actors[OWNER].resources[STAMINA] == 99
    assert (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y) != (3, 6)


def test_feature_picker_includes_native_owned_chassis_without_future_tiers(tmp_path, acquired):
    doc = acquired(10)
    doc['path_and_subpath']['path_feature_record_ids'] = [r['canonical_id']
        for r in acquired.service.path_profiles[BODY]['features'] if r['feature_kind'] == 'attack_chassis']
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid = fixture(tmp_path, [], cl=10, primary='Stamina', owner_bundle=bundle,
                                  foe_sheet=acquired(18, QI, SOUND))
    engine = reload(tmp_path, mid)
    names = {key: value for action in engine.action_catalog.values() if action.owner_id == OWNER
             for key, value in (action.parameters.get('adaptation_body_features') or {}).items()}
    assert names['tianxia.path.body_refining.feature.iron_fist'] == 'Iron Fist'
    assert PREFIX + 'return_the_lesson' in names
    assert PREFIX + 'ten_thousand_answers' not in names

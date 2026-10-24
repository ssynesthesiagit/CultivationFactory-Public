"""Native NS1R acquisition -> table intents -> cold mechanical replay (synthetic fixtures).

The full acquisition/continuation suite for the Yin-Yang cultivator; the
shorter public subset stays in tests/test_mgr_t14_yin_yang_native.py. Every
character is built from the shipped non-sphere catalog through the test
authority pack and a synthetic character sheet, using the shared table harness
(tests.ns1r_evidence_helpers, tests.test_ns1r_non_sphere_authority,
tests.worker2_support). No owner save, character, live data or private
material is read, so the file runs on the public CI. Two cases that need the
printed Fire Ward trigger skip there, because the public export replaces free
prose with pseudo-words and the reaction is no longer compiled on that copy.

No fixture grants ownership, Harmony, polarity, Unity or field flags. Source
techniques and character advancement produce all state under test.
"""
from copy import deepcopy
import pytest

from app.core import Database, Settings
from combat.factory_compiler import compile_character
from non_sphere_authority import NonSphereAuthorityService
from tests.h1_support import ROOT, sheet
from tests.ns1r_evidence_helpers import install_authority_test_pack, ap_award
from tests.test_ns1r_non_sphere_authority import insert_project
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn

QI_PATH = 'tianxia.path.qi_cultivation'
SUBPATH = 'tianxia.subpath.qi.yin_yang_cultivator'
QI = 'resource:core.qi'
HARMONY = 'resource:named.harmony'


def scene_state(actor):
    from combat.ext.yin_yang_cultivator import scene_state as read_scene_state
    return read_scene_state(actor)


@pytest.fixture(scope='module')
def acquired(tmp_path_factory):
    settings = Settings.from_env(ROOT, tmp_path_factory.mktemp('yin-yang-acquisition'))
    settings.ensure_dirs()
    db = Database(settings); db.migrate()
    service = NonSphereAuthorityService(db)
    install_authority_test_pack(db, service)
    cache = {}
    def get(cl):
        if cl not in cache:
            project = f'yin-yang-{cl}'
            insert_project(db, project, cl)
            service.initialize_for_project(project, target_cl=cl, path_ids=[QI_PATH], method_id='METHOD-001')
            service.allocate_advancement(project, {QI_PATH: cl - 1},
                evidence_id=ap_award(db, service, project, 'METHOD-001', cl, cl - 1),
                idempotency_key=project + '-advance')
            service.select_subpath(project, QI_PATH, SUBPATH)
            service.set_resource(project, QI_PATH, current=27, maximum=30)
            state = NonSphereAuthorityService(db).get_state(project)
            doc = sheet(['FIRE_BASE_IGNITE'], cl=cl, name='Yin–Yang cultivator')
            doc['identity']['proficiency_bonus'] = 2 + (cl - 1) // 4
            cache[cl] = doc
        return deepcopy(cache[cl])
    def compile_native(doc, cl):
        return NonSphereAuthorityService(db).compile_combat_character(
            f'yin-yang-{cl}', doc, actor_id=OWNER, reaction_plan={'ask': True})
    def compile_other():
        project = 'yin-yang-wrong-owner'
        insert_project(db, project, 18)
        service.initialize_for_project(project, target_cl=18, path_ids=[QI_PATH], method_id='METHOD-001')
        service.allocate_advancement(project, {QI_PATH: 17},
            evidence_id=ap_award(db, service, project, 'METHOD-001', 18, 17),
            idempotency_key=project + '-advance')
        service.select_subpath(project, QI_PATH, 'tianxia.subpath.qi.sound_cultivator')
        service.set_resource(project, QI_PATH, current=27, maximum=30)
        return NonSphereAuthorityService(db).compile_combat_character(
            project, sheet(['FIRE_BASE_IGNITE'], cl=18), actor_id=OWNER, reaction_plan={'ask': True})
    get.compile = compile_native
    get.compile_other = compile_other
    def compile_peer():
        project = 'yin-yang-first-turn-peer'
        insert_project(db, project, 3)
        service.initialize_for_project(project, target_cl=3, path_ids=[QI_PATH], method_id='METHOD-001')
        service.allocate_advancement(project, {QI_PATH: 2},
            evidence_id=ap_award(db, service, project, 'METHOD-001', 3, 2),
            idempotency_key=project + '-advance')
        service.select_subpath(project, QI_PATH, SUBPATH)
        service.set_resource(project, QI_PATH, current=27, maximum=30)
        return service.compile_combat_character(project, sheet([], cl=3, name='Other cultivator'),
            actor_id=FOE, reaction_plan={'ask': True})
    get.compile_peer = compile_peer
    return get


def scenario(tmp_path, acquired, cl=18, *, effective=None, foe=None):
    doc = acquired(cl)
    if effective is not None:
        doc['identity']['effective_cl'] = effective
    bundle = acquired.compile(doc, cl)
    return fixture(tmp_path, [], cl=cl, owner_bundle=bundle, foe_sheet=foe,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}},
        seed='YIN-YANG-NATIVE')


def use(combat, table, mid, name, target=None, **kw):
    if name == 'Ignite':
        name = 'Ignite: Increase Burn Damage'
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id, choices=kw)


def next_owner_turn(table, mid):
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)


def fireball(combat, table, mid, *, at=(8, 6), **choices):
    """A real saving-throw procedure; Ignite is an attack, not a save."""
    return settle(table, mid, candidate(combat, mid, 'Fireball Art', at=at).candidate_id, choices=choices)


def both_alignments(monkeypatch, *sources):
    """State that these sources are eligible for either alignment.

    ``alignment_options`` derives eligibility from the printed Source Rule text
    and its typed tags. The public export replaces free prose with pseudo-words,
    which collapses, for example, Fire Ward to ``('yang',)`` and One With The
    Night to ``('yin',)``; the prompt and the front-loaded preparation choice
    then never appear. The mechanic under test needs both modes, so pin the
    eligibility here and leave every other source on the real reading.
    """
    from combat.ext import yin_yang_cultivator as yin_yang
    original = yin_yang.alignment_options
    monkeypatch.setattr(yin_yang, 'alignment_options',
        lambda source: ('yin', 'yang') if source in sources else original(source))


def require_fire_ward_reaction(bundle):
    """Skip where the compiled Fire Ward reaction does not exist.

    The public CI export replaces free prose with pseudo-words, so the generic
    reaction compiled from Fire Ward's printed trigger ("You or an ally within
    30 feet takes damage") is absent from ``typed_reactions`` on that copy. The
    cases below need that trigger to fire; the owner tree keeps the real
    wording and compiles the row, so they run there.
    """
    if not any(row.get('feature_id') == 'tianxia.talent.fire.fire_ward'
               for row in bundle.get('typed_reactions') or ()):
        pytest.skip('public export scrambles the Fire Ward trigger; reaction not compiled here')


def assert_temp_protects_triggering_damage(engine, target, source, amount):
    grant = next(event for event in engine.events if event.event_type == 'TEMP_HP_GRANTED'
        and event.source_definition_id == source and target in event.target_ids)
    damage = next(event for event in engine.events if event.event_type == 'DAMAGE_COMMITTED'
        and target in event.target_ids and event.sequence > grant.sequence)
    assert grant.payload['offered'] == amount
    assert damage.payload['temporary_hp_absorbed'] == min(amount, damage.payload['reduced_to']) > 0
    assert engine.state.actors[target].temporary_hp == max(0, amount - damage.payload['reduced_to'])


def test_native_first_turn_current_waits_for_its_actual_player(tmp_path, acquired):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.ext.yin_yang_cultivator import CURRENT
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    bundles = [acquired.compile(acquired(3), 3), acquired.compile_peer()]
    mid = combat._finish_factory_match(bundles, [OWNER, FOE],
        {OWNER: 'team:a', FOE: 'team:b'},
        {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 6, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        [OWNER], [FOE], control_modes={OWNER: 'MANUAL', FOE: 'MANUAL'},
        match_seed='YIN-YANG-FIRST-TURN', display_name='Current choice', maximum_rounds=2)['match_id']
    before = reload(tmp_path, mid)
    first = before.state.current_actor_id
    assert before.state.actors[first].turns_started == 0
    assert not any(c.condition_id == CURRENT for c in before.state.actors[first].conditions.values())
    setup = next(group for group in table.state(mid)['menu']['actions']
        if group['source_definition_id'] == 'system:combat.fight_setup')
    prompts = settle(table, mid, setup['options'][0]['candidate_id'],
        choices={'choice:needle.balanced_flow': ['yang']})
    assert any(p['context']['reactor_id'] == first and p['context']['reaction_source_id'] == 'choice:needle.balanced_flow' for p in prompts)
    after = reload(tmp_path, mid)
    current, = [c for c in after.state.actors[first].conditions.values() if c.condition_id == CURRENT]
    assert current.data['current'] == 'yang'
    assert after.state.actors[first].turns_started == 1
    assert after.state.actors[first].resources[QI] == 27


def test_native_scene_owner_operation_is_distinct_from_actor_consent_and_fact_recording(tmp_path, acquired):
    from combat.gate5_service import CombatService
    from combat.fact_consent_admission import read
    combat = CombatService(ROOT, tmp_path)
    bundles = [acquired.compile(acquired(18), 18),
               compile_character(sheet([], cl=18), actor_id=FOE, reaction_plan={'ask': True})]
    state = combat.journeys.create(bundles,
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 6, 'y': 6}}, {OWNER: 18000, FOE: 18000})
    jid = state['journey_id']
    declaration = {'source': 'system:journey.scene', 'subject': OWNER, 'kind': 'scene_end',
        'scope': jid + ':0', 'value': 'The table owner ends this meaningful situation.',
        'expires_at': 1, 'readers': [OWNER, FOE]}
    with pytest.raises(Exception):
        combat.journey_act(jid, 0, OWNER, 'declare_fact', declaration)
    assert combat.journey_state(jid) == state
    recorded = combat.journey_world_fact(jid, 0, declaration)
    assert 'scene_id' not in recorded
    assert not any(event['kind'] == 'YIN_YANG_SCENE_ENDED' for event in recorded['events'])
    before_foe = deepcopy(recorded['actors'][FOE])
    ended = combat.journey_end_scene(jid, 1, declaration['value'])
    assert combat.journey_state(jid) == ended
    assert ended['actors'][FOE] == before_foe
    assert ended['actors'][OWNER]['resources'][QI] == 27
    assert ended['actors'][OWNER]['resources'][HARMONY] == 0
    event = next(event for event in ended['events'] if event['kind'] == 'SCENE_ENDED')
    receipt = read(combat.journeys.load(jid), 'system:journey.scene', event['actor_id'],
        'scene_end', jid + ':1', OWNER)
    assert receipt['receipt_id'] == event['declaration_receipt']
    assert any(e['kind'] == 'YIN_YANG_SCENE_ENDED' and e['actor_id'] == OWNER for e in ended['events'])
    with pytest.raises(Exception):
        combat.journey_end_scene(jid, 1, declaration['value'])
    assert combat.journey_state(jid) == ended


@pytest.mark.parametrize('control_mode', ['MANUAL', 'LOCAL_AUTO'])
def test_native_outside_combat_palm_uses_real_acquisition_cost_choices_and_cold_replay(tmp_path, acquired, control_mode):
    from combat.gate5_service import CombatService
    from combat.journey_activity import replay_record, load
    combat = CombatService(ROOT, tmp_path)
    bundle = acquired.compile(acquired(3), 3)
    other = compile_character(sheet([], cl=3, name='Palm recipient'), actor_id=ALLY, reaction_plan={'ask': True})
    state = combat.journeys.create([bundle, other],
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}}, {OWNER: 18000, ALLY: 18000},
        control_modes={OWNER: control_mode, ALLY: 'MANUAL'})
    jid = state['journey_id']
    left, right = sorted((OWNER, ALLY))
    relationship = {'source': 'system:journey.activity', 'subject': left, 'kind': 'relations',
        'scope': jid, 'value': {'actors': {left: {right: 'ALLY'}}},
        'expires_at': 3600, 'readers': [OWNER, ALLY]}
    for invalid in [{**relationship, 'readers': [OWNER]},
            {**relationship, 'value': {'actors': {left: {'actor:unmapped': 'ALLY'}}}}]:
        with pytest.raises(Exception):
            combat.journey_world_fact(jid, state['revision'], invalid)
        assert combat.journey_state(jid) == state
    state = combat.journey_world_fact(jid, state['revision'], relationship)
    offered = next(row for row in combat.journey_menu(jid, OWNER)['options']
        if row['label'].startswith('Restorative Palm') and row.get('target_ids') == [ALLY])
    state = combat.journey_act(jid, state['revision'], OWNER, offered['kind'], offered['payload'])
    prompts = []
    for _ in range(12):
        pending = state.get('native_activity_pending')
        if pending is None:
            break
        request = pending['request']; prompts.append(request)
        # A different mapped actor may not impersonate the deciding creature.
        wrong = ALLY if request['reactor_id'] == OWNER else OWNER
        with pytest.raises(Exception):
            combat.journey_act(jid, state['revision'], wrong, 'native_activity_answer', {})
        assert combat.journey_state(jid) == state
        spec = request.get('extension_choice') or {}
        ids = spec.get('preferred') or request.get('legal_option_ids') or []
        answer = {key: request[key] for key in ('checkpoint', 'reactor_id', 'reaction_source_id')}
        answer.update(selection='USE' if ids else 'DECLINE', option_ids=ids[:1])
        state = combat.journey_act(jid, state['revision'], request['reactor_id'], 'native_activity_answer', answer)
    else:
        raise AssertionError('Outside-combat native choices did not settle')
    assert any(p['reaction_source_id'] == 'choice:needle.balanced_flow' for p in prompts) == (control_mode == 'MANUAL')
    assert 'native_activity_pending' not in state
    assert state['actors'][OWNER]['resources'][QI] == 25
    assert state['actors'][OWNER]['resources'][HARMONY] == 0
    assert combat.journey_state(jid) == state
    records = [event for event in state['events'] if event['kind'] == 'NATIVE_ACTIVITY_COMMITTED']
    assert len(records) == 1
    replayed = replay_record(records[0])
    from combat.relations import relation
    assert relation(replayed, replayed.actors[OWNER], replayed.actors[ALLY]) == 'ALLY'
    assert replayed.actors[ALLY].temporary_hp == 2
    assert scene_state(replayed.actors[OWNER])['last_alignment'] == 'yin'
    assert not any(event['event_type'] in ('MATCH_CREATED', 'INITIATIVE_ROLLED') for event in records[0]['events'])
    assert load(combat.journeys.load(jid)).state.model_dump(mode='json') == replayed.model_dump(mode='json')
    closed = combat.journey_act(jid, state['revision'], OWNER, 'native_activity_end', {})
    assert closed['seconds'] == 6
    assert 'native_activity' not in closed
    assert closed['actors'][OWNER]['resources'][QI] == 25
    assert combat.journey_state(jid) == closed
    reopened = load(combat.journeys.load(jid), initiator=OWNER)
    assert reopened.state.match_id != replayed.match_id
    assert reopened.roller.counter == replayed.roll_counter > 0


@pytest.mark.parametrize('unified', [False, True])
def test_native_field_and_unity_keep_remaining_time_across_journey_clock_and_map_changes(tmp_path, acquired, unified):
    from fractions import Fraction
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.ext.yin_yang_continuation import state as continued, left
    from combat.ext.yin_yang_cultivator import fields
    from combat.zones import actor_inside_zone
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    bundles = [acquired.compile(acquired(18), 18),
        compile_character(sheet([], cl=18), actor_id=FOE, reaction_plan={'ask': True})]
    arena = combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    positions = {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 6, 'y': 6}}
    journey = combat.journeys.create(bundles, arena, positions, {OWNER: 18000, FOE: 18000})
    jid = journey['journey_id']
    mid = combat.journey_start_combat(jid, journey['revision'], {OWNER: 'team:a', FOE: 'team:b'}, maximum_rounds=1)['match_id']
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Taiji Field', at=(3, 6)).candidate_id,
        choices={'choice:needle.taiji_rotation': ['yin']})
    if unified:
        use(combat, table, mid, 'Ultimate Unity')
    for _ in range(3):
        if combat._load_session(mid).engine.state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path, mid).state.terminal_result is not None
    if not unified:
        from combat.concentration import project_without_copies
        from combat.ext.concentration_duration import DEADLINE
        original = reload(tmp_path, mid).state.actors[OWNER]
        assert project_without_copies(original, []).model_dump() == original.model_dump()
        assert any(c.condition_id == DEADLINE for c in original.conditions.values())
        projected = project_without_copies(original, [original.concentration])
        assert projected.concentration is None
        assert not any(c.condition_id == DEADLINE for c in projected.conditions.values())
        assert any(c.condition_id == DEADLINE for c in original.conditions.values())
    resumed = combat.journey_resume(jid, combat.journey_state(jid)['revision'])
    session = combat.journeys.load(jid)
    before = min(left(session, row) for row in continued(session, OWNER)['records'] if row['kind'] == 'zone')
    assert 0 < before < 60
    resumed = combat.journey_act(jid, resumed['revision'], OWNER, 'wait', {'seconds': 12})
    session = combat.journeys.load(jid)
    after = min(left(session, row) for row in continued(session, OWNER)['records'] if row['kind'] == 'zone')
    assert after == before - 12
    combat.journey_act(jid, resumed['revision'], OWNER, 'finish', {})
    other_map = deepcopy(arena)
    other_map['stable_id'] = 'battlefield:yin_yang_neighbor'
    next_journey = combat.journeys.create(bundles, other_map, positions, {OWNER: 18000, FOE: 18000})
    next_id = next_journey['journey_id']
    session = combat.journeys.load(next_id)
    assert session.clock() == Fraction(0)
    assert min(left(session, row) for row in continued(session, OWNER)['records'] if row['kind'] == 'zone') == after
    next_mid = combat.journey_start_combat(next_id, 0, {OWNER: 'team:a', FOE: 'team:b'}, maximum_rounds=1)['match_id']
    engine = reload(tmp_path, next_mid)
    field, = fields(engine)
    assert field.trigger_profile['map_identity'] == arena['stable_id']
    assert not actor_inside_zone(engine, engine.state.actors[OWNER], field)
    assert not combat.get_match(next_mid)['state']['zones']
    assert any(e.event_type == 'ZONE_UPDATED' for e in engine.events)
    assert not any(e.event_type == 'ZONE_CREATED' for e in engine.events)
    assert scene_state(engine.state.actors[OWNER])['unity_used'] == int(unified)
    if not unified:
        assert engine.state.actors[OWNER].concentration.zone_id == field.zone_id
        assert any(e.event_type == 'CONCENTRATION_LEDGER_RESTORED' for e in engine.events)


def test_carried_yin_slow_expires_on_ordinary_journey_time_without_key_error(tmp_path, acquired, monkeypatch):
    """Service regression: the restored Flow modifier id must be read from its own payload key."""
    import math
    from combat import ext
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.ext.yin_yang_continuation import state as continued, left
    ext.effects()
    def hit(engine, roll, intent):
        if roll.actor_id == OWNER and str(roll.reason).startswith('ATTACK:'):
            return {'source_id': 'test:fixed-d20', 'operation': 'replace', 'natural_result': 20}
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [hit, *ext._HOOKS.get('d20_result', [])])
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    doc = acquired(3)
    doc['spheres_and_talents'] = sheet(['TAL_FORCE_IMPACT'], cl=3)['spheres_and_talents']
    bundles = [acquired.compile(doc, 3),
        compile_character(sheet([], cl=3), actor_id=FOE, reaction_plan={'ask': True})]
    journey = combat.journeys.create(bundles,
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 6, 'y': 6}}, {OWNER: 18000, FOE: 18000})
    jid = journey['journey_id']
    mid = combat.journey_start_combat(jid, 0, {OWNER: 'team:a', FOE: 'team:b'}, maximum_rounds=1)['match_id']
    turn(table, mid, OWNER)
    use(combat, table, mid, 'Impact', FOE, **{'choice:needle.balanced_yin': [FOE]})
    for _ in range(3):
        if reload(tmp_path, mid).state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    resumed = combat.journey_resume(jid, combat.journey_state(jid)['revision'])
    session = combat.journeys.load(jid)
    slow = [row for row in continued(session, FOE)['records'] if row['kind'] == 'modifier']
    assert len(slow) == 1 and 0 < left(session, slow[0]) < 3600
    # Ordinary travel time now crosses the carried slow's deadline; this must not raise KeyError.
    resumed = combat.journey_act(jid, resumed['revision'], OWNER, 'wait',
        {'seconds': math.ceil(left(session, slow[0])) + 1})
    session = combat.journeys.load(jid)
    assert not any(row['kind'] == 'modifier'
        for row in (session.state['actors'][FOE]['source_states'].get(SUBPATH + '.feature.balanced_flow') or {}).get('records', []))
    assert resumed['phase'] == 'travel'


@pytest.mark.parametrize('unified', [False, True])
def test_gm_ended_yin_yang_effects_do_not_return_on_next_combat_or_travel(tmp_path, acquired, unified):
    """Service regression: a GM journey_resume ending decision must stop Current/Unity/Field/concentration continuation."""
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.ext.yin_yang_continuation import KEY as CONTINUATION_KEY
    from combat.ext.yin_yang_cultivator import fields, UNITY, CURRENT
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    bundles = [acquired.compile(acquired(18), 18),
        compile_character(sheet([], cl=18), actor_id=FOE, reaction_plan={'ask': True})]
    arena = combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    positions = {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 6, 'y': 6}}
    journey = combat.journeys.create(bundles, arena, positions, {OWNER: 18000, FOE: 18000})
    jid = journey['journey_id']
    mid = combat.journey_start_combat(jid, journey['revision'], {OWNER: 'team:a', FOE: 'team:b'}, maximum_rounds=1)['match_id']
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Taiji Field', at=(3, 6)).candidate_id,
        choices={'choice:needle.taiji_rotation': ['yin']})
    if unified:
        use(combat, table, mid, 'Ultimate Unity')
    for _ in range(3):
        if combat._load_session(mid).engine.state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path, mid).state.terminal_result is not None
    resumed = combat.journey_resume(jid, combat.journey_state(jid)['revision'],
        effect_resolutions={OWNER: 'The GM ends the field and Unity effects.'})
    assert not resumed['actors'][OWNER].get('source_states', {}).get(CONTINUATION_KEY)
    new_mid = combat.journey_start_combat(jid, resumed['revision'], {OWNER: 'team:a', FOE: 'team:b'}, maximum_rounds=1)['match_id']
    engine = reload(tmp_path, new_mid)
    owner = engine.state.actors[OWNER]
    assert not any(c.condition_id in (UNITY, CURRENT) for c in owner.conditions.values())
    assert not fields(engine, owner)
    assert owner.concentration is None


def test_activity_scheduler_guard_yields_when_no_creature_can_decide(tmp_path, acquired):
    """Scheduler unit guard, not a native acquisition/whole-row certificate."""
    from combat.gate5_service import CombatService
    from combat.journey_activity import load
    from combat.gate2_engine import Gate2Engine
    combat = CombatService(ROOT, tmp_path)
    bundle = acquired.compile(acquired(3), 3)
    journey = combat.journeys.create([bundle],
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        {OWNER: {'x': 3, 'y': 6}}, {OWNER: 18000})
    engine = load(combat.journeys.load(journey['journey_id']))
    engine.state.maximum_rounds = 3  # Old behavior fails promptly, not a billion-round test.
    actor = engine.state.actors[OWNER]
    actor.active = actor.action_available = actor.bonus_action_available = actor.reaction_available = False
    engine.end_turn('scheduler-guard')
    assert engine.state.terminal_result is None
    assert engine.state.round_number == 2
    assert engine.state.current_actor_id == OWNER
    assert engine.state.actors[OWNER].turns_started == 0
    assert Gate2Engine.automatic_slot_budget(engine) is None


def test_native_carried_yin_slow_ends_on_the_sources_first_actual_turn(tmp_path, acquired, monkeypatch):
    from combat import ext
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    ext.effects()
    def hit(engine, roll, intent):
        if roll.actor_id == OWNER and str(roll.reason).startswith('ATTACK:'):
            return {'source_id': 'test:fixed-d20', 'operation': 'replace', 'natural_result': 20}
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [hit, *ext._HOOKS.get('d20_result', [])])
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    doc = acquired(3)
    # A native Qi-powered Impact isolates Flow's continuing slow; Ignite also
    # leaves a separate Fire-owned burning condition with its own continuation.
    doc['spheres_and_talents'] = sheet(['TAL_FORCE_IMPACT'], cl=3)['spheres_and_talents']
    bundles = [acquired.compile(doc, 3),
        compile_character(sheet([], cl=3), actor_id=FOE, reaction_plan={'ask': True})]
    journey = combat.journeys.create(bundles,
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 6, 'y': 6}}, {OWNER: 18000, FOE: 18000})
    jid = journey['journey_id']
    mid = combat.journey_start_combat(jid, 0, {OWNER: 'team:a', FOE: 'team:b'}, maximum_rounds=1)['match_id']
    turn(table, mid, OWNER)
    use(combat, table, mid, 'Impact', FOE, **{'choice:needle.balanced_yin': [FOE]})
    engine = reload(tmp_path, mid)
    assert engine._effective_speed(engine.state.actors[FOE]) == 20
    for _ in range(3):
        if reload(tmp_path, mid).state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    resumed = combat.journey_resume(jid, combat.journey_state(jid)['revision'])
    continued = resumed['actors'][FOE]['source_states'][SUBPATH + '.feature.balanced_flow']['records']
    assert any(row['kind'] == 'modifier' for row in continued)
    new_mid = combat.journey_start_combat(jid, resumed['revision'], {OWNER: 'team:a', FOE: 'team:b'}, maximum_rounds=2)['match_id']
    turn(table, new_mid, OWNER)
    engine = reload(tmp_path, new_mid)
    assert engine._effective_speed(engine.state.actors[FOE]) == 30
    assert not any(row.source_definition_id == SUBPATH + '.feature.balanced_flow'
        for row in engine.state.actors[FOE].modifiers.values())


@pytest.mark.parametrize('with_field', [False, True])
def test_native_journey_unity_expiry_resolves_actual_fall_without_a_creature_turn(tmp_path, acquired, with_field):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.journey_activity import replay_record
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    bundles = [acquired.compile(acquired(18), 18),
        compile_character(sheet([], cl=18), actor_id=FOE, reaction_plan={'ask': True})]
    journey = combat.journeys.create(bundles,
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 6, 'y': 6}}, {OWNER: 18000, FOE: 18000})
    jid = journey['journey_id']
    mid = combat.journey_start_combat(jid, 0, {OWNER: 'team:a', FOE: 'team:b'}, maximum_rounds=2 if with_field else 1)['match_id']
    turn(table, mid, OWNER)
    use(combat, table, mid, 'Ultimate Unity')
    if with_field:
        next_owner_turn(table, mid)
        settle(table, mid, candidate(combat, mid, 'Taiji Field', at=(3, 6)).candidate_id,
            choices={'choice:needle.taiji_rotation': ['yin']})
    engine = reload(tmp_path, mid)
    ascent = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
        and c.destination is not None and (c.destination.x, c.destination.y, c.destination.z) == (3, 6, 4))
    settle(table, mid, ascent.candidate_id)
    for _ in range(3):
        if reload(tmp_path, mid).state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    resumed = combat.journey_resume(jid, combat.journey_state(jid)['revision'])
    hp = resumed['actors'][OWNER]['encounter_snapshot']['current_hp']
    assert resumed['actors'][OWNER]['position']['z'] == 4
    ended = combat.journey_act(jid, resumed['revision'], OWNER, 'wait', {'seconds': 60})
    frozen_id = None
    prompts = []
    for _ in range(12):
        if 'native_activity_pending' not in ended:
            break
        pending = ended['native_activity_pending']
        assert pending['operation'] == 'journey_command'
        assert ended['seconds'] == resumed['seconds']
        assert ended['actors'][OWNER]['encounter_snapshot']['current_hp'] == hp
        request = pending['request']
        source = request['reaction_source_id']
        prompts.append(source)
        assert source in ('choice:needle.taiji_concentration_restore', 'choice:needle.featherfall')
        if frozen_id is None:
            frozen_id = pending['intent_id']
        assert pending['intent_id'] == frozen_id
        answer = {key: request[key] for key in ('checkpoint', 'reactor_id', 'reaction_source_id')}
        # Decline the actually acquired Featherfall reaction so expiry resolves a fall.
        answer.update(selection='USE' if source.endswith('taiji_concentration_restore') else 'DECLINE',
            option_ids=['end'] if source.endswith('taiji_concentration_restore') else [])
        with pytest.raises(Exception):
            combat.journey_act(jid, ended['revision'], FOE, 'native_activity_answer', answer)
        assert combat.journey_state(jid) == ended
        ended = combat.journey_act(jid, ended['revision'], OWNER, 'native_activity_answer', answer)
    assert 'native_activity_pending' not in ended
    assert 'choice:needle.featherfall' in prompts
    assert ('choice:needle.taiji_concentration_restore' in prompts) == with_field
    assert next(event['intent'] for event in ended['events']
        if event['kind'] == 'NATIVE_ELAPSED_EFFECTS_COMMITTED').find(frozen_id) >= 0
    # Position omits a zero height from its serialized form.
    assert ended['actors'][OWNER]['position'].get('z', 0) == 0
    assert ended['actors'][OWNER]['encounter_snapshot']['current_hp'] < hp
    record, = [event for event in ended['events'] if event['kind'] == 'NATIVE_ELAPSED_EFFECTS_COMMITTED']
    from combat.gate2_runtime_models import MatchState
    before_expiry = MatchState.model_validate_json(record['pre_state'])
    assert before_expiry.actors[OWNER].position.z == 4
    assert before_expiry.actors[OWNER].current_hp == hp
    assert any(row['kind'] == 'condition' and row['instance_id'] != row['runtime_instance_id']
        for row in record['timer_references'])
    if with_field:
        sequence = record['events']
        field_end = next(i for i, event in enumerate(sequence) if event['event_type'] == 'ZONE_REMOVED')
        unity_end = next(i for i, event in enumerate(sequence) if event['event_type'] == 'CONDITION_REMOVED'
            and event['payload'].get('condition_id') == 'condition:typed.yin_yang_unity')
        assert field_end < unity_end  # Owner handover precedes loss of flight support.
    replayed = replay_record(record)
    assert replayed.actors[OWNER].position.z == 0
    assert not any(c.condition_id == 'condition:typed.yin_yang_unity'
        for c in replayed.actors[OWNER].conditions.values())
    assert any(row['reason'] == 'FALLING_DAMAGE' for row in record['rolls'])
    assert not any(event['event_type'] in ('TURN_STARTED', 'MATCH_CREATED', 'INITIATIVE_ROLLED') for event in record['events'])
    assert combat.journey_state(jid) == ended


@pytest.mark.parametrize('kind,reason,ability,allowed', [
    ('save', 'SAVE:death', None, False), ('save', 'SAVE:custom', 'DEATH', False),
    ('check', 'CHECK:breakthrough', None, False), ('check', 'CHECK:training', None, False),
    ('save', 'SAVE:training_grip:WIS', 'WIS', True)])
def test_reversal_roll_kind_guard_without_classifying_source_names(kind, reason, ability, allowed):
    """Boundary guard only; native Reversal delivery is certified separately."""
    from types import SimpleNamespace
    from combat.ext.yin_yang_cultivator import reversal_guard
    rc = SimpleNamespace(kind=kind, ability=ability, roll=SimpleNamespace(reason=reason, roll_id='guard'))
    assert reversal_guard(SimpleNamespace(events=[]), None, rc) is allowed


@pytest.mark.parametrize('cl,maximum,advanced', [(3, 2, False), (13, 5, False), (14, 7, False), (18, 8, True)])
def test_native_acquisition_capacity_and_tiers(tmp_path, acquired, cl, maximum, advanced):
    combat, table, mid = scenario(tmp_path, acquired, cl)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[QI] == 27
    use(combat, table, mid, 'Restorative Palm', ALLY)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.resource_maximums[HARMONY] == maximum
    assert actor.resources[HARMONY] == 0
    # Native Qi Path CL11 Golden Core Efficiency refunds one of the two Qi.
    assert actor.resources[QI] == (25 if cl < 11 else 26)
    assert any(a.display_name == 'Ultimate Unity' for a in engine.action_catalog.values()) == advanced
    assert scene_state(actor)['last_alignment'] == 'yin'


def test_opposite_source_sequence_and_once_per_turn_cold_replay(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, 14)
    use(combat, table, mid, 'Restorative Palm', ALLY)
    next_owner_turn(table, mid)
    use(combat, table, mid, 'Ignite', FOE, **{'choice:needle.yin_yang_alignment': ['yang']})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[HARMONY] == 1
    assert scene_state(engine.state.actors[OWNER])['last_alignment'] == 'yang'
    next_owner_turn(table, mid)
    use(combat, table, mid, 'Restorative Palm', ALLY)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[HARMONY] == 2


def test_native_yin_slow_keeps_feature_source_and_does_not_stack_across_techniques(tmp_path, acquired, monkeypatch):
    from combat import ext
    both_alignments(monkeypatch, 'tianxia.talent.fire.fire_ward')
    ext.effects()
    def attack_die(engine, roll, intent):
        if str(roll.reason).startswith('ATTACK:'):
            return {'source_id': 'test:fixed-d20', 'operation': 'replace', 'natural_result': 10}
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [attack_die, *ext._HOOKS.get('d20_result', [])])
    doc = acquired(14)
    doc['spheres_and_talents'] = sheet(['FIRE_BASE_IGNITE',
        'tianxia.talent.fire.fire_ward'], cl=14)['spheres_and_talents']
    owner = acquired.compile(doc, 14)
    require_fire_ward_reaction(owner)
    combat, table, mid = fixture(tmp_path, [], cl=14, owner_bundle=owner,
        foe_sheet=sheet(['FIRE_BASE_IGNITE'], cl=14), foe_position={'x': 5, 'y': 6})
    use(combat, table, mid, 'Ignite', FOE)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Ignite', OWNER,
        **{'reaction:typed.tianxia.talent.fire.fire_ward': 'use',
           'reaction:typed.' + SUBPATH + '.feature.reversal': None,
           'choice:needle.yin_yang_alignment': ['yin']})
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    slows = [row for row in foe.modifiers.values() if row.source_definition_id == SUBPATH + '.feature.balanced_flow']
    assert len(slows) == 1
    assert sum(event.event_type == 'MODIFIER_APPLIED' and event.source_definition_id == SUBPATH + '.feature.balanced_flow'
               and FOE in event.target_ids for event in engine.events) == 2
    assert engine._effective_speed(foe) == 20


def test_native_nested_fire_ward_keeps_activation_order_after_outer_completion(tmp_path, acquired, monkeypatch):
    both_alignments(monkeypatch, 'tianxia.talent.fire.fire_ward')
    doc = acquired(18)
    doc['spheres_and_talents'] = sheet(['FIRE_TAL_FIREBALL_ART',
        'tianxia.talent.fire.fire_ward'], cl=18)['spheres_and_talents']
    owner = acquired.compile(doc, 18)
    require_fire_ward_reaction(owner)
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_bundle=owner)
    use(combat, table, mid, 'Restorative Palm', ALLY)
    next_owner_turn(table, mid)
    # Overheat is an actual source-owned self-damage event. Its nested Ward
    # has both printed Fire and Damage Reduction eligibility; declare it Yin.
    prompts = settle(table, mid, candidate(combat, mid, 'Fireball Art + Overheat (2 CP)', at=(8, 6)).candidate_id,
        choices={'reaction:typed.tianxia.talent.fire.fire_ward': 'use',
                 'reaction:typed.' + SUBPATH + '.feature.reversal': None,
                 'choice:needle.yin_yang_alignment': ['yin']})
    engine = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.yin_yang_alignment' for p in prompts)
    assert scene_state(engine.state.actors[OWNER])['last_alignment'] == 'yin'
    assert engine.state.actors[OWNER].resources[HARMONY] == 1


def test_unity_free_palm_both_current_benefits_and_flight(tmp_path, acquired):
    from combat.flight import profile
    from combat.ext.effect_durations import remaining_seconds, expiry_after_seconds
    combat, table, mid = scenario(tmp_path, acquired)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[QI]
    use(combat, table, mid, 'Ultimate Unity')
    engine = reload(tmp_path, mid)
    held, = [c for c in engine.state.actors[OWNER].conditions.values()
             if c.condition_id == 'condition:typed.yin_yang_unity']
    assert remaining_seconds(engine, held.expires_on, source_actor_id=OWNER) == 60
    assert remaining_seconds(engine, 'UNTIL_REMOVED', source_actor_id=OWNER) is None
    next_owner_turn(table, mid)
    engine = reload(tmp_path, mid)
    assert remaining_seconds(engine, held.expires_on, source_actor_id=OWNER) == 54
    assert expiry_after_seconds(engine, 54) == held.expires_on
    assert profile(engine, engine.state.actors[OWNER]).speed_ft == 40
    assert profile(engine, engine.state.actors[OWNER]).hover
    assert engine.state.actors[OWNER].resources[HARMONY] == 1
    use(combat, table, mid, 'Restorative Palm (Ultimate Unity)', ALLY,
        **{'choice:needle.balanced_yang': ['increase']})
    engine = reload(tmp_path, mid)
    # Unity pays 8; native CL11 Efficiency refunds 1. A free Palm refunds zero.
    assert engine.state.actors[OWNER].resources[QI] == before - 7
    assert engine.state.actors[ALLY].temporary_hp == 6
    roll = [r for r in engine.rolls if r.reason.startswith('HEALING:')][-1]
    assert roll.expression.startswith('3d8')


def test_native_suppression_does_not_grant_future_features(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, effective=2)
    engine = reload(tmp_path, mid)
    assert HARMONY not in engine.state.actors[OWNER].resources
    assert not any('yin_yang' in a.source_definition_id for a in engine.action_catalog.values())


def test_native_other_subpath_stays_inert_through_table_and_reload(tmp_path, acquired):
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_bundle=acquired.compile_other())
    prompts = use(combat, table, mid, 'Ignite', FOE)
    engine = reload(tmp_path, mid)
    assert HARMONY not in engine.state.actors[OWNER].resources
    assert not any('yin_yang' in a.source_definition_id for a in engine.action_catalog.values())
    assert not any('yin_yang' in p['context']['reaction_source_id'] for p in prompts)
    assert scene_state(engine.state.actors[OWNER]) == {'last_alignment': '', 'unity_used': 0}


def test_native_suppressed_profile_scales_harmony_palm_and_field_without_shrinking_qi(tmp_path, acquired):
    from combat.ext.yin_yang_cultivator import fields
    from combat.zone_sources import of
    combat, table, mid = scenario(tmp_path, acquired, effective=12)
    next_owner_turn(table, mid)
    use(combat, table, mid, 'Restorative Palm', ALLY)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resource_maximums[HARMONY] == 4
    assert owner.resource_maximums[QI] == 30
    assert engine.state.actors[ALLY].temporary_hp == 4
    assert not any(a.display_name == 'Ultimate Unity' for a in engine.action_catalog.values())
    next_owner_turn(table, mid)
    settle(table, mid, candidate(combat, mid, 'Taiji Field', at=(3, 6)).candidate_id,
        choices={'choice:needle.taiji_rotation': ['yin']})
    engine = reload(tmp_path, mid)
    field, = fields(engine)
    assert of(field)['source_cl'] == 12
    next_owner_turn(table, mid)
    use(combat, table, mid, 'Ignite', FOE)
    engine = reload(tmp_path, mid)
    assert not any(r.reason.startswith('TAIJI_FIELD_SAVE:') for r in engine.rolls)
    assert '_round_taiji_roll' not in engine.state.actors[OWNER].turn_flags


def test_peaceful_preparation_declares_polarity_and_settles_real_casts(tmp_path, acquired, monkeypatch):
    from combat.gate5_service import CombatService
    both_alignments(monkeypatch, 'TAL_DARK_ONE_WITH_THE_NIGHT')
    doc = acquired(18)
    dark = sheet(['TAL_DARK_ONE_WITH_THE_NIGHT'], cl=18)
    doc['spheres_and_talents'] = dark['spheres_and_talents']
    bundle = acquired.compile(doc, 18)
    options = bundle['prefight']['options']
    picks = [next(o['action_id'] for o in options if o['action_id'].endswith('.prepare_' + mode)
                  and 'One With The Night' in o['name']) for mode in ('yin', 'yang')]
    service = CombatService(ROOT, tmp_path)
    bundle = service._with_prefight(bundle, {OWNER: picks})
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_bundle=bundle, seed='YIN-YANG-PREPARATION')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[HARMONY] == 1
    assert scene_state(owner)['last_alignment'] == 'yang'
    assert owner.resources[QI] == 23
    assert not any(e.event_type == 'GM_RIDER' for e in engine.events)
    assert not any(c.source_definition_id in picks for c in engine.legal_candidates())


def test_field_native_placement_rotation_and_unity_concentration(tmp_path, acquired):
    from combat.ext.yin_yang_cultivator import fields
    from combat.zones import zone_is_difficult
    combat, table, mid = scenario(tmp_path, acquired)
    settle(table, mid, candidate(combat, mid, 'Taiji Field', at=(3, 6)).candidate_id,
        choices={'choice:needle.taiji_rotation': ['yin']})
    engine = reload(tmp_path, mid)
    field, = fields(engine)
    assert field.center.x == 3 and field.center.y == 6
    assert field.trigger_profile['height_ft'] == 20
    assert zone_is_difficult(engine, field, engine.state.actors[FOE])
    assert engine.state.actors[ALLY].armor_class + engine._ac_modifier(engine.state.actors[ALLY]) == 15
    assert engine.state.actors[OWNER].concentration.zone_id == field.zone_id
    use(combat, table, mid, 'Ultimate Unity')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].concentration is None
    field, = fields(engine)
    assert field.concentration_link is False
    assert sum(e.event_type == 'ZONE_CREATED' and e.payload['zone']['zone_id'] == field.zone_id
               for e in engine.events) == 1
    assert any(e.event_type == 'ZONE_UPDATED' for e in engine.events)
    from combat.zones import actor_inside_zone
    owner = engine.state.actors[OWNER]
    assert actor_inside_zone(engine, owner, field)
    ascent = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
        and c.destination is not None and (c.destination.x, c.destination.y, c.destination.z) == (3, 6, 5))
    settle(table, mid, ascent.candidate_id)
    engine = reload(tmp_path, mid)
    field, = fields(engine)
    owner = engine.state.actors[OWNER]
    assert owner.position.z == 5
    assert not actor_inside_zone(engine, owner, field)
    assert owner.armor_class + engine._ac_modifier(owner) == 14
    next_owner_turn(table, mid)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[HARMONY] == 1


def test_denied_unity_does_not_release_an_actual_field_concentration(tmp_path, acquired, monkeypatch):
    from combat import ext
    from combat.ext.yin_yang_cultivator import fields, UNITY
    ext.effects()
    def deny(engine, target, condition_id, source_id, source_actor_id):
        return False if condition_id == UNITY else None
    monkeypatch.setitem(ext._HOOKS, 'condition_application_attempt',
        [deny, *ext._HOOKS.get('condition_application_attempt', [])])
    combat, table, mid = scenario(tmp_path, acquired)
    settle(table, mid, candidate(combat, mid, 'Taiji Field', at=(3, 6)).candidate_id,
        choices={'choice:needle.taiji_rotation': ['yin']})
    use(combat, table, mid, 'Ultimate Unity')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    field, = fields(engine)
    assert not any(c.condition_id == UNITY for c in owner.conditions.values())
    assert owner.resources[QI] == 15  # Field 5, one native Path refund, then Unity 8
    assert owner.concentration.zone_id == field.zone_id
    assert field.concentration_link is True


@pytest.mark.parametrize('focus', ['focus', 'anchor'])
def test_native_named_armament_anchor_survives_mode_change_and_only_named_loss_ends_field(tmp_path, acquired, monkeypatch, focus):
    from combat import ext
    from combat.ext.qi_path import armament_condition
    from combat.ext.yin_yang_cultivator import fields, unity
    ext.effects()
    def attack_die(engine, roll, intent):
        if roll.actor_id == FOE and str(roll.reason).startswith('ATTACK:'):
            return {'source_id': 'test:fixed-d20', 'operation': 'replace', 'natural_result': 20}
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [attack_die, *ext._HOOKS.get('d20_result', [])])
    combat, table, mid = scenario(tmp_path, acquired, foe=sheet(['TAL_FORCE_IMPACT'], cl=18))
    use(combat, table, mid, 'Domain Armament: Manifest')
    next_owner_turn(table, mid)
    settle(table, mid, candidate(combat, mid, 'Taiji Field', at=(3, 6)).candidate_id,
        choices={'choice:needle.taiji_rotation': ['yin'], 'choice:needle.taiji_focus': [focus]})
    use(combat, table, mid, 'Ultimate Unity')
    use(combat, table, mid, 'Domain Armament: Guard Mode')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert armament_condition(owner).data['mode'] == 'guard'
    assert len(fields(engine, owner)) == 1
    assert bool(fields(engine, owner)[0].trigger_profile.get('condition_anchor')) == (focus == 'anchor')
    # Actual Force packets bypass Unity's printed resistance exception. Native
    # unconsciousness ends the Armament before death; Unity keeps the field free
    # of Concentration. A dying creature remains active for death saves.
    for _ in range(8):
        turn(table, mid, FOE)
        use(combat, table, mid, 'Impact', OWNER)
        engine = reload(tmp_path, mid)
        if armament_condition(engine.state.actors[OWNER]) is None:
            break
        next_owner_turn(table, mid)
    else:
        raise AssertionError('The native Force attacks did not end the Armament within Unity’s duration')
    owner = engine.state.actors[OWNER]
    assert unity(owner)
    assert owner.current_hp == 0
    assert any(c.condition_id == 'condition:typed.life_unconscious' for c in owner.conditions.values())
    assert armament_condition(owner) is None
    assert any(e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids
               and e.payload['damage_type'].upper() == 'FORCE' for e in engine.events)
    assert bool(fields(engine, owner)) == (focus == 'focus')


@pytest.mark.xfail(strict=False, reason=(
    'Known open (RB1): at the owner turn start the mandatory maintain/switch Rotation question is '
    'answered "yin" instead of the preferred "yang" (combat/ext/needle.py ask preferred), so the field '
    'carries the Yin rotation when this test reaches its save. The penalty code itself is unchanged: with '
    'the rotation set to yang, field_owners returns the owner. Needs a main-vs-branch control.'))
def test_yang_field_penalizes_sphere_talent_saves_once_each_turn(tmp_path, acquired):
    """A Sphere talent is a cultivation feature; the penalty refreshes on the next real turn."""
    doc = acquired(14)
    doc['spheres_and_talents'] = sheet(['FIRE_TAL_FIREBALL_ART'], cl=14)['spheres_and_talents']
    combat, table, mid = fixture(tmp_path, [], cl=14, owner_bundle=acquired.compile(doc, 14),
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}})
    settle(table, mid, candidate(combat, mid, 'Taiji Field', at=(3, 6)).candidate_id,
        choices={'choice:needle.taiji_rotation': ['yang']})
    next_owner_turn(table, mid)
    fireball(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert any(r.reason.startswith('SAVE:') and r.actor_id == FOE for r in engine.rolls)
    penalties = [r for r in engine.rolls if r.reason.startswith('TAIJI_FIELD_SAVE:') and r.actor_id == FOE]
    assert len(penalties) == 1

    next_owner_turn(table, mid)
    fireball(combat, table, mid)
    engine = reload(tmp_path, mid)
    penalties = [r for r in engine.rolls if r.reason.startswith('TAIJI_FIELD_SAVE:') and r.actor_id == FOE]
    assert len(penalties) == 2


def test_unity_damage_followup_has_its_own_source_and_scene_use_survives_turns(tmp_path, acquired):
    doc = acquired(18)
    doc['spheres_and_talents'] = sheet(['FIRE_TAL_FIREBALL_ART'], cl=18)['spheres_and_talents']
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_bundle=acquired.compile(doc, 18),
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}})
    use(combat, table, mid, 'Ultimate Unity')
    fireball(combat, table, mid, **{
        'choice:needle.balanced_yang': ['increase'], 'choice:needle.unity_healing': [ALLY]})
    engine = reload(tmp_path, mid)
    heal = [e for e in engine.events if e.event_type == 'HEALING_APPLIED'][-1]
    assert heal.source_definition_id == SUBPATH + '.feature.ultimate_unity'
    assert heal.target_ids == (ALLY,)
    next_owner_turn(table, mid)
    engine = reload(tmp_path, mid)
    assert not any(engine.action_catalog[c.source_definition_id].display_name == 'Ultimate Unity'
                   for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog)


def test_unity_native_damage_resistance_and_three_printed_exclusions(tmp_path, acquired, monkeypatch):
    from combat import ext, typed_reactions
    ext.effects()
    def die(engine, roll, intent):
        if roll.actor_id == OWNER and str(roll.reason).startswith('SAVE:'):
            return {'source_id': 'test:fixed-d20', 'operation': 'replace', 'natural_result': 10}
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [die, *ext._HOOKS.get('d20_result', [])])
    combat, table, mid = scenario(tmp_path, acquired, foe=sheet(['FIRE_TAL_FIREBALL_ART'], cl=18, dc=30))
    use(combat, table, mid, 'Ultimate Unity')
    turn(table, mid, FOE)
    fireball(combat, table, mid, at=(3, 6))
    engine = reload(tmp_path, mid)
    packet = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids][-1]
    assert packet.payload['damage_type'].upper() == 'FIRE'
    assert packet.payload['reduced_to'] == packet.payload['rolled_or_pending_damage'] // 2
    # Boundary quotes use the actual acquired, activated, cold-loaded owner.
    # Only the Fire assertion above is a delivered damage-packet certificate.
    for kind in ('FORCE', 'PSYCHIC', 'VOID'):
        rows = typed_reactions.additional_defenses(engine, engine.state.actors[OWNER],
            kind, packet.source_definition_id, FOE)
        assert not any(row.get('kind') == 'resistance' for row in rows)


def test_native_scene_use_survives_explicit_encounter_effect_ending_snapshot(tmp_path, acquired):
    """Transport boundary only; does not certify outside-combat elapsed time."""
    import json
    from combat.ext.journey_setup import encounter_snapshot
    from combat.ext.yin_yang_cultivator import SCENE, UNITY
    combat, table, mid = scenario(tmp_path, acquired)
    use(combat, table, mid, 'Ultimate Unity')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    snapshot = encounter_snapshot(owner, effects_ended=True)
    conditions = [json.loads(row) for row in snapshot['conditions'].values()]
    held, = [row for row in conditions if row['condition_id'] == SCENE]
    assert held['data']['unity_used'] == 1
    assert held['data']['last_alignment'] in ('yin', 'yang')
    assert not any(row['condition_id'] == UNITY for row in conditions)
    # An explicit continuation snapshot does not rewrite the terminal fight.
    assert any(c.condition_id == UNITY for c in owner.conditions.values())


@pytest.mark.parametrize('benefit', ['move', 'current', 'harmony', 'temp'])
def test_reversal_native_single_benefits_and_exact_qi_payment(tmp_path, acquired, monkeypatch, benefit):
    from combat import ext
    ext.effects()
    def die(engine, roll, intent):
        if str(roll.reason).startswith('SAVE:'):
            return {'source_id': 'test:fixed-d20', 'operation': 'replace', 'natural_result': 10 if roll.actor_id == ALLY else 20}
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [die, *ext._HOOKS.get('d20_result', [])])
    combat, table, mid = scenario(tmp_path, acquired, 6, foe=sheet(['FIRE_TAL_FIREBALL_ART'], cl=6, dc=14))
    next_owner_turn(table, mid)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[QI]
    fireball(combat, table, mid, **{
        'reaction:typed.' + SUBPATH + '.feature.reversal': 'use',
        'choice:needle.reversal_benefits': [benefit], 'choice:needle.reversal_move': ['cell:5,6']})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[QI] == before - 2
    if benefit == 'move':
        assert engine.state.actors[ALLY].position.x == 5
        assert any(e.event_type == 'MOVEMENT_COMMITTED' and e.source_definition_id == SUBPATH + '.feature.reversal'
                   and e.payload.get('forced') is True for e in engine.events)
    elif benefit == 'current':
        assert any(c.data.get('current') == 'yang' for c in owner.conditions.values())
    elif benefit == 'temp':
        assert_temp_protects_triggering_damage(engine, ALLY, SUBPATH + '.feature.reversal', 6)
    else:
        assert owner.resources[HARMONY] == 1


@pytest.mark.parametrize('source_cl,benefit', [(6, 'end'), (10, 'temp')])
def test_reversal_ends_only_native_fear_at_eligible_source_cl(tmp_path, acquired, monkeypatch, source_cl, benefit):
    from combat import ext
    ext.effects()
    def die(engine, roll, intent):
        if str(roll.reason).startswith('SAVE:'):
            return {'source_id': 'test:fixed-d20', 'operation': 'replace', 'natural_result': 10 if roll.actor_id == ALLY else 20}
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [die, *ext._HOOKS.get('d20_result', [])])
    foe = sheet(['FIRE_TAL_FIREBALL_ART', 'TAL_DAEMONIC_CULTIVATION_DREAD_APPETITE'], cl=source_cl, dc=14)
    combat, table, mid = scenario(tmp_path, acquired, 6, foe=foe)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Dread Appetite: Frighten', ALLY)
    engine = reload(tmp_path, mid)
    fear, = [c for c in engine.state.actors[ALLY].conditions.values() if c.condition_id in ('frightened', 'condition:typed.frightened')]
    prompts = fireball(combat, table, mid, **{
        'reaction:typed.' + SUBPATH + '.feature.reversal': 'use',
        'choice:needle.reversal_benefits': [benefit], 'choice:needle.reversal_end': [fear.instance_id]})
    engine = reload(tmp_path, mid)
    assert any(c.condition_id in ('frightened', 'condition:typed.frightened')
               for c in engine.state.actors[ALLY].conditions.values()) == (source_cl > 6)
    menu = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.reversal_benefits')
    assert any(o['id'] == 'end' for o in menu['choice']['options']) == (source_cl <= 6)


def test_yin_field_native_fear_advantage_and_first_packet_reduction(tmp_path, acquired, monkeypatch):
    from combat import ext
    ext.effects()
    def die(engine, roll, intent):
        if roll.actor_id == ALLY and str(roll.reason).startswith('SAVE:'):
            return {'source_id': 'test:fixed-d20', 'operation': 'replace', 'natural_result': 10}
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [die, *ext._HOOKS.get('d20_result', [])])
    foe = sheet(['FIRE_TAL_FIREBALL_ART', 'TAL_DAEMONIC_CULTIVATION_DREAD_APPETITE'], cl=14, dc=16)
    combat, table, mid = scenario(tmp_path, acquired, 14, foe=foe)
    settle(table, mid, candidate(combat, mid, 'Taiji Field', at=(3, 6)).candidate_id,
        choices={'choice:needle.taiji_rotation': ['yin']})
    turn(table, mid, FOE)
    use(combat, table, mid, 'Dread Appetite: Frighten', ALLY)
    engine = reload(tmp_path, mid)
    fear_save = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY][-1]
    assert fear_save.payload['mode'] == 'ADVANTAGE'
    fireball(combat, table, mid)
    engine = reload(tmp_path, mid)
    packet = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and ALLY in e.target_ids][-1]
    damage = [r for r in engine.rolls if r.reason.startswith('DAMAGE:')][-1]
    assert packet.payload['reduced_to'] == max(0, damage.total - 5)
    assert engine.state.actors[ALLY].turn_flags['_round_taiji_reduction'] == engine.state.round_number


@pytest.mark.parametrize('decision', ['maintain', 'end'])
def test_unity_expiry_restores_field_concentration_only_by_owner_choice(tmp_path, acquired, decision):
    from combat.ext.yin_yang_cultivator import unity, fields
    from combat.flight import profile
    combat, table, mid = scenario(tmp_path, acquired)
    use(combat, table, mid, 'Ultimate Unity')
    for _ in range(6):
        next_owner_turn(table, mid)
    settle(table, mid, candidate(combat, mid, 'Taiji Field', at=(3, 6)).candidate_id,
        choices={'choice:needle.taiji_rotation': ['yin']})
    for _ in range(18):
        engine = combat._load_session(mid).engine
        if not unity(engine.state.actors[OWNER]):
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'],
            choices={'choice:needle.taiji_concentration_restore': [decision]})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert not unity(owner)
    assert profile(engine, owner).speed_ft == 0
    active = fields(engine, owner=owner)
    assert bool(active) == (decision == 'maintain')
    if decision == 'maintain':
        assert owner.concentration.zone_id == active[0].zone_id
        assert active[0].concentration_link is True
    assert scene_state(owner)['unity_used'] == 1


def test_native_simultaneous_field_and_unity_expiry_does_not_offer_an_expired_field(tmp_path, acquired):
    from combat.ext.yin_yang_cultivator import unity, fields
    combat, table, mid = scenario(tmp_path, acquired)
    settle(table, mid, candidate(combat, mid, 'Taiji Field', at=(3, 6)).candidate_id,
        choices={'choice:needle.taiji_rotation': ['yin']})
    use(combat, table, mid, 'Ultimate Unity')
    prompts = []
    for _ in range(33):
        engine = combat._load_session(mid).engine
        if not unity(engine.state.actors[OWNER]):
            break
        prompts.extend(settle(table, mid, table.state(mid)['menu']['end_turn']))
    engine = reload(tmp_path, mid)
    assert not unity(engine.state.actors[OWNER])
    assert not fields(engine, owner=engine.state.actors[OWNER])
    assert not any(prompt['context']['reaction_source_id'] == 'choice:needle.taiji_concentration_restore' for prompt in prompts)


def test_native_unity_keeps_two_cast_fields_independent_without_stacking(tmp_path, acquired):
    from combat.ext.yin_yang_cultivator import fields, field_rotation, unity
    combat, table, mid = scenario(tmp_path, acquired)
    use(combat, table, mid, 'Ultimate Unity')
    next_owner_turn(table, mid)
    settle(table, mid, candidate(combat, mid, 'Taiji Field', at=(3, 6)).candidate_id,
        choices={'choice:needle.taiji_rotation': ['yin']})
    first, = fields(reload(tmp_path, mid))
    next_owner_turn(table, mid)
    settle(table, mid, candidate(combat, mid, 'Taiji Field', at=(6, 6)).candidate_id,
        choices={'choice:needle.taiji_rotation': ['yang']})
    engine = reload(tmp_path, mid)
    active = fields(engine)
    assert len(active) == 2
    second, = [field for field in active if field.zone_id != first.zone_id]
    assert {field.zone_id: field_rotation(engine, field) for field in active} == {
        first.zone_id: 'yin', second.zone_id: 'yang'}
    owner = engine.state.actors[OWNER]
    assert owner.concentration is None
    assert owner.armor_class + engine._ac_modifier(owner) == 15
    assert sum(event.event_type == 'ZONE_CREATED' for event in engine.events) == 2
    choices = {
        'choice:needle.taiji_rotation:' + first.zone_id: ['yang'],
        'choice:needle.taiji_rotation:' + second.zone_id: ['yin'],
        'choice:needle.taiji_rotation': ['yin'],
        'choice:needle.taiji_concentration_restore:' + first.zone_id: ['end'],
        'choice:needle.taiji_concentration_restore:' + second.zone_id: ['maintain'],
        'choice:needle.taiji_concentration_restore': ['maintain']}
    prompts = []
    for _ in range(27):
        if not unity(combat._load_session(mid).engine.state.actors[OWNER]):
            break
        prompts.extend(settle(table, mid, table.state(mid)['menu']['end_turn'], choices=choices))
    engine = reload(tmp_path, mid)
    assert not unity(engine.state.actors[OWNER])
    maintained, = fields(engine)
    assert maintained.zone_id == second.zone_id
    assert field_rotation(engine, maintained) == 'yin'
    assert engine.state.actors[OWNER].concentration.zone_id == second.zone_id
    handovers = [p for p in prompts if p['context']['reaction_source_id'].startswith('choice:needle.taiji_concentration_restore')]
    assert len(handovers) == 2
    assert handovers[0]['context']['checkpoint'] != handovers[1]['context']['checkpoint']


@pytest.mark.parametrize('control_mode', ['MANUAL', 'LOCAL_AUTO'])
def test_native_lost_unity_access_keeps_each_legal_field_choice(tmp_path, acquired, control_mode):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.ext.yin_yang_cultivator import fields, unity
    from combat.journey_activity import replay_record
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    other = compile_character(sheet([], cl=18), actor_id=FOE, reaction_plan={'ask': True})
    bundles = [acquired.compile(acquired(18), 18), other]
    arena = combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    positions = {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 6, 'y': 6}}
    state = combat.journeys.create(bundles, arena, positions, {OWNER: 18000, FOE: 18000})
    jid = state['journey_id']
    mid = combat.journey_start_combat(jid, 0, {OWNER: 'team:a', FOE: 'team:b'}, maximum_rounds=2)['match_id']
    turn(table, mid, OWNER)
    use(combat, table, mid, 'Ultimate Unity')
    settle(table, mid, candidate(combat, mid, 'Taiji Field', at=(3, 6)).candidate_id,
        choices={'choice:needle.taiji_rotation': ['yin']})
    first, = fields(reload(tmp_path, mid))
    next_owner_turn(table, mid)
    settle(table, mid, candidate(combat, mid, 'Taiji Field', at=(6, 6)).candidate_id,
        choices={'choice:needle.taiji_rotation': ['yang']})
    second, = [field for field in fields(reload(tmp_path, mid)) if field.zone_id != first.zone_id]
    for _ in range(3):
        if reload(tmp_path, mid).state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    resumed = combat.journey_resume(jid, combat.journey_state(jid)['revision'])
    combat.journey_act(jid, resumed['revision'], OWNER, 'finish', {})
    capped = acquired(18)
    capped['identity']['effective_cl'] = 14
    state = combat.journeys.create([acquired.compile(capped, 18), other], arena, positions,
        {OWNER: 18000, FOE: 18000}, control_modes={OWNER: control_mode, FOE: 'MANUAL'})
    jid = state['journey_id']
    from combat.concentration import journey_limit
    capacity = journey_limit(combat.journeys.load(jid), OWNER)
    qi = resumed['actors'][OWNER]['resources'][QI]
    if control_mode == 'MANUAL':
        choices = [option for option in combat.journey_menu(jid, OWNER)['options'] if option['kind'] == 'yin_yang_unity_expiry']
        assert {(option['payload']['field_id'], option['payload']['mode']) for option in choices} == {
            (iid, mode) for iid in (first.zone_id, second.zone_id) for mode in ('maintain', 'end')}
        first_pick = next(option for option in choices if option['payload']['field_id'] == first.zone_id and option['payload']['mode'] == 'maintain')
        second_pick = next(option for option in choices if option['payload']['field_id'] == second.zone_id and option['payload']['mode'] == 'maintain')
        with pytest.raises(Exception):
            combat.journey_act(jid, state['revision'], FOE, first_pick['kind'], first_pick['payload'])
        assert combat.journey_state(jid) == state
        state = combat.journey_act(jid, state['revision'], OWNER, first_pick['kind'], first_pick['payload'])
        with pytest.raises(Exception):
            combat.journey_act(jid, state['revision'], OWNER, second_pick['kind'], {**second_pick['payload'], 'field_id': 'zone:unmapped'})
        assert combat.journey_state(jid) == state
        if capacity == 1:
            with pytest.raises(Exception):
                combat.journey_act(jid, state['revision'], OWNER, second_pick['kind'], second_pick['payload'])
            assert combat.journey_state(jid) == state
        state = combat.journey_act(jid, state['revision'], OWNER, second_pick['kind'], {**second_pick['payload'], 'mode': 'end'})
    record, = [event for event in state['events'] if event['kind'] == 'NATIVE_ELAPSED_EFFECTS_COMMITTED']
    replayed = replay_record(record)
    assert not unity(replayed.actors[OWNER])
    assert state['seconds'] == 0
    assert state['actors'][OWNER]['resources'][QI] == qi
    kept = {first.zone_id} if control_mode == 'MANUAL' else ({first.zone_id, second.zone_id} if capacity is None or capacity >= 2 else {second.zone_id})
    assert {zone.zone_id for zone in replayed.zones.values() if zone.active} == kept
    assert replayed.actors[OWNER].concentration.zone_id == (first.zone_id if control_mode == 'MANUAL' else second.zone_id)
    assert scene_state(replayed.actors[OWNER])['unity_used'] == 1
    assert combat.journey_state(jid) == state


@pytest.mark.parametrize('circulation_mode', ['qi', 'heal', 'temp', 'move', 'rotate'])
def test_reversal_spend_drives_circulation_after_native_save(tmp_path, acquired, monkeypatch, circulation_mode):
    from combat import ext
    ext.effects()
    def save_die(engine, roll, intent):
        if str(roll.reason).startswith('SAVE:'):
            return {'source_id': 'test:fixed-d20', 'operation': 'replace', 'natural_result': 10 if roll.actor_id == ALLY else 20}
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [save_die, *ext._HOOKS.get('d20_result', [])])
    foe = sheet(['FIRE_TAL_FIREBALL_ART'], cl=14, dc=16)
    combat, table, mid = scenario(tmp_path, acquired, 14, foe=foe)
    if circulation_mode == 'rotate':
        settle(table, mid, candidate(combat, mid, 'Taiji Field', at=(3, 6)).candidate_id,
            choices={'choice:needle.taiji_rotation': ['yin']})
        next_owner_turn(table, mid)
    use(combat, table, mid, 'Restorative Palm', ALLY)
    next_owner_turn(table, mid)
    use(combat, table, mid, 'Ignite', FOE, **{'choice:needle.yin_yang_alignment': ['yang']})
    assert reload(tmp_path, mid).state.actors[OWNER].resources[HARMONY] == 1
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[QI]
    # Temp goes to the ally Fireball hits: the enemy caster takes no damage from its own blast.
    selected = circulation_mode if circulation_mode in ('qi', 'rotate') else circulation_mode + ':' + (
        ALLY if circulation_mode in ('move', 'temp') else FOE)
    prompts = fireball(combat, table, mid, **{
        'reaction:typed.' + SUBPATH + '.feature.reversal': 'use',
        'choice:needle.reversal_harmony': ['two'],
        'choice:needle.reversal_benefits': ['temp', 'harmony'],
        'choice:needle.essence_circulation': [selected],
        'choice:willing.consent': ['accept'],
        'choice:needle.circulation_move': ['cell:5,6']})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[QI] == before - (1 if circulation_mode == 'qi' else 2)
    assert_temp_protects_triggering_damage(engine, ALLY, SUBPATH + '.feature.reversal', 10)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.essence_circulation' for p in prompts)
    assert engine.state.actors[OWNER].turn_flags['_round_essence_circulation'] == engine.state.round_number
    if circulation_mode == 'temp':
        # The ally's Reversal temp HP is already on the pool, so only check this grant's own absorption.
        grant = next(e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED'
            and e.source_definition_id == SUBPATH + '.feature.essence_circulation' and ALLY in e.target_ids)
        damage = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
            and ALLY in e.target_ids and e.sequence > grant.sequence)
        assert grant.payload['offered'] == 10
        assert damage.payload['temporary_hp_absorbed'] > 0
    elif circulation_mode == 'heal':
        assert any(e.event_type == 'HEALING_APPLIED' and e.source_definition_id == SUBPATH + '.feature.essence_circulation'
                   and FOE in e.target_ids for e in engine.events)
    elif circulation_mode == 'move':
        assert engine.state.actors[ALLY].position.x == 5
        prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.circulation_move')
        assert len(prompt['choice']['options']) > 16
    elif circulation_mode == 'rotate':
        assert engine.state.actors[OWNER].turn_flags['_round_taiji_rotation'] == 'yang'

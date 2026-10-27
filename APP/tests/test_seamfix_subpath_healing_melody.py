"""Native acquisition, physical delivery and Healing Melody table regressions.

No fabricated compiled actions or condition markers certify this row. NS1R
admission acquires Sound Cultivator, the compiler grants its source progression,
and actual techniques create wounds, deafness, fear and charm. Every table
assertion cold-loads the saved fight and verifies mechanical replay.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.core import Database, Settings, FoundryError
from combat.factory_compiler import compile_character
from combat.ext.end_effect import known_source_cl
from combat.resonance import normalize_media, connected_performance, receives_performance
from combat.tabletop import TabletopMapStore, to_battlefield, battlefield_as_map
from combat.gate5_service import CombatServiceError
from non_sphere_authority import NonSphereAuthorityService
from tests.h1_support import ROOT, sheet
from tests.ns1r_evidence_helpers import install_authority_test_pack, ap_award
from tests.test_ns1r_non_sphere_authority import insert_project
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn
from tests.test_r9i_karma_persistence import act

QI = 'tianxia.path.qi_cultivation'
SUBPATH = 'tianxia.subpath.qi.sound_cultivator'
MELODY = SUBPATH + '.feature.healing_melody'


@pytest.fixture(scope='module')
def acquired(tmp_path_factory):
    settings = Settings.from_env(ROOT, tmp_path_factory.mktemp('melody-acquisition'))
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    service = NonSphereAuthorityService(db)
    install_authority_test_pack(db, service)
    documents = {}
    def get(cl, subpath=SUBPATH):
        key = (cl, subpath)
        if key not in documents:
            project = 'melody-cl-' + str(cl) + ('' if subpath == SUBPATH else '-' + subpath.rsplit('.', 1)[-1])
            insert_project(db, project, cl)
            service.initialize_for_project(project, target_cl=cl, path_ids=[QI], method_id='METHOD-001')
            service.allocate_advancement(project, {QI: cl - 1},
                evidence_id=ap_award(db, service, project, 'METHOD-001', cl, cl - 1),
                idempotency_key=project + '-advance')
            service.select_subpath(project, QI, subpath)
            # Reopen the actual persisted acquisition before publishing its Path rows.
            state = NonSphereAuthorityService(db).get_state(project)
            doc = sheet([], cl=cl, name='Melody performer')
            if subpath != SUBPATH:
                doc['identity']['name'] = 'Mantra performer'
            doc['path_and_subpath'] = {'paths': state['paths']}
            documents[key] = doc
        return deepcopy(documents[key])
    get.service = service
    return get


def arena(tmp_path, media):
    store = TabletopMapStore(tmp_path / 'maps')
    store.save({'map_id': 'resonance-test', 'display_name': 'Stone walkway and water',
                'width_squares': 20, 'height_squares': 14, 'resonant_media': media})
    # Both the saved editor format and the engine format are native producers.
    return to_battlefield(store.get('resonance-test'))


def medium(material='solid', *, gap=False, blocked=False):
    return [{'id': 'walkway', 'material': material,
             'cells': [{'x': x, 'y': 6, 'z': 0} for x in range(3, 7) if not (gap and x == 5)],
             **({'blocked_cells': [{'x': 5, 'y': 6, 'z': 0}]} if blocked else {})}]


def scenario(tmp_path, acquired, *, cl=6, effective_cl=None, media=None, foe=None, ask=True, modes=None, positions=None,
             extra_allies=0, team_overrides=None):
    doc = acquired(cl)
    if effective_cl is not None:
        next(r for r in doc['path_and_subpath']['paths'] if r['path_id'] == QI)['effective_cl'] = effective_cl
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': ask})
    return fixture(tmp_path, [], cl=cl, ask=ask, owner_bundle=owner, foe_sheet=foe,
                   modes=modes, positions=positions,
                   extra_allies=extra_allies, team_overrides=team_overrides,
                   battlefield=arena(tmp_path, media) if media is not None else None,
                   seed='SEAMFIX-MELODY')


def melody_candidates(engine, target=ALLY):
    return [c for c in engine.legal_candidates() if c.target_ids == (target,)
            and ((engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source') == MELODY)]


def play(combat, table, mid, name, target=None, *, choices=None, at=None):
    selected = candidate(combat, mid, name, target=target, at=at)
    return settle(table, mid, selected.candidate_id, choices=choices or {})


@pytest.mark.parametrize('cl,count,effective_cl', [(6, 2, None), (14, 3, None), (18, 4, None), (18, 2, 6)])
def test_acquire_compile_heal_commit_cold_reload(tmp_path, acquired, cl, count, effective_cl):
    combat, table, mid = scenario(tmp_path, acquired, cl=cl, effective_cl=effective_cl)
    # The acquired CL3 Bonus Action is a genuine wound producer, not a test action.
    play(combat, table, mid, 'Instrument of Qi: Thunder', FOE)
    before = reload(tmp_path, mid)
    hp = before.state.actors[FOE].current_hp
    assert hp < before.state.actors[FOE].maximum_hp
    qi = before.state.actors[OWNER].resources['resource:core.qi']
    prompts = play(combat, table, mid, 'Healing Melody', FOE,
                   choices={'choice:needle.qi5_melody': ['move']})
    after = reload(tmp_path, mid)
    rolls = [r for r in after.rolls if r.reason.startswith('HEALING:')]
    assert rolls[-1].expression.startswith(f'{count}d8')
    assert rolls[-1].total == sum(rolls[-1].dice) + 2
    assert rolls[-1].total >= count + 2
    assert after.state.actors[FOE].current_hp == min(60, hp + rolls[-1].total)
    assert after.state.actors[OWNER].resources['resource:core.qi'] == qi - 2
    assert not after.state.actors[OWNER].action_available
    benefit = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.qi5_melody')
    assert benefit['choice']['minimum'] == benefit['choice']['maximum'] == 1
    assert not melody_candidates(after, FOE), 'one action cannot activate again'


@pytest.mark.parametrize('control', ['below', 'suppressed', 'wrong_parent', 'unowned'])
def test_native_acquisition_boundaries(tmp_path, acquired, control):
    doc = acquired(5 if control == 'below' else 18)
    if control == 'suppressed':
        next(r for r in doc['path_and_subpath']['paths'] if r['path_id'] == QI)['effective_cl'] = 5
        # A stale exported occurrence must not reopen a suppressed native tier.
        doc['path_and_subpath']['source_granted_subpath_feature_record_ids'] = [MELODY]
    elif control == 'wrong_parent':
        row = next(r for r in doc['path_and_subpath']['paths'] if r['path_id'] == QI)
        row['path_id'] = 'tianxia.path.body_refining'
        doc['path_and_subpath']['source_granted_subpath_feature_record_ids'] = [MELODY]
    elif control == 'unowned':
        doc['path_and_subpath'] = {}
    bundle = compile_character(doc, actor_id=OWNER)
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle, cl=18)
    engine = reload(tmp_path, mid)
    assert not melody_candidates(engine)
    assert all((a.parameters.get('typed') or {}).get('source') != MELODY for a in engine.action_catalog.values())


def test_native_acquisition_rejects_wrong_path(acquired):
    acquired(6)
    with pytest.raises(FoundryError) as error:
        acquired.service.select_subpath('melody-cl-6', 'tianxia.path.body_refining', SUBPATH)
    assert error.value.code == 'NS1R_PATH_SUBPATH_MISMATCH'
    assert acquired.service.subpaths[SUBPATH]['access']['canonical_category'] == 'Open School'


def test_legacy_explicit_ownership_still_checks_printed_cl6_before_payment(tmp_path):
    """Admission guard for an explicit historical feature list, not acquisition proof."""
    combat, table, mid = fixture(tmp_path, [], cl=5, owner_features=[MELODY])
    engine = reload(tmp_path, mid)
    assert any((action.parameters.get('typed') or {}).get('source') == MELODY
               for action in engine.action_catalog.values())
    assert not melody_candidates(engine)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 100
    assert engine.state.actors[OWNER].action_available


@pytest.mark.parametrize('feet,offered', [(30, True), (35, False)])
def test_range_before_payment(tmp_path, acquired, feet, offered):
    positions = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 3 + feet // 5, 'y': 6}, FOE: {'x': 3, 'y': 9}}
    combat, table, mid = scenario(tmp_path, acquired, media=[], positions=positions)
    engine = reload(tmp_path, mid)
    assert bool(melody_candidates(engine)) is offered
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 30


@pytest.mark.parametrize('material,gap,blocked,offered', [
    ('solid', False, False, True), ('liquid', False, False, True),
    ('solid', True, False, False), ('solid', False, True, False),
    ('liquid', True, False, False), ('liquid', False, True, False),
    ('unknown', False, False, False)])
def test_native_deafness_requires_contact_connectivity_and_no_blocker(tmp_path, acquired, material, gap, blocked, offered):
    foe = acquired(10)
    foe['ability_scores_and_statistics']['technique_save_dc'] = 100
    geometry = [] if material == 'unknown' else medium(material, gap=gap, blocked=blocked)
    positions = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 6, 'y': 6}, FOE: {'x': 8, 'y': 6}}
    combat, table, mid = scenario(tmp_path, acquired, media=geometry, foe=foe, positions=positions)
    turn(table, mid, FOE)
    play(combat, table, mid, 'Shattering Note', at=(3, 6))
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.deafened' for c in before.state.actors[ALLY].conditions.values())
    assert bool(melody_candidates(before)) is offered
    if offered:
        play(combat, table, mid, 'Healing Melody', ALLY,
             choices={'choice:needle.qi5_melody': ['move']})
        after = reload(tmp_path, mid)
        assert after.state.actors[OWNER].resources['resource:core.qi'] == 28
    else:
        assert before.state.actors[OWNER].action_available
        assert before.state.actors[OWNER].resources['resource:core.qi'] == 30


@pytest.mark.parametrize('caster_cl,removable', [(10, True), (14, True), (6, False)])
def test_native_deafness_source_authority_and_exact_choice(tmp_path, acquired, caster_cl, removable):
    foe = acquired(10)
    foe['ability_scores_and_statistics']['technique_save_dc'] = 100
    combat, table, mid = scenario(tmp_path, acquired, cl=caster_cl, media=medium(), foe=foe)
    turn(table, mid, FOE)
    play(combat, table, mid, 'Shattering Note', at=(3, 6))
    turn(table, mid, OWNER)
    prompts = play(combat, table, mid, 'Healing Melody', ALLY,
                   choices={'choice:needle.qi5_melody': ['deafened'] if removable else ['move']})
    menu = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.qi5_melody')
    assert ('deafened' in [o['id'] for o in menu['choice']['options']]) is removable
    after = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.deafened' for c in after.state.actors[ALLY].conditions.values()) is not removable


@pytest.mark.parametrize('caster_cl,removable', [(14, True), (18, True), (6, False)])
def test_native_fear_source_authority(tmp_path, acquired, caster_cl, removable):
    foe = acquired(14)
    foe['ability_scores_and_statistics']['technique_save_dc'] = 100
    combat, table, mid = scenario(tmp_path, acquired, cl=caster_cl, foe=foe)
    turn(table, mid, FOE)
    play(combat, table, mid, 'Song of Fear')
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.frightened' for c in before.state.actors[OWNER].conditions.values())
    play(combat, table, mid, 'Healing Melody', OWNER,
         choices={'choice:needle.qi5_melody': ['frightened'] if removable else ['move']})
    after = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.frightened' for c in after.state.actors[OWNER].conditions.values()) is not removable


@pytest.mark.parametrize('dc,cleared', [(100, False), (12, True)])
def test_original_native_charm_save_is_retained_with_advantage(tmp_path, acquired, dc, cleared):
    foe = sheet(['TAL_BEASTMASTERY_BEAST_TAMER'], cl=6, dc=dc, name='Beast Tamer')
    combat, table, mid = scenario(tmp_path, acquired, foe=foe)
    turn(table, mid, FOE)
    play(combat, table, mid, 'Beast Tamer', ALLY)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    charm = next(c for c in before.state.actors[ALLY].conditions.values() if c.condition_id == 'condition:typed.charmed')
    spec = charm.data.get('repeat_save') or charm.data['origin_save']
    play(combat, table, mid, 'Healing Melody', ALLY,
         choices={'choice:needle.qi5_melody': ['charmed:0']})
    after = reload(tmp_path, mid)
    rolls = [r for r in after.rolls if r.actor_id == ALLY and r.reason.startswith('SAVE:')]
    assert rolls[-1].reason.endswith(':' + spec['ability'])
    assert rolls[-1].mode == 'ADVANTAGE'
    assert (rolls[-1].total >= spec['dc']) is cleared
    assert (charm.instance_id not in after.state.actors[ALLY].conditions) is cleared


@pytest.mark.parametrize('qi,offered', [(1, False), (2, True)])
def test_exact_qi_boundary_before_payment(tmp_path, acquired, qi, offered):
    doc = acquired(6)
    doc['ability_scores_and_statistics']['primary_resource']['maximum'] = qi
    bundle = compile_character(doc, actor_id=OWNER)
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle, cl=6)
    before = reload(tmp_path, mid)
    assert bool(melody_candidates(before)) is offered
    if offered:
        play(combat, table, mid, 'Healing Melody', ALLY)
        assert reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi'] == 0
    else:
        assert before.state.actors[OWNER].resources['resource:core.qi'] == 1
        assert before.state.actors[OWNER].action_available


@pytest.mark.parametrize('move', [False, True])
def test_exactly_one_benefit_and_recipient_owned_move_or_stay(tmp_path, acquired, move):
    positions = {OWNER: {'x': 4, 'y': 7}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 5, 'y': 6}}
    combat, table, mid = scenario(tmp_path, acquired, positions=positions)
    cid = candidate(combat, mid, 'Healing Melody', target=ALLY).candidate_id
    before = reload(tmp_path, mid).state.model_dump(mode='json')
    pause = act(table, mid, cid)
    assert pause['status'] == 'REACTION_REQUIRED'
    benefit = pause['reaction']
    with pytest.raises(CombatServiceError):
        act(table, mid, cid, [{**benefit['context'], 'selection': 'USE', 'option_ids': ['move', 'move']}])
    assert reload(tmp_path, mid).state.model_dump(mode='json') == before
    answer = {**benefit['context'], 'selection': 'USE', 'option_ids': ['move']}
    result = act(table, mid, cid, [answer])
    assert result['status'] == 'REACTION_REQUIRED'
    step = result['reaction']
    assert step['context']['reactor_id'] == ALLY
    assert step['context']['reaction_source_id'] == 'choice:needle.rider_step'
    assert len(step['choice']['options']) >= 2
    selected = 'cell:3,6' if move else 'cell:4,6'
    assert selected in {o['id'] for o in step['choice']['options']}
    result = act(table, mid, cid, [answer, {**step['context'], 'selection': 'USE', 'option_ids': [selected]}])
    assert result['status'] == 'COMMITTED'
    after = reload(tmp_path, mid)
    pos = after.state.actors[ALLY].position
    assert (pos.x, pos.y) == ((3, 6) if move else (4, 6))
    if move:
        assert after._distance_actor_to_actor(after.state.actors[ALLY], after.state.actors[FOE]) > 5
    from combat.gate2_engine import SYSTEM_OPPORTUNITY
    assert not any(e.source_definition_id == SYSTEM_OPPORTUNITY
                   and e.event_type in {'REACTION_WINDOW_OPENED', 'REACTION_RESOLVED'} for e in after.events)
    assert after.state.actors[FOE].reaction_available
    assert after.state.actors[ALLY].current_hp == 60


def test_unknown_source_cl_never_becomes_one():
    ctx = SimpleNamespace(engine=SimpleNamespace(action_catalog={}, typed_bundle_documents=[{'actor_id': 'actor:source', 'cl': 1}]))
    instance = SimpleNamespace(source_definition_id='missing', source_actor_id='actor:source', data={})
    assert known_source_cl(ctx, instance) is None
    instance.data = {'source_cl': 9}
    assert known_source_cl(ctx, instance) == 9
    instance.data = {'source_cl': '9'}
    assert known_source_cl(ctx, instance) is None


@pytest.mark.parametrize('rule', [{'cant_hear': True}, {'sound_blocked': True}])
def test_native_hearing_rules_are_shared(tmp_path, acquired, monkeypatch, rule):
    from combat import typed_executor
    combat, table, mid = scenario(tmp_path, acquired, media=[])
    engine = reload(tmp_path, mid)
    actor, listener = engine.state.actors[OWNER], engine.state.actors[ALLY]
    original = typed_executor.condition_rules
    monkeypatch.setattr(typed_executor, 'condition_rules', lambda a: [rule] if a is listener else original(a))
    assert not receives_performance(engine, actor, listener)


def test_native_sound_path_is_consulted_without_spending(tmp_path, acquired, monkeypatch):
    from combat import ext
    combat, table, mid = scenario(tmp_path, acquired, media=[])
    engine = reload(tmp_path, mid)
    real = ext.run_strict
    calls = []
    def path(name, *args, **kwargs):
        if name == 'sound_path_allowed':
            calls.append(args)
            return [False]
        return real(name, *args, **kwargs)
    monkeypatch.setattr(ext, 'run_strict', path)
    assert not melody_candidates(engine)
    assert calls
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 30


@pytest.mark.parametrize('change', ['flight_capability', 'height', 'off_surface', 'explicit_block'])
def test_physical_contact_guards(tmp_path, acquired, monkeypatch, change):
    combat, table, mid = scenario(tmp_path, acquired, media=medium())
    engine = reload(tmp_path, mid)
    actor, listener = engine.state.actors[OWNER], engine.state.actors[ALLY]
    assert connected_performance(engine, actor, listener)
    if change == 'height':
        listener.position = listener.position.model_copy(update={'z': 1})
    elif change == 'off_surface':
        listener.position = listener.position.model_copy(update={'y': 7})
    elif change == 'flight_capability':
        listener.fly_speed_ft = 30
        listener.hover = True
        assert connected_performance(engine, actor, listener)
        return
    else:
        from combat import typed_executor
        original = typed_executor.condition_rules
        monkeypatch.setattr(typed_executor, 'condition_rules', lambda a: [{'vibration_blocked': True}] if a is listener else original(a))
    assert not connected_performance(engine, actor, listener)


@pytest.mark.parametrize('mutation', ['material', 'outside', 'duplicate', 'blocker', 'float'])
def test_map_geometry_validation(mutation):
    rows = medium()
    if mutation == 'material': rows[0]['material'] = 'air'
    elif mutation == 'outside': rows[0]['cells'][0]['x'] = 20
    elif mutation == 'duplicate': rows[0]['cells'].append(rows[0]['cells'][0])
    elif mutation == 'float': rows[0]['cells'][0]['z'] = 0.5
    else: rows[0]['blocked_cells'] = [{'x': 19, 'y': 13}]
    with pytest.raises(ValueError): normalize_media(rows, 20, 14)


def test_medium_map_round_trip_and_empty_default(tmp_path):
    geometry = medium('liquid', blocked=True)
    original = arena(tmp_path, geometry)
    assert battlefield_as_map(original)['resonant_media'] == geometry
    assert 'resonant_media' not in arena(tmp_path, [])


def test_native_mantra_boundary_blocks_melody_even_when_both_endpoints_hear(tmp_path, acquired):
    from combat import speech, typed_executor
    foe = acquired(18, 'tianxia.subpath.qi.mantra_cultivator')
    positions = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 9, 'y': 6}, FOE: {'x': 6, 'y': 6}}
    combat, table, mid = scenario(tmp_path, acquired, foe=foe, media=[], positions=positions)
    turn(table, mid, FOE)
    play(combat, table, mid, 'Mantra of Silence', at=(0, 6),
         choices={'choice:needle.mantra_silence_exempt': [OWNER]})
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    performer, listener = engine.state.actors[OWNER], engine.state.actors[ALLY]
    assert not typed_executor.cant_hear(performer)
    assert not typed_executor.cant_hear(listener)
    assert not speech.can_hear_from(engine, performer, listener)
    assert not melody_candidates(engine)
    assert performer.resources['resource:core.qi'] == 30
    assert performer.action_available


@pytest.mark.parametrize('recipient', [FOE, 'actor:factory.worker2-ally3'])
def test_ai_keeps_every_known_legal_recipient_and_ranks_without_hidden_state(tmp_path, acquired, recipient):
    from combat.gate4_adapters import ManualControllerAdapter
    from combat.gate4_context import build_decision_context
    from combat.ext.qi_subpaths_five import melody_healing_value
    neutral = 'actor:factory.worker2-ally3'
    modes = {OWNER: 'LOCAL_AUTO', ALLY: 'MANUAL', FOE: 'MANUAL', neutral: 'MANUAL'}
    combat, table, mid = scenario(tmp_path, acquired, modes=modes, ask=False, extra_allies=1,
                                  team_overrides={neutral: 'team:neutral'})
    session = combat._load_session(mid)
    policy = combat._decision_model(session).policy
    context = build_decision_context(session.engine, policy, for_ai=True)
    rows = [c for c in context.legal_candidates if c.source_definition_id.endswith(MELODY)]
    assert {(OWNER,), (ALLY,), (FOE,), (neutral,)} <= {c.target_ids for c in rows}
    ally = next(c for c in rows if c.target_ids == (ALLY,))
    enemy = next(c for c in rows if c.target_ids == (FOE,))
    assert melody_healing_value(context, ally, ())[0].value > melody_healing_value(context, enemy, ())[0].value
    hidden = context.model_copy(update={'actors': tuple(a for a in context.actors if a.entity_id != FOE)})
    assert melody_healing_value(hidden, enemy, ()) is None
    real = combat.controller
    class ChooseLegalEnemy:
        def choose_primary_action(self, decision):
            selected = next(c for c in decision.legal_candidates
                            if c.source_definition_id.endswith(MELODY) and c.target_ids == (recipient,))
            return ManualControllerAdapter(lambda _: (selected.candidate_id, ())).choose_primary_action(decision)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = ChooseLegalEnemy()
    result = table.auto_step(mid, table.state(mid)['last_sequence'], [])
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['context']['reactor_id'] == recipient
    assert prompt['context']['reaction_source_id'] == 'choice:needle.rider_step'
    stay = next(o['id'] for o in prompt['choice']['options'] if o['label'].startswith('Stay where you are'))
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': [stay]}
    assert table.auto_step(mid, 0, [answer])['status'] == 'COMMITTED'
    assert reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi'] == 28

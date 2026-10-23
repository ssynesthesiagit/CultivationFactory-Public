"""Public synthetic table regressions for the five Seals review findings."""
from copy import deepcopy
import pytest

from combat import ext, summons
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition, ReactionDecision, Position
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield
from combat.ext import qi_sealing_chains as q
from tests.test_mgr_t14_cultivator_of_seals_floor58 import (
    ROOT, SHEET, ME, FOE, acquired_sheet, act, setup,
)

THIRD = 'actor:factory.passage-witness'
POINTS = [(3, 3), (7, 3), (5, 7)]
QI = 'resource:core.qi'


def answer(**answers):
    def provider(request):
        key = request['reaction_source_id'].split('.')[-1]
        pick = answers.get(key)
        if pick is None:
            return None, None
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=(pick,)), None
    return provider


def native(session, feature, suffix=None):
    return next(c for c in session.engine.legal_candidates() if c.target_ids == (FOE,)
        and (a := session.engine.action_catalog.get(c.source_definition_id))
        and q.source_feature(a) == feature
        and (suffix is None or c.source_definition_id.endswith(suffix)))


def end(session):
    act(session, next(c for c in session.engine.legal_candidates() if c.kind.value == 'END_TURN'))


def turn(session, actor):
    for _ in range(8):
        if session.engine.state.current_actor_id == actor:
            return
        end(session)
    raise AssertionError('turn did not arrive')


def reload(session, tmp_path):
    loaded = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return loaded


def bindings(session, feature=q.EDICT):
    return sorted([c for _, c in q.seals(session.engine, session.engine.state.actors[FOE])
                   if c.data['seal_feature'] == feature], key=lambda c: c.data.get('pillar', 0))


def synthetic_action(owner, key, effects, *, costs=(), target='SELF', economy='NONE', cl=None):
    typed = {'source': 'test:' + key, 'effects': effects, 'riders': [],
             'numbers': {'pb': 4, 'key_mod': 2, 'cl': cl or 10, 'save_dc': 50}}
    if cl is not None:
        typed['activation_profile'] = {'source_kind': 'Sphere', 'source_cl': cl}
    return ActionDefinition(source_definition_id='test:' + owner + ':' + key,
        owner_id=owner, display_name=key, economy=economy, resolution_kind='TYPED',
        target_kind=target, range_ft=90, costs=costs,
        parameters={'typed': typed, 'expected_damage': 0}).model_dump(mode='json')


def table(tmp_path, *, target_cl=10, third_cl=10, target_saves=None, source_dc=50):
    source = acquired_sheet()
    source['ability_scores_and_statistics']['technique_save_dc'] = source_dc
    target = deepcopy(SHEET)
    target['identity'].update(cultivation_level=target_cl, name='Target')
    target['path_and_subpath'] = {'path_record_ids': ['tianxia.path.qi_cultivation']}
    target['spheres_and_talents'] = {'learned_talent_record_ids': ['tianxia.talent.ink.painted_beast']}
    if target_saves:
        target['ability_scores_and_statistics']['saving_throws'] = target_saves
    third = deepcopy(target)
    third['identity'].update(cultivation_level=third_cl, name='Traveller')
    third['spheres_and_talents'] = {'learned_talent_record_ids': ['tianxia.talent.ink.painted_beast']}
    bundles = [compile_character(sheet, actor_id=actor)
               for sheet, actor in [(source, ME), (target, FOE), (third, THIRD)]]
    bundles[1]['action_catalog'] += [
        synthetic_action(FOE, 'shapechange', [{'type': 'transform'}]),
        synthetic_action(FOE, 'summon', [{'type': 'summon', 'group': 'painted_beast'}]),
        synthetic_action(FOE, 'spend-two', [], costs=((QI, 2),)),
    ]
    bundles[0]['action_catalog'].append(synthetic_action(ME, 'off-turn-spend',
        [{'type': 'spend_resource', 'resource_id': QI, 'flat': 1}], target='ANY_CREATURE'))
    bundles[2]['action_catalog'] += [
        synthetic_action(THIRD, 'teleport', [{'type': 'teleport', 'distance_ft': 60}], cl=third_cl),
        synthetic_action(THIRD, 'project', [{'type': 'damage', 'flat': 1, 'damage_type': 'FORCE'}],
                         target='ANY_CREATURE', cl=third_cl),
    ]
    place = synthetic_action(THIRD, 'summon-place', [{'type': 'summon', 'group': 'painted_beast'}],
                             target='CELL', cl=third_cl)
    place['parameters'].update(cell_placement={}, summon_group='painted_beast')
    bundles[2]['action_catalog'].append(place)
    from combat.canonical import canonical_sha256
    for bundle in bundles:
        ids = bundle['actor_template']['action_ids']
        ids.extend(a['source_definition_id'] for a in bundle['action_catalog']
                   if a['source_definition_id'].startswith('test:') and a['source_definition_id'] not in ids)
        bundle.pop('bundle_sha256')
        bundle['bundle_sha256'] = canonical_sha256(bundle)
    service = CombatService(ROOT, tmp_path)
    arena = to_battlefield(normalize_map({'width_squares': 16, 'height_squares': 12}))
    mid = service._finish_factory_match(bundles, [ME, FOE, THIRD],
        {ME: 'team:a', FOE: 'team:b', THIRD: 'team:c'},
        {ME: {'x': 4, 'y': 5}, FOE: {'x': 5, 'y': 5}, THIRD: {'x': 9, 'y': 5}},
        arena, [ME], [FOE, THIRD], control_modes={ME: 'LOCAL_AUTO', FOE: 'LOCAL_AUTO', THIRD: 'LOCAL_AUTO'},
        match_seed='SEALS-REVIEW', display_name='Review table', maximum_rounds=20)['match_id']
    session = service._load_session(mid)
    turn(session, ME)
    return session


def use(session, key, *, target=None, destination=None):
    options = session.engine.legal_candidates()
    candidate = next(c for c in options
        if c.source_definition_id.endswith(':' + key)
        and (target is None or c.target_ids == (target,))
        and (destination is None or c.destination == Position(x=destination[0], y=destination[1])))
    act(session, candidate)


def cast_edict(session):
    act(session, native(session, q.EDICT), answer(**{
        'pillar_' + str(i): f'cell:{x},{y}' for i, (x, y) in enumerate(POINTS)}))


@pytest.mark.parametrize('kind,key', [('transformation', 'shapechange'), ('summons', 'summon')])
def test_functional_broad_category_selection_suppression_and_reload(tmp_path, kind, key):
    session = table(tmp_path)
    # No witnessed subtype facts are present or required for Functional categories.
    act(session, native(session, q.MARK), answer(scope=kind, consent='resist'))
    session = reload(session, tmp_path)
    mark, = bindings(session, q.MARK)
    assert mark.data['scope'] == {'kind': kind, 'value': ''}
    turn(session, FOE)
    offered = {c.source_definition_id for c in session.engine.legal_candidates()}
    assert not any(s.endswith(':' + key) for s in offered)
    other = 'summon' if key == 'shapechange' else 'shapechange'
    assert any(s.endswith(':' + other) for s in offered)
    # This is the actual executable operation profile, not a named-fact mock.
    action = next(a for a in session.engine.action_catalog.values() if a.source_definition_id.endswith(':' + key))
    assert q.suppressed_activation(session.engine, session.engine.state.actors[FOE], q.profile(action))


@pytest.mark.parametrize('target_cl,subdued,expected', [
    (18, False, [0, 1]), (14, False, [0, 1, 2]), (18, True, [0, 1, 2]),
])
def test_later_failed_edict_save_activates_the_authority_preparation_band(
        tmp_path, monkeypatch, target_cl, subdued, expected):
    session = table(tmp_path, target_cl=target_cl)
    monkeypatch.setattr(q, 'save_failed', lambda *a, **k: False)
    monkeypatch.setattr(q, 'subdued', lambda *a, **k: subdued)
    cast_edict(session)
    session = reload(session, tmp_path)
    assert [c.data['pillar'] for c in q.active_bindings(session.engine, session.engine.state.actors[FOE])] == [0]
    # Successful initial save's short Outer expires at the source's next turn.
    end(session)
    turn(session, ME)  # the first target save can already activate the band
    session = reload(session, tmp_path)
    if target_cl == 14:
        # Every second target turn for the 3–5 lower band.
        assert not list(q.active_bindings(session.engine, session.engine.state.actors[FOE]))
        end(session)
        turn(session, ME)
        session = reload(session, tmp_path)
    assert [c.data['pillar'] for c in q.active_bindings(session.engine, session.engine.state.actors[FOE])] == expected
    assert all(not c.data['binding_short'] and not c.data['initial_success'] for c in bindings(session))
    assert session.engine._effective_speed(session.engine.state.actors[FOE]) == 0


def test_break_seal_offers_only_active_pillars_and_revalidates_choice(tmp_path, monkeypatch):
    session = table(tmp_path, target_cl=12, target_saves={'CHA': 60})
    monkeypatch.setattr(q, 'save_failed', lambda *a, **k: True)
    cast_edict(session)
    turn(session, FOE)
    outer, meridian, core = bindings(session)
    pick = answer(break_binding=outer.instance_id, break_price=QI)
    act(session, next(c for c in session.engine.legal_candidates()
                      if c.source_definition_id == 'system:qi_seal_break'), pick)
    session = reload(session, tmp_path)
    assert bindings(session)[0].data['break_successes'] == 1
    end(session)
    turn(session, FOE)
    assert outer.instance_id not in {c.instance_id for c in q.breakable_bindings(session.engine, session.engine.state.actors[FOE])}
    # A stale/manipulated choice must not charge a price or accumulate a second success.
    from combat.typed_executor import Context
    actor = session.engine.state.actors[FOE]
    action = session.engine.action_catalog['system:qi_seal_break']
    ctx = Context(session.engine, actor, action, None, action.parameters['typed'], [], None)
    before = dict(actor.resources)
    monkeypatch.setattr(q, 'choose', lambda *a, **k: outer.instance_id)
    with pytest.raises(ValueError, match='active binding'):
        q.release_seal(ctx, {'kind': 'break'})
    assert actor.resources == before
    monkeypatch.undo()
    # End of this turn restores it. On the following turn the second consecutive
    # successful *legal* attempt breaks the link, leaving the physical Pillar.
    end(session)
    turn(session, FOE)
    session = reload(session, tmp_path)
    assert outer.instance_id in {c.instance_id for c in q.breakable_bindings(session.engine, session.engine.state.actors[FOE])}
    act(session, next(c for c in session.engine.legal_candidates()
                      if c.source_definition_id == 'system:qi_seal_break'), pick)
    session = reload(session, tmp_path)
    assert bindings(session)[0].data['broken_binding'] == 1
    assert outer.instance_id not in {c.instance_id for c in q.breakable_bindings(session.engine, session.engine.state.actors[FOE])}
    assert len(list(q.passage_triangles(session.engine))) == 1


def test_initially_dormant_pillars_never_offer_break_the_seal(tmp_path, monkeypatch):
    session = table(tmp_path, target_cl=12)
    monkeypatch.setattr(q, 'save_failed', lambda *a, **k: False)
    cast_edict(session)
    assert [c.data['pillar'] for c in q.breakable_bindings(session.engine, session.engine.state.actors[FOE])] == [0]
    end(session)
    turn(session, ME)
    end(session)
    turn(session, FOE)
    session = reload(session, tmp_path)
    assert not q.breakable_bindings(session.engine, session.engine.state.actors[FOE])
    assert 'system:qi_seal_break' not in {c.source_definition_id for c in session.engine.legal_candidates()}


def test_meridian_spending_is_cumulative_within_each_actual_turn_and_survives_reload(tmp_path):
    session = table(tmp_path)
    # Source-owned Chains supply the printed preparation prerequisite.
    act(session, native(session, q.SOURCE))
    end(session)
    turn(session, ME)
    act(session, native(session, q.MARK, '.meridian'), answer(scope='expenditure_limit', consent='resist'))
    turn(session, FOE)
    use(session, 'spend-two')
    session = reload(session, tmp_path)
    use(session, 'spend-two')
    session = reload(session, tmp_path)
    assert not any(c.source_definition_id.endswith(':spend-two') for c in session.engine.legal_candidates())
    first = bindings(session, q.MARK)[0].data.copy()
    assert first['spent_cp'] == 4
    target_turn_count = session.engine.state.actors[FOE].turns_started
    end(session)
    turn(session, ME)
    # Same sealed creature spends off-turn: its own turns_started has NOT changed.
    assert session.engine.state.actors[FOE].turns_started == target_turn_count
    use(session, 'off-turn-spend', target=FOE)
    session = reload(session, tmp_path)
    second = bindings(session, q.MARK)[0].data
    assert second['spent_cp'] == 1 and second['spend_turn'] != first['spend_turn']
    use(session, 'off-turn-spend', target=FOE)
    session = reload(session, tmp_path)
    assert bindings(session, q.MARK)[0].data['spent_cp'] == 2


@pytest.mark.parametrize('cl,dc,allowed,checks', [(10, 50, False, 0), (18, 50, False, 1), (20, 1, True, 1)])
@pytest.mark.parametrize('mode', ['teleport', 'summon', 'project', 'phase'])
def test_third_party_sealed_passage_authority_and_reload(tmp_path, monkeypatch, cl, dc, allowed, checks, mode):
    session = table(tmp_path, third_cl=cl)
    cast_edict(session)
    session = reload(session, tmp_path)
    assert len(list(q.passage_triangles(session.engine))) == 1
    engine = session.engine
    actor = engine.state.actors[THIRD]
    # DC is an explicit persisted source authority, changed only in this synthetic
    # fixture to force both deterministic check outcomes without patching rolls.
    for c in bindings(session):
        c.data['save_dc'] = dc
    action = next(a for a in engine.action_catalog.values()
                  if a.source_definition_id.endswith(':teleport'))
    before = len([e for e in engine.events if e.event_type == 'CHECK_ROLLED'])
    start, inside, outside = actor.position, Position(x=6, y=5), Position(x=10, y=6)
    from combat.typed_executor import Context
    ctx = Context(engine, actor, action, None, action.parameters['typed'], [], None)
    if mode == 'teleport':
        result = ext.run_strict('subject_teleport_attempt', ctx, actor, start, inside)
        clear = ext.run_strict('subject_teleport_attempt', ctx, actor, start, outside)
    elif mode == 'summon':
        creature = next(summons.owned_by(engine, actor.entity_id, 'painted_beast'))
        result = ext.run_strict('summon_check', engine, actor, creature, inside, False, action.source_definition_id)
        clear = ext.run_strict('summon_check', engine, actor, creature, outside, False, action.source_definition_id)
    elif mode == 'phase':
        engine._apply_condition(actor, 'condition:typed.incorporeal', action.source_definition_id,
                                actor.entity_id, expires_on='END_OF_CURRENT_TURN')
        result = [q.passage_phase(engine, actor, start, inside, None)]
        result = [r for r in result if r is not None]
        clear = [q.passage_phase(engine, actor, start, outside, None)]
        assert bool(result) == (not allowed)
        assert clear == [None]
        result = [False] if result else []
    else:
        action = next(a for a in engine.action_catalog.values() if a.source_definition_id.endswith(':project'))
        ctx = Context(engine, actor, action, None, action.parameters['typed'],
                      [engine.state.actors[FOE]], engine.state.actors[FOE])
        q.passage_recipients(ctx)
        result = [] if ctx.targets else [False]
        ctx.targets = [engine.state.actors[ME]]
        # Both ends outside, not crossing the triangle: a separate geometric assertion below.
        clear = []
    assert (False not in result) is allowed
    assert False not in clear
    after = len([e for e in engine.events if e.event_type == 'CHECK_ROLLED'])
    assert after - before == checks
    assert not q.through_triangle(Position(x=9, y=8), Position(x=10, y=8),
                                  [Position(x=x, y=y) for x, y in POINTS])
    assert q.through_triangle(Position(x=1, y=5), Position(x=9, y=5),
                              [Position(x=x, y=y) for x, y in POINTS])


@pytest.mark.parametrize('destination,allowed', [((6, 5), False), ((10, 6), True)])
def test_lower_cl_third_party_real_teleport_commit_reload(tmp_path, destination, allowed):
    session = table(tmp_path)
    cast_edict(session)
    turn(session, THIRD)
    original = session.engine.state.actors[THIRD].position
    use(session, 'teleport', destination=destination)
    session = reload(session, tmp_path)
    expected = Position(x=destination[0], y=destination[1]) if allowed else original
    assert session.engine.state.actors[THIRD].position == expected

@pytest.mark.parametrize('mode', ['teleport', 'summon-place', 'project'])
@pytest.mark.parametrize('cl,dc,allowed', [(10, 50, False), (18, 50, False), (20, 1, True)])
def test_third_party_actual_delivery_obeys_passage_after_commit_reload(tmp_path, mode, cl, dc, allowed):
    session = table(tmp_path, third_cl=cl, source_dc=dc)
    cast_edict(session)
    session = reload(session, tmp_path)
    turn(session, THIRD)
    first = len(session.engine.events)
    if mode == 'project':
        hp = session.engine.state.actors[FOE].current_hp
        use(session, mode, target=FOE)
    else:
        use(session, mode, destination=(6, 5))
    session = reload(session, tmp_path)
    events = session.engine.events[first:]
    if mode == 'teleport':
        assert (session.engine.state.actors[THIRD].position == Position(x=6, y=5)) is allowed
    elif mode == 'summon-place':
        creature = next(summons.owned_by(session.engine, THIRD, 'painted_beast'))
        assert creature.active is allowed
        if allowed:
            assert creature.position == Position(x=6, y=5)
    else:
        assert (session.engine.state.actors[FOE].current_hp < hp) is allowed
    assert sum(e.event_type == 'CHECK_ROLLED' for e in events) == int(cl >= 18)

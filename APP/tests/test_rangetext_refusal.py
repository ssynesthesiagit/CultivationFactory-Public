"""A refusal caused only by distance says how far the nearest perceived creature is."""
from combat.gate2_runtime_models import Position
from tests.h1_support import FOE
from tests.test_lock18_action_reasons import fixture, ask


def test_altitude_counts_toward_reach_and_the_text_names_the_distance():
    engine, actor = fixture(target='HOSTILE_ENTITY')
    foe = engine.state.actors[FOE]
    actor.position = Position(x=3, y=6, z=15)  # 75 ft up
    foe.position = Position(x=30, y=6, z=0)
    assert ask(engine) == {'available': False, 'code': 'TARGET_RANGE',
        'reason': 'Out of range: the nearest target you know of is 135 ft away (range 5 ft), counting your 75 ft height.'}
    foe.position = Position(x=4, y=6, z=15)
    assert ask(engine)['available']


def test_cultivate_blossom_cell_range_explains_altitude_and_is_available_lower():
    from combat.ext import blossom
    engine, actor = fixture()
    action = next(row for row in blossom.blossom_actions({'short': 'test', 'actor_id': actor.entity_id,
        'numbers': {}, 'owned_ids': [], 'spheres': [blossom.SPHERE], 'primary': 'qi'})
        if row.display_name == 'Cultivate Blossom')
    action = action.model_copy(update={'source_definition_id': 'test:availability'})
    engine.action_catalog['test:availability'] = action
    actor.position = Position(x=3, y=6, z=15)  # 75 ft up
    engine.state.actors[FOE].position = Position(x=8, y=6, z=0)  # 25 ft away horizontally

    result = ask(engine)
    assert not result['available'] and result['code'] == 'TARGET_RANGE'
    assert result['reason'].startswith('Out of range: the nearest square you can see is ')
    assert result['reason'] == (
        'Out of range: the nearest square you can see is 75 ft away '
        '(range 60 ft), counting your 75 ft height.')

    actor.position = Position(x=3, y=6, z=0)
    assert ask(engine)['available']


def test_range_explanation_does_not_describe_a_remembered_but_unseen_creature(monkeypatch):
    from types import SimpleNamespace
    from combat import action_legality, target_knowledge
    engine, actor = fixture(target='HOSTILE_ENTITY')
    action = engine.action_catalog['test:availability']
    foe = engine.state.actors[FOE]
    foe.position = Position(x=30, y=6, z=0)
    engine.grid.opaque.add((15, 6))
    assert not engine._line_of_sight_actor_to_actor(actor, foe)
    monkeypatch.setattr(target_knowledge, 'knowledge', lambda *args: SimpleNamespace(mode='LAST_OBSERVED'))
    assert action_legality.range_reason(engine, actor, action) is None


def test_directly_located_unseen_target_is_not_described_as_visible(monkeypatch):
    from types import SimpleNamespace
    from combat import action_legality, target_knowledge
    engine, actor = fixture(target='HOSTILE_ENTITY')
    action = engine.action_catalog['test:availability']
    engine.state.actors[FOE].position = Position(x=30, y=6, z=0)
    # DIRECT also covers a precise sensed location (for example, a pinpointing sense).
    monkeypatch.setattr(target_knowledge, 'knowledge', lambda *args: SimpleNamespace(mode='DIRECT'))
    assert action_legality.range_reason(engine, actor, action) == (
        'Out of range: the nearest target you know of is 135 ft away (range 5 ft).')


def test_table_state_explains_blossom_and_weapon_range_with_altitude(tmp_path, monkeypatch):
    from combat.factory_compiler import compile_character
    from combat.gate2_runtime_models import ConditionInstance
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT, bundle, sheet, ME

    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    player_sheet = sheet(['TAL_FLOWERS_CULTIVATE_BLOSSOM'], cl=15)
    player_sheet['ability_scores_and_statistics']['initiative'] = {'bonus': 100}
    player = compile_character(player_sheet, actor_id=ME)
    foe = bundle([], actor_id=FOE)
    arena = combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    mid = combat._finish_factory_match(
        [player, foe], [ME, FOE], {ME: 'team:factory', FOE: 'team:opponents'},
        {ME: {'x': 3, 'y': 6, 'z': 15}, FOE: {'x': 8, 'y': 6}}, arena,
        [ME], [FOE], control_modes={ME: 'MANUAL', FOE: 'MANUAL'},
        match_seed='RANGETEXTF2-TABLE', display_name='Range text table regression', maximum_rounds=4,
    )['match_id']

    # Factory setup accepts ground placements only. Prepare the live engine altitude
    # in the loaded session so the real TabletopService state path reports it.
    session = combat._load_session(mid)
    actor = session.engine.state.actors[ME]
    actor.position = Position(x=3, y=6, z=15)
    actor.conditions['test:improvised'] = ConditionInstance(
        instance_id='test:improvised', condition_id='condition:typed.improvised',
        source_definition_id='test:improvised', source_actor_id=ME, target_id=ME,
        applied_sequence=len(session.engine.events),
    )
    monkeypatch.setattr(combat, '_load_session', lambda _match_id: session)
    state = table.state(mid)
    for _ in range(4):
        if state['menu']['actor_id'] == ME:
            break
        result = table.act(mid, state['menu']['end_turn'], state['menu']['decision_id'],
                           state['menu']['state_version'], state['last_sequence'])
        state = result['state']
    assert state['menu']['actor_id'] == ME and state['menu']['manual']
    assert next(row for row in state['presentation']['actors'] if row['entity_id'] == ME)['altitude_ft'] == 75
    reasons = state['unavailable_reasons']
    blossom = next((reason for key, reason in reasons.items() if 'blossom' in key.lower()), None)
    weapon_rows = [(source, action.display_name, reasons[f'act:{source}'])
                   for source, action in session.engine.action_catalog.items()
                   if 'weapon attack' in action.display_name.lower() and f'act:{source}' in reasons]
    weapon = next((reason for _source, _name, reason in weapon_rows
                   if 'nearest' in reason or 'Out of range' in reason), None)
    assert weapon is not None, weapon_rows
    assert blossom is not None and weapon is not None, reasons
    for reason, limit in ((blossom, 60), (weapon, None)):
        assert 'nearest' in reason and '75 ft away' in reason and '75 ft height' in reason, reasons
        if limit is not None:
            assert f'range {limit} ft' in reason
    assert weapon.startswith('No target within reach (5 ft);')

    actor.position = Position(x=3, y=6, z=0)
    session.engine.state.actors[FOE].position = Position(x=4, y=6, z=0)
    refreshed = table.state(mid)
    assert not any('blossom.cultivate' in key for key in refreshed['unavailable_reasons'])
    assert not any('improvised.attack' in key for key in refreshed['unavailable_reasons'])

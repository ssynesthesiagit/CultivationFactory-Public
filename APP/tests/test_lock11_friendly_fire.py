"""Actual area candidates, AI placement and transactional recipient decisions."""
import copy
import pytest
from combat import ext, factory_compiler
from combat.area_safety import preview
from combat.gate2_runtime_models import Position
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_policy import PolicyLibrary
from combat.gate5_service import CombatService, CombatServiceError
from combat.tabletop_service import TabletopService
from combat.tabletop import ButtonStore
from tests import test_tabletop_hunt6 as H
from tests.test_lock_choices import install
from tests.test_friendly_fire_area_table import _commit_area_action


def context(engine, rows):
    policy = PolicyLibrary(H.ROOT).fallback().model_copy(update={'action_priorities': {}})
    return build_decision_context(engine, policy).model_copy(update={'legal_candidates': tuple(rows)})


def test_safe_placement_wins_even_when_more_hostiles_can_outweigh_risk(tmp_path):
    combat, table, mid = H.table_fight(tmp_path, ['STARS_TAL_FALLING_STAR'])
    e = combat._load_session(mid).engine
    action = next(a for a in e.action_catalog.values() if a.owner_id == H.LEFT and a.display_name == 'Falling Star')
    # Compact actual map: one enemy has a safe and an unsafe adjacent placement.
    action = action.model_copy(update={'radius_ft': 5, 'parameters': {**action.parameters,
        'typed': {**action.parameters['typed'], 'area': {'shape': 'sphere', 'size_ft': 5}}}})
    e.action_catalog[action.source_definition_id] = action
    candidates = [c for c in e.legal_candidates() if c.source_definition_id == action.source_definition_id]
    risky = next(c for c in candidates if c.destination == Position(x=4, y=5))
    safe = next(c for c in candidates if c.destination == Position(x=5, y=4))
    assert risky.metadata['hostiles_in_area'] == safe.metadata['hostiles_in_area'] == 1
    assert risky.metadata['allies_in_area'] == 1 and safe.metadata.get('allies_in_area', 0) == 0
    assert 'Hits allies too: Ally' in risky.display_name
    chosen = LocalDeterministicController().choose_primary_action(context(e, [risky, safe]))
    assert chosen.intent.candidate_id == safe.candidate_id
    # Two additional real enemy footprints inside the risky placement, outside the safe one.
    foe = e.state.actors[H.RIGHT]
    for index, pos in enumerate([(4, 6), (3, 5)]):
        key = f'actor:test.extra{index}'
        e.state.actors[key] = foe.model_copy(deep=True, update={'entity_id': key, 'position': Position(x=pos[0], y=pos[1])})
    e.state.actors[H.ALLY].position = Position(x=5, y=5)
    candidates = [c for c in e.legal_candidates() if c.source_definition_id == action.source_definition_id]
    risky = next(c for c in candidates if c.destination == Position(x=4, y=5))
    safe = next(c for c in candidates if c.destination == Position(x=4, y=3))
    assert risky.metadata['hostiles_in_area'] == 3 and safe.metadata['hostiles_in_area'] == 1
    assert risky.metadata['allies_in_area'] == 1
    chosen = LocalDeterministicController().choose_primary_action(context(e, [safe, risky]))
    # SOL114: safety is a placement constraint, not a damage-score tradeoff.
    controller = LocalDeterministicController()
    ctx = context(e, [safe, risky])
    assert controller._score_candidate(ctx, risky, ()).total > controller._score_candidate(ctx, safe, ()).total
    assert chosen.intent.candidate_id == safe.candidate_id


@pytest.mark.parametrize('shape', ['sphere', 'cone', 'line', 'cube', 'wall'])
def test_preview_uses_full_footprint_and_recipient_restrictions(tmp_path, shape):
    combat, _, mid = H.table_fight(tmp_path, ['STARS_TAL_FALLING_STAR'])
    e = combat._load_session(mid).engine
    owner, ally = e.state.actors[H.LEFT], e.state.actors[H.ALLY]
    owner.position = Position(x=1, y=4)
    ally.position = Position(x=5, y=3)
    e.actor_footprints[H.ALLY] = e._footprint(ally).model_copy(update={'width_cells': 2, 'height_cells': 2,
        'occupied_relative_cells': (Position(x=0,y=0), Position(x=1,y=0), Position(x=0,y=1), Position(x=1,y=1))})
    action = next(a for a in e.action_catalog.values() if a.owner_id == H.LEFT and a.display_name == 'Falling Star')
    # This geometry fixture deliberately includes its user; ordinary harmful
    # areas now exclude them unless the printed scope says otherwise (SOL140).
    area = {'shape': shape, 'size_ft': 20 if shape in {'cone', 'line', 'wall'} else 5, 'width_ft': 5, 'thick_ft': 5,
            'include_self': True}
    action = action.model_copy(update={'parameters': {**action.parameters,
        'typed': {**action.parameters['typed'], 'area': area}}})
    _, metadata, label = preview(e, owner, action, Position(x=5, y=4))
    assert 'Ally' in label and metadata['allies_in_area'] == (2 if shape in {'cone', 'line'} else 1)
    assert metadata['ally_expected_damage'] > 0
    action.parameters['typed']['area'] = {**area, 'recipients': 'hostile', 'include_self': False}
    assert preview(e, owner, action, Position(x=5, y=4))[1:] == ({}, '')
    action.parameters['typed']['area'] = None
    assert preview(e, owner, action, Position(x=5, y=4)) is None


def test_table_placement_warning_survives_reload_and_committed_friendly_fire(tmp_path):
    combat, table, mid = H.table_fight(tmp_path, ['STARS_TAL_FALLING_STAR'])
    state = table.state(mid)
    group = next(g for g in state['menu']['actions'] if g['label'] == 'Falling Star')
    risky = next(o for o in group['options'] if o.get('destination') == {'x': 4, 'y': 2})
    assert 'Hits allies too:' in risky['label'] and 'Ally' in risky['label']
    table = TabletopService(CombatService(H.ROOT, tmp_path), tmp_path)
    again = next(g for g in table.state(mid)['menu']['actions'] if g['label'] == 'Falling Star')
    assert next(o for o in again['options'] if o['candidate_id'] == risky['candidate_id'])['label'] == risky['label']
    result, _ = _commit_area_action(table, mid, 'Falling Star', {'x': 4, 'y': 2})
    assert result['status'] == 'COMMITTED'
    session = CombatService(H.ROOT, tmp_path)._load_session(mid)
    assert any(ev.event_type == 'SAVE_ROLLED' and ev.actor_id == H.ALLY for ev in session.engine.events)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('use', [False, True])
def test_selected_ally_gets_paid_target_reaction_excluded_enemy_does_not(monkeypatch, tmp_path, use):
    source = 'test:brace'
    original = factory_compiler.compile_character
    def compile_with_reaction(*args, **kwargs):
        bundle = original(*args, **kwargs)
        if kwargs['actor_id'] in (H.ALLY, H.RIGHT):
            bundle['typed_reactions'].append({'feature_id': source, 'name': 'Brace for the technique',
                'block': 'generic', 'kind': 'technique_targets', 'range_ft': 60, 'ask': True,
                'costs': [['resource:core.qi', 1]], 'effects': []})
        return bundle
    monkeypatch.setattr(factory_compiler, 'compile_character', compile_with_reaction)
    for name in ('ally', 'right'):
        ButtonStore(tmp_path/'tabletop_buttons').save_reactions(H.PROJECTS[name], {'mode': 'ask'}, {source})
    combat, table, mid = H.table_fight(tmp_path, ['RADIANCE_TAL_BLINDING_FLASH'])
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    result, option = _commit_area_action(table, mid, '10-Foot Emanation', None)
    assert result['status'] == 'REACTION_REQUIRED' and 'choose which creatures' in result['reaction']['moment']
    first = {**result['reaction']['context'], 'selection': 'USE', 'option_ids': [H.ALLY]}
    state = table.state(mid)
    result = table.act(mid, option['candidate_id'], state['menu']['decision_id'], state['menu']['state_version'], state['last_sequence'], [first])
    assert result['status'] == 'REACTION_REQUIRED' and result['reaction']['context']['reactor_id'] == H.ALLY
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    second = {**result['reaction']['context'], 'selection': 'USE' if use else 'DECLINE'}
    table = TabletopService(CombatService(H.ROOT, tmp_path), tmp_path)
    state = table.state(mid)
    result = table.act(mid, option['candidate_id'], state['menu']['decision_id'], state['menu']['state_version'], state['last_sequence'], [first, second])
    assert result['status'] == 'COMMITTED', result
    session = CombatService(H.ROOT, tmp_path)._load_session(mid)
    for actor_id in (H.ALLY, H.RIGHT):
        actor = session.engine.state.actors[actor_id]
        assert actor.resources['resource:core.qi'] == before['actors'][actor_id]['resources']['resource:core.qi'] - int(use and actor_id == H.ALLY)
    assert [ev.actor_id for ev in session.engine.events if ev.event_type == 'SAVE_ROLLED' and 'BLINDING_FLASH' in (ev.source_definition_id or '')] == [H.ALLY]
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


def test_optional_recipients_preview_allies_but_auto_policy_spares_them(tmp_path):
    combat, _, mid = H.table_fight(tmp_path, ['TAL_DAEMONIC_CULTIVATION_WORLD_DEVOURING_MAW'])
    e = combat._load_session(mid).engine
    candidate = next(c for c in e.legal_candidates() if 'WORLD_DEVOURING_MAW' in c.source_definition_id
                     and c.destination == Position(x=4, y=2))
    assert 'Allies you can choose:' in candidate.display_name
    assert candidate.metadata['allies_in_area'] > 0
    assert candidate.metadata['unavoidable_allies_in_area'] == candidate.metadata['ally_expected_damage'] == 0
    choice = LocalDeterministicController().choose_primary_action(context(e, [candidate]))
    assert not any(row.component == 'friendly_fire' for row in choice.record.scored_alternatives[0].components)


@pytest.mark.parametrize('invalid', ['duplicate', 'foreign', 'return', 'error'])
def test_bad_recipient_provider_rolls_back_paid_action(monkeypatch, tmp_path, invalid):
    combat, table, mid = H.table_fight(tmp_path, ['STARS_TAL_FALLING_STAR'])
    def broken(ctx):
        ctx.engine._spend_resource(ctx.actor, 'resource:core.qi', 1, 'test:recipient-cost')
        if invalid == 'duplicate':
            ctx.targets = ctx.targets * 2
        elif invalid == 'foreign':
            ctx.targets = [copy.deepcopy(ctx.targets[0])]
        elif invalid == 'return':
            return False
        else:
            raise RuntimeError('test recipient error')
    install(monkeypatch, 'before_target_reactions', broken)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    with pytest.raises(CombatServiceError) as raised:
        _commit_area_action(table, mid, 'Falling Star', {'x': 4, 'y': 2})
    assert isinstance(raised.value.__cause__, ext.CheckpointError)
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before

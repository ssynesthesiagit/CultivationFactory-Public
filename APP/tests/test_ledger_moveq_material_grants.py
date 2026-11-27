"""Hook's Swim stop holds even when Unwilling Boost pays for the route."""
import pytest

from combat.diagnostics import CombatGate1Error
from combat.ext.athletics_momentum import routes
from combat.gate2_runtime_models import ActionIntent, Position
from combat.movement_speeds import speed
from tests.test_a2_axes import (
    BOOST, FOE, HEW, KNEE, STRIKE, assert_grant_choice, assert_grant_move,
    earn_momentum, setup, use,
)
from tests.test_lock_choices import install
from tests.worker2_support import reload, turn


@pytest.mark.parametrize('native_swim', [10, 0], ids=['keyed-stop', 'walk-funded-terrain'])
def test_momentum_grant_respects_live_swim_speed(tmp_path, monkeypatch, native_swim):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    install(monkeypatch, 'd20_result', lambda *args: {
        'source_id': 'test:knee-hit', 'operation': 'replace', 'natural_result': 20})
    # The target is Large: cover its whole destination footprint, with the
    # near row passable so the creature can grow before entering the soil.
    surface = {'region_id': 'soil-surface', 'terrain_type': 'OPEN', 'material': 'soil',
               'material_only': True, 'movement_cost': 0, 'cells': [{'x': x, 'y': 7} for x in (4, 5)]}
    earth = {'region_id': 'earth', 'terrain_type': 'BLOCKED', 'material': 'soil',
             'movement_cost': 0, 'cells': [{'x': x, 'y': 8} for x in (4, 5)]}
    combat, table, mid = setup(tmp_path, [HEW, KNEE], dc=-100, foe_swim=native_swim,
        foe_talents=(BOOST, 'TAL_ATHLETICS_TERRAIN_GLIDE'), terrain_regions=[surface, earth])
    destination = Position(x=4, y=7, z=0)
    option = 'cell:4,7'

    def swim_route(c):
        return c.metadata.get('movement_mode') == 'swim' and c.destination == destination

    before = reload(tmp_path, mid)
    # Save a route that was admissible before the hit; a reaction could make
    # a selected route stale between listing and step settlement too.
    stale = next(c for c in routes(before, before.state.actors[FOE], 'horizontal', 20) if swim_route(c))
    use(combat, table, mid, STRIKE + " + Hook the Giant's Knee",
        choices={'choice:needle.movement_mode': 'swim' if native_swim else 'walk'})
    turn(table, mid, FOE)
    earn_momentum(combat, table, mid)
    engine = reload(tmp_path, mid)
    target = engine.state.actors[FOE]
    assert speed(engine, target, 'swim') == 0
    assert speed(engine, target, 'walk') == (30 if native_swim else 20)
    listed = routes(engine, target, 'horizontal', 20)
    choice = 'choice:needle.athletics.momentum_destination'
    if native_swim:
        assert listed and all(c.metadata.get('movement_mode') != 'swim' for c in listed)
        prompts = use(combat, table, mid, 'Unwilling Boost: use horizontal momentum', choices={choice: None})
        options = next(p['choice']['options'] for p in prompts if p['context']['reaction_source_id'] == choice)
        assert option not in {o['id'] for o in options}
        after = reload(tmp_path, mid)
        assert after.state.actors[FOE].position == target.position
        assert not any(e.event_type == 'MOVEMENT_COMMITTED' and e.source_definition_id == BOOST for e in after.events)

        intent = ActionIntent(intent_id='test:stale-momentum', decision_id=stale.decision_id,
            candidate_id=stale.candidate_id, state_version=stale.state_version, actor_id=FOE,
            destination=stale.destination)
        with pytest.raises(CombatGate1Error) as refused:
            engine._resolve_movement(target, stale, intent, granted_ft=20, grant_source=BOOST)
        assert refused.value.diagnostic.code == 'GATE2_MOVEMENT_BUDGET_EXCEEDED'
    else:
        assert any(swim_route(c) for c in listed)
        prompts = use(combat, table, mid, 'Unwilling Boost: use horizontal momentum', choices={choice: option})
        assert_grant_choice(prompts, choice, option)
        after = reload(tmp_path, mid)
        assert_grant_move(after, BOOST, 'swim', destination.model_dump(mode='json'))
        receipt = next(e for e in reversed(after.events)
                       if e.event_type == 'MOVEMENT_COMMITTED' and e.source_definition_id == BOOST and e.actor_id == FOE)
        assert Position.model_validate(receipt.payload['destination']) == destination
        assert not any(e.event_type == 'FOOTPRINT_CHANGED' and e.actor_id == FOE and e.sequence > receipt.sequence
                       for e in after.events)

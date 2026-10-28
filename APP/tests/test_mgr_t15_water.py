"""Water manager residuals through committed table actions and cold replay."""
import pytest

from combat.gate2_runtime_models import Position
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_auto38_water import SHIELD, prepare
from tests.test_carry import KIT

INCARNATION = 'TAL_WATER_OCEAN_SOVEREIGN_INCARNATION'


@pytest.mark.parametrize('active', [True, False])
@pytest.mark.parametrize('manual', [True, False], ids=['player', 'ai'])
@pytest.mark.parametrize('wet', [True, False], ids=['basin', 'dry'])
def test_incarnation_shield_distance_is_timed_and_owner_local(tmp_path, active, manual, wet):
    combat, table, mid = fixture(
        tmp_path, [SHIELD, INCARNATION], ask=manual,
        foe_position={'x': 3, 'y': 5},
        foe_kit={'starting_kit': {'items': [KIT['items'][-1]]}},
        bundle_transform=prepare)
    if wet:
        settle(table, mid, candidate(combat, mid, 'Shape Current: Mist Basin', at=(3, 6)).candidate_id)
    if active:
        settle(table, mid, candidate(combat, mid, 'Ocean-Sovereign Incarnation').candidate_id)
    turn(table, mid, FOE)
    if not manual:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    engine = reload(tmp_path, mid)
    distance = 30 if active else 10
    owner = engine.state.actors[OWNER]
    from combat.ext.water_defenses import water_contact
    assert water_contact(engine, owner, owner) is wet
    assert not any(c.condition_id.startswith('condition:typed.mark.soaked.') for c in owner.conditions.values())
    destination = Position(x=3, y=12 if active else 8)
    farthest = f'step:{destination.x},{destination.y}'
    assert engine.grid.distance_ft(owner.position, destination) == distance
    prompts = settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=OWNER).candidate_id,
                     {'choice:needle.water_shield': 'use', 'choice:needle.water_shield_step': farthest})
    engine = reload(tmp_path, mid)
    movement = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.source_definition_id == SHIELD]
    assert bool(movement) is (active or wet)
    if manual and (active or wet):
        prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.water_shield_step')
        assert f'{distance} feet' in str(prompt)
        assert engine.state.actors[OWNER].position == destination
        points = [Position(x=int(parts[0]), y=int(parts[1]), z=int(parts[2]) if len(parts) > 2 else 0)
                  for option in prompt['choice']['options']
                  for parts in [option['id'].removeprefix('step:').split(',')]]
        assert max(engine.grid.distance_ft(owner.position, p) for p in points) == distance
    elif not manual:
        assert not prompts
    if manual:
        shield_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.water_shield')
        assert ('even if it is not Soaked' in str(shield_prompt)) is active
    if not active and not wet:
        assert engine.state.actors[OWNER].position == owner.position
        assert not any(p['context']['reaction_source_id'] == 'choice:needle.water_shield_step' for p in prompts)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 99 - (5 if active else 0) - (1 if wet else 0)
    assert not any(e.event_type == 'OPPORTUNITY_ATTACK' for e in engine.events)


def test_incarnation_ends_before_later_shield(tmp_path):
    combat, table, mid = fixture(tmp_path, [SHIELD, INCARNATION],
                               foe_position={'x': 3, 'y': 5},
                               foe_kit={'starting_kit': {'items': [KIT['items'][-1]]}},
                               bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Ocean-Sovereign Incarnation').candidate_id)
    # Let the actual one-minute state expire through native turn boundaries.
    for _ in range(10):
        turn(table, mid, FOE)
        turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == 'condition:typed.state.ocean_sovereign_incarnation'
                   for c in engine.state.actors[OWNER].conditions.values())
    settle(table, mid, candidate(combat, mid, 'Shape Current: Mist Basin', at=(3, 6)).candidate_id)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=OWNER).candidate_id,
                     {'choice:needle.water_shield': 'use', 'choice:needle.water_shield_step': 'step:3,7'})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.water_shield_step')
    assert '10 feet' in str(prompt)
    assert 'step:3,0' not in {o['id'] for o in prompt['choice']['options']}
    reload(tmp_path, mid)

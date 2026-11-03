"""Sure Grip needs physical support even when Air Stunt supplies a virtual wall."""
import pytest

from combat import ext, roof_movement
from combat.ext import athletics, athletics_grip_lungs as grip
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield
from tests.auto8f1_table_support import fixture, OWNER, FOE, SECOND, ARENA, candidate_id, reload_identical
from tests.test_a2_athletics_second_pass import add_action
from tests.test_walkable_roofs import route


@ext.effect('test_t16_sf1_virtual_catch')
def record_invalid_virtual_catch(ctx, eff):
    """Inject a stale recorded anchor through the real condition/event path."""
    actor = ctx.actor
    ctx.engine._apply_condition(actor, grip.CAUGHT, grip.GRIP, actor.entity_id,
        expires_on=None, data={'anchor_id': actor.entity_id, 'surface_id': 'virtual-wall',
                              'x': actor.position.x, 'y': actor.position.y, 'z': actor.position.z})


def air_fight(tmp_path, monkeypatch, dc):
    document = normalize_map({'display_name': 'Open air without physical handholds',
        'width_squares': 18, 'height_squares': 12, 'walls': [], 'roofs': {'enabled': False},
        **({'catch_dc': dc} if dc is not None else {})})
    arena = to_battlefield(document)
    original = CombatService.factory_arenas

    def arenas(self, **kwargs):
        return {**original(self, **kwargs), ARENA: arena}

    monkeypatch.setattr(CombatService, 'factory_arenas', arenas)

    def prepare(bundles):
        owner = next(b for b in bundles if b['actor_id'] == OWNER)
        owner.setdefault('skills', {})['Athletics'] = 100
        add_action(owner, 'Record stale virtual catch', [{'type': 'test_t16_sf1_virtual_catch'}])

    return fixture(tmp_path, [grip.GRIP, 'TAL_ATHLETICS_WALL_STUNT', 'TAL_ATHLETICS_AIR_STUNT'],
        seed='T16-SF1-'+tmp_path.name, bundle_transform=prepare,
        places={OWNER: {'x': 3, 'y': 3}, FOE: {'x': 12, 'y': 3}, SECOND: {'x': 12, 'y': 8}})


@pytest.mark.parametrize('dc', [None, 0], ids=['no-scene-dc', 'scene-dc'])
@pytest.mark.parametrize('stale_catch', [False, True], ids=['new-fall', 'stale-virtual-catch'])
def test_sure_grip_air_stunt_ends_turn_and_falls_without_physical_anchor(tmp_path, monkeypatch, dc, stale_catch):
    g = air_fight(tmp_path, monkeypatch, dc)
    route(g['combat'], g['table'], g['match_id'], [(3, 3, 0), (3, 3, 1), (3, 3, 2)], mode='climb')
    reload_identical(g['combat'], g['match_id'], g['userdata'])
    engine = g['stored_engine']()
    actor = engine.state.actors[OWNER]
    assert actor.position.z == 2 and actor.climbing and actor.reaction_available
    assert [face.id for face in roof_movement.faces(engine, actor, actor.position)] == ['virtual-wall']
    assert not roof_movement.faces(engine, actor, actor.position, include_virtual=False)
    assert engine.grid.catch_dc == dc
    assert any(c.condition_id == athletics.AIR_SUPPORT for c in actor.conditions.values())

    if stale_catch:
        g['commit'](candidate_id(g['menu'](), 'Record stale virtual catch'))
        reload_identical(g['combat'], g['match_id'], g['userdata'])
        # The retained-support query and CONDITION_APPLIED cleanup must reject
        # a virtual anchor even before provisional Air Stunt support expires.
        assert not any(c.condition_id == grip.CAUGHT for c in g['reload_owner']().conditions.values())

    prompts = []
    result = g['commit'](g['menu']()['end_turn'], lambda p, c: prompts.append(c) or [c['options'][0]['id']])
    assert result['status'] == 'COMMITTED'
    reload_identical(g['combat'], g['match_id'], g['userdata'])
    engine = g['stored_engine']()
    actor = engine.state.actors[OWNER]
    assert engine.state.current_actor_id != OWNER
    assert actor.position.z == 0 and not actor.climbing and actor.reaction_available
    assert not any(c.condition_id in {grip.CAUGHT, athletics.AIR_SUPPORT} for c in actor.conditions.values())
    assert not prompts
    assert not any(e.event_type == 'CHECK_ROLLED' and e.source_definition_id == grip.GRIP for e in engine.events)

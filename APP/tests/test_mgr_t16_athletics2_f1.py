"""Second Athletics review: exempt wall costs and upper-volume boarding."""
import pytest

from combat import creature_attachment, flight, motion
from combat.ext import effect
from combat.gate2_runtime_models import CandidateKind, Position
from combat.tabletop import normalize_map, to_battlefield
from tests.auto8f1_table_support import candidate_id
from tests.test_a2_athletics_second_pass import add_action
from tests.test_mgr_t16_athletics2_scale import SCALE
from tests.test_mgr_t16_athletics2_wall import WALL, action, game as wall_game, move
from tests.worker2_support import fixture, OWNER, ALLY, FOE, settle, reload


def test_difficult_ground_exemption_keeps_independent_movement_surcharges():
    from tests.test_roof_movement import engine_at_wall, condition
    engine, actor = engine_at_wall()
    condition(actor, 'condition:test.difficult_ground_climbing', data={'climb_as_difficult_ground': True})
    condition(actor, 'condition:typed.ignore_difficult')
    condition(actor, 'condition:typed.sky_net_slow_down')
    # Sky-Net charges its own extra five feet; Lotus Step cannot remove that.
    assert flight.step_cost(engine, actor, actor.position,
                            actor.position.model_copy(update={'z': 1}), 'climb') == 10


def test_wall_stunt_lotus_step_keeps_long_routes_and_prices_committed_steps(tmp_path):
    combat, table, mid = wall_game(tmp_path, talents=(WALL, 'TAL_FLOWERS_LOTUS_STEP'))
    action(table, mid, 'Lotus Step')
    action(table, mid, 'run up or along a wall')
    engine = combat._load_session(mid).engine
    assert motion.ignores_difficult(engine, engine.state.actors[OWNER])
    routes = [c for c in engine.legal_candidates() if c.kind == CandidateKind.MOVE
              and c.metadata.get('movement_mode') == 'climb']
    assert any(c.destination == Position(x=3, y=6, z=1) and c.movement_cost_ft == 20 for c in routes)
    # Both the candidate quote and real per-step payment must honor the exemption.
    assert move(table, mid, (3, 3, 1)).movement_cost_ft == 5
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].movement_remaining_ft == 25
    assert motion.ignores_difficult(engine, engine.state.actors[OWNER])
    assert move(table, mid, (3, 4, 1)).movement_cost_ft == 5
    fresh = reload(tmp_path, mid)
    assert fresh.state.actors[OWNER].position == Position(x=3, y=4, z=1)
    assert fresh.state.actors[OWNER].movement_remaining_ft == 20


@effect('mgr_t16_f1_grow_host')
def grow_host(ctx, eff):
    from combat.dynamic_size import apply_growth, sync
    from combat.ext.needle import step_to
    apply_growth(ctx.engine, ctx.engine.state.actors[FOE], 'Huge', ctx.source,
                 source_actor_id=ctx.actor.entity_id, expires_on='UNTIL_REMOVED')
    sync(ctx.engine, ctx.source)
    # Event the raised setup explicitly, after the carrier's footprint is sealed.
    from combat.falling import supported
    assert supported(ctx.engine, ctx.actor, Position(x=3, y=3, z=1))
    step_to(ctx.engine, ctx.actor, Position(x=3, y=3, z=1), ctx.source)


@pytest.mark.parametrize('automatic', [False, True])
def test_scale_foe_upper_entry_commits_pays_and_cold_reloads(tmp_path, automatic):
    # A finite five-foot column supports the climber beside a real Huge volume.
    arena = to_battlefield(normalize_map({'display_name': 'Upper creature boarding',
        'width_squares': 10, 'height_squares': 8, 'roofs': {'enabled': False},
        'walls': [{'id': 'platform', 'shape': 'line', 'points': [[3, 3], [3, 3]],
                   'height_ft': 5, 'blocks': 'sight_and_movement'}]}))
    def prepare(bundles):
        for b in bundles:
            b['skills'] = {'Athletics': 100, 'Acrobatics': 100} if b['actor_id'] == OWNER else {'Acrobatics': -100}
            if b['actor_id'] == OWNER:
                add_action(b, 'Grow boarding host', [{'type': 'mgr_t16_f1_grow_host'}])
    combat, table, mid = fixture(tmp_path, [SCALE], named=True, battlefield=arena,
        positions={OWNER: {'x': 3, 'y': 3, 'z': 1}, FOE: {'x': 4, 'y': 3}, ALLY: {'x': 8, 'y': 6}},
        bundle_transform=prepare, seed='MGR-T16-F1-UPPER')
    action(table, mid, 'Grow boarding host')
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].position.z == 1
    assert before._footprint(before.state.actors[FOE]).height_cells == 3
    cid = candidate_id(table.state(mid)['menu'], 'climb onto a bigger creature')
    if automatic:
        from combat.gate4_adapters import ManualControllerAdapter
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
        original = combat.controller
        combat.controller = ManualControllerAdapter(lambda context: (cid, ()),
            reaction_chooser=lambda context: original.choose_reaction(context).decision)
        prompts = settle(table, mid, cid, auto=True)
        assert not prompts
    else:
        prompts = settle(table, mid, cid, picks={'choice:needle.scale_position': 'cell:4,3,2'})
        squares = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.scale_position')
        ids = {o['id'] for o in squares['choice']['options']}
        assert {'cell:4,3,1', 'cell:4,3,2'} <= ids
    engine = reload(tmp_path, mid)
    actor, host = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert creature_attachment.carrier(engine, actor) is host
    assert actor.position.z == (1 if automatic else 2)
    assert creature_attachment.contained(engine, actor, host)
    assert actor.movement_remaining_ft == before.state.actors[OWNER].movement_remaining_ft - 5
    assert not actor.bonus_action_available
    assert creature_attachment.receipt(actor).data['offset_z'] == actor.position.z
    # Completing the action grants no lasting vertical walking capability.
    above = actor.position.model_copy(update={'z': actor.position.z - 1})
    assert not flight.step_allowed(engine, actor, actor.position, above, mode='walk')

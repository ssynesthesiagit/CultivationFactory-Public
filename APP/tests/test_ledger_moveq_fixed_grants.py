"""Fixed five-foot steps do not borrow the mover's ordinary Fly allowance."""
import pytest

from combat import ext
from combat.ext.charge_marks import storm_heart_step
from combat.ext.compass_breaking_hand import FOOTWORK, step
from combat.ext.daemonic_riders import CLAW, claw_step
from combat.gate2_runtime_models import Position
from combat.movement_speeds import speed
from tests.cw2_service_support import add_action
from tests.test_a2_axes import FOE, HEW, KNEE, OWNER, STRIKE, setup, use
from tests.test_lock_choices import install
from tests.worker2_support import reload, turn


@pytest.mark.parametrize(('benefit', 'source', 'choice'), [
    ('compass', FOOTWORK, 'choice:needle.compass.step'),
    ('black-claw', CLAW, 'choice:needle.black_claw_step'),
    ('storm-heart', 'TAL_LIGHTNING_STORM_HEART_ENGINE', 'choice:needle.storm_heart_step'),
])
def test_fixed_step_uses_its_grant_on_zero_walk_flyer(tmp_path, monkeypatch, benefit, source, choice):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    install(monkeypatch, 'd20_result', lambda *args: {
        'source_id': 'test:knee-hit', 'operation': 'replace', 'natural_result': 20})

    # Enter the real ability's step at the point its trigger has resolved. The
    # offer, choice, movement, fight commit and reload use the live table path.
    def take_step(ctx, row):
        if benefit == 'compass':
            step(ctx.engine, ctx.actor, 5, ctx.target, ctx.intent, label='Step Beyond the Angle', stay=False)
        elif benefit == 'black-claw':
            claw_step(ctx, row)
        else:
            storm_heart_step(ctx, ctx.target)

    monkeypatch.setitem(ext.effects(), 'test_fixed_mode_step', take_step)
    combat, table, mid = setup(tmp_path, [HEW, KNEE], dc=-100, foe_walk=10, foe_fly=60,
        terrain_regions=[], foe_setup=lambda bundle: add_action(bundle, 'Trigger fixed step',
            [{'type': 'test_fixed_mode_step'}], target='HOSTILE_ENTITY'))
    use(combat, table, mid, STRIKE + " + Hook the Giant's Knee",
        choices={'choice:needle.movement_mode': 'walk'})
    turn(table, mid, FOE)
    before = combat._load_session(mid).engine
    mover = before.state.actors[FOE]
    assert speed(before, mover, 'walk') == 0
    assert speed(before, mover, 'fly') == 60

    destination = Position(x=4, y=7)
    prompts = use(combat, table, mid, 'Trigger fixed step', target=OWNER, choices={choice: 'cell:4,7'})
    options = next(p['choice']['options'] for p in prompts if p['context']['reaction_source_id'] == choice)
    positions = set()
    for option in options:
        x, y, *z = map(int, option['id'].removeprefix('cell:').split(','))
        positions.add(Position(x=x, y=y, z=z[0] if z else 0))
    assert destination in positions
    assert all(before.grid.distance_ft(mover.position, cell) == 5 for cell in positions)

    after = reload(tmp_path, mid)
    target = after.state.actors[FOE]
    assert target.position == destination
    assert target.movement_remaining_ft == mover.movement_remaining_ft
    receipt = next(e for e in reversed(after.events)
                   if e.event_type == 'MOVEMENT_COMMITTED' and e.source_definition_id == source)
    assert receipt.actor_id == FOE
    assert receipt.payload['movement_mode'] == 'fly'
    assert receipt.payload['granted_cost_ft'] == 5
    assert receipt.payload['cost_ft'] == 0
    assert len(receipt.payload['path']) == 2 and not receipt.payload['interrupted']

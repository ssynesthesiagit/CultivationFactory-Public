"""Real Ice acquisition/Needle mark -> actual Empty Step -> commit/cold replay."""
import pytest

from combat.gate4_adapters import ManualControllerAdapter
from combat.ext.ice_fracture import BASE, marked
from tests.h1_support import sheet
from tests.worker2_support import OWNER, FOE, fixture, candidate, settle, reload
from tests.mgr_t14_acquisition_support import acquire_declared
from tests.test_mgr_t14_fracture_service import prepare, mark_with_needle, QUIET, RESPONSE
from tests.test_auto116_ice import reach


def native_fight(tmp_path, cl, *, ice=True):
    def acquisition(doc, actor):
        acquire_declared('tianxia.sphere.ice')(doc, actor)
        acquire_declared('tianxia.sphere.void')(doc, actor)
    return fixture(tmp_path, [BASE] if ice else [], cl=cl, named=True,
        foe_sheet=sheet(['TAL_VOID_EMPTY_STEP'], cl=cl, score=14, name='Teleporting visitor'),
        bundle_transform=prepare, sheet_edit=acquisition)


@pytest.mark.parametrize('cl', [1, 11])
@pytest.mark.parametrize('accept', [False, True])
@pytest.mark.parametrize('automatic', [False, True])
def test_catch_step_limits_actual_teleport_without_changing_speed(tmp_path, cl, accept, automatic):
    combat, table, mid = native_fight(tmp_path, cl)
    mark_with_needle(combat, table, mid)
    reach(table, mid, FOE, QUIET)
    before = reload(tmp_path, mid)
    start = before.state.actors[FOE].position
    speed = before._effective_speed(before.state.actors[FOE])
    movement = before.state.actors[FOE].movement_remaining_ft
    qi = before.state.actors[FOE].resources['resource:core.qi']
    if automatic:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
        engine = combat._load_session(mid).engine
        chosen = next(c for c in engine.legal_candidates() if 'Empty Step' in c.display_name
            and c.destination is not None and (c.destination.x, c.destination.y) == (2, 6))
        controller = combat.controller
        class SelectActualCandidate:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (chosen.candidate_id, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(controller, name)
        combat.controller = SelectActualCandidate()
        prompts = settle(table, mid, chosen.candidate_id, auto=True, choices={RESPONSE: ['catch'] if accept else None})
    else:
        prompts = settle(table, mid, candidate(combat, mid, 'Empty Step').candidate_id,
            choices={RESPONSE: ['catch'] if accept else None,
                'choice:needle.teleport_destination': ['cell:6,8']})
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[FOE]
    asked = [p for p in prompts if p['context']['reaction_source_id'] == RESPONSE]
    assert len(asked) == 1 and asked[0]['context']['reactor_id'] == OWNER
    assert all(text in str(asked[0]) for text in ('Catch Step', 'Empty Step', 'Teleporting visitor'))
    assert marked(actor, OWNER) is not accept
    assert engine._effective_speed(actor) == speed
    assert actor.movement_remaining_ft == movement
    assert actor.resources['resource:core.qi'] == qi - 1
    assert not actor.bonus_action_available
    travelled = engine.grid.distance_ft(start, actor.position)
    maximum = (0 if cl >= 11 else 10) if accept else 20
    assert travelled <= maximum
    receipts = [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED'
        and e.payload.get('checkpoint') == 'TELEPORT_DISTANCE_REDUCED']
    assert len(receipts) == int(accept)
    if receipts:
        assert receipts[0].actor_id == FOE
        assert receipts[0].payload['maximum_before_ft'] == 20
        assert receipts[0].payload['maximum_after_ft'] == maximum
    if maximum == 0:
        assert actor.position == start
        assert not any(e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == FOE and e.payload.get('teleport')
            for e in engine.events)
    else:
        assert travelled > 0
        movements = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED'
            and e.actor_id == FOE and e.payload.get('teleport')]
        assert len(movements) == 1  # duplicate parser rows represent one hop
    if not automatic and maximum:
        landing = next(p for p in prompts if p['context']['reaction_source_id'].endswith('teleport_destination'))
        ids = {o['id'] for o in landing['choice']['options']}
        assert ('cell:2,6' in ids) is (not accept)
        assert 'cell:6,8' in ids


def test_unowned_and_unmarked_actors_leave_actual_empty_step_unchanged(tmp_path):
    combat, table, mid = native_fight(tmp_path, 1, ice=False)
    reach(table, mid, FOE, QUIET)
    start = reload(tmp_path, mid).state.actors[FOE].position
    prompts = settle(table, mid, candidate(combat, mid, 'Empty Step').candidate_id,
        choices={'choice:needle.teleport_destination': ['cell:2,6']})
    engine = reload(tmp_path, mid)
    assert not any(p['context']['reaction_source_id'] == RESPONSE for p in prompts)
    assert engine.grid.distance_ft(start, engine.state.actors[FOE].position) == 20

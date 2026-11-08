"""Teleport setup must commit real smoke through the table's deferred picker."""
import pytest

from combat import motion, zones
from combat.choice_presentation import option_cell
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.placement_menu import CHOICE
from tests.test_mmx86_paid_teleport_variant import (
    ROOT, OWNER, SHADOW_STEP, _table, _owners_turn, _group, _place_smoke,
)

SMOKE = "tianxia.subpath.qi.ninpo_adept.feature.smoke_veil"


@pytest.mark.parametrize("step,unbound", [
    (SHADOW_STEP, False), (SHADOW_STEP, True),
    ("TAL_DARK_STEP_THROUGH_DARKNESS", False),
    ("TAL_DARK_STEP_THROUGH_DARKNESS", True),
])
def test_teleport_fixture_casts_smoke_at_chosen_square_and_reloads(tmp_path, step, unbound):
    suffix = (SHADOW_STEP if step == SHADOW_STEP
              else "granted.tal_dark_step_through_darkness+full")
    combat, table, mid = _table(tmp_path, owner_talents=(step, SMOKE),
                              unbind=suffix if unbound else None)
    state = _owners_turn(table, mid)
    # This is the actual service menu shape that broke the four teleport cases.
    smoke = _group(state, "Smoke Veil")
    assert smoke is not None and len(smoke["options"]) == 1
    assert not smoke["options"][0].get("destination")
    before = combat._load_session(mid).engine
    qi = before.state.actors[OWNER].resources["resource:core.qi"]
    prompts = _place_smoke(table, mid, state)
    picker, = [p for p in prompts if p["context"]["reaction_source_id"] == CHOICE]
    offered = [option_cell(o["id"]) for o in picker["choice"]["options"]]
    assert {"x": 4, "y": 6, "z": 0} in offered
    assert len(offered) > 1  # The helper chooses; it must not narrow the legal menu.
    cold = CombatService(ROOT, tmp_path)._load_session(mid).engine
    smoke_zone, = [z for z in zones.typed_zones(cold)
                   if z.owner_id == OWNER and z.source_definition_id.endswith(SMOKE)]
    assert smoke_zone.center == Position(x=4, y=6)
    actor = cold.state.actors[OWNER]
    assert actor.position == before.state.actors[OWNER].position
    assert actor.resources["resource:core.qi"] == qi - 2
    assert not actor.bonus_action_available and actor.action_available
    assert motion.obscured(cold, actor)

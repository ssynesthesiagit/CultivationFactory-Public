"""Charged Needle / Meridian-Stopping Spark "cannot regain CP" and Clinging Seal "cannot benefit from the Dash action" were
stand-in 'guarding' tags that did nothing (fight audit 2026-09-29); they are now real conditions."""

import json

from combat import typed_executor
from combat.ext import no_dash
from combat.factory_compiler import TYPED_AUTHORITY
from combat.gate2_runtime_content import AN
from tests.test_reaction_reach import _ctx, _engine, ME

MECH = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]


def test_no_stand_in_guarding_tags_remain():
    assert '"condition": "guarding"' not in json.dumps(MECH)


def test_cannot_regain_cp_stops_a_cp_gain():
    engine = _engine({"x": 1, "y": 1}, {"x": 2, "y": 1})
    me = engine.state.actors[ME]
    engine._spend_resource(me, "resource:core.qi", 3, "test")
    before = me.resources["resource:core.qi"]
    typed_executor.run_effects(_ctx(engine, me, me), [{"type": "condition", "condition": "no_cp_regain", "applies_to": "self", "expires_on": "UNTIL_REMOVED"}])
    typed_executor.run_effects(_ctx(engine, me, me), [{"type": "gain_resource", "resource_id": "resource:core.qi", "flat": 2, "applies_to": "self"}])
    assert me.resources["resource:core.qi"] == before


def test_cannot_dash_takes_the_dash_away():
    engine = _engine({"x": 1, "y": 1}, {"x": 9, "y": 1})
    me = engine.state.actors[ME]

    class Dash:
        source_definition_id = "system:combat.dash"
    assert no_dash.no_dash(engine, me, Dash(), None)
    typed_executor.run_effects(_ctx(engine, engine.state.actors[AN], me), [{"type": "condition", "condition": "no_dash", "applies_to": "target", "expires_on": "UNTIL_REMOVED"}])
    assert not no_dash.no_dash(engine, me, Dash(), None)
    moving = me.movement_remaining_ft
    typed_executor.run_effects(_ctx(engine, me, me), [{"type": "movement", "distance_ft": "speed", "applies_to": "self"}])
    assert me.movement_remaining_ft == moving

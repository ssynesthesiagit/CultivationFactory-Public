"""AUTO58: the Barrage sphere's printed projectile costs, exercised through the compiled table.

"Spend five pieces of ammunition or five thrown weapons" (Needle-Rain Burst), "Spend one ammunition unit or thrown
weapon per 10 feet of line, minimum 10 projectiles" (Hundred-Arrow Passage), "Spend at least 20 ordinary projectiles"
(Ten-Thousand Projectile Rain) and "Spend 10 pieces of ammunition" (Stair Shot) were printed lines left to the GM.
combat/ext/ammunition.py now charges them (``spend_projectiles``), hides an ability the fighter cannot pay for, and
quotes the cost on the ability's own button. Each test fails on the typing that carried the line as a GM rider.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from combat.ext import ammunition
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent

_spec = importlib.util.spec_from_file_location("sweep_athletics_helpers", Path(__file__).with_name("test_review_sw-athletics.py"))
helpers = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(helpers)

ROOT = Path(__file__).resolve().parents[1]
ME, FOE = helpers.ME, AN
ARROW_KIT = {"starting_kit": {"items": [
    {"item_id": "tianxia.mortal.weapon.gong_jian", "name": "Gong Jian", "quantity": 1},
    {"item_id": "tianxia.mortal.gear.arrows_20", "name": "Arrows (20)", "quantity": 2},
]}}
# The harness bow plus a recorded empty quiver: the printed cost reads "ammunition or thrown weapons".
EMPTY_KIT = {"starting_kit": {"items": [
    {"item_id": "tianxia.mortal.weapon.gong_jian", "name": "Gong Jian", "quantity": 1},
    {"item_id": "tianxia.mortal.gear.arrows_20", "name": "Arrows (20)", "quantity": 0},
]}}
# An empty quiver and six javelins: the printed cost reads "ammunition or thrown weapons", so the javelins pay it.
DART_KIT = {"starting_kit": {"items": [
    {"item_id": "tianxia.mortal.weapon.gong_jian", "name": "Gong Jian", "quantity": 1},
    {"item_id": "tianxia.mortal.gear.arrows_20", "name": "Arrows (20)", "quantity": 0},
    {"item_id": "tianxia.mortal.weapon.biao_qiang", "name": "Biao Qiang (Javelin)", "quantity": 3},
    {"item_id": "tianxia.mortal.weapon.biao_qiang", "name": "Biao Qiang (Javelin)", "quantity": 3},
]}}
# A bow whose sheet records no quiver and no thrown weapon: this plug-in's historical unlimited reading.
UNTRACKED_KIT = {"starting_kit": {"items": [
    {"item_id": "tianxia.mortal.weapon.gong_jian", "name": "Gong Jian", "quantity": 1},
]}}
NEEDLE_RAIN = "TAL_BARRAGE_NEEDLE_RAIN_BURST"
HUNDRED_ARROW = "TAL_BARRAGE_HUNDRED_ARROW_PASSAGE"


def _bundle(talents=(), kit=None, *, cl=17, dc=16):
    return helpers._bundle(helpers.BARRAGE, [*talents, NEEDLE_RAIN, HUNDRED_ARROW], kit or ARROW_KIT, cl=cl, dc=dc)


def _fight(*talents, kit=None, cl=17, dc=16, foe_at=(4, 6)):
    return helpers._engine(_bundle(talents, kit, cl=cl, dc=dc), foe_hp=800, foe_at=foe_at)


def _offered(engine, base):
    """Every candidate this ability offers, named by the table."""
    return [candidate.display_name for candidate in engine.legal_candidates()
            if candidate.display_name.split(" \u2014 ")[0] == base or candidate.display_name == base
            or candidate.display_name.startswith(base + " at ")]


def _fire(engine, base, at="4,6"):
    """Use an area ability aimed at the foe's square; its candidate carries the aim, so no target ids are sent."""
    from combat.gate2_runtime_models import ActionIntent
    from tests.equipment_readiness import ready_weapon

    ready_weapon(engine, base, ME)
    candidates = [candidate for candidate in engine.legal_candidates()
                  if candidate.display_name.split(" \u2014 ")[0].startswith(base)]
    assert candidates, f"{base!r} is not a legal action here; offered: {sorted(_offered(engine, base))}"
    chosen = next((candidate for candidate in candidates if f" at {at}" in candidate.display_name), candidates[0])
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{base}", decision_id=chosen.decision_id, candidate_id=chosen.candidate_id,
                                       state_version=chosen.state_version, actor_id=ME,
                                       target_ids=chosen.target_ids, destination=chosen.destination))
    return engine.events[before:]


def _rows(bundle):
    return {row["display_name"]: row for row in bundle["action_catalog"]}


def _spent(engine):
    """Every integer turn flag this plug-in records for the fighter, as (kind, key, pieces)."""
    actor = engine.state.actors[ME]
    return {key: value for key, value in actor.turn_flags.items()
            if key.startswith(ammunition._SPENT_PREFIX) or key.startswith(ammunition._THROWN_SPENT_PREFIX)}


def _log(events):
    return " ".join(str((event.payload or {}).get("rider") or (event.payload or {}).get("text") or "")
                    for event in events)


# ------------------------------------------------------------------------------------------------ the compiled typing


def test_the_printed_projectile_cost_is_typed_not_left_to_the_gm():
    """"Spend five pieces of ammunition or five thrown weapons" was a GM rider; it is a typed charge on the button."""
    mechanics = helpers._mechanics()
    assert mechanics[NEEDLE_RAIN]["riders"] == []
    first = mechanics[NEEDLE_RAIN]["effects"][0]
    assert first["type"] == "spend_projectiles"
    assert first["pieces"] == 5
    assert first["evidence"] == "Spend five pieces of ammunition or five thrown weapons."
    passage = mechanics[HUNDRED_ARROW]["effects"][0]
    assert (passage["per_ft"], passage["length_ft"], passage["minimum"]) == (10, 120, 10)
    assert mechanics["TAL_BARRAGE_TEN_THOUSAND_PROJECTILE_RAIN"]["effects"][0]["pieces"] == 20
    assert mechanics["TAL_BARRAGE_STAIR_SHOT"]["effects"][0]["pieces"] == 10


def test_the_charge_reaches_the_compiled_action_and_its_button_names_the_cost():
    bundle = _bundle()
    action = next(row for row in bundle["action_catalog"] if row["display_name"] == "Needle-Rain Burst")
    assert action["parameters"]["typed"]["effects"][0]["type"] == "spend_projectiles"
    description = ammunition.projectile_description(action)
    assert description is not None
    assert "5 projectiles" in description
    assert "ammunition or thrown weapons" in description


# ------------------------------------------------------------------------------------------------ the printed charge happens


def test_using_needle_rain_burst_spends_the_five_printed_pieces():
    engine = _fight()
    action = next(row for row in engine.action_catalog.values() if row.display_name == "Needle-Rain Burst")
    assert ammunition.projectiles_available(engine, engine.state.actors[ME], action) == (40, "arrows")
    events = _fire(engine, "Needle-Rain Burst")
    assert ammunition.projectiles_available(engine, engine.state.actors[ME], action) == (35, "arrows")
    assert _spent(engine) == {f"{ammunition._SPENT_PREFIX}tianxia.mortal.gear.arrows_20:tianxia.mortal.gear.arrows_20": 5}
    assert "used 5 projectiles" in _log(events)


def test_the_charge_survives_a_table_commit_and_reload(tmp_path):
    """Turn-flag integers only: a table that commits the fight and reloads it keeps the same count."""
    from tests.test_sph_barrage_r1 import test_projectile_cost_commits_reloads_and_replays
    test_projectile_cost_commits_reloads_and_replays(tmp_path)


def test_hundred_arrow_passage_spends_one_piece_per_ten_feet_of_its_printed_line():
    """The printed line is 120 feet at "one ammunition unit or thrown weapon per 10 feet": twelve pieces."""
    engine = _fight(foe_at=(8, 6))
    _fire(engine, "Hundred-Arrow Passage")
    assert sum(_spent(engine).values()) == 12


# ------------------------------------------------------------------------------------------------ the printed limit is enforced


def test_an_ability_with_nothing_to_spend_is_not_offered():
    """A recorded empty quiver and no thrown weapon: nothing to fire the volley with, so it is not a legal action.

    This is the same rule this plug-in already applies to a single strike ("No arrows are carried, so this attack is
    unavailable"), widened to a whole volley that prints a quantity of pieces."""

    engine = _fight(kit=EMPTY_KIT)
    assert not [candidate.display_name for candidate in engine.legal_candidates()
                if candidate.display_name.startswith("Needle-Rain Burst")]


def test_thrown_weapons_pay_a_printed_ammunition_cost_when_no_arrows_are_carried():
    """"five pieces of ammunition or five thrown weapons": with an empty quiver the six carried javelins pay it."""
    engine = _fight(kit=DART_KIT)
    me = engine.state.actors[ME]
    assert ammunition.thrown_pieces(engine, me)[0] == 6
    events = _fire(engine, "Needle-Rain Burst")
    spent = _spent(engine)
    assert sum(spent.values()) == 5
    assert not [key for key in spent if key.startswith(ammunition._SPENT_PREFIX)]  # no arrows to spend
    assert "used 5 projectiles" in _log(events)


def test_fewer_carried_pieces_than_the_printed_quantity_is_not_offered():
    """Four javelins and no arrows against "five pieces of ammunition or five thrown weapons".

    Found by the after-fights: a lenient gate resolved the volley and reported "used 4, 1 short", which is the printed
    ability firing without its printed price. The quantity is the quantity."""
    engine = _fight(kit={"starting_kit": {"items": [
        {"item_id": "tianxia.mortal.weapon.gong_jian", "name": "Gong Jian", "quantity": 1},
        {"item_id": "tianxia.mortal.gear.arrows_20", "name": "Arrows (20)", "quantity": 0},
        {"item_id": "tianxia.mortal.weapon.biao_qiang", "name": "Biao Qiang (Javelin)", "quantity": 2},
        {"item_id": "tianxia.mortal.weapon.biao_qiang", "name": "Biao Qiang (Javelin)", "quantity": 2},
    ]}})
    assert _offered(engine, "Needle-Rain Burst") == []

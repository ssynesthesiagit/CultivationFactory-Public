"""On 2026-11-14 an audit found five printed "ignore your own terrain" clauses
left to the GM: data could express only molten damage or only traversal.
Synthetic persisted tables pin the unified, source-owned grants and Ash defaults.
"""
import json
from pathlib import Path

import pytest

from combat import zones, zone_subjects
from combat.ext import magma_crust
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, act, fight, reload, settle, turn

ARMOR = "TAL_MAGMA_MAGMA_ARMOR"
SOVEREIGN = "TAL_MAGMA_VOLCANO_SOVEREIGN_INCARNATION"
FLAME = "tianxia.talent.fire.court_of_the_living_flame"
ASH = "tianxia.talent.ash.court_of_the_last_ember"


def terrain(name):
    return {
        "shape": "sphere", "size_ft": 10, "centered_on_self": True,
        "terrain": [name], "difficult": "all",
        "duration": {"kind": "minutes", "amount": 10},
        "move_through": {"min_ft": 5, "who": "any", "effects": [
            {"type": "condition", "condition": "reaction_denied",
             "applies_to": "target", "duration": "until_end_of_next_turn"}]},
        "triggers": [{"on": ["start"], "who": "any", "roster": "any",
                      "effects": [{"type": "damage", "flat": 20,
                                   "damage_types": ["force"], "applies_to": "target"}]}],
    }


def setup(tmp_path, talent, kind, own, **kwargs):
    spec = terrain(kind)

    def hold_concentration(bundle):
        # The foreign-terrain cases must keep the Court after its damage;
        # losing Concentration would remove the very grant being checked.
        bundle["actor_template"]["saving_throws"]["CON"] = 1000

    c, t, m = fight(
        tmp_path, [talent], spheres=["tianxia.sphere.magma" if talent in (ARMOR, SOVEREIGN)
                                    else "tianxia.sphere.fire" if talent == FLAME
                                    else "tianxia.sphere.ash"],
        prepare=[{"type": "zone"}] if own else [], prepare_target="SELF",
        prepare_zone_spec=spec if own else None,
        cause=[{"type": "zone"}] if not own else [], cause_target="SELF",
        cause_zone_spec=spec if not own else None,
        bundle_edit=hold_concentration, **kwargs)
    if own:
        settle(lambda answers: act(t, m, "Prepare", answers))
    return c, t, m


def start_hazard(c, t, m, own):
    turn(t, m, RIGHT)
    if not own:
        settle(lambda answers: act(t, m, "Cause", answers))
    turn(t, m, LEFT)
    e = reload(c, m)
    z = next(z for z in zones.typed_zones(e)
             if z.source_definition_id.startswith("action:test.worker1."))
    return e, z


@pytest.mark.parametrize("own", [True, False])
def test_magma_armor_damage_only_keeps_owner_boundary(tmp_path, own):
    c, t, m = setup(tmp_path, ARMOR, "molten terrain", own)
    settle(lambda answers: act(t, m, ARMOR, answers))
    e, z = start_hazard(c, t, m, own)
    bearer = e.state.actors[LEFT]
    assert bearer.current_hp == (1000 if own else 980)
    assert (3, 6) in zones.difficult_cells(e, bearer)
    assert zone_subjects.allowed(e, z, bearer, z.trigger_profile["move_through"])


@pytest.mark.parametrize("own", [True, False])
def test_sovereign_ignores_obsidian_only_while_form_active(tmp_path, own):
    c, t, m = setup(tmp_path, SOVEREIGN, "obsidian terrain", own, maximum_rounds=13)
    e = reload(c, m)
    assert not magma_crust.sovereign_active(e, e.state.actors[LEFT])
    if own:
        z = next(z for z in zones.typed_zones(e)
                 if z.source_definition_id.startswith("action:test.worker1."))
        assert (3, 6) in zones.difficult_cells(e, e.state.actors[LEFT])
    settle(lambda answers: act(t, m, SOVEREIGN, answers))
    e, z = start_hazard(c, t, m, own)
    bearer = e.state.actors[LEFT]
    assert magma_crust.sovereign_active(e, bearer)
    assert bearer.current_hp == (1000 if own else 980)
    assert ((3, 6) not in zones.difficult_cells(e, bearer)) == own
    assert zone_subjects.allowed(e, z, bearer, z.trigger_profile["move_through"]) == (not own)
    if own:
        for _ in range(10):
            turn(t, m, RIGHT)
            turn(t, m, LEFT)
        e = reload(c, m)
        assert not magma_crust.sovereign_active(e, e.state.actors[LEFT])
        assert e.state.actors[LEFT].current_hp < 1000
        assert (3, 6) in zones.difficult_cells(e, e.state.actors[LEFT])


@pytest.mark.parametrize("own", [True, False])
def test_living_flame_shelters_caster_and_allies_from_casters_fire_terrain(tmp_path, own):
    # All five option branches must retain the same continuous allied grant.
    authority = json.loads((Path(__file__).resolve().parents[1] /
                            "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    row = authority["mechanics"][FLAME]
    for option in row["options"]:
        grants = [inside["rule"]["terrain_immunity"]
                  for effect in option["effects"] for inside in effect.get("inside", [])
                  if "terrain_immunity" in inside.get("rule", {})]
        assert grants == [{"names": ["fire terrain"], "owner": "source",
                           "parts": ["difficult", "move_through", "damage"]}]
        assert not any("ignore your Fire Terrain" in rider for rider in option["riders"])
    assert not any("ignore your Fire Terrain" in rider for rider in row["riders"])

    c, t, m = setup(tmp_path, FLAME, "fire terrain", own, ally=[],
                    positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6},
                               ALLY: {"x": 3, "y": 5}})
    settle(lambda answers: act(t, m, FLAME + "#opt0", answers))
    e, z = start_hazard(c, t, m, own)
    for aid in (LEFT, ALLY):
        bearer = e.state.actors[aid]
        assert ((3, 6) not in zones.difficult_cells(e, bearer)) == own
        assert zone_subjects.allowed(e, z, bearer, z.trigger_profile["move_through"]) == (not own)
    assert e.state.actors[LEFT].current_hp == (1000 if own else 980)
    turn(t, m, ALLY)
    e = reload(c, m)
    assert e.state.actors[ALLY].current_hp == (1000 if own else 980)


@pytest.mark.parametrize("own", [True, False])
def test_ash_court_defaults_still_excuse_traversal_but_not_zone_damage(tmp_path, own):
    c, t, m = setup(tmp_path, ASH, "ash terrain", own)
    settle(lambda answers: act(t, m, ASH, answers))
    e, z = start_hazard(c, t, m, own)
    bearer = e.state.actors[LEFT]
    assert bearer.current_hp == 980
    assert ((3, 6) not in zones.difficult_cells(e, bearer)) == own
    assert zone_subjects.allowed(e, z, bearer, z.trigger_profile["move_through"]) == (not own)

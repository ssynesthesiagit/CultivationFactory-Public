"""Magma review fixes (F10): nonmagical unarmed resistance, next-turn Heat Pressure, choice key.

Every fixture here is synthetic (a table built from the authority and the shared worker-1
helpers), so the file runs on public CI.
"""
from combat import typed_reactions
from combat.ext import effect_durations
from tests.auto_worker1_support import LEFT, RIGHT, act, cell_send, fight, settle, turn
from tests.h1_support import mechanics
from tests.test_a2_magma import cold

MAGMA = "tianxia.sphere.magma"
HEAT = "condition:typed.heat_pressure"
HEAT_TURN = "condition:typed.heat_pressure_turn"
GLOB = "TAL_MAGMA_MAGMA_GLOB"
SMOKE = "TAL_MAGMA_VOLCANIC_SMOKE"
ARMOR = "TAL_MAGMA_MAGMA_ARMOR"
IRON_FIST_SPHERE = "tianxia.sphere.iron_fist"
IRON_FIST = "tianxia.talent.iron_fist.the_fist_that_taught_heaven_to_flinch"
UNARMED = "Unarmed Strike (Iron Fist)"


def heat_picker(mode="move_or_action", turn_mode="action", seen=None):
    """Answer the plug-in's own Needle choices and record the keys they were asked under."""
    def choose(prompt):
        source = prompt["context"]["reaction_source_id"]
        if seen is not None:
            seen.append(source)
        if source == "choice:needle.magma_glob_expression":
            return ["Heat Pressure"]
        if source == "choice:needle.magma_heat_pressure":
            return [mode]
        if source == "choice:needle.magma_heat_turn":
            assert prompt["context"]["reactor_id"] == RIGHT
            return [turn_mode]
        options = prompt["choice"]["options"]
        return [o["id"] for o in options[: max(1, prompt["choice"].get("minimum", 1))]]
    return choose


def iron_fist_fighter(doc, aid):
    """Keep the attacking side's sphere base ability: it is what grants the printed Unarmed Strike.

    The shared fixture empties a sphere's automatic components, so the Iron Fist sphere's own
    base ability (the one that grants "Unarmed Strike (Iron Fist)") is put back here.
    """
    if aid != RIGHT:
        return
    doc["spheres_and_talents"]["automatic_sphere_component_record_ids"] = [
        key for key, row in mechanics().items()
        if row.get("sphere_id") == IRON_FIST_SPHERE and row.get("kind") == "base_ability"]


def test_magma_armor_resists_a_real_compiled_unarmed_attack(tmp_path):
    """A printed "nonmagical" defense must read a real unarmed attack, not a synthetic packet."""
    # An empty kit leaves the defender at Armor Class 1, so the unarmed strike always lands.
    c, t, m = fight(tmp_path, [ARMOR], spheres=[MAGMA], left_kit={"items": []},
                    right_talents=[IRON_FIST], right_spheres=[IRON_FIST_SPHERE],
                    sheet_edit=iron_fist_fighter)
    settle(lambda a: act(t, m, "Magma Armor", a))
    c, t, e = cold(c, m)
    attack = next(a for a in e.action_catalog.values() if a.display_name == UNARMED)
    # The producer says so: an unarmed strike is nonmagical damage.
    assert attack.parameters["typed"]["mundane"] is True
    # The printed defense answers that packet while the armor is up.
    assert typed_reactions.resists(e, e.state.actors[LEFT], "bludgeoning", attack.source_definition_id)
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, UNARMED, a, target_id=LEFT))
    c, t, e = cold(c, m)
    committed = [v for v in e.events if v.event_type == "DAMAGE_COMMITTED"
                 and v.source_definition_id == attack.source_definition_id and LEFT in v.target_ids]
    assert len(committed) == 1
    packet = committed[0].payload
    assert packet["rolled_or_pending_damage"] > 0
    assert packet["reduced_to"] == packet["rolled_or_pending_damage"] // 2


def test_heat_pressure_that_lands_mid_turn_lands_on_the_affected_creatures_next_turn(tmp_path):
    """Heat Pressure says "on its next turn": a mid-turn application waits for that turn."""
    c, t, m = fight(tmp_path, [SMOKE], spheres=[MAGMA], cl=15, left_save_dc=100)
    pick = heat_picker()
    settle(cell_send(t, m, "Volcanic Smoke", (4, 6)), pick)
    # The smoke burns the creature whose turn is starting: the Heat Pressure lands mid-turn.
    turn(t, m, RIGHT, pick)
    c, t, e = cold(c, m)
    target = e.state.actors[RIGHT]
    heat, = [v for v in target.conditions.values() if v.condition_id == HEAT]
    assert heat.data["mode"] == "move_or_action"
    # The obligation is the affected creature's NEXT turn, not the one it is taking now.
    assert heat.data["turn"] == target.turns_started + 1
    assert effect_durations.parse(heat.expires_on) == ("end", RIGHT, heat.data["turn"])
    # Nothing is decided yet, and the turn in progress is not restricted.
    assert not any(v.condition_id == HEAT_TURN for v in target.conditions.values())
    assert any(v.kind.value == "MOVE" for v in e.legal_candidates())
    # The affected creature's next turn: the choice is asked there, and only there.
    turn(t, m, LEFT, pick)
    turn(t, m, RIGHT, pick)
    c, t, e = cold(c, m)
    target = e.state.actors[RIGHT]
    delivered, = [v for v in target.conditions.values() if v.condition_id == HEAT_TURN]
    assert delivered.data["mode"] == "action"
    assert not any(v.kind.value == "MOVE" for v in e.legal_candidates())
    assert target.action_available


def test_heat_pressure_outcome_is_asked_under_its_own_needle_key(tmp_path):
    """A driver keys the plug-in's choice by "magma_heat_pressure"; that key must be the one asked."""
    seen = []
    c, t, m = fight(tmp_path, [GLOB], spheres=[MAGMA], left_attack_bonus=100)
    settle(lambda a: act(t, m, "Magma Glob: Heat Pressure", a, target_id=RIGHT),
           heat_picker("reactions", seen=seen))
    c, t, e = cold(c, m)
    assert "choice:needle.magma_heat_pressure" in seen
    assert any(v.condition_id == "condition:typed.reaction_denied"
               for v in e.state.actors[RIGHT].conditions.values())

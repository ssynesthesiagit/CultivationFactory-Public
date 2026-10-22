"""PICMP1: the Monkey Style combat riders this pass automated, each against the printed text through the real table.

Authority -> compiled action -> CombatService/TabletopService or the gate2 engine -> cold reload. Assertions are typed
fields, ids and recorded state, never printed prose, so public CI (which scrambles long prose) still reads the same
behaviour. Inert without the printed talents: every test gives the sheet only the talents it needs.
"""
import pytest

from combat import flight, typed_executor as te
from combat import typed_reactions as tr
from combat.ext import monkey
from tests.auto_worker1_support import fight, act, reload, action_sender, settle, turn, LEFT, RIGHT

SPHERE = "tianxia.sphere.monkey_style"
M = "TAL_MONKEY_STYLE_"
TRICKSTER = M + "HUNDRED_HANDED_TRICKSTER"
HOOK = M + "TAIL_QI_HOOK"
CAPER = M + "CAPERING_FOOTWORK"
REVERSAL = M + "IMPOSSIBLE_APE_REVERSAL"
TRANSFORM = "tianxia.talent.monkey_style.seventy_two_earthly_transformations"


def transform(c, t, m, label):
    return settle(action_sender(c, t, m, "Seventy-Two Earthly Transformations: " + label))


def bead(object_id, x, y, *, size="tiny", name="Jade bead"):
    return {"id": object_id, "kind": "custom", "name": name, "x": x, "y": y, "size": size, "blocks": False}


def door(object_id, x, y, name="Paper door", **flags):
    return {"id": object_id, "kind": "door", "name": name, "x": x, "y": y, "interaction": "simple_door",
            "door_open": 0, "door_locked": 0, "door_jammed": 0, **flags}


def add_objects(*objects):
    def edit(arena):
        for row in objects:
            arena["map_objects"].append(row)
    return edit


def attempted(engine, suffix):
    return [event for event in engine.events if event.event_type == "DAMAGE_ROLLED"
            and str(event.source_definition_id).endswith(suffix)]


# ------------------------------------------------------------- Hundred-Handed Trickster: the improvised weapon floor
@pytest.mark.parametrize(("owned", "sides"), [((TRICKSTER,), "d8"), ((), "d4")])
def test_trickster_improvised_weapon_rolls_at_least_1d8(tmp_path, owned, sides):
    """While Hundred-Handed Trickster is active, an improvised weapon deals at least 1d8; without it the same weapon
    keeps the compiler's own 1d4."""
    c, t, m = fight(tmp_path, list(owned), spheres=[SPHERE], cl=18, left_resource="Stamina")
    if owned:
        result, _ = settle(action_sender(c, t, m, "Hundred-Handed Trickster"))
        assert result["status"] == "COMMITTED", result
    result, _ = settle(action_sender(c, t, m, "Grab an improvised weapon"))
    assert result["status"] == "COMMITTED", result
    result, _ = settle(action_sender(c, t, m, "Improvised weapon attack", target_id=RIGHT))
    assert result["status"] == "COMMITTED", result
    rolls = attempted(reload(c, m), "improvised.attack")
    assert rolls, "the improvised attack rolled no damage"
    assert all(sides in event.payload["expression"] for event in rolls), [event.payload["expression"] for event in rolls]


def test_trickster_floor_never_lowers_a_larger_printed_die():
    """The floor only raises: a printed 1d10 improvised weapon (Improvised Master) is not cut to 1d8."""
    from types import SimpleNamespace

    from combat.gate2_runtime_models import DiceSpec

    actor = SimpleNamespace(conditions={"c": SimpleNamespace(condition_id="condition:typed.trick",
                                          source_definition_id=TRICKSTER)}, modifiers={})
    ctx = SimpleNamespace(actor=actor, engine=None, weapon_damage_dice=True,
                          action=SimpleNamespace(parameters={"typed": {"source": "improvised_weapon"}}))
    assert monkey.trickster_improvised_minimum(ctx, DiceSpec(count=1, sides=4)).sides == 8
    assert monkey.trickster_improvised_minimum(ctx, DiceSpec(count=1, sides=10)) is None
    technique = SimpleNamespace(actor=actor, engine=None, weapon_damage_dice=True,
                                action=SimpleNamespace(parameters={"typed": {"source": "technique"}}))
    assert monkey.trickster_improvised_minimum(technique, DiceSpec(count=1, sides=4)) is None, \
        "a technique that printed its own die is not the fighter's improvised weapon"


def test_trickster_floor_is_inert_without_the_active_talent():
    """The printed line is "While this talent is active"; an inactive sheet keeps its 1d4."""
    from types import SimpleNamespace

    from combat.gate2_runtime_models import DiceSpec

    ctx = SimpleNamespace(actor=SimpleNamespace(conditions={}, modifiers={}), engine=None,
                          weapon_damage_dice=True,
                          action=SimpleNamespace(parameters={"typed": {"source": "improvised_weapon"}}))
    assert monkey.trickster_improvised_minimum(ctx, DiceSpec(count=1, sides=4)) is None


# ------------------------------------------------------------- Tail-Qi Hook: the printed object options
def test_tail_qi_hook_pulls_a_tiny_object_into_reach(tmp_path):
    """A Tiny unattended object within 10 feet is moved to a legal space in the fighter's own reach, and the fight
    records the move after a cold reload."""
    c, t, m = fight(tmp_path, [HOOK], spheres=[SPHERE], cl=18, left_resource="Stamina",
                    arena_edit=add_objects(bead(90, 5, 6)))
    before = reload(c, m).state.objects["object:map.90"].position
    assert (before.x, before.y) == (5, 6)
    chosen = "pull a Tiny unattended object to your hand"

    def pick(prompt):
        options = prompt["choice"]["options"]
        if prompt["context"]["reaction_source_id"].endswith("monkey_tail_qi_pull_space"):
            in_reach = [option["id"] for option in options
                        if option["label"].endswith("5 feet") and not option["label"].startswith("(3, 6,")]
            return in_reach[:1] or [options[0]["id"]]
        return [option["id"] for option in options if option["label"] == chosen]

    result, prompts = settle(action_sender(c, t, m, "Tail-Qi Hook"), choose=pick)
    assert result["status"] == "COMMITTED", result
    assert [p for p in prompts if p["context"]["reaction_source_id"].endswith("monkey_tail_qi_pull_space")], prompts
    engine = reload(c, m)
    me, moved = engine.state.actors[LEFT], engine.state.objects["object:map.90"]
    assert (moved.position.x, moved.position.y) != (before.x, before.y), "the object did not move"
    assert engine.grid.distance_ft(me.position, moved.position) <= 5, "the object did not come into reach"


def test_tail_qi_hook_offers_no_object_that_is_not_there(tmp_path):
    """Without a Tiny unattended object in range the option moves nothing and invents nothing."""
    c, t, m = fight(tmp_path, [HOOK], spheres=[SPHERE], cl=18, left_resource="Stamina",
                    arena_edit=add_objects(bead(91, 5, 6, size="medium")))
    before = reload(c, m).state.objects["object:map.91"].position
    chosen = "pull a Tiny unattended object to your hand"
    result, prompts = settle(action_sender(c, t, m, "Tail-Qi Hook"),
                             choose=lambda prompt: [option["id"] for option in prompt["choice"]["options"]
                                                    if option["label"] == chosen])
    assert result["status"] == "COMMITTED", result
    assert not [p for p in prompts if p["context"]["reaction_source_id"].endswith("monkey_tail_qi_pull")], prompts
    engine = reload(c, m)
    after = engine.state.objects["object:map.91"].position
    assert (after.x, after.y, after.z) == (before.x, before.y, before.z)


def test_tail_qi_hook_opens_an_unlocked_door_and_never_a_locked_one(tmp_path):
    """The printed "open or close an unlocked door" reaches the shared door state; the locked door is not offered"""
    """and no lock is picked."""
    c, t, m = fight(tmp_path, [HOOK], spheres=[SPHERE], cl=18, left_resource="Stamina",
                    arena_edit=add_objects(door(92, 3, 4), door(93, 2, 6, name="Iron door", door_locked=1)))
    result, prompts = settle(action_sender(c, t, m, "Tail-Qi Hook"),
                             choose=lambda prompt: [option["id"] for option in prompt["choice"]["options"]
                                                    if option["id"] == "object:map.92|open"])
    assert result["status"] == "COMMITTED", result
    asked = [p for p in prompts if p["context"]["reaction_source_id"].endswith("monkey_tail_qi_door")]
    assert len(asked) == 1, prompts
    ids = {option["id"] for option in asked[0]["choice"]["options"]}
    assert "object:map.92|open" in ids
    assert not [option for option in ids if option.startswith("object:map.93")], "the locked door was offered"
    engine = reload(c, m)
    assert engine.state.objects["object:map.92"].component["door_open"] == 1
    assert engine.state.objects["object:map.93"].component["door_open"] == 0
    assert engine.state.objects["object:map.93"].component["door_locked"] == 1


def test_tail_qi_hook_offers_a_no_action_use_only_while_the_caper_is_active(tmp_path):
    """Multi-Mode: Bonus Action, or no Action while Capering Footwork is active."""
    c, t, m = fight(tmp_path, [HOOK, CAPER], spheres=[SPHERE], cl=18, left_resource="Stamina")
    free = lambda state: [group for group in state["menu"]["actions"]
                          if str(group["source_definition_id"]).endswith(".caper_no_action")]
    assert not free(t.state(m)), "the free mode was offered without the caper"
    result, _ = settle(action_sender(c, t, m, "Capering Footwork"))
    assert result["status"] == "COMMITTED", result
    offered = free(t.state(m))
    assert offered, "the printed no-Action mode is missing while the caper is active"
    engine = reload(c, m)
    action = next(row for row in engine.action_catalog.values()
                  if str(row.source_definition_id).endswith(".caper_no_action"))
    economy = getattr(action.economy, "value", action.economy)
    assert str(economy).endswith("NONE"), action.economy
    assert action.parameters.get("requires_condition") == CAPER


# ------------------------------------------------------------- Impossible Ape Reversal: the grapple/restraint case
def test_ape_reversal_ends_the_hold_that_triggered_it():
    """The printed "the triggering grapple or restraint fails instead of an attack" ends the holding condition that
    creature applied, and only that creature's hold."""
    from tests.test_auto85_monkey_style import answering, fight as table_fight, has

    _, engine, me, foe = table_fight(REVERSAL, dc=50)
    bystander = foe.model_copy(deep=True)
    bystander.entity_id = "auto85:bystander"
    engine.state.actors[bystander.entity_id] = bystander
    engine._apply_condition(me, te.CONDITION_PREFIX + "grappled", "test:hold", foe.entity_id,
                            expires_on="UNTIL_REMOVED")
    engine._apply_condition(me, te.CONDITION_PREFIX + "restrained", "test:other", bystander.entity_id,
                            expires_on="UNTIL_REMOVED")
    held = [c for c in me.conditions.values() if c.condition_id == te.CONDITION_PREFIX + "grappled"]
    assert held, "the setup grapple is not on the fighter"

    asked = []
    answering(engine, [["the triggering attack misses, or the triggering grapple or restraint fails",
                        "the triggering creature falls Prone"]], asked)
    tr.on_attack_hit(engine, foe, me, {"range_ft": 5}, 20, 20, 10)
    assert not [c for c in me.conditions.values() if c.condition_id == te.CONDITION_PREFIX + "grappled"], \
        "the triggering grapple survived the reversal"
    assert [c for c in me.conditions.values() if c.condition_id == te.CONDITION_PREFIX + "restrained"], \
        "a hold another creature applied was ended"
    assert has(foe, "prone"), "the second printed result did not happen"


# ------------------------------------------------------------- Seventy-Two Earthly Transformations: Flying Beast
def test_flying_beast_flies_at_the_printed_speed_after_reload(tmp_path):
    """Flying Beast: Fly Speed 50 feet -- recorded by the form the fighter actually took."""
    c, t, m = fight(tmp_path, [TRANSFORM], spheres=[SPHERE], cl=18, left_resource="Stamina")
    result, _ = transform(c, t, m, "Flying Beast")
    assert result["status"] == "COMMITTED", result
    engine = reload(c, m)
    me = engine.state.actors[LEFT]
    assert flight.profile(engine, me).speed_ft == 50
    assert not flight.profile(engine, me).hover, "the printed Hover is not granted by this talent"
    assert me.speed_ft == 30, "the Fly Speed must not become walking speed"


@pytest.mark.parametrize("label", ["Swift Beast", "Tiny Scout", "Burrowing Beast"])
def test_other_forms_do_not_fly(tmp_path, label):
    """Only the Flying Beast template reports a Fly Speed; every other template reports none."""
    c, t, m = fight(tmp_path, [TRANSFORM], spheres=[SPHERE], cl=18, left_resource="Stamina")
    result, _ = transform(c, t, m, label)
    assert result["status"] == "COMMITTED", result
    engine = reload(c, m)
    assert flight.profile(engine, engine.state.actors[LEFT]).speed_ft == 0


def test_flying_beast_is_inert_without_the_talent(tmp_path):
    """No talent, no transform action, and no Fly Speed to find."""
    c, t, m = fight(tmp_path, [], spheres=[SPHERE], cl=18, left_resource="Stamina")
    engine = reload(c, m)
    me = engine.state.actors[LEFT]
    assert flight.profile(engine, me).speed_ft == 0
    assert not [group for group in t.state(m)["menu"]["actions"]
                if TRANSFORM in str(group.get("source_definition_id", ""))]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

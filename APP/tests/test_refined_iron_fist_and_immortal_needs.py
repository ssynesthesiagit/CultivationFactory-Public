"""Refined Iron Fist (an integrated weapon counts as magical) and Immortal Body's Transcended Mortal Needs (travel)."""
import pytest

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from tests.h1_support import ROOT, sheet
from tests.test_riders_c7 import FOE, bundle, fight, use

BODY = "tianxia.path.body_refining.feature."
CHAIN = "tianxia.subpath.body.heaven_binding_chain_body.feature."
WHIP = "tianxia.mortal.weapon.jie_bian"


def _whip_damage(ids):
    """Damage one hit of the whip does to a foe who has Body Tempering (Resistance to nonmagical bludgeoning, piercing, slashing)."""
    engine = fight(bundle(ids, items=(WHIP,)), foe=bundle([BODY + "body_tempering"], actor_id=FOE, name="Tempered foe"), foe_at=(4, 6))
    foe = engine.state.actors[FOE]
    foe.armor_class = -50
    hp = foe.current_hp
    use(engine, "Jie Bian (Sectional Steel Whip / Chain Whip) attack", target=FOE)
    return hp - foe.current_hp


def test_refined_iron_fist_makes_an_integrated_weapon_overcome_resistance_to_nonmagical_damage():
    integrated = CHAIN + "chain_body_integration"
    plain = _whip_damage([integrated])
    refined = _whip_damage([integrated, BODY + "refined_iron_fist"])
    assert plain > 0 and refined > plain  # Resistance halves the mundane whip; the refined one counts as magical


def test_refined_iron_fist_does_not_make_a_weapon_you_have_not_integrated_magical():
    assert _whip_damage([BODY + "refined_iron_fist"]) == _whip_damage([])


# ------------------------------------------------------------------------------------------ Immortal Body on a journey
A = FACTORY_ACTOR_PREFIX + "traveller"
B = FACTORY_ACTOR_PREFIX + "companion"


def _journey(tmp_path, monkeypatch, owned):
    monkeypatch.setattr(CombatService, "_factory_owner_sheet",
                        lambda self, pid: sheet([BODY + "immortal_body"] if owned and pid == "traveller" else [], cl=20, name=pid))
    monkeypatch.setattr(CombatService, "factory_arenas", lambda self: {"scene": {
        "stable_id": "journey:test", "width_squares": 20, "height_squares": 5, "square_size_ft": 5,
        "starting_positions": {}, "terrain_regions": []}})
    service = CombatService(ROOT, tmp_path)
    jid = service.create_journey(project_ids=["traveller", "companion"], arena_id="scene",
                                 positions={A: {"x": 0, "y": 1}, B: {"x": 0, "y": 2}},
                                 base_paces={A: 5, B: 5}, control_modes={A: "MANUAL"})["journey_id"]
    fresh = CombatService(ROOT, tmp_path)
    return fresh.journey_act(jid, fresh.journey_state(jid)["revision"], A, "travel_exhaustion", {"levels": 1, "ordinary": True})


@pytest.mark.parametrize("owned,levels", [(True, 0), (False, 1)])
def test_ordinary_hunger_thirst_and_air_do_not_exhaust_an_immortal_body(tmp_path, monkeypatch, owned, levels):
    assert _journey(tmp_path, monkeypatch, owned)["actors"][A]["exhaustion"] == levels


# -------------------------------------------------------------------------------------- Titan's Frame: carrying capacity
CRUCIBLE = "tianxia.subpath.body.flesh_crucible.feature."


def _capacities(ids):
    from combat import carry
    from combat.ext import states

    engine = fight(bundle([CRUCIBLE + k for k in ids]))
    me = engine.state.actors["actor:factory.c7"]
    before = carry.status(engine, me)["capacity_lb"]
    use(engine, "Titan's Frame")
    during = carry.status(engine, me)["capacity_lb"]
    held = states.active(engine, me, "titan_s_frame")
    engine._remove_condition_instance(me, held.instance_id, "test", expected=held)
    return before, during, carry.status(engine, me)["capacity_lb"]


def test_titans_frame_doubles_carrying_capacity_while_it_lasts():
    before, during, after = _capacities(["titan_s_frame"])
    assert (during, after) == (2 * before, before)


def test_titanic_frame_quadruples_it():
    before, during, after = _capacities(["titan_s_frame", "titanic_frame"])
    assert (during, after) == (4 * before, before)


# ------------------------------------------------------------------------------------- Immortal Body: Body Recalls Life (RW170 fix)
STAMINA = "resource:core.stamina"


def _downed_immortal(hp_drop=True):
    from tests.test_riders_c7 import ME, turn, answers
    engine = fight(bundle([BODY + "immortal_body"]), foe_at=(4, 6))
    answers(engine, {"body_recalls_life": ["recall"]})
    actor = engine.state.actors[ME]
    if hp_drop:
        actor.current_hp = 0
        engine._defeat(actor, "test:downed")
    return engine, actor, ME, turn


def test_body_recalls_life_restores_a_downed_immortal_body_at_the_start_of_its_turn():
    engine, actor, me, turn = _downed_immortal()
    assert actor.life_state == "DYING" and actor.active  # alive at 0 HP, not defeated
    before = actor.resources[STAMINA]
    turn(engine, me)
    assert actor.current_hp == 20 and actor.life_state is None and actor.active
    assert actor.resources[STAMINA] == before - 10
    assert not any(c.condition_id == "condition:typed.life_unconscious" for c in actor.conditions.values())


def test_body_recalls_life_is_once_per_scene():
    engine, actor, me, turn = _downed_immortal()
    turn(engine, me)
    actor.current_hp = 0
    engine._defeat(actor, "test:downed_again")
    turn(engine, me)
    assert actor.current_hp == 0  # the scene's one use is spent; no second offer


def test_body_recalls_life_is_not_offered_below_ten_stamina():
    engine, actor, me, turn = _downed_immortal()
    actor.resources[STAMINA] = 9
    turn(engine, me)
    assert actor.current_hp == 0 and actor.resources[STAMINA] == 9


def test_immortal_body_rider_states_the_air_and_regrowth_scope_it_does_not_automate():
    import json
    rows = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/rw170_body_refining.json").read_text())
    text = " ".join(json.dumps(rows))
    assert "do not require food, drink, air or sleep" in text
    assert "suffocation and choke holds" in text and "2 hours" in text


def test_carry_capacity_multiplier_hook_is_documented():
    doc = (ROOT / "combat/ext/__init__.py").read_text()
    assert "carry_capacity_multiplier(engine, actor)" in doc

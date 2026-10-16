"""Open-Hand Disarm spends only the defender's actual next-check benefit.

Legal unarmed hits and Ask-me defense choices run through the table service;
fresh disk loads and same-turn followup checks rule out expiry as consumption.
"""
import pytest

from combat.ext import berserker, iron_open_hand
from combat.ability_checks import skill_bonus
from tests.auto8f1_table_support import fixture, AXE_KIT, OWNER, FOE
from tests.cw2_service_support import seal
from tests.test_a2r22_review import (
    COORDINATED, MERIDIAN, add_action, use, held, finish, fake_menu_embeddings,
)


@pytest.mark.parametrize("benefit", ["meridian", "unyielding"])
@pytest.mark.parametrize("skill", ["Athletics", "Acrobatics"])
def test_open_hand_defending_check_spends_once_after_table_reload(tmp_path, benefit, skill):
    owner_talents = ([COORDINATED, MERIDIAN] if benefit == "meridian" else
                     ["TAL_BERSERKER_BATTER", "TAL_BERSERKER_UNYIELDING_ADVANCE"])

    def prepare(bundles):
        for bundle in bundles:
            template = bundle["actor_template"]
            if bundle["actor_id"] == OWNER:
                template["armor_class"] = 0
                # Both contest outcomes are exercised; a lost defense still
                # spends the benefit and dropping the weapon cannot rearm it.
                # Compiled sheet skill totals live at bundle level and take
                # precedence over actor-template fallback statistics.
                bundle.setdefault("skills", {}).update({name: 1000 if skill == "Athletics" else -1000
                                                        for name in ("Athletics", "Acrobatics")})
            if bundle["actor_id"] in (OWNER, FOE):
                for resource in template["resources"]:
                    if resource["resource_id"] == "resource:core.martial_focus":
                        resource["initial"] = 0
            if bundle["actor_id"] == FOE:
                for action in bundle["action_catalog"]:
                    if action["display_name"] == "Unarmed Strike (Iron Fist)":
                        action["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
                # A legal test-only bonus action makes two non-damaging checks
                # before either creature's next turn. The initiator's unskilled
                # Strength checks must not spend its held Meridian benefit.
                add_action(bundle, "Followup Athletics checks", [{
                    "type": "contest_against",
                    "actor_check": {"kind": "check", "ability": "STR"},
                    "target_check": {"kind": "check", "ability": "STR", "skill": "Athletics"},
                }] * 2, hostile=True)
                bundle["action_catalog"][-1]["economy"] = "BONUS_ACTION"
            seal(bundle)

    g = fixture(tmp_path, owner_talents, seed="A2R22FF2-open-hand", kit=AXE_KIT,
                talents_by_actor={FOE: [iron_open_hand.SOURCE, COORDINATED, MERIDIAN]},
                ask_actors=(FOE,), bundle_transform=prepare)
    use(g, "Dodge" if benefit == "meridian" else "Adrenaline: Unyielding Advance")
    g["turn_of"](FOE)
    use(g, "Dash")
    g["to_owner"]()
    # A neutral movement action also arms Meridian for its owner. Dodge would
    # make this seed's triggering unarmed attack miss on a natural 1, leaving
    # no hit, damage or defending check to exercise Unyielding consumption.
    use(g, "Dash")
    g["turn_of"](FOE)
    before = g["stored_engine"]()
    assert iron_open_hand.held_weapons(before, before.state.actors[OWNER])
    assert all(skill_bonus(before, before.state.actors[OWNER], name, 0) ==
               (1000 if skill == "Athletics" else -1000)
               for name in ("Athletics", "Acrobatics")), "exercise both actual contest outcomes"
    assert held(before.state.actors[FOE]), "the attacking side has its own unused check benefit"
    if benefit == "meridian":
        assert held(before.state.actors[OWNER])
    else:
        assert not before.state.actors[OWNER].turn_flags.get(berserker.UNYIELDING_CHECK)
    # Menu construction must neither spend a benefit nor arm one without damage.
    g["menu"]()
    assert g["stored_engine"]().state == before.state
    asked = []

    def choose_defense(prompt, choice):
        options = [option["id"] for option in choice["options"]]
        if "Athletics" in options:
            assert options == ["Athletics", "Acrobatics"]
            assert prompt["context"]["reactor_id"] == OWNER
            assert "Open-Hand Disarm" in prompt["moment"]
            asked.append(prompt)
            return [skill]
        return [options[0]]

    use(g, "Unarmed Strike (Iron Fist)", chooser=choose_defense, target=OWNER)
    engine = g["stored_engine"]()
    receipt = next(event.payload for event in reversed(engine.events)
                   if event.event_type == "CHECK_ROLLED" and event.source_definition_id == iron_open_hand.SOURCE)
    assert asked, "the manual defender must choose its printed skill"
    assert receipt["actor"]["mode"] == "NORMAL", "the initiating attack is not an ability check"
    expected = "ADVANTAGE" if benefit == "meridian" or skill == "Athletics" else "NORMAL"
    assert receipt["target"]["mode"] == expected
    assert receipt["success"] is (skill == "Acrobatics")
    defender = engine.state.actors[OWNER]
    if benefit == "meridian":
        assert not held(defender), "the actual defending check must spend Meridian before reload"
    else:
        assert any(event.event_type == "DAMAGE_COMMITTED" and OWNER in event.target_ids
                   and event.payload.get("hp_damage", 0) > 0 for event in engine.events)
        assert bool(defender.turn_flags.get(berserker.UNYIELDING_CHECK)) is (skill == "Acrobatics"), \
            "Unyielding is armed by the hit and spent only by Strength (Athletics)"
    assert held(engine.state.actors[FOE]), "the attacking side's Meridian must survive"
    assert receipt["target_check_kind"] == "check"
    assert receipt["target_ability"] == ("STR" if skill == "Athletics" else "DEX")
    assert receipt["target_skill"] == skill
    assert "skill" not in receipt and "ability" not in receipt, "do not label the attack as a check"

    use(g, "Followup Athletics checks", target=OWNER)
    engine = g["stored_engine"]()
    followups = [event.payload for event in engine.events if event.event_type == "CHECK_ROLLED"
                 and event.source_definition_id.startswith("action:test.a2r22.")]
    assert len(followups) == 2
    first = "ADVANTAGE" if benefit == "unyielding" and skill == "Acrobatics" else "NORMAL"
    assert [payload["target"]["mode"] for payload in followups] == [first, "NORMAL"]
    assert not held(engine.state.actors[OWNER])
    assert not engine.state.actors[OWNER].turn_flags.get(berserker.UNYIELDING_CHECK)
    assert held(engine.state.actors[FOE])
    assert engine.state.current_actor_id == FOE, "both followups precede expiry at a turn boundary"
    finish(g)

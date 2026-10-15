"""Equipment sphere printed-rule regressions (automation lane AUTO68, 2026-10-05).

The Equipment sphere's own automation (combat/ext/equipment_armor.py, the feature block in
combat/rules/feature_blocks.d/auto68_equipment.json, and the reviewed rows in
authority/typed_mechanics/reviewed_final.d/auto68_equipment.json) has to make the printed effects happen at the
table, not just compile. Each test drives the shipped ability through the live controller engine or the real
table service and checks the printed outcome; the table-level ones also reload the fight from disk, so the
printed state has to survive a save.

Owner text (APP/authority/typed_mechanics/rules_text.json) is the rule for every assertion here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import combat.factory_compiler as factory_compiler
from combat import typed_reactions
from combat.ext import equipment_armor
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, script
from tests.test_carry import KIT
from tests.test_zones import SHEET
from tests.r1i_service_support import force_ai_candidate
from tests.test_tabletop_hunt6 import HOLD, on_hold

T = "tianxia.talent.equipment."
KEY_MODIFIER = 2                                   # this sheet's Equipment key ability is CON 14
DEX_MODIFIER = 3                                   # DEX 16, so the unarmored calculation is 10 + Dexterity = 13
ARMORED_ITEMS = [{"item_id": "tianxia.mortal.armor.lacquered_lamellar", "name": "Lacquered Lamellar", "quantity": 1}]
BARE_ITEMS = [{"item_id": "tianxia.mortal.weapon.jian", "name": "Jian", "quantity": 1}]
SHIELD_ITEMS = BARE_ITEMS + [{"item_id": "tianxia.mortal.armor.shield", "name": "Shield", "quantity": 1}]
ATTACKER = "actor:factory.auto68-attacker"
DEFENDER = "actor:factory.auto68-defender"


def _authority() -> dict:
    return json.loads(Path(factory_compiler.TYPED_AUTHORITY).read_bytes())["mechanics"]


def _riders(mechanic_id: str) -> list[str]:
    return _authority()[mechanic_id].get("riders") or []


def _sheet(talents, *, items=None, cl=12, name="Iron Rain fighter", base_ac=10 + DEX_MODIFIER):
    scores = {"STR": 14, "DEX": 16, "CON": 14, "INT": 10, "WIS": 10, "CHA": 10}
    return {**SHEET,
            "proficiencies": {"armor": ["light", "medium", "heavy"]},
            "equipment": [{"starting_kit": {"items": list(items if items is not None else KIT["items"])}}],
            "identity": {**SHEET["identity"], "cultivation_level": cl, "display_name": name},
            "ability_scores_and_statistics": {
                **SHEET["ability_scores_and_statistics"],
                "abilities": [{"ability": a, "score": s, "modifier": (s - 10) // 2} for a, s in scores.items()],
                # A real sheet publishes the calculation it chose on its own (10 + Dexterity here, or a Path's own).
                "armor_class": {"base_value": base_ac},
                "primary_resource": {"name": "Qi", "maximum": 60},
            },
            "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.equipment"],
                                    "automatic_sphere_component_record_ids": [],
                                    "learned_talent_record_ids": [T + t for t in talents]}}


def _engine(talents, *, items=None, cl=12, seed="AUTO68", actor=DEFENDER, base_ac=10 + DEX_MODIFIER):
    """A live controller engine holding one Equipment fighter; every printed number is its own."""
    from combat.factory_compiler import compile_character
    from combat.gate2_runtime_content import AN
    from combat.gate4_engine import Gate4ControllerEngine

    bundle = compile_character(_sheet(talents, items=items, cl=cl, base_ac=base_ac), actor_id=actor)
    # These older damage fixtures begin with a trained, already-fitted suit.
    # Designation timing is independently tested through the native service.
    worn = next((i for i in bundle["carrying"]["items"] if i.get("worn") and i.get("armor_category")), None)
    if worn:
        bundle["armor_subject"].update(fitted_key=worn["key"], ready=1)
        _seal(bundle)
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [actor, AN],
                                                 "team_by_actor": {actor: "team:a", AN: "team:b"},
                                                 "starting_positions": {actor: {"x": 3, "y": 6},
                                                                        AN: {"x": 10, "y": 6}}})
    me = engine.state.actors[actor]
    me.maximum_hp = me.current_hp = 900
    return engine, me


def _effective_ac(engine, actor):
    """The Armor Class an attack on this creature actually rolls against (combat/gate2_engine._attack_defense)."""
    return actor.armor_class + engine._ac_modifier(actor)


def _taken(engine, actor, amount, kind):
    return typed_reactions.defend(engine, actor, amount, kind, None, None)


def _fall(engine, actor, squares=12, *, answer=None, dice=None):
    """A real launch and fall (combat/falling.displace). Every die reads 1 unless ``dice`` says otherwise; a 60-foot
    fall then rolls 6d6. ``answer`` puts a player at the table for the printed "may", so USE and DECLINE can be driven."""
    from combat import falling
    from tests.h1_support import script

    script(engine, list(dice) if dice else [1] * 60)
    asked = _answer_choices(engine, actor, answer) if answer is not None else []
    before = actor.current_hp
    falling.displace(engine, actor, squares, "test:launch")
    return before - actor.current_hp


def _answer_choices(engine, actor, answer):
    """Answer the fighter's own questions the way the table does: through the choice transport, with an active intent.

    Returns the list of requests the transport was asked with, so a test can read the prompt that reached the player."""
    from combat.gate2_runtime_models import ActionIntent, ReactionDecision

    asked = []

    def provider(request):
        asked.append(request)
        picked = answer(request.get("choice_trigger") or {})
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"],
                                selection="USE" if picked else "DECLINE", option_ids=tuple(picked or ())), None

    engine.set_reaction_provider(provider)
    end = next(c for c in engine.legal_candidates() if c.kind == "END_TURN")
    engine._active_intent = ActionIntent(intent_id="test:auto68-fall", decision_id=end.decision_id,
                                        candidate_id=end.candidate_id, state_version=end.state_version, actor_id=actor.entity_id)
    return asked


# ============================================================ Reinforced Robes: "AC equals 10 + Dexterity + key ability"
def test_reinforced_robes_is_an_alternate_calculation_not_a_bonus():
    """While you are wearing no armor and not using a shield, your AC equals 10 + your Dexterity modifier + your Equipment
    key ability modifier. A sheet's own unarmored calculation is 10 + Dexterity, so the printed calculation wins -- but it is
    a calculation, not a bonus (owner amendment R1), so it replaces rather than stacks and nothing is added on top."""
    engine, me = _engine(["reinforced_robes"], items=BARE_ITEMS)
    assert _effective_ac(engine, me) == 10 + DEX_MODIFIER + KEY_MODIFIER == 15
    assert me.armor_class == 15, "the calculation is chosen once, at compile time"
    assert engine._ac_modifier(me) == 0, "and is not also a bonus on every attack"


def test_reinforced_robes_never_stacks_on_a_paths_own_calculation():
    """Owner amendment R1: "Alternate AC calculations replace rather than stack. Use one applicable AC calculation." A
    fighter whose Path calculation is already 18 uses that one -- 10 + Dexterity + the key modifier would be 15."""
    engine, me = _engine(["reinforced_robes"], items=BARE_ITEMS, base_ac=18)
    assert _effective_ac(engine, me) == 18
    assert me.armor_class == 18
    assert engine._ac_modifier(me) == 0


def test_reinforced_robes_wins_when_its_own_calculation_is_the_higher_one():
    """One calculation is used, the best one: a sheet calculation of 13 is replaced by 10 + Dexterity + key modifier."""
    engine, me = _engine(["reinforced_robes"], items=BARE_ITEMS, base_ac=13)
    assert me.armor_class == 15
    assert _effective_ac(engine, me) == 15


def test_reinforced_robes_gives_nothing_while_wearing_armor():
    engine, me = _engine(["reinforced_robes"], items=ARMORED_ITEMS)
    assert _effective_ac(engine, me) == me.armor_class        # worn armour replaces the unarmored calculation
    assert engine._ac_modifier(me) == 0


def test_reinforced_robes_gives_nothing_while_using_a_shield():
    engine, me = _engine(["reinforced_robes"], items=SHIELD_ITEMS)
    assert engine._ac_modifier(me) == 0                      # the printed line says "not using a shield"
    assert _effective_ac(engine, me) == 10 + DEX_MODIFIER + 2  # the Shield's own +2 is in the compiled Armor Class


def test_reinforced_robes_does_nothing_for_a_character_without_it():
    engine, me = _engine([], items=BARE_ITEMS)
    assert engine._ac_modifier(me) == 0
    assert me.armor_class == 10 + DEX_MODIFIER


def test_the_alternate_calculation_is_not_a_defense_row_any_damage_can_use():
    """The row is a calculation, not a Bludgeoning/defence entry: it never appears in the ordinary damage defences."""
    engine, me = _engine(["reinforced_robes"], items=BARE_ITEMS)
    rows = [row for row in engine.typed_passive_rows[DEFENDER] if row.get("kind") == "ac_calculation"]
    assert len(rows) == 1, rows
    assert (rows[0]["ac_base"], rows[0]["ac_ability"], rows[0]["amount"]) == (10, "DEX", KEY_MODIFIER)
    from combat import typed_reactions

    found = typed_reactions._defenses(engine, me, "BLUDGEONING", None, None)
    assert found["reduction"] == 0 and not found["resist"] and not found["immune"]


# ============================== Padded Layers: falling and collision damage take twice the Proficiency Bonus
def test_padded_layers_takes_twice_the_proficiency_bonus_off_falling_damage():
    """While wearing armor you are proficient with, once per round when you take bludgeoning damage, you may reduce that
    damage by your Proficiency Bonus. If the damage comes from falling or collision with an object or surface, reduce the
    damage by twice your Proficiency Bonus instead."""
    engine, me = _engine(["padded_layers"], cl=18)
    row = next(r for r in engine.typed_passive_rows[DEFENDER] if r.get("feature_id") == T + "padded_layers")
    assert int(row["amount"]) == 4
    assert _fall(engine, me) == max(0, 6 - 2 * 4)
    assert any("Padded Layers" in str(event.payload.get("log") or "") for event in engine.events)


def test_padded_layers_falling_reduction_is_the_rounds_one_reduction():
    engine, me = _engine(["padded_layers"], cl=18)
    assert _taken(engine, me, 20, "BLUDGEONING") == 16       # ordinary bludgeoning: one Proficiency Bonus
    assert _taken(engine, me, 20, "BLUDGEONING") == 20        # spent for the round
    assert _fall(engine, me) == 6, "the round's one reduction is already spent"


def test_padded_layers_falling_reduction_is_offered_again_next_round():
    engine, me = _engine(["padded_layers"], cl=18)
    for round_number in (1, 2):
        engine.state.round_number = round_number
        assert _fall(engine, me) == max(0, 6 - 8)


def test_ordinary_bludgeoning_is_still_one_proficiency_bonus_once_a_round():
    engine, me = _engine(["padded_layers"], cl=18)
    assert _taken(engine, me, 20, "BLUDGEONING") == 16
    assert _taken(engine, me, 20, "SLASHING") == 20
    engine.state.round_number += 1
    assert _taken(engine, me, 20, "BLUDGEONING") == 16


def test_falling_reduction_is_inert_without_padded_layers():
    engine, me = _engine([], cl=18)
    assert _fall(engine, me) == 6


# ------------------------------------------------------- Padded Layers, falling: edge cases, consent, one reduction only
GRAND_SHELL = T + "mountain_pattern_grand_shell"
FALLING_PROMPT = "choice:needle.padded_layers_fall"


def _claim_gone(actor):
    assert equipment_armor.FALLING_CLAIM not in actor.turn_flags, actor.turn_flags.get(equipment_armor.FALLING_CLAIM)
    return True


def test_a_short_fall_spends_nothing_and_asks_nothing():
    """Below ten feet nothing is rolled, so there is no packet to answer: a 5-foot drop deals no damage and must not
    cost the round's reduction (review AUTO68 finding 3)."""
    engine, me = _engine(["padded_layers"], cl=18)
    assert _fall(engine, me, squares=1) == 0
    _claim_gone(me)
    assert equipment_armor.PADDED_ROUND_FLAG not in me.turn_flags
    assert _taken(engine, me, 20, "BLUDGEONING") == 16, "the round's one reduction is still there"


def test_a_protected_fall_spends_nothing():
    """A creature that cannot be hurt by falling damage rolls no packet either, so the round's reduction survives."""
    engine, me = _engine(["padded_layers"], cl=18)
    engine._apply_condition(me, "condition:typed.fall_damage_immune", "test:featherfall", DEFENDER, expires_on=None,
                            data={"fall_damage_immune": 1})
    assert _fall(engine, me) == 0
    _claim_gone(me)
    assert equipment_armor.PADDED_ROUND_FLAG not in me.turn_flags
    assert _taken(engine, me, 20, "BLUDGEONING") == 16


def test_a_later_fall_is_still_reduced_after_a_harmless_one():
    engine, me = _engine(["padded_layers"], cl=18)
    assert _fall(engine, me, squares=1) == 0
    assert _fall(engine, me) == max(0, 6 - 2 * 4), "no stale claim is left over from the harmless drop"


def test_a_declined_fall_spends_nothing():
    """The printed clause is a "may" its owner decides; declining leaves the ordinary once-per-round reduction."""
    engine, me = _engine(["padded_layers"], cl=18)
    taken = _fall(engine, me, answer=lambda prompt: None)
    assert taken == 6 - 4, "only the ordinary Bludgeoning reduction"
    _claim_gone(me)
    assert me.turn_flags.get(equipment_armor.PADDED_ROUND_FLAG) == engine.state.round_number
    assert _taken(engine, me, 20, "BLUDGEONING") == 20, "the round's one reduction was spent on the fall"


def test_the_offered_decline_button_is_a_refusal():
    """Checklist item 9 and review AUTO68r1 finding 1: "decline" is an offered answer in its own right, so it reaches the
    plug-in as ["decline"] rather than as no answer at all. Pressing the button must leave the ordinary one-Proficiency-Bonus
    reduction -- it cannot spend the round's use AND take twice the Proficiency Bonus off."""
    engine, me = _engine(["padded_layers"], cl=18)
    taken = _fall(engine, me, answer=lambda prompt: ["decline"])
    assert taken == 6 - 4, "the button that promises one Proficiency Bonus off took twice it"
    _claim_gone(me)
    assert me.turn_flags.get(equipment_armor.PADDED_ROUND_FLAG) == engine.state.round_number
    assert _taken(engine, me, 20, "BLUDGEONING") == 20, "the round's one reduction was spent on the fall"


def test_the_player_is_asked_with_the_ability_the_fall_and_the_creature():
    """Checklist item 9: the question names the ability, the triggering action and who it affects, and offers both answers."""
    engine, me = _engine(["padded_layers"], cl=18)
    asked = []
    _fall(engine, me, answer=lambda prompt: asked.append(prompt) or ["use"])
    assert len(asked) == 1, asked
    trigger = asked[0]
    text = json.dumps(trigger, ensure_ascii=False)
    assert "Padded Layers" in text and "falling" in text and me.display_name in text, text
    assert trigger["needle_options"] == ["use", "decline"] and trigger["allow_decline"] is True
    assert trigger["automatic"] is True, "an AI owner uses it without being asked"
    assert trigger["preferred"] == ["use"] and trigger["maximum"] == 1
    prompt = trigger["prompt"]
    assert "twice your Proficiency Bonus" in prompt and "once per round" in prompt
    assert trigger["labels"]["use"].startswith("Use it"), trigger["labels"]
    assert "tianxia" not in prompt and "choice:" not in prompt


def test_only_one_equipment_reduction_answers_a_fall():
    """Mountain-Pattern Grand Shell: "If another passive Equipment feature would also reduce the same damage, choose
    one". A 20-point fall with both talents takes 12 -- twice the Proficiency Bonus -- and spends one round allowance."""
    engine, me = _engine(["padded_layers", "mountain_pattern_grand_shell"], items=ARMORED_ITEMS, cl=18)
    grand_shell = [row for row in engine.typed_passive_rows[DEFENDER] if row.get("feature_id") == GRAND_SHELL
                   and row.get("kind") == "grand_shell"]
    assert int(grand_shell[0]["pb"]) == 4 and grand_shell[0]["armor"] in ("medium", "heavy")
    assert _fall(engine, me, squares=8, dice=[5] * 20) == 20 - 2 * 4
    _claim_gone(me)
    assert me.turn_flags.get(equipment_armor.PADDED_ROUND_FLAG) == engine.state.round_number
    assert _taken(engine, me, 20, "BLUDGEONING") == 16, "the Grand Shell answers the next packet: one reduction each"
    assert _taken(engine, me, 20, "BLUDGEONING") == 20, "and both round allowances are now spent"


def test_a_fighter_without_padded_layers_still_gets_the_grand_shell_on_a_fall():
    engine, me = _engine(["mountain_pattern_grand_shell"], items=ARMORED_ITEMS, cl=18)
    assert _fall(engine, me, squares=8, dice=[5] * 20) == 20 - 4
    assert _taken(engine, me, 20, "PIERCING") == 20, "the Grand Shell spent its own once-per-round reduction"


def test_a_fall_spent_on_other_bludgeoning_damage_takes_nothing():
    engine, me = _engine(["padded_layers"], cl=18)
    assert _taken(engine, me, 20, "BLUDGEONING") == 16
    assert _fall(engine, me) == 6, "the round's one reduction was already spent, as printed"
    _claim_gone(me)


@pytest.mark.parametrize("owner,answer,expected", [("player", lambda prompt: ["use"], 4),
                                                      ("player", lambda prompt: ["decline"], 8),
                                                      ("player", lambda prompt: None, 8),
                                                      ("ai", None, 4)],
                         ids=["player-uses-it", "player-picks-the-decline-option", "player-declines", "ai-uses-it"])
def test_a_fall_commits_reloads_and_keeps_the_spent_allowance(monkeypatch, tmp_path, owner, answer, expected):
    """A committed table action launches the fighter for real (combat/falling.displace), the fight is saved, and the
    reloaded fight keeps the printed state: the once-per-round allowance the fall spent, no claim left behind, and a later
    Bludgeoning packet in the same round answered with the full amount.

    A manual owner is asked for the printed "may"; both refusals are driven here -- picking the offered "decline" answer
    and answering nothing at all -- and both leave one Proficiency Bonus off the fall (review AUTO68r1 finding 1).  An AI
    owner answers for itself."""
    combat, table, mid = _table(tmp_path, ["padded_layers"], cl=18, turn=DEFENDER)
    before = _reload(tmp_path, mid).state.actors[DEFENDER]
    round_number = int(combat._load_session(mid).engine.state.round_number)

    def launch(engine):
        from combat import falling

        script(engine, [3] * 20)
        falling.displace(engine, engine.state.actors[DEFENDER], 8, "test:launch", intent=engine._active_intent)

    on_hold(monkeypatch, launch)
    if owner == "ai":
        force_ai_candidate(combat, mid, DEFENDER, _candidate(table, mid, HOLD))
    prompts = _commit(combat, table, mid, HOLD, actor=DEFENDER, answer=answer, auto=owner == "ai")
    if owner == "player":
        assert [prompt["context"]["reaction_source_id"] for prompt in prompts] == [FALLING_PROMPT], prompts
        prompt = prompts[0]
        # Checklist items 9 and 13: the window names the ability, the fall, the creature, both answers and the cost.
        assert prompt["reaction"] == "Padded Layers" and prompt["affected"] == before.display_name
        moment = prompt["moment"]
        assert "Padded Layers" in moment and "falling" in moment and before.display_name in moment
        assert "twice your Proficiency Bonus" in moment and "once per round" in moment
        assert [option["id"] for option in prompt["choice"]["options"]] == ["use", "decline"]
        assert "falling" in prompt["summary"].lower()
        assert "tianxia" not in json.dumps(prompts, ensure_ascii=False)
    else:
        assert prompts == [], "an AI owner is never asked"

    engine = _reload(tmp_path, mid)
    me = engine.state.actors[DEFENDER]
    fall = [event for event in engine.events if event.event_type == "PASSIVE_TRIGGERED"
            and int((event.payload or {}).get("fall_distance_ft") or 0) == 40]
    assert fall, "the committed action really launched and dropped the fighter"
    assert int(fall[-1].payload["damage_taken"]) == expected      # 4d6 = 12, less twice the Proficiency Bonus
    assert me.current_hp == before.current_hp - expected
    _claim_gone(me)
    assert me.turn_flags.get(equipment_armor.PADDED_ROUND_FLAG) == round_number
    assert _taken(engine, me, 20, "BLUDGEONING") == 20, "the round's one reduction was spent by the fall"
    engine.state.round_number = round_number + 1
    assert _taken(engine, me, 20, "BLUDGEONING") == 16, "and is offered again in the next round"


@pytest.mark.parametrize("picked,expected", [(["use"], 4), (["decline"], 8)], ids=["player-uses-it", "player-picks-decline"])
def test_a_player_owned_fall_during_an_ai_action_is_asked_and_honoured(monkeypatch, tmp_path, picked, expected):
    """Checklist item 9: a player-owned decision is asked on an AI actor's turn too, and the player's answer -- not the AI
    controller's -- is what the fall costs.

    The attacker runs on Local AI and holds position; the fall happens inside that committed action, while the fighter who
    falls is a Manual player on the other side.  Both answers are driven, so the offered "decline" button is honoured
    during somebody else's turn as well as on the fighter's own (review AUTO68r1 finding 1)."""
    combat, table, mid = _table(tmp_path, ["padded_layers"], cl=18, turn=ATTACKER)
    assert table.state(mid)["menu"]["actor_id"] == ATTACKER, "the AI acts first"
    opening = _reload(tmp_path, mid)
    before, attacker = opening.state.actors[DEFENDER], opening.state.actors[ATTACKER]
    round_number = int(opening.state.round_number)

    def launch(engine):
        from combat import falling

        script(engine, [3] * 20)
        falling.displace(engine, engine.state.actors[DEFENDER], 8, "test:launch", intent=engine._active_intent)

    on_hold(monkeypatch, launch)
    force_ai_candidate(combat, mid, ATTACKER, _candidate(table, mid, HOLD))
    prompts = _commit(combat, table, mid, HOLD, actor=ATTACKER, answer=lambda prompt: picked, auto=True)
    assert [prompt["context"]["reaction_source_id"] for prompt in prompts] == [FALLING_PROMPT], prompts
    assert prompts[0]["context"]["reactor_id"] == DEFENDER, "the falling fighter is asked, not the acting AI"
    assert prompts[0]["trigger_actor"] == attacker.display_name, "and the question names the AI that caused the fall"

    engine = _reload(tmp_path, mid)
    me = engine.state.actors[DEFENDER]
    fall = [event for event in engine.events if event.event_type == "PASSIVE_TRIGGERED"
            and int((event.payload or {}).get("fall_distance_ft") or 0) == 40]
    assert fall, "the AI's committed action really launched and dropped the player"
    assert int(fall[-1].payload["damage_taken"]) == expected      # 4d6 = 12, less twice the Proficiency Bonus
    assert me.current_hp == before.current_hp - expected
    _claim_gone(me)
    assert me.turn_flags.get(equipment_armor.PADDED_ROUND_FLAG) == round_number
    assert _taken(engine, me, 20, "BLUDGEONING") == 20, "the round's one reduction was spent by the fall"


def test_circuit_armor_survives_a_table_commit_and_reload(tmp_path):
    """The Equipment plug-in's own fight state has to come back off disk: the awake circuit is a condition the fight
    records, and the once-per-round reductions read the recorded round."""
    combat, table, mid = _table(tmp_path, ["circuit_armor"], cl=12, turn=DEFENDER)
    _commit(combat, table, mid, "tianxia.talent.equipment.circuit_armor", actor=DEFENDER)
    engine = _reload(tmp_path, mid)
    me = engine.state.actors[DEFENDER]
    assert any(c.condition_id == equipment_armor.CIRCUIT for c in me.conditions.values())
    assert _taken(engine, me, 10, "FIRE") == 10 - KEY_MODIFIER
    assert _taken(engine, me, 10, "FIRE") == 10, "once per round"


# ======================================================= Iron Rain Readiness: a Reaction on a ranged hit and a DEX save
RANGED = "action:test.auto68.ranged"
AREA = "action:test.auto68.area"


def _bundle_action(bundle, source, display_name, parameters, **overrides):
    action = dict(bundle["action_catalog"][0])
    action.update(source_definition_id=source, display_name=display_name, economy="ACTION", costs=[], **overrides)
    action["parameters"] = parameters
    bundle["action_catalog"].append(action)
    bundle["actor_template"]["action_ids"].append(source)


def _seal(bundle):
    from combat.canonical import canonical_sha256

    bundle.pop("bundle_sha256", None)
    bundle["bundle_sha256"] = canonical_sha256(bundle)


def _ranged_attack(bundle):
    """A synthetic 1d10 piercing ranged attack by the attacker: one action, no resource, no rider."""
    if bundle["actor_id"] != ATTACKER:
        return
    _bundle_action(bundle, RANGED, "Test Ranged Shot",
                   {"expected_damage": 10, "typed": {
                       "numbers": {"cl": 18, "pb": 4, "save_dc": 100, "attack_bonus": 100},
                       # A ranged attack reports its range in the typed payload (a melee swing reports none).
                       "range_ft": 60,
                       "effects": [{"type": "attack", "attack_kind": "weapon", "on_hit": [
                           {"type": "damage", "dice": {"count": 1, "sides": 10, "bonus": 0}, "damage_types": ["piercing"]}]}],
                       "duration": {"kind": "instant"}, "riders": []}},
                   target_kind="HOSTILE_ENTITY", range_ft=60, reach_ft=None)
    _seal(bundle)


def _area_save(bundle):
    """A synthetic area effect on a chosen square: 1d6 Force on a failed Dexterity save, with no attack roll at all."""
    if bundle["actor_id"] != ATTACKER:
        return
    _bundle_action(bundle, AREA, "Test Burning Field",
                   {"expected_damage": 6, "any_cell": True, "typed": {
                       "numbers": {"cl": 18, "pb": 4, "save_dc": 8, "attack_bonus": 100},
                       "effects": [{"type": "area", "applies_to": "creatures_in_area", "shape": {"kind": "burst", "size_ft": 20},
                                    "save": {"type": "save", "applies_to": "creatures_in_area", "ability": "dex", "dc": 8,
                                             "on_fail": [{"type": "damage", "applies_to": "target",
                                                          "dice": {"count": 1, "sides": 6, "bonus": 0},
                                                          "damage_types": ["force"]}], "on_success": []}}],
                       "duration": {"kind": "instant"}, "riders": []}},
                   target_kind="CELL", range_ft=60)
    _seal(bundle)


def _table(tmp_path, talents, *, prepare=None, cl=18, turn=ATTACKER):
    from combat.factory_compiler import compile_character
    from combat.tabletop_service import TabletopService
    from tests.test_lock2_persistence import act

    bundles = []
    documents = {}
    for aid in (ATTACKER, DEFENDER):
        document = _sheet(talents if aid == DEFENDER else [], cl=cl,
                          name="Ranged attacker" if aid == ATTACKER else "Iron Rain fighter")
        documents[aid.removeprefix("actor:factory.")] = document
        bundle = compile_character(document, actor_id=aid, reaction_plan={"mode": "ask", "ask": aid == DEFENDER})
        if prepare:
            prepare(bundle)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    combat._factory_owner_sheet = lambda project: documents[project]
    for bundle in bundles:
        worn = next((i for i in bundle["carrying"]["items"] if i.get("worn") and i.get("armor_category")), None)
        if worn:
            project = bundle["actor_id"].removeprefix("actor:factory.")
            combat.character_preparation(project, "armor.fit.start", parameters={"item_key": worn["key"]})
            combat.character_preparation(project, "time.advance", parameters={"seconds": 600, "observation": "fitting"}, expected_revision=1)
    mid = combat._finish_factory_match(bundles, [ATTACKER, DEFENDER],
                                       {ATTACKER: "team:opponents", DEFENDER: "team:factory"},
                                       {ATTACKER: {"x": 8, "y": 6}, DEFENDER: {"x": 3, "y": 6}},
                                       combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [DEFENDER], [ATTACKER],
                                       control_modes={ATTACKER: "MANUAL", DEFENDER: "MANUAL"}, match_seed="AUTO68",
                                       display_name="AUTO68 regression", maximum_rounds=6)["match_id"]
    table = TabletopService(combat, tmp_path)
    while table.state(mid)["menu"]["actor_id"] != turn:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid


def _reload(tmp_path, mid):
    """The fight as it comes back off disk, with its own replay check run."""
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"
    return loaded.engine


def _candidate(table, mid, source):
    """The candidate id the table offers for a named action on the actor whose turn it is."""
    menu = table.state(mid)["menu"]
    cid = next((o["candidate_id"] for g in menu["actions"] for o in g["options"]
                if g["source_definition_id"] == source or g["source_definition_id"].endswith("." + source)), None)
    if cid is None:
        raise AssertionError(f"{source} was not offered; menu: {[g['source_definition_id'] for g in menu['actions']]}")
    return cid


def _commit(combat, table, mid, source, *, actor=ATTACKER, selection="USE", answer=None, auto=False, max_steps=8):
    """Play ``actor``'s named action through the table, answering every window it opens.

    ``answer(prompt)`` returns the option ids to pick (None declines), so a test can drive a printed "may"; without it
    every Ask-me Reaction window is answered with ``selection``.  ``auto`` drives an automatic owner through the table's
    own step, which is how the AI decides for itself."""
    from tests.test_lock2_persistence import act

    given = []
    prompts = []
    for _ in range(max_steps):
        state = table.state(mid)
        menu = state["menu"]
        if not auto and menu["actor_id"] != actor:
            assert act(table, mid, "end")["status"] == "COMMITTED"
            continue
        if auto:
            cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
                       if c.source_definition_id == source)
            result = table.auto_step(mid, state["last_sequence"], list(given))
        else:
            cid = _candidate(table, mid, source)
            result = table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], list(given))
        if result["status"] == "REACTION_REQUIRED":
            prompt = result["reaction"]
            prompts.append(prompt)
            picked = answer(prompt) if answer is not None else None
            given.append({**prompt["context"], "selection": "DECLINE" if (answer is not None and not picked) else selection,
                          "option_ids": list(picked or [])})
            continue
        assert result["status"] == "COMMITTED", result["status"]
        return prompts
    raise AssertionError("the action was never offered")


def _packets(engine, source):
    return [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == source]


def test_iron_rain_readiness_reduces_a_ranged_hit_by_2d8_plus_proficiency_bonus(tmp_path):
    """When you are hit by a ranged attack ... you may use your Reaction and spend 2 CP. Roll 2d8 + your Proficiency Bonus.
    Reduce the triggering damage by the result."""
    combat, table, mid = _table(tmp_path, ["iron_rain_readiness"], prepare=_ranged_attack)
    _commit(combat, table, mid, RANGED)
    engine = _reload(tmp_path, mid)
    packets = _packets(engine, RANGED)
    assert len(packets) == 1, [e.event_type for e in engine.events]
    rolled = int(packets[0].payload["rolled_or_pending_damage"])
    assert int(packets[0].payload["hp_damage"]) == max(0, rolled - 12), packets[0].payload
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == T + "iron_rain_readiness"
               for e in engine.events)


def test_iron_rain_readiness_spends_two_qi_and_the_reaction(tmp_path):
    combat, table, mid = _table(tmp_path, ["iron_rain_readiness"], prepare=_ranged_attack)
    before = _reload(tmp_path, mid).state.actors[DEFENDER]
    qi_before = int(before.resources.get("resource:core.qi", 0))
    assert qi_before and before.reaction_available
    _commit(combat, table, mid, RANGED)
    me = _reload(tmp_path, mid).state.actors[DEFENDER]
    assert int(me.resources.get("resource:core.qi", 0)) == qi_before - 2
    assert not me.reaction_available


def test_iron_rain_readiness_can_be_declined(tmp_path):
    combat, table, mid = _table(tmp_path, ["iron_rain_readiness"], prepare=_ranged_attack)
    _commit(combat, table, mid, RANGED, selection="DECLINE")
    engine = _reload(tmp_path, mid)
    packets = _packets(engine, RANGED)
    assert int(packets[0].payload["hp_damage"]) == int(packets[0].payload["rolled_or_pending_damage"])
    assert not _packets(engine, T + "iron_rain_readiness")


def test_iron_rain_readiness_does_nothing_to_a_fighter_without_it(tmp_path):
    combat, table, mid = _table(tmp_path, [], prepare=_ranged_attack)
    _commit(combat, table, mid, RANGED)
    engine = _reload(tmp_path, mid)
    packets = _packets(engine, RANGED)
    assert int(packets[0].payload["hp_damage"]) == int(packets[0].payload["rolled_or_pending_damage"])
    assert int(_reload(tmp_path, mid).state.actors[DEFENDER].resources.get("resource:core.qi", 0)) == 60


# ==================================================== retired riders: printed limitations the table already settles
@pytest.mark.parametrize("mechanic_id", [
    T + "circuit_armor",
    T + "field_maintenance",
    T + "hidden_brigandine_assassin_robe",
    T + "padded_layers",
    T + "reinforced_robes",
    T + "soul_sealed_armor",
    T + "quick_harness",
    T + "sleep_in_armor",
    T + "underplate_channels",
    T + "armor_answers_the_soul",
    T + "instant_harness",
    T + "armor_training",
    T + "shield_training",
])
def test_retired_equipment_riders_are_gone(mechanic_id):
    """Each of these printed lines is either run by the engine or is a printed limitation or a build-time choice; none of
    them is left as a reminder in a fight. The printed text itself stays available on hover."""
    assert _riders(mechanic_id) == [], _riders(mechanic_id)


@pytest.mark.parametrize("mechanic_id,printed", [
    (T + "hidden_plates", "Intelligence (Investigation) check"),
])
def test_hidden_plates_manual_search_rider_retired_after_automation(mechanic_id, printed):
    """The old manual rider is retired; native searches execute the printed check.

    Actual target DC, Investigation dice and touch Advantage are tested through
    the table and cold replay in test_mgr_t14_armor_consumers.
    """
    assert _riders(mechanic_id) == []
    bundle = factory_compiler.compile_character(_sheet(["hidden_plates"]), actor_id=DEFENDER)
    searches = [a for a in bundle["action_catalog"] if ".armor_search." in a["source_definition_id"]]
    assert len(searches) == 2
    assert all(a["parameters"]["typed"]["effects"][0]["type"] == "equipment_armor_search" for a in searches)


def test_iron_rain_area_save_reminder_retired_after_automation():
    assert _authority()[T + "iron_rain_readiness"]["coverage"] == "FULL"
    assert _riders(T + "iron_rain_readiness") == []


@pytest.mark.parametrize("mechanic_id", [
    T + "ancestral_battle_dress", T + "beast_hide_harness_scripture", T + "black_armor_legion_scripture",
    T + "helmet_discipline", T + "mountain_pattern_grand_shell", T + "mountain_pattern_shell", T + "sure_harness",
    T + "ancestral_battle_dress_scripture", T + "armor_ease", T + "beast_hide_harness_scripture",
    T + "brigandine_robe_scripture", T + "breath_aligned_armor", T + "lamellar_flow",
    T + "mingguang_bright_armor_scripture", T + "mirror_bright_armor", T + "mountain_pattern_grand_shell",
    T + "qi_conductive_lacing", T + "walking_fortress_scripture",
])
def test_already_automated_equipment_talents_stay_typed(mechanic_id):
    assert _authority()[mechanic_id]["coverage"] == "FULL", _authority()[mechanic_id].get("riders")

"""Real-character regressions for the source-bound Path/Tradition rider lane."""
import copy
import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

from combat import typed_executor
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position, ReactionDecision
from combat.gate4_engine import Gate4ControllerEngine

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.riders13"
PREFIX = "tianxia.subpath.body.adamant_thunderbolt_body.feature."


@lru_cache(maxsize=1)
def authority():
    if os.environ.get("R13_AUTHORITY_COMMIT"):
        return json.loads(subprocess.check_output(["git", "show", os.environ["R13_AUTHORITY_COMMIT"] +
                         ":APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json"], cwd=ROOT))
    if os.environ.get("R13_OLD_TYPING") == "1":
        return json.loads(subprocess.check_output(["git", "show", "793a9a89:APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json"], cwd=ROOT))
    return json.loads(Path(os.environ.get("R13_AUTHORITY", ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json")).read_text())


def bundle(ids, cl=10, dc=50, actor_id=ME, items=(), ability_mods=None):
    mods = {a: 2 for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}
    mods.update(ability_mods or {})
    sheet = {
        "identity": {"proficiency_bonus": 4, "cultivation_level": cl, "path": "Body Refining", "key_ability": "CON"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 10 + 2 * value, "modifier": value} for a, value in mods.items()],
            "primary_resource": {"name": "Stamina", "maximum": 60}, "armor_class": {"base_value": 14},
            "hit_points": {"maximum": 80}, "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 8},
        "path_and_subpath": {"path_feature_record_ids": list(ids)},
        "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.iron_fist"],
                              "automatic_sphere_component_record_ids": ["TAL_IRON_FIST_IRON_FIST_TRAINING"]},
        "equipment": [{"starting_kit": {"items": [{"item_id": item} for item in items]}}],
    }
    return compile_character(sheet, actor_id=actor_id, typed_authority=authority())


def engine(ids, cl=10, dc=50, enemy_typed=False, items=(), ability_mods=None):
    bundles = (bundle(ids, cl, dc, items=items, ability_mods=ability_mods),) + ((bundle([], actor_id=AN),) if enemy_typed else ())
    fight = Gate4ControllerEngine(ROOT, match_seed="R13", typed_bundles=bundles,
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    fight.state.current_slot_index = fight.state.initiative_order.index(ME)
    fight.state.current_actor_id = ME
    fight._system_start_turn()
    fight.state.actors[AN].armor_class = -50
    fight.state.actors[AN].maximum_hp = 1000
    fight.state.actors[AN].current_hp = 1000
    return fight


def use(fight, name, target=AN, actor_id=ME):
    me = fight.state.actors[actor_id]
    me.action_available = me.bonus_action_available = True
    candidate = next(c for c in fight.legal_candidates() if c.display_name == name and (not target or not c.target_ids or target in c.target_ids))
    start = len(fight.events)
    fight.execute_intent(ActionIntent(intent_id=f"r13-{start}", decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=actor_id,
        target_ids=candidate.target_ids, destination=candidate.destination))
    return fight.events[start:]


def attack_name(fight):
    return next(a.display_name for a in fight.action_catalog.values() if a.owner_id == ME and a.economy.value == "ACTION"
                and any(e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                        for e in (a.parameters.get("typed") or {}).get("effects") or []))


def answers(fight, selections):
    def provider(request):
        spec = request.get("extension_choice")
        if spec is None:
            return None, None
        chosen = next((value for suffix, value in selections.items() if request["reaction_source_id"].endswith(suffix)),
                      spec["option_ids"][:spec["minimum_selections"]])
        base = {key: request[key] for key in ("checkpoint", "reactor_id", "reaction_source_id")}
        return ReactionDecision(**base, selection="DECLINE" if chosen is None else "USE", option_ids=tuple(chosen or [])), None
    fight.set_reaction_provider(provider)


def packet(fight, amount, damage_type):
    """Commit one hostile packet with an active intent, as the typed damage path does."""
    candidate = next(c for c in fight.legal_candidates() if c.display_name == attack_name(fight))
    intent = ActionIntent(intent_id=f"packet-{len(fight.events)}", decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=AN, target_ids=(ME,))
    fight._typed_pending_damage_type = damage_type
    fight._active_intent = intent
    try:
        return fight._commit_damage(fight.state.actors[ME], amount, damage_type, source_definition_id="test:hostile",
                                   source_actor_id=AN, intent=intent, reaction_depth=0)
    finally:
        fight._active_intent = None


def test_adamant_can_decline_a_hit_rider_without_spending():
    fight = engine([PREFIX + "adamant_frame"])
    me = fight.state.actors[ME]
    fight._gain_resource(me, "resource:named.thunder_charge", 4, "test")
    answers(fight, {"adamant_frame": None})
    use(fight, attack_name(fight))
    assert me.resources["resource:named.thunder_charge"] == 4


def test_adamant_next_save_bonus_is_consumed_by_one_str_or_con_save():
    fight = engine([PREFIX + "adamant_frame"])
    me = fight.state.actors[ME]
    fight._gain_resource(me, "resource:named.thunder_charge", 4, "test")
    answers(fight, {"adamant_frame": ["Next Strength or Constitution Save"]})
    use(fight, attack_name(fight))
    action = next(a for a in fight.action_catalog.values() if a.display_name == attack_name(fight))
    ctx = typed_executor.Context(fight, fight.state.actors[AN], action, None,
                                 {"numbers": {"pb": 4, "save_dc": 16}}, [me], me, {})
    for ability, wanted in (("dex", 16), ("con", 12), ("str", 16)):
        typed_executor.block_save(ctx, {"type": "save", "ability": ability, "on_fail": [], "on_success": []})
        assert next(e for e in reversed(fight.events) if e.event_type == "SAVE_ROLLED").payload["dc"] == wanted


@pytest.mark.parametrize("dc,selected", [(50, ["No Reactions", "Reduce AC"]), (-40, ["Reduce AC"])])
def test_knuckle_chooses_two_on_failure_one_on_success_and_ac_does_not_stack(dc, selected, monkeypatch):
    fight = engine([PREFIX + "heaven_breaking_knuckle"], dc=dc)
    me, foe = fight.state.actors[ME], fight.state.actors[AN]
    fight._gain_resource(me, "resource:named.thunder_charge", 4, "test")
    answers(fight, {"path_results.heaven_breaking_knuckle": selected})
    from tests.h1_support import script
    script(fight, [18, *([1] * 60)])  # control the save rather than the sheet DC overridden by attack mastery
    original_save = fight._roll_save

    def save(*args, **kwargs):
        script(fight, [1 if dc > 0 else 20])
        return original_save(*args, **kwargs)

    monkeypatch.setattr(fight, "_roll_save", save)
    use(fight, attack_name(fight))
    from combat import ext
    assert sum(ext.run("ac", fight, foe)) == -2
    assert me.resources["resource:named.thunder_charge"] == 2
    assert me.resources["resource:core.stamina"] == 58
    held = [c for c in foe.conditions.values() if c.condition_id.endswith("reaction_denied")]
    assert bool(held) is (dc == 50)
    fight.state.round_number += 1
    use(fight, attack_name(fight))
    assert sum(ext.run("ac", fight, foe)) == -2


@pytest.mark.parametrize("cl,count", [(3, 1), (11, 2), (17, 3)])
def test_adamant_added_damage_scales_and_costs_one_charge_once_per_turn(cl, count):
    fight = engine([PREFIX + "adamant_frame"], cl)
    me = fight.state.actors[ME]
    fight._gain_resource(me, "resource:named.thunder_charge", 4, "test")
    events = use(fight, attack_name(fight))
    rolls = [e for e in events if e.event_type == "DAMAGE_ROLLED" and e.payload.get("expression") == f"{count}d8+0"]
    # The ordinary weapon packet is resolved by the locked attack path; this is the paid extra damage roll.
    assert rolls and len(rolls[-1].payload["dice"]) == count
    assert me.resources["resource:named.thunder_charge"] == 3
    fight.state.actors[AN].position = Position(x=4, y=6)
    use(fight, attack_name(fight))
    assert me.resources["resource:named.thunder_charge"] == 3


def test_adamant_unarmed_damage_chooses_an_unresisted_type_without_spending():
    fight = engine([PREFIX + "adamant_frame"])
    foe = fight.state.actors[AN]
    fight._add_modifier(foe, "test", "damage_resistance", "SET", "BLUDGEONING", "ALWAYS", expires_on="UNTIL_REMOVED")
    events = use(fight, attack_name(fight))
    assert any(e.event_type == "DAMAGE_COMMITTED" and e.payload.get("damage_type") == "FORCE" for e in events)
    assert fight.state.actors[ME].resources["resource:named.thunder_charge"] == 0


def test_unbroken_bolt_ignores_resistance_on_unarmed_but_never_immunity():
    fight = engine([PREFIX + "body_of_the_unbroken_bolt"])
    foe = fight.state.actors[AN]
    action = next(a for a in fight.action_catalog.values() if a.display_name == attack_name(fight))
    typed = action.parameters["typed"]
    from combat import typed_reactions
    fight._add_modifier(foe, "test", "damage_resistance", "SET", "BLUDGEONING", "ALWAYS", expires_on="UNTIL_REMOVED")
    assert typed_reactions.defend(fight, foe, 20, "BLUDGEONING", action.source_definition_id, ME) == 20
    fight._add_modifier(foe, "test2", "damage_immunity", "SET", "BLUDGEONING", "ALWAYS", expires_on="UNTIL_REMOVED")
    assert typed_reactions.defend(fight, foe, 20, "BLUDGEONING", action.source_definition_id, ME) == 0


def test_unbroken_bolt_miss_charge_is_gained_once_per_round_on_typed_misses():
    # Rider lane C7 (2026-09-30): the printed "Once per round when a hostile creature within reach misses you with a melee
    # attack, gain 1 Thunder Charge" is now automated for typed attacks (combat/ext/thunder_charges.py); this test asserted
    # the earlier GM deferral (0 Charges) and now asserts the printed rule.
    fight = engine([PREFIX + "body_of_the_unbroken_bolt"])
    me = fight.state.actors[ME]
    foe = fight.state.actors[AN]
    action = next(a for a in fight.action_catalog.values() if a.display_name == attack_name(fight))
    ctx = typed_executor.Context(fight, foe, action, None, action.parameters["typed"], [me], me)
    me.armor_class = 1000
    typed_executor.block_attack(ctx, {"type": "attack", "attack_kind": "unarmed", "no_damage": True})
    assert me.resources["resource:named.thunder_charge"] == 1
    typed_executor.block_attack(ctx, {"type": "attack", "attack_kind": "unarmed", "no_damage": True})
    assert me.resources["resource:named.thunder_charge"] == 1
    fight._append_event("ROUND_STARTED", "test:next-round",
                        payload={"round": fight.state.round_number + 1})
    typed_executor.block_attack(ctx, {"type": "attack", "attack_kind": "unarmed", "no_damage": True})
    assert me.resources["resource:named.thunder_charge"] == 2
    gains = [e for e in fight.events if e.event_type == "RESOURCE_GAINED"
             and e.actor_id == ME and e.payload.get("resource_id") == "resource:named.thunder_charge"]
    assert len(gains) == 2 and all(e.payload["gained"] == 1 for e in gains)
    assert all(e.source_definition_id == PREFIX + "body_of_the_unbroken_bolt" for e in gains)


def test_unbroken_bolt_does_not_gain_on_ranged_or_allied_misses():
    fight = engine([PREFIX + "body_of_the_unbroken_bolt"])
    me, foe = fight.state.actors[ME], fight.state.actors[AN]
    action = next(a for a in fight.action_catalog.values() if a.display_name == attack_name(fight))
    from combat import ext
    typed = {**action.parameters["typed"], "range_ft": 30}
    ext.run("after_miss", typed_executor.Context(fight, foe, action, None, typed, [me], me), me)
    foe.team_id = me.team_id
    ext.run("after_miss", typed_executor.Context(fight, foe, action, None, action.parameters["typed"], [me], me), me)
    assert me.resources["resource:named.thunder_charge"] == 0


def test_unbroken_bolt_is_immune_to_deafened_and_has_advantage_against_stunned():
    fight = engine([PREFIX + "body_of_the_unbroken_bolt"])
    me = fight.state.actors[ME]
    action = next(a for a in fight.action_catalog.values() if a.display_name == attack_name(fight))
    ctx = typed_executor.Context(fight, fight.state.actors[AN], action, None,
                                 {"numbers": {"pb": 4, "save_dc": -40}}, [me], me, {})
    typed_executor.block_condition(ctx, {"type": "condition", "condition": "deafened", "applies_to": "target"})
    assert not any(c.condition_id.endswith("deafened") for c in me.conditions.values())
    typed_executor.block_save(ctx, {"type": "save", "ability": "con", "on_fail": [
        {"type": "condition", "condition": "stunned", "applies_to": "target"}], "on_success": []})
    event = next(e for e in reversed(fight.events) if e.event_type == "SAVE_ROLLED")
    assert event.payload["mode"] == "ADVANTAGE"


@pytest.mark.parametrize("amount,gained", [(1, 1), (100, 0)])
def test_thunder_bone_only_grants_followups_when_the_packet_is_fully_absorbed(amount, gained):
    fight = engine([PREFIX + "thunder_runs_through_bone"])
    me, foe = fight.state.actors[ME], fight.state.actors[AN]
    start = me.position
    before = me.current_hp
    packet(fight, amount, "THUNDER")
    assert me.resources["resource:core.stamina"] == 59
    assert not me.reaction_available
    # Rider lane C7 (2026-09-30): the Subpath's Thunder Charge record ("Gain 1 after ... taking hostile Lightning, Thunder, or
    # Force damage", combat/ext/subpath_pools.py) now grants the normal Charge when the packet gets through; fully absorbed,
    # the Charge is Thunder Runs Through Bone's own. Either way one Charge -- the follow-ups below tell them apart.
    assert me.resources["resource:named.thunder_charge"] == 1
    assert (me.current_hp == before) is bool(gained)
    assert (me.position != start) is bool(gained)
    assert any(c.condition_id == "condition:typed.path_next_unarmed" for c in me.conditions.values()) is bool(gained)


def test_thunder_bone_does_not_answer_psychic_damage():
    fight = engine([PREFIX + "thunder_runs_through_bone"])
    me = fight.state.actors[ME]
    packet(fight, 1, "PSYCHIC")
    assert me.resources["resource:core.stamina"] == 60
    assert me.reaction_available


@pytest.mark.parametrize("own_turn", [True, False])
def test_thunder_bone_pending_unarmed_advantage_expires_at_end_of_next_turn(own_turn):
    fight = engine([PREFIX + "thunder_runs_through_bone"], enemy_typed=True)
    me = fight.state.actors[ME]
    if not own_turn:
        fight.end_turn()
        assert fight.state.current_actor_id == AN
    packet(fight, 1, "THUNDER")
    def held():
        return any(c.condition_id == "condition:typed.path_next_unarmed" for c in me.conditions.values())
    assert held()
    if own_turn:
        fight.end_turn()
        assert held(), "must survive the current turn's end"
    fight.end_turn()
    assert fight.state.current_actor_id == ME and held(), "must survive the next turn's start"
    fight.end_turn()
    assert not held(), "unused Advantage must expire at the end of that next turn"


def test_knuckle_ends_one_represented_temporary_ac_defense_after_a_failed_save():
    fight = engine([PREFIX + "heaven_breaking_knuckle"])
    me, foe = fight.state.actors[ME], fight.state.actors[AN]
    action = next(a for a in fight.action_catalog.values() if a.display_name == attack_name(fight))
    ward = action.model_copy(update={"source_definition_id": "test:ward", "owner_id": AN,
        "parameters": {"typed": {"duration": {"kind": "minutes", "amount": 1}, "numbers": {"cl": 3}}}})
    fight.action_catalog[ward.source_definition_id] = ward
    fight.state.current_actor_id = AN
    fight._add_modifier(foe, ward.source_definition_id, "armor_class", "ADD", 2, "ALWAYS", expires_on="UNTIL_REMOVED")
    fight.state.current_actor_id = ME
    fight._gain_resource(me, "resource:named.thunder_charge", 4, "test")
    answers(fight, {"path_results.heaven_breaking_knuckle": ["End Defense", "Reduce AC"]})
    from tests.h1_support import script
    script(fight, [18, *([1] * 60)])
    use(fight, attack_name(fight))
    assert not any(m.source_definition_id == ward.source_definition_id for m in foe.modifiers.values())


THORN = "tianxia.subpath.body.black_thorn_demon_body.feature."


@pytest.mark.parametrize("success", [False, True])
def test_impaling_garden_offers_a_strength_action_escape_and_keeps_other_sources(success):
    fight = engine([THORN + "impaling_garden"], enemy_typed=True)
    me, foe = fight.state.actors[ME], fight.state.actors[AN]
    fight._gain_resource(me, "resource:named.demon_spine", 2, "test")
    use(fight, "Impaling Garden", None)
    assert me.resources["resource:core.stamina"] == 57
    assert me.resources["resource:named.demon_spine"] == 0
    held = next(c for c in foe.conditions.values() if c.condition_id == "condition:typed.restrained")
    assert held.data["action_escape"] == {"ability": "str", "dc": 50}
    if success:
        # Force the success branch while retaining the actual source's escape data shape.
        held.data["action_escape"]["dc"] = -40
    fight._apply_condition(foe, "condition:typed.restrained", "test:other_restraint", ME, expires_on="UNTIL_REMOVED")
    fight.state.current_actor_id = AN
    fight.state.current_slot_index = fight.state.initiative_order.index(AN)
    fight._system_start_turn()
    events = use(fight, "Escape source restraint", AN, actor_id=AN)
    check = next(e.payload for e in events if e.event_type == "CHECK_ROLLED")
    assert check["success"] is success and check["ability"] == "STR"
    assert check["actor"]["modifier"] == 2  # an ability check, without saving throw/skill proficiency
    assert not foe.action_available
    assert any(c.condition_id == "condition:typed.restrained" and c.source_definition_id == "test:other_restraint"
               for c in foe.conditions.values())
    assert any(c.instance_id == held.instance_id for c in foe.conditions.values()) is not success


@pytest.mark.parametrize("grappling", [False, True])
def test_spines_answer_violence_pushes_only_an_attacker_that_is_not_grappling_you(grappling):
    from combat import typed_reactions
    fight = engine([THORN + "spines_answer_violence"])
    me, foe = fight.state.actors[ME], fight.state.actors[AN]
    start = foe.position
    if grappling:
        fight._apply_condition(me, "condition:typed.grappled", "test:grapple", AN, expires_on="UNTIL_REMOVED")
    row = next(r for r in fight.typed_reaction_rows[ME] if r.get("feature_id") == THORN + "spines_answer_violence")
    typed_reactions._run_generic_effects(fight, me, foe, row, row["effects"])
    assert (foe.position != start) is not grappling
    assert any(c.condition_id.endswith("bleeding") for c in foe.conditions.values())


def thorn_fight():
    fight = engine([THORN + "thorn_flesh_armory"], enemy_typed=True)
    fight._gain_resource(fight.state.actors[ME], "resource:named.demon_spine", 4, "test")
    use(fight, attack_name(fight))
    assert any(c.condition_id.endswith("bleeding") and c.data.get("thorn_bleeding")
               for c in fight.state.actors[AN].conditions.values())
    fight.state.current_actor_id = AN
    fight.state.current_slot_index = fight.state.initiative_order.index(AN)
    fight._system_start_turn()
    fight.state.actors[ME].reaction_available = False
    return fight


def move(fight, destination):
    candidate = next(c for c in fight.legal_candidates() if c.kind.value == "MOVE" and c.destination == destination)
    fight.execute_intent(ActionIntent(intent_id=f"move-{len(fight.events)}", decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=AN,
        target_ids=candidate.target_ids, destination=candidate.destination))


def test_thorn_bleeding_counts_two_willing_five_foot_moves_and_emits_one_gm_packet():
    fight = thorn_fight()
    foe = fight.state.actors[AN]
    before = foe.current_hp
    move(fight, Position(x=5, y=6))
    assert foe.current_hp == before
    move(fight, Position(x=6, y=6))
    # Owner integration directive: event-hook damage cannot bypass downstream
    # riders; retain the exact packet as a GM line until the lock-round seam.
    assert foe.current_hp == before
    pending = [e for e in fight.events if e.event_type == "GM_RIDER" and
               "lock round 3" in e.payload.get("rider", "")]
    assert len(pending) == 1 and "4" in pending[0].payload["rider"]
    assert not any(c.data.get("thorn_bleeding") for c in foe.conditions.values())
    move(fight, Position(x=7, y=6))
    assert foe.current_hp == before
    assert len([e for e in fight.events if e.event_type == "GM_RIDER" and
                "lock round 3" in e.payload.get("rider", "")]) == 1


def test_thorn_bleeding_triggers_on_an_attack_that_misses(monkeypatch):
    fight = thorn_fight()
    me, foe = fight.state.actors[ME], fight.state.actors[AN]
    me.armor_class = 1000
    before = foe.current_hp
    original = fight.roller.d20
    def force_miss(**kwargs):
        roll = original(**kwargs)
        if kwargs.get("actor_id") == AN and str(kwargs.get("reason")).startswith("ATTACK:"):
            return roll.model_copy(update={"natural_result": 2, "dice": (2,), "total": 2 + roll.modifier, "discarded": ()})
        return roll
    monkeypatch.setattr(fight.roller, "d20", force_miss)
    events = use(fight, attack_name(fight), ME, actor_id=AN)
    assert any(e.event_type == "ATTACK_ROLLED" and e.payload["provisional_hit"] is False for e in events)
    assert foe.current_hp == before - 4
    assert not any(c.data.get("thorn_bleeding") for c in foe.conditions.values())


def test_thorn_bleeding_does_not_count_forced_movement_or_teleportation():
    fight = thorn_fight()
    me, foe = fight.state.actors[ME], fight.state.actors[AN]
    action = next(a for a in fight.action_catalog.values() if a.owner_id == ME and a.display_name == attack_name(fight))
    ctx = typed_executor.Context(fight, me, action, None, action.parameters["typed"], [foe], foe, {})
    before = foe.current_hp
    typed_executor.block_forced_movement(ctx, {"type": "forced_movement", "direction": "away", "distance_ft": 10, "applies_to": "target"})
    other = typed_executor.Context(fight, foe, action, None, action.parameters["typed"], [], None, {})
    typed_executor._teleport(other, Position(x=7, y=7))
    assert foe.current_hp == before
    held = next(c for c in foe.conditions.values() if c.data.get("thorn_bleeding"))
    assert held.data["thorn_bleeding"]["moved_ft"] == 0


def test_thorn_basic_unarmed_strike_can_choose_slashing_separately_from_the_added_damage():
    fight = engine([THORN + "thorn_flesh_armory"], enemy_typed=True)
    foe = fight.state.actors[AN]
    for kind in ("BLUDGEONING", "PIERCING"):
        fight._add_modifier(foe, f"test:{kind}", "damage_resistance", "SET", kind, "ALWAYS", expires_on="UNTIL_REMOVED")
    events = use(fight, attack_name(fight))
    first = next(e for e in events if e.event_type == "DAMAGE_COMMITTED")
    assert first.payload["damage_type"] == "SLASHING"


def test_thorn_bleeding_ends_after_a_legacy_attack_negated_before_damage(monkeypatch):
    from combat import typed_reactions

    fight = engine([THORN + "thorn_flesh_armory"])
    fight._gain_resource(fight.state.actors[ME], "resource:named.demon_spine", 1, "test:fixture")
    use(fight, attack_name(fight))
    foe, me = fight.state.actors[AN], fight.state.actors[ME]
    fight.state.current_actor_id = AN
    fight.state.current_slot_index = fight.state.initiative_order.index(AN)
    fight._system_start_turn()
    before, protected = foe.current_hp, me.current_hp
    original = fight.roller.d20
    def force_hit(**kwargs):
        roll = original(**kwargs)
        if kwargs.get("actor_id") == AN and str(kwargs.get("reason")).startswith("ATTACK:"):
            return roll.model_copy(update={"natural_result": 20, "dice": (20,), "total": 20 + roll.modifier, "discarded": ()})
        return roll
    monkeypatch.setattr(fight.roller, "d20", force_hit)
    monkeypatch.setattr(typed_reactions, "on_attack_hit", lambda engine, actor, target, spec, total, natural, ac, *, correct_ac_miss=None: (ac, False))
    candidate = next(c for c in fight.legal_candidates() if c.kind.value == "ACTION" and ME in c.target_ids
                     and fight.action_catalog[c.source_definition_id].resolution_kind == "ATTACK_THEN_SAVE")
    use(fight, candidate.display_name, ME, actor_id=AN)
    assert me.current_hp == protected
    assert foe.current_hp == before - 4
    assert not any(c.data.get("thorn_bleeding") for c in foe.conditions.values())


BOJUTSU = "tianxia.subpath.body.bojutsu.feature."
STAFF = "tianxia.mortal.weapon.gun"


def barrier_fight(cl=18):
    fight = engine([BOJUTSU + "heavenly_staff_barrier"], cl=cl, items=[STAFF])
    use(fight, "Heavenly Staff Barrier", target=None)
    return fight


@pytest.mark.parametrize("form", [False, True])
def test_barrier_reach_is_gated_and_stacks_with_staff_form(form):
    ids = [BOJUTSU + "heavenly_staff_barrier"] + ([BOJUTSU + "staff_form"] if form else [])
    fight = engine(ids, cl=3, items=[STAFF])
    base = staff_action(fight)
    foe = fight.state.actors[AN]
    foe.position = Position(x=7 if form else 6, y=6)
    assert not any(AN in c.target_ids for c in fight.legal_candidates() if
                   fight.action_catalog.get(c.source_definition_id) and
                   fight.action_catalog[c.source_definition_id].parameters.get("bojutsu_barrier_reach"))
    use(fight, "Heavenly Staff Barrier", target=None)
    action = next(a for a in fight.action_catalog.values() if a.owner_id == ME and
                  a.parameters.get("bojutsu_barrier_reach") and
                  bool(a.parameters.get("bojutsu_on_turn")) == form and not a.parameters.get("bojutsu_flow") and
                  "bojutsu_con" not in a.source_definition_id)
    assert action.range_ft == base.range_ft + (10 if form else 5)
    events = use(fight, action.display_name)
    assert any(e.event_type == "ATTACK_ROLLED" and e.target_ids == (AN,) for e in events)
    assert fight._typed_opportunity_reach(fight.state.actors[ME]) == base.range_ft + (10 if form else 5)
    fight.state.current_actor_id = AN
    assert fight._typed_opportunity_reach(fight.state.actors[ME]) == base.range_ft + 5


@pytest.mark.parametrize("case", ["expired", "disarmed", "unowned"])
def test_barrier_reach_dormancy_does_not_mutate_catalog_or_reaction_rows(case):
    from combat import typed_reactions
    from combat.ext.bojutsu import BARRIER, barrier_opportunity_profile

    fight = barrier_fight(cl=3) if case != "unowned" else engine([], cl=3, items=[STAFF])
    actor = fight.state.actors[ME]
    catalog = {key: a.model_dump(mode="json") for key, a in fight.action_catalog.items()}
    rows = copy.deepcopy(fight.typed_reaction_rows)
    if case == "expired":
        fight._remove_condition(actor, BARRIER, "test:expiry")
    elif case == "disarmed":
        fight._apply_condition(actor, "condition:typed.disarmed", "test:disarm", AN,
            expires_on="END_OF_SCENE", data={"disables_action": staff_action(fight).source_definition_id})
    row = next(r for r in fight.typed_reaction_rows[ME] if r.get("block") == "opportunity")
    assert barrier_opportunity_profile(fight, actor, fight.action_catalog[row["action_id"]]) is None
    assert typed_reactions.opportunity_reach(fight, actor) == row["reach_ft"]
    assert not any(c.source_definition_id in fight.action_catalog and
                   fight.action_catalog[c.source_definition_id].parameters.get("bojutsu_barrier_reach")
                   for c in fight.legal_candidates())
    assert rows == fight.typed_reaction_rows
    assert catalog == {key: a.model_dump(mode="json") for key, a in fight.action_catalog.items()}
    if case == "disarmed":
        fight._remove_condition(actor, "condition:typed.disarmed", "test:pickup")
        assert typed_reactions.opportunity_reach(fight, actor) == staff_action(fight).range_ft + 5


def test_barrier_reach_actual_leave_attack_uses_one_staff_hit():
    from combat.ext.bojutsu import BARRIER_AC

    fight = barrier_fight(cl=3)
    actor, foe = fight.state.actors[ME], fight.state.actors[AN]
    catalog = {key: a.model_dump(mode="json") for key, a in fight.action_catalog.items()}
    rows = copy.deepcopy(fight.typed_reaction_rows)
    foe.position = Position(x=6, y=6)  # 15 feet: inside Barrier, outside the ordinary Staff.
    fight.state.current_actor_id = AN
    fight.state.current_slot_index = fight.state.initiative_order.index(AN)
    fight._system_start_turn()
    actor.reaction_available = True
    answers(fight, {"bojutsu_barrier_hit": ["Gain +1 AC"]})
    candidate = next(c for c in fight.legal_candidates() if c.destination == Position(x=7, y=6)
                     and c.source_definition_id == "system:combat.movement")
    start = len(fight.events)
    fight.execute_intent(ActionIntent(intent_id="r13-barrier-reach-exit", decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=AN,
        destination=candidate.destination))
    rolled = [e for e in fight.events[start:] if e.event_type == "ATTACK_ROLLED" and e.actor_id == ME]
    assert len(rolled) == 1
    assert any(c.condition_id == BARRIER_AC for c in actor.conditions.values())  # Staff-only hit hook ran.
    assert not actor.reaction_available
    assert rows == fight.typed_reaction_rows
    assert catalog == {key: a.model_dump(mode="json") for key, a in fight.action_catalog.items()}


def test_barrier_reach_does_not_extend_or_relabel_the_compiled_unarmed_opportunity_attack():
    from combat import typed_reactions
    from combat.ext.bojutsu import barrier_opportunity_profile

    fight = barrier_fight(cl=18)
    row = next(r for r in fight.typed_reaction_rows[ME] if r.get("block") == "opportunity")
    action = fight.action_catalog[row["action_id"]]
    assert action.parameters["typed"]["effects"][0]["attack_kind"] == "unarmed"
    assert barrier_opportunity_profile(fight, fight.state.actors[ME], action) is None
    assert typed_reactions.opportunity_reach(fight, fight.state.actors[ME]) == row["reach_ft"]


def test_barrier_reach_flowing_spin_uses_the_same_gated_staff_range():
    fight = engine([BOJUTSU + mid for mid in ("staff_form", "flowing_spin", "heavenly_staff_barrier")], items=[STAFF])
    use(fight, "Heavenly Staff Barrier", target=None)
    use(fight, staff_action(fight).display_name)
    fight.state.actors[AN].position = Position(x=7, y=6)
    action = next(a for a in fight.action_catalog.values() if a.parameters.get("bojutsu_flow") and
                  a.parameters.get("bojutsu_barrier_reach") and a.parameters.get("bojutsu_on_turn") and
                  "bojutsu_con" not in a.source_definition_id)
    events = use(fight, action.display_name)
    assert len([e for e in events if e.event_type == "ATTACK_ROLLED"]) == 1


def test_barrier_activation_cost_scene_limit_and_ten_round_expiry():
    from combat.ext.bojutsu import BARRIER
    from combat.ext.effect_durations import sweep

    fight = barrier_fight()
    actor = fight.state.actors[ME]
    assert actor.resources["resource:core.stamina"] == 54
    active = next(c for c in actor.conditions.values() if c.condition_id == BARRIER)
    assert active.expires_on == f"START_OF_SLOT_AT:{fight.state.round_number + 10}:{fight.state.current_slot_index}"
    actor.bonus_action_available = True
    assert not any(c.display_name == "Heavenly Staff Barrier" for c in fight.legal_candidates())
    fight.state.round_number += 9
    sweep(fight, actor, "START_OF_TURN")
    assert any(c.condition_id == BARRIER for c in actor.conditions.values())
    fight.state.round_number += 1
    sweep(fight, actor, "START_OF_TURN")
    assert not any(c.condition_id == BARRIER for c in actor.conditions.values())


@pytest.mark.parametrize("selection", ["Push 10 feet", "No Reactions", "Gain +1 AC", "Move 10 feet"])
def test_barrier_staff_hit_resolves_exactly_one_printed_result(selection):
    from combat.ext.bojutsu import BARRIER_AC, BARRIER_USED

    fight = barrier_fight()
    actor, foe = fight.state.actors[ME], fight.state.actors[AN]
    actor.movement_remaining_ft = 0
    before_ac, before_position = fight._ac_modifier(actor), foe.position
    answers(fight, {"bojutsu_barrier_hit": [selection], "bojutsu_barrier_step": ["cell:1,6"]})
    events = use(fight, staff_action(fight).display_name)
    assert any(c.condition_id == BARRIER_USED for c in actor.conditions.values())
    assert (foe.position != before_position) == (selection == "Push 10 feet")
    if selection == "Push 10 feet":
        assert fight.grid.distance_ft(before_position, foe.position) == 10
    assert any(c.condition_id == "condition:typed.reaction_denied" for c in foe.conditions.values()) == (selection == "No Reactions")
    assert fight._ac_modifier(actor) == before_ac + int(selection == "Gain +1 AC")
    assert any(c.condition_id == BARRIER_AC for c in actor.conditions.values()) == (selection == "Gain +1 AC")
    assert (actor.position == Position(x=1, y=6)) == (selection == "Move 10 feet")
    if selection == "Move 10 feet":
        moves = [e for e in events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == ME]
        assert len(moves) == 2 and all(e.payload["without_provoking"] and not e.payload.get("forced") for e in moves)
        assert actor.movement_remaining_ft == 0
    assert actor.resources["resource:core.stamina"] == 54


def test_barrier_hit_limit_resets_each_turn_and_ac_refreshes_without_stacking():
    from combat.ext.bojutsu import BARRIER_AC
    from combat.ext.effect_durations import sweep

    # At this level the compiler selects the Staff, rather than the higher-die
    # Iron Fist profile, for the actual Opportunity Attack.
    fight = barrier_fight(cl=3)
    actor = fight.state.actors[ME]
    before = fight._ac_modifier(actor)
    seen = []
    def provider(request):
        if request.get("extension_choice"):
            seen.append(request)
            return ReactionDecision(**{k: request[k] for k in ("checkpoint", "reactor_id", "reaction_source_id")},
                selection="USE", option_ids=("Gain +1 AC",)), None
        return None, None
    fight.set_reaction_provider(provider)
    use(fight, staff_action(fight).display_name)
    use(fight, staff_action(fight).display_name)
    assert len(seen) == 1 and fight._ac_modifier(actor) == before + 1
    fight.end_turn()
    from combat import typed_reactions
    candidate = fight.legal_candidates()[0]
    intent = ActionIntent(intent_id="r13-barrier-oa", decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=AN, target_ids=candidate.target_ids)
    typed_reactions.opportunity_attack(fight, actor, fight.state.actors[AN], intent)
    assert len(seen) == 2 and fight._ac_modifier(actor) == before + 1
    assert sum(c.condition_id == BARRIER_AC for c in actor.conditions.values()) == 1
    fight.end_turn()
    from combat.ext.bojutsu import BARRIER_USED
    assert not any(c.condition_id == BARRIER_USED for c in actor.conditions.values())
    actor.turns_started += 1
    sweep(fight, actor, "START_OF_TURN")
    assert fight._ac_modifier(actor) == before


def test_barrier_reaction_denial_expires_at_targets_next_start():
    from combat.ext.effect_durations import sweep

    fight = barrier_fight()
    actor, foe = fight.state.actors[ME], fight.state.actors[AN]
    answers(fight, {"bojutsu_barrier_hit": ["No Reactions"]})
    use(fight, staff_action(fight).display_name)
    denial = next(c for c in foe.conditions.values() if c.condition_id == "condition:typed.reaction_denied")
    assert denial.source_definition_id == BOJUTSU + "heavenly_staff_barrier"
    actor.turns_started += 1
    sweep(fight, actor, "START_OF_TURN")
    assert denial.instance_id in foe.conditions
    foe.turns_started += 1
    sweep(fight, foe, "START_OF_TURN")
    assert denial.instance_id not in foe.conditions


@pytest.mark.parametrize("case", ["unarmed", "disarmed", "expired", "unowned"])
def test_barrier_hit_is_inert_without_active_owned_staff(case):
    from combat.ext.bojutsu import BARRIER, BARRIER_USED

    fight = barrier_fight() if case != "unowned" else engine([], items=[STAFF])
    actor = fight.state.actors[ME]
    if case == "disarmed":
        fight._apply_condition(actor, "condition:typed.disarmed", "test", AN, expires_on="UNTIL_REMOVED",
                               data={"disables_action": staff_action(fight).source_definition_id})
    if case == "expired":
        fight._remove_condition(actor, BARRIER, "test")
    answers(fight, {"bojutsu_barrier_hit": ["Gain +1 AC"]})
    use(fight, attack_name(fight) if case in {"unarmed", "disarmed"} else staff_action(fight).display_name)
    assert not any(c.condition_id == BARRIER_USED for c in actor.conditions.values())


@pytest.mark.parametrize("automatic,offturn,reach", [(False, False, False), (True, False, False),
                                                    (False, True, False), (False, False, True)])
@pytest.mark.parametrize("result_name", ["Gain +1 AC", "Move 10 feet"])
def test_barrier_real_table_hit_choice_commit_reload_and_replay(tmp_path, automatic, offturn, reach, result_name):
    import zipfile
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from tests.test_factory_combat_compiler import SHEET
    from combat.ext.bojutsu import BARRIER, BARRIER_AC, BARRIER_USED

    actors = [FACTORY_ACTOR_PREFIX + side for side in ("left", "right")]
    for side in ("left", "right"):
        sheet = copy.deepcopy(SHEET)
        sheet["path_and_subpath"] = {"path_feature_record_ids": [BOJUTSU + "heavenly_staff_barrier"]}
        if reach:
            sheet["path_and_subpath"]["path_feature_record_ids"].append(BOJUTSU + "staff_form")
        sheet["equipment"] = [{"starting_kit": {"items": [{"item_id": STAFF}]}}]
        sheet["ability_scores_and_statistics"]["armor_class"] = {"base_value": 0}
        folder = tmp_path / "portable_characters" / side
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({"display_name": "R13 Staff yard", "width_squares": 12, "height_squares": 8,
        "walls": [], "starts": {"team1": [[3, 4]], "team2": [[7 if reach else 4, 4]]}})
    view = service.create_factory_match(project_ids=["left"], opponent_actor_ids=[actors[1]],
        control_modes={aid: "MANUAL" for aid in actors}, arena_id="battlefield:map.r13-staff-yard",
        match_seed="R13-TABLE-BARRIER")
    mid = view["match_id"]
    table = TabletopService(service, tmp_path)
    state = table.state(mid)
    menu = state["menu"]
    owner = menu["actor_id"]
    activate = next(g for g in menu["actions"] if g["source_definition_id"].endswith(".heavenly_staff_barrier"))
    result = table.act(mid, activate["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(c.condition_id == BARRIER for c in loaded.engine.state.actors[owner].conditions.values())
    if offturn:
        state = table.state(mid)
        menu = state["menu"]
        table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    state = table.state(mid)
    menu = state["menu"]
    attack = next(g for g in menu["actions"] if g["source_definition_id"].endswith(
        ".weapon.gun#bojutsu_reach#bojutsu_barrier_reach" if reach else ".weapon.gun"))
    candidate = attack["options"][0]["candidate_id"]
    before = loaded.engine.state.actors[owner].model_dump(mode="json")
    if automatic or offturn:
        service.set_controller_mode(mid, actor_id=menu["actor_id"], controller_mode="LOCAL_AUTO")
        from combat.gate4_adapters import ManualControllerAdapter
        real = service.controller
        class StaffAttacker:
            def choose_primary_action(self, context):
                if offturn:
                    # Force the hostile AI's physical move out of normal Staff
                    # reach; the production Reaction chooser stays unchanged.
                    candidates = [c for c in context.legal_candidates if c.source_definition_id == "system:combat.movement"]
                    position = loaded.engine.state.actors[owner].position
                    chosen = max(candidates, key=lambda c: max(abs(c.destination.x - position.x), abs(c.destination.y - position.y)))
                else:
                    chosen = next(c for c in context.legal_candidates if c.source_definition_id.endswith(".weapon.gun"))
                return ManualControllerAdapter(lambda _context: (chosen.candidate_id, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        service.controller = StaffAttacker()
        result = table.auto_step(mid, state["last_sequence"])
    else:
        result = table.act(mid, candidate, menu["decision_id"], menu["state_version"], state["last_sequence"])
    if not automatic:
        assert result["status"] == "REACTION_REQUIRED"
        reaction = result["reaction"]
        assert reaction["context"]["reaction_source_id"] == "choice:needle.bojutsu_barrier_hit"
        assert "Heavenly Staff Barrier" in reaction["moment"] and "hit" in reaction["moment"]
        victim = menu["actor_id"] if offturn else attack["options"][0]["target_ids"][0]
        assert loaded.engine.state.actors[victim].display_name in reaction["moment"]
        assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[owner].model_dump(mode="json") == before
        reply = {**reaction["context"], "selection": "USE", "option_ids": [result_name]}
        result = (table.auto_step(mid, state["last_sequence"], [reply]) if offturn else
                  table.act(mid, candidate, menu["decision_id"], menu["state_version"], state["last_sequence"], [reply]))
        if result_name == "Move 10 feet":
            assert result["status"] == "REACTION_REQUIRED"
            followup = result["reaction"]
            assert followup["context"]["reaction_source_id"].endswith("bojutsu_barrier_step")
            assert all(o["label"] == "Move to " + o["id"].removeprefix("cell:")
                       for o in followup["choice"]["options"])
            destination = {**followup["context"], "selection": "USE",
                           "option_ids": [followup["choice"]["options"][0]["id"]]}
            result = (table.auto_step(mid, state["last_sequence"], [reply, destination]) if offturn else
                      table.act(mid, candidate, menu["decision_id"], menu["state_version"], state["last_sequence"], [reply, destination]))
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(c.condition_id == BARRIER_USED for c in loaded.engine.state.actors[owner].conditions.values())
    if not automatic and result_name == "Gain +1 AC":
        assert any(c.condition_id == BARRIER_AC for c in loaded.engine.state.actors[owner].conditions.values())
    if not automatic and result_name == "Move 10 feet":
        assert loaded.engine.state.actors[owner].position.model_dump(mode="json") != before["position"]
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_staff_of_one_ac_requires_a_staff_and_resumes_after_pickup():
    fight = engine([BOJUTSU + "staff_of_one"], items=[STAFF])
    me = fight.state.actors[ME]
    baseline = engine([], items=[STAFF])
    expected = baseline._ac_modifier(baseline.state.actors[ME])
    assert fight._ac_modifier(me) == expected + 1
    action = staff_action(fight)
    ctx = typed_executor.Context(fight, fight.state.actors[AN], action, None, {}, [me], me)
    typed_executor.block_condition(ctx, {"type": "condition", "condition": "disarmed"})
    assert fight._ac_modifier(me) == expected
    use(fight, next(a.display_name for a in fight.action_catalog.values()
                   if a.owner_id == ME and a.parameters.get("typed", {}).get("effects", [{}])[0].get("type") == "recover_weapon"), target=None)
    assert fight._ac_modifier(me) == expected + 1
    without = engine([BOJUTSU + "staff_of_one"])
    control = engine([])
    assert without._ac_modifier(without.state.actors[ME]) == control._ac_modifier(control.state.actors[ME])


def test_staff_of_one_does_not_compile_a_projectile_attack():
    fight = engine([BOJUTSU + "staff_of_one"], items=[STAFF])
    assert not any(a.parameters.get("typed", {}).get("source") == BOJUTSU + "staff_of_one"
                   for a in fight.action_catalog.values())
    assert not any(r.get("feature_id") == BOJUTSU + "staff_of_one" for r in fight.typed_reaction_rows[ME])


def test_staff_of_one_hooks_leave_an_unowned_ai_fight_byte_identical(monkeypatch):
    import sys
    from combat.canonical import canonical_bytes
    from combat.gate4_context import build_decision_context
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_policy import PolicyLibrary

    previous = json.loads(subprocess.check_output(["git", "show",
        "7c3bd9778034cb58b3d3ac27b426522f3e662569:APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json"], cwd=ROOT))

    def run():
        fight = engine([], enemy_typed=True, items=[STAFF])
        fight.state.actors[AN].current_hp = 80
        fight.state.actors[AN].maximum_hp = 80
        fight.state.actors[AN].armor_class = 14
        controller, policies = LocalDeterministicController(), PolicyLibrary(ROOT)
        for _ in range(600):
            if fight.state.terminal_result:
                break
            policy, _ = policies.for_actor(fight.state.current_actor_id)
            choice = controller.choose_primary_action(build_decision_context(fight, policy, for_ai=True))
            fight.execute_intent(choice.intent)
        assert fight.state.terminal_result
        return canonical_bytes([e.model_dump(mode="json") for e in fight.events])

    current = run()
    monkeypatch.setattr(sys.modules[__name__], "authority", lambda: previous)
    assert run() == current


def test_staff_of_one_passive_survives_table_commit_and_reload(tmp_path):
    import zipfile
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from tests.test_factory_combat_compiler import SHEET

    for side in ("left", "right"):
        sheet = {**copy.deepcopy(SHEET),
            "path_and_subpath": {"path_feature_record_ids": [BOJUTSU + "staff_of_one"]},
            "equipment": [{"starting_kit": {"items": [{"item_id": STAFF}]}}]}
        folder = tmp_path / "portable_characters" / side
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    service = CombatService(ROOT, tmp_path)
    view = service.create_factory_match(project_ids=["left"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "right"],
        control_modes={FACTORY_ACTOR_PREFIX + side: "MANUAL" for side in ("left", "right")}, match_seed="R13-STAFF-SAVED")
    mid = view["match_id"]
    table = TabletopService(service, tmp_path)
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["source_definition_id"] == "system:combat.hold_position")
    result = table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    from combat.ext.bojutsu import staff_of_one_ac

    assert staff_of_one_ac(loaded.engine, loaded.engine.state.actors[menu["actor_id"]]) == 1
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("staff", [True, False])
def test_staff_of_one_opportunity_advantage_is_staff_specific(staff):
    from combat import typed_reactions

    fight = engine([BOJUTSU + "staff_of_one"], cl=3, items=[STAFF] if staff else [])
    me, foe = fight.state.actors[ME], fight.state.actors[AN]
    # Resolve the actual compiled Opportunity Attack, not a synthetic effect.
    row = next(r for r in fight.typed_reaction_rows[ME] if r["block"] == "opportunity")
    action = fight.action_catalog[row["action_id"]]
    assert (action.parameters["typed"]["source"] == STAFF) is staff
    start = len(fight.events)
    typed_reactions.opportunity_attack(fight, me, foe, None)
    rolled = next(e for e in fight.events[start:] if e.event_type == "ATTACK_ROLLED")
    assert rolled.payload["mode"] == ("ADVANTAGE" if staff else "NORMAL")
    if staff:
        events = use(fight, staff_action(fight).display_name)
        assert next(e for e in events if e.event_type == "ATTACK_ROLLED").payload["mode"] == "NORMAL"


@pytest.mark.parametrize("condition,staff", [("disarmed", True), ("prone", True), ("disarmed", False)])
def test_staff_of_one_save_advantage_only_retains_the_staff(condition, staff):
    fight = engine([BOJUTSU + "staff_of_one"], dc=-40, items=[STAFF] if staff else [])
    me = fight.state.actors[ME]
    action = next(a for a in fight.action_catalog.values() if a.display_name == attack_name(fight))
    ctx = typed_executor.Context(fight, fight.state.actors[AN], action, None,
                                 {"numbers": {"save_dc": -40}}, [me], me)
    typed_executor.block_save(ctx, {"type": "save", "ability": "str",
        "on_fail": [{"type": "condition", "condition": condition}], "on_success": []})
    rolled = next(e for e in reversed(fight.events) if e.event_type == "SAVE_ROLLED")
    assert rolled.payload["mode"] == ("ADVANTAGE" if condition == "disarmed" and staff else "NORMAL")


def staff_action(fight, con=False, extended=False):
    return next(a for a in fight.action_catalog.values() if a.owner_id == ME and a.economy.value == "ACTION"
                and a.parameters.get("typed", {}).get("source") == STAFF
                and any(e.get("attack_kind") == "weapon" for e in a.parameters["typed"].get("effects") or [])
                and ("bojutsu_con" in a.source_definition_id) == con
                and bool(a.parameters.get("bojutsu_on_turn")) == extended
                and ("#" not in a.source_definition_id or "bojutsu" in a.source_definition_id))


def deflect_fight(*, owned=True, staff=True, ally=False, con=5):
    protected = "actor:factory.r13ally" if ally else ME
    bundles = [bundle([BOJUTSU + "staff_of_one"] if owned else [], cl=3,
                      items=[STAFF] if staff else [], ability_mods={"CON": con}),
               bundle([], cl=3, actor_id=AN, items=["tianxia.mortal.weapon.gong_jian"])]
    if ally:
        bundles.append(bundle([], cl=3, actor_id=protected))
    fight = Gate4ControllerEngine(ROOT, match_seed="R13-DEFLECT", typed_bundles=bundles,
        roster_setup={"primary_actor_ids": [ME, AN, *([protected] if ally else [])],
                      "team_by_actor": {ME: "team:a", protected: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 8, "y": 6},
                                             **({protected: {"x": 3, "y": 7}} if ally else {})}})
    fight.state.current_slot_index = fight.state.initiative_order.index(AN)
    fight.state.current_actor_id = AN
    fight._system_start_turn()
    fight.state.actors[protected].armor_class = -50
    action = next(a for a in fight.action_catalog.values() if a.owner_id == AN and a.economy.value == "ACTION"
                  and a.parameters.get("typed", {}).get("source") == "tianxia.mortal.weapon.gong_jian")
    return fight, action, protected


def deflect_attack(fight, action, protected):
    return use(fight, action.display_name, target=protected, actor_id=AN)


@pytest.mark.parametrize("ally", [False, True])
def test_deflecting_staff_reduces_real_bow_packet_before_hp_and_temp_hp(ally):
    fight, action, protected = deflect_fight(ally=ally)
    actor, target = fight.state.actors[ME], fight.state.actors[protected]
    target.temporary_hp = 8
    start_hp, start_stamina = target.current_hp, actor.resources["resource:core.stamina"]
    events = deflect_attack(fight, action, protected)
    response = next(e for e in events if e.event_type == "REACTION_RESOLVED"
                    and e.source_definition_id == BOJUTSU + "staff_of_one")
    damage = next(e for e in events if e.event_type == "DAMAGE_COMMITTED")
    assert events.index(response) < events.index(damage)
    assert response.payload["protects"] == protected
    assert damage.payload["reduced_to"] == response.payload["pending_after"]
    assert target.current_hp == start_hp - max(0, response.payload["pending_after"] - 8)
    assert target.temporary_hp == max(0, 8 - response.payload["pending_after"])
    roll = next(r for r in fight.rolls if r.reason.startswith("DAMAGE_REDUCTION:"))
    assert roll.modifier == 5
    assert actor.resources["resource:core.stamina"] == start_stamina - 1
    assert not actor.reaction_available
    assert any(c.data.get("round") == fight.state.round_number for c in actor.conditions.values()
               if c.condition_id == "condition:typed.bojutsu_deflect_used")


@pytest.mark.parametrize("guard", ["unowned", "no_staff", "no_stamina", "no_reaction", "distant_ally", "disarmed", "uninterceptable"])
def test_deflecting_staff_is_inert_when_not_qualified(guard):
    fight, action, protected = deflect_fight(owned=guard != "unowned", staff=guard != "no_staff", ally=guard == "distant_ally")
    actor = fight.state.actors[ME]
    if guard == "no_stamina":
        actor.resources["resource:core.stamina"] = 0
    elif guard == "no_reaction":
        actor.reaction_available = False
    elif guard == "distant_ally":
        fight.state.actors[protected].position = Position(x=3, y=9)
    elif guard == "disarmed":
        ctx = typed_executor.Context(fight, fight.state.actors[AN], action, None, {}, [actor], actor)
        typed_executor.block_condition(ctx, {"type": "condition", "condition": "disarmed"})
    elif guard == "uninterceptable":
        action.parameters["typed"]["effects"][0]["interceptable"] = False
    before = actor.resources["resource:core.stamina"]
    events = deflect_attack(fight, action, protected)
    assert any(e.event_type == "DAMAGE_COMMITTED" and e.payload["reduced_to"] > 0 for e in events)
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == BOJUTSU + "staff_of_one" for e in events)
    assert actor.resources["resource:core.stamina"] == before


def test_deflecting_staff_can_decline_and_names_the_trigger_and_protected_creature():
    fight, action, protected = deflect_fight(ally=True)
    seen = []
    def provider(request):
        seen.append(request)
        return ReactionDecision(**{key: request[key] for key in ("checkpoint", "reactor_id", "reaction_source_id")},
                                selection="DECLINE"), None
    fight.set_reaction_provider(provider)
    actor = fight.state.actors[ME]
    before = actor.resources["resource:core.stamina"]
    events = deflect_attack(fight, action, protected)
    request = next(r for r in seen if r["reaction_source_id"] == "choice:needle.bojutsu_deflect")
    prompt = request["choice_trigger"]["prompt"]
    assert "Deflecting Staff" in prompt and action.display_name in prompt and fight.state.actors[protected].display_name in prompt
    assert actor.resources["resource:core.stamina"] == before and actor.reaction_available
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == BOJUTSU + "staff_of_one" for e in events)


def test_deflecting_staff_round_limit_survives_an_extra_reaction_and_resets_next_round():
    fight, action, protected = deflect_fight()
    actor = fight.state.actors[ME]
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == BOJUTSU + "staff_of_one"
               for e in deflect_attack(fight, action, protected))
    actor.reaction_available = True
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == BOJUTSU + "staff_of_one"
                   for e in deflect_attack(fight, action, protected))
    fight.state.round_number += 1
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == BOJUTSU + "staff_of_one"
               for e in deflect_attack(fight, action, protected))


def test_deflecting_staff_does_not_intercept_standalone_damage_from_the_same_bow_action():
    fight, action, protected = deflect_fight()
    action.parameters["typed"]["effects"] = [{"type": "damage", "flat": 12, "damage_types": ["poison"]}]
    events = deflect_attack(fight, action, protected)
    assert next(e for e in events if e.event_type == "DAMAGE_COMMITTED").payload["hp_damage"] == 12
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == BOJUTSU + "staff_of_one" for e in events)
    assert getattr(fight, "_typed_damage_packet", None) is None


@pytest.mark.parametrize("delivery", ["melee", "ray", "save_area"])
def test_deflecting_staff_excludes_melee_spell_and_save_area_delivery(delivery):
    fight, action, protected = deflect_fight()
    typed = action.parameters["typed"]
    if delivery == "melee":
        typed["range_ft"] = None
        fight.state.actors[AN].position = Position(x=4, y=6)
    elif delivery == "ray":
        typed["effects"][0]["attack_kind"] = "cultivation_ranged"
        typed.pop("weapon", None)
    else:
        typed["effects"] = [{"type": "save", "ability": "dex", "on_fail": [
            {"type": "damage", "flat": 12, "damage_types": ["fire"]}], "on_success": []}]
        typed["numbers"]["save_dc"] = 100
    events = deflect_attack(fight, action, protected)
    assert any(e.event_type == "DAMAGE_COMMITTED" and e.payload["hp_damage"] > 0 for e in events)
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == BOJUTSU + "staff_of_one" for e in events)


def test_deflecting_staff_does_not_cancel_separate_afterimpact_poison():
    fight, action, protected = deflect_fight()
    action.parameters["typed"]["effects"][0]["on_hit"].append(
        {"type": "damage", "flat": 12, "damage_types": ["poison"]})
    events = deflect_attack(fight, action, protected)
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == BOJUTSU + "staff_of_one" for e in events)
    poison = next(e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.payload["damage_type"] == "POISON")
    assert poison.payload["hp_damage"] == 12


def test_deflecting_staff_uses_post_resistance_damage_before_the_selected_zero_result():
    fight, action, protected = deflect_fight()
    target = fight.state.actors[protected]
    fight._add_modifier(target, "test:resistance", "damage_resistance", "SET", "PIERCING", "SELF", expires_on="END_OF_CURRENT_TURN")
    answers(fight, {"bojutsu_deflect_result": ["Catch projectile"]})
    events = deflect_attack(fight, action, protected)
    damage = next(e for e in events if e.event_type == "DAMAGE_COMMITTED")
    response = next(e for e in events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == BOJUTSU + "staff_of_one")
    assert response.payload["pending_before"] == damage.payload["rolled_or_pending_damage"] // 2
    assert response.payload["pending_after"] == 0
    assert any(e.event_type == "GM_RIDER" and "Catch projectile" in e.payload.get("rider", "") for e in events)
    assert not any(e.event_type == "MOVEMENT_COMMITTED" for e in events)


@pytest.mark.parametrize("ai_turn,guard_auto,ally", [(False, False, False), (True, False, False), (True, True, False),
                                                   (False, False, True), (True, False, True)])
def test_deflecting_staff_table_choices_on_manual_ai_turns_and_reloads_round_marker(tmp_path, ai_turn, guard_auto, ally):
    import zipfile
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from combat.gate4_adapters import ManualControllerAdapter
    from tests.test_factory_combat_compiler import SHEET

    guard, shooter = [FACTORY_ACTOR_PREFIX + side for side in ("left", "right")]
    protected = FACTORY_ACTOR_PREFIX + "ally" if ally else guard
    for side in ("left", "right", *(["ally"] if ally else [])):
        sheet = copy.deepcopy(SHEET)
        if side == "left":
            abilities = json.loads(sheet["ability_scores_and_statistics"]["abilities"])
            next(a for a in abilities if a["ability"] == "CON").update(score=210, modifier=100)
            sheet["ability_scores_and_statistics"]["abilities"] = json.dumps(abilities)
        sheet["path_and_subpath"] = {"path_feature_record_ids": [BOJUTSU + "staff_of_one"] if side == "left" else []}
        sheet["equipment"] = [{"starting_kit": {"items": [{"item_id": STAFF if side == "left" else "tianxia.mortal.weapon.gong_jian"}]}}]
        folder = tmp_path / "portable_characters" / side
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({"display_name": "R13 bow yard", "width_squares": 12, "height_squares": 8,
        "walls": [], "starts": {"team1": [[3, 4], [3, 5]], "team2": [[8, 4]]}})
    view = service.create_factory_match(project_ids=["left", *(["ally"] if ally else [])], opponent_actor_ids=[shooter],
        control_modes={guard: "MANUAL", shooter: "LOCAL_AUTO" if ai_turn else "MANUAL"},
        arena_id="battlefield:map.r13-bow-yard", match_seed="R13-TABLE-DEFLECT")
    mid = view["match_id"]
    table = TabletopService(service, tmp_path)
    real = service.controller
    class Archer:
        def choose_primary_action(self, context):
            chosen = next(c for c in context.legal_candidates if c.source_definition_id.endswith(".weapon.gong_jian")
                          and protected in c.target_ids)
            return ManualControllerAdapter(lambda _context: (chosen.candidate_id, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    if ai_turn:
        service.controller = Archer()
    asked = None
    for _ in range(20):
        state = table.state(mid)
        menu = state["menu"]
        if menu["actor_id"] != shooter:
            c = menu["end_turn"]
            table.act(mid, c, menu["decision_id"], menu["state_version"], state["last_sequence"])
            continue
        before = service._load_session(mid).engine.state.actors[guard].model_dump(mode="json")
        if guard_auto:
            service.set_controller_mode(mid, actor_id=guard, controller_mode="LOCAL_AUTO")
        if ai_turn:
            result = table.auto_step(mid, state["last_sequence"])
        else:
            group = next(g for g in menu["actions"] if g["source_definition_id"].endswith(".weapon.gong_jian"))
            c = next(option for option in group["options"] if protected in option["target_ids"])
            result = table.act(mid, c["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
        if guard_auto:
            assert result["status"] == "COMMITTED"
            assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == BOJUTSU + "staff_of_one"
                       for e in service._load_session(mid).engine.events)
            break
        if result["status"] == "REACTION_REQUIRED":
            asked = result["reaction"]
            assert asked["context"]["reactor_id"] == guard
            assert asked["context"]["reaction_source_id"] == "choice:needle.bojutsu_deflect"
            assert "Deflecting Staff" in asked["moment"] and "attack" in asked["moment"]
            assert service._load_session(mid).engine.state.actors[guard].model_dump(mode="json") == before
            reply = {**asked["context"], "selection": "USE", "option_ids": ["Use Deflecting Staff"]}
            if ai_turn:
                done = table.auto_step(mid, state["last_sequence"], [reply])
            else:
                done = table.act(mid, c["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"], [reply])
            replies = [reply]
            while done["status"] == "REACTION_REQUIRED":
                followup = done["reaction"]
                context = followup["context"]
                assert context["reactor_id"] == guard
                assert "Deflecting Staff" in followup["moment"] and "attack" in followup["moment"]
                assert service._load_session(mid).engine.state.actors[guard].model_dump(mode="json") == before
                options = [option["id"] for option in followup["choice"]["options"]]
                if context["reaction_source_id"].endswith("bojutsu_deflect_step"):
                    assert all(o["label"] == "Move to " + o["id"].removeprefix("cell:")
                               for o in followup["choice"]["options"])
                choice = ("Grant Half Cover" if ally else "Move 5 feet") if context["reaction_source_id"].endswith("bojutsu_deflect_result") else options[0]
                replies.append({**context, "selection": "USE", "option_ids": [choice]})
                if ai_turn:
                    done = table.auto_step(mid, state["last_sequence"], replies)
                else:
                    done = table.act(mid, c["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"], replies)
            assert done["status"] == "COMMITTED"
            break
        # A miss committed the attack. End this turn to refresh its Action.
        state = table.state(mid)
        menu = state["menu"]
        if not ai_turn:
            c = menu["end_turn"]
            table.act(mid, c, menu["decision_id"], menu["state_version"], state["last_sequence"])
        else:
            # The scripted controller must end after the bow Action is spent.
            class End:
                def choose_primary_action(self, context):
                    chosen = next(c for c in context.legal_candidates if c.kind.value == "END_TURN")
                    return ManualControllerAdapter(lambda _context: (chosen.candidate_id, ())).choose_primary_action(context)
                def __getattr__(self, name):
                    return getattr(real, name)
            service.controller = End()
            table.auto_step(mid, state["last_sequence"])
            service.controller = Archer()
    assert guard_auto or asked is not None
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[guard]
    marker = next(c for c in actor.conditions.values() if c.condition_id == "condition:typed.bojutsu_deflect_used")
    assert marker.data == {"round": loaded.engine.state.round_number}
    assert not actor.reaction_available
    if ally:
        friend = loaded.engine.state.actors[protected]
        cover = next(c for c in friend.conditions.values() if c.condition_id == "condition:typed.bojutsu_deflect_cover")
        assert cover.source_actor_id == guard and cover.data["cover"] == 2
        assert loaded.engine._cover_bonus_actor_to_actor(loaded.engine.state.actors[shooter], friend) == 2
    else:
        assert actor.position.model_dump(mode="json") != before["position"]
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_deflecting_staff_zero_move_is_physical_free_and_does_not_provoke():
    fight, action, protected = deflect_fight(con=100)
    actor = fight.state.actors[ME]
    actor.movement_remaining_ft = 0
    before = actor.position
    # Enemy is close enough to threaten the chosen departure, but still fires
    # the compiled ranged attack. No Opportunity Attack is manufactured.
    fight.state.actors[AN].position = Position(x=4, y=6)
    answers(fight, {"bojutsu_deflect_result": ["Move 5 feet"], "bojutsu_deflect_step": ["cell:2,6"]})
    events = deflect_attack(fight, action, protected)
    movement = next(e for e in events if e.event_type == "MOVEMENT_COMMITTED")
    assert actor.position == Position(x=2, y=6)
    assert actor.movement_remaining_ft == 0
    assert movement.payload["path"] == [before.model_dump(mode="json"), actor.position.model_dump(mode="json")]
    assert movement.payload["without_provoking"] and not movement.payload.get("forced") and not movement.payload.get("teleport")
    assert not any(e.event_type == "REACTION_WINDOW_OPENED" and "OPPORTUNITY" in str(e.payload) for e in events)
    assert not any(c.condition_id == "condition:typed.bojutsu_deflect_cover" for c in actor.conditions.values())


@pytest.mark.parametrize("guard", ["speed_zero", "occupied", "frightened", "terrain"])
def test_deflecting_staff_move_options_obey_ordinary_route_restrictions(guard):
    from combat.ext.bojutsu import _deflect_routes

    fight, action, protected = deflect_fight(con=100)
    actor = fight.state.actors[ME]
    if guard == "speed_zero":
        fight._apply_condition(actor, "condition:typed.restrained", "test", AN, expires_on="UNTIL_REMOVED")
        assert _deflect_routes(fight, actor) == {}
    elif guard == "occupied":
        fight.state.actors[AN].position = Position(x=2, y=6)
        assert "cell:2,6" not in _deflect_routes(fight, actor)
    elif guard == "frightened":
        fight._apply_condition(actor, "condition:typed.frightened", "test", AN, expires_on="UNTIL_REMOVED")
        assert "cell:4,6" not in _deflect_routes(fight, actor)
    else:
        fight.grid.base_movement_cost[(2, 6)] = 2
        assert "cell:2,6" not in _deflect_routes(fight, actor)


def test_deflecting_staff_zero_cover_only_protects_selected_ally_and_expires_on_source_start():
    from combat.ext.effect_durations import sweep

    fight, action, protected = deflect_fight(ally=True, con=100)
    actor, ally, enemy = (fight.state.actors[mid] for mid in (ME, protected, AN))
    answers(fight, {"bojutsu_deflect_result": ["Grant Half Cover"]})
    events = deflect_attack(fight, action, protected)
    assert not any(e.event_type == "MOVEMENT_COMMITTED" for e in events)
    condition = next(c for c in ally.conditions.values() if c.condition_id == "condition:typed.bojutsu_deflect_cover")
    assert condition.source_actor_id == ME and condition.data["cover"] == 2
    assert fight._cover_bonus_actor_to_actor(enemy, ally) == 2
    assert fight._cover_bonus_actor_to_actor(enemy, actor) == 0
    another = deflect_attack(fight, action, protected)
    assert next(e for e in another if e.event_type == "ATTACK_ROLLED").payload["cover_bonus"] == 2
    ally.turns_started += 1
    sweep(fight, ally, "START_OF_TURN")
    assert fight._cover_bonus_actor_to_actor(enemy, ally) == 2
    actor.turns_started += 1
    sweep(fight, actor, "START_OF_TURN")
    assert fight._cover_bonus_actor_to_actor(enemy, ally) == 0


@pytest.mark.parametrize("choice", ["Catch projectile", "Deflect projectile"])
def test_deflecting_staff_unrepresented_item_choices_do_not_duplicate_items_or_apply_another_result(choice):
    fight, action, protected = deflect_fight(ally=True, con=100)
    before = copy.deepcopy(fight.typed_bundle_documents)
    answers(fight, {"bojutsu_deflect_result": [choice]})
    events = deflect_attack(fight, action, protected)
    assert any(e.event_type == "GM_RIDER" and choice in e.payload.get("rider", "") for e in events)
    assert not any(e.event_type == "MOVEMENT_COMMITTED" for e in events)
    assert not any(c.condition_id == "condition:typed.bojutsu_deflect_cover"
                   for a in fight.state.actors.values() for c in a.conditions.values())
    assert fight.typed_bundle_documents == before


def test_deflecting_staff_self_cover_is_not_offered_and_nonzero_damage_has_no_result_menu():
    for con in (100, -100):
        fight, action, protected = deflect_fight(con=con)
        seen = []
        def provider(request):
            spec = request.get("extension_choice")
            if spec is None:
                return None, None
            seen.append(request)
            return ReactionDecision(**{key: request[key] for key in ("checkpoint", "reactor_id", "reaction_source_id")},
                selection="USE", option_ids=tuple(spec["option_ids"][:1])), None
        fight.set_reaction_provider(provider)
        deflect_attack(fight, action, protected)
        results = [r for r in seen if r["reaction_source_id"].endswith("bojutsu_deflect_result")]
        if con > 0:
            assert len(results) == 1
            assert "Grant Half Cover" not in results[0]["extension_choice"]["option_ids"]
        else:
            assert not results


def test_deflecting_staff_free_step_counts_as_willing_movement_for_thorn_bleeding():
    fight, action, protected = deflect_fight(con=100)
    actor = fight.state.actors[ME]
    ctx = typed_executor.Context(fight, fight.state.actors[AN], action, None,
        {"numbers": {"pb": 4}}, [actor], actor)
    typed_executor.run_effects(ctx, [{"type": "thorn_bleeding", "damage_type": "piercing"}])
    answers(fight, {"bojutsu_deflect_result": ["Move 5 feet"], "bojutsu_deflect_step": ["cell:2,6"]})
    deflect_attack(fight, action, protected)
    held = next(c for c in actor.conditions.values() if c.data.get("thorn_bleeding"))
    assert held.data["thorn_bleeding"]["moved_ft"] == 5


def test_staff_form_uses_con_and_on_turn_reach_without_replacing_the_staff_die():
    fight = engine([BOJUTSU + "staff_form"], items=[STAFF], ability_mods={"CON": 5, "STR": 1})
    base, extended = staff_action(fight), staff_action(fight, con=True, extended=True)
    assert extended.range_ft == base.range_ft + 5
    assert extended.parameters["typed"]["weapon"]["damage"]["sides"] == 8
    assert extended.parameters["typed"]["numbers"]["attack_bonus"] == 8
    foe = fight.state.actors[AN]
    foe.position = Position(x=6, y=6)  # 15 feet, outside this Staff's normal reach.
    assert not any(c.source_definition_id == base.source_definition_id and AN in c.target_ids for c in fight.legal_candidates())
    events = use(fight, extended.display_name)
    roll = next(e for e in events if e.event_type == "ATTACK_ROLLED")
    assert roll.payload["modifier"] == 8
    damage = next(e for e in events if e.event_type == "DAMAGE_ROLLED")
    assert damage.payload["dice"] and damage.payload["modifier"] == 5
    fight.state.current_actor_id = AN
    fight.state.current_slot_index = fight.state.initiative_order.index(AN)
    from combat.ext.bojutsu import allowed
    assert allowed(fight, fight.state.actors[ME], None, extended) is False
    assert fight._typed_opportunity_reach(fight.state.actors[ME]) <= base.range_ft


def test_flowing_spin_requires_an_attack_action_staff_roll_then_makes_exactly_one_staff_attack():
    fight = engine([BOJUTSU + "staff_form", BOJUTSU + "flowing_spin"], items=[STAFF])
    assert not any(c.display_name.startswith("Flowing Spin") for c in fight.legal_candidates())
    events = use(fight, staff_action(fight).display_name)
    assert any(e.event_type == "ATTACK_ROLLED" for e in events)
    candidate = next(c for c in fight.legal_candidates() if c.display_name.startswith("Flowing Spin") and AN in c.target_ids)
    action = fight.action_catalog[candidate.source_definition_id]
    assert action.parameters["typed"]["weapon"]["damage"]["sides"] == 8
    before = fight.state.actors[ME].resources["resource:core.stamina"]
    events = use(fight, candidate.display_name)
    assert len([e for e in events if e.event_type == "ATTACK_ROLLED"]) == 1
    assert fight.state.actors[ME].resources["resource:core.stamina"] == before - 1
    assert not fight.state.actors[ME].bonus_action_available


def test_flowing_spin_is_not_enabled_by_an_unarmed_or_reaction_staff_attack():
    fight = engine([BOJUTSU + "flowing_spin"], items=[STAFF])
    use(fight, attack_name(fight))
    assert not any(c.display_name.startswith("Flowing Spin") for c in fight.legal_candidates())
    from combat.gate2_runtime_models import EconomyKind
    action = staff_action(fight)
    reaction = action.model_copy(update={"source_definition_id": "test:staff_reaction", "economy": EconomyKind.REACTION})
    fight.action_catalog[reaction.source_definition_id] = reaction
    fight._append_event("ATTACK_ROLLED", reaction.source_definition_id, actor_id=ME, target_ids=(AN,), payload={"provisional_hit": False})
    assert not any(c.display_name.startswith("Flowing Spin") for c in fight.legal_candidates())


@pytest.mark.parametrize("dc, selection, push", [(50, "Prone", 0), (50, "Push 10 feet", 10),
                                                (-40, "Prone", 5), (50, "No Reactions", 0)])
def test_sweeping_strike_saves_then_chooses_one_result_and_pays_once(dc, selection, push):
    fight = engine([BOJUTSU + "sweeping_strike"], dc=dc, items=[STAFF])
    answers(fight, {"bojutsu_result": [selection]})
    me, foe = fight.state.actors[ME], fight.state.actors[AN]
    before, start = me.resources["resource:core.stamina"], foe.position
    events = use(fight, staff_action(fight).display_name)
    assert me.resources["resource:core.stamina"] == before - 1
    assert any(e.event_type == "SAVE_ROLLED" and e.payload["dc"] == dc for e in events)
    assert fight.grid.distance_ft(start, foe.position) == push
    assert fight._has_condition(foe, "condition:typed.prone") == (dc == 50 and selection == "Prone")
    denied = next((c for c in foe.conditions.values() if c.condition_id == "condition:typed.reaction_denied"), None)
    assert (denied is not None) == (selection == "No Reactions")
    if denied is not None:
        assert denied.expires_on == f"START_OF_TURN_AT:{AN}:{foe.turns_started + 1}"
    if push == 0:
        use(fight, staff_action(fight).display_name)
        assert me.resources["resource:core.stamina"] == before - 1
    if denied is not None:
        fight.state.current_actor_id = AN
        fight.state.current_slot_index = fight.state.initiative_order.index(AN)
        fight._system_start_turn()
        assert not fight._has_condition(foe, "condition:typed.reaction_denied")


def test_sweeping_reposition_uses_a_physical_route_and_does_not_teleport_through_a_wall():
    fight = engine([BOJUTSU + "sweeping_strike"], items=[STAFF])
    fight.grid.blocked.add((5, 6))
    offered = []
    def provider(request):
        spec = request.get("extension_choice")
        if spec is None:
            return None, None
        options = spec["option_ids"]
        source = request["reaction_source_id"]
        if source.endswith("bojutsu_reposition"):
            offered.extend(options)
            selected = ["cell:4,7"]
        elif source.endswith("bojutsu_result"):
            selected = ["Reposition within reach"]
        else:
            selected = options[:spec["minimum_selections"]]
        return ReactionDecision(**{key: request[key] for key in ("checkpoint", "reactor_id", "reaction_source_id")},
                                selection="USE", option_ids=tuple(selected)), None
    fight.set_reaction_provider(provider)
    events = use(fight, staff_action(fight).display_name)
    assert "cell:6,6" not in offered  # detouring around the wall exceeds endpoint distance.
    assert fight.state.actors[AN].position == Position(x=4, y=7)
    movement = next(e for e in events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == AN)
    assert movement.payload["forced"] and not movement.payload.get("teleport")
    assert len(movement.payload["path"]) == 2


def test_flowing_spin_floors_a_small_staff_die_instead_of_adding_a_die(monkeypatch):
    from combat import factory_compiler

    original = factory_compiler._weapon_rows
    def small_staff(*args, **kwargs):
        rows = copy.deepcopy(original(*args, **kwargs))
        for row in rows:
            if row["item_id"] == STAFF:
                row["damage"] = "1d4 Bludgeoning"
        return rows
    monkeypatch.setattr(factory_compiler, "_weapon_rows", small_staff)
    fight = engine([BOJUTSU + "flowing_spin"], items=[STAFF])
    use(fight, staff_action(fight).display_name)
    candidate = next(c for c in fight.legal_candidates() if c.display_name.startswith("Flowing Spin") and AN in c.target_ids)
    action = fight.action_catalog[candidate.source_definition_id]
    assert action.parameters["typed"]["weapon"]["damage"] == {"count": 1, "sides": 6, "modifier": 2}
    events = use(fight, candidate.display_name)
    damage = next(e for e in events if e.event_type == "DAMAGE_ROLLED")
    assert len(damage.payload["dice"]) == 1
    assert not any(e.event_type == "ATTACK_ROLLED" and e.source_definition_id != action.source_definition_id for e in events)


def test_flowing_spin_requirement_is_satisfied_by_a_staff_attack_that_misses(monkeypatch):
    fight = engine([BOJUTSU + "flowing_spin"], items=[STAFF])
    fight.state.actors[AN].armor_class = 1000
    original = fight.roller.d20
    def force_miss(**kwargs):
        roll = original(**kwargs)
        if str(kwargs.get("reason")).startswith("ATTACK:"):
            return roll.model_copy(update={"natural_result": 2, "dice": (2,), "total": 2 + roll.modifier, "discarded": ()})
        return roll
    monkeypatch.setattr(fight.roller, "d20", force_miss)
    events = use(fight, staff_action(fight).display_name)
    assert any(e.event_type == "ATTACK_ROLLED" and not e.payload["provisional_hit"] for e in events)
    assert any(c.display_name.startswith("Flowing Spin") for c in fight.legal_candidates())


def test_sweeping_strike_can_be_declined_and_does_not_apply_to_unarmed_hits():
    fight = engine([BOJUTSU + "sweeping_strike"], items=[STAFF])
    before = fight.state.actors[ME].resources["resource:core.stamina"]
    use(fight, attack_name(fight))
    assert fight.state.actors[ME].resources["resource:core.stamina"] == before
    answers(fight, {"bojutsu_sweep": None})
    use(fight, staff_action(fight).display_name)
    assert fight.state.actors[ME].resources["resource:core.stamina"] == before


def test_flowing_spin_is_hidden_when_the_staff_is_disarmed():
    fight = engine([BOJUTSU + "flowing_spin"], items=[STAFF])
    action = staff_action(fight)
    use(fight, action.display_name)
    me = fight.state.actors[ME]
    fight._apply_condition(me, "condition:typed.disarmed", "test:fixture", AN, expires_on="UNTIL_REMOVED",
                          data={"disables_action": action.source_definition_id, "dropped_at": me.position.model_dump(mode="json")})
    assert not any(c.display_name.startswith("Flowing Spin") for c in fight.legal_candidates())


def test_flowing_spin_keeps_other_printed_damage_but_cannot_grant_a_nested_attack():
    fight = engine([BOJUTSU + "flowing_spin"], items=[STAFF])
    use(fight, staff_action(fight).display_name)
    candidate = next(c for c in fight.legal_candidates() if c.display_name.startswith("Flowing Spin") and AN in c.target_ids)
    action = fight.action_catalog[candidate.source_definition_id]
    # Model another source's on-hit damage and attack grant at the executor boundary.
    action.parameters["typed"]["effects"][0]["on_hit"].extend([
        {"type": "damage", "flat": 5, "damage_types": ["fire"], "applies_to": "target"},
        {"type": "attack", "attack_kind": "weapon", "count": 1,
         "on_hit": [{"type": "damage", "weapon_damage": True}]},
    ])
    events = use(fight, candidate.display_name)
    assert len([e for e in events if e.event_type == "ATTACK_ROLLED"]) == 1
    assert any(e.event_type == "DAMAGE_COMMITTED" and e.payload["damage_type"] == "FIRE"
               and e.payload["reduced_to"] == 5 for e in events)


def test_bojutsu_candidate_filter_is_inert_for_old_typing(monkeypatch):
    from combat.ext.bojutsu import allowed

    with monkeypatch.context() as scope:
        scope.setenv("R13_OLD_TYPING", "1")
        authority.cache_clear()
        try:
            fight = engine([BOJUTSU + "flowing_spin"], items=[STAFF])
            legacy = next(a for a in fight.action_catalog.values()
                          if a.parameters.get("typed", {}).get("source") == BOJUTSU + "flowing_spin")
            assert allowed(fight, fight.state.actors[ME], None, legacy) is None
            assert any(c.source_definition_id == legacy.source_definition_id for c in fight.legal_candidates())
        finally:
            authority.cache_clear()

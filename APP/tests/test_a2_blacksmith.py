"""Blacksmith second pass: actual service commits, choices and cold replay.

Test setup actions are sealed into the initial bundle, never injected into a
running engine. The table path uses the session's mechanical execute_intent;
the explicit session case protects that journal boundary as well.
"""
from combat.canonical import canonical_sha256
import pytest
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
from combat.ext.blacksmith_forge import mark_count, held_condition
from combat.ext import ironclad_blacksmith, physical_holds
from combat.ext.ironclad_blacksmith import TEMPER
from tests.worker2_support import fixture, candidate, settle, turn, reload, sealed_native_attack, OWNER, ALLY, FOE, ROOT

K = "tianxia.talent.blacksmith."
TWO_BEAT_LOCK = "condition:typed.blacksmith_two_beat_lock."
HAMMER = "Hammer the Mark"
REDUCE = "Forge-Fitted Armor: reduce nonmagical weapon damage by your Proficiency Bonus once each round"
PUSH = "Forge-Fitted Armor: ignore the next 5 feet of forced movement each round"


def armor_temper(actor):
    """Read the new armor family or the base's old shared family for red runs."""
    query = getattr(ironclad_blacksmith, "armor_temper", None)
    return query(actor) if query else held_condition(actor, TEMPER)


def seal(bundle, name, effects, *, target="SELF", economy="NONE", mundane=False):
    source = "action:test.a2." + bundle["actor_id"].split('.')[-1] + "." + name.replace(' ', '_')
    bundle["action_catalog"].append({
        "source_definition_id": source, "display_name": name, "owner_id": bundle["actor_id"],
        "economy": economy, "resolution_kind": "TYPED", "target_kind": target,
        # NONE alone no longer admits a turn action. These deliberately free
        # fixture actions opt into the same contract as compiler plug-in actions.
        "range_ft": 60, "costs": [], "parameters": {"free_primary": economy == "NONE", "typed": {
            "source": "test:a2", "effects": effects, "numbers": {"pb": 4, "save_dc": 30, "attack_bonus": 100},
            "mundane": mundane, "duration": {"kind": "instant"}, "riders": []}}})
    bundle["actor_template"]["action_ids"].append(source)
    bundle.pop("bundle_sha256", None)
    bundle["bundle_sha256"] = canonical_sha256(bundle)


def setup(bundles):
    seal(bundles[0], "Extra mark", [{"type": "mark", "mark": "Forge Mark", "applies_to": "self"}])
    for bundle in bundles:
        seal(bundle, "Fire packet", [{"type": "damage", "applies_to": "target", "flat": 10, "damage_types": ["fire"]}], target="ANY_CREATURE")
        for name, mundane, attacks in [("Mundane strike", True, True), ("Magic strike", False, True), ("Mundane hazard", True, False)]:
            seal(bundle, name, ([{"type": "attack", "attack_kind": "weapon", "attack_bonus": 100,
                                  "on_hit": [{"type": "damage", "applies_to": "target", "flat": 10, "damage_types": ["slashing"]}]}]
                                if attacks else [{"type": "damage", "applies_to": "target", "flat": 10, "damage_types": ["slashing"]}]),
                 target="ANY_CREATURE", mundane=mundane)
        seal(bundle, "Push ten", [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "on": "push"}], target="ANY_CREATURE")


def press(combat, table, mid, name, target=None, picks=None):
    if name == REDUCE:
        # Bind the same advertised option on the base and on this branch;
        # wording improvements must not be the reason the red test fails.
        row = next(c for c in combat._load_session(mid).engine.legal_candidates()
                   if c.source_definition_id.endswith("temper_pick.armor.armor_reduce"))
    else:
        row = candidate(combat, mid, name, target=target)
    return settle(table, mid, row.candidate_id, picks=picks)


def hp(combat, mid, actor=OWNER):
    return combat._load_session(mid).engine.state.actors[actor].current_hp


def armor_setup(bundles):
    setup(bundles)
    bundles[0]["actor_template"]["maximum_hp"] = 200
    bundles[0].pop("bundle_sha256", None)
    bundles[0]["bundle_sha256"] = canonical_sha256(bundles[0])


def strike(combat, table, mid, name, reduction):
    # A natural 1 still misses with +100. Read only this activation's damage,
    # never a stale roll from a prior strike, and retry a missed setup attack.
    for _ in range(4):
        before = hp(combat, mid)
        start = len(combat._load_session(mid).engine.events)
        source = candidate(combat, mid, name, target=OWNER).source_definition_id
        press(combat, table, mid, name, OWNER)
        engine = combat._load_session(mid).engine
        rolls = [e for e in engine.events[start:] if e.event_type == "DAMAGE_ROLLED" and e.source_definition_id == source]
        if not rolls:
            assert hp(combat, mid) == before
            continue
        raw = int(rolls[-1].payload["total"])
        assert before - hp(combat, mid) == max(0, raw - reduction)
        return
    raise AssertionError("The regression must deliver a real hit")


def test_two_beat_choice_payment_lock_and_cold_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, [K + "two_beat_temper"], bundle_transform=setup)
    before = combat._load_session(mid).engine.state.actors[OWNER].resources["resource:core.qi"]
    prompts = press(combat, table, mid, HAMMER, picks={"choice:needle.blacksmith_two_beat": ["two"]})
    assert prompts and "Hammer the Mark" in str(prompts[0])
    engine = reload(tmp_path, mid)
    assert mark_count(engine.state.actors[OWNER], OWNER) == 2
    assert held_condition(engine.state.actors[OWNER], TWO_BEAT_LOCK + OWNER)
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == before
    assert not any(c.display_name == "Extra mark" for c in engine.legal_candidates())
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert held_condition(engine.state.actors[OWNER], TWO_BEAT_LOCK + OWNER) is None
    press(combat, table, mid, HAMMER, picks={"choice:needle.blacksmith_two_beat": ["two"]})
    engine = reload(tmp_path, mid)
    assert mark_count(engine.state.actors[OWNER], OWNER) == 4
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == before - 1


def test_two_beat_decline_does_not_spend_free_scene_use(tmp_path):
    combat, table, mid = fixture(tmp_path, [K + "two_beat_temper"])
    press(combat, table, mid, HAMMER, picks={"choice:needle.blacksmith_two_beat": ["one"]})
    assert mark_count(reload(tmp_path, mid).state.actors[OWNER], OWNER) == 1
    turn(table, mid, ALLY); turn(table, mid, OWNER)
    before = hp(combat, mid)
    press(combat, table, mid, HAMMER, picks={"choice:needle.blacksmith_two_beat": ["two"]})
    engine = reload(tmp_path, mid)
    assert mark_count(engine.state.actors[OWNER], OWNER) == 3
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == 100
    assert hp(combat, mid) == before


def test_two_beat_workshop_free_each_round_and_reversible(tmp_path):
    combat, table, mid = fixture(tmp_path, [K + "two_beat_temper"], bundle_transform=setup)
    press(combat, table, mid, "Two-Beat Temper: working at a workshop or Apprentice's Anvil")
    for _ in range(2):
        press(combat, table, mid, HAMMER, picks={"choice:needle.blacksmith_two_beat": ["two"]})
        assert reload(tmp_path, mid).state.actors[OWNER].resources["resource:core.qi"] == 100
        turn(table, mid, ALLY); turn(table, mid, OWNER)
        # Spend the marks via the real Set Edge response, then mark next turn.
        press(combat, table, mid, "Set Edge")
        turn(table, mid, ALLY); turn(table, mid, OWNER)
    press(combat, table, mid, "Two-Beat Temper: working away from a workshop")
    press(combat, table, mid, HAMMER, picks={"choice:needle.blacksmith_two_beat": ["two"]})
    assert reload(tmp_path, mid).state.actors[OWNER].resources["resource:core.qi"] == 99


def test_unowned_hammer_is_one_mark_through_session_journal(tmp_path):
    # No sphere means no Hammer button; owning a different Blacksmith talent
    # enrolls the chassis without enrolling Two-Beat Temper.
    combat, table, mid = fixture(tmp_path / "smith", [K + "quench_in_breath"])
    session = combat._load_session(mid)
    row = candidate(combat, mid, HAMMER)
    session.mechanical.execute_intent(ActionIntent(
        intent_id="a2:session", actor_id=row.actor_id, decision_id=row.decision_id,
        candidate_id=row.candidate_id, state_version=row.state_version,
        target_ids=row.target_ids, destination=row.destination))
    engine = CombatService(ROOT, tmp_path / "smith")._load_session(mid).engine
    assert mark_count(engine.state.actors[OWNER], OWNER) == 1


def test_furnace_discipline_requires_mark_or_declared_tool(tmp_path):
    combat, table, mid = fixture(tmp_path, [K + "furnace_discipline"], bundle_transform=setup)
    press(combat, table, mid, "Fire packet", OWNER)
    assert hp(combat, mid) == 50
    press(combat, table, mid, HAMMER)
    press(combat, table, mid, "Fire packet", OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].current_hp == 45
    # Set Edge spends the last Forge Mark; no unconditional resistance remains.
    turn(table, mid, ALLY); turn(table, mid, OWNER)
    press(combat, table, mid, "Set Edge")
    press(combat, table, mid, "Fire packet", OWNER)
    assert hp(combat, mid) == 35
    press(combat, table, mid, "Furnace Discipline: holding a Blacksmith tool")
    press(combat, table, mid, "Fire packet", OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].current_hp == 30
    press(combat, table, mid, "Furnace Discipline: no Blacksmith tool held")
    press(combat, table, mid, "Fire packet", OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].current_hp == 20


def temper(combat, table, mid, pick):
    press(combat, table, mid, HAMMER)
    turn(table, mid, ALLY); turn(table, mid, OWNER)
    press(combat, table, mid, pick)
    press(combat, table, mid, "Fit Armor (1 minute)")


def test_fitted_armor_reduction_is_qualified_and_refreshes_each_round(tmp_path):
    combat, table, mid = fixture(tmp_path, [K + "forge_fitted_armor"], bundle_transform=armor_setup)
    temper(combat, table, mid, REDUCE)
    assert armor_temper(reload(tmp_path, mid).state.actors[OWNER]).data["benefit"] == "armor_reduce"
    strike(combat, table, mid, "Magic strike", 0)
    before = hp(combat, mid)
    press(combat, table, mid, "Mundane hazard", OWNER)
    assert hp(combat, mid) == before - 10
    strike(combat, table, mid, "Mundane strike", 4)
    assert reload(tmp_path, mid).state.actors[OWNER].current_hp == hp(combat, mid)
    strike(combat, table, mid, "Mundane strike", 0)
    turn(table, mid, ALLY); turn(table, mid, OWNER)
    strike(combat, table, mid, "Mundane strike", 4)
    assert reload(tmp_path, mid).state.actors[OWNER].current_hp == hp(combat, mid)


def test_fitted_armor_ac_does_not_stack_and_replacement_ends_bonus(tmp_path):
    combat, table, mid = fixture(tmp_path, [K + "forge_fitted_armor"], bundle_transform=setup)
    temper(combat, table, mid, "Forge-Fitted Armor: +1 AC")
    engine = reload(tmp_path, mid)
    assert engine._ac_modifier(engine.state.actors[OWNER]) == 1
    turn(table, mid, ALLY); turn(table, mid, OWNER)
    temper(combat, table, mid, REDUCE)
    engine = reload(tmp_path, mid)
    assert engine._ac_modifier(engine.state.actors[OWNER]) == 0
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == 98


def test_two_beat_ai_chooses_automatically_and_does_not_invent_workshop(tmp_path):
    combat, table, mid = fixture(tmp_path, [K + "two_beat_temper"], ask=False,
                                 modes={OWNER: "LOCAL_AUTO", ALLY: "MANUAL", FOE: "MANUAL"})
    session = combat._load_session(mid)
    row = candidate(combat, mid, HAMMER)
    session.mechanical.execute_intent(ActionIntent(
        intent_id="a2:ai", actor_id=row.actor_id, decision_id=row.decision_id,
        candidate_id=row.candidate_id, state_version=row.state_version,
        target_ids=row.target_ids, destination=row.destination))
    engine = reload(tmp_path, mid)
    assert mark_count(engine.state.actors[OWNER], OWNER) == 2
    assert not any("workshop" in c.condition_id for c in engine.state.actors[OWNER].conditions.values())


def test_fitted_armor_push_refreshes_each_round_and_cold_reload(tmp_path):
    # Row 8 is clear; row 6's central pillar would stop the second push.
    positions = {OWNER: {"x": 6, "y": 8}, ALLY: {"x": 5, "y": 8}, FOE: {"x": 2, "y": 2}}
    combat, table, mid = fixture(tmp_path, [K + "forge_fitted_armor"], bundle_transform=setup, positions=positions)
    temper(combat, table, mid, PUSH)
    turn(table, mid, ALLY)
    press(combat, table, mid, "Push ten", OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].position.x == 7
    press(combat, table, mid, "Push ten", OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].position.x == 9
    turn(table, mid, OWNER); turn(table, mid, ALLY)
    press(combat, table, mid, "Push ten", OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].position.x == 10


def test_fitted_armor_native_multiattack_spends_one_reduction_per_round(tmp_path):
    def native_setup(bundles):
        armor_setup(bundles)
        source = sealed_native_attack(bundles[2], "Native sword", damage_type="SLASHING",
                                      count=1, sides=2, modifier=9, attack_bonus=100, attacks=2)
        action = next(row for row in bundles[2]["action_catalog"] if row["source_definition_id"] == source)
        # A native action carrying explicit source provenance, as the generic
        # defense reader requires; no inferred magical/mundane equipment fact.
        action["parameters"]["typed"] = {"mundane": True, "effects": [{"type": "attack", "attack_kind": "weapon"}]}
        bundles[2].pop("bundle_sha256", None)
        bundles[2]["bundle_sha256"] = canonical_sha256(bundles[2])

    combat, table, mid = fixture(tmp_path, [K + "forge_fitted_armor"], bundle_transform=native_setup)
    temper(combat, table, mid, REDUCE)
    for iteration in range(2):
        turn(table, mid, FOE)
        before = hp(combat, mid)
        start = len(combat._load_session(mid).engine.events)
        source = candidate(combat, mid, "Native sword", target=OWNER).source_definition_id
        press(combat, table, mid, "Native sword", OWNER)
        engine = combat._load_session(mid).engine
        packets = [e for e in engine.events[start:] if e.event_type == "DAMAGE_ROLLED" and e.source_definition_id == source]
        # The fixed first activation hits twice, proving only one reduction.
        # A later natural-1 miss must not borrow the first activation's roll.
        assert len(packets) == 2 if iteration == 0 else len(packets) >= 1
        assert before - hp(combat, mid) == sum(int(e.payload["total"]) for e in packets) - 4
        assert reload(tmp_path, mid).state.actors[OWNER].current_hp == hp(combat, mid)
        turn(table, mid, OWNER)


def test_two_beat_follows_hammer_source_on_suffixed_action_variant(tmp_path):
    from copy import deepcopy

    def variant_setup(bundles):
        bundle = bundles[0]
        original = next(row for row in bundle["action_catalog"] if row["display_name"] == HAMMER)
        variant = deepcopy(original)
        variant["source_definition_id"] += ".test_variant"
        variant["display_name"] = "Variant Hammer"
        bundle["action_catalog"].append(variant)
        bundle["actor_template"]["action_ids"].append(variant["source_definition_id"])
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, mid = fixture(tmp_path, [K + "two_beat_temper"], bundle_transform=variant_setup)
    press(combat, table, mid, "Variant Hammer", picks={"choice:needle.blacksmith_two_beat": ["two"]})
    engine = reload(tmp_path, mid)
    assert mark_count(engine.state.actors[OWNER], OWNER) == 2
    assert held_condition(engine.state.actors[OWNER], TWO_BEAT_LOCK + OWNER)


def test_armor_temper_preserves_weapon_temper_and_replaces_only_armor(tmp_path):
    combat, table, mid = fixture(tmp_path, [K + "forge_fitted_weapon", K + "forge_fitted_armor"], bundle_transform=setup)
    for _ in range(3):
        press(combat, table, mid, "Extra mark")
    press(combat, table, mid, "Forge-Fitted Weapon: +1 to damage rolls")
    press(combat, table, mid, "Set Edge (1 minute)")
    turn(table, mid, ALLY); turn(table, mid, OWNER)
    press(combat, table, mid, "Forge-Fitted Armor: +1 AC")
    press(combat, table, mid, "Fit Armor (1 minute)")
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert held_condition(actor, TEMPER).data["benefit"] == "damage"
    assert armor_temper(actor).data["benefit"] == "armor_ac"
    assert engine._ac_modifier(actor) == 1
    turn(table, mid, ALLY); turn(table, mid, OWNER)
    press(combat, table, mid, "Fit Armor: Reduce Weapon Damage")
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert held_condition(actor, TEMPER).data["benefit"] == "damage"
    assert armor_temper(actor).data["benefit"] == "armor_reduce"
    assert engine._ac_modifier(actor) == 0


def session_pick(combat, tmp_path, mid, suffix):
    """Commit a picker through the session journal, then cold-load the saved fight."""
    session = combat._load_session(mid)
    row = next(c for c in session.engine.legal_candidates()
               if c.source_definition_id.endswith("temper_pick." + suffix))
    session.mechanical.execute_intent(ActionIntent(
        intent_id="a2:pick:" + suffix, actor_id=row.actor_id, decision_id=row.decision_id,
        candidate_id=row.candidate_id, state_version=row.state_version,
        target_ids=row.target_ids, destination=row.destination))
    return reload(tmp_path, mid).state.actors[OWNER]


@pytest.mark.parametrize("first", ["armor", "weapon"])
def test_interleaved_temper_selections_survive_service_commit_and_cold_reload(tmp_path, first):
    combat, table, mid = fixture(tmp_path, [K + "forge_fitted_weapon", K + "forge_fitted_armor"],
                                 bundle_transform=setup)
    for _ in range(3):
        press(combat, table, mid, "Extra mark")
    choices = {"armor": "armor.armor_reduce", "weapon": "weapon.damage"}
    second = "weapon" if first == "armor" else "armor"
    session_pick(combat, tmp_path, mid, choices[first])
    session_pick(combat, tmp_path, mid, choices[second])
    # Replace just the second choice, then restore it before either response.
    session_pick(combat, tmp_path, mid, "weapon.attack" if second == "weapon" else "armor.armor_ac")
    session_pick(combat, tmp_path, mid, choices[second])
    for kind in (first, second):
        press(combat, table, mid, "Fit Armor (1 minute)" if kind == "armor" else "Set Edge (1 minute)")
        actor = reload(tmp_path, mid).state.actors[OWNER]
        condition = armor_temper(actor) if kind == "armor" else held_condition(actor, TEMPER)
        assert condition.data["benefit"] == ("armor_reduce" if kind == "armor" else "damage")
        turn(table, mid, ALLY); turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert armor_temper(actor).data["benefit"] == "armor_reduce"
    assert held_condition(actor, TEMPER).data["benefit"] == "damage"
    assert engine._ac_modifier(actor) == 0
    assert actor.resources["resource:core.qi"] == 98


def test_reduction_picker_names_damage_types_and_attack_scope_after_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, [K + "forge_fitted_armor"], bundle_transform=setup)
    actor = session_pick(combat, tmp_path, mid, "armor.armor_reduce")
    expected = ("Forge-Fitted Armor: reduce nonmagical Bludgeoning, Piercing, or Slashing "
                "attack damage by your Proficiency Bonus once each round")
    engine = reload(tmp_path, mid)
    action = next(a for a in engine.action_catalog.values()
                  if a.source_definition_id.endswith("temper_pick.armor.armor_reduce"))
    assert action.display_name == expected
    assert any(c.data.get("label") == expected for c in actor.conditions.values())
    press(combat, table, mid, "Extra mark")
    press(combat, table, mid, "Fit Armor (1 minute)")
    assert armor_temper(reload(tmp_path, mid).state.actors[OWNER]).data["label"] == (
        "Temporary Temper: " + expected.removeprefix("Forge-Fitted Armor: ") + " for 1 minute")


@pytest.mark.parametrize("kind,benefit", [("weapon", "damage"), ("armor", "armor_reduce")])
def test_legacy_temper_selection_remains_readable_after_cold_reload(tmp_path, kind, benefit):
    def legacy_setup(bundles):
        setup(bundles)
        bundle = bundles[0]
        for action in bundle["action_catalog"]:
            for effect in action.get("parameters", {}).get("typed", {}).get("effects", []):
                if effect.get("type") == "blacksmith_temper_pick":
                    effect.pop("independent", None)
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, mid = fixture(tmp_path, [K + "forge_fitted_weapon", K + "forge_fitted_armor"],
                                 bundle_transform=legacy_setup)
    actor = session_pick(combat, tmp_path, mid, kind + "." + benefit)
    assert held_condition(actor, ironclad_blacksmith.TEMPER_PICK).data["benefit"] == benefit
    press(combat, table, mid, "Extra mark")
    press(combat, table, mid, "Set Edge (1 minute)" if kind == "weapon" else "Fit Armor (1 minute)")
    actor = reload(tmp_path, mid).state.actors[OWNER]
    condition = held_condition(actor, TEMPER) if kind == "weapon" else armor_temper(actor)
    assert condition.data["benefit"] == benefit


def test_two_beat_does_not_offer_or_charge_doubling_above_mark_cap(tmp_path):
    combat, table, mid = fixture(tmp_path, [K + "two_beat_temper"], bundle_transform=setup)
    for _ in range(3):
        press(combat, table, mid, "Extra mark")
    prompts = press(combat, table, mid, HAMMER)
    assert not prompts
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert mark_count(actor, OWNER) == 4
    assert actor.resources["resource:core.qi"] == 100
    assert held_condition(actor, TWO_BEAT_LOCK + OWNER) is None


def test_fitted_armor_prone_save_temper_requires_payment_to_last_a_minute(tmp_path):
    combat, table, mid = fixture(tmp_path, [K + "forge_fitted_armor"], bundle_transform=setup)
    for _ in range(2):
        press(combat, table, mid, "Extra mark")
    press(combat, table, mid, "Fit Armor: Advantage on saves against being knocked Prone")
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert armor_temper(actor).data["benefit"] == "armor_prone"
    assert actor.resources["resource:core.qi"] == 100
    turn(table, mid, ALLY); turn(table, mid, OWNER)
    assert armor_temper(reload(tmp_path, mid).state.actors[OWNER]) is None
    press(combat, table, mid, "Forge-Fitted Armor: Advantage on saving throws against being knocked Prone")
    press(combat, table, mid, "Fit Armor (1 minute)")
    turn(table, mid, ALLY); turn(table, mid, OWNER)
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert armor_temper(actor).data["benefit"] == "armor_prone"
    assert armor_temper(actor).data["recurring"] == 1
    assert actor.resources["resource:core.qi"] == 99
    press(combat, table, mid, "Extra mark")
    press(combat, table, mid, "Fit Armor: +1 AC")
    engine = reload(tmp_path, mid)
    assert engine._ac_modifier(engine.state.actors[OWNER]) == 1
    turn(table, mid, ALLY); turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert armor_temper(engine.state.actors[OWNER]) is None
    assert engine._ac_modifier(engine.state.actors[OWNER]) == 0

# ------------------------------------------------------------------ Armor Knows Its Owner (P4)
STAND = "Fit Armor: Stand from Prone"
END_GRAPPLE = "Fit Armor: End a Grappled state"
SAVE_ADVANTAGE = "Fit Armor: Advantage on the next Strength or Dexterity saving throw"


def armor_knows_setup(bundles):
    """Prone on the smith, two ordinary grips and one magical grip, and Strength, Dexterity and Constitution saves."""
    setup(bundles)
    seal(bundles[0], "Lie down", [{"type": "condition", "condition": "prone", "applies_to": "self"}])
    for name, hold_kind in [("Ordinary grip", "ordinary_physical"), ("Magical grip", None)]:
        condition = {"type": "condition", "condition": "grappled", "applies_to": "target", "duration": "until_removed"}
        if hold_kind:
            condition["hold_kind"] = hold_kind
        seal(bundles[2], name, [condition], target="ANY_CREATURE")
    for ability, name in [("STR", "Strength save"), ("DEX", "Dexterity save"), ("CON", "Constitution save")]:
        seal(bundles[2], name, [{"type": "save", "ability": ability, "applies_to": "target",
                                 "on_fail": [{"type": "damage", "applies_to": "target", "flat": 1,
                                              "damage_types": ["bludgeoning"]}]}], target="ANY_CREATURE")


# Armor Knows Its Owner fits "a willing creature wearing armor or carrying a shield": the positive tests carry one.
SHIELD_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.armor.shield", "name": "Shield", "quantity": 1}]}}


def armor_knows_game(tmp_path):
    return fixture(tmp_path, [K + "armor_knows_its_owner"], bundle_transform=armor_knows_setup, owner_kit=SHIELD_KIT)


def armor_knows_ally_setup(bundles):
    """The smith-side setup plus a prone toggle on the ally, so one fit can be aimed at either creature."""
    armor_knows_setup(bundles)
    seal(bundles[1], "Lie down", [{"type": "condition", "condition": "prone", "applies_to": "self"}])


def armor_knows_ally_game(tmp_path, **kwargs):
    kwargs.setdefault("owner_kit", SHIELD_KIT)
    kwargs.setdefault("ally_kit", SHIELD_KIT)
    return fixture(tmp_path, [K + "armor_knows_its_owner"], bundle_transform=armor_knows_ally_setup, **kwargs)


def action_field(engine, source_definition_id, field):
    row = engine.action_catalog.get(source_definition_id)
    return row.get(field) if isinstance(row, dict) else getattr(row, field, None)


def fit_armor_rows(engine):
    """The three Armor Knows Its Owner Fit Armor buttons and the creatures each one is offered for."""
    names = {STAND, END_GRAPPLE, SAVE_ADVANTAGE}
    return [c for c in engine.legal_candidates()
            if getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) in names]


def prone(engine, actor):
    return any(c.condition_id == "condition:typed.prone" for c in engine.state.actors[actor].conditions.values())


def grapples(engine, actor=OWNER):
    return [c for c in engine.state.actors[actor].conditions.values() if c.condition_id == "condition:typed.grappled"]


def no_temper(actor):
    """Stand and End Grappled are transitions: neither leaves a Temper behind."""
    return armor_temper(actor) is None and held_condition(actor, TEMPER) is None


def test_armor_knows_stand_runs_the_stand_transition_and_spends_no_movement(tmp_path):
    combat, table, mid = armor_knows_game(tmp_path)
    press(combat, table, mid, "Lie down", OWNER)
    assert any(c.condition_id == "condition:typed.prone"
               for c in reload(tmp_path, mid).state.actors[OWNER].conditions.values())
    press(combat, table, mid, "Extra mark")
    before = reload(tmp_path, mid).state.actors[OWNER].movement_remaining_ft
    assert before > 0
    # The three Armor Knows buttons now take "a willing creature", so the smith is an explicit recipient itself.
    press(combat, table, mid, STAND, OWNER)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert not any(c.condition_id == "condition:typed.prone" for c in actor.conditions.values())
    stood = [e for e in engine.events if e.event_type == "STOOD_UP" and e.actor_id == OWNER]
    assert stood and stood[-1].payload["cost_ft"] == 0
    assert stood[-1].payload["movement_after"] == actor.movement_remaining_ft == before
    assert no_temper(actor)
    assert actor.bonus_action_available is False  # still the printed bonus-action result


def test_armor_knows_end_grappled_ends_exactly_one_ordinary_hold_and_keeps_a_magical_one(tmp_path):
    combat, table, mid = armor_knows_game(tmp_path)
    turn(table, mid, FOE)
    for name in ("Ordinary grip", "Ordinary grip", "Magical grip"):
        press(combat, table, mid, name, OWNER)
    engine = reload(tmp_path, mid)
    held = grapples(engine)
    ordinary = {c.instance_id for c in held if physical_holds.source(engine, c)[0]}
    magical = {c.instance_id for c in held} - ordinary
    assert len(held) == 3 and len(ordinary) == 2 and len(magical) == 1
    turn(table, mid, OWNER)
    press(combat, table, mid, "Extra mark")
    press(combat, table, mid, END_GRAPPLE, OWNER)
    engine = reload(tmp_path, mid)
    left = {c.instance_id for c in grapples(engine)}
    assert len(left) == 2
    assert len(ordinary - left) == 1  # one hold ended, not both
    assert magical <= left            # the magical hold is not ordinary, so it stays
    assert no_temper(engine.state.actors[OWNER])


def test_armor_knows_save_advantage_is_used_once_on_a_strength_save(tmp_path):
    combat, table, mid = armor_knows_game(tmp_path)
    press(combat, table, mid, "Extra mark")
    press(combat, table, mid, SAVE_ADVANTAGE, OWNER)
    turn(table, mid, FOE)
    for _ in range(2):
        press(combat, table, mid, "Strength save", OWNER)
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == OWNER]
    assert [e.payload["mode"] for e in saves] == ["ADVANTAGE", "NORMAL"]
    assert no_temper(engine.state.actors[OWNER])


def test_armor_knows_fits_a_willing_ally_as_well_as_the_smith(tmp_path):
    """The printed target is "a willing creature": the smith and its ally are offered, the enemy never is."""
    combat, table, mid = armor_knows_ally_game(tmp_path)
    engine = combat._load_session(mid).engine
    rows = fit_armor_rows(engine)
    assert {tuple(c.target_ids) for c in rows} == {(OWNER,), (ALLY,)}
    assert {action_field(engine, c.source_definition_id, "target_kind") for c in rows} == {"ALLY_OR_SELF"}
    assert {action_field(engine, c.source_definition_id, "range_ft") for c in rows} == {5}


def test_armor_knows_stands_a_prone_ally_up_for_free_and_the_smith_pays(tmp_path):
    """The free stand lands on the ally the smith fitted; the Forge Mark is still the smith's."""
    combat, table, mid = armor_knows_ally_game(tmp_path)
    turn(table, mid, ALLY)          # the ally lies down on its own turn
    press(combat, table, mid, "Lie down", ALLY)
    turn(table, mid, OWNER)         # and it is still prone when the smith's next turn starts
    engine = reload(tmp_path, mid)
    assert prone(engine, ALLY) and not prone(engine, OWNER)
    moving = engine.state.actors[ALLY].movement_remaining_ft
    press(combat, table, mid, "Extra mark")
    marks = mark_count(reload(tmp_path, mid).state.actors[OWNER], OWNER)
    press(combat, table, mid, STAND, ALLY)
    engine = reload(tmp_path, mid)
    assert not prone(engine, ALLY) and not prone(engine, OWNER)
    stood = [e for e in engine.events if e.event_type == "STOOD_UP"]
    assert [e.actor_id for e in stood] == [ALLY]  # never the smith
    assert stood[-1].payload["cost_ft"] == 0
    assert engine.state.actors[ALLY].movement_remaining_ft == moving
    assert mark_count(engine.state.actors[OWNER], OWNER) == marks - 1  # the smith pays
    assert mark_count(engine.state.actors[ALLY], ALLY) == 0           # the ally never does
    assert no_temper(engine.state.actors[ALLY]) and no_temper(engine.state.actors[OWNER])


def test_armor_knows_ends_one_ordinary_hold_on_the_ally_and_keeps_a_magical_one(tmp_path):
    combat, table, mid = armor_knows_ally_game(tmp_path)
    turn(table, mid, FOE)
    for name in ("Ordinary grip", "Ordinary grip", "Magical grip"):
        press(combat, table, mid, name, ALLY)
    engine = reload(tmp_path, mid)
    held = grapples(engine, ALLY)
    ordinary = {c.instance_id for c in held if physical_holds.source(engine, c)[0]}
    magical = {c.instance_id for c in held} - ordinary
    assert len(held) == 3 and len(ordinary) == 2 and len(magical) == 1
    assert grapples(engine, OWNER) == []
    turn(table, mid, OWNER)
    press(combat, table, mid, "Extra mark")
    press(combat, table, mid, END_GRAPPLE, ALLY)
    engine = reload(tmp_path, mid)
    left = {c.instance_id for c in grapples(engine, ALLY)}
    assert len(left) == 2
    assert len(ordinary - left) == 1  # one hold ended, not both
    assert magical <= left            # the magical hold is not ordinary, so it stays
    assert grapples(engine, OWNER) == []
    assert no_temper(engine.state.actors[ALLY]) and no_temper(engine.state.actors[OWNER])


def test_armor_knows_gives_the_ally_one_advantage_on_strength_or_dexterity(tmp_path):
    """One shot on the bearer's next Strength or Dexterity save, still the smith's turn that ends it."""
    combat, table, mid = armor_knows_ally_game(tmp_path)
    press(combat, table, mid, "Extra mark")
    press(combat, table, mid, SAVE_ADVANTAGE, ALLY)
    engine = reload(tmp_path, mid)
    temper = held_condition(engine.state.actors[ALLY], TEMPER)
    assert temper is not None
    assert temper.source_actor_id == OWNER                     # the smith's effect, carried by the ally
    assert temper.expires_on == f"START_OF_TURN_AT:{OWNER}:{engine.state.actors[OWNER].turns_started + 1}"
    assert no_temper(engine.state.actors[OWNER])               # nothing left on the smith
    turn(table, mid, FOE)
    for name in ("Constitution save", "Dexterity save", "Strength save"):
        press(combat, table, mid, name, ALLY)
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == ALLY]
    # Constitution is neither: the Temper waits. The Dexterity save spends it; the Strength save is ordinary again.
    assert [e.payload["mode"] for e in saves] == ["NORMAL", "ADVANTAGE", "NORMAL"]
    assert no_temper(engine.state.actors[ALLY])


def test_armor_knows_ally_advantage_ends_at_the_start_of_the_smiths_next_turn(tmp_path):
    combat, table, mid = armor_knows_ally_game(tmp_path)
    press(combat, table, mid, "Extra mark")
    press(combat, table, mid, SAVE_ADVANTAGE, ALLY)
    assert held_condition(reload(tmp_path, mid).state.actors[ALLY], TEMPER) is not None
    turn(table, mid, ALLY)
    turn(table, mid, FOE)
    assert held_condition(reload(tmp_path, mid).state.actors[ALLY], TEMPER) is not None
    turn(table, mid, OWNER)
    assert no_temper(reload(tmp_path, mid).state.actors[ALLY])


def test_armor_knows_is_not_offered_to_an_unarmored_ally(tmp_path):
    """The printed trigger needs the ally wearing armor or carrying a shield; an unarmored ally gets no Fit Armor result."""
    combat, table, mid = armor_knows_ally_game(tmp_path, ally_kit=None)
    engine = combat._load_session(mid).engine
    assert {tuple(c.target_ids) for c in fit_armor_rows(engine)} == {(OWNER,)}


def test_armor_knows_is_not_offered_to_an_unarmored_smith_or_ally(tmp_path):
    combat, table, mid = armor_knows_ally_game(tmp_path, owner_kit=None, ally_kit=None)
    engine = combat._load_session(mid).engine
    assert fit_armor_rows(engine) == []


def test_armor_knows_is_not_offered_for_an_ally_out_of_touch(tmp_path):
    combat, table, mid = armor_knows_ally_game(tmp_path, ally_position={"x": 5, "y": 6})
    engine = combat._load_session(mid).engine
    # 30 feet away: outside the printed Fit Armor reach, so the smith may only fit itself.
    assert {tuple(c.target_ids) for c in fit_armor_rows(engine)} == {(OWNER,)}

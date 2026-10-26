"""Review regressions through table -> session execute_intent -> cold service load.

Probes are compiled fixture actions/reactions, never production authority edits.
They exercise native mixed weapon delivery and typed generic reaction plumbing.
No browser is started; any future browser check must be explicitly opted into
and run by the lead outside the sandbox.
"""
import copy

import pytest

from tests import r1i_service_support as s
from tests.test_devil_qi_augment_service import (
    AUGMENT, COUNTER, DEVIL_QI, add_probe, add_consecrated_probe, add_counter_probe,
    cold, commit_first_choice, damage_totals, play, probe_action, seal, assert_original_damage_unchanged,
)

MIXED = "tianxia.forged_technique.test.devil_qi_mixed"


def end_turn(table, mid):
    menu = table.state(mid)["menu"]
    result = table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0, [])
    assert result["status"] == "COMMITTED", result


def turn_to(table, mid, who):
    for _ in range(4):
        if table.state(mid)["menu"]["actor_id"] == who:
            return
        end_turn(table, mid)
    raise AssertionError(who)


def mixed_probe(bundles):
    add_probe(bundles)
    owner = next(b for b in bundles if b["actor_id"] == s.OWNER)
    # Reuse the fighter's actual compiled weapon profile; fixed base damage
    # removes dice noise without bypassing attack, defenses or persistence.
    weapon = copy.deepcopy(next(a["parameters"]["typed"]["weapon"] for a in owner["action_catalog"]
        if a.get("parameters", {}).get("typed", {}).get("weapon")))
    weapon["damage"] = {"count": 1, "sides": 8, "modifier": 0}
    weapon["fixed_damage"] = 8
    weapon["damage_type"] = "SLASHING"
    weapon["damage_types"] = ["SLASHING"]
    probe_action(owner, "Mixed Cultivation Strike", MIXED, [{"type": "attack", "attack_kind": "weapon",
        "on_hit": [{"type": "damage", "applies_to": "target", "weapon_damage": True},
                   {"type": "damage", "applies_to": "target", "flat": 7, "damage_types": ["force"]}]}], weapon=weapon)
    foe = next(b for b in bundles if b["actor_id"] == s.FOE)
    foe["typed_passives"].append({"block": "defense", "feature_id": "test:slashing_resistance",
        "kind": "resistance", "damage_types": ["SLASHING"]})
    seal(foe)


@pytest.mark.parametrize("packet", ["weapon", "technique"])
def test_mixed_packet_selection_precedes_damage_and_preserves_defenses(tmp_path, packet):
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], wide=True, bundle_transform=mixed_probe)
    engine = cold(combat, tmp_path, mid)
    start, hp = len(engine.events), engine.state.actors[s.FOE].current_hp
    candidate = s.candidate(table, mid, "Mixed Cultivation Strike", s.FOE)
    # The first prompt is the pre-damage selector. A cold reload sees neither
    # provisional damage nor a Devil Qi payment while the intent is paused.
    menu = table.state(mid)["menu"]
    paused = table.act(mid, candidate, menu["decision_id"], menu["state_version"], 0, [])
    assert paused["status"] == "REACTION_REQUIRED", paused
    assert paused["reaction"]["context"]["checkpoint"].endswith(":packet")
    assert cold(combat, tmp_path, mid).state.actors[s.FOE].current_hp == hp
    assert len(cold(combat, tmp_path, mid).events) == start
    prompts = play(combat, table, mid, candidate, "Speed", packet=packet)
    assert sum(p["context"]["checkpoint"].endswith(":packet") for p in prompts) == 1
    engine = cold(combat, tmp_path, mid)
    commits = [e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED" and s.FOE in e.target_ids]
    expected = ["SLASHING", "PSYCHIC", "FORCE"] if packet == "weapon" else ["SLASHING", "FORCE", "PSYCHIC"]
    assert [e.payload["damage_type"] for e in commits] == expected
    assert next(e.payload["hp_damage"] for e in commits if e.payload["damage_type"] == "SLASHING") == 4
    assert next(e.payload["hp_damage"] for e in commits if e.payload["damage_type"] == "FORCE") == 7
    rolled, added, original = damage_totals(engine, start)
    assert added == rolled and original == 11
    assert engine.state.actors[s.FOE].current_hp == hp - 11 - rolled
    assert engine.state.actors[s.OWNER].resources[DEVIL_QI] == 1
    assert all(e.source_definition_id == MIXED for e in commits)
    augment = next(e for e in commits if e.payload["damage_type"] == "PSYCHIC")
    assert augment.payload["display_source_id"] == AUGMENT + ".damage"


def test_mixed_decline_allows_later_technique_packet_in_same_activation(tmp_path):
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], wide=True, bundle_transform=mixed_probe)
    prompts = play(combat, table, mid, s.candidate(table, mid, "Mixed Cultivation Strike", s.FOE),
                   "Speed", packet="weapon", decline_first=True)
    assert sum(p["context"]["checkpoint"].endswith(":offer") for p in prompts) == 2
    engine = cold(combat, tmp_path, mid)
    assert engine.state.actors[s.OWNER].resources[DEVIL_QI] == 1
    assert any(m.source_definition_id == AUGMENT + ".speed" for m in engine.state.actors[s.FOE].modifiers.values())


@pytest.mark.parametrize("packet", ["weapon", "technique"])
def test_selected_packet_uses_its_remaining_defenses_not_the_other_packet(tmp_path, packet):
    def prepare(bundles):
        mixed_probe(bundles)
        owner = next(b for b in bundles if b["actor_id"] == s.OWNER)
        action = next(a for a in owner["action_catalog"] if a["source_definition_id"] == MIXED)
        action["parameters"]["typed"]["effects"][0]["on_hit"][1]["damage_types"] = ["psychic"]
        seal(owner)
        foe = next(b for b in bundles if b["actor_id"] == s.FOE)
        probe_action(foe, "Next Psychic Resistance", "test:next_psychic_resistance",
            [{"type": "resistance_next", "applies_to": "self", "damage_types": ["psychic"],
              "expires_on": "UNTIL_REMOVED"}])
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], wide=True, bundle_transform=prepare)
    turn_to(table, mid, s.FOE)
    commit_first_choice(table, mid, s.candidate(table, mid, "Next Psychic Resistance", s.OWNER))
    turn_to(table, mid, s.OWNER)
    engine = cold(combat, tmp_path, mid)
    assert any(m.target_field == "damage_resistance_next" for m in engine.state.actors[s.FOE].modifiers.values())
    start = len(engine.events)
    play(combat, table, mid, s.candidate(table, mid, "Mixed Cultivation Strike", s.FOE), "Speed", packet=packet)
    engine = cold(combat, tmp_path, mid)
    commits = [e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED" and s.FOE in e.target_ids]
    added = next(e for e in commits if e.payload.get("display_source_id") == AUGMENT + ".damage")
    original = next(e for e in commits if e.payload["damage_type"] == "PSYCHIC" and e is not added)
    roll = next(e.payload["total"] for e in engine.events[start:] if e.event_type == "DAMAGE_ROLLED"
                and e.payload.get("display_source_id") == AUGMENT + ".damage")
    assert added.payload["hp_damage"] == (roll // 2 if packet == "weapon" else roll)
    assert original.payload["hp_damage"] == (7 if packet == "weapon" else 3)
    assert not any(m.target_field == "damage_resistance_next" for m in engine.state.actors[s.FOE].modifiers.values())


def test_speed_refreshes_across_different_techniques_without_removing_native_speed(tmp_path):
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], wide=True, bundle_transform=add_counter_probe)
    # Establish this technique's native speed effect before an activation that
    # applies both it and a separately named Augment speed rider. Each source
    # must refresh its own old modifier, even though they share a hit cache.
    turn_to(table, mid, s.FOE)
    play(combat, table, mid, s.candidate(table, mid, "Trigger Cultivation Counter", s.OWNER),
         "Speed", decline_offer=True)
    assert [m.value for m in cold(combat, tmp_path, mid).state.actors[s.FOE].modifiers.values()
            if m.target_field == "speed_ft"] == [-5]
    turn_to(table, mid, s.OWNER)
    play(combat, table, mid, s.candidate(table, mid, "Test Cultivation Bolt", s.FOE), "Speed")
    end_turn(table, mid)
    turn_to(table, mid, s.FOE)
    assert table.state(mid)["menu"]["actor_id"] != s.OWNER
    play(combat, table, mid, s.candidate(table, mid, "Trigger Cultivation Counter", s.OWNER), "Speed")
    engine = cold(combat, tmp_path, mid)
    foe = engine.state.actors[s.FOE]
    speed = [m for m in foe.modifiers.values() if m.target_field == "speed_ft"]
    assert sorted(m.value for m in speed) == [-10, -5]
    assert {m.source_definition_id for m in speed} == {AUGMENT + ".speed", COUNTER}
    assert next(m for m in speed if m.source_definition_id == AUGMENT + ".speed").source_actor_id == s.OWNER
    assert engine._effective_speed(foe) == 15
    assert engine.state.actors[s.OWNER].resources[DEVIL_QI] == 0
    turn_to(table, mid, s.OWNER)
    engine = cold(combat, tmp_path, mid)
    assert sorted(m.value for m in engine.state.actors[s.FOE].modifiers.values() if m.target_field == "speed_ft") == [-5]


@pytest.mark.parametrize("off_turn", [False, True])
def test_reaction_denial_expires_only_at_targets_next_start_in_both_orders(tmp_path, off_turn):
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], wide=True, bundle_transform=add_counter_probe)
    if off_turn:
        turn_to(table, mid, s.FOE)
        play(combat, table, mid, s.candidate(table, mid, "Trigger Cultivation Counter", s.OWNER), "Reactions")
    else:
        play(combat, table, mid, s.candidate(table, mid, "Test Cultivation Bolt", s.FOE), "Reactions")
    engine = cold(combat, tmp_path, mid)
    denial = next(c for c in engine.state.actors[s.FOE].conditions.values()
                  if c.condition_id == "condition:typed.reaction_denied")
    end_turn(table, mid)
    if off_turn:
        turn_to(table, mid, s.OWNER)
        engine = cold(combat, tmp_path, mid)
        assert any(c.condition_id == "condition:typed.reaction_denied" for c in engine.state.actors[s.FOE].conditions.values())
    turn_to(table, mid, s.FOE)
    assert not any(c.condition_id == "condition:typed.reaction_denied"
                   for c in cold(combat, tmp_path, mid).state.actors[s.FOE].conditions.values())
    assert denial.source_definition_id == AUGMENT + ".no_reactions"


@pytest.mark.parametrize("choice", ["save", "decline"])
def test_consecrated_failure_or_decline_keeps_full_damage_and_rider(tmp_path, choice):
    def prepare(bundles):
        add_consecrated_probe(bundles)
        foe = next(b for b in bundles if b["actor_id"] == s.FOE)
        foe["actor_template"]["saving_throws"]["CON"] = -100
        seal(foe)
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], wide=True, bundle_transform=prepare)
    commit_first_choice(table, mid, s.candidate(table, mid, "Test Consecrated Ward", s.FOE))
    engine = cold(combat, tmp_path, mid)
    start, hp = len(engine.events), engine.state.actors[s.FOE].current_hp
    prompts = play(combat, table, mid, s.candidate(table, mid, "Test Cultivation Bolt", s.FOE),
                   "Reactions", consecrated=choice)
    assert any(p["context"]["checkpoint"].endswith(":consecrated") for p in prompts)
    engine = cold(combat, tmp_path, mid)
    rolled, added, original = damage_totals(engine, start)
    assert rolled > 0 and added == rolled
    assert_original_damage_unchanged(engine, start, original)
    assert engine.state.actors[s.FOE].current_hp == hp - added - original
    saves = [e for e in engine.events[start:] if e.event_type == "SAVE_ROLLED" and e.actor_id == s.FOE]
    assert bool(saves) == (choice == "save")
    if saves:
        assert saves[-1].payload["total"] < 18
    assert any(c.condition_id == "condition:typed.reaction_denied" for c in engine.state.actors[s.FOE].conditions.values())


@pytest.mark.parametrize("choice,con,expected_roll_dice", [
    ("save", 100, 4), ("save", -100, 4), ("decline", 100, 4),
])
def test_consecrated_augmented_hit_retains_critical_and_attack_resistance(
        tmp_path, monkeypatch, choice, con, expected_roll_dice):
    """A save-wrapped bonus keeps the triggering critical and declared defense."""
    from combat import ext
    from combat.ext.attack_defenses import grant_resistance

    def prepare(bundles):
        add_consecrated_probe(bundles)
        foe = next(b for b in bundles if b["actor_id"] == s.FOE)
        foe["actor_template"]["saving_throws"]["CON"] = con
        seal(foe)

    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], wide=True, bundle_transform=prepare,
                                          seed="DEVILQIF4-CRIT-DEFENSE")
    ext.effects()

    def declare_resistance(engine, attacker, target, intent, context):
        grant_resistance(context["attack_spec"], target, "test:attack_only_resistance")
        return {"source_id": "test:attack_only_resistance", "target_id": target.entity_id, "cover_bonus": 0}

    monkeypatch.setitem(ext._HOOKS, "retarget_attack", [declare_resistance])
    monkeypatch.setitem(ext._HOOKS, "attack_critical_range", [lambda *args: 2])
    commit_first_choice(table, mid, s.candidate(table, mid, "Test Consecrated Ward", s.FOE))
    engine = cold(combat, tmp_path, mid)
    start, hp = len(engine.events), engine.state.actors[s.FOE].current_hp
    prompts = play(combat, table, mid, s.candidate(table, mid, "Test Cultivation Bolt", s.FOE),
                   "Reactions", consecrated=choice)
    engine = cold(combat, tmp_path, mid)
    aug_rolls = [e for e in engine.events[start:] if e.event_type == "DAMAGE_ROLLED"
                 and e.payload.get("display_source_id") == AUGMENT + ".damage"]
    assert len(aug_rolls) == 1 and aug_rolls[0].payload["critical"] is True
    assert len(aug_rolls[0].payload["dice"]) == expected_roll_dice
    committed = [e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED"
                 and e.payload.get("display_source_id") == AUGMENT + ".damage"]
    assert len(committed) == 1
    # Attack-only Resistance halves the critical Augment damage on failed save
    # or decline; a successful Consecrated save halves it once more.
    roll = int(aug_rolls[0].payload["total"])
    failed = con < 0
    expected = roll // (4 if choice == "save" and not failed else 2)
    assert committed[0].payload["hp_damage"] == expected
    assert hp - engine.state.actors[s.FOE].current_hp >= expected
    assert any(p["context"]["checkpoint"].endswith(":consecrated") for p in prompts)
    saves = [e for e in engine.events[start:] if e.event_type == "SAVE_ROLLED" and e.actor_id == s.FOE]
    assert bool(saves) == (choice == "save")


def test_qualifying_damage_to_ally_can_be_augmented_through_cold_reload(tmp_path):
    def prepare(bundles):
        add_probe(bundles)
        owner = next(b for b in bundles if b["actor_id"] == s.OWNER)
        ally_action = "tianxia.path.qi_cultivation.feature.devil_qi_ally_bolt"
        probe_action(owner, "Test Ally Bolt", ally_action,
                     [{"type": "damage", "applies_to": "target", "flat": 3,
                       "damage_types": ["force"], "evidence": "Test Ally Bolt deals 3 Force damage"}])
        action = next(a for a in owner["action_catalog"] if a["source_definition_id"] == ally_action)
        action["target_kind"] = "ALLY_OR_SELF"
        seal(owner)

    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], wide=True, allies=[s.SECOND],
                                          bundle_transform=prepare)
    engine = cold(combat, tmp_path, mid)
    start, hp = len(engine.events), engine.state.actors[s.SECOND].current_hp
    prompts = play(combat, table, mid, s.candidate(table, mid, "Test Ally Bolt", s.SECOND),
                   "Temporary Hit Points")
    assert any(p["context"]["checkpoint"].endswith(":offer") for p in prompts)
    engine = cold(combat, tmp_path, mid)
    assert hp - engine.state.actors[s.SECOND].current_hp == 3 + sum(
        int(e.payload["total"]) for e in engine.events[start:]
        if e.event_type == "DAMAGE_ROLLED" and e.payload.get("display_source_id") == AUGMENT + ".damage")
    assert engine.state.actors[s.OWNER].resources[DEVIL_QI] == 1
    assert any(e.event_type == "DAMAGE_COMMITTED" and s.SECOND in e.target_ids
               and e.payload.get("display_source_id") == AUGMENT + ".damage" for e in engine.events[start:])


@pytest.mark.parametrize("cl,dice", [(6, 2), (11, 3), (17, 4)])
def test_scaling_uses_exact_augment_dice_after_reload(tmp_path, cl, dice):
    def prepare(bundles):
        add_probe(bundles)
        owner = next(b for b in bundles if b["actor_id"] == s.OWNER)
        for action in owner["action_catalog"]:
            if action["display_name"] == "Test Cultivation Bolt":
                action["parameters"]["typed"]["numbers"]["cl"] = cl
        seal(owner)
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], wide=True, bundle_transform=prepare)
    start = len(cold(combat, tmp_path, mid).events)
    play(combat, table, mid, s.candidate(table, mid, "Test Cultivation Bolt", s.FOE), "Temporary Hit Points")
    engine = cold(combat, tmp_path, mid)
    rolls = [e for e in engine.events[start:] if e.event_type == "DAMAGE_ROLLED"
             and any(str(e.payload.get("expression", "")).startswith(str(n) + "d8+") for n in (2, 3, 4))]
    assert len(rolls) == 1 and len(rolls[0].payload["dice"]) == dice
    assert all(1 <= n <= 8 for n in rolls[0].payload["dice"])
    rolled, added, original = damage_totals(engine, start)
    assert added == rolled
    assert_original_damage_unchanged(engine, start, original)


def test_unrelated_path_and_non_owner_are_inert_through_service(tmp_path):
    def prepare(bundles):
        add_probe(bundles)
        owner = next(b for b in bundles if b["actor_id"] == s.OWNER)
        probe_action(owner, "Unrelated Path Damage", "tianxia.path.body_tempering.feature.probe",
                     [{"type": "damage", "applies_to": "target", "flat": 3, "damage_types": ["force"]}])
    combat, table, mid, _, _ = s.fixture(tmp_path / "owner", [AUGMENT], wide=True, bundle_transform=prepare)
    assert not commit_first_choice(table, mid, s.candidate(table, mid, "Unrelated Path Damage", s.FOE))
    assert cold(combat, tmp_path / "owner", mid).state.actors[s.OWNER].resources[DEVIL_QI] == 2
    def no_owner(bundles):
        mixed_probe(bundles)
        owner = next(b for b in bundles if b["actor_id"] == s.OWNER)
        owner["typed_passives"] = [r for r in owner["typed_passives"] if r.get("kind") != "devil_qi_augment"]
        seal(owner)
    combat, table, mid, _, _ = s.fixture(tmp_path / "plain", [AUGMENT], wide=True, bundle_transform=no_owner)
    assert not commit_first_choice(table, mid, s.candidate(table, mid, "Mixed Cultivation Strike", s.FOE))
    assert cold(combat, tmp_path / "plain", mid).state.actors[s.OWNER].resources[DEVIL_QI] == 2


@pytest.mark.parametrize("owner_ai", [False, True])
def test_owner_choices_on_ai_turn_and_ai_owner_decides_automatically(tmp_path, owner_ai):
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], wide=True, bundle_transform=add_counter_probe)
    turn_to(table, mid, s.FOE)
    candidate = s.candidate(table, mid, "Trigger Cultivation Counter", s.OWNER)
    s.force_ai_candidate(combat, mid, s.FOE, candidate)
    if owner_ai:
        combat.set_controller_mode(mid, actor_id=s.OWNER, controller_mode="LOCAL_AUTO")
    prompts = play(combat, table, mid, candidate, "Reactions", auto=True)
    augment_prompts = [p for p in prompts if "DEVIL_QI_AUGMENT" in p["context"]["checkpoint"]]
    if owner_ai:
        assert not augment_prompts
    else:
        assert augment_prompts and all(p["context"]["reactor_id"] == s.OWNER for p in augment_prompts)
        assert all("Second Cultivation Counter" in str(p) and "Foe" in str(p) for p in augment_prompts)
        assert cold(combat, tmp_path, mid).state.actors[s.OWNER].resources[DEVIL_QI] == 1
    assert cold(combat, tmp_path, mid).state.current_actor_id == s.FOE


def test_explicit_modifier_ownership_is_general_and_default_is_unchanged(tmp_path):
    def prepare(bundles):
        add_counter_probe(bundles)
        owner = next(b for b in bundles if b["actor_id"] == s.OWNER)
        owner["typed_passives"] = [r for r in owner["typed_passives"] if r.get("kind") != "devil_qi_augment"]
        counter = next(r for r in owner["typed_reactions"] if r["feature_id"] == COUNTER)
        counter["effects"] = [
            {"type": "speed", "applies_to": "target", "flat": -5, "source_owned": True,
             "expires_on": "START_OF_SOURCE_NEXT_TURN"},
            {"type": "resistance", "applies_to": "target", "damage_types": ["force"], "expires_on": "UNTIL_REMOVED"},
        ]
        seal(owner)
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], wide=True, bundle_transform=prepare)
    turn_to(table, mid, s.FOE)
    play(combat, table, mid, s.candidate(table, mid, "Trigger Cultivation Counter", s.OWNER), "Speed")
    engine = cold(combat, tmp_path, mid)
    modifiers = [m for m in engine.state.actors[s.FOE].modifiers.values() if m.source_definition_id == COUNTER]
    assert next(m for m in modifiers if m.target_field == "speed_ft").source_actor_id == s.OWNER
    assert next(m for m in modifiers if m.target_field == "damage_resistance").source_actor_id == s.FOE
    turn_to(table, mid, s.OWNER)
    engine = cold(combat, tmp_path, mid)
    assert not any(m.target_field == "speed_ft" and m.source_definition_id == COUNTER
                   for m in engine.state.actors[s.FOE].modifiers.values())

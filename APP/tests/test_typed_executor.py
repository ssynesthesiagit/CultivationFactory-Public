"""Typed abilities run through the Gate 2 engine from data alone (owner 2026-09-24: combat is modular)."""

import json
from pathlib import Path

from combat import typed_executor
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind

ROOT = Path(__file__).resolve().parents[1]
PALM = {
    "effects": [{
        "type": "save", "ability": "str",
        "on_fail": [
            {"type": "damage", "dice": {"count": 8, "sides": 8}, "damage_types": ["force"]},
            {"type": "forced_movement", "distance_ft": 30, "direction": "away"},
            {"type": "condition", "condition": "prone"},
        ],
        "on_success": [{"type": "half_damage"}, {"type": "forced_movement", "distance_ft": 10, "direction": "away"}],
    }],
    "riders": ["Temporary Barriers take double damage."],
    "numbers": {"pb": 6, "save_dc": 30, "attack_bonus": 9, "key_mod": 4},
    "duration": {"kind": "instant"},
}


def test_shared_static_formulas_match_execution_without_emitting_display_riders():
    from combat.display_values import display_formula_value
    from combat.typed_executor import Context, static_formula

    engine, actor_id = _engine_with(PALM, "SHARED-FORMULAS")
    actor = engine.state.actors[actor_id]
    action = engine.action_catalog["action:typed.test"]
    numbers = {"pb": 3, "cl": 5, "key_mod": -2}
    ctx = Context(engine, actor, action, None, {"numbers": numbers}, [])
    expected = {None: 0, "none": 0, "pb": 3, "cl": 5, "half_pb": 1,
                "double_pb": 6, "triple_pb": 9, "cl_x5": 25, "mod:STR": -2,
                "key_ability_modifier": -2, "text:twice your proficiency bonus + your key ability modifier": 4,
                "text:your key ability modifier, minimum 1": 1}
    before = len(engine.events)
    for formula, value in expected.items():
        assert static_formula(formula, numbers) == (value, "")
        assert display_formula_value(formula, numbers) == ctx.formula(formula) == value
    assert len(engine.events) == before
    assert numbers == {"pb": 3, "cl": 5, "key_mod": -2}

    formula = "text:your proficiency bonus and +1 AC"
    assert display_formula_value(formula, numbers) == 3
    assert len(engine.events) == before
    assert ctx.formula(formula) == 3
    assert engine.events[-1].event_type == "GM_RIDER"
    assert engine.events[-1].payload["rider"] == "Also: and +1 AC"

    engine._typed_trigger_damage = 99
    assert ctx.formula("half_trigger_damage") == 25
    assert ctx.formula("unresolved") == int(typed_executor.rules()["defaults"].get("unknown_formula_value", 0))
    assert engine.events[-1].payload["rider"] == "Formula not typed: unresolved"


def _intent(candidate):
    return ActionIntent(intent_id="test:typed", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                        state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=candidate.target_ids,
                        destination=candidate.destination)


def _engine_with(typed: dict, seed: str) -> tuple[Gate2Engine, str]:
    engine = Gate2Engine(ROOT, match_seed=seed)
    actor = engine.state.actors[engine.state.current_actor_id]
    action = ActionDefinition(source_definition_id="action:typed.test", display_name="Typed test", owner_id=actor.entity_id,
                              economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
                              range_ft=500, parameters={"typed": typed})
    engine.action_catalog[action.source_definition_id] = action
    actor.action_ids = (*actor.action_ids, action.source_definition_id)
    return engine, actor.entity_id


def test_a_typed_save_ability_runs_from_data():
    engine, actor_id = _engine_with(PALM, "TYPED-PALM")
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
    target = engine.state.actors[candidate.target_ids[0]]
    hp_before, position_before = target.current_hp + target.temporary_hp, target.position
    engine.execute_intent(_intent(candidate))
    kinds = [event.event_type for event in engine.events if event.source_definition_id == "action:typed.test"]
    assert "SAVE_ROLLED" in kinds and "DAMAGE_ROLLED" in kinds
    # DC 30 cannot be met: full damage, pushed and knocked prone.
    assert target.current_hp + target.temporary_hp < hp_before or not target.active
    assert any(c.condition_id == "condition:typed.prone" for c in target.conditions.values()) or not target.active
    assert target.position != position_before or not target.active
    assert any(e.event_type == "GM_RIDER" and e.payload.get("rider") == "Temporary Barriers take double damage." for e in engine.events)


def test_condition_rules_are_data():
    rows = typed_executor.rules()["conditions"]
    assert rows["restrained"]["speed_zero"] is True
    # Prone (owner 2026-09-26): Advantage only from within 5 ft, Disadvantage beyond; it ends when the creature stands.
    assert (rows["prone"]["attacked_within_5ft"], rows["prone"]["attacked_beyond_5ft"]) == ("ADVANTAGE", "DISADVANTAGE")
    # Every block type the parser emits has a building block.
    for kind in ("save", "attack", "damage", "condition", "forced_movement", "temp_hp", "ac_bonus", "resistance", "advantage"):
        assert kind in typed_executor.BLOCKS


def test_a_typed_attack_and_a_self_buff_run_from_data():
    cut = {"effects": [{"type": "attack", "attack_kind": "saber", "count": 1,
                        "on_hit": [{"type": "damage", "weapon_damage": True}]}],
           "numbers": {"pb": 6, "save_dc": 17, "attack_bonus": 30, "key_mod": 4},
           "weapon": {"damage": {"count": 1, "sides": 8, "modifier": 4}, "damage_type": "SLASHING"},
           "duration": {"kind": "instant"}}
    engine, _ = _engine_with(cut, "TYPED-CUT")
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
    engine.execute_intent(_intent(candidate))
    assert any(e.event_type == "ATTACK_ROLLED" or e.event_type.startswith("ATTACK") for e in engine.events if e.source_definition_id == "action:typed.test")

    armor = {"effects": [{"type": "ac_bonus", "amount": 2}, {"type": "resistance", "damage_types": ["slashing"]}],
             "numbers": {"pb": 6}, "duration": {"kind": "minutes", "amount": 1}}
    engine, actor_id = _engine_with(armor, "TYPED-ARMOR")
    action = engine.action_catalog["action:typed.test"]
    engine.action_catalog["action:typed.test"] = action.model_copy(update={"target_kind": "SELF", "range_ft": None})
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
    engine.execute_intent(_intent(candidate))
    actor = engine.state.actors[actor_id]
    assert engine._ac_modifier(actor) == 2
    assert any(m.target_field == "damage_resistance" and m.value == "SLASHING" for m in actor.modifiers.values())


def test_a_fixed_amount_with_no_dice_does_not_crash():
    """'Temporary HP equal to your PB' has no dice (found by the 2026-09-24 tournament: Lian Feng crashed every fight)."""
    ward = {"effects": [{"type": "temp_hp", "applies_to": "self", "formula": "pb", "dice": {"count": None, "sides": None}}],
            "numbers": {"pb": 3}, "duration": {"kind": "instant"}}
    engine, actor_id = _engine_with(ward, "TYPED-FLAT")
    action = engine.action_catalog["action:typed.test"]
    engine.action_catalog["action:typed.test"] = action.model_copy(update={"target_kind": "SELF", "range_ft": None})
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
    engine.execute_intent(_intent(candidate))
    assert engine.state.actors[actor_id].temporary_hp == 3

    flat_hit = {"effects": [{"type": "attack", "count": 1, "on_hit": [{"type": "damage", "flat": 2, "damage_types": ["force"]}]}],
                "numbers": {"pb": 3, "attack_bonus": 40}, "weapon": {"damage": {"count": 1, "sides": 6, "modifier": 0}, "damage_type": "FORCE"},
                "duration": {"kind": "instant"}}
    engine, _ = _engine_with(flat_hit, "TYPED-FLAT-HIT")
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
    engine.execute_intent(_intent(candidate))  # the attack rolls weapon dice plus the fixed 2
    assert any(e.event_type == "DAMAGE_COMMITTED" for e in engine.events if e.source_definition_id == "action:typed.test")


def test_the_history_feed_spells_out_typed_ability_events():
    """Owner 2026-09-24: the fight feed records actions and rolls; GM calls must read as text."""
    from combat.history_feed import format_history_feed

    events = [
        {"event_type": "GM_RIDER", "actor_id": "a", "target_ids": ["b"], "source_definition_id": "action:typed.x.palm",
         "payload": {"rider": "Ordinary unsecured objects move automatically."}, "sequence": 1},
        {"event_type": "HEALING_APPLIED", "actor_id": "a", "target_ids": ["a"], "source_definition_id": "action:typed.x.mend",
         "payload": {"offered": 7, "before": 10, "after": 17}, "sequence": 2},
        {"event_type": "SAVE_AUTO_FAILED", "actor_id": "b", "target_ids": [], "source_definition_id": "action:typed.x.palm",
         "payload": {"ability": "DEX"}, "sequence": 3},
    ]
    rows = format_history_feed(events, [], pre_state=None, post_state={}, actor_names={"a": "Lian Feng", "b": "Wu Yun"},
                               definition_names={"action:typed.x.palm": "Mountain Palm", "action:typed.x.mend": "Mend"})
    text = [row["summary"] for row in rows]
    # Every expected word comes from this synthetic event and the renderer's
    # fixed framing, rather than private source/rules prose. Keep the complete
    # equality check while distinguishing that framing from the fixture rider.
    expected_rider = events[0]["payload"]["rider"]
    expected_summary = (
        "Lian Feng's Mountain Palm on Wu Yun: additional effect reminder. "
        "Resolve only effects that the recorded outcomes have not already applied. "
        "Rule reminder: " + expected_rider)
    assert text[0] == expected_summary
    assert "healed Lian Feng for 7; HP 10 → 17" in text[1]
    assert "automatically failed the DEX save against Mountain Palm" in text[2]
    assert all("not recorded" not in line for line in text)


def test_cl_scaled_dice_roll_the_row_for_the_characters_cl():
    """Playtest 2026-09-24: Mind Spike's 'listed dice' (a CL table) were untyped, so at CL 10 it dealt only WIS."""
    spike = {"effects": [{"type": "damage", "dice": "", "dice_by_cl": [[1, 4, 1, 8], [5, 10, 2, 8], [11, 16, 3, 8], [17, 20, 4, 8]],
                          "damage_types": ["psychic"], "applies_to": "target"}],
             "numbers": {"pb": 4, "cl": 10, "key_mod": 3}, "duration": {"kind": "instant"}}
    engine, _ = _engine_with(spike, "TYPED-CL-DICE")
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
    engine.execute_intent(_intent(candidate))
    rolled = [e for e in engine.events if e.source_definition_id == "action:typed.test" and e.event_type == "DAMAGE_ROLLED"]
    assert rolled and rolled[0].payload["expression"].startswith("2d8")


def test_the_parser_reads_both_printed_cl_scaling_forms():
    from factory_authoring.typed_mechanics import cl_dice_table, dice_for_cl

    table = cl_dice_table("| CL | Damage |\n|---:|---:|\n| 1–4 | `1d8 + Wisdom modifier` |\n| 5–10 | `2d8` |\n| 11–16 | `3d8` |\n| 17–20 | `4d8` |")
    assert dice_for_cl(table, 10) == {"count": 2, "sides": 8} and dice_for_cl(table, 17) == {"count": 4, "sides": 8}
    growth = cl_dice_table("The target takes 1d8 bludgeoning damage. The damage increases by 1d8 at CL 5, CL 11, and CL 17.", {"count": 1, "sides": 8})
    assert dice_for_cl(growth, 4) == {"count": 1, "sides": 8} and dice_for_cl(growth, 11) == {"count": 3, "sides": 8}


def _reactor(seed: str, rows: list[dict], resource: str = "resource:core.stamina", amount: int = 5):
    engine = Gate2Engine(ROOT, match_seed=seed)
    target = next(a for a in engine.state.actors.values() if a.entity_id != engine.state.current_actor_id)
    attacker = engine.state.actors[engine.state.current_actor_id]
    engine.typed_actor_ids.add(target.entity_id)
    engine.typed_reaction_rows[target.entity_id] = rows
    target.resource_maximums = {**target.resource_maximums, resource: 10}
    target.resources = {**target.resources, resource: amount}
    target.reaction_available = True
    return engine, attacker, target


def test_a_save_rescue_turns_a_near_miss_into_a_success_once():
    """Owner 2026-09-25: Cultivated/Soulward/Tempered Response (combat/rules/feature_blocks.json)."""
    from combat import typed_reactions

    row = {"feature_id": "f.rescue", "block": "save_rescue", "resource_id": "resource:core.qi", "abilities": ["DEX"], "cost": 1, "bonus": 3, "reaction": True}
    engine, _, target = _reactor("RESCUE", [row], "resource:core.qi", 2)
    roll = engine.roller.d20(modifier=0, actor_id=target.entity_id, reason="t")
    dc = roll.total + 2  # failed by 2: +3 turns it into a success
    rescued = typed_reactions.on_save(engine, target, "DEX", dc, roll, "src")
    assert rescued.total >= dc and target.resources["resource:core.qi"] == 1 and not target.reaction_available
    # Not for another ability, and not when the bonus cannot reach the DC.
    target.reaction_available = True
    assert typed_reactions.on_save(engine, target, "WIS", dc, roll, "src").total == roll.total
    assert typed_reactions.on_save(engine, target, "DEX", roll.total + 9, roll, "src").total == roll.total


def test_damage_soak_rolls_dice_against_a_big_hit():
    from combat import typed_reactions

    row = {"feature_id": "f.soak", "block": "damage_soak", "resource_id": "resource:core.stamina", "max_spend": 3, "die": 10, "minimum_damage": 5}
    engine, _, target = _reactor("SOAK", [row])
    left = typed_reactions.on_damage(engine, target, 30, 0)
    assert left < 30 and target.resources["resource:core.stamina"] == 2  # 3 spent against 30 damage
    target.reaction_available = True
    assert typed_reactions.on_damage(engine, target, 3, 0) == 3  # too small to bother


def test_hit_ac_reaction_turns_a_ranged_hit_into_a_miss():
    from combat import typed_reactions

    row = {"feature_id": "f.qi_armor", "block": "hit_ac", "resource_id": "resource:core.qi", "cost": 2, "ac": 3, "ranged_only": True}
    engine, attacker, target = _reactor("QIARMOR", [row], "resource:core.qi", 4)
    assert typed_reactions.on_attack_hit(engine, attacker, target, {"range_ft": None}, 16, 12, 15) == (15, True)  # melee: no
    assert typed_reactions.on_attack_hit(engine, attacker, target, {"range_ft": 60}, 20, 15, 15) == (15, True)    # would still hit
    ac, hit = typed_reactions.on_attack_hit(engine, attacker, target, {"range_ft": 60}, 16, 12, 15)
    assert (ac, hit) == (18, False) and target.resources["resource:core.qi"] == 2 and engine._ac_modifier(target) == 3


def test_feature_blocks_compile_from_the_rules_file():
    from combat.factory_compiler import RESOURCE_IDS
    from combat.typed_reactions import compile_blocks

    # Ownership overrides are runtime directory inputs. This real Path row
    # replaces the base declaration; reduced test snapshots must retain it.
    path_rows = json.loads((ROOT / "combat/rules/feature_blocks.d/auto1_paths_a.json").read_text())["features"]
    assert path_rows["tianxia.path.body_refining.feature.tempered_response"]["block"] == "save_rescue"

    ids = ["tianxia.path.body_refining.feature.iron_fist", "tianxia.path.body_refining.feature.stamina_guard",
           "tianxia.path.body_refining.feature.tempered_response", "tianxia.path.qi_cultivation.feature.qi_technique_potency", "unrelated"]
    blocks = compile_blocks(ids, pb=6, key_mod=5, saves={"STR": 4, "DEX": 1, "CON": 3}, resource_ids=RESOURCE_IDS)
    by_block = {row["block"]: row for row in blocks["reactions"] + blocks["passives"]}
    assert by_block["damage_soak"]["max_spend"] == 6 and by_block["damage_soak"]["resource_id"] == "resource:core.stamina"
    assert by_block["save_rescue"]["abilities"] == ["DEX"] and by_block["save_rescue"]["bonus"] == 6  # weakest listed save
    assert by_block["technique_potency"]["bonus_value"] == 5 and by_block["natural_weapon"]["dice"] == "1d8"
    assert "unrelated" not in blocks["automated"] and len(blocks["automated"]) == 4


def test_second_wave_blocks_compile_and_extra_attack_scales_with_cl():
    """Owner 2026-09-25: Extra Attack, Body Tempering, Guard-Cutting Parry, Conductive Strike, Unarmored Defense."""
    from combat.factory_compiler import RESOURCE_IDS
    from combat.typed_reactions import compile_blocks

    ids = ["tianxia.path.body_refining.feature.extra_attack", "tianxia.path.body_refining.feature.body_tempering",
           "tianxia.path.body_refining.feature.unarmored_defense", "tianxia.talent.sabers.guard_cutting_parry", "TAL_LIGHTNING_CONDUCTIVE_STRIKE"]
    for cl, attacks in ((5, 2), (11, 3), (20, 4)):
        blocks = compile_blocks(ids, pb=6, key_mod=0, cl=cl, saves={}, resource_ids=RESOURCE_IDS)
        assert next(row for row in blocks["passives"] if row["block"] == "extra_attack")["attacks"] == attacks
    by_block = {row["block"]: row for row in blocks["reactions"] + blocks["passives"]}
    assert by_block["resistance"]["mundane_only"] and "SLASHING" in by_block["resistance"]["damage_types"]
    assert by_block["damage_reduction"]["bonus"] == 6 and by_block["damage_reduction"]["dice"] == "1d8"
    assert by_block["on_hit_damage"]["bonus_value"] == 6 and by_block["on_hit_damage"]["once_per_turn"]
    assert set(blocks["automated"]) == set(ids)  # Unarmored Defense is already in the sheet's AC


def test_extra_attacks_each_roll_and_a_once_per_turn_rider_lands_once():
    cut = {"effects": [{"type": "attack", "attack_kind": "weapon", "count": 3,
                        "on_hit": [{"type": "damage", "weapon_damage": True},
                                   {"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["COLD"]},
                                   {"type": "damage", "flat": 5, "damage_types": ["LIGHTNING"], "once_per_turn": "f.conductive"}]}],
           "numbers": {"pb": 6, "save_dc": 17, "attack_bonus": 30, "key_mod": 4},
           "weapon": {"damage": {"count": 1, "sides": 4, "modifier": 0}, "damage_type": "SLASHING"},
           "duration": {"kind": "instant"}}
    engine, _ = _engine_with(cut, "TYPED-EXTRA-ATTACK")
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
    engine.execute_intent(_intent(candidate))
    committed = [e.payload["damage_type"] for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == "action:typed.test"]
    cold_rolls = [roll for roll in engine.rolls if roll.reason == "DAMAGE:action:typed.test" and roll.expression.startswith("1d6")]
    assert committed.count("SLASHING") >= 2 and committed.count("LIGHTNING") == 1  # the rider lands on one hit per turn
    assert len(cold_rolls) == committed.count("COLD") == committed.count("SLASHING")  # every hit rolls its own on-hit dice


def test_attack_consumption_phase_is_per_roll_and_inherited_by_late_packets(monkeypatch):
    from tests.h1_support import script
    from tests.test_lock_choices import install

    cut = {'effects': [{'type': 'attack', 'attack_kind': 'weapon', 'count': 2,
                       'on_hit': [{'type': 'damage', 'weapon_damage': True},
                                  {'type': 'damage', 'flat': 3, 'damage_types': ['FORCE']}]}],
           'numbers': {'pb': 6, 'attack_bonus': 30, 'key_mod': 4},
           'weapon': {'damage': {'count': 1, 'sides': 4}, 'damage_type': 'SLASHING'}}
    engine, actor_id = _engine_with(cut, 'CONSUMPTION-PHASE')
    target = next(a for a in engine.state.actors.values() if a.team_id != engine.state.actors[actor_id].team_id)
    target.armor_class = 0
    seen = []

    def damage(ctx, target, amount):
        if ctx.source == 'action:typed.test':
            seen.append(('damage', ctx.attack_mode_consumption_pending, ctx.attack_damage_context is not None))

    def resolved(ctx, target, hit, effect):
        if ctx.source == 'action:typed.test':
            seen.append(('resolved', ctx.attack_mode_consumption_pending, ctx.attack_damage_context is not None))

    install(monkeypatch, 'damage_dealt', damage)
    install(monkeypatch, 'attack_resolved', resolved)
    script(engine, [15] * 100)
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == 'action:typed.test')
    engine.execute_intent(_intent(candidate))
    assert seen == [('damage', True, True), ('resolved', False, True), ('damage', False, True)] * 2
    ctx = typed_executor.Context(engine, engine.state.actors[actor_id],
                                 engine.action_catalog['action:typed.test'], None, cut, [target], target)
    assert ctx.attack_mode_consumption_pending is False
    assert ctx.on_hit_context(target).attack_mode_consumption_pending is False


def test_parry_meets_only_melee_weapon_hits_and_body_tempering_only_mundane_weapons():
    from types import SimpleNamespace

    from combat import typed_reactions

    parry = {"feature_id": "f.parry", "block": "damage_reduction", "resource_id": "", "dice": "1d8", "bonus": 6, "cost": 0,
             "minimum_damage": 5, "trigger": "melee_weapon_hit"}
    engine, attacker, target = _reactor("PARRY", [parry])
    engine.action_catalog["src.blade"] = SimpleNamespace(parameters={"typed": {"effects": [{"type": "attack", "attack_kind": "weapon"}], "range_ft": None, "mundane": True}})
    engine.action_catalog["src.palm"] = SimpleNamespace(parameters={"typed": {"effects": [{"type": "save"}]}})
    assert typed_reactions.on_damage(engine, target, 20, 0, "src.palm", attacker.entity_id) == 20  # a technique: no parry
    left = typed_reactions.on_damage(engine, target, 20, 0, "src.blade", attacker.entity_id)
    assert 6 <= left <= 13 and not target.reaction_available

    engine.typed_passive_rows[target.entity_id] = [{"feature_id": "f.tempering", "block": "resistance", "damage_types": ["SLASHING"], "mundane_only": True}]
    assert typed_reactions.resists(engine, target, "SLASHING", "src.blade")
    assert not typed_reactions.resists(engine, target, "SLASHING", "src.palm") and not typed_reactions.resists(engine, target, "FIRE", "src.blade")
    hp = target.current_hp
    engine._commit_damage(target, 10, "SLASHING", "src.blade", attacker.entity_id, None, reaction_depth=0)
    assert hp - target.current_hp == 5


def test_a_dash_effect_grants_movement_equal_to_speed():
    dash = {"effects": [{"type": "movement", "distance_ft": "speed"}], "numbers": {"pb": 3}, "duration": {"kind": "instant"}}
    engine, actor_id = _engine_with(dash, "TYPED-DASH")
    actor = engine.state.actors[actor_id]
    action = engine.action_catalog["action:typed.test"]
    before = actor.movement_remaining_ft
    typed_executor.run_effects(typed_executor.Context(engine, actor, action, None, dash, [], None), dash["effects"])
    assert actor.movement_remaining_ft == before + engine._effective_speed(actor)

"""Damage types, resistances, immunities, vulnerability and flat reductions for Factory fighters (owner 2026-09-26:
"are damage types all tracked and resistances?" -- "lets fix all 3")."""

from types import SimpleNamespace

from combat.factory_compiler import RESOURCE_IDS, compile_character
from combat.typed_reactions import compile_blocks
from tests.test_factory_combat_compiler import ACTOR, SHEET
from tests.test_typed_executor import _engine_with, _intent, _reactor

HELLWALKER = "tianxia.subpath.body.jigoku.feature.hellwalker"
STONE_SKIN = "tianxia.subpath.body.yamabushi.feature.stone_skin"
BELL_TOWER = "TAL_IRON_FIST_BELL_TOWER_BODY"


def test_always_on_defences_compile_with_their_armour_conditions():
    blocks = compile_blocks([HELLWALKER, STONE_SKIN, BELL_TOWER], pb=4, key_mod=0, saves={}, resource_ids=RESOURCE_IDS)
    rows = {(row["feature_id"], row["kind"]): row for row in blocks["passives"]}
    assert rows[(HELLWALKER, "immunity")]["damage_types"] == ["FIRE"] and rows[(HELLWALKER, "resistance")]["damage_types"] == ["NECROTIC"]
    assert rows[(BELL_TOWER, "reduction")]["amount"] == 4 and rows[(BELL_TOWER, "reduction")]["martial_focus"]
    assert (STONE_SKIN, "resistance") in rows
    # Only the defence is automated: the features' other parts still compile.
    assert set(blocks["defended"]) == {HELLWALKER, STONE_SKIN, BELL_TOWER} and not blocks["automated"]

    armoured = compile_blocks([STONE_SKIN, BELL_TOWER], pb=4, key_mod=0, saves={}, resource_ids=RESOURCE_IDS, armor="heavy")
    assert not armoured["passives"]  # no Unarmored Defense in armour; Bell-Tower Body needs no Heavy armour


def test_a_compiled_character_keeps_its_poison_resistance():
    sheet = {**SHEET, "spheres_and_talents": {**SHEET["spheres_and_talents"], "learned_talent_record_ids": [
        *SHEET["spheres_and_talents"]["learned_talent_record_ids"], "tianxia.talent.poison.venom_body_method"]}}
    bundle = compile_character(sheet, actor_id=ACTOR)
    rows = [row for row in bundle["typed_passives"] if row["block"] == "defense"]
    assert [(row["kind"], row["damage_types"]) for row in rows] == [("resistance", ["POISON"])]
    assert "Venom Body Method" not in bundle["diagnostics"]["skipped"]["passive"]


def _committed(engine, target, amount, kind, source="src.palm", attacker=None):
    hp = target.current_hp
    engine._commit_damage(target, amount, kind, source, attacker, None, reaction_depth=0)
    taken = hp - target.current_hp
    target.current_hp = hp
    return taken


def test_immunity_resistance_vulnerability_then_flat_reduction():
    engine, attacker, target = _reactor("DEFENCES", [])
    engine.action_catalog["src.palm"] = SimpleNamespace(parameters={"typed": {"effects": [{"type": "attack", "attack_kind": "unarmed"}], "numbers": {"cl": 5}}})
    engine.typed_passive_rows[target.entity_id] = [
        {"feature_id": "f.hell", "block": "defense", "kind": "immunity", "damage_types": ["FIRE"]},
        {"feature_id": "f.hell", "block": "defense", "kind": "resistance", "damage_types": ["NECROTIC", "COLD"]},
        {"feature_id": "f.body", "block": "defense", "kind": "reduction", "damage_types": ["COLD", "BLUDGEONING"], "amount": 3},
        {"feature_id": "f.venom", "block": "defense", "kind": "resistance", "damage_types": ["POISON"], "immune_below_cl": 9},
    ]
    assert _committed(engine, target, 20, "FIRE", attacker=attacker.entity_id) == 0
    assert _committed(engine, target, 20, "NECROTIC", attacker=attacker.entity_id) == 10
    assert _committed(engine, target, 20, "COLD", attacker=attacker.entity_id) == 7  # halved, then minus 3
    assert _committed(engine, target, 20, "POISON", attacker=attacker.entity_id) == 0  # a CL5 source against CL9
    engine.action_catalog["src.palm"].parameters["typed"]["numbers"]["cl"] = 12
    assert _committed(engine, target, 20, "POISON", attacker=attacker.entity_id) == 10

    engine._add_modifier(target, "src.brittle", "damage_vulnerability_next", "ADD", "NECROTIC", "ALWAYS", expires_on=None)
    assert _committed(engine, target, 20, "NECROTIC", attacker=attacker.entity_id) == 20  # halved, then doubled
    assert any(e.event_type == "MODIFIER_REMOVED" and e.payload.get("reason") == "CONSUMED" for e in engine.events)
    assert _committed(engine, target, 20, "NECROTIC", attacker=attacker.entity_id) == 10  # only the next one


def test_suppressed_and_ignored_resistance():
    engine, attacker, target = _reactor("IGNORE", [])
    engine.action_catalog["src.fist"] = SimpleNamespace(parameters={"typed": {"effects": [{"type": "attack", "attack_kind": "unarmed"}]}})
    engine.action_catalog["src.shot"] = SimpleNamespace(parameters={"typed": {"effects": [
        {"type": "attack", "attack_kind": "weapon", "on_hit": [{"type": "ignore_resistance", "damage_types": ["piercing"]}]}], "range_ft": 150}})
    engine.typed_passive_rows[target.entity_id] = [
        {"feature_id": "f.crown", "block": "defense", "kind": "resistance", "damage_types": ["PIERCING", "THUNDER"]}]
    assert _committed(engine, target, 20, "PIERCING", "src.fist", attacker.entity_id) == 10
    assert _committed(engine, target, 20, "PIERCING", "src.shot", attacker.entity_id) == 20  # Targeted Assault
    engine.typed_passive_rows[attacker.entity_id] = [
        {"feature_id": "f.bolt", "block": "defense", "kind": "ignore_resistance", "damage_types": ["THUNDER"], "attack_kinds": ["unarmed"]}]
    assert _committed(engine, target, 20, "THUNDER", "src.fist", attacker.entity_id) == 20  # Body of the Unbroken Bolt
    assert _committed(engine, target, 20, "THUNDER", "src.shot", attacker.entity_id) == 10  # not an unarmed strike
    engine._add_modifier(target, "src.hilt", "resistance_suppressed", "ADD", "PIERCING", "ALWAYS", expires_on=None)
    assert _committed(engine, target, 20, "PIERCING", "src.fist", attacker.entity_id) == 20  # To the Hilt


def test_the_attacker_picks_the_damage_type_that_lands():
    cut = {"effects": [{"type": "attack", "attack_kind": "weapon", "count": 2, "on_hit": [{"type": "damage", "weapon_damage": True}]}],
           "numbers": {"pb": 6, "save_dc": 17, "attack_bonus": 30, "key_mod": 4},
           "weapon": {"damage": {"count": 1, "sides": 8, "modifier": 4}, "damage_type": "PIERCING", "damage_types": ["PIERCING", "SLASHING"]},
           "duration": {"kind": "instant"}}
    engine, actor_id = _engine_with(cut, "EITHER-TYPE")
    for other in engine.state.actors.values():
        if other.entity_id != actor_id:
            engine.typed_actor_ids.add(other.entity_id)
            engine.typed_passive_rows[other.entity_id] = [{"feature_id": "f.r", "block": "defense", "kind": "resistance", "damage_types": ["PIERCING"]}]
    engine.execute_intent(_intent(next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")))
    kinds = {e.payload["damage_type"] for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == "action:typed.test"}
    assert kinds == {"SLASHING"}


def test_either_or_damage_effects_are_choices_but_and_is_both():
    from combat.typed_executor import damage_choices

    assert damage_choices({"damage_types": ["fire", "necrotic"], "evidence": "Take 2d8 Fire or Necrotic damage"}) == ["FIRE", "NECROTIC"]
    assert damage_choices({"damage_types": ["force", "psychic"], "evidence": "Take `6d10` Force and Psychic damage"}) == ["FORCE"]
    assert damage_choices({}, {"damage_type": "PIERCING", "damage_types": ["PIERCING", "SLASHING"]}) == ["PIERCING", "SLASHING"]


def test_advantage_on_the_next_attack_reaches_the_attack_roll():
    """The mode was stored as the modifier's operation while the engine reads its value, so "advantage on your
    next attack roll" never applied (found 2026-09-26 while adding long-range Disadvantage)."""
    typed = {"effects": [{"type": "advantage", "on": "your next attack roll"}], "numbers": {"pb": 6, "save_dc": 17, "attack_bonus": 9},
             "duration": {"kind": "instant"}}
    engine, actor_id = _engine_with(typed, "ADVANTAGE-NEXT")
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
    engine.execute_intent(_intent(candidate))
    actor = engine.state.actors[actor_id]
    target = next(a for a in engine.state.actors.values() if a.team_id != actor.team_id)
    assert engine._attack_mode(actor, target) == "ADVANTAGE"


def _two(seed):
    from tests.test_factory_combat_compiler import _duel, _weapons_of

    bundle, _ = _weapons_of(["tianxia.mortal.weapon.dao"], paths=("tianxia.path.body_refining",))
    return _duel(bundle, seed)


def test_repeat_saves_burning_and_healing_reduction():
    """Owner 2026-09-26 list item 6: "save ends" conditions, Tianxia Burn, healing reduction."""
    from combat import typed_executor

    engine, me, foe = _two("CONDITIONS")
    # A repeat save at the end of the creature's turn ends it on a success.
    engine._apply_condition(foe, "condition:typed.frightened", "src.fear", me.entity_id, expires_on="UNTIL_REMOVED",
                            data={"repeat_save": {"ability": "WIS", "when": "end", "dc": 1}})
    engine._expire_for_checkpoint("END_OF_TURN", me.entity_id)
    assert any(c.condition_id.endswith(".frightened") for c in foe.conditions.values())  # not on the frightener's turn
    engine._expire_for_checkpoint("END_OF_TURN", foe.entity_id)
    assert not any(c.condition_id.endswith(".frightened") for c in foe.conditions.values())
    # Burn: Proficiency Bonus Fire damage at the start of its turn; burns from one cultivator do not stack.
    action = engine.action_catalog[next(a for a in me.action_ids if a.endswith(".weapon.dao"))]
    ctx = typed_executor.Context(engine, me, action, None, {**action.parameters["typed"], "numbers": {"pb": 6}}, [foe], foe, {})
    typed_executor.block_condition(ctx, {"type": "condition", "condition": "burning", "applies_to": "target"})
    typed_executor.block_condition(ctx, {"type": "condition", "condition": "burning", "applies_to": "target"})
    assert sum(c.condition_id.endswith(".burning") for c in foe.conditions.values()) == 1
    hp = foe.current_hp
    engine._expire_for_checkpoint("START_OF_TURN", foe.entity_id)
    assert hp - foe.current_hp == 6
    # Healing reduction: minus Proficiency Bonus, halved, none, and a "next healing" one is spent.
    heal = {"type": "healing", "flat": 20, "applies_to": "target"}
    for evidence, expected in (("reduce healing received by your Proficiency Bonus until the start of your next turn", 14),
                               ("healing received is halved", 10), ("cannot regain Hit Points until the start of your next turn", 0)):
        foe.modifiers.clear()
        foe.current_hp = 10
        typed_executor.block_healing_reduction(ctx, {"type": "healing_reduction", "applies_to": "target", "evidence": evidence})
        typed_executor.block_healing(ctx, heal)
        assert foe.current_hp - 10 == expected, evidence
    foe.modifiers.clear()
    typed_executor.block_healing_reduction(ctx, {"type": "healing_reduction", "applies_to": "target",
                                                 "evidence": "The next healing the target receives before its next long rest is reduced by your Proficiency Bonus"})
    foe.current_hp = 10
    typed_executor.block_healing(ctx, heal)
    typed_executor.block_healing(ctx, heal)
    assert foe.current_hp == 10 + 14 + 20


def test_frightened_cannot_close_in_and_charmed_cannot_attack_the_charmer():
    engine, me, foe = _two("FEAR-CHARM")
    engine._apply_condition(me, "condition:typed.frightened", "src.fear", foe.entity_id, expires_on="UNTIL_REMOVED")
    moves = [c for c in engine.legal_candidates() if c.kind.value == "MOVE" and c.actor_id == me.entity_id]
    start = engine.grid.distance_ft(me.position, foe.position)
    assert moves and all(engine.grid.distance_ft(c.destination, foe.position) >= start for c in moves)
    me.conditions.clear()
    engine._apply_condition(me, "condition:typed.charmed", "src.charm", foe.entity_id, expires_on="UNTIL_REMOVED")
    assert not any(foe.entity_id in c.target_ids for c in engine.legal_candidates() if c.actor_id == me.entity_id and c.kind.value != "MOVE")


def test_extinguish_puts_out_a_burn_on_yourself():
    from tests.test_typed_executor import _intent

    engine, me, foe = _two("EXTINGUISH")
    assert "Extinguish flames" not in {c.display_name.split(" ->")[0] for c in engine.legal_candidates()}
    engine._apply_condition(me, "condition:typed.burning", "src.fire", foe.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN", data={"burn": 3})
    put_out = next(c for c in engine.legal_candidates() if c.source_definition_id.endswith(".extinguish"))
    engine.execute_intent(_intent(put_out))
    assert not me.conditions


def test_guarding_method_gives_the_target_disadvantage_against_you_only():
    from combat import typed_executor
    from combat.gate2_runtime_content import LEE
    from tests.test_factory_combat_compiler import ACTOR, ROOT, _weapons_of
    from combat.gate2_engine import Gate2Engine
    from combat.gate2_runtime_content import AN

    bundle, _ = _weapons_of(["tianxia.mortal.weapon.jian"], paths=("tianxia.path.body_refining",))
    engine = Gate2Engine(ROOT, match_seed="GUARDING", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [ACTOR, AN, LEE], "team_by_actor": {ACTOR: "team:a", AN: "team:b", LEE: "team:a"}})
    me, foe, ally = engine.state.actors[ACTOR], engine.state.actors[AN], engine.state.actors[LEE]
    action = engine.action_catalog[next(a for a in me.action_ids if a.endswith(".weapon.jian"))]
    typed_executor.block_guard_against(typed_executor.Context(engine, me, action, None, action.parameters["typed"], [foe], foe, {}), {})
    assert (engine._attack_mode(foe, me), engine._attack_mode(foe, ally)) == ("DISADVANTAGE", "NORMAL")

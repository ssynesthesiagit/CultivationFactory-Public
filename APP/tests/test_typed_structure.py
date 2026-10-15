"""Abilities are delivered properly and talents that modify other abilities work (owner 2026-09-25).

Owner: "it also looks like modifying talents with other talents when possible isn't an option ... just do
the whole thing."  Found on the way: 107 abilities that say "make a ranged Cultivation Attack" hit
without an attack roll, and 175 saving throws did not gate their damage.
"""

from pathlib import Path

from combat.factory_compiler import apply_modifiers, compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind
from factory_authoring.typed_mechanics import cl_dice_table
from factory_authoring.typed_structure import from_v2, modifier_from_text, nest_saves, structure

ROOT = Path(__file__).resolve().parents[1]


def test_an_ability_that_makes_an_attack_rolls_to_hit():
    text = "Make a ranged Cultivation Attack. Hit: the target takes 2d6 Fire damage and cannot take Reactions."
    flat = [{"type": "damage", "dice": "2d6", "damage_types": ["fire"]}, {"type": "condition", "condition": "reaction_denied"},
            {"type": "temp_hp", "applies_to": "self", "formula": "pb"}]
    tree = structure(flat, text)
    assert tree[0]["type"] == "attack" and tree[0]["attack_kind"] == "cultivation_ranged"
    assert [row["type"] for row in tree[0]["on_hit"]] == ["damage", "condition"]
    assert tree[0]["on_hit"][0]["dice"]["count"] == 2  # dice text became the parser's dice object
    assert tree[1]["type"] == "temp_hp"  # a self effect is not gated by the hit
    for named in ("Make a ranged Music Attack.", "Make one Batter attack.", "Make a Talisman Attack. On a hit, ..."):
        assert structure([{"type": "damage", "dice": "1d6"}], named)[0]["type"] == "attack"


def test_a_saving_throw_gates_the_effects_after_it():
    text = "Each creature makes a Dexterity saving throw. Failed Save: 2d6 Fire damage and knocked Prone. Success: half damage."
    flat = [{"type": "save", "ability": "dex"}, {"type": "damage", "dice": "2d6"}, {"type": "condition", "condition": "prone"}]
    tree = nest_saves(flat, text)
    assert len(tree) == 1 and [row["type"] for row in tree[0]["on_fail"]] == ["damage", "condition"]
    assert tree[0]["on_success"][0]["type"] == "half_damage"
    # Damage printed before the save is not gated by it.
    before = nest_saves([{"type": "damage", "dice": "1d6"}, {"type": "save", "ability": "con"}, {"type": "condition", "condition": "poisoned"}])
    assert before[0]["type"] == "damage" and before[1]["on_fail"][0]["condition"] == "poisoned"


def test_the_structured_pass_keeps_damage_it_could_not_ground():
    result = {"delivery": "attack", "attack_kind": "ranged", "attack_count": 1, "on_hit": [], "effects": []}
    prior = [{"type": "damage", "dice": "1d10", "formula": "key_ability_modifier", "origin": "model"},
             {"type": "condition", "condition": "reaction_denied", "origin": "parser"}]
    tree = from_v2(result, prior, "Make a ranged Cultivation Attack. On hit, Ruin damage based on your Realm; it cannot take Reactions.")
    assert tree[0]["type"] == "attack"
    assert {row["type"] for row in tree[0]["on_hit"]} == {"damage", "condition"}


def test_cl_and_realm_damage_tables_are_read():
    cl = "| Cultivation Level | Damage |\n| --- | ---: |\n| CL 1-4 | 1d8 Psychic |\n| CL 5-10 | 2d8 Psychic |\n| CL 11-16 | 3d8 |"
    assert cl_dice_table(cl) == [[1, 4, 1, 8], [5, 10, 2, 8], [11, 16, 3, 8]]
    realm = ("| Realm | Safe |\n|---|---:|\n| Mortal | 1d10 + mod |\n| Foundation | 2d10 + mod |\n| Core Formation | 3d10 |\n"
             "| Realm | Unbound |\n| Mortal | 2d10 |\n| Foundation | 4d10 |")
    assert cl_dice_table(realm) == [[1, 4, 1, 10], [5, 9, 2, 10], [10, 14, 3, 10]]  # the first (safe) table


def test_a_modifier_is_read_from_the_earlier_typing():
    text = "When Water Lash hits, you may spend 1 CP to wrap the target. It must succeed on a Strength saving throw or become Grappled."
    modifier = modifier_from_text("Water Whip", text, "Water Lash", "When Water Lash hits",
                                  [{"type": "save", "ability": "str"}, {"type": "condition", "condition": "grappled"}])
    assert modifier["targets"] == ["Water Lash"] and modifier["when"] == "hit" and modifier["optional"] and modifier["extra_cp"] == 1
    assert modifier["effects"][0]["on_fail"][0]["condition"] == "grappled"


def _mechanic(key, name, economy, effects, modifier=None, cost=None):
    return {"mechanic_id": key, "name": name, "sphere_id": "tianxia.sphere.water", "kind": "talent",
            "activation": {"economy": economy}, "effects": effects, "riders": [], "range": {"kind": "feet", "feet": 30},
            "area": None, "duration": {"kind": "instant"}, "cost": cost or [], **({"modifier": modifier} if modifier else {})}


LASH = [{"type": "attack", "attack_kind": "cultivation_ranged", "count": 1,
         "on_hit": [{"type": "damage", "dice": {"count": 1, "sides": 8}, "damage_types": ["bludgeoning"]}]}]
AUTHORITY = {"mechanics": {
    "LASH": _mechanic("LASH", "Water Lash", "action", LASH),
    "WHIP": _mechanic("WHIP", "Water Whip", "passive", [], {
        "targets": ["Water Lash"], "scope": "named", "when": "hit", "optional": True, "extra_cp": 1, "limit": "none",
        "effects": [{"type": "save", "ability": "str", "on_fail": [{"type": "condition", "condition": "grappled"}], "on_success": []}]}),
    "EDGE": _mechanic("EDGE", "Cutting Current", "passive", [], {
        "targets": ["Water Lash"], "scope": "named", "when": "hit", "optional": False, "limit": "none", "damage_type": "slashing",
        "effects": [{"type": "extra_damage", "formula": "pb", "damage_types": ["slashing"]}]}),
    "STREAM": _mechanic("STREAM", "Flowing Response", "reaction", []),
    "WRIST": _mechanic("WRIST", "Hand on the Wrist", "passive", [], {
        "targets": ["Flowing Response"], "scope": "named", "when": "success", "optional": False, "limit": "none",
        "effects": [{"type": "condition", "condition": "reaction_denied"}]}),
}}
SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Qi Cultivation"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Qi", "maximum": 20}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
        "speed": {"walking_ft": 30}, "technique_save_dc": 15, "technique_attack_bonus": 7,
    },
    "spheres_and_talents": {"learned_talent_record_ids": ["LASH", "WHIP", "EDGE", "STREAM", "WRIST"]},
}


def test_modifiers_change_the_ability_or_become_their_own_choice():
    bundle = compile_character(SHEET, actor_id="actor:factory.mod", typed_authority=AUTHORITY)
    actions = {row["display_name"]: row for row in bundle["action_catalog"]}
    lash, whip = actions["Water Lash"], actions["Water Lash + Water Whip"]
    # Always-on (Cutting Current): the base ability deals slashing damage plus PB on a hit.
    hit = lash["parameters"]["typed"]["effects"][0]["on_hit"]
    assert hit[0]["damage_types"] == ["slashing"] and any(row["type"] == "extra_damage" for row in hit)
    # Optional (Water Whip, 1 CP): its own choice with the save riding the hit.
    whip_hit = whip["parameters"]["typed"]["effects"][0]["on_hit"]
    assert any(row["type"] == "save" and row["on_fail"][0]["condition"] == "grappled" for row in whip_hit)
    assert ["resource:core.qi", 1] in [list(cost) for cost in whip["costs"]]
    assert whip["parameters"]["typed"]["variant_of"] == lash["source_definition_id"]
    report = {row["name"]: row for row in bundle["modifiers"]}
    assert report["Water Whip"]["status"] == "applied" and report["Cutting Current"]["applied"] == ["Water Lash"]
    # A modifier of a reaction that is not automated yet is reported, not dropped.
    assert report["Hand on the Wrist"]["not_automated_targets"] == ["Flowing Response"]
    assert "Water Whip" not in bundle["diagnostics"]["skipped"]["passive"]


def test_variants_are_capped_per_ability():
    built = {"LASH": {"action_id": "a:lash", "name": "Water Lash", "economy": "action", "target_kind": "HOSTILE_ENTITY", "range_ft": 30,
                      "costs": [], "typed": {"effects": LASH, "riders": []}, "mechanic": AUTHORITY["mechanics"]["LASH"], "modifiers": []}}
    mechanics = {"LASH": AUTHORITY["mechanics"]["LASH"]}
    for index in range(12):
        mechanics[f"M{index}"] = _mechanic(f"M{index}", f"Mod {index}", "passive", [], {
            "targets": ["Water Lash"], "scope": "named", "when": "hit", "optional": True, "limit": "none", "extra_cp": 1,
            "effects": [{"type": "extra_damage", "flat": index + 1}]})
    apply_modifiers(built, list(mechanics), mechanics, "qi", {"qi": 10})
    assert len(built["LASH"]["variants"]) == 8


def _engine_with(typed: dict, seed: str) -> tuple[Gate2Engine, str]:
    engine = Gate2Engine(ROOT, match_seed=seed)
    actor = engine.state.actors[engine.state.current_actor_id]
    action = ActionDefinition(source_definition_id="action:typed.test", display_name="Typed test", owner_id=actor.entity_id,
                              economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
                              range_ft=500, parameters={"typed": typed})
    engine.action_catalog[action.source_definition_id] = action
    actor.action_ids = (*actor.action_ids, action.source_definition_id)
    return engine, actor.entity_id


def _run(engine):
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
    engine.execute_intent(ActionIntent(intent_id="test:typed", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=candidate.actor_id,
                                       target_ids=candidate.target_ids, destination=candidate.destination))


def test_a_cultivation_attack_that_only_pushes_rolls_to_hit_and_no_phantom_damage():
    push = {"effects": [{"type": "attack", "attack_kind": "cultivation_ranged", "count": 1,
                         "on_hit": [{"type": "forced_movement", "distance_ft": 10, "direction": "away"}]}],
            "numbers": {"pb": 4, "attack_bonus": 40}, "duration": {"kind": "instant"}}
    engine, _ = _engine_with(push, "TYPED-PUSH")
    _run(engine)
    mine = [e.event_type for e in engine.events if e.source_definition_id == "action:typed.test"]
    assert "ATTACK_ROLLED" in mine and "DAMAGE_ROLLED" not in mine


def test_on_miss_effects_and_once_per_turn_modifiers():
    miss = {"effects": [{"type": "attack", "attack_kind": "cultivation_ranged", "count": 2,
                         "on_hit": [{"type": "damage", "dice": {"count": 1, "sides": 4}, "damage_types": ["force"]}],
                         "on_miss": [{"type": "temp_hp", "applies_to": "self", "flat": 3}]}],
            "numbers": {"pb": 4, "attack_bonus": -40}, "duration": {"kind": "instant"}}
    engine, actor_id = _engine_with(miss, "TYPED-MISS")
    _run(engine)
    assert engine.state.actors[actor_id].temporary_hp == 3  # both attacks missed; temp HP does not stack

    once = {"effects": [{"type": "attack", "attack_kind": "cultivation_ranged", "count": 2,
                         "on_hit": [{"type": "damage", "dice": {"count": 1, "sides": 4}, "damage_types": ["force"]},
                                    {"type": "temp_hp", "applies_to": "self", "flat": 1, "modifier_once": "TEST"},
                                    {"type": "damage", "flat": 1, "damage_types": ["force"], "modifier_once": "TEST"}]}],
            "numbers": {"pb": 4, "attack_bonus": 40}, "duration": {"kind": "instant"}}
    engine, actor_id = _engine_with(once, "TYPED-ONCE-7")
    _run(engine)
    mine = [e for e in engine.events if e.source_definition_id == "action:typed.test"]
    hits = sum(1 for e in mine if e.event_type == "ATTACK_ROLLED" and e.payload.get("provisional_hit"))
    commits = sum(1 for e in mine if e.event_type == "DAMAGE_COMMITTED")
    # Each hit rolls its d4; the once-per-turn modifier's extra damage lands on the first hit only.
    assert hits >= 1 and commits == hits + 1
    assert sum(1 for e in mine if e.event_type == "TEMP_HP_GRANTED") == 1


def test_free_options_are_always_used_and_printed_costs_count():
    """Owner 2026-09-25: Reflection Cut showed as 15 free "+ Reflection Cut" choices though it spends a Mirror Trace."""
    mechanics = {
        "LASH": AUTHORITY["mechanics"]["LASH"],
        "FREE": _mechanic("FREE", "Sharp Current", "passive", [], {
            "targets": ["Water Lash"], "scope": "named", "when": "hit", "optional": True, "limit": "none",
            "effects": [{"type": "extra_damage", "flat": 2}]}),
        "CUT": _mechanic("CUT", "Reflection Cut", "passive", [], {
            "targets": [], "scope": "any_sphere_technique", "when": "hit", "optional": True, "limit": "none",
            "precondition": "Requires 1 Mirror Trace", "effects": [{"type": "extra_damage", "formula": "pb"}]}),
    }
    built = {"LASH": {"action_id": "a:lash", "name": "Water Lash", "economy": "action", "target_kind": "HOSTILE_ENTITY", "range_ft": 30,
                      "costs": [], "typed": {"effects": LASH, "riders": [], "numbers": {"pb": 4}}, "mechanic": mechanics["LASH"], "modifiers": []}}
    trace = {"name": "Mirror Trace", "resource_id": "foundation.resource.mirror"}
    report = {row["name"]: row for row in apply_modifiers(built, list(mechanics), mechanics, "qi", {"qi": 10}, foundation_resource=trace)}
    assert report["Sharp Current"]["applied"] == ["Water Lash"]  # free and harmless: always on, no extra choice
    variants = built["LASH"]["variants"]
    assert len(variants) == 1 and ("foundation.resource.mirror", 1) in variants[0]["costs"]



def test_one_effect_stated_twice_runs_once():
    """Owner 2026-09-26 tournament check: Wind Lash's typing carried its push five times."""
    from factory_authoring.typed_structure import dedupe

    push = {"type": "forced_movement", "applies_to": "target", "distance_ft": 10}
    tree = dedupe([{"type": "attack", "on_hit": [push, dict(push), {"type": "condition", "condition": "reaction_denied"},
                                                 {"type": "reaction_denied"}, {**push, "distance_ft": 5}]}])
    assert [row.get("distance_ft") for row in tree[0]["on_hit"] if row["type"] == "forced_movement"] == [10, 5]
    assert sum(1 for row in tree[0]["on_hit"] if "reaction_denied" in (row.get("type"), row.get("condition"))) == 1
    # A distance written as "speed" (move up to your speed) is a value like any other.
    assert len(dedupe([{"type": "movement", "distance_ft": "speed"}, {"type": "movement", "distance_ft": "speed"}])) == 1


def test_a_spheres_broad_modifier_stays_in_its_sphere():
    """Owner 2026-09-26 tournament check: a Barrage talent rode a Qi Path feature."""
    mechanics = {
        "LASH": AUTHORITY["mechanics"]["LASH"],
        "ARM": {**_mechanic("ARM", "Domain Armament", "bonus_action", LASH), "sphere_id": None, "path_id": "tianxia.path.qi_cultivation"},
        "SCAV": {**_mechanic("SCAV", "Battlefield Scavenger", "passive", [], {
            "targets": [], "scope": "any_attack", "when": "hit", "optional": True, "limit": "none", "extra_cp": 1,
            "effects": [{"type": "extra_damage", "flat": 2}]}), "sphere_id": "tianxia.sphere.barrage"},
    }
    built = {key: {"action_id": f"a:{key}", "name": mechanics[key]["name"], "economy": "action", "target_kind": "HOSTILE_ENTITY",
                   "range_ft": 30, "costs": [], "typed": {"effects": LASH, "riders": [], "numbers": {"pb": 4}}, "mechanic": mechanics[key],
                   "modifiers": []} for key in ("LASH", "ARM")}
    apply_modifiers(built, list(mechanics), mechanics, "qi", {"qi": 10})
    assert not built["ARM"]["variants"] and not built["LASH"]["variants"]  # Water Lash is Water, not Barrage



def test_reusing_an_ability_refreshes_its_bonus_instead_of_stacking():
    """Owner 2026-09-26 tournament: Domain Armament's +2 AC stacked every turn (AC 18 -> 42, fights hit the round limit)."""
    from factory_authoring.typed_structure import dedupe

    armor = {"effects": [{"type": "ac_bonus", "applies_to": "self", "amount": 2}], "numbers": {"pb": 4}, "duration": {"kind": "minutes", "amount": 1}}
    engine, actor_id = _engine_with(armor, "TYPED-REFRESH")
    action = engine.action_catalog["action:typed.test"]
    engine.action_catalog["action:typed.test"] = action.model_copy(update={"target_kind": "SELF", "range_ft": None})
    actor = engine.state.actors[actor_id]
    from combat import typed_executor
    from combat.typed_executor import Context
    for _ in range(3):  # three uses
        ctx = Context(engine, actor, engine.action_catalog["action:typed.test"], None, armor, [], None)
        typed_executor.run_effects(ctx, armor["effects"])
    assert engine._ac_modifier(actor) == 2
    # The parser's "amount" and a model's "flat" are the same bonus.
    assert len(dedupe([{"type": "ac_bonus", "amount": 2}, {"type": "ac_bonus", "applies_to": "self", "flat": 2}])) == 1



def test_a_header_after_an_intro_sentence_is_still_read():
    """Owner 2026-09-26 tournament: Coagulate's "Cost: 1 CP" came after an intro line and was lost (it ran free)."""
    from factory_authoring.typed_mechanics import parse_header

    text = ("#### Coagulate - Thread Talent\nWhen you learn the Blood sphere, you learn Coagulate automatically.\n"
            "Action Type: Bonus Action\nFactory Combat Bucket: bonus_action\nRange: 30 feet\nCost: 1 CP\nChoose one:\n"
            "grant Temporary HP equal to Proficiency Bonus.")
    header, body = parse_header(text.splitlines())
    assert header["cost"] == "1 CP" and header["action_type"] == "Bonus Action" and header["range"] == "30 feet"
    assert not any(line.startswith("Cost:") for line in body)


def test_a_parser_bonus_restated_with_its_qualifier_runs_once():
    """Owner 2026-09-26 tournament: Domain Armament's "+2 AC" ran as an always-on self bonus beside the model's
    "+2 AC against ranged attack rolls" for the protected creature."""
    from factory_authoring.typed_structure import dedupe

    parser = {"type": "ac_bonus", "amount": 2, "evidence": "+2 AC", "origin": "parser"}
    model = {"type": "ac_bonus", "applies_to": "ally", "flat": 2, "on": "ranged attack rolls", "origin": "model",
             "evidence": "The creature gains: `+2 AC against ranged attack rolls`"}
    assert dedupe([parser, model]) == [model]
    # A different number, or a phrase the model does not quote, is a different effect.
    assert len(dedupe([{**parser, "amount": 3, "evidence": "+3 AC"}, model])) == 2
    assert len(dedupe([parser, {**model, "evidence": "gains a bonus to AC against ranged attack rolls"}])) == 2


def test_the_header_cost_is_not_charged_again_as_a_typed_spend():
    """Owner 2026-09-26 tournament: Talisman Recall's typing restated "Cost: 1 CP" as a spend, so it paid 2 CP."""
    from factory_authoring.typed_structure import drop_cost_restatement

    spend = {"type": "spend_resource", "flat": 1, "evidence": "Cost: 1 CP"}
    other = {"type": "spend_resource", "flat": 1, "evidence": "you may spend 1 Mirror Trace"}
    cost = [[{"resource": "cp", "amount": 1}]]
    assert drop_cost_restatement([spend, other], cost) == [other]
    assert drop_cost_restatement([{"type": "save", "on_fail": [spend], "on_success": []}], cost)[0]["on_fail"] == []
    assert drop_cost_restatement([spend], []) == [spend]  # the header was not read: this is the only charge


def test_an_ac_bonus_against_ranged_attacks_does_not_stop_a_sword():
    """Owner 2026-09-26 tournament: Domain Armament's "+2 AC against ranged attack rolls" ran as plain AC."""
    from combat import typed_executor, typed_reactions
    from combat.typed_executor import Context, ac_field

    guard = {"type": "ac_bonus", "applies_to": "self", "flat": 2, "on": "ranged attack rolls",
             "evidence": "The creature gains: `+2 AC against ranged attack rolls`"}
    assert ac_field(guard) == "armor_class_vs_ranged"
    assert ac_field({"type": "ac_bonus", "evidence": "gain +1 AC against melee attack rolls until the start of your next turn"}) == "armor_class_vs_melee"
    assert ac_field({"type": "ac_bonus", "evidence": "Gain +3 AC until the start of your next turn, including against the triggering attack"}) == "armor_class"
    typed = {"effects": [guard], "numbers": {"pb": 4}, "duration": {"kind": "rounds", "amount": 1}}
    engine, actor_id = _engine_with(typed, "TYPED-RANGED-AC")
    actor = engine.state.actors[actor_id]
    typed_executor.run_effects(Context(engine, actor, engine.action_catalog["action:typed.test"], None, typed, [], None), typed["effects"])
    assert engine._ac_modifier(actor) == 0  # the sealed engine's plain AC is unchanged
    attacker = next(a for a in engine.state.actors.values() if a.team_id != actor.team_id)
    ac = actor.armor_class
    assert typed_reactions.on_attack_hit(engine, attacker, actor, {"range_ft": 60}, ac + 1, 12, ac) == (ac + 2, False)
    assert typed_reactions.on_attack_hit(engine, attacker, actor, {"range_ft": None}, ac + 1, 12, ac)[1] is True


def test_a_later_trigger_is_not_an_effect_of_using_the_ability():
    """Owner 2026-09-26 tournament: Demon Mark gained its Devoured Essence on every cast, and Oni Form's
    "once per turn when you hit with an unarmed strike, deal an additional 2d6" hit at activation."""
    from combat import typed_executor
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    from combat.typed_executor import Context
    from factory_authoring.typed_structure import mark_deferred

    essence = {"type": "gain_resource", "applies_to": "self", "flat": 1, "evidence": "when it drops to 0 HP, gain 1 Devoured Essence"}
    oni = {"type": "extra_damage", "dice": {"count": 2, "sides": 6}, "damage_types": ["necrotic"],
           "evidence": "Once per turn when you hit with an unarmed strike, deal an additional `2d6` Necrotic damage instead"}
    now = {"type": "temp_hp", "flat": 5, "evidence": "gain 5 temporary HP"}
    effects = mark_deferred([essence, oni, now])
    assert [bool(row.get("deferred")) for row in effects] == [True, True, False]

    form = {"effects": effects, "numbers": {"pb": 4}, "duration": {"kind": "minutes", "amount": 1}}
    engine, actor_id = _engine_with(form, "TYPED-DEFERRED")
    actor = engine.state.actors[actor_id]
    enemy = next(a for a in engine.state.actors.values() if a.team_id != actor.team_id and a.active)
    engine.action_catalog["action:typed.test"] = engine.action_catalog["action:typed.test"].model_copy(update={"target_kind": "SELF", "range_ft": None})
    before = len(engine.events)
    typed_executor.run_effects(Context(engine, actor, engine.action_catalog["action:typed.test"], None, form, [], None), form["effects"])
    kinds = [e.event_type for e in engine.events[before:]]
    assert "RESOURCE_GAINED" not in kinds and "DAMAGE_ROLLED" not in kinds and "TEMP_HP_GRANTED" in kinds
    assert [m.target_field for m in actor.modifiers.values()].count("typed_on_hit") == 1
    # Using it again refreshes the bonus, and logs the removal so the Gate 3 replay reproduces the state.
    mark = len(engine.events)
    typed_executor.run_effects(Context(engine, actor, engine.action_catalog["action:typed.test"], None, form, [], None), form["effects"])
    assert [m.target_field for m in actor.modifiers.values()].count("typed_on_hit") == 1
    assert any(e.event_type == "MODIFIER_REMOVED" and e.payload.get("reason") == "REFRESHED" for e in engine.events[mark:])

    def strike(kind: str, range_ft: int | None) -> list[str]:
        typed = {"effects": [{"type": "attack", "attack_kind": kind, "count": 1, "on_hit": [], "on_miss": []}],
                 "numbers": {"pb": 4, "attack_bonus": 60}, "range_ft": range_ft, "weapon": {"damage": {"count": 1, "sides": 4, "modifier": 0}, "damage_type": "BLUDGEONING"}}
        action = ActionDefinition(source_definition_id=f"action:typed.strike.{kind}", display_name=f"{kind} strike", owner_id=actor_id,
                                  economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=range_ft or 5,
                                  parameters={"typed": typed})
        engine.action_catalog[action.source_definition_id] = action
        mark = len(engine.events)
        typed_executor.run_effects(Context(engine, actor, action, None, typed, [enemy], enemy), typed["effects"])
        return [e.source_definition_id for e in engine.events[mark:] if e.event_type == "DAMAGE_ROLLED"]

    assert strike("cultivation_ranged", 60).count("action:typed.test") == 0  # not an unarmed strike
    # An attack is rolled only at a target in reach (fight audit 2026-09-29): the unarmed strikes stand next to it.
    enemy.position = actor.position.model_copy(update={"x": actor.position.x + 1 if actor.position.x + 1 < engine.grid.width else actor.position.x - 1})
    assert strike("unarmed", None).count("action:typed.test") == 1
    assert strike("unarmed", None).count("action:typed.test") == 0  # once per turn


def test_a_modifier_of_your_own_saves_does_not_ride_techniques_that_force_one():
    """Owner 2026-09-26 tournament: Meridian Reinforcement (advantage on your saves against poison) rode every
    Iron Voice and Wind Lash; Broken Gourd Recovery's move on a failed save would have moved the caster."""
    iron_voice = [{"type": "save", "ability": "con", "on_fail": [{"type": "condition", "condition": "frightened"}], "on_success": []}]
    mechanics = {
        "VOICE": {**_mechanic("VOICE", "Iron Voice", "bonus_action", iron_voice), "sphere_id": None},
        "MERIDIAN": {**_mechanic("MERIDIAN", "Meridian Reinforcement", "passive", [], {
            "targets": [], "scope": "any_save", "when": "use", "optional": False, "limit": "none",
            "effects": [{"type": "advantage", "applies_to": "self", "on": "saving throws against the Poisoned condition"}]}), "sphere_id": None},
        "HEX": {**_mechanic("HEX", "Grave Hex", "passive", [], {
            "targets": [], "scope": "any_save", "when": "use", "optional": False, "limit": "none",
            "effects": [{"type": "disadvantage", "applies_to": "target", "on": "saving throw"}]}), "sphere_id": None},
    }
    built = {"VOICE": {"action_id": "a:VOICE", "name": "Iron Voice", "economy": "bonus_action", "target_kind": "HOSTILE_ENTITY",
                       "range_ft": 30, "costs": [], "typed": {"effects": iron_voice, "riders": [], "numbers": {"pb": 4}},
                       "mechanic": mechanics["VOICE"], "modifiers": []}}
    apply_modifiers(built, list(mechanics), mechanics, "stamina", {"stamina": 10})
    assert built["VOICE"]["modifiers"] == ["HEX"]  # the target's save is changed; the caster's own saves are not a technique

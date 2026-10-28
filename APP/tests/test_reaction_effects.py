"""Reaction effects go numeric (owner 2026-09-26): the generic reaction runner
(combat/typed_reactions.py) can now reduce incoming damage (damage_modifier/half_damage on a
"damaged" trigger), add a bonus that turns a failed save into a success or an attack penalty that
turns a hit into a miss (attack_modifier), and gain_resource/spend_resource actually move a
resource (combat/typed_executor.py) -- including a Foundation's own free ("no_action") resource
generation, which no longer requires or spends the Reaction (combat/factory_compiler.py "free").
Built like combat/tests/test_generic_reactions.py.
"""

from pathlib import Path
import pytest

from combat import typed_reactions
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN

ROOT = Path(__file__).resolve().parents[1]


def _mechanic(key: str, name: str, economy: str, effects: list, *, trigger: str | None = None) -> dict:
    return {"mechanic_id": key, "name": name, "sphere_id": "tianxia.sphere.test", "kind": "talent",
            "activation": {"economy": economy, "trigger": trigger}, "effects": effects, "riders": [],
            "range": None, "area": None, "duration": {"kind": "instant"}, "cost": []}


AUTHORITY = {"mechanics": {
    "SCALE_WARD": _mechanic("SCALE_WARD", "Scale Ward", "reaction",
        [{"type": "damage_modifier", "applies_to": "self", "formula": "pb", "flat": 2, "evidence": "reduce the damage by PB + 2"},
         {"type": "spend_resource", "applies_to": "self", "flat": 3, "formula": "none", "evidence": "spend 3 Qi"}],
        trigger="You take damage."),
    "IRON_WILL": _mechanic("IRON_WILL", "Iron Will", "reaction",
        [{"type": "attack_modifier", "applies_to": "self", "formula": "pb",
          "on": "the failed saving throw", "evidence": "Add your Proficiency Bonus to the failed saving throw."}],
        trigger="You fail a saving throw."),
    "DEFLECTING_STANCE": _mechanic("DEFLECTING_STANCE", "Deflecting Stance", "reaction",
        [{"type": "attack_modifier", "applies_to": "attacker", "flat": 6, "evidence": "Subtract 6 from the attack roll."}],
        trigger="A creature hits you with a melee attack"),
    "CLOUD_SLEEVE": _mechanic("CLOUD_SLEEVE", "Cloud-Sleeve Guard", "reaction",
        [{"type": "attack_modifier", "applies_to": "attacker", "flat": 6, "evidence": "Subtract 6 from the attack roll."}],
        trigger="A creature makes an attack roll against you"),
    "GATHER_RESOLVE": _mechanic("GATHER_RESOLVE", "Gather Resolve", "no_action",
        [{"type": "gain_resource", "applies_to": "self", "flat": 5, "formula": "none", "evidence": "gain 5 Qi"}],
        trigger="Once per round, after a hostile creature misses you with an attack."),
}}
REACTOR = "actor:factory.reaction_effects_reactor"
REACTOR_SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Qi Cultivation"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Qi", "maximum": 20}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
        "speed": {"walking_ft": 30}, "technique_save_dc": 15, "technique_attack_bonus": 7,
    },
    "spheres_and_talents": {"learned_talent_record_ids": list(AUTHORITY["mechanics"])},
}


def _engine(hold: str | None = None) -> Gate2Engine:
    bundle = compile_character(REACTOR_SHEET, actor_id=REACTOR, typed_authority=AUTHORITY, reaction_hold=hold)
    return Gate2Engine(ROOT, match_seed="REACTION-EFFECTS-ENGINE", typed_bundles=(bundle,),
                       roster_setup={"primary_actor_ids": [REACTOR, AN], "team_by_actor": {REACTOR: "team:a", AN: "team:b"}})


@pytest.mark.parametrize("ranked", [False, True])
def test_ask_me_keeps_hit_defense_even_when_auto_would_save_reaction(monkeypatch, ranked):
    """The player's legal choices cannot be filtered by automatic usefulness/ranking."""
    engine = _engine()
    engine.typed_ask_reactors = frozenset({REACTOR})
    rows = engine.typed_reaction_rows[REACTOR]
    for row in rows:
        row["ask"] = True
        if ranked:
            row["priority"] = 0 if row["feature_id"] == "SCALE_WARD" else 1
    asked = []
    def decline(engine, row, reactor, checkpoint, **kwargs):
        asked.append(row["feature_id"])
        return False
    monkeypatch.setattr(typed_reactions, "_consent", decline)
    target, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    target.reaction_available = True
    typed_reactions.on_attack_hit(engine, attacker, target, {"range_ft": None}, 40, 10, 14)
    assert "DEFLECTING_STANCE" in asked
    assert target.reaction_available


def test_compiler_wires_every_new_effect_shape_instead_of_skipping_it():
    bundle = compile_character(REACTOR_SHEET, actor_id="actor:factory.reaction_effects_compile", typed_authority=AUTHORITY)
    reactions = {row["feature_id"]: row for row in bundle["typed_reactions"] if row.get("block") == "generic"}
    assert set(reactions) == set(AUTHORITY["mechanics"])
    assert reactions["GATHER_RESOLVE"]["free"] is True
    assert all(not reactions[key].get("free") for key in AUTHORITY["mechanics"] if key != "GATHER_RESOLVE")
    assert reactions["GATHER_RESOLVE"]["effects"][0]["resource_id"] == "resource:core.qi"
    assert not bundle["diagnostics"]["skipped"]["reaction"] and not bundle["diagnostics"]["skipped"]["passive"]


def test_a_damaged_reaction_reduces_pending_damage_by_pb_plus_flat():
    engine = _engine()
    reactor = engine.state.actors[REACTOR]
    reactor.reaction_available = True
    reduced = typed_reactions.on_damage(engine, reactor, 20, 0, source_definition_id="action:test.attack", source_actor_id=AN)
    assert reduced == 20 - (4 + 2)  # Scale Ward: PB(4) + flat(2)
    assert not reactor.reaction_available
    resolved = [e for e in engine.events if e.source_definition_id == "SCALE_WARD" and e.event_type == "REACTION_RESOLVED"]
    assert resolved and resolved[-1].payload["reduction"] == 6


def test_a_save_bonus_turns_a_failure_into_a_success():
    engine = _engine()
    reactor = engine.state.actors[REACTOR]
    reactor.reaction_available = True
    roll = engine.roller.d20(modifier=0, actor_id=REACTOR, reason="TEST_SAVE")
    roll = roll.model_copy(update={"total": 10})  # a DC 13 save that fails by 3; Iron Will's +PB(4) covers it
    rescued = typed_reactions.on_save(engine, reactor, "CON", 13, roll, "action:test.save")
    assert rescued.total == 14 and not reactor.reaction_available
    resolved = [e for e in engine.events if e.source_definition_id == "IRON_WILL" and e.event_type == "REACTION_RESOLVED"]
    assert resolved and resolved[-1].payload["bonus"] == 4


def test_a_save_bonus_that_is_not_enough_does_not_spend_the_reaction():
    engine = _engine()
    reactor = engine.state.actors[REACTOR]
    reactor.reaction_available = True
    roll = engine.roller.d20(modifier=0, actor_id=REACTOR, reason="TEST_SAVE")
    roll = roll.model_copy(update={"total": 5})  # fails by 8; PB(4) alone cannot rescue it
    result = typed_reactions.on_save(engine, reactor, "CON", 13, roll, "action:test.save")
    assert result.total == 5 and reactor.reaction_available


def test_a_hit_reaction_penalty_turns_a_hit_into_a_miss():
    engine = _engine()
    reactor, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    reactor.reaction_available = True
    # Deflecting Stance: flat -6 against the attacker; a total of 15 vs AC 10 hits, but not once
    # the equivalent 6-point swing is applied.
    new_ac, hit = typed_reactions.on_attack_hit(engine, attacker, reactor, {"range_ft": None}, total=15, natural=15, effective_ac=10)
    assert hit is False and new_ac == 16
    assert not reactor.reaction_available
    resolved = [e for e in engine.events if e.source_definition_id == "DEFLECTING_STANCE" and e.event_type == "REACTION_RESOLVED"]
    assert resolved and resolved[-1].payload["attack_penalty"] == 6 and resolved[-1].payload["hit_after_recheck"] is False


def test_an_attacked_reaction_penalty_reduces_the_pending_attack_bonus():
    engine = _engine(hold="CLOUD_SLEEVE")  # held: on Auto it would wait for Scale Ward's damage reduction
    reactor, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    reactor.reaction_available = True
    spec = {"attack_bonus": 8, "range_ft": None}
    typed_reactions.on_attacked(engine, attacker, reactor, spec, None)
    assert spec["attack_bonus"] == 2  # Cloud-Sleeve Guard: -6 to the pending roll, before it is made
    assert not reactor.reaction_available
    resolved = [e for e in engine.events if e.source_definition_id == "CLOUD_SLEEVE" and e.event_type == "REACTION_RESOLVED"]
    assert resolved and resolved[-1].payload["attack_penalty"] == 6


def test_gain_resource_clamps_to_the_maximum_and_does_not_spend_a_free_rows_reaction():
    engine = _engine()
    reactor, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    reactor.resources["resource:core.qi"] = 18
    reactor.reaction_available = False  # a Foundation-style generation trigger costs no Reaction
    typed_reactions.on_attack_missed(engine, attacker, reactor, {"range_ft": None}, None)
    assert reactor.resources["resource:core.qi"] == 20  # clamped: +5 would have been 23
    assert not reactor.reaction_available  # unchanged: GATHER_RESOLVE never touches it (it is free)
    gained = [e for e in engine.events if e.source_definition_id == "GATHER_RESOLVE" and e.event_type == "RESOURCE_GAINED"]
    assert gained and gained[-1].payload == {"resource_id": "resource:core.qi", "requested": 5, "gained": 2, "current": 20}


def test_a_generated_resource_can_then_be_spent_by_a_real_reaction():
    """Mirror-Trace-style chain: a free generation trigger (Gather Resolve, on a miss) fills the pool,
    then a costed reaction's own spend_resource effect (Scale Ward, alongside its damage reduction)
    draws it back down."""
    engine = _engine()
    reactor, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    reactor.resources["resource:core.qi"] = 0
    reactor.reaction_available = True
    typed_reactions.on_attack_missed(engine, attacker, reactor, {"range_ft": None}, None)
    assert reactor.resources["resource:core.qi"] == 5 and reactor.reaction_available
    reduced = typed_reactions.on_damage(engine, reactor, 20, 0, source_definition_id="action:test.attack", source_actor_id=AN)
    assert reduced == 20 - 6  # Scale Ward's own damage_modifier still applies
    assert reactor.resources["resource:core.qi"] == 2  # ... alongside spending 3 of the 5 gained
    assert not reactor.reaction_available


def test_an_attacked_reaction_ac_bonus_counts_pb_and_lasts_until_the_next_turn():
    """Owner 2026-09-26 manual-control check (Flowing Response, "Increase your AC against the triggering melee
    attack by your Proficiency Bonus"): a PB AC bonus counted as 0 on the hit path, and on the declared path
    it ran with the reaction's instant duration, so it never expired."""
    authority = {"mechanics": {"YIELD": _mechanic("YIELD", "Yield", "reaction",
        [{"type": "ac_bonus", "applies_to": "self", "formula": "pb", "flat": 0,
          "evidence": "Increase your AC against the triggering melee attack by your Proficiency Bonus."}],
        trigger="A creature makes an attack roll against you")}}
    sheet = {**REACTOR_SHEET, "spheres_and_talents": {"learned_talent_record_ids": ["YIELD"]}}
    bundle = compile_character(sheet, actor_id=REACTOR, typed_authority=authority)
    engine = Gate2Engine(ROOT, match_seed="REACTION-AC-DURATION", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [REACTOR, AN], "team_by_actor": {REACTOR: "team:a", AN: "team:b"}})
    reactor, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    reactor.reaction_available = True
    typed_reactions.on_attacked(engine, attacker, reactor, {"attack_bonus": 8, "range_ft": None}, None)
    guards = [m for m in reactor.modifiers.values() if m.source_definition_id == "YIELD" and m.target_field == "armor_class"]
    assert [(m.value, m.expires_on) for m in guards] == [(4, "START_OF_SELF_NEXT_TURN")]


def test_hold_up_and_auto():
    """Owner 2026-09-26 ("make a hold up and auto option"): Hold keeps the Reaction for one reaction and holds the
    rest back (free triggers still fire); Auto keeps it for a damage soak/reduction rather than spending it on a
    reaction that cannot see the roll (Liu Ling's Cloud-Sleeve Guard used it up before Stamina Guard every round)."""
    held = compile_character(REACTOR_SHEET, actor_id=REACTOR, typed_authority=AUTHORITY, reaction_hold="SCALE_WARD")
    rows = {row["feature_id"]: row for row in held["typed_reactions"]}
    assert held["reaction_plan"]["mode"] == "custom" and held["reaction_plan"]["order"] == ["SCALE_WARD"]
    assert rows["CLOUD_SLEEVE"].get("held_back") and not rows["SCALE_WARD"].get("held_back")
    assert not rows["GATHER_RESOLVE"].get("held_back")  # a free trigger never spends the Reaction
    assert {row["id"] for row in held["reaction_plan"]["choices"]} >= {"CLOUD_SLEEVE", "SCALE_WARD", "IRON_WILL"}
    assert "GATHER_RESOLVE" not in {row["id"] for row in held["reaction_plan"]["choices"]}
    unknown = compile_character(REACTOR_SHEET, actor_id=REACTOR, typed_authority=AUTHORITY, reaction_hold="NOT_MINE")
    assert unknown["reaction_plan"]["mode"] == "auto"  # an unknown hold is Auto

    for hold, fires in ((None, False), ("SCALE_WARD", False), ("CLOUD_SLEEVE", True)):
        engine = _engine(hold)
        reactor, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
        reactor.reaction_available = True
        spec = {"attack_bonus": 8, "range_ft": None}
        typed_reactions.on_attacked(engine, attacker, reactor, spec, None)
        assert (spec["attack_bonus"] == 2) is fires, hold
        assert reactor.reaction_available is not fires, hold  # Auto and Hold Scale Ward keep it for the damage
    # With nothing to soak or reduce the damage, Auto uses the early reaction after all.
    only = {"mechanics": {"CLOUD_SLEEVE": AUTHORITY["mechanics"]["CLOUD_SLEEVE"]}}
    sheet = {**REACTOR_SHEET, "spheres_and_talents": {"learned_talent_record_ids": ["CLOUD_SLEEVE"]}}
    bundle = compile_character(sheet, actor_id=REACTOR, typed_authority=only)
    engine = Gate2Engine(ROOT, match_seed="REACTION-AUTO-NO-SOAK", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [REACTOR, AN], "team_by_actor": {REACTOR: "team:a", AN: "team:b"}})
    reactor, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    reactor.reaction_available = True
    spec = {"attack_bonus": 8, "range_ft": None}
    typed_reactions.on_attacked(engine, attacker, reactor, spec, None)
    assert spec["attack_bonus"] == 2


def test_auto_keeps_a_retaliation_for_the_damage_reduction():
    """Owner 2026-09-26: Du Daoyuan's Spines Answer Violence (strikes back on a hit) spent the Reaction before
    Stamina Guard every time. On Auto a hit-stage reaction that neither turns the hit into a miss nor reduces it
    waits for the damage-stage answer; held, it fires."""
    spines = _mechanic("SPINES", "Spines", "reaction",
                       [{"type": "damage", "applies_to": "attacker", "flat": 3, "evidence": "the attacker takes 3 piercing damage"}],
                       trigger="A creature hits you with a melee attack")
    authority = {"mechanics": {"SPINES": spines, "SCALE_WARD": AUTHORITY["mechanics"]["SCALE_WARD"]}}
    sheet = {**REACTOR_SHEET, "spheres_and_talents": {"learned_talent_record_ids": ["SPINES", "SCALE_WARD"]}}
    for hold, fires in ((None, False), ("SPINES", True)):
        bundle = compile_character(sheet, actor_id=REACTOR, typed_authority=authority, reaction_hold=hold)
        engine = Gate2Engine(ROOT, match_seed="REACTION-AUTO-SPINES", typed_bundles=(bundle,),
                             roster_setup={"primary_actor_ids": [REACTOR, AN], "team_by_actor": {REACTOR: "team:a", AN: "team:b"}})
        reactor, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
        reactor.reaction_available = True
        ac = reactor.armor_class
        assert typed_reactions.on_attack_hit(engine, attacker, reactor, {"range_ft": None}, ac + 5, 15, ac)[1] is True
        assert reactor.reaction_available is not fires, hold


def test_an_order_of_importance_with_some_turned_off():
    """Owner 2026-09-26: "having multiple you can hold up and order of importance on can some dont apply"."""
    plan = {"order": ["SCALE_WARD", "CLOUD_SLEEVE"], "off": ["IRON_WILL"]}
    bundle = compile_character(REACTOR_SHEET, actor_id=REACTOR, typed_authority=AUTHORITY, reaction_plan=plan)
    rows = {row["feature_id"]: row for row in bundle["typed_reactions"]}
    assert (rows["SCALE_WARD"]["priority"], rows["CLOUD_SLEEVE"]["priority"]) == (0, 1)
    assert rows["IRON_WILL"].get("held_back") and "priority" not in rows["GATHER_RESOLVE"]
    assert rows["DEFLECTING_STANCE"]["priority"] == 2  # not mentioned: used, after the ranked ones
    # Every fighter also has its Opportunity Attack in the plan (owner 2026-09-26), used after the ranked ones.
    assert bundle["reaction_plan"]["order"] == ["SCALE_WARD", "CLOUD_SLEEVE", "DEFLECTING_STANCE", "opportunity_attack"]
    assert bundle["reaction_plan"]["off"] == ["IRON_WILL"]
    auto = compile_character(REACTOR_SHEET, actor_id=REACTOR, typed_authority=AUTHORITY)["reaction_plan"]
    assert auto["mode"] == "auto" and auto["order"][0] == "SCALE_WARD"  # Auto's own order starts with the damage soak

    def declared(order):
        bundle = compile_character(REACTOR_SHEET, actor_id=REACTOR, typed_authority=AUTHORITY, reaction_plan={"order": order})
        engine = Gate2Engine(ROOT, match_seed="REACTION-ORDER", typed_bundles=(bundle,),
                             roster_setup={"primary_actor_ids": [REACTOR, AN], "team_by_actor": {REACTOR: "team:a", AN: "team:b"}})
        reactor, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
        reactor.reaction_available = True
        spec = {"attack_bonus": 8, "range_ft": None}
        typed_reactions.on_attacked(engine, attacker, reactor, spec, None)
        return spec["attack_bonus"], engine, reactor

    assert declared(["SCALE_WARD", "CLOUD_SLEEVE"])[0] == 8  # waits: Scale Ward, more important, can answer the damage
    bonus, engine, reactor = declared(["CLOUD_SLEEVE", "SCALE_WARD"])
    assert bonus == 2 and not reactor.reaction_available  # most important: fires before the roll
    # Ranked first, Scale Ward then answers the damage itself.
    _bonus, engine, reactor = declared(["SCALE_WARD", "CLOUD_SLEEVE"])
    assert typed_reactions.on_damage(engine, reactor, 20, 0) < 20 and not reactor.reaction_available

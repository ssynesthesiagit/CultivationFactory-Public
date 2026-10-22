"""Extended combat reactions (owner 2026-09-26): bystander/ally reactions, drop_to_zero/bloodied,
technique_targets/technique_used, condition_gained, critical_hit/natural_1, and a "hit"-kind damage
reduction that lands on the following on_damage call. Builds on tests/test_generic_reactions.py's
fixtures and style; see combat/typed_reactions.py and combat/rules/reaction_trigger_phrases.json.
"""

from pathlib import Path

from combat import typed_reactions
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN

ROOT = Path(__file__).resolve().parents[1]


def _mechanic(key: str, name: str, effects: list, *, trigger: str) -> dict:
    return {"mechanic_id": key, "name": name, "sphere_id": "tianxia.sphere.test", "kind": "talent",
            "activation": {"economy": "reaction", "trigger": trigger}, "effects": effects, "riders": [],
            "range": None, "area": None, "duration": {"kind": "instant"}, "cost": []}


AUTHORITY = {"mechanics": {
    "HIT_REDUCTION_GUARD": _mechanic(
        "HIT_REDUCTION_GUARD", "Hit Reduction Guard",
        [{"type": "damage_modifier", "applies_to": "self", "flat": 6}],
        trigger="A creature hits you with a melee attack"),
    "DROP_GUARD": _mechanic(
        "DROP_GUARD", "Drop Guard",
        [{"type": "damage_modifier", "applies_to": "self", "flat": 20}],
        trigger="You would be reduced to 0 HP"),
    "CONDITION_WARD": _mechanic(
        "CONDITION_WARD", "Condition Ward",
        [{"type": "prevent_condition"}],
        trigger="You would gain the frightened condition"),
    "CRIT_GUARD": _mechanic(
        "CRIT_GUARD", "Crit Guard",
        [{"type": "temp_hp", "flat": 5}],
        trigger="You are struck by a critical hit"),
    "PENALTY_GUARD": _mechanic(
        "PENALTY_GUARD", "Penalty Guard",
        [{"type": "attack_modifier", "flat": 6}],
        trigger="A creature uses a technique that targets you"),
}}
REACTOR = "actor:factory.hooks_reactor"
ALLY = "actor:factory.hooks_ally"


def _sheet(talent_ids: list[str]) -> dict:
    return {
        "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Qi Cultivation"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Qi", "maximum": 20}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
            "speed": {"walking_ft": 30}, "technique_save_dc": 15, "technique_attack_bonus": 7,
        },
        "spheres_and_talents": {"learned_talent_record_ids": talent_ids},
    }


REACTOR_SHEET = _sheet(["HIT_REDUCTION_GUARD", "DROP_GUARD", "CONDITION_WARD", "CRIT_GUARD", "PENALTY_GUARD"])
ALLY_AUTHORITY = {"mechanics": {
    "GUARD_ALLY": _mechanic(
        "GUARD_ALLY", "Guard Ally",
        [{"type": "damage_modifier", "applies_to": "self", "flat": 5}],
        trigger="An ally within 30 feet takes damage"),
}}
ALLY_SHEET = _sheet(["GUARD_ALLY"])


def _engine(*, reactor_talents=None) -> Gate2Engine:
    reactor_bundle = compile_character(REACTOR_SHEET if reactor_talents is None else _sheet(reactor_talents),
                                       actor_id=REACTOR, typed_authority=AUTHORITY)
    ally_bundle = compile_character(ALLY_SHEET, actor_id=ALLY, typed_authority=ALLY_AUTHORITY)
    return Gate2Engine(ROOT, match_seed="REACTION-HOOKS-ENGINE", typed_bundles=(reactor_bundle, ally_bundle),
                       roster_setup={"primary_actor_ids": [REACTOR, ALLY, AN],
                                     "team_by_actor": {REACTOR: "team:a", ALLY: "team:a", AN: "team:b"}})


# ------------------------------------------------------------------ ally-protect reduces damage
def test_an_ally_protect_reaction_reduces_damage_to_an_ally():
    engine = _engine()
    target, ally = engine.state.actors[REACTOR], engine.state.actors[ALLY]
    ally.reaction_available = True
    reduced = typed_reactions.on_damage(engine, target, 10, 0, source_definition_id="action:test.attack", source_actor_id=AN)
    assert reduced == 5  # Guard Ally: flat 5 reduction, spent by the bystander not the target
    assert not ally.reaction_available
    assert target.reaction_available  # the target's own Reaction is untouched
    resolved = [e for e in engine.events if e.source_definition_id == "GUARD_ALLY" and e.event_type == "REACTION_RESOLVED"]
    assert resolved and resolved[-1].actor_id == ALLY and resolved[-1].payload["protects"] == REACTOR


# ------------------------------------------------------------------ drop_to_zero keeps a fighter up
def test_a_drop_to_zero_reaction_keeps_a_fighter_up():
    engine = _engine()
    target = engine.state.actors[REACTOR]
    target.reaction_available = True
    target.current_hp = 10
    reduced = typed_reactions.on_damage(engine, target, 15, 0, source_definition_id="action:test.attack", source_actor_id=AN)
    assert reduced == 0  # Drop Guard's flat-20 reduction erases the pending 15
    assert target.current_hp - reduced > 0  # the fighter stays up
    assert not target.reaction_available


# ------------------------------------------------------------------ technique_targets penalty flips a hit
def test_a_technique_targets_reaction_penalty_turns_a_hit_into_a_miss():
    engine = _engine()
    target, actor = engine.state.actors[REACTOR], engine.state.actors[AN]
    target.reaction_available = True
    typed = {"numbers": {"attack_bonus": 10, "save_dc": 15}}
    typed_reactions.on_technique_start(engine, actor, [target], typed)
    assert typed["numbers"]["attack_bonus"] == 4  # Penalty Guard: -6
    assert not target.reaction_available
    roll = 3
    assert 10 + roll >= 13  # would have hit AC 13 before the reaction
    assert typed["numbers"]["attack_bonus"] + roll < 13  # misses after
    resolved = [e for e in engine.events if e.source_definition_id == "PENALTY_GUARD" and e.event_type == "REACTION_RESOLVED"]
    assert resolved and resolved[-1].payload["attack_penalty"] == 6


# ------------------------------------------------------------------ condition_gained prevents a condition
def test_a_condition_gained_reaction_prevents_a_condition():
    engine = _engine()
    target, actor = engine.state.actors[REACTOR], engine.state.actors[AN]
    target.reaction_available = True
    prevented = typed_reactions.offer_condition_gained(engine, target, actor, "frightened")
    assert prevented is True
    assert not target.reaction_available
    resolved = [e for e in engine.events if e.source_definition_id == "CONDITION_WARD" and e.event_type == "REACTION_RESOLVED"]
    assert resolved and resolved[-1].payload["prevented"] is True


# ------------------------------------------------------------------ critical_hit follows the finalized native result
def test_a_critical_hit_reaction_waits_for_the_final_critical_result():
    # Isolate Crit Guard: a hit damage-reduction reaction may validly spend the
    # same Reaction earlier, even on a natural 20.
    engine = _engine(reactor_talents=["CRIT_GUARD"])
    target, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    target.reaction_available = True
    new_ac, hit = typed_reactions.on_attack_hit(engine, attacker, target, {"range_ft": None}, total=25, natural=20, effective_ac=13)
    assert hit is True and target.temporary_hp == 0 and target.reaction_available
    # Hit declaration precedes critical cancellation. The native resolver
    # publishes this distinct checkpoint only after the critical survives.
    typed_reactions.offer_critical_hit(engine, attacker, target)
    assert target.temporary_hp == 5  # Crit Guard fired once
    assert not target.reaction_available

    engine2 = _engine(reactor_talents=["CRIT_GUARD"])
    target2, attacker2 = engine2.state.actors[REACTOR], engine2.state.actors[AN]
    target2.reaction_available = True
    typed_reactions.on_attack_hit(engine2, attacker2, target2, {"range_ft": None}, total=15, natural=15, effective_ac=13)
    assert target2.temporary_hp == 0  # not a natural 20: Crit Guard never offered


# ------------------------------------------------------------------ a "hit"-kind reduction lands on the next damage
def test_a_hit_kind_reduction_lands_on_the_following_damage():
    engine = _engine()
    target, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    target.reaction_available = True
    engine.state.actors[ALLY].reaction_available = False  # isolate the hit-kind reduction, not Guard Ally
    new_ac, hit = typed_reactions.on_attack_hit(engine, attacker, target, {"range_ft": None}, total=15, natural=15, effective_ac=13)
    assert hit is True  # Hit Reduction Guard cannot turn this hit into a miss, only reduce its damage
    assert not target.reaction_available
    assert target.turn_flags[f"typed_hit_reduction:{AN}"] == 6
    reduced = typed_reactions.on_damage(engine, target, 10, 0, source_definition_id="action:test.attack", source_actor_id=AN)
    assert reduced == 4  # 10 - the parked 6
    assert f"typed_hit_reduction:{AN}" not in target.turn_flags  # consumed, not reused


# ------------------------------------------------------------------ one reaction per round, across kinds
def test_one_reaction_per_round_is_respected_across_kinds():
    engine = _engine()
    target, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    target.reaction_available = True
    typed_reactions.on_attack_hit(engine, attacker, target, {"range_ft": None}, total=15, natural=15, effective_ac=13)
    assert not target.reaction_available  # Hit Reduction Guard spent the round's only Reaction
    prevented = typed_reactions.offer_condition_gained(engine, target, attacker, "frightened")
    assert prevented is False  # Condition Ward never gets a chance this round
    resolved = [e for e in engine.events if e.source_definition_id == "CONDITION_WARD"]
    assert not resolved


# ------------------------------------------------------------------ a malformed row never crashes a fight
def test_a_malformed_drop_to_zero_row_logs_a_rider_instead_of_crashing():
    engine = _engine()
    target = engine.state.actors[REACTOR]
    target.reaction_available = True
    target.current_hp = 5
    engine.state.actors[ALLY].reaction_available = False  # isolate the malformed row, not Guard Ally
    bad_row = {"feature_id": "BAD_DROP", "block": "generic", "name": "Broken Guard", "kind": "drop_to_zero",
              "costs": [], "effects": [{"type": "damage_modifier", "applies_to": "self", "flat": "not-a-number"}]}
    engine.typed_reaction_rows[REACTOR] = [bad_row]
    # Must not raise; the malformed row is skipped (a GM rider records it) and the damage resolves normally.
    reduced = typed_reactions.on_damage(engine, target, 10, 0, source_definition_id="action:test.attack", source_actor_id=AN)
    assert reduced == 10
    assert target.reaction_available  # the broken row never actually fired, so nothing was spent
    riders = [e for e in engine.events if e.event_type == "GM_RIDER" and e.source_definition_id == "BAD_DROP"]
    assert riders and "Broken Guard" in riders[-1].payload["rider"]



def test_you_or_an_ally_rows_answer_the_reactors_own_event():
    """Owner 2026-09-26 review: a "you or an ally takes damage" guard protected only allies."""
    from types import SimpleNamespace

    from combat import typed_reactions

    rows = [{"feature_id": "GUARD", "block": "generic", "kind": "ally_damaged", "includes_self": True},
            {"feature_id": "ONLY_ALLY", "block": "generic", "kind": "ally_damaged", "includes_self": False}]
    engine = SimpleNamespace(typed_reaction_rows={"actor:me": rows})
    assert [row["feature_id"] for row in typed_reactions._generic_rows(engine, "actor:me", "damaged")] == ["GUARD"]
    assert len(typed_reactions._generic_rows(engine, "actor:me", "ally_damaged")) == 2

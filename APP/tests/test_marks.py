"""Mark tracking in combat (owner 2026-09-26): many Sphere talents place a named mark on a creature
("place a Faultline Mark on it", "the target also gains a Faultline Mark") and other talents key off
"a creature bearing your <Mark>" or "spend/consume the <Mark>". Placement recognition lives in
factory_authoring/typed_structure.py (add_marks_from_text/add_spend_mark_from_text/
gate_extra_damage_on_mark); tracking and use live in combat/typed_executor.py (block_mark/
block_spend_mark/block_if_marked, bears_mark), combat/reaction_triggers.py (requires_mark) and
combat/typed_reactions.py (_generic_mark_ok). Built like tests/test_reaction_limits.py and
tests/test_typed_executor.py.
"""

from pathlib import Path

from combat import typed_executor, typed_reactions
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind
from combat.history_feed import format_history_feed
from combat.reaction_triggers import classify_trigger
from factory_authoring.typed_structure import add_marks_from_text, add_spend_mark_from_text

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ placement parsed from text
def test_mark_placement_is_parsed_from_printed_text_and_lands_on_hit():
    effects = [{"type": "attack", "attack_kind": "cultivation_melee", "count": 1, "on_hit": [], "on_miss": []}]
    text = ("Make a melee Cultivation Attack. On a hit, the attack deals its normal damage. "
            "The target also gains a Faultline Mark.")
    result = add_marks_from_text(effects, text)
    marks = [e for e in result[0]["on_hit"] if e.get("type") == "mark"]
    assert len(marks) == 1
    assert marks[0]["mark"] == "Faultline Mark" and marks[0]["applies_to"] == "target"
    assert marks[0]["duration"] == {"kind": "until_removed"} and "gains a Faultline Mark" in marks[0]["evidence"]


def test_mark_placement_lands_top_level_for_a_non_attack_ability_with_its_printed_duration():
    text = "Choose a creature you can see. It gains your Dream Seed, which lasts until the end of your next turn."
    result = add_marks_from_text([], text)
    assert result[0]["type"] == "mark" and result[0]["mark"] == "Dream Seed"
    assert result[0]["duration"] == {"kind": "target_next_turn"}


def test_mark_placement_ignores_a_trigger_menu_and_ordinary_words():
    # "when one of the following happens" introduces a Foundation's whole trigger menu, not one
    # ability's own placement; "Hit Points" is not a mark despite ending in a mark-suffix word.
    menu = "You may place a Faultline Mark when one of the following happens: your Faultline Strike hits."
    assert add_marks_from_text([], menu) == []
    ordinary = "On a hit, the target gains 4 Hit Points."
    assert add_marks_from_text([], ordinary) == []


def test_mark_placement_deduplicates_a_name_repeated_in_flavour_text():
    text = "Plant a Smoke Trace on the target. The Smoke Trace lasts until removed or spent."
    result = add_marks_from_text([], text)
    assert len([e for e in result if e.get("type") == "mark"]) == 1


def test_spend_mark_is_parsed_and_not_double_booked_with_a_placement():
    text = "You may spend a Faultline Mark to reroll a failed save."
    result = add_spend_mark_from_text([], text)
    assert len(result) == 1 and result[0] == {
        "type": "spend_mark", "mark": "Faultline Mark", "applies_to": "target",
        "evidence": "spend a Faultline Mark", "origin": "structure"}
    # A placement and a spend of the identical name printed in the same ability text describes the
    # mark's own limit ("place... a talent explicitly places a Faultline Mark"), not a use of it.
    placing = [{"type": "mark", "mark": "Faultline Mark", "applies_to": "target"}]
    assert add_spend_mark_from_text(placing, text) == placing


# ------------------------------------------------------------------ classifier: requires_mark
def test_classifier_parses_requires_mark_from_a_bearing_your_subject():
    match = classify_trigger("A creature bearing your Beauty Mark makes an attack roll against you.")
    assert match.kind == "attacked" and match.requires_mark == "Beauty Mark"

    match = classify_trigger("A creature bearing one of your Pressure Points hits you with a melee attack.")
    assert match.kind == "hit" and match.requires_mark == "Pressure Point"

    match = classify_trigger("When a marked creature hits with an attack")
    assert match.requires_mark == "*"  # informational even though this kind never becomes runnable

    match = classify_trigger("A creature hits you with a melee attack")
    assert match.requires_mark is None


# ------------------------------------------------------------------ block_mark: applies + feed
def _intent(candidate):
    return ActionIntent(intent_id="test:mark", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
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


def _one_target_run(typed: dict, seed: str):
    engine, actor_id = _engine_with(typed, seed)
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
    target = engine.state.actors[candidate.target_ids[0]]
    engine.execute_intent(_intent(candidate))
    return engine, actor_id, target


def test_block_mark_applies_a_condition_and_the_feed_names_it():
    typed = {"effects": [{"type": "mark", "mark": "Dream Seed", "applies_to": "target", "duration": {"kind": "until_removed"}}],
             "numbers": {"pb": 4}, "duration": {"kind": "instant"}}
    engine, actor_id, target = _one_target_run(typed, "TYPED-MARK-APPLY")
    condition_id = typed_executor.mark_condition_id("Dream Seed", actor_id)
    assert any(c.condition_id == condition_id for c in target.conditions.values())

    applied = [e.model_dump(mode="json") for e in engine.events if e.event_type == "CONDITION_APPLIED"
              and e.payload.get("condition_id") == condition_id]
    feed = format_history_feed(applied, [], pre_state=None, post_state={"actors": {}},
                               actor_names={actor_id: "Lianhui", target.entity_id: "Tang Zhenfeng"}, definition_names={})
    # fix/log1 (merge cac068a1) deliberately calls the named condition a mark;
    # keep the exact owner, printed mark name and affected creature assertion.
    assert any(row["summary"] == "Lianhui placed the Dream Seed mark on Tang Zhenfeng." for row in feed)


def test_re_marking_the_same_creature_refreshes_rather_than_stacks():
    typed = {"effects": [{"type": "mark", "mark": "Dream Seed", "applies_to": "target"}],
             "numbers": {"pb": 4}, "duration": {"kind": "instant"}}
    engine, actor_id, target = _one_target_run(typed, "TYPED-MARK-REFRESH")
    condition_id = typed_executor.mark_condition_id("Dream Seed", actor_id)
    assert sum(1 for c in target.conditions.values() if c.condition_id == condition_id) == 1
    # A second application, called directly (the turn has already moved on from the intent system's
    # point of view): still one instance, not two.
    action = engine.action_catalog["action:typed.test"]
    ctx = typed_executor.Context(engine, engine.state.actors[actor_id], action, None, typed, [target], target)
    typed_executor.block_mark(ctx, typed["effects"][0])
    assert sum(1 for c in target.conditions.values() if c.condition_id == condition_id) == 1


# ------------------------------------------------------------------ spend_mark removes it
def test_spend_mark_removes_it():
    typed = {"effects": [{"type": "spend_mark", "mark": "Faultline Mark", "applies_to": "target"}],
             "numbers": {"pb": 4}, "duration": {"kind": "instant"}}
    engine, actor_id = _engine_with(typed, "TYPED-MARK-SPEND")
    probe = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
    target = engine.state.actors[probe.target_ids[0]]
    condition_id = typed_executor.mark_condition_id("Faultline Mark", actor_id)
    engine._apply_condition(target, condition_id, "test:setup", actor_id, expires_on="UNTIL_REMOVED")
    assert any(c.condition_id == condition_id for c in target.conditions.values())
    # Re-fetch: applying the condition above bumped the state version, so the earlier candidate is stale. Aim at the
    # marked creature itself: the menu's order follows candidate ids, which change with the event sequence.
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id == "action:typed.test" and c.target_ids == (target.entity_id,))
    engine.execute_intent(_intent(candidate))
    assert not any(c.condition_id == condition_id for c in target.conditions.values())


def test_spend_mark_on_a_bad_name_never_crashes_the_fight():
    typed = {"effects": [{"type": "spend_mark", "mark": "Nonexistent Mark", "applies_to": "target"}],
             "numbers": {"pb": 4}, "duration": {"kind": "instant"}}
    engine, actor_id, target = _one_target_run(typed, "TYPED-MARK-SPEND-MISSING")
    assert engine.state.terminal_result is None  # nothing to spend: quietly does nothing


# ------------------------------------------------------------------ if_marked gates an effect
def test_if_marked_effect_applies_only_to_a_marked_target():
    typed = {"effects": [{"type": "if_marked", "mark": "Stellar Mark",
                          "effects": [{"type": "damage", "dice": {"count": 4, "sides": 6}, "damage_types": ["radiant"]}]}],
             "numbers": {"pb": 4}, "duration": {"kind": "instant"}}
    engine, actor_id, target = _one_target_run(typed, "TYPED-IF-MARKED-UNMARKED")
    assert target.current_hp == target.maximum_hp  # not marked: the gated damage never runs

    engine2, actor_id2 = _engine_with(typed, "TYPED-IF-MARKED-MARKED")
    probe2 = next(c for c in engine2.legal_candidates() if c.source_definition_id == "action:typed.test")
    target2 = engine2.state.actors[probe2.target_ids[0]]
    condition_id = typed_executor.mark_condition_id("Stellar Mark", actor_id2)
    engine2._apply_condition(target2, condition_id, "test:setup", actor_id2, expires_on="UNTIL_REMOVED")
    # Re-fetch: applying the condition above bumped the state version, so the earlier candidate is stale. Aim at the
    # marked creature itself: the menu's order follows candidate ids, which change with the event sequence.
    candidate2 = next(c for c in engine2.legal_candidates()
                      if c.source_definition_id == "action:typed.test" and c.target_ids == (target2.entity_id,))
    engine2.execute_intent(_intent(candidate2))
    assert target2.current_hp < target2.maximum_hp  # marked: the gated damage runs


# ------------------------------------------------------------------ reaction hook: requires_mark
def _mechanic(key: str, name: str, effects: list, *, trigger: str) -> dict:
    return {"mechanic_id": key, "name": name, "sphere_id": "tianxia.sphere.test", "kind": "talent",
            "activation": {"economy": "reaction", "trigger": trigger}, "effects": effects, "riders": [],
            "range": None, "area": None, "duration": {"kind": "instant"}, "cost": []}


AUTHORITY = {"mechanics": {
    "MARK_GUARD": _mechanic(
        "MARK_GUARD", "Mark Guard", [{"type": "ac_bonus", "amount": 4}],
        trigger="A creature bearing your Beauty Mark makes an attack roll against you."),
}}
REACTOR = "actor:factory.marks_reactor"
REACTOR_SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Qi Cultivation"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Qi", "maximum": 20}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
        "speed": {"walking_ft": 30}, "technique_save_dc": 15, "technique_attack_bonus": 7,
    },
    "spheres_and_talents": {"learned_talent_record_ids": ["MARK_GUARD"]},
}


def test_compiler_records_requires_mark_on_the_generic_row():
    bundle = compile_character(REACTOR_SHEET, actor_id="actor:factory.marks_compile", typed_authority=AUTHORITY)
    reactions = {row["feature_id"]: row for row in bundle["typed_reactions"] if row.get("block") == "generic"}
    assert reactions["MARK_GUARD"]["kind"] == "attacked" and reactions["MARK_GUARD"]["requires_mark"] == "Beauty Mark"


def _reaction_engine() -> Gate2Engine:
    bundle = compile_character(REACTOR_SHEET, actor_id=REACTOR, typed_authority=AUTHORITY)
    return Gate2Engine(ROOT, match_seed="MARKS-REACTION-ENGINE", typed_bundles=(bundle,),
                       roster_setup={"primary_actor_ids": [REACTOR, AN], "team_by_actor": {REACTOR: "team:a", AN: "team:b"}})


def test_mark_gated_reaction_fires_only_against_a_creature_bearing_the_reactors_mark():
    engine = _reaction_engine()
    reactor, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    reactor.reaction_available = True
    spec = {"attack_bonus": 5, "range_ft": None, "parameters": {}}
    typed_reactions.on_attacked(engine, attacker, reactor, spec, None)
    assert reactor.reaction_available  # AN does not bear the reactor's Beauty Mark: never offered
    assert engine._ac_modifier(reactor) == 0

    condition_id = typed_executor.mark_condition_id("Beauty Mark", REACTOR)
    engine._apply_condition(attacker, condition_id, "test:setup", REACTOR, expires_on="UNTIL_REMOVED")
    typed_reactions.on_attacked(engine, attacker, reactor, spec, None)
    assert not reactor.reaction_available  # now bearing the mark: Mark Guard fires
    assert engine._ac_modifier(reactor) == 4


# ------------------------------------------------------------------ duration expiry
def test_mark_duration_expires_at_the_owners_turn_end_checkpoint_but_until_removed_persists():
    typed = {"effects": [{"type": "mark", "mark": "Dream Seed", "applies_to": "target", "duration": {"kind": "target_next_turn"}}],
             "numbers": {"pb": 4}, "duration": {"kind": "instant"}}
    engine, actor_id, target = _one_target_run(typed, "TYPED-MARK-EXPIRE")
    condition_id = typed_executor.mark_condition_id("Dream Seed", actor_id)
    assert any(c.condition_id == condition_id for c in target.conditions.values())
    # "Until the end of the target's next turn" (owner 2026-09-26): the marker's own turn end no longer removes it.
    engine._expire_for_checkpoint("END_OF_TURN", actor_id)
    assert any(c.condition_id == condition_id for c in target.conditions.values())
    engine._expire_for_checkpoint("END_OF_TURN", target.entity_id)
    assert not any(c.condition_id == condition_id for c in target.conditions.values())

    persistent = {"effects": [{"type": "mark", "mark": "Dream Seed", "applies_to": "target"}],
                 "numbers": {"pb": 4}, "duration": {"kind": "instant"}}
    engine2, actor_id2, target2 = _one_target_run(persistent, "TYPED-MARK-PERSIST")
    condition_id2 = typed_executor.mark_condition_id("Dream Seed", actor_id2)
    engine2._expire_for_checkpoint("END_OF_TURN", actor_id2)
    engine2._expire_for_checkpoint("START_OF_TURN", actor_id2)
    assert any(c.condition_id == condition_id2 for c in target2.conditions.values())  # UNTIL_REMOVED: not turn-based


def test_a_marker_keeps_at_most_its_cap_and_the_oldest_mark_ends():
    """Step 8 (owner 2026-09-26): "You can maintain a number of Rising Marks equal to your Proficiency Bonus"."""
    from combat.gate2_runtime_content import LEE
    from tests.test_factory_combat_compiler import ACTOR, ROOT, SHEET
    from combat.factory_compiler import compile_character
    from combat.gate2_engine import Gate2Engine
    from combat.gate2_runtime_content import AN

    bundle = compile_character(SHEET, actor_id=ACTOR)
    caps = next(row["caps"] for row in bundle["typed_passives"] if row["block"] == "mark_caps")
    assert caps["rising mark"] == 6 and caps["rivalry mark"] == 1  # PB 6 at CL17; "only one Rivalry Mark at a time"
    engine = Gate2Engine(ROOT, match_seed="MARK-CAP", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [ACTOR, AN, LEE], "team_by_actor": {ACTOR: "team:a", AN: "team:b", LEE: "team:b"}})
    me = engine.state.actors[ACTOR]
    action = next(engine.action_catalog[a] for a in me.action_ids if ".weapon." in a)
    for target_id in (AN, LEE):
        target = engine.state.actors[target_id]
        ctx = typed_executor.Context(engine, me, action, None, action.parameters["typed"], [target], target, {})
        typed_executor.block_mark(ctx, {"type": "mark", "mark": "Rivalry Mark", "applies_to": "target"})
    bearers = [a.entity_id for a in engine.state.actors.values() if typed_executor.bears_mark(a, ACTOR, "Rivalry Mark")]
    assert bearers == [LEE]  # the first one ended when the second was placed


# ------------------------------------------------------------------ step 15: the Reaction is kept for the marked creature
HOLD_AUTHORITY = {"mechanics": {
    **AUTHORITY["mechanics"],
    "PLAIN_GUARD": _mechanic("PLAIN_GUARD", "Plain Guard", [{"type": "ac_bonus", "amount": 2}],
                             trigger="A creature you can see makes an attack roll against you."),
}}
HOLD_SHEET = {**REACTOR_SHEET, "spheres_and_talents": {"learned_talent_record_ids": ["MARK_GUARD", "PLAIN_GUARD"]}}


def _hold_engine(plan=None) -> Gate2Engine:
    from combat.gate2_runtime_content import LEE

    bundle = compile_character(HOLD_SHEET, actor_id=REACTOR, typed_authority=HOLD_AUTHORITY, reaction_plan=plan)
    return Gate2Engine(ROOT, match_seed="MARKS-HOLD", typed_bundles=(bundle,),
                       roster_setup={"primary_actor_ids": [REACTOR, AN, LEE], "team_by_actor": {REACTOR: "team:a", AN: "team:b", LEE: "team:b"}})


def _attacked_by(engine: Gate2Engine, attacker_id: str) -> None:
    reactor = engine.state.actors[REACTOR]
    typed_reactions.on_attacked(engine, engine.state.actors[attacker_id], reactor, {"attack_bonus": 5, "range_ft": None, "parameters": {}}, None)


def _mark(engine: Gate2Engine, actor_id: str) -> None:
    condition_id = typed_executor.mark_condition_id("Beauty Mark", REACTOR)
    engine._apply_condition(engine.state.actors[actor_id], condition_id, "test:setup", REACTOR, expires_on="UNTIL_REMOVED")


def test_a_reaction_is_kept_for_the_creature_bearing_the_mark_its_reaction_answers():
    """Owner 2026-09-26: "reactions that come from a specific person or creature ignore attacks from others so the
    reaction is spent on that creature"."""
    from combat.gate2_runtime_content import LEE

    engine = _hold_engine()
    _attacked_by(engine, LEE)  # nobody bears the mark: the plain guard answers anyone
    assert not engine.state.actors[REACTOR].reaction_available and engine._ac_modifier(engine.state.actors[REACTOR]) == 2

    engine = _hold_engine()
    reactor = engine.state.actors[REACTOR]
    _mark(engine, AN)
    _attacked_by(engine, LEE)  # AN bears the mark: LEE's attack is let through
    assert reactor.reaction_available and engine._ac_modifier(reactor) == 0
    assert not typed_reactions.wants_opportunity_attack(engine, reactor, engine.state.actors[LEE])
    assert typed_reactions.wants_opportunity_attack(engine, reactor, engine.state.actors[AN])
    _attacked_by(engine, AN)  # the marked creature gets the Reaction
    assert not reactor.reaction_available and engine._ac_modifier(reactor) == 4


def test_in_my_order_a_reaction_ranked_above_the_marked_one_is_not_held():
    from combat.gate2_runtime_content import LEE

    engine = _hold_engine({"order": ["PLAIN_GUARD", "MARK_GUARD"], "off": []})
    reactor = engine.state.actors[REACTOR]
    _mark(engine, AN)
    _attacked_by(engine, LEE)
    assert not reactor.reaction_available and engine._ac_modifier(reactor) == 2


def test_marked_subject_phrasings_read_as_mark_requirements():
    from combat.reaction_triggers import _requires_mark

    assert _requires_mark("A creature bearing your Dream Seed succeeds on a saving throw against one of your Dreams talents") == "Dream Seed"
    assert _requires_mark("Your Marked Star hits you with an attack, or your Marked Star forces you to make a saving throw.") == "Star Mark"
    # A mark on some other creature nearby is not a requirement on the attacker.
    assert _requires_mark("You are hit by an attack while a creature bearing one of your Choreography Strings is within 30 feet") is None

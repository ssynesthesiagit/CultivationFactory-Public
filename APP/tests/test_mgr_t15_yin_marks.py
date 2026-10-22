"""MGR-T15: Yin's Waning Mark records on a real compiled character.

Each test fails on the parent commit, where none of these clauses existed:

* Marked Allies: a Waning Mark on a willing ally is a preservation mark, and the
  Diminishing Responses that cannot benefit that ally are not offered for it.
* Mark Limit: the mark ends when the marker is on another plane, and a willing
  creature may end it on itself with no Action.
* Quiet Reception: the mark lasts until the end of the marker's next turn, or
  1 minute when the miss had one of the printed causes.
* Preserving Yin: accepted 2 CP preservation (1 HP, no healing, PB less damage
  until the owner's next turn, a Waning Mark, once per Long Rest).
* Spending a Waning Mark: Diminish Aim, Power, Step and Readiness each answer
  their printed trigger, spend the mark, and share the once-a-round flag.
"""

from pathlib import Path

import pytest

from combat import typed_executor
from combat.ext import yin_responses as yin
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN, LEE
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind, Position
from tests.h1_support import bundle

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.h1"
MARKING = "TAL_YIN_MARKING_A_CREATURE"
QUIET = "TAL_YIN_QUIET_RECEPTION"
PRESERVING = "TAL_YIN_PRESERVING_YIN"


def battle(*talents: str, engine_class=Gate2Engine) -> Gate2Engine:
    compiled = bundle([MARKING, *talents], actor_id=ME)
    engine = engine_class(ROOT, match_seed="T15-YIN", typed_bundles=(compiled,),
                         roster_setup={"primary_actor_ids": [ME, LEE, AN],
                                       "team_by_actor": {ME: "team:a", LEE: "team:a", AN: "team:b"}})
    engine.typed_actor_ids = {*engine.typed_actor_ids, LEE, AN}
    for actor_id, x in ((ME, 5), (LEE, 6), (AN, 9)):
        engine.state.actors[actor_id].position = Position(x=x, y=6)
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    return engine


def mark(engine: Gate2Engine, subject, marker: str = ME) -> None:
    action = next(iter(engine.action_catalog.values()))
    ctx = typed_executor.Context(engine, engine.state.actors[marker], action, None,
                                 {"numbers": {}, "effects": []}, [subject], subject, {})
    typed_executor.run_effects(ctx, [{"type": "mark", "mark": "Waning Mark", "applies_to": "target",
                                      "duration": {"kind": "until_end_of_your_next_turn"}}])


def typed_action(engine: Gate2Engine, actor_id: str, effects: list, *, name: str = "T15 action",
                 bonus: int = 5, dc: int = 10) -> ActionDefinition:
    action = ActionDefinition(source_definition_id=f"action:typed.t15.{name.replace(' ', '_')}", display_name=name,
                              owner_id=actor_id, economy=EconomyKind.ACTION, resolution_kind="TYPED",
                              target_kind="HOSTILE_ENTITY", range_ft=60,
                              parameters={"typed": {"effects": effects,
                                                    "numbers": {"pb": 4, "save_dc": dc, "attack_bonus": bonus, "cl": 10},
                                                    "duration": {"kind": "instant"}, "weapon": None, "riders": []}})
    engine.action_catalog[action.source_definition_id] = action
    engine.state.actors[actor_id].action_ids = (*engine.state.actors[actor_id].action_ids, action.source_definition_id)
    return action


def use(engine: Gate2Engine, actor_id: str, action: ActionDefinition, target_id: str) -> None:
    engine.state.current_actor_id = actor_id
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    actor = engine.state.actors[actor_id]
    actor.action_available = True
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id == action.source_definition_id and c.target_ids == (target_id,))
    engine.execute_intent(ActionIntent(intent_id="t15", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=actor_id, target_ids=candidate.target_ids))


ATTACK = [{"type": "attack", "attack_kind": "cultivation_melee", "on_miss": [],
           "on_hit": [{"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 6},
                       "damage_types": ["slashing"]}]}]
SAVE = [{"type": "save", "ability": "dex", "dc": 10, "on_success": [],
         "on_fail": [{"type": "damage", "applies_to": "target", "flat": 1, "damage_types": ["slashing"]}]}]


@pytest.fixture
def accept(monkeypatch):
    """Answer the Diminishing Response menus with a yes (the table's place)."""
    monkeypatch.setattr(yin, "_ask", lambda *args, **kwargs: True)


# ------------------------------------------------------------------------------------------ Marked Allies
def test_marked_allies_tags_an_allies_mark_and_leaves_a_foes_alone():
    engine = battle("TAL_YIN_MARKED_ALLIES", "TAL_YIN_MARK_LIMIT")
    ally, foe = engine.state.actors[LEE], engine.state.actors[AN]
    mark(engine, ally)
    mark(engine, foe)
    assert yin.preserved(ally, ME)
    assert not yin.preserved(foe, ME)
    assert (yin.mark_on(ally, ME).data or {}).get("preserved_team") == "team:a"


def test_marked_allies_refuses_diminish_force_on_a_preservation_mark(accept):
    engine = battle("TAL_YIN_MARKED_ALLIES")
    ally = engine.state.actors[LEE]
    mark(engine, ally)
    assert yin.force_needs_benefit(engine, engine.state.actors[ME], ally, {"feature_id": yin.FORCE}) is False
    # and the same hook is inert for an ordinary hostile mark
    assert yin.force_needs_benefit(engine, engine.state.actors[ME], engine.state.actors[AN],
                                   {"feature_id": yin.FORCE}) is None


def test_preserved_marks_are_never_offered_aim_or_step(accept):
    engine = battle("TAL_YIN_MARKED_ALLIES")
    ally = engine.state.actors[LEE]
    mark(engine, ally)
    ctx = type("Ctx", (), {"engine": engine, "target": engine.state.actors[AN], "actor": ally})()
    assert yin.diminish_aim(ctx, ally) is None
    engine.state.current_actor_id = LEE
    ally.movement_remaining_ft = 30
    yin.diminish_step(engine, ally, None, None, 0)
    assert yin.mark_on(ally, ME) is not None  # neither response spent it


# ------------------------------------------------------------------------------------------ Mark Limit
def test_mark_limit_ends_a_mark_when_the_marker_is_on_another_plane():
    from combat import ext

    engine = battle("TAL_YIN_MARK_LIMIT")
    ally = engine.state.actors[LEE]
    mark(engine, ally)
    engine._apply_condition(ally, yin.PLANE + "ethereal", "test:plane", ME, expires_on="UNTIL_REMOVED")
    ext.run("turn_start", engine, ally)  # the engine's own start-of-turn observer
    assert yin.mark_on(ally, ME) is None


def test_mark_limit_ends_a_mark_mid_turn_when_the_marker_changes_plane():
    # Only the Gate 4 controller dispatches the plug-in "event" hooks the plane change relies on.
    from combat.gate4_engine import Gate4ControllerEngine

    engine = battle("TAL_YIN_MARK_LIMIT", engine_class=Gate4ControllerEngine)
    ally = engine.state.actors[LEE]
    mark(engine, ally)
    # no turn starts here: the plane change itself, mid-turn, must end the mark
    engine._apply_condition(engine.state.actors[ME], yin.PLANE + "ethereal", "test:plane", ME,
                            expires_on="UNTIL_REMOVED")
    assert yin.mark_on(ally, ME) is None


def test_mark_limit_offers_the_willing_creature_a_no_action_removal(monkeypatch):
    from combat import typed_reactions
    import combat.ext.needle as needle

    engine = battle("TAL_YIN_MARK_LIMIT")
    ally = engine.state.actors[LEE]
    mark(engine, ally)
    original, seen = needle.ask, []

    def answer(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs):
        if choice_id == "choice:needle.yin_mark_remove":
            seen.append(kwargs)
            return ["end"]
        return original(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs)

    monkeypatch.setattr(needle, "ask", answer)
    typed_reactions.on_turn_start(engine, ally)
    assert seen and "no Action" in seen[0]["prompt"] and "Waning Mark" in seen[0]["prompt"]
    assert "begin your turn" in seen[0]["prompt"]
    assert yin.mark_on(ally, ME) is None
    assert ally.action_available and ally.bonus_action_available


# ------------------------------------------------------------------------------------------ Quiet Reception
def test_quiet_reception_mark_lasts_a_minute_only_after_a_qualified_miss(accept):
    engine = battle(QUIET)
    foe = engine.state.actors[AN]
    plain = typed_action(engine, AN, ATTACK, name="T15 plain miss", bonus=-100)
    use(engine, AN, plain, LEE)
    first = yin.mark_on(foe, ME)
    assert first is not None and first.expires_on == "END_OF_MARKER_NEXT_TURN"
    engine._remove_condition(foe, first.condition_id, "test:reset")
    engine.state.actors[ME].reaction_available = True

    engine._add_modifier(foe, "test:disadvantage", "attack_mode", "SET", "DISADVANTAGE", "NEXT_ATTACK",
                         expires_on="CONSUMED")
    qualified = typed_action(engine, AN, ATTACK, name="T15 disadvantaged miss", bonus=-100)
    use(engine, AN, qualified, LEE)
    second = yin.mark_on(foe, ME)
    assert second is not None and second.expires_on.startswith("START_OF_SLOT_AT:")  # one minute, ten rounds


# ------------------------------------------------------------------------------------------ Preserving Yin
def _lethal_attack(engine, damage=20) -> ActionDefinition:
    return typed_action(engine, AN, [{"type": "damage", "applies_to": "target", "flat": damage,
                                      "damage_types": ["slashing"]}], name="T15 lethal")


def test_preserving_yin_is_accepted_paid_and_holds_at_one_hit_point():
    engine = battle(PRESERVING, "TAL_YIN_MARKED_ALLIES")
    ally, owner = engine.state.actors[LEE], engine.state.actors[ME]
    ally.current_hp = 5
    cp = owner.resources["resource:core.qi"]
    use(engine, AN, _lethal_attack(engine), LEE)

    assert ally.current_hp == 1 and ally.active
    assert owner.resources["resource:core.qi"] == cp - 2
    assert not owner.reaction_available
    assert yin.mark_on(ally, ME) is not None
    assert any(c.condition_id == yin.WARD for c in ally.conditions.values())
    assert ally.modifiers and all(m.target_field == "healing_reduction" for m in ally.modifiers.values())
    assert any(c.condition_id == yin.RECEIPT and c.data["owner"] == ME for c in ally.conditions.values())
    # persisted fight state is primitive
    assert isinstance((yin.mark_on(ally, ME).data or {}).get("preserved"), int)
    assert yin.preserved(ally, ME)


def test_preserving_yin_ward_reduces_later_damage_and_the_creature_cannot_benefit_again():
    engine = battle(PRESERVING)
    ally, owner = engine.state.actors[LEE], engine.state.actors[ME]
    ally.current_hp = 5
    use(engine, AN, _lethal_attack(engine), LEE)
    assert ally.current_hp == 1

    action = _lethal_attack(engine, damage=4)
    use(engine, AN, action, LEE)
    assert ally.current_hp == 1  # 4 less the owner's Proficiency Bonus (4) is 0 damage

    healing = typed_executor.Context(engine, owner, action, None, {"numbers": {"pb": 4}}, [ally], ally, {})
    ally.current_hp = 1
    typed_executor.block_healing(healing, {"type": "healing", "flat": 10, "applies_to": "target"})
    assert ally.current_hp == 1  # cannot regain Hit Points until the owner's next turn

    # The long-rest receipt blocks a second preservation of the same creature.
    owner.reaction_available = True
    ally.current_hp = 5
    cp = owner.resources["resource:core.qi"]
    use(engine, AN, _lethal_attack(engine), LEE)
    assert ally.current_hp == 0 and not ally.active
    assert owner.resources["resource:core.qi"] == cp


# ------------------------------------------------------------------------------------------ Diminish Aim
def test_diminish_aim_subtracts_a_die_and_shares_the_round(accept):
    engine = battle()
    mark(engine, engine.state.actors[AN])
    attack = typed_action(engine, AN, ATTACK, name="T15 aim")
    use(engine, AN, attack, ME)
    checks = [e for e in engine.events if e.event_type == "CHECK_ROLLED"
              and e.source_definition_id == yin.AIM and e.payload.get("purpose") == "Diminish Aim penalty"]
    assert len(checks) == 1
    assert engine.state.actors[ME].turn_flags[yin.ONCE] == engine.state.round_number
    assert any(e.event_type == "CONDITION_REMOVED" and e.source_definition_id == yin.AIM
               and AN in e.target_ids for e in engine.events)

    # The shared once-a-round flag keeps a second response from spending another mark.
    mark(engine, engine.state.actors[AN])
    second = typed_action(engine, AN, ATTACK, name="T15 aim second")
    use(engine, AN, second, ME)
    assert len([e for e in engine.events if e.event_type == "CHECK_ROLLED"
                and e.source_definition_id == yin.AIM]) == 1


def test_diminish_aim_prompt_names_the_ability_cost_and_creature(monkeypatch):
    engine = battle()
    foe = engine.state.actors[AN]
    mark(engine, foe)
    seen = []
    monkeypatch.setattr(yin, "_ask", lambda engine_, owner, subject, key, choice_id, label, prompt, **kw:
                        (seen.append((label, prompt, choice_id)), True)[1])
    ctx = type("Ctx", (), {"engine": engine, "target": engine.state.actors[ME], "actor": foe,
                            "action": type("Action", (), {"display_name": "Bi Shou (Dagger) attack"})()})()
    assert yin.diminish_aim(ctx, foe) is not None
    label, prompt, choice_id = seen[0]
    assert choice_id == "choice:needle.yin_diminish_aim"
    assert "Diminish Aim" in label and "1d" in label
    assert foe.display_name in prompt and "Waning Mark" in prompt and "no Action" in prompt


# ------------------------------------------------------------------------------------------ Diminish Power
def test_diminish_power_adds_a_die_to_the_chosen_save(accept):
    engine = battle()
    mark(engine, engine.state.actors[AN])
    action = typed_action(engine, AN, SAVE, name="T15 power")
    use(engine, AN, action, ME)
    checks = [e for e in engine.events if e.event_type == "CHECK_ROLLED"
              and e.source_definition_id == yin.POWER and e.payload.get("purpose") == "Diminish Power bonus"]
    assert len(checks) == 1
    assert yin.mark_on(engine.state.actors[AN], ME) is None


# ------------------------------------------------------------------------------------------ Diminish Step
def test_diminish_step_slows_the_marked_mover_until_the_turn_ends(accept):
    engine = battle()
    foe = engine.state.actors[AN]
    mark(engine, foe)
    engine.state.current_actor_id = AN
    engine.state.current_slot_index = engine.state.initiative_order.index(AN)
    foe.movement_remaining_ft = 30
    candidates = [c for c in engine.legal_candidates() if c.display_name.startswith("Move to")]
    step = next(c for c in candidates if c.destination
                and max(abs(c.destination.x - foe.position.x), abs(c.destination.y - foe.position.y)) == 1)
    engine.execute_intent(ActionIntent(intent_id="t15-move", decision_id=step.decision_id,
                                       candidate_id=step.candidate_id, state_version=step.state_version,
                                       actor_id=AN, target_ids=step.target_ids, destination=step.destination))
    assert yin.mark_on(foe, ME) is None
    assert foe.movement_remaining_ft == 15  # 30 - 5 moved - 10 printed reduction
    assert [(m.target_field, m.value) for m in foe.modifiers.values() if m.target_field == "speed_ft"] == [("speed_ft", -10)]
    assert all(m.expires_on.startswith("END_OF_TURN_AT:") for m in foe.modifiers.values() if m.target_field == "speed_ft")


# ------------------------------------------------------------------------------------------ Diminish Readiness
def test_diminish_readiness_takes_reactions_until_the_next_turn(accept):
    engine = battle()
    foe = engine.state.actors[AN]
    mark(engine, foe)
    engine.typed_reaction_rows.setdefault(AN, []).append({
        "block": "generic", "kind": "attacked", "feature_id": "test:t15_counter", "name": "T15 Counter", "ask": True,
        "costs": [], "numbers": {"pb": 4, "cl": 10, "key_mod": 2, "attack_bonus": 5, "save_dc": 10},
        "effects": [{"type": "condition", "applies_to": "self", "condition": "prone",
                     "duration": {"kind": "instant"}, "evidence": "test"}]})
    attack = typed_action(engine, ME, ATTACK, name="T15 player hit", bonus=100)
    use(engine, ME, attack, AN)
    assert any(e.source_definition_id == "test:t15_counter" for e in engine.events if e.event_type == "REACTION_RESOLVED")
    assert yin.mark_on(foe, ME) is None
    denied = [c for c in foe.conditions.values() if c.condition_id == yin.DENIED]
    assert len(denied) == 1 and denied[0].expires_on == "START_OF_TARGET_NEXT_TURN"

# ------------------------------------------------------------------------------------------ Review fixes
def quiet_mark(engine: Gate2Engine, subject, marker: str = ME) -> None:
    """Place the Waning Mark as Quiet Reception's own rider, so mark_duration sees QUIET."""
    ctx = typed_executor.Context(engine, engine.state.actors[marker], next(iter(engine.action_catalog.values())),
                                 None, {"numbers": {}, "effects": []}, [subject], subject, {},
                                 effect_source=yin.QUIET)
    typed_executor.run_effects(ctx, [{"type": "mark", "mark": "Waning Mark", "applies_to": "target",
                                      "duration": {"kind": "until_end_of_your_next_turn"}}])


def test_a_spent_aim_receipt_does_not_qualify_a_later_uncaused_miss(accept):
    """Finding 1: the Diminish Aim receipt belongs to the one roll it was spent on.
    On the original code the later miss matched the old receipt and lasted a minute."""
    engine = battle(QUIET)
    foe = engine.state.actors[AN]
    mark(engine, foe)
    aimed = typed_action(engine, AN, ATTACK, name="T15 aimed hit", bonus=100)
    use(engine, AN, aimed, LEE)
    assert yin.mark_on(foe, ME) is None  # Diminish Aim spent the mark on that roll
    engine._append_event("ATTACK_ROLLED", "test:later_uncaused_miss", actor_id=AN,
                         target_ids=(LEE,), payload={"mode": "NORMAL", "cover_bonus": 0})
    quiet_mark(engine, foe)
    landed = yin.mark_on(foe, ME)
    assert landed is not None and landed.expires_on == "END_OF_MARKER_NEXT_TURN"


def _advantaged_foe(engine):
    foe = engine.state.actors[AN]
    mark(engine, foe)
    engine._add_modifier(foe, "test:advantage", "attack_mode", "SET", "ADVANTAGE", "NEXT_ATTACK",
                         expires_on="CONSUMED")
    return foe


def test_a_read_only_label_query_does_not_consume_the_readiness_cancel(accept):
    """Finding 2a: targeting labels call presentation_modes, which must not spend the cancel."""
    from combat import attack_modes

    engine = battle()
    foe = _advantaged_foe(engine)
    yin.readiness_advantage(engine, foe, engine.state.actors[ME], None, {"source_id": "test:first"})
    assert "ADVANTAGE" not in attack_modes.presentation_modes(engine, foe, engine.state.actors[ME])
    assert attack_modes.removed(engine, foe, engine.state.actors[ME], False) == frozenset({"ADVANTAGE"})


def test_a_later_attack_roll_ends_the_readiness_cancel(accept):
    """Finding 2b: a cancel spent on an earlier attack must not strip a later attack's Advantage.
    The later roll is recorded with no removal query first, as a plain attack would be."""
    from combat import attack_modes

    engine = battle()
    foe = _advantaged_foe(engine)
    yin.readiness_advantage(engine, foe, engine.state.actors[ME], None, {"source_id": "test:first"})
    engine._append_event("ATTACK_ROLLED", "test:later_attack", actor_id=AN,
                         target_ids=(ME,), payload={"mode": "ADVANTAGE"})
    assert attack_modes.removed(engine, foe, engine.state.actors[ME], False) == frozenset()


def test_a_miss_before_the_roll_ends_the_readiness_cancel(accept):
    """Review 013338: an attack spent on Readiness that never rolls (a miss before the d20) must not leave
    a record that a later preview or attack reads as its own Advantage cancellation."""
    from types import SimpleNamespace
    from combat import attack_modes

    engine = battle()
    foe = _advantaged_foe(engine)
    yin.readiness_advantage(engine, foe, engine.state.actors[ME], None, {"source_id": "test:missed"})
    yin.readiness_attack_done(SimpleNamespace(engine=engine), foe, False, {})
    assert attack_modes.removed(engine, foe, engine.state.actors[ME], False) == frozenset()

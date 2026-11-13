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
def test_an_allies_mark_is_preservation_only_after_the_ally_accepts(monkeypatch):
    """The printed willing ally answers for itself; team membership is not consent."""
    import combat.ext.willing_targets as willing

    engine = battle("TAL_YIN_MARKED_ALLIES")
    ally = engine.state.actors[LEE]
    monkeypatch.setattr(willing, "asks_consent", lambda *args, **kwargs: False)
    mark(engine, ally)
    assert not yin.preserved(ally, ME)
    monkeypatch.setattr(willing, "asks_consent", lambda *args, **kwargs: True)
    mark(engine, ally)
    assert yin.preserved(ally, ME)


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


def _free_removal_candidates(engine, actor_id):
    engine.state.current_actor_id = actor_id
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    return [c for c in engine.legal_candidates() if c.source_definition_id == yin.REMOVE]


def test_a_willing_creature_ends_the_mark_with_a_free_button_at_any_time_in_its_turn():
    """The printed clause is "at any time, no Action required": the button must survive
    both paid slots already being spent (the old code only asked once, at turn start)."""
    engine = battle("TAL_YIN_MARKED_ALLIES")
    ally = engine.state.actors[LEE]
    mark(engine, ally)
    ally.action_available = False
    ally.bonus_action_available = False
    candidates = _free_removal_candidates(engine, LEE)
    assert len(candidates) == 1
    button = candidates[0]
    assert "Waning Mark" in button.display_name
    engine.execute_intent(ActionIntent(intent_id="t15-remove", decision_id=button.decision_id,
                                       candidate_id=button.candidate_id, state_version=button.state_version,
                                       actor_id=LEE, target_ids=button.target_ids))
    assert yin.mark_on(ally, ME) is None
    assert not ally.action_available and not ally.bonus_action_available


def test_the_free_removal_button_is_only_offered_for_a_willing_mark():
    engine = battle("TAL_YIN_MARKED_ALLIES")
    assert _free_removal_candidates(engine, LEE) == []  # no mark
    mark(engine, engine.state.actors[AN])               # an enemy's harmful mark is not the willing clause
    assert _free_removal_candidates(engine, AN) == []
    mark(engine, engine.state.actors[LEE])
    assert len(_free_removal_candidates(engine, LEE)) == 1


# ------------------------------------------------------------------------------------------ Quiet Reception
def test_quiet_reception_mark_lasts_a_minute_only_after_a_qualified_miss(accept):
    engine = battle(QUIET)
    foe = engine.state.actors[AN]
    # The mark itself is placed as Quiet Reception's own rider: the compiled generic
    # reaction reads its printed text, and the public export scrambles prose, so its
    # presence is not this clause's subject (the real attack receipts below are).
    plain = typed_action(engine, AN, ATTACK, name="T15 plain miss", bonus=-100)
    use(engine, AN, plain, LEE)
    quiet_mark(engine, foe)
    first = yin.mark_on(foe, ME)
    assert first is not None and first.expires_on == "END_OF_MARKER_NEXT_TURN"
    engine._remove_condition(foe, first.condition_id, "test:reset")
    engine.state.actors[ME].reaction_available = True

    engine._add_modifier(foe, "test:disadvantage", "attack_mode", "SET", "DISADVANTAGE", "NEXT_ATTACK",
                         expires_on="CONSUMED")
    qualified = typed_action(engine, AN, ATTACK, name="T15 disadvantaged miss", bonus=-100)
    use(engine, AN, qualified, LEE)
    quiet_mark(engine, foe)
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
    # A hit would also let the marker answer with Receive Overextension, which
    # places a fresh mark: spend that Reaction so the spent mark stays spent.
    engine.state.actors[ME].reaction_available = False
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


def test_a_read_only_label_query_never_spends_the_readiness_mark(accept):
    """A targeting label reads the mode set without drawing a d20, so the mark is not spent."""
    from combat import attack_modes

    engine = battle()
    foe = _advantaged_foe(engine)
    assert "ADVANTAGE" in attack_modes.presentation_modes(engine, foe, engine.state.actors[ME])
    assert yin.mark_on(foe, ME) is not None
    assert yin.readiness_cancels_advantage(engine, {"mode": "NORMAL", "actor_id": AN, "reason": "ATTACK:test"}, None) is None
    assert yin.mark_on(foe, ME) is not None


def test_a_normal_roll_is_never_turned_into_a_mode(accept):
    """Readiness cancels an Advantage; it never invents Disadvantage on a plain roll."""
    engine = battle()
    foe = _advantaged_foe(engine)
    assert yin.readiness_cancels_advantage(engine, {"mode": "NORMAL", "actor_id": AN, "reason": "CHECK:test"}, None) is None
    assert yin.readiness_cancels_advantage(engine, {"mode": "DISADVANTAGE", "actor_id": AN, "reason": "SAVE:x:DEX"}, None) is None
    assert yin.mark_on(foe, ME) is not None


def test_diminish_readiness_cancels_advantage_on_a_save_and_a_check(accept):
    """The printed trigger is any roll, so native saves and ability checks answer too."""
    engine = battle()
    mark(engine, engine.state.actors[AN])
    roll = engine._roll_save(engine.state.actors[AN], "DEX", 10, "test:save", extra_mode="ADVANTAGE")
    assert roll.mode == "NORMAL"
    assert yin.mark_on(engine.state.actors[AN], ME) is None

    mark(engine, engine.state.actors[AN])
    engine.state.actors[ME].turn_flags.pop(yin.ONCE, None)
    check = engine.roll_check(modifier=0, actor_id=AN, reason="CHECK:test", ability="WIS", skill="Perception",
                              modes=("ADVANTAGE",))
    assert check.mode == "NORMAL"
    assert yin.mark_on(engine.state.actors[AN], ME) is None


# ------------------------------------------------------------------------------------------ Review F9 fixes
def _blink(engine, actor_id, feet: int = 30):
    """A self-teleport Action, the printed trigger Diminish Step's second alternative answers."""
    action = ActionDefinition(source_definition_id="action:typed.t15.blink", display_name="T15 blink",
                              owner_id=actor_id, economy=EconomyKind.ACTION, resolution_kind="TYPED",
                              target_kind="SELF", range_ft=feet,
                              parameters={"typed": {"effects": [{"type": "teleport", "applies_to": "self",
                                                                 "distance_ft": feet}],
                                                   "numbers": {}, "duration": {"kind": "instant"},
                                                   "weapon": None, "riders": []}})
    engine.action_catalog[action.source_definition_id] = action
    engine.state.actors[actor_id].action_ids = (*engine.state.actors[actor_id].action_ids,
                                                action.source_definition_id)
    return action


def _answer_destination(monkeypatch, cell):
    """Accept Diminish Step, then land where the table clicked."""
    import combat.ext.needle as needle

    original = needle.ask

    def answer(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs):
        if choice_id == "choice:needle.yin_diminish_step":
            return ["use"]
        if choice_id == "choice:needle.teleport_destination":
            wanted = needle.cell_id(cell)
            return [wanted] if wanted in options else []
        return original(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs)

    monkeypatch.setattr(needle, "ask", answer)


def _use_blink(engine, action):
    foe = engine.state.actors[AN]
    engine.state.current_actor_id = AN
    engine.state.current_slot_index = engine.state.initiative_order.index(AN)
    foe.action_available = True
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id == action.source_definition_id)
    engine.execute_intent(ActionIntent(intent_id="t15-blink", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=AN,
                                       target_ids=candidate.target_ids))


def test_diminish_step_shortens_a_marked_creature_teleport(monkeypatch):
    """Printed Step: "reduce the distance of one teleportation effect by 10 feet".
    The 25-foot landing is legal at the printed 30-foot reach, so it fails only
    because the response shortened the teleport to 20 feet."""
    engine = battle()
    foe = engine.state.actors[AN]
    mark(engine, foe)
    engine.typed_control_modes = {AN: "MANUAL"}
    action = _blink(engine, AN)
    _answer_destination(monkeypatch, Position(x=4, y=6))  # 25 ft away: beyond 30 - 10
    _use_blink(engine, action)
    assert foe.position == Position(x=9, y=6)
    assert any("beyond the remaining" in str((e.payload or {}).get("rider") or "") for e in engine.events)
    assert yin.mark_on(foe, ME) is None  # the mark paid for the response
    assert engine.state.actors[ME].turn_flags[yin.ONCE] == engine.state.round_number


def test_diminish_step_still_lands_a_teleport_within_the_shortened_distance(monkeypatch):
    engine = battle()
    foe = engine.state.actors[AN]
    mark(engine, foe)
    engine.typed_control_modes = {AN: "MANUAL"}
    action = _blink(engine, AN)
    _answer_destination(monkeypatch, Position(x=7, y=6))  # 10 ft away, inside 20
    _use_blink(engine, action)
    assert foe.position == Position(x=7, y=6)
    assert any(e.event_type == "MOVEMENT_COMMITTED" and (e.payload or {}).get("teleport")
               for e in engine.events)
    assert yin.mark_on(foe, ME) is None


def test_diminish_readiness_cancels_advantage_on_a_typed_attack(monkeypatch):
    """The printed Readiness clause "the triggering Advantage is canceled for that roll"
    must also cover a typed strike's locked-in Advantage."""
    import combat.ext.needle as needle

    engine = battle()
    _advantaged_foe(engine)
    engine.state.actors[ME].reaction_available = False  # no Receive Overextension re-mark
    original, seen = needle.ask, []

    def answer(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs):
        seen.append(choice_id)
        if choice_id == "choice:needle.yin_diminish_aim":
            return []  # the mark is saved for Readiness
        if choice_id == "choice:needle.yin_diminish_readiness":
            return ["use"]
        return original(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs)

    monkeypatch.setattr(needle, "ask", answer)
    attack = typed_action(engine, AN, ATTACK, name="T15 readiness typed")
    use(engine, AN, attack, ME)
    rolled = [e for e in engine.events if e.event_type == "ATTACK_ROLLED"
              and e.source_definition_id == attack.source_definition_id]
    assert len(rolled) == 1
    assert rolled[0].payload["mode"] == "NORMAL"
    assert not any("waning" in c.condition_id for c in engine.state.actors[AN].conditions.values())
    assert "choice:needle.yin_diminish_readiness" in seen
    assert engine.state.actors[ME].turn_flags[yin.ONCE] == engine.state.round_number


def test_diminish_readiness_cancels_an_actions_own_chosen_advantage(monkeypatch):
    """A typed action that accepts its own Advantage records it only in the choice
    journal, not as a condition: the printed cancel must still reach that roll."""
    import combat.ext.needle as needle

    engine = battle()
    foe = engine.state.actors[AN]
    mark(engine, foe)
    engine.state.actors[ME].reaction_available = False  # no Receive Overextension re-mark
    action = ActionDefinition(source_definition_id="action:typed.t15.chosen", display_name="T15 chosen",
                              owner_id=AN, economy=EconomyKind.ACTION, resolution_kind="TYPED",
                              target_kind="HOSTILE_ENTITY", range_ft=60,
                              parameters={"chosen_attack_modes": ["ADVANTAGE"],
                                          "typed": {"effects": ATTACK,
                                                    "numbers": {"pb": 4, "save_dc": 10, "attack_bonus": 5, "cl": 10},
                                                    "duration": {"kind": "instant"}, "weapon": None, "riders": []}})
    engine.action_catalog[action.source_definition_id] = action
    foe.action_ids = (*foe.action_ids, action.source_definition_id)
    original = needle.ask

    def answer(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs):
        if choice_id == "choice:needle.yin_diminish_readiness":
            return ["use"]
        return original(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs)

    monkeypatch.setattr(needle, "ask", answer)
    use(engine, AN, action, ME)
    rolled = [e for e in engine.events if e.event_type == "ATTACK_ROLLED"
              and e.source_definition_id == action.source_definition_id]
    assert len(rolled) == 1
    assert rolled[0].payload["mode"] == "NORMAL"
    assert rolled[0].payload.get("chosen_attack_modes") == ["ADVANTAGE"]


# ------------------------------------------------------------------------------------------ table path
# Commit + cold reload for each finding: the real CombatService/TabletopService transaction,
# then a fresh service reads the saved fight from disk. Synthetic characters only (public CI).
import copy
import json
import zipfile

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet as character_sheet

T_OWNER = "actor:factory.t15-yin-owner"
T_ALLY = "actor:factory.t15-yin-ally"
T_FOE = "actor:factory.t15-yin-foe"
NAMES = {T_OWNER: "Yin Keeper", T_ALLY: "Guarding Friend", T_FOE: "Visiting Fighter"}
MARK_EFFECT = [{"type": "mark", "mark": "Waning Mark", "applies_to": "target",
                "duration": {"kind": "until_end_of_your_next_turn"}}]
LETHAL = [{"type": "damage", "applies_to": "target", "flat": 20, "damage_types": ["slashing"]}]


def _seal(bundle) -> None:
    bundle.pop("bundle_sha256", None)
    bundle["bundle_sha256"] = canonical_sha256(bundle)


def _add_action(bundle, actor_id: str, source_id: str, name: str, effects: list,
                *, target_kind: str = "HOSTILE_ENTITY") -> None:
    action = copy.deepcopy(next(a for a in bundle["action_catalog"] if a["resolution_kind"] == "TYPED"))
    action.update(source_definition_id=source_id, display_name=name, owner_id=actor_id, economy="NONE",
                  target_kind=target_kind, range_ft=60, costs=[])
    action["parameters"] = {"free_primary": True,
                            "typed": {"effects": effects,
                                      "numbers": {"cl": 10, "pb": 4, "key_mod": 2, "save_dc": 10, "attack_bonus": 5},
                                      "duration": {"kind": "instant"}, "weapon": None, "riders": []}}
    bundle["action_catalog"].append(action)
    bundle["actor_template"]["action_ids"].append(source_id)


def table_fight(tmp_path, owner_talents, *, ally_talents=(), foe_talents=(), owner_actions=(), ally_actions=(),
                foe_actions=(), hp=None, armor=None, bundle_edit=None, seed="T15-YIN-TABLE"):
    """A real match from synthetic characters; every setup the tests need is a compiled action."""
    bundles = []
    for actor_id, talents, actions in ((T_OWNER, owner_talents, owner_actions),
                                       (T_ALLY, ally_talents, ally_actions),
                                       (T_FOE, foe_talents, foe_actions)):
        document = character_sheet(list(talents), cl=10, dc=10, primary="Qi")
        document["identity"]["display_name"] = NAMES[actor_id]
        document["ability_scores_and_statistics"]["hit_points"]["maximum"] = (hp or {}).get(actor_id, 60)
        if armor and actor_id in armor:
            document["ability_scores_and_statistics"]["armor_class"]["base_value"] = armor[actor_id]
        bundle = compile_character(document, actor_id=actor_id, reaction_plan={"ask": True})
        for source_id, name, effects, target_kind in actions:
            _add_action(bundle, actor_id, source_id, name, effects, target_kind=target_kind)
        if bundle_edit is not None:
            bundle_edit(bundle, actor_id)
        _seal(bundle)
        bundles.append(bundle)
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed=seed, maximum_rounds=20, typed_bundles=tuple(bundles),
        roster_setup={"primary_actor_ids": [T_OWNER, T_ALLY, T_FOE],
                      "team_by_actor": {T_OWNER: "team:a", T_ALLY: "team:a", T_FOE: "team:b"},
                      "starting_positions": {T_OWNER: {"x": 3, "y": 6}, T_ALLY: {"x": 3, "y": 5},
                                             T_FOE: {"x": 4, "y": 5}}})
    return service, TabletopService(service, tmp_path), session.match_id


def cold(service, tmp_path, match_id):
    loaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
    return loaded.engine


def _menu(table, match_id):
    return table.state(match_id)["menu"]


def _answer(prompt, accept: bool):
    choice = prompt.get("choice") or {}
    options = [option["id"] for option in choice.get("options", [])]
    count = max(1, int(choice.get("minimum", 1)))
    return {**(prompt.get("context") or {}), "selection": "USE" if accept else "DECLINE",
            "option_ids": options[:count] if accept else []}


def _commit(table, match_id, candidate_id, decide):
    """One committed action, answering every table question the way ``decide(prompt)`` says."""
    answers, prompts = [], []
    for _ in range(40):
        state = table.state(match_id)
        menu = state["menu"]
        result = table.act(match_id, candidate_id, menu["decision_id"], menu["state_version"],
                           state["last_sequence"], list(answers))
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return result, prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        answers.append(decide(prompt))
    raise AssertionError("the table never committed that action")


def _candidate(table, match_id, label, target=None):
    menu = _menu(table, match_id)
    group = next(g for g in menu["actions"] if label in g["label"])
    option = next(o for o in group["options"] if target is None or target in (o.get("target_ids") or ()))
    return option["candidate_id"]


def _end_turn(table, match_id, decide):
    return _commit(table, match_id, _menu(table, match_id)["end_turn"], decide)


def _turn(table, match_id, actor_id, decide):
    for _ in range(8):
        if _menu(table, match_id)["actor_id"] == actor_id:
            return
        _end_turn(table, match_id, decide)
    raise AssertionError(f"{actor_id} never received a turn")


def _kind(prompt) -> str:
    return str((prompt.get("context") or {}).get("reaction_source_id") or "")


def _decline(prompt):
    return _answer(prompt, False)


def _accept(prompt):
    return _answer(prompt, True)


def test_preserving_yin_can_keep_the_owner_itself_at_one_hit_point_at_the_table(tmp_path):
    """Finding 1: "a willing creature within 30 feet" includes the owner."""
    service, table, mid = table_fight(tmp_path, [PRESERVING], hp={T_OWNER: 5},
                                      foe_actions=[("action:test.t15.lethal", "Lethal", LETHAL, "HOSTILE_ENTITY")])
    _turn(table, mid, T_FOE, _decline)
    result, prompts = _commit(table, mid, _candidate(table, mid, "Lethal", T_OWNER), _accept)
    assert [p for p in prompts if "preserving_yin" in _kind(p)], prompts
    assert not [p for p in prompts if "willing.consent" in _kind(p)], "the owner is not asked for consent"
    engine = cold(service, tmp_path, mid)
    owner = engine.state.actors[T_OWNER]
    assert owner.current_hp == 1 and owner.active
    assert owner.resources["resource:core.qi"] == 28
    assert not owner.reaction_available
    assert yin.mark_on(owner, T_OWNER) is not None
    assert any(c.condition_id == yin.WARD for c in owner.conditions.values())
    assert any(c.condition_id == yin.RECEIPT for c in owner.conditions.values())


def test_a_same_team_recipient_is_asked_and_its_refusal_is_honoured_at_the_table(tmp_path):
    """Finding 2: team membership is not consent; the allied player answers the question."""
    service, table, mid = table_fight(tmp_path, [PRESERVING], hp={T_ALLY: 5},
                                      foe_actions=[("action:test.t15.lethal", "Lethal", LETHAL, "HOSTILE_ENTITY")])
    _turn(table, mid, T_FOE, _decline)
    result, prompts = _commit(table, mid, _candidate(table, mid, "Lethal", T_ALLY), _decline)
    assert [p for p in prompts if "willing.consent" in _kind(p)], prompts
    engine = cold(service, tmp_path, mid)
    ally, owner = engine.state.actors[T_ALLY], engine.state.actors[T_OWNER]
    assert ally.current_hp == 0 and not ally.active
    assert owner.resources["resource:core.qi"] == 30
    assert owner.reaction_available
    assert yin.mark_on(ally, T_OWNER) is None
    assert not any(c.condition_id in (yin.WARD, yin.RECEIPT) for c in ally.conditions.values())


def test_a_willing_creature_ends_the_mark_off_its_own_turn_at_the_table(tmp_path):
    """Finding 3: "at any time, no Action required" also covers somebody else's turn."""
    service, table, mid = table_fight(
        tmp_path, [yin.MARKED_ALLIES, MARKING], hp={T_ALLY: 60},
        owner_actions=[("action:test.t15.mark_ally", "Yin Mark Ally", MARK_EFFECT, "ANY_CREATURE")])
    _turn(table, mid, T_OWNER, _decline)
    _commit(table, mid, _candidate(table, mid, "Yin Mark Ally", T_ALLY), _accept)
    assert yin.mark_on(cold(service, tmp_path, mid).state.actors[T_ALLY], T_OWNER) is not None

    _turn(table, mid, T_ALLY, _decline)
    result, prompts = _end_turn(table, mid, _accept)
    asked = [p for p in prompts if "yin_mark_remove" in _kind(p)]
    assert asked, prompts
    assert (asked[0].get("context") or {}).get("reactor_id") == T_ALLY
    engine = cold(service, tmp_path, mid)
    assert yin.mark_on(engine.state.actors[T_ALLY], T_OWNER) is None
    assert any("ends" in str((e.payload or {}).get("log") or "") and "Waning Mark" in str((e.payload or {}).get("log") or "")
               for e in engine.events)


def _readiness_test(tmp_path, action_effect, label, read_mode):
    service, table, mid = table_fight(
        tmp_path, [MARKING, "TAL_YIN_SPENDING_A_WANING_MARK"],
        owner_actions=[("action:test.t15.mark_foe", "Yin Mark", MARK_EFFECT, "HOSTILE_ENTITY"),
                       ("action:test.t15.readiness", label, action_effect, "HOSTILE_ENTITY")])
    _turn(table, mid, T_OWNER, _decline)
    _commit(table, mid, _candidate(table, mid, "Yin Mark", T_FOE), _accept)
    _, prompts = _commit(table, mid, _candidate(table, mid, label, T_FOE),
                         lambda prompt: _answer(prompt, "yin_diminish_readiness" in _kind(prompt)))
    assert [p for p in prompts if "yin_diminish_readiness" in _kind(p)], prompts
    engine = cold(service, tmp_path, mid)
    return engine, read_mode


def test_diminish_readiness_cancels_advantage_on_a_save_at_the_table(tmp_path):
    """Finding 4: a saving throw's Advantage is covered by the printed "any roll" trigger."""
    save = [{"type": "save", "ability": "dex", "dc": 10, "advantage_if_larger": -1,
             "on_fail": [], "on_success": []}]
    engine, _ = _readiness_test(tmp_path, save, "Test Save", "save")
    rolled = [e for e in engine.events if e.event_type == "SAVE_ROLLED"]
    assert rolled and rolled[-1].payload["mode"] == "NORMAL", [e.payload for e in rolled]
    assert any(e.event_type == "CONDITION_REMOVED" and e.source_definition_id == yin.READINESS
               for e in engine.events)


def test_diminish_readiness_cancels_advantage_on_an_ability_check_at_the_table(tmp_path):
    """Finding 4: an ability check's Advantage is covered too, through the same seam."""
    contest = [{"type": "contest_against", "harmful": True,
                "actor_check": {"kind": "check", "ability": "DEX", "skill": "Sleight of Hand"},
                "target_check": {"kind": "check", "ability": "STR", "skill": "Athletics", "mode": "ADVANTAGE"},
                "on_success": [], "on_fail": []}]
    engine, _ = _readiness_test(tmp_path, contest, "Test Contest", "check")
    event = next(e for e in engine.events if (e.payload or {}).get("roll_kind") == "opposed_check")
    assert event.payload["target"]["mode"] == "NORMAL", event.payload
    assert any(e.event_type == "CONDITION_REMOVED" and e.source_definition_id == yin.READINESS
               for e in engine.events)


def _quiet_reaction(bundle, actor_id):
    """The reaction's own mark effect, standing in for the text-compiled row on public CI.

    Same feature id, trigger and effect: the mark's lifetime is read by mark_duration
    from this row's source, exactly as the compiled Quiet Reception row is.
    """
    if actor_id != T_OWNER:
        return
    rows = [row for row in bundle.get("typed_reactions") or [] if row.get("feature_id") == QUIET]
    row = rows[0] if rows else {"feature_id": QUIET, "block": "generic", "name": "Quiet Reception",
                                "range_ft": 60, "min_move_ft": 0, "includes_self": True, "mark_on": "source",
                                "costs": [], "rolls": [], "conditions": [], "damage_types": [],
                                "numbers": {"pb": 4, "save_dc": 10, "attack_bonus": 5, "key_mod": 2, "cl": 10}}
    row.update({"kind": "ally_missed", "ask": True, "requires_sight": False,
                "effects": [{"type": "mark", "mark": "Waning Mark", "applies_to": "target",
                             "duration": {"kind": "until_end_of_your_next_turn"}}]})
    if not rows:
        bundle.setdefault("typed_reactions", []).append(row)


def _quiet_mark_test(tmp_path, owner_talents, ally_talents, *, by_owner: bool):
    owner_mark = ("action:test.t15.owner_mark_foe", "Yin Mark", MARK_EFFECT, "HOSTILE_ENTITY")
    ally_mark = ("action:test.t15.ally_mark_foe", "Yin Mark", MARK_EFFECT, "HOSTILE_ENTITY")
    service, table, mid = table_fight(
        tmp_path, owner_talents, ally_talents=ally_talents,
        owner_actions=[owner_mark], ally_actions=[ally_mark] if ally_talents else [],
        armor={T_OWNER: 40, T_ALLY: 40}, bundle_edit=_quiet_reaction)
    marker = T_OWNER if by_owner else T_ALLY
    _turn(table, mid, marker, _decline)
    _commit(table, mid, _candidate(table, mid, "Yin Mark", T_FOE), _accept)
    _turn(table, mid, T_FOE, _decline)
    _, prompts = _commit(table, mid, _candidate(table, mid, "Unarmed Strike", T_OWNER),
                         lambda prompt: _answer(prompt, "yin_diminish_aim" in _kind(prompt)
                                                or "TAL_YIN_QUIET_RECEPTION" in _kind(prompt)))
    assert [p for p in prompts if "yin_diminish_aim" in _kind(p)], prompts
    assert [p for p in prompts if QUIET in _kind(p)], prompts
    engine = cold(service, tmp_path, mid)
    mark_row = yin.mark_on(engine.state.actors[T_FOE], T_OWNER)
    assert mark_row is not None
    return mark_row.expires_on


def test_quiet_reception_does_not_credit_another_yin_owners_penalty_at_the_table(tmp_path):
    """Finding 5: only this Yin character's own Diminish Aim makes the mark last a minute."""
    expires = _quiet_mark_test(
        tmp_path, [QUIET, MARKING], ["TAL_YIN_MARKING_A_CREATURE", "TAL_YIN_SPENDING_A_WANING_MARK"], by_owner=False)
    assert expires == "END_OF_MARKER_NEXT_TURN"


def test_quiet_reception_credits_its_own_yin_penalty_at_the_table(tmp_path):
    """Finding 5 positive control: the same character's own Diminish Aim does qualify."""
    expires = _quiet_mark_test(
        tmp_path, [QUIET, MARKING, "TAL_YIN_SPENDING_A_WANING_MARK"], (), by_owner=True)
    assert expires.startswith("START_OF_SLOT_AT:")

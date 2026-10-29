"""AUTO17 (round 25): the Blacksmith sphere's Forge Mark chassis and its Forge Responses, run at the table.

Every test here fails on int/r25x2-fix. The Forge Mark chassis printed
"a workpiece can hold a number of Forge Marks from you equal to your Proficiency Bonus" and
"a Forge Mark lasts for 1 minute during action scenes" (the sphere's own Forge Marks section), and neither
half ran: combat/typed_executor.py's block_mark keys ONE condition instance per mark name, so a second
Hammer the Mark on the same workpiece refreshed that instance and changed nothing, and marks never expired.
Tempering Sequence and Field Repair compiled to nothing at all, Fit Armor's two middle options were literal
{"type": "rider"} effects that reduced nothing, and Seven-Hammer Revision's modifier reported
"no matching ability". See APP/combat/ext/blacksmith_forge.py and APP/combat/ext/ironclad_blacksmith.py.
"""

from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind
from combat.gate4_engine import Gate4ControllerEngine

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.smith17"
ALLY = "actor:factory.smith17ally"


@pytest.mark.parametrize("owner_id", [ME, AN])
def test_expiring_modifier_does_not_enter_forge_mark_condition_hook(owner_id):
    """The real expiry sweep dispatches both modifiers and conditions to this hook."""
    from combat.ext import effect_durations
    from combat.gate2_runtime_models import ModifierInstance

    engine = _engine(_bundle([]))
    holder = engine.state.actors[owner_id]
    holder.modifiers["expiry-probe"] = ModifierInstance(
        modifier_id="expiry-probe", source_definition_id="test:expiry-probe",
        source_actor_id=owner_id, target_id=owner_id, target_field="speed_ft",
        operation="ADD", value=10, applies_to="ALL",
        expires_on=effect_durations.token("end", owner_id, holder.turns_started),
    )
    before = len(engine.events)
    effect_durations.sweep(engine, holder, "END_OF_TURN", owner_id)
    assert "expiry-probe" not in holder.modifiers
    events = engine.events[before:]
    assert any(e.event_type == "MODIFIER_REMOVED" for e in events)
    assert not any("forge_mark_expires_one_at_a_time" in str(e.payload) for e in events)

SPHERE = "tianxia.sphere.blacksmith"
BASES = ["BLACKSMITH_BASE_BLACKSMITH_TRAINING", "BLACKSMITH_BASE_READ_THE_FLAW", "BLACKSMITH_BASE_SET_THE_WORKPIECE",
         "BLACKSMITH_BASE_HAMMER_THE_MARK", "BLACKSMITH_BASE_QUENCH_THE_MARK"]
HAMMER = "tianxia.talent.blacksmith.tempering_sequence"
FIELD_REPAIR = "tianxia.talent.blacksmith.field_repair"
QUENCH_BREATH = "tianxia.talent.blacksmith.quench_in_breath"
REVISION = "tianxia.talent.blacksmith.seven_hammer_revision"
INCARNATION = "tianxia.talent.blacksmith.incarnation_of_the_living_forge"
FITTED_ARMOR = "tianxia.talent.blacksmith.forge_fitted_armor"
FITTED_WEAPON = "tianxia.talent.blacksmith.forge_fitted_weapon"


def _sheet(talents, *, cl=10, pb=4, spheres=(SPHERE,), key="INT", key_mod=4):
    abilities = [{"ability": a, "score": 18 if a == key else 14, "modifier": key_mod if a == key else 2}
                 for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")]
    return {
        "identity": {"proficiency_bonus": pb, "cultivation_level": cl, "path": "Qi Cultivation", "key_ability": key},
        "ability_scores_and_statistics": {
            "abilities": abilities, "primary_resource": {"name": "Qi", "maximum": 40},
            "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60}, "speed": {"walking_ft": 30},
            "technique_save_dc": 8 + pb, "technique_attack_bonus": 8,
        },
        # A real weapon, so a printed "weapon, tool, object, or construct attack" exists to strike with.
        "equipment": [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao"}]}}],
        "spheres_and_talents": {"sphere_record_ids": list(spheres), "learned_talent_record_ids": [*BASES, *talents]},
    }


def _bundle(talents, **kw):
    return compile_character(_sheet(talents, **kw), actor_id=ME)


def _ally_bundle(**kw):
    """A second compiled fighter, weaker than the smith and keyed on a different ability, so a printed number that
    must come from the smith cannot be read off the ally by accident."""
    return compile_character(_sheet([], spheres=(), pb=2, key="STR", key_mod=5, **kw), actor_id=ALLY)


def _engine(bundle, *, ally=True, foe_at=(4, 6)):
    """A real table fight: the smith, a stock foe, and (when asked) a second compiled fighter who can attack the smith."""
    bundles, teams, places = (bundle,), {ME: "team:a", AN: "team:b"}, {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}
    roster = [ME, AN]
    if ally:
        bundles += (_ally_bundle(),)
        roster.append(ALLY)
        teams[ALLY], places[ALLY] = "team:a", {"x": 4, "y": 5}  # a real ally: the printed 30 feet measure an ally
    engine = Gate4ControllerEngine(ROOT, match_seed="AUTO17", typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": roster, "team_by_actor": teams, "starting_positions": places})
    _turn(engine, ME)
    return engine


def _turn(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()
    actor = engine.state.actors[actor_id]
    actor.action_available, actor.bonus_action_available, actor.reaction_available = True, True, True
    return actor


def _ready(engine, actor_id=ME):
    actor = engine.state.actors[actor_id]
    engine.state.current_actor_id = actor_id
    actor.action_available, actor.bonus_action_available, actor.reaction_available = True, True, True
    return actor


def _use(engine, name, *, actor_id=ME, target=None, times=1):
    events = []
    for index in range(times):
        candidates = [c for c in engine.legal_candidates() if c.display_name == name]
        assert candidates, f"{name!r} is not a legal action for {actor_id}; legal: {sorted({c.display_name for c in engine.legal_candidates()})}"
        candidate = next((c for c in candidates if target in (c.target_ids or ())), candidates[0])
        before = len(engine.events)
        engine.execute_intent(ActionIntent(intent_id=f"a17-{index}-{name}", decision_id=candidate.decision_id,
                                           candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                           actor_id=actor_id, target_ids=candidate.target_ids or ((target,) if target else ()),
                                           destination=candidate.destination))
        events += engine.events[before:]
        if actor_id == ME:
            _ready(engine, ME)
    return events


def _smith(engine):
    return engine.state.actors[ME]


def _condition(actor, condition_id):
    """The stored condition with this id (ActorState.conditions is keyed by instance id)."""
    return next((c for c in actor.conditions.values() if c.condition_id == condition_id), None)


def _holds(actor, condition_id):
    return _condition(actor, condition_id) is not None


def _marks(engine):
    """The Forge Marks the smith currently carries (the count the printed limit and 1-minute life apply to)."""
    from combat.typed_executor import mark_condition_id

    row = _condition(_smith(engine), mark_condition_id("Forge Mark", ME))
    return int((row.data or {}).get("count") or 0) if row is not None else 0


def _mark_row(engine):
    """The one stored Forge Mark instance the smith's marks live in."""
    from combat.typed_executor import mark_condition_id

    return _condition(_smith(engine), mark_condition_id("Forge Mark", ME))


def _mark_data(engine):
    return dict((_mark_row(engine).data or {}))


def _advance_to(engine, round_number, slot_index):
    """Move the table's round clock onto a stored deadline, the way the engine's own expiry sweep reads it."""
    engine.state.round_number = int(round_number)
    engine.state.current_slot_index = int(slot_index)


def _rider_lines(events):
    return [str(payload.get("log") or payload.get("text") or payload.get("rider") or "") for event in events
            for payload in [event.payload or {}] if event.event_type in {"GM_RIDER", "RIDER"}]


def _strike_ctx(engine, *, actor_id=ME, weapon=True):
    """The striker's real Context, aimed at the foe, with that fighter's own compiled numbers.

    Its typed row rolls visible damage dice, so a printed "rolls damage" trigger has a typed packet to answer (a
    basic Attack action's own dice are rolled inside the sealed gate2 resolver instead -- a lock-round item listed in
    the AUTO17 report). ``weapon=False`` gives the same packet behind an unarmed strike instead.
    """
    from combat.gate2_runtime_models import ActionIntent
    from combat.typed_executor import Context

    wanted = "Dao (Saber" if weapon else "Unarmed Strike"
    action = next(row for row in engine.action_catalog.values() if row.display_name.startswith(wanted))
    typed = action.parameters.get("typed") or {}
    intent = ActionIntent(intent_id="a17-strike", decision_id="d", candidate_id="c", state_version=0,
                          actor_id=actor_id, target_ids=(AN,))
    return Context(engine, engine.state.actors[actor_id], action, intent, typed, [engine.state.actors[AN]],
                   engine.state.actors[AN], {})


# ----------------------------------------------------------------------------------------- the Forge Mark chassis
def test_a_workpiece_accumulates_forge_marks_up_to_the_printed_limit():
    """"a workpiece can hold a number of Forge Marks from you equal to your Proficiency Bonus" and Hammer the Mark's
    "A workpiece cannot exceed your normal Forge Mark limit": before, the second Hammer the Mark refreshed one
    condition instance and the count never rose above 1."""
    engine = _engine(_bundle([]))
    assert _marks(engine) == 0
    _use(engine, "Hammer the Mark", times=4)
    assert _marks(engine) == 4  # this smith's Proficiency Bonus
    _use(engine, "Hammer the Mark")
    assert _marks(engine) == 4, "a fifth mark must not be placed"


def test_a_forge_mark_expires_after_one_minute():
    """"a Forge Mark lasts for 1 minute during action scenes" -- ten rounds on this table's clock. Before, the
    compiled rows carried duration until_removed, so a mark lasted the whole fight."""
    from combat.ext import effect_durations

    engine = _engine(_bundle([]))
    _use(engine, "Hammer the Mark")
    from combat.typed_executor import mark_condition_id

    row = _condition(_smith(engine), mark_condition_id("Forge Mark", ME))
    assert effect_durations.SLOT_AT in row.expires_on
    engine.state.round_number += 10
    effect_durations.sweep(engine, _smith(engine), "TEST")
    assert _marks(engine) == 0


def test_a_later_forge_mark_does_not_keep_an_older_one_alive():
    """"a Forge Mark lasts for 1 minute" is measured per mark. The whole count lives in one condition instance, so the
    clock is measured from the placement that started it: a mark placed five rounds later must not push the first
    mark's minute out with it."""
    engine = _engine(_bundle([]))
    from combat.typed_executor import mark_condition_id

    _use(engine, "Hammer the Mark")
    first = _condition(_smith(engine), mark_condition_id("Forge Mark", ME)).expires_on
    engine.state.round_number += 5
    _ready(engine, ME)
    _use(engine, "Hammer the Mark")
    row = _condition(_smith(engine), mark_condition_id("Forge Mark", ME))
    assert int(row.data["count"]) == 2
    assert row.expires_on == first, "the count still ends one minute after the mark that started it"


def test_each_forge_mark_keeps_its_own_one_minute():
    """"a Forge Mark lasts for 1 minute during action scenes" is measured per mark, and the row keeps one deadline
    per mark. Before, every mark in the count shared the oldest mark's single deadline, so a mark placed five rounds
    later lost those five rounds of its own printed minute and the whole batch went at the first mark's minute."""
    from combat.ext import effect_durations

    engine = _engine(_bundle([]))
    _use(engine, "Hammer the Mark")
    first = tuple(_mark_data(engine)["deadlines"][0])
    engine.state.round_number += 5
    _ready(engine, ME)
    _use(engine, "Hammer the Mark")
    deadlines = [tuple(pair) for pair in _mark_data(engine)["deadlines"]]
    assert len(deadlines) == 2 and deadlines[0] == first < deadlines[1], "one deadline per mark, oldest first"
    assert effect_durations.parse_round(_mark_row(engine).expires_on) == (first[0] + 10, first[1])

    _advance_to(engine, first[0] + 10, first[1])  # the first mark's own minute comes due
    effect_durations.sweep(engine, _smith(engine), "TEST")
    assert _marks(engine) == 1, "the later mark still has five rounds of its own minute"
    assert effect_durations.parse_round(_mark_row(engine).expires_on) == (deadlines[1][0] + 10, deadlines[1][1])
    _advance_to(engine, deadlines[1][0] + 10, deadlines[1][1])
    effect_durations.sweep(engine, _smith(engine), "TEST")
    assert _marks(engine) == 0, "and the last mark's own minute ends it"


def test_a_saved_forge_mark_row_with_one_shared_deadline_keeps_that_deadline():
    """A fight saved by auto17f1 counted its marks against a single ``since_round``/``since_slot`` pair, so every
    mark in it shares that minute. Reading that row back must not shift the deadline it was saved with: the saved
    marks keep it, and only a mark placed afterwards gets a deadline of its own."""
    from combat.ext import blacksmith_forge
    from combat.typed_executor import mark_condition_id

    engine = _engine(_bundle([]))
    smith = _smith(engine)
    saved = blacksmith_forge.clock_token(2, 1)
    engine._apply_condition(smith, mark_condition_id("Forge Mark", ME), "BLACKSMITH_BASE_HAMMER_THE_MARK", ME,
                            expires_on=saved,
                            data={"count": 2, "since_round": 2, "since_slot": 1, "label": "Forge Marks (2 of 4)"})
    assert _marks(engine) == 2 and blacksmith_forge.stored_deadlines({"count": 2}) == [], "no deadline is invented"

    engine.state.round_number = 6
    blacksmith_forge.set_marks(engine, smith, smith, 1, "test:place")
    placed = (6, int(engine.state.current_slot_index))
    assert _mark_row(engine).expires_on == saved, "a saved deadline is kept, not restarted"
    assert [tuple(pair) for pair in _mark_data(engine)["deadlines"]] == [(2, 1), (2, 1), placed]

    blacksmith_forge.set_marks(engine, smith, smith, -1, "test:spend")
    assert _mark_row(engine).expires_on == saved, "spending the mark that would have gone first keeps the saved minute"
    assert [tuple(pair) for pair in _mark_data(engine)["deadlines"]] == [(2, 1), placed]

    engine.state.round_number = 12
    _ready(engine, ME)
    blacksmith_forge.set_marks(engine, smith, smith, 1, "test:place")
    assert [tuple(pair) for pair in _mark_data(engine)["deadlines"]] == [(2, 1), placed, (12, engine.state.current_slot_index)]


def test_spending_one_forge_mark_leaves_the_others_on_the_workpiece():
    """"Cost: Spend 1 Forge Mark" takes one mark off; before, the first spend removed the only instance whatever
    the count, so a second response had nothing left to pay with."""
    engine = _engine(_bundle([]))
    _use(engine, "Hammer the Mark", times=2)
    _use(engine, "Set Edge")
    assert _marks(engine) == 1
    _use(engine, "Set Edge")
    assert _marks(engine) == 0


def test_incarnation_of_the_living_forge_raises_the_forge_mark_limit_by_two():
    """"your Forge Mark limit on each current workpiece increases by 2"."""
    engine = _engine(_bundle([INCARNATION]))
    smith = _smith(engine)
    from combat.ext import blacksmith_forge

    assert blacksmith_forge.limit(engine, smith) == smith.proficiency_bonus
    _use(engine, "Incarnation of the Living Forge")
    assert blacksmith_forge.limit(engine, smith) == smith.proficiency_bonus + 2


# -------------------------------------------------------------------------------------------------- Tempering Sequence
def test_tempering_sequence_is_offered_only_with_three_forge_marks_and_spends_them_all():
    """"When a workpiece has at least 3 Forge Marks from you, you may spend all of them to perform a Tempering
    Sequence." Before, the talent compiled to nothing at all (skipped passive, no action)."""
    engine = _engine(_bundle([HAMMER]))
    assert "Tempering Sequence: Hardening Sequence" not in {c.display_name for c in engine.legal_candidates()}
    _use(engine, "Hammer the Mark", times=3)
    _ready(engine, ME)
    assert "Tempering Sequence: Hardening Sequence" in {c.display_name for c in engine.legal_candidates()}
    _use(engine, "Tempering Sequence: Hardening Sequence")
    assert _marks(engine) == 0


def test_the_four_printed_tempering_sequences_are_all_offered():
    """"Choose one: Hardening Sequence / Softening Sequence / Purifying Sequence / Awakening Sequence." All four are the
    player's choice, so all four are buttons. Before, the Purifying Sequence was left out entirely."""
    engine = _engine(_bundle([HAMMER]))
    _use(engine, "Hammer the Mark", times=3)
    _ready(engine, ME)
    offered = {c.display_name for c in engine.legal_candidates()}
    assert {"Tempering Sequence: Hardening Sequence", "Tempering Sequence: Softening Sequence",
            "Tempering Sequence: Purifying Sequence",
            "Tempering Sequence: Awakening Sequence"} <= offered


def test_the_purifying_sequence_spends_every_mark_and_leaves_the_purification_to_the_gm():
    """"Reduce one mundane impurity, rust, poison residue, rot, corrosion, instability, or crafting complication
    affecting the workpiece. A magical curse or artifact flaw is only reduced if the GM allows it." The table keeps no
    state for an object's condition, so the sequence spends the marks and says what it purifies."""
    engine = _engine(_bundle([HAMMER]))
    _use(engine, "Hammer the Mark", times=3)
    _use(engine, "Tempering Sequence: Purifying Sequence")
    assert _marks(engine) == 0, "a sequence spends all of them"
    lines = _rider_lines(engine.events)
    assert any("Purifying Sequence" in line and "rust" in line for line in lines)
    assert not _holds(_smith(engine), "condition:typed.tempering_hardened")


def test_the_hardening_sequence_grants_the_printed_temporary_temper():
    """"The workpiece gains a Temporary Temper lasting 10 minutes. If armor or shield, it grants +1 AC. If weapon or
    tool, it gains +1 to attack rolls or relevant checks." On this table the smith is the workpiece."""
    from combat import ext

    engine = _engine(_bundle([HAMMER]))
    base_ac = sum(ext.run("ac", engine, _smith(engine)))
    _use(engine, "Hammer the Mark", times=3)
    _use(engine, "Tempering Sequence: Hardening Sequence")
    smith = _smith(engine)
    assert _holds(smith, "condition:typed.tempering_hardened")
    assert sum(ext.run("ac", engine, smith)) == base_ac + 1
    assert 1 in list(ext.run("attack_bonus", _context(engine), smith))


def test_the_softening_sequence_grants_advantage_on_one_check():
    """"The next repair, crafting, modification, or disarm attempt involving it before the end of the scene has
    Advantage" -- one use, on the smith's next roll."""
    engine = _engine(_bundle([HAMMER]))
    _use(engine, "Hammer the Mark", times=3)
    _use(engine, "Tempering Sequence: Softening Sequence")
    from combat import ext

    smith = _smith(engine)
    assert _holds(smith, "condition:typed.tempering_softened")
    assert "ADVANTAGE" in list(ext.run("ability_check_mode", engine, smith, "INT", "smiths_tools", None))
    assert not _holds(smith, "condition:typed.tempering_softened"), "Advantage is granted once"


def test_the_awakening_sequence_grants_advantage_on_one_roll():
    """"During that time, once when used for its named purpose, it grants Advantage on one roll."""
    from combat import ext

    engine = _engine(_bundle([HAMMER]))
    _use(engine, "Hammer the Mark", times=3)
    _use(engine, "Tempering Sequence: Awakening Sequence")
    smith = _smith(engine)
    assert _holds(smith, "condition:typed.item_spirit_sign")
    assert "ADVANTAGE" in list(ext.run("attack_mode", _context(engine), engine.state.actors[AN]))
    assert not _holds(smith, "condition:typed.item_spirit_sign"), "the one Advantage is spent on that roll"


def test_the_awakening_sequence_also_answers_a_saving_throw():
    """The same one-roll Advantage covers a saving throw, which is the other roll a fight asks for."""
    from combat import ext

    engine = _engine(_bundle([HAMMER]))
    _use(engine, "Hammer the Mark", times=3)
    _use(engine, "Tempering Sequence: Awakening Sequence")
    smith = _smith(engine)
    ctx = _context(engine)
    assert ext.run("save", ctx, smith, "STR", {"prone"}) == [{"bonus": 0, "modes": ["ADVANTAGE"]}]
    assert not _holds(smith, "condition:typed.item_spirit_sign")
    assert ext.run("save", ctx, smith, "STR", {"prone"}) == [], "and only once"


def test_the_softening_sequence_leaves_attack_rolls_alone():
    """Softening is printed for "the next repair, crafting, modification, or disarm attempt" -- an attempt at the
    workpiece is a check, so an ordinary attack roll must not quietly consume the one Advantage."""
    from combat import ext

    engine = _engine(_bundle([HAMMER]))
    _use(engine, "Hammer the Mark", times=3)
    _use(engine, "Tempering Sequence: Softening Sequence")
    smith = _smith(engine)
    assert "ADVANTAGE" not in list(ext.run("attack_mode", _context(engine), engine.state.actors[AN]))
    assert _holds(smith, "condition:typed.tempering_softened"), "the check Advantage is still waiting"


def _context(engine):
    """A read-only Context for querying a hook whose signature takes one (no effect is run)."""
    from combat.typed_executor import Context

    action = next(row for row in engine.action_catalog.values() if row.display_name == "Hammer the Mark")
    foe = engine.state.actors[AN]
    return Context(engine, _smith(engine), action, None, action.parameters.get("typed") or {}, [foe], foe, {})


# ----------------------------------------------------------------------------------------------------- Field Repair
def test_field_repair_places_a_forge_mark_on_a_creatures_damaged_equipment():
    """"use your Reaction to Set the Workpiece to that object and place 1 Forge Mark on it." Before, the talent
    compiled to nothing (it was listed as a ritual, 'outside' fights)."""
    from combat.typed_executor import mark_condition_id

    engine = _engine(_bundle([FIELD_REPAIR]), ally=False)
    _use(engine, "Confirm damaged equipment: Field Repair (uses Reaction)", target=AN)
    row = _condition(engine.state.actors[AN], mark_condition_id("Forge Mark", ME))
    assert row is not None and int(row.data["count"]) == 1


def test_close_the_crack_costs_one_of_the_smiths_own_path_points():
    """"At CL 5+, you may also use Close the Crack as part of the same Reaction by spending 1 CP." The printed cost
    must be charged from the fighter's own pool, not left free."""
    engine = _engine(_bundle([FIELD_REPAIR]))
    qi = next(key for key in _smith(engine).resources if key.endswith("core.qi"))
    before = _smith(engine).resources[qi]
    _use(engine, "Confirm damaged equipment: Field Repair + Close the Crack (uses Reaction + 1 CP)", target=AN)
    assert _smith(engine).resources[qi] == before - 1


def test_set_edge_check_hook_uses_the_checked_creature_and_spends_its_bonus_once():
    from combat import ext
    from combat.ext.ironclad_blacksmith import SET_EDGE_READY
    from combat.typed_executor import bears_mark

    engine = _engine(_bundle([]))
    smith = _smith(engine)
    _use(engine, "Hammer the Mark")
    _use(engine, "Set Edge")
    ctx = _strike_ctx(engine)
    # Defensive checks can supply a creature other than the Context's actor.
    assert sum(ext.run("check_bonus", ctx, engine.state.actors[ALLY])) == 0
    assert bears_mark(smith, ME, SET_EDGE_READY)
    assert sum(ext.run("check_bonus", _strike_ctx(engine, actor_id=ALLY), smith)) == 4
    assert not bears_mark(smith, ME, SET_EDGE_READY)
    assert sum(ext.run("check_bonus", ctx, smith)) == 0


# ------------------------------------------------------------------------------------------------- Quench in Breath
def test_quench_in_breath_reduces_the_next_element_damage_after_spending_a_mark():
    """Quench in Breath: "When you spend a Forge Mark on a workpiece you hold, wear, or touch, reduce the next
    Fire, Cold, Lightning, or Acid damage you take before the start of your next turn by your Proficiency Bonus."
    The printed reduction ran for nothing (the talent was listed as a table gap)."""
    engine = _engine(_bundle([QUENCH_BREATH]))
    smith = _smith(engine)
    _use(engine, "Hammer the Mark", times=2)
    _use(engine, "Set Edge")
    assert _holds(smith, "condition:typed.quench_in_breath")
    engine._commit_damage(smith, 30, "FIRE", "test:flame", AN, None, reaction_depth=0)
    assert smith.current_hp == 60 - 30 + 4, "Fire damage 30 is reduced by the Proficiency Bonus of 4"
    assert not _holds(smith, "condition:typed.quench_in_breath"), "the reduction is spent"


def test_quench_in_breath_leaves_other_damage_alone():
    engine = _engine(_bundle([QUENCH_BREATH]))
    smith = _smith(engine)
    _use(engine, "Hammer the Mark", times=2)
    _use(engine, "Set Edge")
    engine._commit_damage(smith, 30, "BLUDGEONING", "test:club", AN, None, reaction_depth=0)
    assert smith.current_hp == 60 - 30


def test_quench_in_breath_answers_a_revision_that_spends_a_forge_mark():
    """Quench in Breath triggers on "When you spend a Forge Mark", and Seven-Hammer Revision spends one by itself.
    The engine only announces a spend it makes from a "Cost: Spend 1 Forge Mark" row, so before this lane's review
    the revision paid its mark in silence and the printed reduction never appeared."""
    from combat.typed_executor import run_effects

    engine = _engine(_bundle([QUENCH_BREATH, REVISION]))
    smith = _smith(engine)
    _use(engine, "Hammer the Mark", times=2)
    run_effects(_strike_ctx(engine), _STRIKE_DAMAGE)
    assert _holds(smith, "condition:typed.quench_in_breath")
    engine._commit_damage(smith, 30, "ACID", "test:acid", AN, None, reaction_depth=0)
    assert smith.current_hp == 60 - 30 + 4


def test_quench_in_breath_answers_a_tempering_sequence_that_spends_every_mark():
    """"spend all of them to perform a Tempering Sequence" spends Forge Marks too."""
    engine = _engine(_bundle([QUENCH_BREATH, HAMMER]))
    smith = _smith(engine)
    _use(engine, "Hammer the Mark", times=3)
    assert not _holds(smith, "condition:typed.quench_in_breath"), "placing a mark is not spending one"
    _use(engine, "Tempering Sequence: Hardening Sequence")
    assert _holds(smith, "condition:typed.quench_in_breath")


# ------------------------------------------------------------------------------------------- Seven-Hammer Revision
_STRIKE_DAMAGE = [{"type": "damage", "dice": {"count": 3, "sides": 6, "modifier": 0}, "damage_types": ["slashing"]}]


def test_seven_hammer_revision_rerolls_damage_dice_and_spends_exactly_one_mark():
    """Seven-Hammer Revision: "When you or an ally within 30 feet rolls damage with a weapon, tool, object, or
    construct attack involving a workpiece bearing your Forge Mark, spend 1 Forge Mark to revise the strike. Reroll a
    number of damage dice up to your Proficiency Bonus and use the new rolls." Before, the modifier reported
    'no matching ability' and nothing ran."""
    from combat.typed_executor import run_effects

    engine = _engine(_bundle([REVISION]))
    ctx = _strike_ctx(engine)
    _use(engine, "Hammer the Mark", times=2)
    before = len(engine.events)
    run_effects(ctx, _STRIKE_DAMAGE)
    events = engine.events[before:]
    assert _marks(engine) == 1, "the revision spends exactly one Forge Mark"
    rerolled = [event for event in events if event.event_type == "DAMAGE_ROLLED" and event.payload.get("rerolled_dice")]
    assert len(rerolled) == 1, "one damage reroll is rolled and recorded for the replay"
    assert int(rerolled[0].payload["rerolled_dice"]) == 3, "up to the Proficiency Bonus of 4, capped by the 3 dice rolled"
    assert any("Seven-Hammer Revision" in line for line in _rider_lines(events))


def test_seven_hammer_revision_adds_the_intelligence_modifier_only_for_a_workpiece_you_built_yourself():
    """"If the workpiece is one you personally forged or prepared during the current day, also add your Intelligence
    modifier to the damage roll." The table keeps no record of which workpieces a smith forged, so the modifier waits
    for the fighter's own toggle -- and is not simply added on every revision."""
    from combat.typed_executor import run_effects

    engine = _engine(_bundle([REVISION]))
    _use(engine, "Hammer the Mark", times=3)
    run_effects(_strike_ctx(engine), _STRIKE_DAMAGE)
    assert int(_reroll(engine)[-1].payload["reroll_bonus"]) == 0, "no declared personal work, no modifier"
    _use(engine, "Seven-Hammer Revision: workpiece personally forged or prepared today")
    _use(engine, "Hammer the Mark")
    run_effects(_strike_ctx(engine), _STRIKE_DAMAGE)
    assert int(_reroll(engine)[-1].payload["reroll_bonus"]) == 4, "the smith's own +4 Intelligence modifier"
    damage = [event for event in engine.events if event.event_type == "DAMAGE_COMMITTED"]
    assert int(damage[-1].payload["hp_damage"]) > 4, "the packet carries the Intelligence modifier too"


def test_seven_hammer_revision_prices_the_revision_with_the_smiths_own_numbers():
    """An ally's strike is revised with the SMITH's Proficiency Bonus cap and the SMITH's Intelligence modifier.
    Before, both numbers were read off ``ctx.numbers``, which belongs to whoever rolled the damage, so an ally's
    weaker Proficiency Bonus capped the reroll and the ally's own key-ability modifier was reported as the smith's
    Intelligence modifier."""
    from combat.typed_executor import run_effects

    engine = _engine(_bundle([REVISION]))
    _use(engine, "Hammer the Mark", times=3)
    ally = engine.state.actors[ALLY]
    assert ally.proficiency_bonus == 2 and int(ally.saving_throws["STR"]) == 5, "the ally's numbers, not the smith's"
    run_effects(_strike_ctx(engine, actor_id=ALLY), _STRIKE_DAMAGE)
    assert int(_reroll(engine)[-1].payload["rerolled_dice"]) == 3, "capped by the smith's Proficiency Bonus of 4, not 2"
    _use(engine, "Seven-Hammer Revision: workpiece personally forged or prepared today")
    _use(engine, "Hammer the Mark")
    run_effects(_strike_ctx(engine, actor_id=ALLY), _STRIKE_DAMAGE)
    assert int(_reroll(engine)[-1].payload["reroll_bonus"]) == 4, "the smith's Intelligence modifier, not the ally's +5"


def test_seven_hammer_revision_leaves_an_unarmed_strike_alone():
    """The printed trigger is "rolls damage with a weapon, tool, object, or construct attack". An unarmed strike is
    none of the four, so it is not revised and no Forge Mark is spent on it."""
    from combat.typed_executor import run_effects

    engine = _engine(_bundle([REVISION]))
    _use(engine, "Hammer the Mark", times=2)
    before = len(engine.events)
    run_effects(_strike_ctx(engine, weapon=False), _STRIKE_DAMAGE)
    assert not _reroll(engine, since=before), "an unarmed strike is not a weapon, tool, object or construct attack"
    assert _marks(engine) == 2, "no Forge Mark was spent"


def test_seven_hammer_revision_leaves_the_packet_alone_without_a_forge_mark_to_spend():
    from combat.typed_executor import run_effects

    engine = _engine(_bundle([REVISION]))
    ctx = _strike_ctx(engine)
    before = len(engine.events)
    run_effects(ctx, _STRIKE_DAMAGE)
    events = engine.events[before:]
    assert _marks(engine) == 0
    assert not [event for event in events if event.event_type == "DAMAGE_ROLLED" and event.payload.get("rerolled_dice")]


def test_seven_hammer_revision_reaches_an_ally_within_thirty_feet_and_no_further():
    """The printed trigger is "you or an ally within 30 feet"; a smith whose Forge Mark has run out of reach
    (or out of marks) revises nothing."""
    from combat.typed_executor import run_effects

    engine = _engine(_bundle([REVISION]))
    _use(engine, "Hammer the Mark", times=2)
    ally = engine.state.actors[ALLY]
    ally.position = {"x": 11, "y": 11}  # more than 30 feet from the smith at 3,6
    before = len(engine.events)
    run_effects(_strike_ctx(engine, actor_id=ALLY), _STRIKE_DAMAGE)
    assert not _reroll(engine, since=before)
    assert _marks(engine) == 2, "no Forge Mark was spent on a strike nobody could revise"
    ally.position = {"x": 4, "y": 5}  # within 30 feet
    before = len(engine.events)
    run_effects(_strike_ctx(engine, actor_id=ALLY), _STRIKE_DAMAGE)
    assert _reroll(engine, since=before)


def test_the_thirty_foot_reach_is_the_maps_own_measure():
    """The printed 30 feet are the table's own range measure. Before, the reach was a hand-counted grid distance that
    counts the diagonal twice, so a smith 5 squares away across the diagonal fell outside the printed range."""
    from combat.typed_executor import run_effects

    engine = _engine(_bundle([REVISION]))
    _use(engine, "Hammer the Mark", times=2)
    ally = engine.state.actors[ALLY]
    ally.position = {"x": 8, "y": 10}  # five squares away on the map's own measure (25 feet), six by the old count
    before = len(engine.events)
    run_effects(_strike_ctx(engine, actor_id=ALLY), _STRIKE_DAMAGE)
    assert _reroll(engine, since=before), "25 feet on the map is inside the printed 30 feet"


def test_the_personal_work_declaration_can_be_ended_by_the_fighter():
    """"If the workpiece is one you personally forged or prepared during the current day" is the fighter's own answer,
    and it was a one-way button: once pressed it could never be taken back, so a workpiece bought from a shop kept
    the printed Intelligence modifier for the rest of the fight. Each button is now offered only while it would
    change something, and ending the declaration takes it straight back."""
    from combat.ext import blacksmith_forge
    from combat.typed_executor import run_effects

    engine = _engine(_bundle([REVISION]))
    _use(engine, "Hammer the Mark", times=2)
    assert "Seven-Hammer Revision: end the personal-work declaration" not in _labels(engine), "nothing to end yet"
    _use(engine, "Seven-Hammer Revision: workpiece personally forged or prepared today")
    assert blacksmith_forge.personal_work(_smith(engine))
    assert "Seven-Hammer Revision: workpiece personally forged or prepared today" not in _labels(engine), "already declared"
    _use(engine, "Seven-Hammer Revision: end the personal-work declaration")
    assert not blacksmith_forge.personal_work(_smith(engine))
    run_effects(_strike_ctx(engine), _STRIKE_DAMAGE)
    assert int(_reroll(engine)[-1].payload["reroll_bonus"]) == 0, "a declaration that was ended pays no modifier"
    assert _marks(engine) == 1, "the revision itself still rerolled its dice and spent its one mark"


def test_the_personal_work_declaration_lapses_with_the_smiths_last_forge_mark():
    """The declaration describes a workpiece bearing your Forge Mark, so it has a defined reset: with no Forge Mark
    of the smith's standing there is no workpiece for it to describe, and the answer ends -- by a spend here and, in
    the next test, by the printed one-minute expiry. It cannot otherwise drift on for the rest of the fight."""
    from combat.ext import blacksmith_forge
    from combat.typed_executor import run_effects

    engine = _engine(_bundle([REVISION, HAMMER]))
    _use(engine, "Hammer the Mark", times=3)
    _use(engine, "Seven-Hammer Revision: workpiece personally forged or prepared today")
    assert blacksmith_forge.personal_work(_smith(engine))
    _use(engine, "Tempering Sequence: Hardening Sequence")  # "spend all of them"
    assert _marks(engine) == 0
    assert not blacksmith_forge.personal_work(_smith(engine)), "the declaration ends with the last Forge Mark"
    _use(engine, "Hammer the Mark")
    run_effects(_strike_ctx(engine), _STRIKE_DAMAGE)
    assert int(_reroll(engine)[-1].payload["reroll_bonus"]) == 0, "a lapsed declaration pays no modifier"


def test_the_personal_work_declaration_lapses_when_the_last_forge_mark_expires():
    """The same defined reset by the printed one-minute life, through the engine's own expiry sweep."""
    from combat.ext import blacksmith_forge, effect_durations

    engine = _engine(_bundle([REVISION]))
    _use(engine, "Hammer the Mark")
    _use(engine, "Seven-Hammer Revision: workpiece personally forged or prepared today")
    row = _mark_row(engine)
    clock = effect_durations.parse_round(row.expires_on)
    _advance_to(engine, *clock)
    effect_durations.sweep(engine, _smith(engine), "TEST")
    assert _marks(engine) == 0
    assert not blacksmith_forge.personal_work(_smith(engine))


def test_the_personal_work_declaration_survives_one_holders_forge_mark_expiring():
    """Forge Marks do not only sit on the smith: Field Repair prints "place 1 Forge Mark on it" for a creature's own
    equipment, and the declaration describes "a workpiece you personally forged or prepared", which is any marked
    workpiece of theirs. So one holder's mark reaching its minute used to end the declaration while the smith's own
    marked workpiece was still standing, and the next revision silently lost its Intelligence modifier. Here the
    smith's mark is the older one and ends first; the answer must stay until the last mark of the smith is gone."""
    from combat.ext import blacksmith_forge, effect_durations
    from combat.typed_executor import mark_condition_id

    engine = _engine(_bundle([REVISION, FIELD_REPAIR]))
    _use(engine, "Hammer the Mark")                       # the smith's own marked workpiece, placed first
    own = _mark_row(engine)
    own_deadline = effect_durations.parse_round(own.expires_on)
    _advance_to(engine, *own_deadline)
    _ready(engine, ME)
    _use(engine, "Confirm damaged equipment: Field Repair (uses Reaction)", target=ALLY)  # an ally's damaged equipment, declared a minute later
    _use(engine, "Seven-Hammer Revision: workpiece personally forged or prepared today")
    assert blacksmith_forge.personal_work(_smith(engine))

    _advance_to(engine, *own_deadline)
    effect_durations.sweep(engine, _smith(engine), "TEST")
    assert _marks(engine) == 0, "the smith's own mark has ended"
    ally_row = _condition(engine.state.actors[ALLY], mark_condition_id("Forge Mark", ME))
    assert ally_row is not None and int(ally_row.data["count"]) == 1, "the ally's mark is still standing"
    assert blacksmith_forge.personal_work(_smith(engine)), (
        "another workpiece of the smith's is still marked, so the printed answer still applies to one")

    ally_clock = effect_durations.parse_round(ally_row.expires_on)
    _advance_to(engine, *ally_clock)
    effect_durations.sweep(engine, _smith(engine), "TEST")
    assert not blacksmith_forge.personal_work(_smith(engine)), "now no marked workpiece is left, the answer ends"


def test_spending_the_smiths_last_own_forge_mark_keeps_the_declaration_while_an_ally_mark_stands():
    """The same rule by a spend rather than an expiry: "spend all of them" on the smith's own workpiece must not end
    the declaration while another marked workpiece of theirs is still standing. Before, the reset asked only about
    the smith's own workpiece, so a smith who had marked a partner's equipment lost the modifier silently."""
    from combat.ext import blacksmith_forge
    from combat.typed_executor import mark_condition_id

    engine = _engine(_bundle([REVISION, HAMMER, FIELD_REPAIR]))
    _use(engine, "Hammer the Mark", times=4)               # the printed limit, Proficiency Bonus 4
    _use(engine, "Confirm damaged equipment: Field Repair (uses Reaction)", target=ALLY)
    _use(engine, "Seven-Hammer Revision: workpiece personally forged or prepared today")
    assert _marks(engine) == 4

    _use(engine, "Set Edge")                              # "Cost: Spend 1 Forge Mark" on the smith's own workpiece
    assert _marks(engine) == 3
    assert blacksmith_forge.personal_work(_smith(engine)), "the ally's marked equipment is still one of the smith's"

    _use(engine, "Tempering Sequence: Hardening Sequence")  # "spend all of them", the last of the smith's own
    assert _marks(engine) == 0
    assert _condition(engine.state.actors[ALLY], mark_condition_id("Forge Mark", ME)) is not None
    assert blacksmith_forge.personal_work(_smith(engine)), (
        "the smith still has a marked workpiece: the ally's, so the declaration stands")

    # With the last mark of the smith's gone from every holder, the answer ends.
    from combat.ext import effect_durations

    ally_row = _condition(engine.state.actors[ALLY], mark_condition_id("Forge Mark", ME))
    _advance_to(engine, *effect_durations.parse_round(ally_row.expires_on))
    effect_durations.sweep(engine, _smith(engine), "TEST")
    assert not blacksmith_forge.personal_work(_smith(engine))


def _legacy_mark_row(engine, subject, owner_id, count, expires_on):
    """Write the Forge Mark row exactly as auto17f1 wrote it: a count, a label, and the printed one-minute clock as
    the instance's own expiry -- and nothing at all recording when each mark was placed. Every save from that build
    carries this shape, and no writer in this build produces it any more, so this is how a regression puts one back."""
    from combat.ext import blacksmith_forge, rider_support
    from combat.typed_executor import mark_condition_id

    old = blacksmith_forge.mark_row(subject, owner_id)
    if old is not None:
        rider_support.remove_instance(engine, subject, old.instance_id, old.source_definition_id)
    engine._apply_condition(subject, mark_condition_id("Forge Mark", owner_id), "BLACKSMITH_BASE_HAMMER_THE_MARK",
                            owner_id, expires_on=expires_on,
                            data={"count": count, "label": f"Forge Mark{'s' if count > 1 else ''} ({count} of 4)"})


def test_a_saved_forge_mark_row_with_no_clock_at_all_keeps_its_count_and_its_own_expiry():
    """A save from before the per-mark shape kept a count and its own expiry and said nothing about when each mark
    was placed. Spending one used to raise IndexError -- ``stored_deadlines`` returned an empty list, the spend
    sliced it, and ``store_marks`` then read ``deadlines[0]`` after the old instance was already removed -- and adding
    one wrote a single deadline, quietly dropping the marks a player had already paid for. The expiry the save was
    saved with is recovered from the clock name itself, so the marks keep their minute and the count never drops."""
    from combat.ext import blacksmith_forge
    from combat.ext import effect_durations
    from combat.typed_executor import clock_expiry

    engine = _engine(_bundle([]))
    smith = _smith(engine)
    engine.state.round_number, engine.state.current_slot_index = 3, 1
    saved_expiry = clock_expiry(engine, blacksmith_forge.ONE_MINUTE)   # what auto17f1's own writer stored
    assert saved_expiry == blacksmith_forge.clock_token(3, 1), "the saved expiry is the one-minute clock name"
    _legacy_mark_row(engine, smith, ME, 2, saved_expiry)
    assert _marks(engine) == 2
    assert blacksmith_forge.stored_deadlines(_mark_data(engine), expires_on=saved_expiry) == [(3, 1), (3, 1)], (
        "the saved row's own expiry is read back as the one minute it was saved with, for every mark in it")

    # A placement: the two saved marks keep their saved minute, the new one dates itself.
    _advance_to(engine, 5, 0)
    _ready(engine, ME)
    blacksmith_forge.set_marks(engine, smith, smith, 1, "test:place")
    assert _marks(engine) == 3, "adding a mark keeps the two the save was holding"
    assert [tuple(pair) for pair in _mark_data(engine)["deadlines"]] == [(3, 1), (3, 1), (5, 0)]
    assert _mark_row(engine).expires_on == saved_expiry, "the instance still expires at the soonest mark's minute"

    # A spend: no IndexError, the mark that would have gone first is retired, and the other two are untouched.
    blacksmith_forge.set_marks(engine, smith, smith, -1, "test:spend")
    assert _marks(engine) == 2
    assert [tuple(pair) for pair in _mark_data(engine)["deadlines"]] == [(3, 1), (5, 0)]
    assert _mark_row(engine).expires_on == saved_expiry, "spending a mark does not renew the ones that remain"

    # Spending the saved pair down to one and back up again keeps the same saved minute throughout.
    blacksmith_forge.set_marks(engine, smith, smith, -1, "test:spend")
    assert _marks(engine) == 1, "the saved pair is down to the one mark placed after it"
    assert [tuple(pair) for pair in _mark_data(engine)["deadlines"]] == [(5, 0)]
    assert _mark_row(engine).expires_on == blacksmith_forge.clock_token(5, 0), (
        "the row now expires at its only remaining mark's own minute, and that is later than the saved one")
    _advance_to(engine, *effect_durations.parse_round(saved_expiry))
    effect_durations.sweep(engine, smith, "TEST")
    assert _marks(engine) == 1, "the saved minute went by and took the two saved marks with it, not the newer one"
    _advance_to(engine, *effect_durations.parse_round(_mark_row(engine).expires_on))
    effect_durations.sweep(engine, smith, "TEST")
    assert _marks(engine) == 0, "and the mark placed after it still ends on its own printed minute"


def test_a_forge_mark_row_saved_with_no_clock_still_reloads_from_a_real_saved_fight(tmp_path):
    """The same historical shape, this time on a state a real service loaded off disk from a real committed table
    fight, and stored back in the canonical form a save needs. The row is written here rather than pressed, because
    no button in this build produces it any more -- it is what the older build left behind -- so the resume path is
    what is under test: load, add, spend, and hand the result back to the save format."""
    import json
    import zipfile

    from combat.canonical import canonical_bytes
    from combat.ext import blacksmith_forge
    from combat.ext import effect_durations
    from combat.gate2_runtime_models import ConditionInstance
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from combat.typed_executor import mark_condition_id

    for side in ("smith", "rival"):
        folder = tmp_path / "portable_characters" / side
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(_sheet([REVISION])))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "Lock2 yard", "width_squares": 12, "height_squares": 8,
                               "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    smith_id = FACTORY_ACTOR_PREFIX + "smith"
    view = combat.create_factory_match(project_ids=["smith"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "rival"],
                                       control_modes={smith_id: "MANUAL", FACTORY_ACTOR_PREFIX + "rival": "MANUAL"},
                                       arena_id="battlefield:map.lock2-yard", match_seed="AUTO17R2F1-LEGACY")
    table, match_id = TabletopService(combat, tmp_path), view["match_id"]
    for _ in range(2):
        assert _press(table, match_id, smith_id, "Hammer the Mark")["status"] == "COMMITTED"

    engine = CombatService(ROOT, tmp_path)._load_session(match_id).engine   # a fresh service reads the fight back
    smith = engine.state.actors[smith_id]
    row = _condition(smith, mark_condition_id("Forge Mark", smith_id))
    assert row is not None and int(row.data["count"]) == 2, "the real save came back with its two marks"
    placed = (int(row.data["since_round"]), int(row.data["since_slot"]))
    saved_expiry = blacksmith_forge.clock_token(*placed)

    # Put the row back into the shape the older build wrote, and prove the add/spend path is the one a resumed
    # save actually takes.
    _legacy_mark_row(engine, smith, smith_id, 2, saved_expiry)
    legacy = _condition(smith, mark_condition_id("Forge Mark", smith_id))
    assert legacy.expires_on == saved_expiry and legacy.data == {"count": 2, "label": "Forge Marks (2 of 4)"}, (
        "the row really is the older build's shape: a count, a label, and its own expiry")
    blacksmith_forge.set_marks(engine, smith, smith, 1, "test:add")
    added = [tuple(pair) for pair in _condition(smith, mark_condition_id("Forge Mark", smith_id)).data["deadlines"]]
    assert int(_condition(smith, mark_condition_id("Forge Mark", smith_id)).data["count"]) == 3, (
        "adding a mark keeps the two the save was holding; it used to write one deadline and drop them")
    assert added[:2] == [placed, placed], "and both of them keep the minute the save was saved with"
    blacksmith_forge.set_marks(engine, smith, smith, -1, "test:spend")
    healed = _condition(smith, mark_condition_id("Forge Mark", smith_id))
    assert int(healed.data["count"]) == 2, "spending one retires one mark; it used to raise IndexError"
    assert [tuple(pair) for pair in healed.data["deadlines"]] == [placed, added[2]], (
        "the spend retired the mark that would have gone first, leaving one saved mark and the new one")
    assert healed.expires_on == saved_expiry, "and the fight still ends when that save said it would"

    # The repaired row is integers and strings only, and revalidates as a stored condition, so the next commit of
    # this resumed fight writes a save the next service can read back.
    canonical_bytes(engine.state.model_dump(mode="json"))
    reloaded = ConditionInstance.model_validate(healed.model_dump(mode="json"))
    assert int(reloaded.data["count"]) == 2 and reloaded.expires_on == saved_expiry
    assert effect_durations.parse_round(reloaded.expires_on) == blacksmith_forge.deadline_of(placed)

    # And the historical save itself is untouched and still verifies.
    again = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert again.verify()["status"] == "PASS", "the committed save still verifies"


def test_a_mark_placed_onto_an_undated_saved_row_gets_its_own_printed_minute():
    """The finding this round closes: a save from before this module kept any clock stored ``UNTIL_REMOVED``, so
    there was nothing to read a placement back from. Those marks keep the expiry that save was saved with -- that is
    the compatibility policy and no mark a player paid for is dropped or renewed by it -- but a mark placed AFTER
    resuming is a new mark, and "a Forge Mark lasts for 1 minute during action scenes" has to apply to it.

    Before, the whole count was written back undated on the save's expiry, so the new mark inherited a row the engine
    never came due for: it lasted the rest of the fight, and the printed limit could be spent on marks that had no
    minute at all. Ten rounds later only the two the save was holding are left, the new one has ended on its own
    minute, and spending from either population afterwards keeps the other intact."""
    from combat.canonical import canonical_bytes
    from combat.ext import blacksmith_forge, effect_durations

    engine = _engine(_bundle([]))
    smith = _smith(engine)
    engine.state.round_number, engine.state.current_slot_index = 3, 0
    _legacy_mark_row(engine, smith, ME, 2, "UNTIL_REMOVED")
    assert _marks(engine) == 2

    # A placement after resuming: the two the save was holding are untouched, the new one dates itself.
    blacksmith_forge.set_marks(engine, smith, smith, 1, "test:place")
    row = _mark_row(engine)
    assert _marks(engine) == 3, "adding a mark keeps the two the save was holding"
    assert int(_mark_data(engine)["undated"]) == 2, "and counts them apart from the one that has a minute"
    assert [tuple(pair) for pair in _mark_data(engine)["deadlines"]] == [(3, 0)], (
        "the mark placed now carries its own placement minute, not the save's")
    assert row.expires_on == blacksmith_forge.clock_token(3, 0), (
        "the row ends at the sooner of the two, which is the new mark's own minute")

    # Ten rounds on, the printed one minute goes by and takes the new mark with it, and only it.
    _advance_to(engine, *effect_durations.parse_round(row.expires_on))
    effect_durations.sweep(engine, smith, "TEST")
    assert _marks(engine) == 2, "the save's two marks are still the ones standing"
    data = _mark_data(engine)
    assert int(data["undated"]) == 2 and "deadlines" not in data, "none of them has a minute of its own"
    assert _mark_row(engine).expires_on == "UNTIL_REMOVED", "and they are back on the expiry the save was saved with"

    # A placement after that dates itself again, and a spend retires the mark that would have gone first -- the
    # dated one -- so the save's marks are still there afterwards.
    _advance_to(engine, 14, 0)
    blacksmith_forge.set_marks(engine, smith, smith, 1, "test:place")
    assert _marks(engine) == 3 and int(_mark_data(engine)["undated"]) == 2
    blacksmith_forge.set_marks(engine, smith, smith, -1, "test:spend")
    assert _marks(engine) == 2, "spending retired the mark with a minute, not one of the save's"
    assert "deadlines" not in _mark_data(engine) and _mark_row(engine).expires_on == "UNTIL_REMOVED"
    blacksmith_forge.set_marks(engine, smith, smith, -1, "test:spend")
    blacksmith_forge.set_marks(engine, smith, smith, -1, "test:spend")
    assert _marks(engine) == 0 and _mark_row(engine) is None, "the save's own marks can still be spent"

    # And the whole shape is integers and strings, so the save format accepts it.
    canonical_bytes(engine.state.model_dump(mode="json"))


def test_a_save_with_an_earlier_own_expiry_ends_on_it_and_leaves_the_new_mark_alone():
    """The finding this round closes: a save whose row carries its own expiry that is neither ``UNTIL_REMOVED`` nor a
    round name -- here ``END_OF_TURN_AT:<smith>:<its second turn>``, the shape any turn-based name a fight made for
    itself has -- keeps that expiry, and resuming it must not move it.

    A Forge Mark row has ONE ``expires_on``, and the engine's own expiry sweep reads only that name, so the moment a
    mark was placed after resuming, the whole row was written back on that new mark's minute and the save's expiry was
    left sitting in the row's data with nothing reading it. The smith's second turn came and went, and the two marks
    the save was holding were still there to be spent, ten rounds past the turn that was supposed to end them --
    "a Forge Mark lasts for 1 minute during action scenes" is the rule that was broken, because the marks outlived
    any minute at all.

    Here the legacy expiry is the EARLIER of the two clocks, which is the direction the row being parked on the dated
    minute used to lose. The save's two marks end at the smith's second turn end; the mark placed after resuming is
    untouched and is still spendable afterwards on its own printed minute."""
    from combat import ext
    from combat.ext import blacksmith_forge, effect_durations

    engine = _engine(_bundle([]))
    smith = _smith(engine)
    assert smith.turns_started == 1, "the smith is on its first turn, so a second-turn name is genuinely ahead of it"
    engine.state.round_number, engine.state.current_slot_index = 3, 0
    saved_until = f"{effect_durations.END_AT}:{ME}:2"
    _legacy_mark_row(engine, smith, ME, 2, saved_until)
    assert _marks(engine) == 2

    # A placement after resuming: the new mark gets its own printed minute, the save's two keep the name above.
    blacksmith_forge.set_marks(engine, smith, smith, 1, "test:place")
    assert _marks(engine) == 3
    assert int(_mark_data(engine)["undated"]) == 2
    assert _mark_data(engine)["undated_until"] == saved_until, (
        "the save's own expiry is kept verbatim beside the count; it is never rewritten to a minute")
    assert [tuple(pair) for pair in _mark_data(engine)["deadlines"]] == [(3, 0)], (
        "the mark placed now carries its own placement minute")
    assert effect_durations.parse_round(_mark_row(engine).expires_on) == blacksmith_forge.deadline_of((3, 0)), (
        "the row is parked on the new mark's own minute, which is the one the engine can bring it down on")

    # The smith's second turn ends. That is the save's own expiry, and it is the earlier of the two clocks.
    engine.state.round_number, engine.state.current_slot_index = 4, 1
    smith.turns_started = 2
    engine.state.current_actor_id = ME
    ext.run("turn_end", engine, smith)
    assert _marks(engine) == 1, (
        "the save's two marks ended at the turn their own expiry named, ten rounds before the new mark's minute; "
        "they used to stay spendable until that minute came")
    data = _mark_data(engine)
    assert int(data.get("undated") or 0) == 0 and "undated_until" not in data, (
        "and they are gone from the count, with no leftover expiry to read")
    assert [tuple(pair) for pair in data["deadlines"]] == [(3, 0)], (
        "the mark placed after resuming is untouched: it is still on its own placement minute")
    assert effect_durations.parse_round(_mark_row(engine).expires_on) == blacksmith_forge.deadline_of((3, 0)), (
        "and the row still ends at that mark's own printed minute")

    # It is still a real, spendable mark: "Cost: Spend 1 Forge Mark" takes it off, and then nothing is left.
    blacksmith_forge.set_marks(engine, smith, smith, -1, "test:spend")
    assert _marks(engine) == 0 and _mark_row(engine) is None, (
        "the mark that survived the save's expiry is still spendable, and spending it ends the row")

    # And the printed minute still does its own job: a mark placed now, with nothing legacy in the row, ends on time.
    _advance_to(engine, 4, 1)
    blacksmith_forge.set_marks(engine, smith, smith, 1, "test:place")
    row = _mark_row(engine)
    assert row.expires_on == blacksmith_forge.clock_token(4, 1) and "undated_until" not in row.data
    _advance_to(engine, *effect_durations.parse_round(row.expires_on))
    ext.run("turn_start", engine, smith)
    assert _marks(engine) == 0 and _mark_row(engine) is None, "a mark placed on its own is not held past its minute"


def test_a_save_with_an_earlier_own_expiry_survives_a_real_commit_and_still_ends_on_it(tmp_path):
    """The same legacy shape through a real save, at the level the finding showed. The row is put back into what an
    older build wrote -- a count and a turn-based expiry this module cannot date -- a real button is pressed, and a
    fresh persistence object reads back what that commit left behind. The saved expiry has to come back intact, or a
    resumed fight cannot honour it at all; and it has to still fire afterwards, through a second real commit."""
    from combat.ext import blacksmith_forge, effect_durations
    from combat.gate2_runtime_models import ConditionInstance
    from combat.typed_executor import mark_condition_id

    persistence, session, match_id = _committed_smith_fight(tmp_path)
    saved_until = f"{effect_durations.END_AT}:{ME}:2"
    _legacy_mark_row_quietly(session.engine.state.actors[ME], ME, 2, saved_until)

    _press_real(session, "Hammer the Mark")                    # a real commit, on the repaired row
    placed = (int(session.engine.state.round_number), int(session.engine.state.current_slot_index))
    session = _reload(persistence, match_id)
    row = _condition(session.engine.state.actors[ME], mark_condition_id("Forge Mark", ME))
    assert int(row.data["count"]) == 3, "the save came back with all three marks"
    assert int(row.data["undated"]) == 2, "the save's two are still counted apart from the one that has a minute"
    assert row.data["undated_until"] == saved_until, (
        "and the expiry that save was saved with came back verbatim -- it was not rewritten to the new mark's minute")
    assert [tuple(pair) for pair in row.data["deadlines"]] == [placed]
    assert session.verify()["status"] == "PASS", "the save this commit wrote still verifies"

    # Play out to the end of the smith's second turn -- the save's own expiry -- through real commits only.
    _press_real(session, "End Turn")                           # the smith's first turn ends: not due yet
    _smith_turn_again(session)
    _press_real(session, "Hammer the Mark")                    # a second real commit on the same row
    placed_two = (int(session.engine.state.round_number), int(session.engine.state.current_slot_index))
    _press_real(session, "End Turn")                           # the smith's second turn ends: the save's expiry
    session = _reload(persistence, match_id)
    row = _condition(session.engine.state.actors[ME], mark_condition_id("Forge Mark", ME))
    assert int(row.data["count"]) == 2, (
        "the save's two marks ended on the turn their own expiry named; they used to survive until the new marks' "
        "minute ten rounds later")
    assert int(row.data["undated"]) == 0 and "undated_until" not in row.data, (
        "and are gone from the count, leaving no leftover expiry to read")
    assert [tuple(pair) for pair in row.data["deadlines"]] == sorted([placed, placed_two]), (
        "both marks this fight placed are still standing on their own printed minutes")
    assert session.verify()["status"] == "PASS", "that commit still verifies"

    # And the survivors are still spendable, through one more real commit on the reloaded save.
    _smith_turn_again(session)
    _press_real(session, "Set Edge")                           # "Cost: Spend 1 Forge Mark"
    session = _reload(persistence, match_id)
    row = _condition(session.engine.state.actors[ME], mark_condition_id("Forge Mark", ME))
    assert int(row.data["count"]) == 1 and len(row.data["deadlines"]) == 1, (
        "a mark that outlived the save's expiry is still a real mark to spend")
    ConditionInstance.model_validate(row.model_dump(mode="json"))


NATIVE_SAVED_EXPIRIES = [
    # (the name an older build's save carried, the boundary that name is due at, the hook that stands on it)
    ("END_OF_SOURCE_TURN_AT:2", "END_OF_TURN", "turn_end"),
    ("END_OF_HOLDER_NEXT_TURN", "END_OF_TURN", "turn_end"),
    ("START_OF_SOURCE_NEXT_TURN", "START_OF_TURN", "turn_start"),
]


@pytest.mark.parametrize("saved_until,checkpoint,hook_name", NATIVE_SAVED_EXPIRIES,
                         ids=[name for name, _, _ in NATIVE_SAVED_EXPIRIES])
def test_a_save_carrying_the_engines_own_turn_name_ends_on_it_and_leaves_the_new_mark_alone(
        saved_until, checkpoint, hook_name):
    """The rest of the finding this round closes: a save whose row carries one of the expiry names the SEALED engine
    removes for itself keeps that expiry too, and resuming it must not move it.

    ``END_OF_SOURCE_TURN_AT:2``, ``END_OF_HOLDER_NEXT_TURN`` and ``START_OF_SOURCE_NEXT_TURN`` are the engine's own
    three turn names (gate2_engine._expire_typed_for_checkpoint); they are what any build that dated a mark by a turn
    rather than by the table's round clock stores. The reader this row's saved expiry is handed to recognised only the
    round and turn-counter names written by ``effect_durations``, and answered False for all three of these, so the save's
    marks sat in ``undated_until`` with nothing reading them: the smith's second turn came and went and they were still
    there to be spent, ten rounds past the turn that was supposed to end them. "a Forge Mark lasts for 1 minute during
    action scenes" is the rule that was broken, because the marks outlived any minute at all.

    Each name is due at the boundary the ENGINE brings it down at, which is the point: ``START_OF_SOURCE_NEXT_TURN`` only
    at a turn start, the other two only at the turn end of the creature each is filed under. So the mark placed after
    resuming is left alone and keeps the full minute it was just given."""
    from combat import ext
    from combat.ext import blacksmith_forge, effect_durations

    engine = _engine(_bundle([]))
    smith = _smith(engine)
    engine.state.round_number, engine.state.current_slot_index = 3, 0
    _legacy_mark_row(engine, smith, ME, 2, saved_until)
    assert _marks(engine) == 2

    # A placement after resuming: the new mark gets its own printed minute, the save's two keep the name above.
    blacksmith_forge.set_marks(engine, smith, smith, 1, "test:place")
    assert _marks(engine) == 3
    assert _mark_data(engine)["undated_until"] == saved_until, (
        "the save's own expiry is kept verbatim beside the count; it is never rewritten to a minute")
    assert effect_durations.parse_round(_mark_row(engine).expires_on) == blacksmith_forge.deadline_of((3, 0)), (
        "the row is parked on the new mark's own minute, which is the one the engine can bring it down on")

    # The boundary that name names, and the seam agrees with the engine about it being due there.
    engine.state.round_number, engine.state.current_slot_index = 4, 1
    smith.turns_started = 2
    engine.state.current_actor_id = ME
    assert effect_durations.engine_due(engine, saved_until, checkpoint, source_id=ME, holder_id=ME), (
        "the saved name is due at the boundary it names")

    ext.run(hook_name, engine, smith)
    assert _marks(engine) == 1, (
        "the save's two marks ended on the turn their own expiry named, ten rounds before the new mark's minute; "
        "they used to stay spendable until that minute came")
    data = _mark_data(engine)
    assert int(data.get("undated") or 0) == 0 and "undated_until" not in data, (
        "and they are gone from the count, with no leftover expiry to read")
    assert [tuple(pair) for pair in data["deadlines"]] == [(3, 0)], (
        "the mark placed after resuming is untouched: it is still on its own placement minute")

    # It is still a real, spendable mark: "Cost: Spend 1 Forge Mark" takes it off, and then nothing is left.
    blacksmith_forge.set_marks(engine, smith, smith, -1, "test:spend")
    assert _marks(engine) == 0 and _mark_row(engine) is None, (
        "the mark that survived the save's expiry is still spendable, and spending it ends the row")


def test_a_save_carrying_the_engines_own_turn_name_survives_a_real_commit_and_still_ends_on_it(tmp_path):
    """The same native shape through a real save, at the level the finding showed. The row is put back into what an
    older build wrote -- a count and one of the sealed engine's own turn-based expiries -- a real button is pressed, and a
    fresh persistence object reads back what that commit left behind. The saved expiry has to come back intact, or a
    resumed fight cannot honour it at all; and it has to still fire afterwards, through a second real commit, when the
    engine only ever sees the new mark's minute."""
    from combat.ext import blacksmith_forge
    from combat.gate2_runtime_models import ConditionInstance
    from combat.typed_executor import mark_condition_id

    persistence, session, match_id = _committed_smith_fight(tmp_path)
    saved_until = "END_OF_SOURCE_TURN_AT:2"          # the end of the smith's second turn
    _legacy_mark_row_quietly(session.engine.state.actors[ME], ME, 2, saved_until)

    _press_real(session, "Hammer the Mark")                    # a real commit, on the repaired row
    placed = (int(session.engine.state.round_number), int(session.engine.state.current_slot_index))
    session = _reload(persistence, match_id)
    row = _condition(session.engine.state.actors[ME], mark_condition_id("Forge Mark", ME))
    assert int(row.data["count"]) == 3, "the save came back with all three marks"
    assert int(row.data["undated"]) == 2, "the save's two are still counted apart from the one that has a minute"
    assert row.data["undated_until"] == saved_until, (
        "and the expiry that save was saved with came back verbatim -- it was not rewritten to the new mark's minute")
    assert [tuple(pair) for pair in row.data["deadlines"]] == [placed]
    assert session.verify()["status"] == "PASS", "the save this commit wrote still verifies"

    # Play out to the end of the smith's second turn -- the save's own expiry -- through real commits only.
    _press_real(session, "End Turn")                           # the smith's first turn ends: not due yet
    _smith_turn_again(session)
    _press_real(session, "Hammer the Mark")                    # a second real commit on the same row
    placed_two = (int(session.engine.state.round_number), int(session.engine.state.current_slot_index))
    _press_real(session, "End Turn")                           # the smith's second turn ends: the save's expiry
    session = _reload(persistence, match_id)
    row = _condition(session.engine.state.actors[ME], mark_condition_id("Forge Mark", ME))
    assert int(row.data["count"]) == 2, (
        "the save's two marks ended on the turn their own expiry named; they used to survive until the new marks' "
        "minute ten rounds later")
    assert int(row.data["undated"]) == 0 and "undated_until" not in row.data, (
        "and are gone from the count, leaving no leftover expiry to read")
    assert [tuple(pair) for pair in row.data["deadlines"]] == sorted([placed, placed_two]), (
        "both marks this fight placed are still standing on their own printed minutes")
    assert session.verify()["status"] == "PASS", "that commit still verifies"

    # And the survivors are still spendable, through one more real commit on the reloaded save.
    _smith_turn_again(session)
    _press_real(session, "Set Edge")                           # "Cost: Spend 1 Forge Mark"
    session = _reload(persistence, match_id)
    row = _condition(session.engine.state.actors[ME], mark_condition_id("Forge Mark", ME))
    assert int(row.data["count"]) == 1 and len(row.data["deadlines"]) == 1, (
        "a mark that outlived the save's expiry is still a real mark to spend")
    ConditionInstance.model_validate(row.model_dump(mode="json"))


_NATIVE_NAMES = ("START_OF_SOURCE_NEXT_TURN", "END_OF_HOLDER_NEXT_TURN", "END_OF_SOURCE_TURN_AT:2", "END_OF_SOURCE_TURN_AT:3")
_EXTENSION_NAMES = ("START_OF_TURN_AT:actor:2", "END_OF_TURN_AT:actor:2", "START_OF_SLOT_AT:4:1", "UNTIL_REMOVED", "", "nonsense")


def _sealed_engine_removes(engine, name, *, source_id, holder_id, checkpoint, actor_id):
    """Whether the SEALED engine's own typed-expiry routine actually removes a row carrying ``name``.

    This is the oracle the differential test compares against, and it is the engine's routine itself --
    ``Gate2Engine._expire_typed_for_checkpoint``, the same call ``_expire_for_checkpoint`` makes at
    ``gate2_engine.py:3634`` from all three of its turn boundaries. One probe row is written onto the holder's
    conditions with the name, the two ids and nothing else in its data (no ``burn``, no ``repeat_save``, no
    ``reach_ft``, so none of that routine's other branches can touch it), the routine runs, and the answer is
    whether the row is still there afterwards. Nothing is re-stated from the source: if the engine's clauses change,
    this follows them.
    """
    from combat.gate2_runtime_models import ConditionInstance

    holder = engine.state.actors[holder_id]
    probe_id = "condition-instance:condition:auto17.native_probe:1"
    holder.conditions[probe_id] = ConditionInstance(
        instance_id=probe_id, condition_id="condition:auto17.native_probe",
        source_definition_id="BLACKSMITH_BASE_HAMMER_THE_MARK", source_actor_id=source_id,
        target_id=holder_id, applied_sequence=1, expires_on=name, data={"label": "probe"})
    try:
        engine._expire_typed_for_checkpoint(checkpoint, actor_id)
        return probe_id not in holder.conditions
    finally:
        holder.conditions.pop(probe_id, None)          # isolated: the next case starts from the same state


def test_the_engines_own_turn_names_are_read_exactly_as_the_sealed_engine_reads_them():
    """The shared reader has to agree with the engine it stands in for, clause for clause, or the names it claims to
    honour are honoured on the engine's schedule rather than the one they were saved with.

    The oracle is the sealed engine's own removal routine run on isolated state (:func:`_sealed_engine_removes`), not a
    copy of its clauses, and the comparison is STRICT: the reader's answer has to equal what the engine did, in both
    directions, at both of the boundaries each name could be read at, for every pairing of the stored row's two ids.
    There is no "unless the reader said no" escape hatch -- a regression that answered False for a name the engine
    really does remove is the exact failure this lane repairs (the save's marks outliving the turn their own expiry
    named), and it has to fail here too.

    ``END_OF_SOURCE_TURN_AT:<n>`` is also swept across the applier's real turn counter, since that number is the only
    clause with a comparison in it: the same name is due at the end of the applier's Nth turn and not before it."""
    from combat.ext import effect_durations

    engine = _engine(_bundle([]))
    smith = _smith(engine)
    engine.state.round_number, engine.state.current_slot_index = 4, 1
    other = next(a for a in engine.state.actors.values() if a.entity_id != ME)
    checked = 0

    def compare(name, source_id, holder_id, checkpoint):
        """The reader against the engine, strictly, at one boundary."""
        nonlocal checked
        engine.state.current_actor_id = ME          # what both engine boundaries name (see the real-boundary check below)
        mine = effect_durations.native_due(engine, name, checkpoint, source_id=source_id, holder_id=holder_id)
        theirs = _sealed_engine_removes(engine, name, source_id=source_id, holder_id=holder_id,
                                        checkpoint=checkpoint, actor_id=ME)
        assert mine == theirs, (
            f"the reader says the engine would {'' if mine else 'not '}remove {name!r} at {checkpoint} "
            f"(source={source_id}, holder={holder_id}, turns_started={smith.turns_started}); "
            f"the engine's own routine actually removes it: {theirs}")
        checked += 1

    # The engine's own family, every name x both boundaries x every pairing of the stored row's two ids. A pair with a
    # missing id cannot be compared against a row the engine files on a creature, so it is checked on the reader's own
    # side below: a name waiting for a creature that is not in the fight can never come down.
    for name in _NATIVE_NAMES:
        for source_id, holder_id in ((ME, ME), (ME, other.entity_id), (other.entity_id, ME),
                                     (other.entity_id, other.entity_id)):
            for checkpoint in ("END_OF_TURN", "START_OF_TURN"):
                smith.turns_started = 2
                compare(name, source_id, holder_id, checkpoint)

    # END_OF_SOURCE_TURN_AT:<n>'s own comparison: the applier's turn counter against the name's number.
    for turns_started in (0, 1, 2, 3, 4):
        for name in ("END_OF_SOURCE_TURN_AT:2", "END_OF_SOURCE_TURN_AT:3"):
            for checkpoint in ("END_OF_TURN", "START_OF_TURN"):
                smith.turns_started = turns_started
                compare(name, ME, ME, checkpoint)

    # A boundary a caller could pass that names neither of the engine's two: inert, on the reader's side and against
    # the engine's own routine. (A boundary with no creature at it cannot be staged: MatchState.current_actor_id is a
    # required string, so the reader's `current is None` guard is unreachable through a real fight.)
    for name in _NATIVE_NAMES:
        for checkpoint in ("AT_TURN_START", "TURN_START", "MID_TURN", ""):
            compare(name, ME, ME, checkpoint)
    assert checked >= 60, f"the differential only ran {checked} comparisons"

    # A name in neither family is not the ENGINE's to remove, checked separately from the three above: the round and
    # turn-counter names are effect_durations' own sweep's business and "nonsense" is nobody's.
    for name in _EXTENSION_NAMES:
        for source_id, holder_id in ((ME, ME), (ME, other.entity_id), (other.entity_id, ME)):
            for checkpoint in ("END_OF_TURN", "START_OF_TURN"):
                compare(name, source_id, holder_id, checkpoint)

    # The id each clause compares, and the one boundary each is due at, rather than both ids at both boundaries:
    # START_OF_SOURCE_NEXT_TURN and END_OF_SOURCE_TURN_AT:<n> are filed under the applier, END_OF_HOLDER_NEXT_TURN under
    # the affected creature, and the two "source" names are due at different ends of the turn. A name is due exactly when
    # ITS OWN id is the creature at ITS OWN boundary. Replacing that id with a creature this fight does not have, or
    # with no id at all, ends it. The id the clause does not read is left out entirely below: the reader must not demand
    # it, or a Forge Mark row would be read differently from the row the engine files.
    smith.turns_started = 4
    for name, its_id, due_at in (("START_OF_SOURCE_NEXT_TURN", "source", "START_OF_TURN"),
                                 ("END_OF_HOLDER_NEXT_TURN", "holder", "END_OF_TURN"),
                                 ("END_OF_SOURCE_TURN_AT:2", "source", "END_OF_TURN"),
                                 ("END_OF_SOURCE_TURN_AT:3", "source", "END_OF_TURN")):
        for absent in (None, "actor:nobody", other.entity_id):
            for checkpoint in ("END_OF_TURN", "START_OF_TURN"):
                assert not effect_durations.native_due(
                    engine, name, checkpoint,
                    source_id=absent if its_id == "source" else ME,
                    holder_id=absent if its_id == "holder" else ME), (
                    f"{name!r} waits on {its_id}={absent!r}, which is not the creature at this boundary, "
                    "so neither the reader nor the engine removes it")
        # And the id that clause does not read is genuinely not required: the name is still due without it.
        assert effect_durations.native_due(
            engine, name, due_at,
            source_id=None if its_id == "holder" else ME,
            holder_id=None if its_id == "source" else ME) is True, (
            f"{name!r} is due at {due_at} on its own clause's id alone; it does not also need the other one")

    # The reader's checkpoint and creature are the engine's own, checked on the routine the engine itself calls rather
    # than on a copy of its clauses: a turn start removes the applier's name and nothing else, and a turn end never does.
    assert _sealed_engine_removes(engine, "START_OF_SOURCE_NEXT_TURN", source_id=ME, holder_id=ME,
                                  checkpoint="START_OF_TURN", actor_id=ME) is True
    assert _sealed_engine_removes(engine, "END_OF_HOLDER_NEXT_TURN", source_id=ME, holder_id=ME,
                                  checkpoint="END_OF_TURN", actor_id=ME) is True
    assert _sealed_engine_removes(engine, "START_OF_SOURCE_NEXT_TURN", source_id=ME, holder_id=ME,
                                  checkpoint="END_OF_TURN", actor_id=ME) is False, (
        "the engine removes START_OF_SOURCE_NEXT_TURN at a turn START only, and never at a turn end")


def test_a_name_no_family_recognises_is_never_due_and_a_fight_without_a_smith_is_untouched():
    """Inert by default: the reader is asked about a name on every turn boundary, so a name outside both families has
    to read False, a save parked on ``UNTIL_REMOVED`` has to keep standing, and a fight with no Forge Mark row in it has
    to cost the boundary nothing at all.

    The no-smith half is now a fight with genuinely no smith in it (two fighters, neither carrying the Blacksmith
    sphere) driven through BOTH registered hooks, so it measures what the hooks do to a table they have no business
    touching rather than re-checking a name. It asserts that no condition anywhere in the fight is removed and that the
    hooks write no events, which is the "no global behaviour change for other characters" claim at hook level. Then a
    smith-less row carrying an ``undated`` count is dropped in on a fighter to confirm the retirement path is gated on
    the Forge Mark row's own condition id and not merely on a count being present."""
    from combat.ext import blacksmith_forge, effect_durations

    engine = _engine(_bundle([]))
    smith = _smith(engine)
    engine.state.round_number, engine.state.current_slot_index = 4, 1
    smith.turns_started = 2
    engine.state.current_actor_id = ME

    for name in ("UNTIL_REMOVED", "", "SOMEONE_ELSES_CLOCK", "END_OF_TURN_AT:actor:99",
                 # Names carrying the engine's native PREFIX that no writer here produces. Measured against the engine's
                 # own routine (probe recorded in the report): on "END_OF_SOURCE_TURN_AT:" and ":soon" the engine raises
                 # ValueError out of int(), while on ":-1", ":+2" and ":2:3" it removes the row. The reader answers False
                 # for all of them and never raises, so a hand-edited or corrupt save cannot retire marks or break a
                 # turn through this seam. These are deliberately NOT in the differential below, which is the engine's
                 # family as the engine writes it.
                 "END_OF_SOURCE_TURN_AT:", "END_OF_SOURCE_TURN_AT:soon", "END_OF_SOURCE_TURN_AT:-1"):
        assert not effect_durations.engine_due(engine, name, "END_OF_TURN", source_id=ME, holder_id=ME), (
            f"{name!r} names no boundary this build removes, so it is not due")
        assert not effect_durations.native_due(engine, name, "END_OF_TURN", source_id=ME, holder_id=ME)

    # A save whose row is parked on the name it was saved with, and nothing else, keeps standing across both edges.
    _legacy_mark_row(engine, smith, ME, 2, "UNTIL_REMOVED")
    for hook_name in ("turn_start", "turn_end"):
        blacksmith_forge.retire_saved_forge_mark_expiries(
            engine, "START_OF_TURN" if hook_name == "turn_start" else "END_OF_TURN", ME)
    assert _marks(engine) == 2 and _mark_row(engine).expires_on == "UNTIL_REMOVED", (
        "a row saved on UNTIL_REMOVED keeps the marks a player already paid for, on the save's own terms")

    # ---- the no-smith control: a real fight with no Blacksmith in it, through both registered hooks -------------
    from combat.ext import run as ext_run

    def _smithless_fight():
        """Two fighters, neither carrying the Blacksmith sphere: a table this plug-in has no business changing."""
        return Gate4ControllerEngine(ROOT, match_seed="AUTO17-NO-SMITH",
                                     typed_bundles=(_ally_bundle(), _rival_bundle()),
                                     roster_setup={"primary_actor_ids": [ALLY, AN],
                                                   "team_by_actor": {ALLY: "team:a", AN: "team:b"},
                                                   "starting_positions": {ALLY: {"x": 4, "y": 5},
                                                                          AN: {"x": 4, "y": 6}}})

    quiet = _smithless_fight()
    fighter = quiet.state.actors[ALLY]
    fighter.turns_started = 2
    quiet.state.round_number, quiet.state.current_slot_index = 4, 1
    # An unrelated condition of the sort any other plug-in might store: not a Forge Mark row, not owned by a smith.
    quiet._apply_condition(fighter, "condition:auto17.unrelated", "SOME_OTHER_ABILITY", ME,
                           expires_on="END_OF_HOLDER_NEXT_TURN",
                           data={"undated": 3, "undated_until": "END_OF_HOLDER_NEXT_TURN", "label": "Unrelated"})
    unrelated = _condition(fighter, "condition:auto17.unrelated")
    assert unrelated is not None
    quiet.state.current_actor_id = ALLY

    # Both boundaries, each firing its own registered hook, at a name the ENGINE's own routine would otherwise remove
    # (an END_OF_HOLDER_NEXT_TURN on the fighter whose turn it is) -- so this also proves the hook is not merely
    # shadowing a removal the engine makes anyway, but is itself removing nothing on a row it does not own.
    before = {a.entity_id: dict(a.conditions) for a in quiet.state.actors.values()}
    events_before = len(quiet.events)
    for hook_name in ("turn_start", "turn_end"):
        ext_run(hook_name, quiet, fighter)
    after = {a.entity_id: dict(a.conditions) for a in quiet.state.actors.values()}
    assert after == before, (
        "a fight with no smith in it comes out of both turn boundaries with every condition exactly as it went in")
    assert len(quiet.events) == events_before, (
        "and the boundary writes no events of its own for a fight it has no business changing")

    # Even a row carrying an undated Forge-Mark-shaped count is left alone, because it is not a Forge Mark row: the
    # gate is the row's condition id, not the presence of the field. A Forge Mark condition id is namespaced per owner,
    # so no fighter's unrelated row can present one.
    assert _condition(fighter, "condition:auto17.unrelated") is not None
    assert unrelated.data.get("undated") == 3, "an unrelated row's own data is read but never written"


def _legacy_mark_row_quietly(subject, owner_id, count, expires_on):
    """The Forge Mark row exactly as an older build's save held it, put onto a live engine's state without recording
    an event of its own.

    ``_apply_condition`` would append a CONDITION_APPLIED that no journal record backs, and the next real commit would
    then carry an event sequence the committed journal cannot replay -- ``Gate3EventReducer`` refuses the gap. This
    writes the stored condition itself, which is what that save's state held; the button pressed afterwards is a real
    commit, and it is that commit's own record which carries the repaired row back out.
    """
    from combat.gate2_runtime_models import ConditionInstance
    from combat.typed_executor import mark_condition_id

    condition_id = mark_condition_id("Forge Mark", owner_id)
    subject.conditions = {iid: row for iid, row in subject.conditions.items() if row.condition_id != condition_id}
    subject.conditions[f"condition-instance:{condition_id}:{owner_id}:1"] = ConditionInstance(
        instance_id=f"condition-instance:{condition_id}:{owner_id}:1", condition_id=condition_id,
        source_definition_id="BLACKSMITH_BASE_HAMMER_THE_MARK", source_actor_id=owner_id, target_id=subject.entity_id,
        applied_sequence=1, expires_on=expires_on,
        data={"count": count, "label": f"Forge Mark{'s' if count > 1 else ''} ({count} of 4)"})


def _committed_smith_fight(tmp_path):
    """A real saved fight with a real Forge Mark row in it, through the real persistence layer (the same
    ``create_match`` / ``submit_intent`` / ``load_match`` path the service itself uses), with the smith's turn."""
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="AUTO17R3F1-UNDATED",
                                       typed_bundles=(_bundle([REVISION]), _rival_bundle()),
                                       roster_setup={"primary_actor_ids": [ME, AN],
                                                     "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6},
                                                                            AN: {"x": 4, "y": 6}}})
    return persistence, session, session.match_id


def _rival_bundle():
    """A second compiled fighter on the other side, keyed off a different ability, so a printed number that has to
    come from the smith cannot be read off the rival by accident."""
    return compile_character(_sheet([], spheres=(), pb=2, key="STR", key_mod=5), actor_id=AN)


def _press_real(session, label):
    """Press one real table button through the real commit path, the way ``TabletopService`` does."""
    from combat.gate2_runtime_models import ActionIntent

    candidate = next(c for c in session.engine.legal_candidates()
                     if c.display_name == label or (label == "End Turn" and c.kind.value == "END_TURN"))
    session.submit_intent(ActionIntent(intent_id=f"auto17r3f1:{label}:{session.engine.state.state_version}",
                                       actor_id=candidate.actor_id, decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       target_ids=candidate.target_ids, destination=candidate.destination),
                          primary_decision_record=None, reaction_provider=None)


def _reload(persistence, match_id):
    """Reopen the fight through a fresh persistence object over the same folder, the way the next service run does."""
    from combat.gate4_persistence import Gate4Persistence

    return Gate4Persistence(ROOT, persistence.userdata_root).load_match(match_id)


def _smith_turn_again(session):
    """End every turn until the smith is the one deciding again, so a second placement can be pressed."""
    while session.engine.state.current_actor_id != ME:
        _press_real(session, "End Turn")


def test_the_repaired_mark_row_survives_a_real_commit_and_a_reload(tmp_path):
    """The same historical shape through a real save: the row is put back into what an older build wrote, a real
    button is pressed, and the row that commit left behind is read back by a fresh persistence object. The engine's
    own re-read is what makes this worth having -- the earlier test only ever checked the in-memory model and then
    verified the *untouched* committed fight."""
    from combat.ext import blacksmith_forge
    from combat.gate2_runtime_models import ConditionInstance
    from combat.typed_executor import mark_condition_id

    persistence, session, match_id = _committed_smith_fight(tmp_path)
    _legacy_mark_row_quietly(session.engine.state.actors[ME], ME, 2, "UNTIL_REMOVED")

    _press_real(session, "Hammer the Mark")                    # a real commit, on the repaired row
    placed = (int(session.engine.state.round_number), int(session.engine.state.current_slot_index))
    session = _reload(persistence, match_id)
    row = _condition(session.engine.state.actors[ME], mark_condition_id("Forge Mark", ME))
    assert int(row.data["count"]) == 3, "the save came back with all three marks"
    assert int(row.data["undated"]) == 2, "and with the save's two counted apart from the one that has a minute"
    assert [tuple(pair) for pair in row.data["deadlines"]] == [placed], (
        "the mark placed after resuming came back with its own minute")
    assert row.expires_on == blacksmith_forge.clock_token(*placed), "and the row ends at that mark's own minute"
    assert session.verify()["status"] == "PASS", "the save this commit wrote still verifies"

    # The next turn: another placement, then a spend on a turn of its own ("Set Edge" and "Hammer the Mark" are
    # both Bonus Actions), each one a real commit read back by a fresh load.
    _press_real(session, "End Turn")
    _smith_turn_again(session)
    _press_real(session, "Hammer the Mark")
    session = _reload(persistence, match_id)
    row = _condition(session.engine.state.actors[ME], mark_condition_id("Forge Mark", ME))
    assert int(row.data["count"]) == 4 and int(row.data["undated"]) == 2, "the printed limit, the save's two apart"
    assert len(row.data["deadlines"]) == 2, "and both marks this fight placed have a minute each"

    _press_real(session, "End Turn")
    _smith_turn_again(session)
    _press_real(session, "Set Edge")                            # "Cost: Spend 1 Forge Mark"
    session = _reload(persistence, match_id)
    row = _condition(session.engine.state.actors[ME], mark_condition_id("Forge Mark", ME))
    assert int(row.data["count"]) == 3 and int(row.data["undated"]) == 2, (
        "the spend retired the mark with a minute; the save's two are untouched")
    assert len(row.data["deadlines"]) == 1
    ConditionInstance.model_validate(row.model_dump(mode="json"))


def test_the_built_in_ai_is_never_offered_the_declaration_and_declares_nothing():
    """The AI decision for this printed choice, stated instead of left to the harness: the built-in AI is not the
    smith and cannot know what its fighter forged today, so it never declares and the printed condition simply does
    not hold. A player -- manual control or "Ask me" -- sets the answer on either button."""
    from combat.ext import blacksmith_forge, setting_choices
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary

    assert blacksmith_forge.AI_DECLARES_PERSONAL_WORK is False
    engine = _engine(_bundle([REVISION]))
    smith = _smith(engine)
    for action in engine.action_catalog.values():
        if ".seven_hammer.personal_work" in action.source_definition_id:
            assert action.parameters.get("player_only") is True, "an AI pilot's own menu keeps it; the built-in AI's does not"
    policy, _ = PolicyLibrary(ROOT).for_actor(ME)
    # The two menus the service really builds (gate5_service: the player's with include_item_actions, the built-in
    # AI's with for_ai). A player_only setting is the documented way to stay out of the built-in AI's list.
    ai_menu = {c.display_name for c in build_decision_context(engine, policy, for_ai=True).legal_candidates}
    player_menu = {c.display_name for c in
                   build_decision_context(engine, policy, include_item_actions=True).legal_candidates}
    assert not [name for name in ai_menu if "personally forged" in name or "personal-work" in name], ai_menu
    assert any("personally forged" in name for name in player_menu), "the player's own menu keeps the printed choice"
    setting_choices.install_ai_setting_defaults(engine, smith)
    assert not blacksmith_forge.personal_work(smith), "the shared AI-setting seam has no default for this choice"


def test_a_revision_of_an_allies_strike_answers_quench_in_breath_for_the_smith():
    """Quench in Breath is the smith's printed answer to spending their own Forge Mark: "When YOU spend a Forge Mark
    ... reduce the next Fire, Cold, Lightning, or Acid damage YOU take ... by YOUR Proficiency Bonus". A smith that
    revises an ally's strike within 30 feet spends its mark, and before the announcement carried the ally's context,
    so it asked the ally whether the ally owned the talent and priced the reduction with the ally's Proficiency
    Bonus -- the smith's own answer was missing, or answered on the wrong creature."""
    from combat.typed_executor import run_effects

    engine = _engine(_bundle([QUENCH_BREATH, REVISION]))
    smith, ally = _smith(engine), engine.state.actors[ALLY]
    _use(engine, "Hammer the Mark", times=2)
    run_effects(_strike_ctx(engine, actor_id=ALLY), _STRIKE_DAMAGE)
    assert _reroll(engine), "the ally's strike was revised by the smith"
    assert _holds(smith, "condition:typed.quench_in_breath"), "the smith who spent the mark gets the printed answer"
    assert not _holds(ally, "condition:typed.quench_in_breath"), "the ally is not the smith who spent the mark"
    assert int(_condition(smith, "condition:typed.quench_in_breath").data["pb"]) == smith.proficiency_bonus == 4, (
        "the smith's own Proficiency Bonus, not the ally's")
    engine._commit_damage(smith, 30, "LIGHTNING", "test:storm", AN, None, reaction_depth=0)
    assert smith.current_hp == 60 - 30 + 4


def _labels(engine):
    return {c.display_name for c in engine.legal_candidates()}


def _reroll(engine, *, since=0):
    """The damage rerolls recorded for one revision (each is its own recorded roll, so a replay draws the same dice)."""
    return [event for event in engine.events[since:] if event.event_type == "DAMAGE_ROLLED"
            and event.payload.get("rerolled_dice")]


# --------------------------------------------------------------------------------- Forge-Fitted Armor / Weapon
def test_fit_armors_reduce_option_actually_reduces_weapon_damage():
    """Fit Armor: "the wearer reduces the next Bludgeoning, Piercing, or Slashing damage taken before the start of
    your next turn by your Proficiency Bonus". Before, this option was a literal {"type": "rider"} effect."""
    engine = _engine(_bundle([FITTED_ARMOR]), ally=True)
    smith = _smith(engine)
    _use(engine, "Hammer the Mark", times=2)
    _use(engine, "Fit Armor: Reduce Weapon Damage")
    from combat.ext.ironclad_blacksmith import armor_temper

    assert armor_temper(smith).data["benefit"] == "armor_reduce"
    engine._commit_damage(smith, 30, "SLASHING", "test:slash", ALLY, None, reaction_depth=0)
    assert smith.current_hp == 60 - 30 + 4


def test_fit_armors_forced_movement_option_ignores_five_feet():
    engine = _engine(_bundle([FITTED_ARMOR]))
    _use(engine, "Hammer the Mark", times=2)
    _use(engine, "Fit Armor: Ignore Forced Movement")
    from combat import ext

    assert 5 in list(ext.run("forced_movement_reduction", _context(engine), _smith(engine)))


def test_the_forge_fitted_weapon_bonus_is_applied_while_the_temper_stands():
    engine = _engine(_bundle([FITTED_WEAPON]))
    smith = _smith(engine)
    _use(engine, "Hammer the Mark", times=2)
    _use(engine, "Forge-Fitted Weapon: +1 to damage rolls")
    _use(engine, "Set Edge")
    from combat import ext

    temper = _condition(smith, "condition:typed.blacksmith_temporary_temper")
    assert temper is not None, "Set Edge places the Temporary Temper while Forge-Fitted Weapon is owned"
    assert temper.data["benefit"] == "damage", "the temper carries the benefit the fighter chose"
    assert 1 in list(ext.run("attack_damage_bonus", _context(engine), engine.state.actors[AN], {}))


def test_a_character_without_the_blacksmith_records_is_untouched():
    """Inert by default: a fighter with no Blacksmith record gains no Forge Mark, no Temporary Temper and no new
    button from this module."""
    engine = _engine(_bundle([], spheres=()))
    legal = {c.display_name for c in engine.legal_candidates()}
    assert not [name for name in legal if "Forge" in name or "Tempering Sequence" in name or "Field Repair" in name]
    assert _marks(engine) == 0


# ------------------------------------------------------------------------------- persistence through the real table
def test_the_forge_marks_and_the_chosen_revision_survive_a_table_commit_and_reload(tmp_path):
    """Everything this module stores in fight state -- the counted Forge Mark, the round its one-minute clock started
    on, and the fighter's own "personally forged or prepared" answer -- goes through a real table transaction and a
    fresh service, on the same saved-fight path a player resumes from. The stored values are integers and strings
    only, so the state stays JSON-canonical."""
    import json
    import zipfile

    from combat.canonical import canonical_bytes
    from combat.ext import effect_durations
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from combat.typed_executor import mark_condition_id

    for side in ("smith", "rival"):
        folder = tmp_path / "portable_characters" / side
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(_sheet([REVISION, QUENCH_BREATH])))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "Lock2 yard", "width_squares": 12, "height_squares": 8,
                               "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    smith_id = FACTORY_ACTOR_PREFIX + "smith"
    view = combat.create_factory_match(project_ids=["smith"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "rival"],
                                       control_modes={smith_id: "MANUAL", FACTORY_ACTOR_PREFIX + "rival": "MANUAL"},
                                       arena_id="battlefield:map.lock2-yard", match_seed="AUTO17F1-MARKS")
    table, match_id = TabletopService(combat, tmp_path), view["match_id"]
    for label, count in (("Hammer the Mark", 2), ("Seven-Hammer Revision: workpiece personally forged or prepared today", 1)):
        for _ in range(count):
            assert _press(table, match_id, smith_id, label)["status"] == "COMMITTED", label

    fresh = CombatService(ROOT, tmp_path)  # a fresh service reads the fight back off disk
    state = fresh._load_session(match_id).engine.state
    canonical_bytes(state.model_dump(mode="json"))
    actor = state.actors[smith_id]
    row = _condition(actor, mark_condition_id("Forge Mark", smith_id))
    assert row is not None, "the Forge Mark is the smith's own workpiece mark"
    assert int(row.data["count"]) == 2
    assert row.data["label"] == "Forge Marks (2 of 4)"
    assert all(type(row.data[key]) is int for key in ("count", "since_round", "since_slot"))
    clock = effect_durations.parse_round(row.expires_on)
    assert clock is not None, "the printed one-minute clock came back"
    assert clock[0] == int(row.data["since_round"]) + 10, "the count ends one minute after the mark that started it"
    assert _holds(actor, "condition:typed.seven_hammer_personal_work")


def test_the_per_mark_deadlines_and_the_ended_declaration_survive_a_table_commit_and_reload(tmp_path):
    """The per-mark deadlines and the reversible declaration go through a real table transaction and a fresh service,
    on the same saved-fight path a player resumes from: one deadline per mark, all of them integers, the instance
    expiring at the soonest, and the second button's answer (no declaration) still standing after the reload."""
    import json
    import zipfile

    from combat.canonical import canonical_bytes
    from combat.ext import blacksmith_forge, effect_durations
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.gate2_runtime_models import ConditionInstance
    from combat.tabletop_service import TabletopService
    from combat.typed_executor import mark_condition_id

    for side in ("smith", "rival"):
        folder = tmp_path / "portable_characters" / side
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(_sheet([REVISION])))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "Lock2 yard", "width_squares": 12, "height_squares": 8,
                               "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    smith_id = FACTORY_ACTOR_PREFIX + "smith"
    view = combat.create_factory_match(project_ids=["smith"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "rival"],
                                       control_modes={smith_id: "MANUAL", FACTORY_ACTOR_PREFIX + "rival": "MANUAL"},
                                       arena_id="battlefield:map.lock2-yard", match_seed="AUTO17R1F1-DEADLINES")
    table, match_id = TabletopService(combat, tmp_path), view["match_id"]
    for label, count in (("Hammer the Mark", 3),
                         ("Seven-Hammer Revision: workpiece personally forged or prepared today", 1),
                         ("Seven-Hammer Revision: end the personal-work declaration", 1)):
        for _ in range(count):
            assert _press(table, match_id, smith_id, label)["status"] == "COMMITTED", label

    fresh = CombatService(ROOT, tmp_path)  # a fresh service reads the fight back off disk
    state = fresh._load_session(match_id).engine.state
    canonical_bytes(state.model_dump(mode="json"))
    actor = state.actors[smith_id]
    row = _condition(actor, mark_condition_id("Forge Mark", smith_id))
    deadlines = [tuple(pair) for pair in row.data["deadlines"]]
    assert len(deadlines) == 3 and deadlines == sorted(deadlines), "one deadline per mark, oldest first"
    assert all(type(part) is int for pair in row.data["deadlines"] for part in pair), "integers only"
    assert effect_durations.parse_round(row.expires_on) == blacksmith_forge.deadline_of(deadlines[0]), (
        "the instance expires at its soonest mark's own minute")
    assert not _holds(actor, "condition:typed.seven_hammer_personal_work"), "the declaration really was ended"

    # The row auto17f1 would have saved, rebuilt from what came back: one deadline for the whole count. That save's
    # marks genuinely shared one minute then, and the reader hands it back to every one of them, so a fight saved
    # before this change still ends on the round it was saved to end on.
    legacy = row.model_dump(mode="json")
    legacy["data"].pop("deadlines")
    saved = ConditionInstance.model_validate(legacy)
    assert saved.expires_on == row.expires_on
    assert blacksmith_forge.stored_deadlines(saved.data) == [deadlines[0]] * 3, (
        "the saved count keeps the single minute it was saved with, for every mark in it")
    assert blacksmith_forge.clock_token(*deadlines[0]) == saved.expires_on


def _press(table, match_id, actor_id, label, *, limit=8):
    """Press one real table button by its printed label, ending the other creatures' turns to reach ``actor_id``."""
    from tests.iron_fist_support import answering_iron_fist

    def submit(state, candidate_id):
        menu = state["menu"]
        return answering_iron_fist(lambda answers: table.act(match_id, candidate_id, menu["decision_id"],
                                                            menu["state_version"], state["last_sequence"], answers))()

    for _ in range(limit):
        state = table.state(match_id)
        menu = state["menu"]
        if menu["actor_id"] == actor_id:
            group = next((g for g in menu["actions"]
                          if any(option.get("label") == label for option in g["options"])), None)
            if group is not None:
                option = next(option for option in group["options"] if option.get("label") == label)
                return submit(state, option["candidate_id"])
        submit(state, menu["end_turn"])
    raise AssertionError(f"{label!r} never came up for {actor_id}")

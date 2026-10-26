"""AUTO70/AUTO70f1: the Berserker sphere's printed lines, driven through the table itself.

Every test here runs a real intent through a real ``Gate4ControllerEngine`` on a compiled character (real Attack action, real
Action Intent, real cost payment, real rolls, real events), because that is where each of these printed rules used to go
wrong: a rider that never fired, a step asked of the wrong creature, a menu that never reached the player, a duration that
stopped at the first turn.  Unit-level helpers are used only to read a value the table already computed.

  Court of the Unbroken Warpath   an Adrenaline talent without the -2 AC penalty; Resistance to forced movement;
                                 double damage to unattended objects and temporary Barriers
  War-God Incarnation            two Adrenaline talents at once; +5 feet of reach; a 10-foot step after taking damage
  Extended Exertion              two Exertion talents on one Batter attack, paid with a Bonus Action or Martial Focus
  Heaven-Crushing Exertion        three Exertion talents on a hit, asked before the roll; not combinable with Extended
  The Blow Heaven Refused to Receive  up to four Exertion talents; the target counts as already Battered
  Beat Down                      Battered to the end of your second turn; every Exertion effect to the start of its second turn
  Unyielding Advance             a 5-foot step toward a hostile creature that enters its reach; Advantage on the next
                                 Strength (Athletics) check after taking damage, spent on the first one
  Meridian-Rending Blow          only the structures the table can enforce are offered, and the rest stays the GM's
  Berserk / Cultivation Sunder   the printed lines the table already enforced, retired from the GM list

The negative controls matter as much as the positives: a character without the talent owns no row and gets nothing, which is
what keeps every other sphere's saved fight byte-identical.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from combat import typed_executor
from combat.ext import berserker, body_berserker, exertion_talents, reach_bonus
from combat.ext import states
from combat.ext.effect_durations import sweep as sweep_due, token as turn_token
from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position, ReactionDecision, RuntimeObjectState
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_auto_docket import ME, ROOT, _my_turn, _sheet

FOCUS = "resource:core.martial_focus"
WAR_GOD = "condition:typed.state.war_god_incarnation"
MECH = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]

WARPATH_TALENT = "TAL_BERSERKER_COURT_OF_THE_UNBROKEN_WARPATH"
WARPATH_BUTTON = "Court of the Unbroken Warpath"
WAR_GOD_BUTTON = "War-God Incarnation"
WAR_GOD_TALENT = "TAL_BERSERKER_WAR_GOD_INCARNATION"
HEAVEN_CRUSHING = "TAL_BERSERKER_HEAVEN_CRUSHING_EXERTION"
THE_BLOW = "tianxia.talent.berserker.the_blow_heaven_refused_to_receive"


# ------------------------------------------------------------------------------------------------ table helpers
def _berserker_sheet(talents):
    return _sheet(talents, spheres=["tianxia.sphere.berserker"])


def _restock(engine, actor_id=AN):
    """The foe's pools back to what it started the fight with: its own attack price, not anything this lane changes."""
    engine.state.actors[actor_id].resources.update(engine.__dict__.get("_auto70_start_resources", {}).get(actor_id, {}))
    return engine.state.actors[actor_id]


def _fight(talents, seed="AUTO70", me_at=(3, 6), foe_at=(10, 6)):
    engine = Gate4ControllerEngine(ROOT, match_seed=seed,
                                   typed_bundles=(compile_character(_berserker_sheet(talents), actor_id=ME),),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": me_at[0], "y": me_at[1]},
                                                                        AN: {"x": foe_at[0], "y": foe_at[1]}}})
    _my_turn(engine)
    for actor in engine.state.actors.values():
        actor.maximum_hp = actor.current_hp = 500
    engine.__dict__["_auto70_start_resources"] = {row.entity_id: dict(row.resources) for row in engine.state.actors.values()}
    return engine


def _ready(engine, actor_id=ME):
    """Whose turn it is now, with their economy available (the same switch the table makes between turns)."""
    actor = engine.state.actors[actor_id]
    engine.state.current_actor_id = actor_id
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    actor.action_available = actor.bonus_action_available = actor.reaction_available = True
    return actor


def _next_turn(engine, actor_id=ME):
    """The fighter's next turn start: the printed "At the start of your turn, choose whether to enter Adrenaline"."""
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()
    return _ready(engine, actor_id)


def _me(engine):
    return engine.state.actors[ME]


def _foe(engine):
    return engine.state.actors[AN]


def _names(engine, actor_id=ME):
    return {c.display_name for c in engine.legal_candidates() if c.actor_id == actor_id}


def _act(engine, name, target=None, actor_id=ME):
    """Run one real action through the table and return the events it produced."""
    matches = [c for c in engine.legal_candidates() if c.display_name == name and c.actor_id == actor_id
               and (target is None or target in (c.target_ids or ()))]
    assert matches, f"{name!r} is not offered to {actor_id}; offered: {sorted(_names(engine, actor_id))[:20]}"
    candidate = matches[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"auto70-{before}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=actor_id, target_ids=(target,) if target else (candidate.target_ids or ()),
                                       destination=candidate.destination))
    return engine.events[before:]


def _asked(engine, picks):
    """A table that answers each extension choice whose id contains a key of ``picks`` (a list of option ids, or ``None``
    to decline that question) and declines everything else.  Returns the list of questions asked, filled in as it runs."""
    asked = []

    def provider(request):
        asked.append(request)
        options = list(request.get("legal_option_ids") or ())
        for key, pick in picks.items():
            if key in request["reaction_source_id"]:
                chosen = pick(options) if callable(pick) else pick
                return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                        reaction_source_id=request["reaction_source_id"],
                                        selection="DECLINE" if chosen is None else "USE",
                                        option_ids=() if chosen is None else tuple(chosen)), None
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="DECLINE", option_ids=()), None

    engine.set_reaction_provider(provider)
    return asked


def _of(events, event_type):
    return [event.payload or {} for event in events if event.event_type == event_type]


def _notes(events):
    return [payload.get("log") or payload.get("rider") or ""
            for payload in _of(events, "PASSIVE_TRIGGERED") + _of(events, "GM_RIDER")]


def _held(actor, condition_id):
    return [c for c in actor.conditions.values() if c.condition_id == condition_id]


def _has(actor, condition_id):
    return bool(_held(actor, condition_id))


def _mods(actor, field=None):
    return [(m.target_field, m.operation, m.value, m.expires_on) for m in actor.modifiers.values()
            if field is None or m.target_field == field]


def _mod(actor, field, value=1, operation=None):
    """Whether ``actor`` carries a modifier on ``field`` with that value (a printed -1d4, a halved Speed, ...)."""
    return any(m.target_field == field and m.value == value and (operation is None or m.operation == operation)
               for m in actor.modifiers.values())


def _hittable(engine, actor_id=AN):
    """This creature cannot be missed, so a printed effect is proven by the effect and not by the die."""
    engine.state.actors[actor_id].armor_class = -50
    return engine.state.actors[actor_id]


def _action(engine, actor, source):
    """The catalog action whose own typed payload names ``source`` (a compiled id is prefixed with action:typed.<short>.)."""
    for row in engine.action_catalog.values():
        if row.owner_id == actor.entity_id:
            typed = (row.parameters or {}).get("typed") or {}
            if str(typed.get("source") or "") == source or row.source_definition_id == source:
                return row
    raise AssertionError(f"{actor.display_name} owns no action for {source}")


# ------------------------------------------------------------------------------------------------ Court of the Unbroken Warpath
def test_court_of_the_unbroken_warpath_lets_an_adrenaline_talent_run_without_the_ac_penalty():
    engine = _fight(["TAL_BERSERKER_BATTER", WARPATH_TALENT, "TAL_BERSERKER_BERSERK"], foe_at=(4, 6))
    me = _me(engine)
    _act(engine, WARPATH_BUTTON)
    assert states.active(engine, me, "court_of_the_unbroken_warpath") is not None
    _act(engine, "Adrenaline: Berserk")
    assert _has(me, "condition:typed.body_adrenaline_berserk")
    assert body_berserker.adrenaline_ac_penalty(engine, me) is None, "-2 AC while Adrenaline is waived by the Court"
    assert "-2 AC" not in (_held(me, body_berserker.ACTIVE)[0].data or {}).get("label", ""), \
        "the status pill must not claim an Armor Class penalty that is waived"

    # Without the Court the same choice still costs the printed 2 Armor Class.
    plain = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_BERSERK"], foe_at=(4, 6))
    _act(plain, "Adrenaline: Berserk")
    assert body_berserker.adrenaline_ac_penalty(plain, _me(plain)) == -2


def test_court_of_the_unbroken_warpath_resists_forced_movement_and_doubles_unattended_object_damage():
    engine = _fight(["TAL_BERSERKER_BATTER", WARPATH_TALENT], foe_at=(4, 6))
    me = _me(engine)
    foe = _foe(engine)
    _act(engine, WARPATH_BUTTON)
    assert berserker.warpath_holds_ground(_step_ScopeCtx(engine, foe, me), me), "Resistance to forced movement: not moved at all"
    # A creature with no Court is moved normally.
    plain = _fight(["TAL_BERSERKER_BATTER"], foe_at=(4, 6))
    assert berserker.warpath_holds_ground(_step_ScopeCtx(plain, _foe(plain), _me(plain)), _me(plain)) is None

    crate = RuntimeObjectState(object_id="object:auto70.crate", object_kind="object", position=Position(x=10, y=6),
                               unattended=True, flammable=True, ac=10, current_hp=27, maximum_hp=27, destroyed=False,
                               component={"name": "Wooden crate", "material": "wood", "size": "medium", "blocks": False,
                                          "structure": False, "resilient": False, "vulnerable": [], "resist": [],
                                          "artifact": False, "kind": "object"})
    engine.state.objects[crate.object_id] = crate
    doubled = berserker.warpath_doubles_object_damage(engine, me, crate, [(10, "BLUDGEONING")], "object_attack")
    assert doubled is not None and doubled["packets"] == [(10, "BLUDGEONING"), (10, "BLUDGEONING")]
    # A guarded crate (not unattended, not a Barrier) is not doubled.
    guard = crate.model_copy(update={"object_id": "object:auto70.guard", "unattended": False,
                                    "component": {**crate.component, "name": "Statue"}})
    engine.state.objects[guard.object_id] = guard
    assert berserker.warpath_doubles_object_damage(engine, me, guard, [(10, "BLUDGEONING")], "object_attack") is None
    assert berserker.warpath_doubles_object_damage(plain, _me(plain), crate, [(10, "BLUDGEONING")], "object_attack") is None


def _step_ScopeCtx(engine, actor, target):
    """The context a forced-movement attempt runs in: the creature doing the moving is the actor, the one moved the target."""
    action = next(row for row in engine.action_catalog.values() if row.owner_id == actor.entity_id)
    return typed_executor.Context(engine, actor, action, getattr(engine, "_active_intent", None), {"numbers": {}},
                                  [target], target, {})


# ------------------------------------------------------------------------------------------------ War-God Incarnation
def test_war_god_incarnation_runs_two_adrenaline_talents_and_adds_five_feet_of_reach():
    engine = _fight(["TAL_BERSERKER_BATTER", WAR_GOD_TALENT, "TAL_BERSERKER_BERSERK", "TAL_BERSERKER_MARAUDER"], foe_at=(4, 6))
    me = _me(engine)
    _act(engine, WAR_GOD_BUTTON)
    assert states.active(engine, me, "war_god_incarnation") is not None
    _act(engine, "Adrenaline: Berserk")
    _act(engine, "Adrenaline: Marauder")
    assert _has(me, "condition:typed.body_adrenaline_berserk"), "the first Adrenaline talent keeps running"
    assert _has(me, "condition:typed.body_adrenaline_marauder"), "'activate two Adrenaline talents at once'"
    assert body_berserker.adrenaline_ac_penalty(engine, me) is None, "'ignore the AC penalty from one active Adrenaline talent'"

    one = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_BERSERK", "TAL_BERSERKER_MARAUDER"], foe_at=(4, 6))
    _act(one, "Adrenaline: Berserk")
    _next_turn(one)
    _act(one, "Adrenaline: Marauder")
    assert not _has(_me(one), "condition:typed.body_adrenaline_berserk"), "one Adrenaline talent at a time without the Incarnation"

    # "increase reach by 5 feet": the fight's own menu offers the reach variants of this fighter's attacks, and the
    # Incarnation's reach_bonus row is what builds them.
    reach_rows = [row for row in MECH[WAR_GOD_TALENT]["effects"] if row.get("kind") == "reach_bonus"]
    assert reach_rows and reach_rows[0]["feet"] == 5 and reach_rows[0]["attacks"] == "melee" \
        and reach_rows[0]["state"] == "war_god_incarnation", "'increase reach by 5 feet' while the Incarnation is on"
    catalog = {action.display_name for action in engine.action_catalog.values() if action.owner_id == me.entity_id}
    assert {"Batter (reach +5 ft)", "Batter (extended reach)"} <= catalog, \
        "the granted Batter gets the printed +5 feet of reach, and not only a weapon attack"
    far = _fight(["TAL_BERSERKER_BATTER", WAR_GOD_TALENT], foe_at=(5, 6))  # 10 feet away: beyond the plain 5 feet
    assert "Batter (extended reach)" not in _names(far), "and nothing is offered at 10 feet without the Incarnation"
    _act(far, WAR_GOD_BUTTON)
    assert "Batter (extended reach)" in _names(far), "the fight offers the reach while the Incarnation is on"


def test_war_god_incarnation_steps_ten_feet_once_per_turn_after_an_enemy_hit_lands():
    engine = _fight(["TAL_BERSERKER_BATTER", WAR_GOD_TALENT], foe_at=(4, 6))
    me = _me(engine)
    _hittable(engine, ME)
    _act(engine, WAR_GOD_BUTTON)
    assert not me.turn_flags.get(berserker.STEP_AFTER_DAMAGE), "not before it is hurt"
    asked = _asked(engine, {"rider_step": lambda options: [next(option for option in options if option != "cell:3,6")]})
    start = me.position

    _ready(engine, AN)
    events = _act(engine, "Paired Bi Shou Assault", target=ME, actor_id=AN)
    assert _of(events, "DAMAGE_COMMITTED"), "the enemy's own attack is what hurt it"
    assert any("may move 10 feet" in note for note in _notes(events)), _notes(events)
    assert [request["reaction_source_id"] for request in asked] == ["choice:needle.rider_step"], "the printed step is asked"
    assert me.position != start and engine.grid.distance_ft(me.position, start) <= 10, \
        f"it really moved (from {start} to {me.position})"
    spent = me.turn_flags[berserker.STEP_AFTER_DAMAGE]

    _next_turn(engine, AN)
    _restock(engine)
    second = _act(engine, "Scouring Destructive Blast", target=ME, actor_id=AN)
    assert _of(second, "DAMAGE_COMMITTED"), "it was hit again"
    assert me.turn_flags[berserker.STEP_AFTER_DAMAGE] == spent, \
        "once per turn: the second packet of damage did not offer a second step"
    assert len(asked) == 1, "and nothing else was asked"

    plain = _fight(["TAL_BERSERKER_BATTER"], foe_at=(4, 6))
    _hittable(plain, ME)
    plain_asked = _asked(plain, {"rider_step": lambda options: [options[0]]})
    _ready(plain, AN)
    _act(plain, "Paired Bi Shou Assault", target=ME, actor_id=AN)
    assert not _me(plain).turn_flags.get(berserker.STEP_AFTER_DAMAGE) and not plain_asked, "no Incarnation, no step"


def test_ending_war_god_incarnation_drops_adrenaline_back_to_one_talent():
    engine = _fight(["TAL_BERSERKER_BATTER", WAR_GOD_TALENT, "TAL_BERSERKER_BERSERK", "TAL_BERSERKER_MARAUDER"], foe_at=(4, 6))
    me = _me(engine)
    _act(engine, WAR_GOD_BUTTON)
    _act(engine, "Adrenaline: Berserk")
    _next_turn(engine)
    _act(engine, "Adrenaline: Marauder")
    assert body_berserker.running_talents(me) == ["berserk", "marauder"]
    assert body_berserker.adrenaline_ac_penalty(engine, me) is None

    # The Incarnation's printed duration ends: the state condition is brought due and the engine's own turn boundary
    # sweeps it, exactly as a ten-round Incarnation would.
    state = next(c for c in me.conditions.values() if c.condition_id == WAR_GOD)
    state.expires_on = turn_token("start", me.entity_id, int(me.turns_started))
    me.turns_started += 1
    sweep_due(engine, me, "START_OF_TURN")
    assert not states.active(engine, me, "war_god_incarnation"), "the Incarnation ended"
    assert body_berserker.running_talents(me) == ["marauder"], \
        f"capacity is back to one talent, got {body_berserker.running_talents(me)}"
    assert body_berserker.adrenaline_ac_penalty(engine, me) == -2, "and the -2 AC penalty is back with it"
    assert _has(me, body_berserker.ACTIVE), "Adrenaline is still on: one talent is still running"

    # Pressing a running talent's own button turns only that one off.
    _next_turn(engine)
    _act(engine, "Adrenaline: Marauder")
    assert body_berserker.running_talents(me) == [] and not _has(me, body_berserker.ACTIVE), \
        "the last talent off ends Adrenaline, so the -2 AC penalty does not linger"
    assert body_berserker.adrenaline_ac_penalty(engine, me) is None


def test_pressing_a_running_adrenaline_talent_leaves_the_other_one_running():
    engine = _fight(["TAL_BERSERKER_BATTER", WAR_GOD_TALENT, "TAL_BERSERKER_BERSERK", "TAL_BERSERKER_MARAUDER"], foe_at=(4, 6))
    me = _me(engine)
    _act(engine, WAR_GOD_BUTTON)
    _act(engine, "Adrenaline: Berserk")
    _next_turn(engine)
    _act(engine, "Adrenaline: Marauder")
    _next_turn(engine)
    events = _act(engine, "Adrenaline: Berserk")
    assert body_berserker.running_talents(me) == ["marauder"], "only the pressed talent is turned off"
    assert _has(me, "condition:typed.body_adrenaline_marauder")
    assert any("Marauder" in note for note in _notes(events)), _notes(events)


def test_adrenaline_expiry_keeps_the_talent_the_fighter_selected_last_in_either_order():
    """"The most recently activated talent keeps running" when the second slot goes away.

    Both printed orders are exercised, because the registry's own order is not the fighter's: selecting Marauder then
    Berserk has to keep Berserk, and selecting Berserk then Marauder has to keep Marauder.  Only one of those agrees
    with the order the markers happen to be written in, so a test that always presses them the same way proves nothing.
    """
    for first, second, kept in (("Adrenaline: Marauder", "Adrenaline: Berserk", "berserk"),
                                ("Adrenaline: Berserk", "Adrenaline: Marauder", "marauder")):
        engine = _fight(["TAL_BERSERKER_BATTER", WAR_GOD_TALENT, "TAL_BERSERKER_BERSERK",
                         "TAL_BERSERKER_MARAUDER"], foe_at=(4, 6))
        me = _me(engine)
        _act(engine, WAR_GOD_BUTTON)
        _act(engine, first)
        _next_turn(engine)
        _act(engine, second)
        assert body_berserker.running_talents(me) == sorted(["berserk", "marauder"]), "both talents run while there is room"

        state = next(c for c in me.conditions.values() if c.condition_id == WAR_GOD)
        state.expires_on = turn_token("start", me.entity_id, int(me.turns_started))
        me.turns_started += 1
        before = len(engine.events)
        sweep_due(engine, me, "START_OF_TURN")
        assert body_berserker.running_talents(me) == [kept], \
            f"selecting {first.split(': ')[1]} then {second.split(': ')[1]} keeps {kept}, got {body_berserker.running_talents(me)}"
        said = " ".join(_notes(engine.events[before:]))
        assert kept.title() in said, f"the reconciliation names the survivor to the player: {said!r}"


def test_the_reconciled_adrenaline_pill_says_the_ac_penalty_the_fighter_really_has():
    """The pill a fighter reads must match the AC they get.

    The reconciliation happens while the Incarnation's own condition is still present, so reading the fighter at that
    moment promises a waived penalty that the very next AC query no longer grants.
    """
    engine = _fight(["TAL_BERSERKER_BATTER", WAR_GOD_TALENT, "TAL_BERSERKER_BERSERK"], foe_at=(4, 6))
    me = _me(engine)
    _act(engine, WAR_GOD_BUTTON)
    _act(engine, "Adrenaline: Berserk")
    pill = next(c for c in me.conditions.values() if c.condition_id == body_berserker.ACTIVE)
    assert "(-2 AC)" not in str((pill.data or {}).get("label")), "while two run, the penalty is waived: no -2 promised"
    assert body_berserker.adrenaline_ac_penalty(engine, me) is None

    state = next(c for c in me.conditions.values() if c.condition_id == WAR_GOD)
    state.expires_on = turn_token("start", me.entity_id, int(me.turns_started))
    me.turns_started += 1
    sweep_due(engine, me, "START_OF_TURN")

    assert body_berserker.running_talents(me) == ["berserk"], "one talent still runs"
    assert body_berserker.adrenaline_ac_penalty(engine, me) == -2, "the -2 AC penalty is back"
    pill = next(c for c in me.conditions.values() if c.condition_id == body_berserker.ACTIVE)
    assert (pill.data or {}).get("label") == "Adrenaline active (-2 AC)", \
        f"and the pill says so: got {(pill.data or {}).get('label')!r}"
    assert (pill.data or {}).get("choices") == ["berserk"], "and it carries the running set for the next reconciliation"


def test_a_fighter_who_owns_no_second_slot_never_sees_a_waived_penalty_promise():
    """Without the Incarnation the pill and the AC agree from the start."""
    engine = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_BERSERK"], foe_at=(4, 6))
    me = _me(engine)
    _act(engine, "Adrenaline: Berserk")
    pill = next(c for c in me.conditions.values() if c.condition_id == body_berserker.ACTIVE)
    assert (pill.data or {}).get("label") == "Adrenaline active (-2 AC)"
    assert body_berserker.adrenaline_ac_penalty(engine, me) == -2


# ------------------------------------------------------------------------------------------------ more than one Exertion talent
def test_extended_exertion_costs_only_the_printed_payment_and_spends_its_second_talent_once():
    engine = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_EXTENDED_EXERTION", "TAL_BERSERKER_BONE_BREAKER",
                     "TAL_BERSERKER_HEAVY_SWING"], foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine)
    bonus = next(a for a in engine.action_catalog.values() if a.source_definition_id.endswith(".extended_exertion.bonus"))
    focus = next(a for a in engine.action_catalog.values() if a.source_definition_id.endswith(".extended_exertion.focus"))
    assert str(bonus.economy.value if hasattr(bonus.economy, "value") else bonus.economy).endswith("BONUS_ACTION")
    assert str(focus.economy.value if hasattr(focus.economy, "value") else focus.economy) == "NONE", \
        "'expending Martial Focus' is the whole price of that alternative: the Action is the Batter's"
    assert list(focus.costs) == [(FOCUS, 1)]
    assert list(bonus.costs) == []

    assert exertion_talents.armed(engine, me) == ["bone_breaker"], "nothing chosen: the first talent it owns"
    _act(engine, "Exertion: Heavy Swing")
    assert exertion_talents.standing(me) == ["heavy_swing"]

    _asked(engine, {"exertion_set": ["bone_breaker"]})
    assert _me(engine).resources[FOCUS] == 1
    _act(engine, "Extended Exertion: a second Exertion talent (Martial Focus)")
    assert me.resources[FOCUS] == 0, "Martial Focus was spent"
    assert me.action_available and me.bonus_action_available, \
        "that alternative spends nothing else: the Action and the Bonus Action are both still the Batter's"
    assert exertion_talents.extra_slot(engine, me, berserker.BATTER_SOURCE) == ["bone_breaker"]

    _ready(engine)
    first = _act(engine, "Batter", target=AN)
    assert _mod(foe, "attack_roll", 1, "SUBTRACT_DIE"), "Bone-Breaker landed on the target"
    assert _has(foe, "condition:typed.reaction_denied"), "Heavy Swing's failed save took the target's Reactions"
    assert _has(foe, "condition:typed.wrestling_hold"), "and its Bonus Actions"
    assert exertion_talents.extra_slot(engine, me, berserker.BATTER_SOURCE) == [], \
        "the paid second talent is spent by the attack it was paid for"
    assert _held(foe, "condition:typed.battered"), "the Batter landed"

    # The next plain Batter this turn is the standing choice only: the paid second talent is gone.
    _ready(engine)
    foe.conditions.clear()
    foe.modifiers.clear()
    _act(engine, "Batter", target=AN)
    assert not _mods(foe, "attack_roll"), "Bone-Breaker was paid for one attack, not for the rest of the turn"
    assert _has(foe, "condition:typed.reaction_denied"), "Heavy Swing, the standing choice, still applies"


def test_extended_exertion_adds_its_second_talent_to_a_batter_talent_variant():
    """"Apply two Exertion talents to one Batter attack" also works when the attack already is a talent variant: the variant
    spent this attack's one printed Exertion talent, so the standing toggle stands down and Extended Exertion's paid slot
    joins it."""
    engine = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_EXTENDED_EXERTION", "TAL_BERSERKER_BONE_BREAKER",
                     "TAL_BERSERKER_HEAVY_SWING"], foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine)
    _act(engine, "Exertion: Heavy Swing")
    _asked(engine, {"exertion_set": ["bone_breaker"]})
    _act(engine, "Extended Exertion: a second Exertion talent (Bonus Action)")
    assert not me.bonus_action_available, "the Bonus Action alternative spends a Bonus Action"

    _ready(engine)
    events = _act(engine, "Batter + Heavy Swing", target=AN)
    saves = [(payload.get("total"), payload.get("dc"), payload.get("success")) for payload in _of(events, "SAVE_ROLLED")]
    assert saves and saves[0][2] is False, f"Heavy Swing's own Constitution save failed, got {saves}"
    assert _has(foe, "condition:typed.reaction_denied"), "the variant's own talent"
    assert _mod(foe, "attack_roll", 1, "SUBTRACT_DIE"), "and the paid second talent (Bone-Breaker)"
    assert _held(foe, "condition:typed.battered")


def test_the_exertion_menus_reach_a_manual_player_and_a_decline_applies_nothing():
    """A manual or Ask me player is really asked, through the documented needle transport, and an explicit decline applies
    nothing at all -- no silent fallback to another talent."""
    talents = ["TAL_BERSERKER_BATTER", THE_BLOW, "TAL_BERSERKER_BONE_BREAKER", "TAL_BERSERKER_HEAVY_SWING",
               "TAL_BERSERKER_LEG_SMASHER"]
    engine = _fight(talents, foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine)
    asked = _asked(engine, {"exertion_set": lambda options: options[:2]})
    events = _act(engine, "The Blow Heaven Refused to Receive", target=AN)
    menus = [request for request in asked if "exertion" in request["reaction_source_id"]]
    assert len(menus) == 1, "one menu for the pre-roll set"
    menu = menus[0]
    assert menu["reaction_source_id"] == "choice:needle.berserker_exertion_set", "the documented choice transport"
    assert list(menu["legal_option_ids"]) == ["bone_breaker", "heavy_swing", "leg_smasher"], \
        "every Exertion talent this fighter owns, the standing one included (the set is complete on its own)"
    prompt = (menu.get("choice_trigger") or {}).get("prompt", "")
    assert "The Blow Heaven Refused to Receive" in prompt and foe.display_name in prompt, \
        f"the prompt names the ability and the creature it affects: {prompt!r}"
    assert _mod(foe, "attack_roll", 1, "SUBTRACT_DIE"), "Bone-Breaker applied on the hit"
    assert _has(foe, "condition:typed.reaction_denied"), "and Heavy Swing"

    declined = _fight(talents, foe_at=(4, 6))
    _hittable(declined)
    _asked(declined, {"exertion_set": None})
    events = _act(declined, "The Blow Heaven Refused to Receive", target=AN)
    assert _of(events, "DAMAGE_COMMITTED"), "the blow's own hit still lands"
    assert not _mods(_foe(declined)), "a declined choice applies no Exertion talent"
    assert not _has(_foe(declined), "condition:typed.reaction_denied")


def test_the_exertion_menus_are_asked_of_the_player_who_owns_them_on_the_players_own_turn():
    """Checklist 9: a player-owned decision is asked of that player.

    Both abilities that open an Exertion menu are the player's own Action, so "on the player's own turn" is where the
    printed rule puts them; what this pins is that the question is routed to the fighter who owns it (reactor is the
    fighter, not an opponent or the engine), arrives as an askable choice rather than a silent default, and says what it
    is for. The menu transport is checked against what a manual / Ask me table actually reads.
    """
    talents = ["TAL_BERSERKER_BATTER", HEAVEN_CRUSHING, "TAL_BERSERKER_BONE_BREAKER", "TAL_BERSERKER_HEAVY_SWING"]
    engine = _fight(talents, foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine)
    asked = _asked(engine, {"exertion_set": lambda options: options[:1]})
    _act(engine, "Heaven-Crushing Exertion", target=AN)
    menus = [request for request in asked if "exertion_set" in request["reaction_source_id"]]
    assert len(menus) == 1, f"one pre-roll menu, got {len(menus)}"
    menu = menus[0]

    assert menu["reactor_id"] == me.entity_id, "the fighter who owns the talents is the one asked"
    assert menu["reaction_source_id"] == exertion_talents.CHOICE_SET, "the documented choice transport"
    assert menu["reaction_source_id"].startswith("choice:needle."), "which the choice provider really owns"
    trigger = menu.get("choice_trigger") or {}
    assert trigger.get("allow_decline") is True, "a player may decline; it is not a forced default"
    assert trigger.get("automatic_use") is not True, "and it is not auto-resolved past the player"
    prompt = trigger.get("prompt", "")
    assert "Heaven-Crushing Exertion" in prompt, f"the prompt names the ability: {prompt!r}"
    assert foe.display_name in prompt, f"and the creature it affects: {prompt!r}"

    # An AI fighter with nobody answering decides for itself and its attack still lands the standing Exertion talent:
    # an unanswered menu must resolve rather than stall the fight.
    solo = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_HEAVY_SWING"], foe_at=(4, 6))
    _hittable(solo)
    _act(solo, "Exertion: Heavy Swing")
    events = _act(solo, "Batter", target=AN)
    assert _of(events, "ATTACK_ROLLED"), "the AI fighter's own attack resolved without stalling on a menu"
    assert _has(_foe(solo), "condition:typed.reaction_denied"), "and its standing Exertion talent still applied"


def test_every_exertion_menu_option_explains_itself_to_someone_who_has_never_read_the_sheet():
    """Checklist 13: each option says what it does, who it affects and how long it lasts.

    A bare "Apply Heavy Swing to this attack" leaves a newcomer unable to choose; the option text carries the effect and
    the printed length in plain words, and says nothing internal.
    """
    engine = _fight(["TAL_BERSERKER_BATTER", THE_BLOW, "TAL_BERSERKER_BONE_BREAKER", "TAL_BERSERKER_HEAVY_SWING",
                     "TAL_BERSERKER_LEG_SMASHER"], foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine)
    asked = _asked(engine, {"exertion_set": []})
    _act(engine, "The Blow Heaven Refused to Receive", target=AN)
    menu = next(request for request in asked if "exertion_set" in request["reaction_source_id"])
    labels = (menu.get("choice_trigger") or {}).get("labels") or {}
    assert labels, f"the menu carries its own option text: {menu.get('choice_trigger')}"
    for key, text in labels.items():
        assert exertion_talents.label(key) in text, f"the talent's own name is in its option: {text!r}"
        assert len(text.split()) > 8, f"and it explains the effect, not just the name: {text!r}"
        assert "start of your next turn" in text, f"with its printed length: {text!r}"
        for jargon in ("TAL_", "condition:typed", "source_modifier", "START_OF_SOURCE"):
            assert jargon not in text, f"no internal ids in player text: {text!r}"

    # Beat Down changes how long those effects last, so the option has to say so as well.
    beat = _fight(["TAL_BERSERKER_BATTER", THE_BLOW, "TAL_BERSERKER_HEAVY_SWING", "TAL_BERSERKER_BEAT_DOWN"],
                  foe_at=(4, 6))
    _hittable(beat)
    asked = _asked(beat, {"exertion_set": []})
    _act(beat, "The Blow Heaven Refused to Receive", target=AN)
    menu = next(request for request in asked if "exertion_set" in request["reaction_source_id"])
    labels = (menu.get("choice_trigger") or {}).get("labels") or {}
    assert labels and all("second turn" in text for text in labels.values()), \
        f"with Beat Down on, the option says the longer length: {labels}"


def test_pre_roll_exertion_talents_are_their_own_automated_variant_not_a_menu_choice():
    """Brutal Strike and Reaper's Momentum change the roll, so they are their own attack variants.

    A set applied on a hit cannot carry them without handing out their benefit after the roll has already missed the
    penalty.  They are automated where the printed sphere puts them -- "Batter + <talent>" (combat/ext/pre_roll_attack.py
    folds the -5 and the first-hit damage into that row) -- so this menu offers only the on-hit talents and no longer
    tells the player to resolve the two by hand.
    """
    engine = _fight(["TAL_BERSERKER_BATTER", THE_BLOW, "TAL_BERSERKER_BONE_BREAKER", "TAL_BERSERKER_BRUTAL_STRIKE",
                     "TAL_BERSERKER_REAPER_S_MOMENTUM"], foe_at=(4, 6))
    me = _me(engine)
    _hittable(engine)
    asked = _asked(engine, {"exertion_set": ["bone_breaker"]})
    offered = _names(engine)
    events = _act(engine, "The Blow Heaven Refused to Receive", target=AN)
    menu = next(request for request in asked if "exertion_set" in request["reaction_source_id"])
    assert list(menu["legal_option_ids"]) == ["bone_breaker"], "only talents that work on a hit"

    said = " ".join(_notes(events))
    for name in ("Brutal Strike", "Reaper's Momentum"):
        assert not any(name in note and "by hand" in note for note in _notes(events)), \
            f"{name} is automated as its own attack, not a by-hand rider: {said!r}"
    assert exertion_talents.owned(engine, me.entity_id) == ["bone_breaker"], \
        "the pre-roll talents are not offered as post-hit choices"

    assert "Batter + Brutal Strike" in offered and "Batter + Reaper’s Momentum" in offered, \
        "the printed way to use them is still its own attack"


def test_extended_exertion_and_heaven_crushing_exertion_cannot_be_combined():
    engine = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_EXTENDED_EXERTION", HEAVEN_CRUSHING,
                     "TAL_BERSERKER_BONE_BREAKER"], foe_at=(4, 6))
    me = _me(engine)
    bonus = next(a for a in engine.action_catalog.values() if a.source_definition_id.endswith(".extended_exertion.bonus"))
    heaven = _action(engine, me, HEAVEN_CRUSHING)

    class _Candidate:
        target_ids = ()
        destination = None

    assert berserker.extended_exertion_not_with_heaven_crushing(engine, me, _Candidate(), bonus) is None
    me.turn_flags[exertion_talents.turn_key(engine, HEAVEN_CRUSHING, me)] = "bone_breaker"
    assert berserker.extended_exertion_not_with_heaven_crushing(engine, me, _Candidate(), bonus) is False
    assert berserker.extended_exertion_not_with_heaven_crushing(engine, me, _Candidate(), heaven) is None
    me.turn_flags[exertion_talents.turn_key(engine, f"extended:{berserker.BATTER_SOURCE}", me)] = "bone_breaker"
    assert berserker.extended_exertion_not_with_heaven_crushing(engine, me, _Candidate(), heaven) is False
    assert berserker.extended_exertion_not_with_heaven_crushing(engine, me, _Candidate(), bonus) is False


def test_heaven_crushing_exertion_asks_for_its_exertion_set_before_the_roll():
    engine = _fight(["TAL_BERSERKER_BATTER", HEAVEN_CRUSHING, "TAL_BERSERKER_BONE_BREAKER",
                     "TAL_BERSERKER_HEAVY_SWING", "TAL_BERSERKER_LEG_SMASHER"], foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine)
    _act(engine, "Exertion: Leg-Smasher")
    asked = _asked(engine, {"exertion_set": lambda options: options[:3]})
    events = _act(engine, "Heaven-Crushing Exertion", target=AN)
    roll = _of(events, "ATTACK_ROLLED")
    assert roll, "the attack was rolled"
    menu = next(request for request in asked if "exertion_set" in request["reaction_source_id"])
    assert list(menu["legal_option_ids"]) == ["bone_breaker", "heavy_swing", "leg_smasher"], "all three it knows"
    assert int(menu["extension_choice"]["maximum_selections"]) == 3, "'choose three Exertion talents you know'"
    assert "before you roll" in (menu.get("choice_trigger") or {}).get("prompt", ""), "asked before the roll, as printed"
    assert foe.display_name in (menu.get("choice_trigger") or {}).get("prompt", ""), "and it names the creature"
    assert me.resources[FOCUS] == 0, "'Cost: Expend Martial Focus' was paid by the table"


def test_the_blow_treats_its_target_as_already_battered_and_ignores_resistance():
    engine = _fight(["TAL_BERSERKER_BATTER", THE_BLOW, "TAL_BERSERKER_HEAVY_SWING"], foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine)
    assert MECH[THE_BLOW]["riders"] == ["ignore Disadvantage"], "every other printed line is resolved by the table now"
    blow = _action(engine, me, THE_BLOW)
    ctx = typed_executor.Context(engine, me, blow, getattr(engine, "_active_intent", None),
                                 {**(((blow.parameters or {}).get("typed")) or {}),
                                  "numbers": {"pb": 4, "save_dc": 15}}, [foe], foe, {})
    assert berserker.was_battered(ctx, foe), "'treat the target as already Battered'"
    assert berserker.the_blow_ignores_resistance(engine, "ACID", ctx.typed, me.entity_id, foe) is True
    plain = _fight(["TAL_BERSERKER_BATTER"], foe_at=(4, 6))
    plain_ctx = typed_executor.Context(plain, _me(plain), _action(plain, _me(plain), "TAL_BERSERKER_BATTER"),
                                       getattr(plain, "_active_intent", None), {"numbers": {}},
                                       [_foe(plain)], _foe(plain), {})
    assert berserker.was_battered(plain_ctx, _foe(plain)) is False
    assert berserker.the_blow_ignores_resistance(plain, "ACID", plain_ctx.typed, _me(plain).entity_id, _foe(plain)) is None


def test_heaven_shaking_batter_asks_for_a_second_different_effect_on_an_already_battered_target():
    engine = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_HEAVEN_SHAKING_BATTER", "TAL_BERSERKER_HEAVY_SWING"], foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine)
    # "If the target was already Battered, choose two different effects instead of one."
    engine._apply_condition(foe, "condition:typed.battered", "test", me.entity_id, expires_on="UNTIL_REMOVED")
    _act(engine, "Exertion: Heaven-Shaking Batter")
    asked = _asked(engine, {"exertion_option": lambda options: [options[0]]})
    events = _act(engine, "Batter", target=AN)
    options = [request for request in asked if "exertion_option" in request["reaction_source_id"]]
    assert options, "the printed 'choose one' is asked"
    first = list(options[0]["legal_option_ids"])
    _ready(engine)
    foe.conditions.clear()
    engine._apply_condition(foe, "condition:typed.battered", "test", me.entity_id, expires_on="UNTIL_REMOVED")
    asked = _asked(engine, {"exertion_option": lambda options: [options[0]]})
    events = _act(engine, "Batter", target=AN)
    pairs = [request for request in asked if "exertion_option" in request["reaction_source_id"]]
    assert len(pairs) == 2, f"'choose two different effects instead of one' asked twice, got {len(pairs)}"
    assert list(pairs[0]["legal_option_ids"]) != list(pairs[1]["legal_option_ids"]), "and they are different effects"
    assert exertion_talents.TWO_IF_BATTERED == {"heaven_shaking_batter"}
    assert len(exertion_talents.talent_effects(engine, me.entity_id, "heaven_shaking_batter")) == 4, \
        "four of the printed five effects are this fighter's own attack variants (the fifth damages an adjacent object)"


def test_heaven_shaking_batter_actually_lands_the_effect_it_offers():
    """The menu test above proves the fighter is asked and that the options differ; this one proves the chosen effect
    really happens to the target, which is the only part a player can see.

    Two of the printed effects are checked separately because they are different kinds of consequence: a condition on
    the creature, and the creature's position. Both are read back off the target after a real attack.
    """
    def _chosen_index(name):
        labels = [option["label"] for option in
                  exertion_talents.talent_effects(engine, me.entity_id, "heaven_shaking_batter")]
        return str(labels.index(name))

    # 1. Knock Prone -> the target really is Prone afterwards.
    engine = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_HEAVEN_SHAKING_BATTER"], foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine)
    _act(engine, "Exertion: Heaven-Shaking Batter")
    _ready(engine)
    _asked(engine, {"exertion_option": lambda options: [_chosen_index("Knock Prone")]})
    _act(engine, "Batter", target=AN)
    assert any("prone" in c.condition_id.lower() for c in foe.conditions.values()), \
        f"Knock Prone really Prones {foe.display_name}: {sorted(c.condition_id for c in foe.conditions.values())}"

    # 2. Push 15 Feet -> the target really moves, and this is a different consequence from the condition above.
    engine = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_HEAVEN_SHAKING_BATTER"], foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine)
    _act(engine, "Exertion: Heaven-Shaking Batter")
    _ready(engine)
    _asked(engine, {"exertion_option": lambda options: [_chosen_index("Push 15 Feet")]})
    start = (foe.position.x, foe.position.y)
    _act(engine, "Batter", target=AN)
    moved = engine.grid.distance_ft(start, (foe.position.x, foe.position.y))
    assert moved >= 15, f"Push 15 Feet really moves {foe.display_name}, it moved {moved} feet from {start}"


# ------------------------------------------------------------------------------------------------ Beat Down
def test_beat_down_keeps_battered_and_every_exertion_effect_until_the_second_turn():
    """'Your Exertion effects that normally last until the start of your next turn instead last until the start of your
    second turn after the attack' -- on the standing toggle, on a talent's own compiled attack variant, and on the rows
    nested inside one."""
    for talent, variant in (("TAL_BERSERKER_HEAVY_SWING", "Batter + Heavy Swing"),
                            ("TAL_BERSERKER_LEG_SMASHER", "Batter + Leg-Smasher")):
        engine = _fight(["TAL_BERSERKER_BATTER", talent, "TAL_BERSERKER_BEAT_DOWN"], foe_at=(4, 6))
        me, foe = _me(engine), _hittable(engine)
        _act(engine, variant, target=AN)
        held = _held(foe, "condition:typed.battered")
        assert held and held[0].expires_on == f"END_OF_SOURCE_TURN_AT:{int(me.turns_started) + 2}", \
            "'Battered lasts until the end of your second turn'"
        if talent == "TAL_BERSERKER_HEAVY_SWING":
            for condition_id in ("condition:typed.reaction_denied", "condition:typed.wrestling_hold"):
                marks = _held(foe, condition_id)
                assert marks and marks[0].expires_on == f"START_OF_TURN_AT:{me.entity_id}:{int(me.turns_started) + 2}", \
                    f"{condition_id} lasts to the start of the second turn, got {marks and marks[0].expires_on}"
        else:
            halved = [row for row in _mods(foe, "speed_halved")]
            assert halved and halved[0][3] == f"START_OF_TURN_AT:{me.entity_id}:{int(me.turns_started) + 2}", \
                "Leg-Smasher's halved Speed lasts to the start of the second turn"

        # And it really is the second turn: the effect survives one turn boundary and goes at the second.
        marks = _held(foe, "condition:typed.reaction_denied") or [c for c in foe.conditions.values() if c.expires_on.startswith("START_OF_TURN_AT")]
        if marks:
            condition = marks[0]
            me.turns_started += 1
            sweep_due(engine, me, "START_OF_TURN")
            assert _held(foe, condition.condition_id), f"{condition.condition_id} survives the first turn boundary"
            me.turns_started += 1
            sweep_due(engine, me, "START_OF_TURN")
            assert not _held(foe, condition.condition_id), f"{condition.condition_id} ends at the start of the second turn"

        # Without Beat Down the printed length stands: the start of the user's next turn.
        plain = _fight(["TAL_BERSERKER_BATTER", talent], foe_at=(4, 6))
        _hittable(plain)
        _act(plain, variant, target=AN)
        printed = {c.condition_id: c.expires_on for c in _foe(plain).conditions.values()}
        shortened = ({"condition:typed.reaction_denied", "condition:typed.wrestling_hold"}
                     if talent == "TAL_BERSERKER_HEAVY_SWING" else set())
        for condition_id in shortened or set(printed):
            if condition_id == "condition:typed.battered":
                continue
            assert printed[condition_id] == "START_OF_SOURCE_NEXT_TURN", \
                f"without Beat Down {condition_id} lasts to the start of your next turn, got {printed}"
        for row in _mods(_foe(plain), "speed_halved"):
            assert row[3] == "START_OF_SOURCE_NEXT_TURN", f"without Beat Down Leg-Smasher ends with your next turn: {row}"

    # Bell-Ringer through the standing toggle, applied by the shared applier.
    engine = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_BEAT_DOWN", "TAL_BERSERKER_BELL_RINGER"], foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine)
    _act(engine, "Exertion: Bell-Ringer")
    _act(engine, "Batter", target=AN)
    rung = _held(foe, "condition:typed.bell_rung")
    assert rung and rung[0].expires_on == f"START_OF_TURN_AT:{me.entity_id}:{int(me.turns_started) + 2}", \
        "'until the start of your second turn after the attack'"
    assert berserker.exertion_expiry(engine, me, "START_OF_SOURCE_NEXT_TURN") is not None
    assert berserker.exertion_expiry(engine, me, "START_OF_TARGET_NEXT_TURN") is None


def test_beat_down_lengthens_the_exertion_talents_on_the_attack_and_not_the_attack_itself():
    """The Blow Heaven Refused to Receive prints its own "Successful Save: it cannot take Reactions until the start of
    your next turn", and that denial belongs to the Blow, not to any Exertion talent it applies beside it.

    So with Beat Down on, the talent the fighter chose alongside it (Leg-Smasher's halved Speed) reaches the start of
    the second turn while the Blow's own denial keeps the printed length -- the two are decided from the row that wrote
    them, not from "this attack carries an Exertion talent".
    """
    engine = _fight(["TAL_BERSERKER_BATTER", THE_BLOW, "TAL_BERSERKER_BEAT_DOWN", "TAL_BERSERKER_LEG_SMASHER"],
                    foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine)
    foe.saving_throws["CON"] = 40  # a successful save, so the Blow's OWN denial is the one that applies
    _asked(engine, {"exertion_set": ["leg_smasher"]})
    events = _act(engine, "The Blow Heaven Refused to Receive", target=AN)
    saves = [(payload.get("total"), payload.get("dc"), payload.get("success")) for payload in _of(events, "SAVE_ROLLED")]
    assert saves and saves[0][2] is True, f"the target made its own save, got {saves}"

    denied = _held(foe, "condition:typed.reaction_denied")
    assert denied, "the Blow's own successful-save denial is on the target"
    assert denied[0].expires_on == "START_OF_SOURCE_NEXT_TURN", \
        f"the Blow's own effect keeps the printed length, got {denied[0].expires_on}"
    halved = [row for row in _mods(foe, "speed_halved")]
    assert halved and halved[0][3] == f"START_OF_TURN_AT:{me.entity_id}:{int(me.turns_started) + 2}", \
        f"the chosen Exertion talent still lasts to the start of the second turn, got {halved}"

    # The Blow's own denial keeps the engine's own name, which the engine removes at its own turn boundary; the
    # Exertion talent's replaced name is a sweep token, and is still running one boundary later.
    assert denied[0].expires_on == "START_OF_SOURCE_NEXT_TURN", "the engine's own name, not a replaced one"
    me.turns_started += 1
    sweep_due(engine, me, "START_OF_TURN")
    assert [row for row in _mods(foe, "speed_halved")], "the Exertion talent is still running"


def test_a_fighter_without_beat_down_never_lengthens_anything():
    """The lengthening is this fighter's own talent: a fighter who does not own Beat Down keeps every printed length,
    even carrying the same Exertion talent on the same printed attack."""
    engine = _fight(["TAL_BERSERKER_BATTER", THE_BLOW, "TAL_BERSERKER_LEG_SMASHER"], foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine)
    foe.saving_throws["CON"] = 40
    _asked(engine, {"exertion_set": ["leg_smasher"]})
    _act(engine, "The Blow Heaven Refused to Receive", target=AN)
    assert berserker.exertion_expiry(engine, me, "START_OF_SOURCE_NEXT_TURN") is None, "no Beat Down, no replacement"
    for row in _mods(foe, "speed_halved"):
        assert row[3] == "START_OF_SOURCE_NEXT_TURN", f"the printed length stands without Beat Down, got {row}"


def test_beat_down_stops_at_the_end_of_its_own_attack_and_reaches_no_later_attack_this_turn():
    """The negative control for the marker that says "this resolution is my own Exertion variant".

    Beat Down lengthens "your Exertion effects ... after THE attack", so that provenance belongs to the one attack's
    resolution.  A turn flag outlived it -- the engine clears those only at the fighter's NEXT turn -- so a second
    attack on the same turn inherited a marker it never earned.

    Here a "Batter + Leg-Smasher" variant runs first and Leg-Smasher really is lengthened, then an unrelated attack
    resolves in the same turn: The Blow's own printed "cannot take Reactions until the start of your next turn" must
    keep its printed length, because no Exertion talent wrote that row.
    """
    talents = ["TAL_BERSERKER_BATTER", "TAL_BERSERKER_BEAT_DOWN", "TAL_BERSERKER_LEG_SMASHER",
               THE_BLOW, "TAL_BERSERKER_HEAVY_SWING"]
    engine = _fight(talents, foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine)
    foe.saving_throws["CON"] = 40  # a successful save, so the Blow's OWN denial is the one that applies
    _asked(engine, {"exertion_set": ["heavy_swing"]})

    _act(engine, "Batter + Leg-Smasher", target=AN)
    halved = _mods(foe, "speed_halved")
    assert halved and halved[0][3] == f"START_OF_TURN_AT:{me.entity_id}:{int(me.turns_started) + 2}", \
        "the variant's own talent is still lengthened"
    assert berserker.VARIANT_STACK not in engine.__dict__, \
        "the marker is popped when that resolution ends, not left behind on the fight"

    # A second attack on the SAME turn, by the same fighter, printing its own length.
    _ready(engine)
    _act(engine, "The Blow Heaven Refused to Receive", target=AN)
    denied = _held(foe, "condition:typed.reaction_denied")
    assert denied, "the Blow's own successful-save denial is on the target"
    assert denied[0].expires_on == "START_OF_SOURCE_NEXT_TURN", \
        f"an attack after the variant keeps the length it printed, got {denied[0].expires_on}"


def test_an_attack_granted_inside_the_variant_resolves_as_itself():
    """The nested negative control: an attack that runs INSIDE the variant's resolution is its own attack.

    Beat Down's provenance is pushed by the ``effect_resolution_scope`` around the variant's attack block, so an attack
    granted or triggered inside it pushes nothing and pops back to its host on the way out.  Its rows were not written by
    the talent, so it keeps its printed lengths -- while the variant's own rows, which run after the nested attack has
    returned, are still lengthened.  A turn-wide boolean could not say this: it was still set while the nested attack ran.
    """
    engine = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_BEAT_DOWN", "TAL_BERSERKER_LEG_SMASHER"], foe_at=(4, 6))
    me = _me(engine)
    variant = next(a for a in engine.action_catalog.values() if a.display_name == "Batter + Leg-Smasher")
    variant_ctx = _ScopeCtx(engine, me, variant, (variant.parameters or {}).get("typed") or {})
    attack_row = {"type": "attack", "on_hit": []}
    granted = _ScopeCtx(engine, me, variant, {"modifier": {"id": "TAL_BERSERKER_BELL_RINGER"}})
    plain = _ScopeCtx(engine, me, variant, {})
    here = berserker.exertion_variant_scope
    resolving = berserker._resolving_own_variant

    seen = [("before", resolving(variant_ctx))]
    with here(variant_ctx, attack_row):
        seen.append(("variant", resolving(variant_ctx)))
        with here(granted, attack_row):  # a granted attack INSIDE the variant resolves as itself
            seen.append(("nested", resolving(variant_ctx)))
        seen.append(("after", resolving(variant_ctx)))
    seen.append(("closed", resolving(variant_ctx)))

    assert seen == [("before", False), ("variant", True), ("nested", False), ("after", True), ("closed", False)], \
        f"the marker names one resolution, is hidden from a nested attack, and is gone afterwards: {seen}"
    assert berserker.VARIANT_STACK not in engine.__dict__, "and nothing is left on the fight"

    # A plain attack of the same fighter carries its own answer, so it cannot inherit one it did not earn...
    with here(plain, attack_row):
        assert resolving(plain) is False, "an attack that is not this fighter's own variant is not one"
    # ...and a fighter who does not own Beat Down opens no frame at all, so nothing outside the rider changes.
    assert here(_ScopeCtx(engine, _foe(engine), variant, {}), attack_row) is None, \
        "a fighter with no Beat Down row is inert here"


class _ScopeCtx:
    """The fields the two provenance seams read off a context, so a test can drive them directly."""
    def __init__(self, engine, actor, action, typed):
        self.engine, self.actor, self.action, self.typed = engine, actor, action, typed


@pytest.mark.parametrize("outcome", ["complete", "pause", "error"])
def test_nested_granted_attack_dispatch_restores_variant_expiry_and_unwinds(monkeypatch, outcome):
    """Exercise the documented granted-attack contract inside a real variant attack's on-hit dispatch.

    Only the test's grant/inspection effects are registered. Both attacks, the nested choice, and every lasting
    effect run through the shipped executor. The nested action is owned The Blow, not an unowned talent marker.
    """
    from copy import deepcopy
    from combat import ext
    from combat.ext import CheckpointError, ControllerPause
    from tests.h1_support import script

    engine = _fight(MENUS, foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine)
    foe.saving_throws["CON"] = 40
    script(engine, [12] * 100)
    variant = next(a for a in engine.action_catalog.values() if a.display_name == "Batter + Leg-Smasher")
    granted_action = _action(engine, me, THE_BLOW)
    granted_typed = deepcopy(granted_action.parameters["typed"])
    granted_attack = next(e for e in granted_typed["effects"] if e["type"] == "attack")
    granted_attack.update(count=1, granted_attack_root=True)
    granted_typed.update(granted_attack=True, effects=[granted_attack])
    typed = deepcopy(variant.parameters["typed"])
    attack = next(e for e in typed["effects"] if e["type"] == "attack")
    # Legacy variants can carry unstamped rows: exercise the scope fallback rather than the explicit stamp.
    for effect in attack["on_hit"]:
        effect.pop("source_modifier", None)
    # Keep the compiled Leg-Smasher rows, adding a test grant before them and inspection after them.
    attack["on_hit"] = [{"type": "test:auto70_grant"}, *attack["on_hit"],
                        {"type": "test:auto70_expiry", "first_hit_only": True}]
    candidate = next(c for c in engine.legal_candidates() if c.display_name == variant.display_name and AN in c.target_ids)
    intent = ActionIntent(intent_id="auto70-nested", decision_id=candidate.decision_id,
                          candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                          actor_id=ME, target_ids=(AN,))
    ctx = typed_executor.Context(engine, me, variant, intent, typed, [foe], foe, {})
    expected = f"START_OF_TURN_AT:{ME}:{int(me.turns_started) + 2}"
    seen = []

    def provider(request):
        if request["reaction_source_id"] == "choice:needle.berserker_exertion_set":
            assert engine.__dict__[berserker.VARIANT_STACK] == [ME, ""], "actual granted context hides its host"
            if outcome == "pause":
                raise ControllerPause("waiting for the player's nested choice")
            if outcome == "error":
                raise CheckpointError("invalid nested player answer")
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="DECLINE", option_ids=()), None

    engine.set_reaction_provider(provider)

    def grant(host, effect):
        assert engine.__dict__[berserker.VARIANT_STACK] == [ME]
        nested = typed_executor.Context(engine, me, granted_action, intent, granted_typed, [foe], foe, {})
        try:
            # Direct callers are a documented path: block_attack itself must enter the resolution hooks.
            typed_executor.block_attack(nested, granted_attack)
        except (ControllerPause, ValueError):
            assert engine.__dict__[berserker.VARIANT_STACK] == [ME], "nested pause/error restores the real outer frame"
            raise
        assert engine.__dict__[berserker.VARIANT_STACK] == [ME]
        denied = _held(foe, "condition:typed.reaction_denied")
        assert denied and denied[0].expires_on == "START_OF_SOURCE_NEXT_TURN", "unrelated granted effect keeps printed expiry"
        seen.append("granted")

    def expiry(host, effect):
        assert _mods(foe, "speed_halved")[0][3] == expected, "outer talent still lengthens after the grant returns"
        seen.append("outer")

    ext.effects()
    monkeypatch.setitem(ext._EFFECTS, "test:auto70_grant", grant)
    monkeypatch.setitem(ext._EFFECTS, "test:auto70_expiry", expiry)
    if outcome == "complete":
        typed_executor.run_effects(ctx, [attack])
        assert seen == ["granted", "outer"]
        assert len([e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ME]) == 2
        _next_turn(engine)
        assert not _held(foe, "condition:typed.reaction_denied"), "the granted effect expires on the first source turn"
        assert _mods(foe, "speed_halved"), "the outer Exertion survives the first source turn"
        _next_turn(engine)
        assert not _mods(foe, "speed_halved"), "the outer Exertion expires on the second source turn"
    else:
        error = ControllerPause if outcome == "pause" else ValueError
        with pytest.raises(error):
            typed_executor.run_effects(ctx, [attack])
        assert not _mods(foe, "speed_halved"), "paused/failed nested choice never reaches the outer talent"
        assert berserker.VARIANT_STACK not in engine.__dict__
        # A fresh real resolution after unwind still earns its own lengthening.
        _asked(engine, {})
        typed_executor.run_effects(replace(ctx, damage_cache={}), variant.parameters["typed"]["effects"])
        assert _mods(foe, "speed_halved")[0][3] == expected
    assert berserker.VARIANT_STACK not in engine.__dict__, "nothing survives the complete attack, pause, or error"


def test_a_fighter_whose_only_exertion_talents_change_the_roll_gets_their_own_attack_not_a_rider():
    """Brutal Strike and Reaper's Momentum are used as "Batter + <talent>", never applied on a hit.

    A fighter who owns only one of them has no post-hit menu (``owned()`` is empty), and The Blow therefore opens no
    Exertion question.  That is not a gap left to the GM: the talent's own attack variant is offered, and its -5 and
    first-hit effect are compiled into it (combat/ext/pre_roll_attack.py).  No by-hand note is emitted.
    """
    for key in ("brutal_strike", "reapers_momentum"):
        talent = exertion_talents.mechanic_id(key)
        engine = _fight(["TAL_BERSERKER_BATTER", THE_BLOW, talent], foe_at=(4, 6))
        me = _me(engine)
        _hittable(engine)
        offered = _names(engine)
        asked = _asked(engine, {"exertion_set": []})

        events = _act(engine, "The Blow Heaven Refused to Receive", target=AN)

        assert not exertion_talents.owned(engine, me.entity_id), f"{talent}: not offered as a post-hit choice"
        assert not [r for r in asked if "exertion_set" in r["reaction_source_id"]], \
            f"{talent}: no menu is offered, because no owned talent can be applied on a hit"
        assert not any(exertion_talents.label(key) in note and "by hand" in note for note in _notes(events)), \
            f"{talent}: nothing is left for the GM to resolve by hand"
        assert _of(events, "DAMAGE_COMMITTED"), f"{talent}: the Blow's own hit still lands"
        short = "Brutal Strike" if key == "brutal_strike" else "Momentum"
        assert any(name.startswith("Batter +") and short in name for name in offered), \
            f"{talent}: the printed attack variant is offered by its own name"


# ------------------------------------------------------------------------------------------------ Unyielding Advance
def test_unyielding_advance_gives_athletics_advantage_after_taking_damage():
    engine = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_UNYIELDING_ADVANCE"], foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine, ME)
    _act(engine, "Adrenaline: Unyielding Advance")
    assert _has(me, "condition:typed.body_adrenaline_unyielding_advance")
    assert typed_executor.check_modes(me, "STR", "Athletics", engine=engine, against_creature=foe) == set(), "not until it is hurt"
    _ready(engine, AN)
    _act(engine, "Paired Bi Shou Assault", target=ME, actor_id=AN)
    assert me.turn_flags.get(berserker.UNYIELDING_CHECK) is True, "taking damage arms the next check"
    assert typed_executor.check_modes(me, "STR", "Athletics", engine=engine, against_creature=foe) == {"ADVANTAGE"}
    assert typed_executor.check_modes(me, "STR", "", engine=engine, against_creature=foe) == set(), \
        "the printed check names Athletics; an unspecified Strength check is a different check"
    assert typed_executor.check_modes(me, "DEX", "Athletics", engine=engine, against_creature=foe) == set()

    plain = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_BERSERK"], foe_at=(4, 6))
    _act(plain, "Adrenaline: Berserk")
    assert _has(_me(plain), "condition:typed.body_adrenaline_berserk")
    assert typed_executor.check_modes(_me(plain), "STR", "Athletics", engine=plain, against_creature=_foe(plain)) == set(), \
        "no Unyielding Advance running, no Advantage"


def test_unyielding_advance_spends_its_advantage_on_the_first_qualifying_check():
    """One payment, one check: the first Strength (Athletics) check is rolled with Advantage and the next one is ordinary."""
    engine = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_UNYIELDING_ADVANCE"], foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine, ME)
    _act(engine, "Adrenaline: Unyielding Advance")
    _ready(engine, AN)
    _act(engine, "Paired Bi Shou Assault", target=ME, actor_id=AN)
    action = _action(engine, me, "TAL_BERSERKER_BATTER")
    modes = []
    for _attempt in (1, 2):
        before = len(engine.events)
        typed_executor.resolve_opposed_check(
            typed_executor.Context(engine, me, action, getattr(engine, "_active_intent", None), {"numbers": {"pb": 4, "save_dc": 15}},
                                    [foe], foe, {}),
            foe, {"kind": "check", "ability": "STR", "skill": "Athletics"}, {"kind": "save", "ability": "STR"})
        modes += [(payload.get("actor") or {}).get("mode") for payload in _of(engine.events[before:], "CHECK_ROLLED")]
    assert modes == ["ADVANTAGE", "NORMAL"], f"the Advantage was spent by the first check, got {modes}"
    assert not me.turn_flags.get(berserker.UNYIELDING_CHECK)


def test_unyielding_advance_steps_toward_a_hostile_creature_that_enters_its_reach():
    engine = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_UNYIELDING_ADVANCE"], foe_at=(9, 6))
    me, foe = _me(engine), _foe(engine)
    _act(engine, "Adrenaline: Unyielding Advance")
    start = me.position
    asked = _asked(engine, {"rider_step": lambda options: [next(option for option in options if option != "cell:3,6")]})
    _ready(engine, AN)
    _act(engine, "Move to 5,6", actor_id=AN)
    assert foe.position == Position(x=5, y=6)
    assert not me.turn_flags.get(f"{berserker.UNYIELDING_STEP}:{foe.entity_id}"), \
        "a creature that stops 10 feet away never entered a 5-foot reach"

    _ready(engine, AN)
    events = _act(engine, "Move to 4,6", actor_id=AN)
    assert me.turn_flags.get(f"{berserker.UNYIELDING_STEP}:{foe.entity_id}") is not None, \
        "'when a hostile creature enters your reach, move 5 feet toward it' is offered"
    menus = [request for request in asked if "rider_step" in request["reaction_source_id"]]
    assert menus, "the step is asked of the player"
    assert "toward" in (menus[0].get("choice_trigger") or {}).get("prompt", ""), \
        (menus[0].get("choice_trigger") or {}).get("prompt", "")
    assert me.position != start, f"and it really moved (from {start} to {me.position})"
    assert engine.grid.distance_ft(me.position, foe.position) <= engine.grid.distance_ft(start, foe.position), \
        "'toward it': the step never ends farther from that creature"
    options = [option for option in menus[-1]["legal_option_ids"] if option != "cell:3,6"]
    assert options and all(engine.grid.distance_ft(Position(x=int(option.split(":")[1].split(",")[0]),
                                                     y=int(option.split(":")[1].split(",")[1])), foe.position)
                           <= engine.grid.distance_ft(start, foe.position) for option in options), \
        "every offered square is toward the creature that entered"

    plain = _fight(["TAL_BERSERKER_BATTER"], foe_at=(9, 6))
    plain_asked = _asked(plain, {"rider_step": lambda options: [options[0]]})
    _ready(plain, AN)
    _act(plain, "Move to 4,6", actor_id=AN)
    assert not [key for key in _me(plain).turn_flags if key.startswith(berserker.UNYIELDING_STEP)] and not plain_asked, \
        "no Adrenaline talent running, no step"


def test_unyielding_advance_counts_the_reach_its_fighter_really_has():
    """"your reach" is the fighter's own melee reach, so War-God Incarnation's +5 feet counts: a creature that stops 10 feet
    away enters that reach and not a 5-foot one."""
    talents = ["TAL_BERSERKER_BATTER", "TAL_BERSERKER_UNYIELDING_ADVANCE", WAR_GOD_TALENT]
    engine = _fight(talents, foe_at=(9, 6))
    me, foe = _me(engine), _foe(engine)
    _act(engine, WAR_GOD_BUTTON)
    _act(engine, "Adrenaline: Unyielding Advance")
    assert reach_bonus.melee_reach(engine, me) == 10, "'increase reach by 5 feet' while the Incarnation is on"
    asked = _asked(engine, {"rider_step": lambda options: [next(option for option in options if option != "cell:3,6")]})
    _ready(engine, AN)
    _act(engine, "Move to 5,6", actor_id=AN)
    assert me.turn_flags.get(f"{berserker.UNYIELDING_STEP}:{foe.entity_id}") is not None, "it entered the 10-foot reach"
    assert asked, "and the step is asked"
    plain = _fight(talents[:2], foe_at=(9, 6))
    _act(plain, "Adrenaline: Unyielding Advance")
    assert reach_bonus.melee_reach(plain, _me(plain)) == 5
    _ready(plain, AN)
    _act(plain, "Move to 5,6", actor_id=AN)
    assert not _me(plain).turn_flags.get(f"{berserker.UNYIELDING_STEP}:{_foe(plain).entity_id}")


# ------------------------------------------------------------------------------------------------ Meridian-Rending Blow
def test_meridian_rending_blow_offers_only_what_the_table_can_enforce_and_says_what_is_left_to_the_gm():
    from combat.typed_reactions import rules as block_rules

    record = MECH["TAL_BERSERKER_MERIDIAN_RENDING_BLOW"]
    printed = " ".join(record["riders"])
    assert "Creatures without recognizable anatomy are immune." in printed, "the anatomy immunity stays the GM's rule"
    assert "Wing" in printed and "Tail" in printed, "and so do the wing and tail rows of the printed table"
    assert not ((block_rules().get("features") or {}).get("TAL_BERSERKER_MERIDIAN_RENDING_BLOW") or {}).get("covers"), \
        "nothing about this ability is retired as covered any more"

    # Seed AUTO70-CRIT-13 is the one where this fighter's Batter scores the natural 20 the printed trigger needs.
    engine = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_MERIDIAN_RENDING_BLOW"], seed="AUTO70-CRIT-13", foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine)
    me.resources[FOCUS] = 1
    asked = _asked(engine, {"meridian_rending": lambda options: [options[0]]})
    events = _act(engine, "Batter", target=AN)
    assert any(payload.get("natural_result") == 20 for payload in _of(events, "ATTACK_ROLLED")), \
        "'You score a critical hit with a melee weapon' is the printed trigger"
    menus = [request for request in asked if "meridian_rending" in request["reaction_source_id"]]
    assert menus, "the structure is asked"
    assert list(menus[0]["legal_option_ids"]) == ["arm", "leg"], \
        "only the two structures the table enforces are offered; a wing or tail spends nothing for nothing"
    prompt = (menus[0].get("choice_trigger") or {}).get("prompt", "")
    assert "wing" in prompt and "recognizable anatomy" in prompt, f"and the rest is named as the GM's: {prompt!r}"
    assert me.resources[FOCUS] == 0, "Martial Focus was spent for the blow it asked about"
    rended = _held(foe, "condition:typed.rended_arm")
    assert rended and rended[0].data.get("rule") == {"attacks_have": "DISADVANTAGE"}, \
        f"the arm is disabled as printed: {rended and rended[0].data}"


# ------------------------------------------------------------------------------------------------ retired GM lines
@pytest.mark.parametrize("mid,sentence", [
    ("TAL_BERSERKER_BERSERK", "Apply this reduction before Resistance."),
    ("TAL_BERSERKER_BERSERK", "While active"),
    ("TAL_BERSERKER_SHATTER_EARTH", "Instead of attacking a creature, Batter the ground and expend Martial Focus (Exertion, Ruin)."),
    ("TAL_BERSERKER_WORLD_BREAKING_RAMPAGE", "Formation cores;"),
    (THE_BLOW, "ignore ordinary object Damage Thresholds"),
    (HEAVEN_CRUSHING, "Before rolling, choose three Exertion talents you know."),
])
def test_the_lines_the_table_enforces_no_longer_reach_a_fight_as_gm_work(mid, sentence):
    """Every one of these is either gone from the record or covered by its feature_blocks row, and the compiled
    character shows neither."""
    import re

    from combat.factory_compiler import _gm_lines
    from combat.typed_reactions import rules as block_rules

    record = MECH[mid]
    covers = [" ".join(str(text).lower().split())
              for text in ((block_rules().get("features") or {}).get(mid) or {}).get("covers") or []]
    kept = _gm_lines(record.get("riders") or [], record, record.get("effects") or [])
    assert " ".join(sentence.lower().split()) not in covers or " ".join(sentence.lower().split()) not in kept, \
        f"{mid} still hands the GM: {sentence}"
    if covers:
        for line in kept:
            for part in re.split(r"(?<=[.;])\s+", line):
                assert " ".join(part.lower().split()) not in covers, f"{mid}: covered text still reaches the fight: {part}"


def test_the_berserker_exertion_toggle_covers_every_exertion_talent_the_fighter_owns():
    engine = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_BONE_BREAKER", "TAL_BERSERKER_BELL_RINGER",
                     "TAL_BERSERKER_CULTIVATION_SUNDER", "TAL_BERSERKER_HEAVY_SWING", "TAL_BERSERKER_LEG_SMASHER",
                     "TAL_BERSERKER_HEAVEN_SHAKING_BATTER", "TAL_BERSERKER_BRUTAL_STRIKE",
                     "TAL_BERSERKER_REAPER_S_MOMENTUM"], foe_at=(4, 6))
    names = _names(engine)
    for talent in ("Bone-Breaker", "Bell-Ringer", "Cultivation Sunder", "Heavy Swing", "Leg-Smasher", "Heaven-Shaking Batter"):
        assert f"Exertion: {talent}" in names, talent
    assert "Exertion: none (no Exertion talent fires on a Batter)" in names
    # Brutal Strike and Reaper's Momentum change the attack roll, so they stay their own "Batter + ..." variant.
    assert not any(name.startswith("Exertion: Brutal") or name.startswith("Exertion: Reaper") for name in names)
    assert "Batter + Brutal Strike" in names and "Batter + Reaper’s Momentum" in names


def test_the_first_exertion_talent_a_fighter_owns_is_still_bone_breaker():
    """The default for a fighter who never pressed the toggle has always been the first talent in the registry, and Bone-Breaker
    was first before the registry existed (base commit 3324732c); an old saved fight relies on it."""
    assert list(exertion_talents.TALENTS)[0] == "bone_breaker", "the historical default order is preserved"
    engine = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_BELL_RINGER", "TAL_BERSERKER_BONE_BREAKER"], foe_at=(4, 6))
    me, foe = _me(engine), _hittable(engine)
    assert exertion_talents.armed(engine, me, berserker.BATTER_SOURCE) == ["bone_breaker"]
    assert {"Exertion: Bone-Breaker", "Exertion: Bell-Ringer"} <= _names(engine), "both buttons are offered"
    _act(engine, "Batter", target=AN)
    assert _mod(foe, "attack_roll", 1, "SUBTRACT_DIE"), "and the default talent is the one that fires"


def test_a_fighter_with_no_exertion_talent_gets_no_exertion_machinery():
    engine = _fight(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_DEATHLESS"])
    assert not exertion_talents.owned(engine, _me(engine).entity_id), "no Exertion talent, nothing to choose"
    assert not any(name.startswith("Exertion: ") for name in _names(engine))
    assert not any(name.startswith("Extended Exertion") for name in _names(engine))
    assert not any("extended_exertion" in action.source_definition_id for action in engine.action_catalog.values())


# ------------------------------------------------------------------------------------------------ persistence
def test_the_new_exertion_and_adrenaline_state_survives_a_table_commit_and_reload(tmp_path):
    """Everything this lane stores is an integer or a string: the standing Exertion choice, the armed second slot, the
    Adrenaline markers and the turn flags that carry them, and the target's own Exertion effects."""
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="AUTO70F1-SAVE",
                                       typed_bundles=(compile_character(_berserker_sheet(
                                           ["TAL_BERSERKER_BATTER", WAR_GOD_TALENT, "TAL_BERSERKER_BERSERK",
                                            "TAL_BERSERKER_EXTENDED_EXERTION", "TAL_BERSERKER_BONE_BREAKER",
                                            "TAL_BERSERKER_HEAVY_SWING"]), actor_id=ME),),
                                       roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine = session.engine

    def commit_for_turn(name, actor_id, target=None):
        """One real intent through the session: nothing here writes fight state behind the reducer."""
        candidate = next(c for c in engine.legal_candidates() if c.display_name == name and c.actor_id == actor_id
                         and (target is None or target in (c.target_ids or ())))
        session.mechanical.execute_intent(ActionIntent(intent_id=f"auto70-save-{len(engine.events)}",
                                                       decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                                       state_version=candidate.state_version, actor_id=actor_id,
                                                       target_ids=(target,) if target else (candidate.target_ids or ()),
                                                       destination=candidate.destination))

    def commit(name, actor_id=ME, target=None):
        commit_for_turn(name, actor_id, target)

    def next_turn_of_me():
        started = int(engine.state.actors[ME].turns_started)
        for _attempt in range(12):
            if int(engine.state.actors[ME].turns_started) > started:
                return
            commit_for_turn("End turn", engine.state.current_actor_id)
        raise AssertionError("the fight never came back around to this fighter")

    for _attempt in range(12):  # wait for the table's own turn order to reach this fighter
        if engine.state.current_actor_id == ME:
            break
        commit_for_turn("End turn", engine.state.current_actor_id)
    _ready(engine)

    commit(WAR_GOD_BUTTON)
    commit("Adrenaline: Berserk")
    next_turn_of_me()
    commit("Exertion: Heavy Swing")
    _asked(engine, {"exertion_set": ["bone_breaker"]})
    commit("Extended Exertion: a second Exertion talent (Bonus Action)")
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    armed = exertion_talents.extra_slot(engine, me, berserker.BATTER_SOURCE)
    flags = {key: value for key, value in me.turn_flags.items() if "exertion" in key or "adrenaline" in key}

    reloaded = persistence.load_match(session.match_id)
    assert reloaded.verify()["status"] == "PASS", "the reloaded fight verifies"
    engine = reloaded.engine
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert states.active(engine, me, "war_god_incarnation") is not None
    assert body_berserker.running_talents(me) == ["berserk"], "the Adrenaline marker survived"
    assert exertion_talents.standing(me) == ["heavy_swing"], "the standing Exertion choice survived"
    assert exertion_talents.extra_slot(engine, me, berserker.BATTER_SOURCE) == armed, "the armed second slot survived"
    assert {key: value for key, value in me.turn_flags.items() if "exertion" in key or "adrenaline" in key} == flags
    assert _has(me, "condition:typed.body_adrenaline_berserk")
    assert body_berserker.adrenaline_ac_penalty(engine, me) is None, "the Incarnation still waives the penalty after a reload"

    # And the reloaded fighter can still spend it: the attack resolves with both talents, as before the reload.
    _hittable(engine)
    _ready(engine)
    _act(engine, "Batter", target=AN)
    assert _has(_foe(engine), "condition:typed.reaction_denied"), "Heavy Swing still applies after the reload"
    assert _mod(_foe(engine), "attack_roll", 1, "SUBTRACT_DIE"), "and so does the paid Bone-Breaker"


def test_the_adrenaline_selection_order_survives_a_commit_and_reload_and_still_decides_the_expiry(tmp_path):
    """Which talent was selected last is state, so it has to survive the save like everything else.

    The order is kept as plain strings on the ACTIVE marker; if it were re-derived from the order the markers happen to
    be written in, a reloaded fight would quietly keep a different talent from an unreloaded one.
    """
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="AUTO70R1F2-SAVE",
                                       typed_bundles=(compile_character(_berserker_sheet(
                                           ["TAL_BERSERKER_BATTER", WAR_GOD_TALENT, "TAL_BERSERKER_BERSERK",
                                            "TAL_BERSERKER_MARAUDER"]), actor_id=ME),),
                                       roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine = session.engine

    def commit_for_turn(name, actor_id):
        candidate = next(c for c in engine.legal_candidates() if c.display_name == name and c.actor_id == actor_id)
        session.mechanical.execute_intent(ActionIntent(intent_id=f"auto70-order-{len(engine.events)}",
                                                       decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                                       state_version=candidate.state_version, actor_id=actor_id,
                                                       target_ids=candidate.target_ids or (), destination=candidate.destination))

    def commit(name, actor_id=ME):
        commit_for_turn(name, actor_id)

    def next_turn_of_me():
        started = int(engine.state.actors[ME].turns_started)
        for _attempt in range(12):
            if int(engine.state.actors[ME].turns_started) > started:
                return
            commit_for_turn("End turn", engine.state.current_actor_id)
        raise AssertionError("the fight never came back around to this fighter")

    for _attempt in range(12):
        if engine.state.current_actor_id == ME:
            break
        commit_for_turn("End turn", engine.state.current_actor_id)
    _ready(engine)
    commit(WAR_GOD_BUTTON)
    commit("Adrenaline: Marauder")  # selected first
    next_turn_of_me()
    commit("Adrenaline: Berserk")  # selected last, and the one that must survive
    engine.state.actors[ME].maximum_hp = engine.state.actors[ME].current_hp = 500

    reloaded = persistence.load_match(session.match_id)
    assert reloaded.verify()["status"] == "PASS", "the reloaded fight verifies"
    me = reloaded.engine.state.actors[ME]
    assert body_berserker.running_talents(me) == sorted(["berserk", "marauder"]), "both talents survived the save"
    pill = next(c for c in me.conditions.values() if c.condition_id == body_berserker.ACTIVE)
    assert (pill.data or {}).get("choices") == ["marauder", "berserk"], \
        f"the selection order survived as plain strings, got {(pill.data or {}).get('choices')!r}"

    # Expiring the second slot after the reload keeps the talent selected last, exactly as it would have before.
    state = next(c for c in me.conditions.values() if c.condition_id == WAR_GOD)
    state.expires_on = turn_token("start", me.entity_id, int(me.turns_started))
    me.turns_started += 1
    sweep_due(reloaded.engine, me, "START_OF_TURN")
    assert body_berserker.running_talents(me) == ["berserk"], \
        f"the reloaded fight keeps the last selection, got {body_berserker.running_talents(me)}"
    assert body_berserker.adrenaline_ac_penalty(reloaded.engine, me) == -2, "and the -2 AC penalty is back"
    pill = next(c for c in me.conditions.values() if c.condition_id == body_berserker.ACTIVE)
    assert (pill.data or {}).get("label") == "Adrenaline active (-2 AC)", "the pill agrees with the AC"

# ------------------------------------------------------------------------------------------------ who answers, at the table
def _service(tmp_path, talents, *, me_mode="MANUAL", foe_mode="MANUAL", seed="AUTO70R2F1", foe_at=(4, 6), ask=False,
             me_ac=None):
    """A real committed table: CombatService + TabletopService, both fighters' control modes as asked.

    Everything below goes through the shipped service (candidates, the menu, the pending-reaction transport and the
    save), so it exercises the control-mode POLICY and not just the engine's choice plumbing.
    """
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    me_sheet = json.loads(json.dumps(_berserker_sheet(talents)))
    if me_ac is not None:
        me_sheet["ability_scores_and_statistics"]["armor_class"]["base_value"] = me_ac
    bundles = [compile_character(me_sheet, actor_id=ME, reaction_plan={"ask": True} if ask else None),
               compile_character(_berserker_sheet([]), actor_id=AN)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    mid = combat._finish_factory_match(
        bundles, [ME, AN], {ME: "team:a", AN: "team:b"},
        {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}},
        arena, [ME], [AN], control_modes={ME: me_mode, AN: foe_mode},
        match_seed=seed, display_name="AUTO70r2f1", maximum_rounds=10)["match_id"]
    combat.set_controller_mode(mid, actor_id=ME, controller_mode=me_mode)
    combat.set_controller_mode(mid, actor_id=AN, controller_mode=foe_mode)
    _advance(table, mid, ME)
    return combat, table, mid


def _advance(table, mid, actor):
    """Bring the fight round to ``actor``'s turn: a manual actor ends its own turn, an AI one is auto-stepped."""
    for _ in range(16):
        state = table.state(mid)
        if state["menu"]["actor_id"] == actor:
            return
        if "end_turn" in state["menu"]:
            table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"],
                      state["menu"]["state_version"], state["last_sequence"], [])
        else:
            table.auto_step(mid, state["last_sequence"])
    raise AssertionError(f"{actor} never got the turn")


def _candidate(table, mid, label, target=None):
    return next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if label in g["label"]
                for o in g["options"] if target is None or target in o.get("target_ids", []))


def _drive(table, mid, cid, picks, *, limit=16):
    """Submit one real candidate and answer every question it raises; ``picks`` maps a choice id to option ids or None."""
    answers, prompts = [], []
    for _ in range(limit):
        state = table.state(mid)
        result = table.act(mid, cid, state["menu"]["decision_id"], state["menu"]["state_version"],
                          state["last_sequence"], list(answers))
        if result["status"] == "COMMITTED":
            return prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        picked = picks.get(prompt["context"]["reaction_source_id"])
        answer = {**prompt["context"], "selection": "USE" if picked else "DECLINE"}
        if picked:
            legal = [o["id"] for o in prompt["choice"]["options"]]
            assert set(picked) <= set(legal), f"{picked} is not on offer: {legal}"
            answer["option_ids"] = list(picked)
        answers.append(answer)
    raise AssertionError("too many prompts")


def _reloaded(tmp_path, mid):
    """The saved fight, committed and reloaded through a fresh service, with its replay verified."""
    from combat.gate5_service import CombatService

    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS", "a saved fight must replay"
    return loaded.engine


MENUS = ["TAL_BERSERKER_BATTER", THE_BLOW, "TAL_BERSERKER_BEAT_DOWN", "TAL_BERSERKER_HEAVY_SWING", "TAL_BERSERKER_LEG_SMASHER"]


@pytest.mark.parametrize("ask", [True, False])
def test_the_exertion_question_reaches_a_manual_player_on_their_own_turn_and_takes_their_answer(tmp_path, ask):
    """Checklist 9 at the service level: a MANUAL fighter is ASKED, on their own turn, and what they answer is what lands.

    The engine-level test proves the transport; this one proves the table's policy -- the question comes back as an
    answerable prompt routed to the fighter who owns the talents, with the printed decline available, and the talents the
    player picked are the ones the target really gets.
    """
    combat, table, mid = _service(tmp_path, [*MENUS, "TAL_BERSERKER_BLOODY_COUNTER"], ask=ask)
    if ask:
        assert any(r.get("ask") for r in _reloaded(tmp_path, mid).typed_reaction_rows[ME])
    cid = _candidate(table, mid, "The Blow Heaven Refused to Receive", AN)

    prompts = _drive(table, mid, cid, {"choice:needle.berserker_exertion_set": ["leg_smasher"]})

    menus = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.berserker_exertion_set"]
    assert len(menus) == 1, f"the manual player is asked exactly once, got {len(menus)}"
    menu = menus[0]
    assert menu["context"]["reactor_id"] == ME, "the fighter who owns the talents is the one asked"
    option_ids = [o["id"] for o in menu["choice"]["options"]]
    assert "leg_smasher" in option_ids and "heavy_swing" in option_ids, f"its own talents are on offer: {option_ids}"
    assert "The Blow Heaven Refused to Receive" in menu["moment"], f"the prompt names the ability: {menu['moment']!r}"

    engine = _reloaded(tmp_path, mid)
    foe = engine.state.actors[AN]
    assert any(e.event_type == "DAMAGE_COMMITTED" and AN in e.target_ids for e in engine.events)
    assert [m for m in foe.modifiers.values() if m.target_field == "speed_halved"], \
        "the talent the player chose is the one that landed"
    assert not [m for m in foe.modifiers.values() if m.target_field == "reaction_denied"], \
        "and the talent the player did not choose was not applied"


def test_a_manual_player_may_decline_the_exertion_question_and_nothing_is_applied_instead(tmp_path):
    """Checklist 9 and the chooser's own promise: a decline is a real answer, never a silent fallback to another talent."""
    combat, table, mid = _service(tmp_path, MENUS)
    cid = _candidate(table, mid, "The Blow Heaven Refused to Receive", AN)

    prompts = _drive(table, mid, cid, {"choice:needle.berserker_exertion_set": None})

    menus = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.berserker_exertion_set"]
    assert menus, "the player was asked"
    engine = _reloaded(tmp_path, mid)
    foe = engine.state.actors[AN]
    assert not list(foe.modifiers.values()), f"a declined set applies nothing, got {[(m.target_field, m.value) for m in foe.modifiers.values()]}"
    assert any(e.event_type == "DAMAGE_COMMITTED" for e in engine.events), "but the Blow's own hit still landed"


@pytest.mark.parametrize("use", [True, False])
@pytest.mark.parametrize("ask", [True, False])
def test_a_manual_fighter_is_still_asked_while_the_enemy_holds_the_current_turn(tmp_path, use, ask):
    """Enemy auto-step pauses for the injured player's War-God step, never for another own-turn action."""
    talents = [*MENUS, WAR_GOD_TALENT, "TAL_BERSERKER_BLOODY_COUNTER"]
    combat, table, mid = _service(tmp_path, talents, ask=ask, me_ac=1)
    _drive(table, mid, _candidate(table, mid, WAR_GOD_BUTTON), {})
    before = _reloaded(tmp_path, mid)
    start = before.state.actors[ME].position
    if ask:
        assert any(r.get("ask") for r in before.typed_reaction_rows[ME]), "the compiled Ask me plan is active"
    table.act(mid, table.state(mid)["menu"]["end_turn"], table.state(mid)["menu"]["decision_id"],
              table.state(mid)["menu"]["state_version"], table.state(mid)["last_sequence"], [])
    assert table.state(mid)["menu"]["actor_id"] == AN
    cid = _candidate(table, mid, "Batter", ME)
    _force_action(combat, table, mid, AN, cid)
    snapshot = _reloaded(tmp_path, mid).state.model_dump(mode="json")
    answers, prompts = [], []
    for _ in range(16):
        state = table.state(mid)
        assert state["menu"]["actor_id"] == AN, "the enemy remains current throughout the player's answers"
        result = table.auto_step(mid, state["last_sequence"], list(answers))
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        assert _reloaded(tmp_path, mid).state.model_dump(mode="json") == snapshot, "a preview pause commits nothing"
        prompt = result["reaction"]
        prompts.append(prompt)
        assert prompt["context"]["reactor_id"] == ME
        answer = {**prompt["context"], "selection": "DECLINE", "option_ids": []}
        if ask and prompt["context"]["reaction_source_id"] == "reaction:typed.TAL_BERSERKER_BLOODY_COUNTER":
            answer["selection"] = "USE" if use else "DECLINE"
        if prompt["context"]["reaction_source_id"] == "choice:needle.rider_step":
            assert "War-God Incarnation" in prompt["moment"]
            assert "Batter" in prompt["moment"] and before.state.actors[ME].display_name in prompt["moment"]
            if use:
                option = next(o["id"] for o in prompt["choice"]["options"] if o["id"] != f"cell:{start.x},{start.y}")
                answer.update(selection="USE", option_ids=[option])
        answers.append(answer)
    else:
        pytest.fail("the enemy attack stalled after the player's answers")
    assert len([p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.rider_step"]) == 1, \
        (list(combat._load_session(mid).engine.typed_ask_reactors), [p["context"]["reaction_source_id"] for p in prompts])
    if ask:
        assert any(p["context"]["reaction_source_id"] == "reaction:typed.TAL_BERSERKER_BLOODY_COUNTER" for p in prompts)
    engine = _reloaded(tmp_path, mid)
    assert engine.state.current_actor_id == AN
    assert (engine.state.actors[ME].position != start) is use
    assert engine.grid.distance_ft(start, engine.state.actors[ME].position) <= 10
    assert any(e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids for e in engine.events)
    if ask:
        assert engine.state.actors[ME].reaction_available is not use, "Ask me Use spends the Reaction; Decline keeps it"


def test_an_ai_fighter_answers_its_own_exertion_question_without_stalling(tmp_path):
    """Checklist 9's other side: an AI actor decides by itself, so the set resolves with no player present at all."""
    combat, table, mid = _service(tmp_path, [*MENUS, "TAL_BERSERKER_BLOODY_COUNTER"],
                                  me_mode="MANUAL", foe_mode="LOCAL_AUTO", ask=True)
    cid = _candidate(table, mid, "The Blow Heaven Refused to Receive", AN)  # while it is still a manual fighter
    _force_action(combat, table, mid, ME, cid)

    state = table.state(mid)
    result = table.auto_step(mid, state["last_sequence"])
    assert result["status"] == "COMMITTED", \
        f"the AI fighter's own turn resolves without waiting for a player, got {result['status']}"

    engine = _reloaded(tmp_path, mid)
    assert any(e.event_type == "DAMAGE_COMMITTED" for e in engine.events), "and its attack really landed"
    assert _mods(engine.state.actors[AN], "speed_halved"), "the AI actually selected Leg-Smasher"
    assert _has(engine.state.actors[AN], "condition:typed.reaction_denied"), "and Heavy Swing, not an empty automatic set"


def _force_action(combat, table, mid, actor, cid):
    """An AI fighter that uses the printed ability we are asking about, so the case is not about what it chose to do."""
    from combat.gate4_adapters import ManualControllerAdapter

    real = combat.controller

    class FixedController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _context: (cid, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = FixedController()
    combat.set_controller_mode(mid, actor_id=actor, controller_mode="LOCAL_AUTO")

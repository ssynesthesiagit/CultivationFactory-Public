"""Well of Hours (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Well of Hours: Time Debt, the Hour Comes Due, Temporal Arrears, Deferred
Consequences, CL3 Ripple of Before, CL6 Borrowed Second, CL10 Hourglass Mark, CL14 Refuse the Moment, CL18 The Well Has No Bottom,
Interaction Closure). No Spheres 5e or D&D 5.5e counterpart. Ownership rows: combat/rules/feature_blocks.d/riders_c8.json (Ripple of
Before, Borrowed Second, Refuse the Moment: the plug-in answers).

Time Debt (resource:named.time_debt, maximum = Proficiency Bonus, 0 at the start). A gain past the maximum sets it to the maximum and
the Hour Comes Due at the start of your next turn. At the end of one of your turns in which you neither gained Time Debt nor activated
a Well of Hours feature, 1 Time Debt goes. The Hour Comes Due at the start of your turn while it is at its maximum (once a turn): until
the end of that turn your Speed is halved, you take no Reactions and no Well of Hours feature is offered; 1 Time Debt goes at the end of
that turn. Temporal Arrears (resource:named.temporal_arrears, maximum = Proficiency Bonus): when a Well of Hours field ends your Time
Debt becomes Arrears; while you have Arrears your Resonance cannot rise above its maximum minus the Arrears (never below half the
maximum) -- any Resonance above that is lost.

What runs:
  * Ripple of Before: Echo of the Chosen Step -- once on each of your turns, after one of your own moves of at least 10 feet, you may
    record where it began as your Before-Space (asked); "Echo of the Chosen Step" (Bonus Action, 1 Resonance, 1 Time Debt) returns you
    there if it is a legal space within 30 feet, without provoking and without teleporting.
  * Borrowed Second (Bonus Action, 3 Resonance, once a turn): "Borrowed Second: Slip Away" (half your Speed without provoking), "Rise
    and Step" (stand from Prone, 10 more feet of movement), "Disengage", "Search", "Soul Gaze" (Soul Gaze's own cost too) -- 1 Time
    Debt; "Weapon Strike" (one attack with a weapon on a creature bearing your Resonance Mark within its reach or range) and "Mind
    Spike" (on a Resonance Marked creature, one damage die fewer, at least one) -- 2 Time Debt. Pay the Second Back (asked at the start
    of your turn while you have Time Debt): Speed 0, no Reactions, no teleport or self-moving ability and no Borrowed Second until the
    start of your next turn; 2 Time Debt go.
  * Hourglass Mark (Action, 60 feet, 5 Resonance, 1 minute): Wisdom save; failed -- the Hourglass Mark (a special Resonance Mark: it
    replaces your Resonance Mark on that creature and your Resonance Mark replaces it; one at a time), which it repeats the save
    against at the end of each of its turns; succeeded -- your Spiritual Pressure effect until the start of your next turn. Once a
    round (1 Resonance and 1 Time Debt, asked): Delayed Strike (subtract 1d6 from its attack roll after the d20) or Delayed Technique
    (a creature saving against its technique adds 1d6). "Break the Glass" (Action) for the marked creature or a creature adjacent to
    it: its best of Arcana, Insight, Sleight of Hand or a Cultivation Check against your DC ends the mark.
  * Refuse the Moment (Reaction, 6 Resonance, 2 Time Debt, asked): you or a creature you can see within 30 feet would take damage
    (all the damage of that attack or packet waits), gain a condition from a failed save, or become Grappled, Restrained or
    Unconscious. The consequence arrives at the end of that creature's next turn: the damage with its own type and source (healing
    it receives meanwhile can pay the deferred damage off first, asked), the condition from its original source. One Deferred
    Consequence from you at a time: a new one releases the old one first.
  * The Well Has No Bottom (Action, 90 feet, 30-foot sphere, 10 Resonance, Concentration): the field. The creatures you choose in it
    (asked; newcomers at the start of your turns) get a Round Image (space, Hit Points, ordinary conditions) renewed at the start of
    each of your turns. Friendly Current: a chosen ally starting its turn in it picks one (asked): a 10-foot step without provoking,
    standing from Prone without spending movement, 2 x PB Temporary Hit Points, or one ordinary Spiritual Pressure effect on it
    suppressed until the end of the turn. Hostile Undertow: the first time each round a hostile creature in it moves, attacks,
    activates a technique or takes a Reaction it makes a Wisdom save -- failed, Delayed Strike or Delayed Technique on that attack or
    technique for free and your Resonance Mark until the end of its next turn; succeeded, Speed -10 or no Reactions until the start of
    its next turn (asked); two successes make it immune for the activation. Return to the Bell (once, your Reaction, asked): when a
    chosen creature in it takes damage, gains an ordinary condition or is pushed or pulled, it returns to its Round Image (its space or
    the nearest legal one within 15 feet, the recorded Hit Points if higher, ordinary conditions gained since removed); your Time Debt
    becomes its maximum and you take 3d10 Psychic damage nothing reduces. Drink the Unlived Hour: once on each of your turns, Borrowed
    Second can cost 1 Time Debt instead of the Resonance (asked); its Weapon Strike or Mind Spike only once in the activation. Collapse
    of the Well: when it ends, Deferred Consequences on creatures in it arrive and your Time Debt becomes Temporal Arrears; it cannot be
    activated again in the fight (the clearing procedure takes 10 quiet minutes).

Plug-in surface: effects well_hourglass, well_field, well_borrowed, well_echo, well_break_glass; hooks event, turn_start_choice, turn_end,
technique_start, before_attack, d20_bonus, save, after_save_resolved, mark_applied, incoming_damage, condition_attempt, healing_assigned,
candidate_allowed, compile_actions, match_start, additional_actions. Public helper: ``gain_debt``. Shared helpers used: spirit_traditions
(row/context/numbers/feature_action/feature_of/action_named/run_action/mind_spike/save/remove/pick_creature/can_react/routes/
choose_route/data_of/set_data/suppress/delay_condition/land_delayed_condition/landing), needle (ask/checkpoint_id/step_to),
rider_movement.step, life_state.restore_hp, eye_common.skill, ability_checks.ability_modifier, stealth.sees, typed_executor.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.well_of_hours.feature."
RIPPLE = TRADITION + "ripple_of_before"
BORROWED = TRADITION + "borrowed_second"
HOURGLASS = TRADITION + "hourglass_mark"
REFUSE = TRADITION + "refuse_the_moment"
WELL = TRADITION + "the_well_has_no_bottom"
DEBT = "resource:named.time_debt"
ARREARS = "resource:named.temporal_arrears"
RESONANCE = "resource:core.resonance"
HOUR = "condition:typed.hour_comes_due"
PAYING = "condition:typed.paying_the_second_back"
DEFERRED = "condition:typed.deferred_consequence"
FIELD = "condition:typed.well_of_hours_field"
HOURGLASS_MARK = "Hourglass Mark"
BREAK_GLASS = "system:combat.break_the_glass"
ORDINARY = ("blinded", "charmed", "deafened", "frightened", "grappled", "incapacitated", "paralyzed", "petrified", "poisoned", "prone",
            "restrained", "stunned", "unconscious", "life_unconscious", "spirit_awakening_pressure")
_ARRIVING = "_c8_well_arriving"      # a deferred consequence landing (nothing defers it again)
_BACKLASH = "_c8_well_backlash"      # Return to the Bell's 3d10 (no Well of Hours feature reduces it)
_FAILED = "_c8_well_failed_save"     # (subject, source, actor) of the save that just failed, for "a condition from a failed save"
_PACKET = "_c8_well_packet"          # the attack or packet whose damage is waiting: its later packets wait with it
_STRIKE = "_c8_well_strike"          # {attacker id: source} -- a free Delayed Strike from Hostile Undertow for its next attack roll
_TECHNIQUE = "_c8_well_technique"    # {actor id: owner id} -- a free Delayed Technique from Hostile Undertow for this activation
_DELAYED_ROLL = "_c8_well_delayed_roll"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _rows(effects: Any):
    for entry in effects or []:
        if isinstance(entry, dict):
            yield entry
            for key in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                yield from _rows(entry.get(key))


def _path_ft(engine: Any, path: list[dict[str, Any]]) -> int:
    from ..gate2_runtime_models import Position

    cells = [Position(x=int(p["x"]), y=int(p["y"])) for p in path]
    return sum(engine.grid.distance_ft(a, b) for a, b in zip(cells, cells[1:]))


def _owns(engine: Any, actor: Any, feature: str) -> bool:
    kind = feature.rsplit(".", 1)[-1]
    if st.row(engine, actor, kind) is not None:
        return True
    return any(st.feature_of(engine.action_catalog[a]) == feature for a in actor.action_ids if a in engine.action_catalog)


def _wells(engine: Any) -> list[Any]:
    return [a for a in engine.state.actors.values() if a.active and DEBT in (a.resource_maximums or {})]


def _numbers(engine: Any, actor: Any) -> dict[str, Any]:
    return st.numbers(engine, actor)


def _ctx(engine: Any, owner: Any, feature: str, targets: list[Any], intent: Any = None) -> Any:
    return st.context(engine, owner, st.feature_action(engine, owner, feature), targets, _numbers(engine, owner), intent or engine._active_intent)


def _held(creature: Any, condition_id: str, source: str | None = None) -> list[Any]:
    return [c for c in creature.conditions.values() if c.condition_id == condition_id and (source is None or c.source_actor_id == source)]


def _hour(actor: Any) -> bool:
    return bool(_held(actor, HOUR))


def _busy(actor: Any) -> None:
    actor.turn_flags["c8_well_busy"] = True  # "a turn in which you ... gained Time Debt [or] activated a Well of Hours feature"


# ---------------------------------------------------------------------------------------------------------- Time Debt
def gain_debt(engine: Any, owner: Any, amount: int, source: str) -> None:
    """Time Debt up to its maximum; past it, the maximum and "the Hour Comes Due at the start of your next turn"."""
    top = int(owner.resource_maximums.get(DEBT, 0) or 0)
    if top <= 0 or amount <= 0:
        return
    _busy(owner)
    now = int(owner.resources.get(DEBT, 0) or 0)
    if now + amount > top:
        owner.turn_flags["_round_c8_well_due"] = True
    if min(top, now + amount) > now:
        engine._gain_resource(owner, DEBT, min(top, now + amount) - now, source)


def _lose_debt(engine: Any, owner: Any, amount: int, source: str) -> None:
    now = int(owner.resources.get(DEBT, 0) or 0)
    if now and amount:
        engine._spend_resource(owner, DEBT, min(now, amount), source)


def _cut_movement(engine: Any, actor: Any, feet: int, source: str) -> None:
    if engine.state.current_actor_id != actor.entity_id or feet <= 0 or actor.movement_remaining_ft <= 0:
        return
    cut = min(feet, int(actor.movement_remaining_ft))
    actor.movement_remaining_ft -= cut
    engine._append_event("MOVEMENT_GRANTED", source, actor_id=actor.entity_id, payload={"distance_ft": -cut})


@hook("turn_start_choice")
def well_turn_start(engine: Any, actor: Any) -> None:
    """The Hour Comes Due; Pay the Second Back; the field's Round Images and newcomers; Friendly Current."""
    if DEBT in (actor.resource_maximums or {}):
        _hour_comes_due(engine, actor)
        _pay_the_second_back(engine, actor)
        field = field_of(actor)
        if field is not None:
            _renew_images(engine, actor, field)
    _friendly_current(engine, actor)


def _hour_comes_due(engine: Any, owner: Any) -> None:
    top = int(owner.resource_maximums.get(DEBT, 0) or 0)
    due = owner.turn_flags.pop("_round_c8_well_due", False)
    if top <= 0 or not (due or int(owner.resources.get(DEBT, 0) or 0) >= top):
        return
    owner.turn_flags["c8_well_hour_turn"] = True
    engine._apply_condition(owner, HOUR, RIPPLE, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"rule": {"no_reactions": True}, "label": "The Hour Comes Due: Speed halved, no Reactions and no Well of Hours "
                                                                           "feature until the end of this turn"})
    before = engine._effective_speed(owner)
    _te().run_effects(_ctx(engine, owner, RIPPLE, [owner]), [{"type": "speed", "applies_to": "self", "halved": True, "duration": {"kind": "until_end_of_turn"},
                                                             "evidence": "your Speed is halved"}])
    _cut_movement(engine, owner, before - engine._effective_speed(owner), RIPPLE)
    note(engine, RIPPLE, owner, f"The Hour Comes Due for {owner.display_name}: Time Debt at its maximum.")


def _pay_the_second_back(engine: Any, owner: Any) -> None:
    from . import needle

    if not _owns(engine, owner, BORROWED) or int(owner.resources.get(DEBT, 0) or 0) <= 0:
        return
    top = int(owner.resource_maximums.get(DEBT, 0) or 0)
    chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "PAY_THE_SECOND_BACK", owner.entity_id), owner,
                        "choice:needle.well.pay_back", ["pay"], labels={"pay": "Pay the Second Back: remove 2 Time Debt"},
                        preferred=["pay"], allow_decline=True,
                        default="first", name="Borrowed Second (Pay the Second Back)",
                        feature_id=BORROWED, prompt="Pay the Second Back? Until the start of your next turn your Speed is 0, you take no Reactions, "
                                                   "you cannot move yourself or teleport, and you cannot use Borrowed Second. Then 2 Time Debt go.")
    if not chosen or chosen[0] != "pay":
        return
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, owner, BORROWED, independent=True):
        engine._apply_condition(owner, PAYING, BORROWED, owner.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"rule": {"speed_zero": True, "no_reactions": True, "no_teleport": True},
                                      "label": "Paying the Second Back: Speed 0, no Reactions, no moving yourself and no Borrowed Second until the start of your next turn"})
        _cut_movement(engine, owner, int(owner.movement_remaining_ft), BORROWED)
        owner.reaction_available = False
        _lose_debt(engine, owner, 2, BORROWED)


@hook("technique_used")
def technique_over(ctx: Any) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, _TECHNIQUE)
    (ctx.engine.__dict__.get(_TECHNIQUE) or {}).pop(ctx.actor.entity_id, None)  # Delayed Technique is for that activation only


@hook("turn_end")
def well_turn_end(engine: Any, actor: Any) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _STRIKE)
    preserve_pending(engine, _TECHNIQUE)
    (engine.__dict__.get(_STRIKE) or {}).pop(actor.entity_id, None)
    (engine.__dict__.get(_TECHNIQUE) or {}).pop(actor.entity_id, None)
    for held in _held(actor, HOUR):
        st.remove(engine, actor, held, "TURN_ENDED")
    if DEBT in (actor.resource_maximums or {}):
        if actor.turn_flags.get("c8_well_hour_turn"):
            _lose_debt(engine, actor, 1, RIPPLE)  # "remove 1 Time Debt at the end of that turn"
        if not actor.turn_flags.get("c8_well_busy"):
            _lose_debt(engine, actor, 1, RIPPLE)  # "neither gained Time Debt nor activated a Well of Hours feature"
    for held in list(_held(actor, DEFERRED)):
        if actor.turns_started > int((held.data or {}).get("turn") or 0):
            _arrive(engine, actor, held)
    for held in [c for c in actor.conditions.values() if c.condition_id == _te().mark_condition_id(HOURGLASS_MARK, c.source_actor_id)]:
        owner = engine.state.actors.get(held.source_actor_id)
        if owner is not None and st.save(_ctx(engine, owner, HOURGLASS, [actor]), actor, "wis"):
            continue
        st.remove(engine, actor, held, "SAVED")  # the end-of-turn repeat save ends the mark on a success


@hook("technique_start")
def well_activated(engine: Any, actor: Any, action: Any) -> None:
    if str(st.feature_of(action)).startswith(TRADITION):
        _busy(actor)
    _undertow_activity(engine, actor, "technique", action)


# ---------------------------------------------------------------------------------------------------------- Temporal Arrears
def _resonance_cap(actor: Any) -> int | None:
    arrears = int(actor.resources.get(ARREARS, 0) or 0)
    top = int(actor.resource_maximums.get(RESONANCE, 0) or 0)
    return top - min(arrears, top // 2) if arrears and top else None


def _trim_resonance(engine: Any, actor: Any) -> None:
    cap = _resonance_cap(actor)
    if cap is not None and int(actor.resources.get(RESONANCE, 0) or 0) > cap:
        engine._spend_resource(actor, RESONANCE, int(actor.resources[RESONANCE]) - cap, WELL)


# ---------------------------------------------------------------------------------------------------------- events
@hook("event")
def well_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    payload = kwargs.get("payload") or {}
    if event_type == "RESOURCE_GAINED" and actor is not None and payload.get("resource_id") == RESONANCE:
        _trim_resonance(engine, actor)
    if event_type == "ZONE_REMOVED":
        for owner in _wells(engine):
            field = field_of(owner)
            if field is not None and str(payload.get("zone_id") or "") == str((field.data or {}).get("zone_id")):
                _collapse(engine, owner, field)
    if event_type == "MOVEMENT_COMMITTED" and actor is not None:
        path = [p for p in payload.get("path") or [] if isinstance(p, dict)]
        if not payload.get("forced") and not payload.get("teleport"):
            _before_space(engine, actor, path)
            _undertow_activity(engine, actor, "move", None, path=path)
        elif payload.get("forced"):
            _bell_trigger(engine, actor, "is moved")
    if event_type == "REACTION_RESOLVED" and actor is not None:
        _undertow_activity(engine, actor, "reaction", None)
    if event_type == "DAMAGE_COMMITTED":
        for target_id in kwargs.get("target_ids") or ():
            target = engine.state.actors.get(target_id)
            if target is not None and engine.__dict__.get(_BACKLASH) != target_id:
                _bell_trigger(engine, target, "takes damage")
    if event_type == "CONDITION_APPLIED":
        name = str(payload.get("condition_id") or "").removeprefix("condition:typed.")
        if any(name == o or name.startswith(o + ".") for o in ORDINARY):
            for target_id in kwargs.get("target_ids") or ():
                target = engine.state.actors.get(target_id)
                if target is not None:
                    _bell_trigger(engine, target, f"gains {name.split('.')[0].replace('_', ' ')}")


# ---------------------------------------------------------------------------------------------------------- Ripple of Before
def _before_space(engine: Any, owner: Any, path: list[dict[str, Any]]) -> None:
    """Ripple of Before: once a turn, right after moving at least 10 feet, the Well may record the space where that move began."""
    from . import needle

    if (engine.state.current_actor_id != owner.entity_id or st.row(engine, owner, "ripple_of_before") is None or owner.turn_flags.get("c8_before_space")
            or len(path) < 2 or _path_ft(engine, path) < 10 or not owner.bonus_action_available
            or int(owner.resources.get(RESONANCE, 0) or 0) < 1 or _hour(owner)):
        return
    start = path[0]
    chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "BEFORE_SPACE", owner.entity_id), owner, "choice:needle.well.before_space",
                        ["record"], labels={"record": f"Record {start['x']},{start['y']} as your Before-Space"}, preferred=["record"], allow_decline=True,
                        name="Ripple of Before (Echo of the Chosen Step)", feature_id=RIPPLE,
                        prompt=f"Echo of the Chosen Step: record {start['x']},{start['y']}, where this move began, as your Before-Space until the start of your next turn?")
    if chosen and chosen[0] == "record":
        owner.turn_flags["c8_before_space"] = [int(start["x"]), int(start["y"]), int(start.get("z", 0))]


def _before_cell(engine: Any, owner: Any) -> Any:
    from ..gate2_runtime_models import Position

    spot = owner.turn_flags.get("c8_before_space")
    if not spot:
        return None
    cell = Position(x=int(spot[0]), y=int(spot[1]), z=int(spot[2]) if len(spot) > 2 else 0)
    legal = engine.grid.volume_legal(cell, footprint=engine._footprint(owner), occupied_cells=engine._occupied_volumes_except(owner.entity_id))
    return cell if legal and cell != owner.position and engine.grid.distance_ft(owner.position, cell) <= 30 else None


@effect("well_echo")
def echo_of_the_chosen_step(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import step_to

    engine, owner = ctx.engine, ctx.actor
    cell = _before_cell(engine, owner)
    if cell is None:
        return
    engine._spend_resource(owner, RESONANCE, 1, RIPPLE)
    step_to(engine, owner, cell, RIPPLE)  # conceptual translation: no Opportunity Attack, not a teleport
    owner.turn_flags.pop("c8_before_space", None)
    gain_debt(engine, owner, 1, RIPPLE)


# ---------------------------------------------------------------------------------------------------------- Borrowed Second
OPTIONS = {"slip": ("Slip Away", "move up to half your Speed without provoking Opportunity Attacks", 1),
           "rise": ("Rise and Step", "stand up from Prone and move up to 10 more feet this turn", 1),
           "disengage": ("Disengage", "take the Disengage action", 1),
           "search": ("Search", "take the Search action", 1),
           "gaze": ("Soul Gaze", "use Soul Gaze (and pay its own cost)", 1),
           "strike": ("Weapon Strike", "one attack with a weapon against a creature bearing your Resonance Mark within its reach or range", 2),
           "spike": ("Mind Spike", "Mind Spike against a creature bearing your Resonance Mark, one damage die fewer (at least one)", 2)}


def _weapons(engine: Any, owner: Any, target: Any) -> list[Any]:
    return [a for a in (engine.action_catalog.get(i) for i in owner.action_ids) if a is not None and ((a.parameters or {}).get("typed") or {}).get("weapon")
            and "#" not in a.source_definition_id and engine._target_in_range(owner, target, a)]


def _can_drink(engine: Any, owner: Any) -> bool:
    return field_of(owner) is not None and not owner.turn_flags.get("c8_drank")


def _pay(engine: Any, owner: Any, intent: Any) -> bool:
    """3 Resonance, or inside your field once a turn "gain 1 Time Debt to use Borrowed Second without spending Resonance"."""
    from . import needle

    ways = [*(["drink"] if _can_drink(engine, owner) else []), *(["resonance"] if int(owner.resources.get(RESONANCE, 0) or 0) >= 3 else [])]
    if not ways:
        return False
    pick = ways[0]
    if len(ways) > 1:
        chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "DRINK_THE_UNLIVED_HOUR", owner.entity_id), owner, "choice:needle.well.drink",
                            ways, labels={"drink": "Drink the Unlived Hour: gain 1 Time Debt instead", "resonance": "Pay 3 Resonance"},
                            preferred=["drink"], name="The Well Has No Bottom (Drink the Unlived Hour)", feature_id=WELL,
                            prompt="Borrowed Second: pay 3 Resonance, or Drink the Unlived Hour (1 Time Debt, once on each of your turns)?")
        pick = chosen[0] if chosen and chosen[0] in ways else ways[0]
    if pick == "drink":
        owner.turn_flags["c8_drank"] = True
        gain_debt(engine, owner, 1, WELL)
    else:
        engine._spend_resource(owner, RESONANCE, 3, BORROWED)
    return True


@effect("well_borrowed")
def borrowed_second(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, owner, mode = ctx.engine, ctx.actor, str(row.get("mode") or "")
    if mode not in OPTIONS or not _pay(engine, owner, ctx.intent):
        return
    owner.turn_flags["c8_borrowed_used"] = True
    _busy(owner)
    target = ctx.target if ctx.target is not None and ctx.target is not owner else None
    if mode == "slip":
        spots = {c: v for c, v in st.routes(engine, owner, engine._effective_speed(owner) // 2).items() if c != owner.position}
        path = st.choose_route(engine, owner, spots, ctx.intent, checkpoint="BORROWED_SLIP", prompt="Borrowed Second: move where (without provoking)?",
                               name="Borrowed Second", feature=BORROWED, stay=False) if spots else None
        if path is not None:
            from .rider_movement import step

            step(engine, owner, list(path), BORROWED)
    elif mode == "rise":
        for held in [c for c in owner.conditions.values() if str(c.condition_id).endswith(".prone")]:
            st.remove(engine, owner, held, "STOOD_UP")
        owner.movement_remaining_ft += 10
        engine._append_event("MOVEMENT_GRANTED", BORROWED, actor_id=owner.entity_id, payload={"distance_ft": 10})
    elif mode == "disengage":
        owner.turn_flags["disengaged"] = True
    elif mode == "search":
        search = st.action_named(engine, owner, "Search")
        if search is not None:
            st.run_action(engine, owner, search, owner, ctx.intent)
    elif mode == "gaze" and target is not None:
        gaze = st.action_named(engine, owner, "Soul Gaze")
        if gaze is not None and int(owner.resources.get(RESONANCE, 0) or 0) >= 1:
            engine._spend_resource(owner, RESONANCE, 1, st.feature_of(gaze))
            st.run_action(engine, owner, gaze, target, ctx.intent)
    elif mode in ("strike", "spike") and target is not None:
        field = field_of(owner)
        if field is not None:
            st.set_data(owner, field, struck=True)  # "only once during the entire activation of The Well Has No Bottom"
        if mode == "spike":
            _spike(engine, owner, target, ctx.intent)
        else:
            weapons = _weapons(engine, owner, target)
            weapon = weapons[0] if weapons else None
            if len(weapons) > 1:
                chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "BORROWED_WEAPON", target.entity_id), owner, "choice:needle.well.weapon",
                                    [w.source_definition_id for w in weapons], labels={w.source_definition_id: w.display_name for w in weapons},
                                    preferred=[weapons[0].source_definition_id], name="Borrowed Second", feature_id=BORROWED, prompt="Borrowed Second: strike with which weapon?")
                weapon = next((w for w in weapons if chosen and w.source_definition_id == chosen[0]), weapons[0])
            if weapon is not None:
                st.run_action(engine, owner, weapon, target, ctx.intent)
    gain_debt(engine, owner, OPTIONS[mode][2], BORROWED)


def _spike(engine: Any, owner: Any, target: Any, intent: Any) -> None:
    """"reducing its damage by one die, to a minimum of one die"."""
    from factory_authoring.typed_mechanics import dice_for_cl

    spike = st.action_named(engine, owner, "Mind Spike")
    if spike is None:
        return
    typed = (spike.parameters or {}).get("typed") or {}
    counts = [int((dice_for_cl(e.get("dice_by_cl"), (typed.get("numbers") or {}).get("cl")) or e.get("dice") or {}).get("count") or 1)
              for e in _rows(typed.get("effects")) if e.get("type") == "damage"]
    st.mind_spike(engine, owner, target, intent, dice_delta=-1 if min(counts or [2]) > 1 else 0)


# ---------------------------------------------------------------------------------------------------------- Hourglass Mark
def _hourglass_owner(creature: Any) -> Any:
    """The creature whose Hourglass Mark this one bears (its id), or None."""
    return next((c.source_actor_id for c in creature.conditions.values() if c.condition_id == _te().mark_condition_id(HOURGLASS_MARK, c.source_actor_id)), None)


@effect("well_hourglass")
def hourglass_mark(ctx: Any, row: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    target = next(iter(_te()._default_subject(ctx, row, harmful=True)), None)
    if target is None or not target.active:
        return
    _busy(owner)
    if not st.save(ctx, target, "wis"):
        _te().run_effects(st.context(engine, owner, ctx.action, [target], ctx.numbers, ctx.intent),
                          [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "It suffers one ordinary Spiritual Pressure effect until your next turn starts."}])
        return
    mark_id = _te().mark_condition_id(HOURGLASS_MARK, owner.entity_id)
    for creature in engine.state.actors.values():  # only one Hourglass Mark is held; a new one ends the previous
        for held in [c for c in creature.conditions.values() if c.condition_id == mark_id]:
            st.remove(engine, creature, held, "REPLACED")
    _te().run_effects(st.context(engine, owner, ctx.action, [target], ctx.numbers, ctx.intent),
                      [{"type": "mark", "mark": HOURGLASS_MARK, "applies_to": "target", "duration": {"kind": "minutes", "amount": 1},
                        "evidence": "The creature gains your Hourglass Mark."}])


@hook("mark_applied")
def one_special_mark(ctx: Any, name: str, subject: Any) -> None:
    """Hourglass Mark: applying it replaces another Resonance Mark the owner placed on that creature, and an ordinary Resonance
    Mark applied to that creature replaces the Hourglass Mark."""
    owner = ctx.actor.entity_id
    slug = str(name or "").strip().lower()
    if slug == HOURGLASS_MARK.lower():
        drop = _te().mark_condition_id("Resonance", owner)
    elif slug in ("resonance", "resonance mark"):
        drop = _te().mark_condition_id(HOURGLASS_MARK, owner)
    else:
        return
    for held in [c for c in subject.conditions.values() if c.condition_id == drop]:
        st.remove(ctx.engine, subject, held, "REPLACED")


def _delay_once(engine: Any, owner: Any) -> bool:
    return (int(owner.turn_flags.get("_round_c8_hourglass_delay") or 0) != engine.state.round_number and int(owner.resources.get(RESONANCE, 0) or 0) >= 1
            and not _hour(owner) and owner.active)


def _ask_delay(engine: Any, owner: Any, intent: Any, kind: str, prompt: str, preferred: bool, subject: Any) -> bool:
    from . import needle

    labels = {"strike": "Delayed Strike: subtract 1d6 from the roll", "technique": "Delayed Technique: this creature adds 1d6 to its save"}
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, f"HOURGLASS_{kind.upper()}", subject.entity_id, len(engine.events)), owner,
                        f"choice:needle.well.hourglass_{kind}", [kind], labels={kind: labels[kind]}, preferred=[kind] if preferred else [], allow_decline=True,
                        default="first" if preferred else "decline", name="Hourglass Mark", feature_id=HOURGLASS, target_id=subject.entity_id,
                        prompt=f"{prompt} Spend 1 Resonance and gain 1 Time Debt?")
    if not chosen or chosen[0] != kind:
        return False
    owner.turn_flags["_round_c8_hourglass_delay"] = engine.state.round_number
    engine._spend_resource(owner, RESONANCE, 1, HOURGLASS)
    gain_debt(engine, owner, 1, HOURGLASS)
    return True


def _d6(engine: Any, actor: Any, source: str) -> int:
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=1, sides=6, modifier=0), actor_id=actor.entity_id, reason=f"HOURGLASS:{source}")
    engine._record_roll(roll)
    return int(roll.total)


@hook("d20_bonus")
def delayed_strike(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    """Delayed Strike: on an attack roll, subtract 1d6, decided after the d20 is seen."""
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _STRIKE)
    preserve_pending(engine, _DELAYED_ROLL)
    if roll.natural_result is None or not str(roll.reason or "").startswith("ATTACK:"):
        return None
    attacker = engine.state.actors.get(roll.actor_id)
    if attacker is None:
        return None
    free = (engine.__dict__.get(_STRIKE) or {}).pop(attacker.entity_id, None)
    if free is not None:
        engine.__dict__[_DELAYED_ROLL] = roll.roll_id
        return {"source_id": WELL, "bonus": -_d6(engine, attacker, WELL)}  # Hostile Undertow's failed save: no Resonance, no Time Debt
    owner = engine.state.actors.get(_hourglass_owner(attacker) or "")
    if owner is None or not _delay_once(engine, owner) or engine.__dict__.get(_DELAYED_ROLL) == roll.roll_id:
        return None
    from .d20_rewrite import context_of

    rc = context_of(engine, roll)
    target = getattr(rc, "target", None) if rc is not None else None
    ac = getattr(rc, "ac", None) if rc is not None else None
    hits = ac is not None and roll.natural_result != 1 and (roll.natural_result == 20 or int(roll.total) >= int(ac))
    ours = target is not None and target.team_id == owner.team_id
    words = f"{attacker.display_name}'s attack roll is {roll.total}" + (f" against AC {ac}" if ac is not None else "") + "."
    if not _ask_delay(engine, owner, intent, "strike", f"Hourglass Mark: {words}", bool(ours and hits and roll.natural_result != 20 and int(roll.total) - int(ac) < 6), attacker):
        return None
    engine.__dict__[_DELAYED_ROLL] = roll.roll_id
    return {"source_id": HOURGLASS, "bonus": -_d6(engine, owner, HOURGLASS)}


@hook("save")
def delayed_technique(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Delayed Technique: when it forces a save against a technique, one chosen target adds 1d6 to its saving throw."""
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, _TECHNIQUE)
    engine, source = ctx.engine, ctx.actor
    if subject is None or source is None or subject is source:
        return None
    free = engine.__dict__.get(_TECHNIQUE) or {}
    if source.entity_id in free:
        owner = engine.state.actors.get(free[source.entity_id])
        if owner is not None and _ask_free_technique(engine, owner, ctx.intent, subject):
            free.pop(source.entity_id, None)
            return {"bonus": _d6(engine, subject, WELL), "modes": []}
        return None
    owner = engine.state.actors.get(_hourglass_owner(source) or "")
    if owner is None or not _delay_once(engine, owner):
        return None
    if not _ask_delay(engine, owner, ctx.intent, "technique", f"Hourglass Mark: {subject.display_name} saves against {source.display_name}'s technique.",
                      subject.team_id == owner.team_id, subject):
        return None
    return {"bonus": _d6(engine, subject, HOURGLASS), "modes": []}


def _ask_free_technique(engine: Any, owner: Any, intent: Any, subject: Any) -> bool:
    from . import needle

    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "UNDERTOW_TECHNIQUE", subject.entity_id, len(engine.events)), owner,
                        "choice:needle.well.undertow_technique", ["technique"], labels={"technique": f"{subject.display_name} adds 1d6 to its save"},
                        preferred=["technique"] if subject.team_id == owner.team_id else [], allow_decline=True,
                        default="first" if subject.team_id == owner.team_id else "decline", name="Hostile Undertow (Delayed Technique)", feature_id=WELL,
                        target_id=subject.entity_id, prompt=f"Hostile Undertow: choose {subject.display_name} as the target of Delayed Technique?")
    return bool(chosen and chosen[0] == "technique")


@hook("match_start")
def break_the_glass_action(engine: Any) -> None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    engine.action_catalog[BREAK_GLASS] = ActionDefinition(
        source_definition_id=BREAK_GLASS, display_name="Break the Glass", owner_id="*", economy=EconomyKind.ACTION, resolution_kind="TYPED",
        target_kind="SELF", parameters={"typed": {"effects": [{"type": "well_break_glass"}], "numbers": {}, "duration": {"kind": "instant"}, "riders": []},
                                        "expected_damage": 0, "well_break_glass": True,
                                        "description": "Hourglass Mark counterplay: strike, shatter or realign an Hourglass Mark on you or an adjacent creature. "
                                                       "Your best of Arcana, Insight, Sleight of Hand or a Cultivation Check against its maker's DC ends it."})


def _glass_bearers(engine: Any, actor: Any) -> list[Any]:
    return [c for c in engine.state.actors.values() if c.active and _hourglass_owner(c) and (c is actor or engine._distance_actor_to_actor(actor, c) <= 5)]


@hook("additional_actions")
def break_the_glass_offered(engine: Any, actor: Any) -> list[str]:
    return [BREAK_GLASS] if _glass_bearers(engine, actor) else []


@effect("well_break_glass")
def break_the_glass(ctx: Any, row: dict[str, Any]) -> None:
    from ..ability_checks import ability_modifier
    from . import needle
    from .eye_common import numbers_of, skill

    engine, actor = ctx.engine, ctx.actor
    bearers = _glass_bearers(engine, actor)
    bearer = actor if actor in bearers else st.pick_creature(engine, ctx.intent, actor, bearers, checkpoint="BREAK_THE_GLASS", choice_id="choice:needle.well.glass_bearer",
                                                               prompt="Break the Glass: whose Hourglass Mark?", name="Break the Glass", feature_id=HOURGLASS)
    owner = engine.state.actors.get(_hourglass_owner(bearer) or "") if bearer is not None else None
    if owner is None:
        return
    numbers = numbers_of(engine, actor)
    checks = {"arcana": ("Intelligence (Arcana)", skill(engine, actor, "Arcana", ability_modifier(actor, "INT")), "INT", "Arcana"),
              "insight": ("Wisdom (Insight)", skill(engine, actor, "Insight", ability_modifier(actor, "WIS")), "WIS", "Insight"),
              "sleight": ("Dexterity (Sleight of Hand)", skill(engine, actor, "Sleight of Hand", ability_modifier(actor, "DEX")), "DEX", "Sleight of Hand")}
    if numbers.get("cl"):
        checks["cultivation"] = ("Cultivation Check", int(numbers.get("pb") or 2) + int(numbers.get("key_mod") or 0), "", None)
    best = max(checks, key=lambda k: checks[k][1])
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "BREAK_THE_GLASS_CHECK", actor.entity_id), actor, "choice:needle.well.glass_check",
                        list(checks), labels={k: f"{v[0]} ({v[1]:+d})" for k, v in checks.items()}, preferred=[best], name="Break the Glass", feature_id=HOURGLASS,
                        prompt="Break the Glass: which check?")
    pick = chosen[0] if chosen and chosen[0] in checks else best
    dc = int(_numbers(engine, owner).get("save_dc") or 10)
    roll = engine.roll_check(
        modifier=checks[pick][1],
        actor_id=actor.entity_id,
        reason=f'CHECK:{BREAK_GLASS}:{checks[pick][0]}',
        ability=checks[pick][2],
        skill=checks[pick][3],
        against_creature=owner,
    )
    engine._record_roll(roll)
    success = int(roll.total) >= dc
    engine._append_event("CHECK_ROLLED", BREAK_GLASS, actor_id=actor.entity_id, target_ids=(bearer.entity_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success, "skill": checks[pick][0]})
    if success:
        for held in [c for c in bearer.conditions.values() if c.condition_id == _te().mark_condition_id(HOURGLASS_MARK, owner.entity_id)]:
            st.remove(engine, bearer, held, "BROKEN")


# ---------------------------------------------------------------------------------------------------------- Refuse the Moment
def _refusers(engine: Any, subject: Any) -> list[Any]:
    from .. import stealth

    out = []
    for owner in _wells(engine):
        if (st.row(engine, owner, "refuse_the_moment") is None or not st.can_react(owner) or _hour(owner) or int(owner.resources.get(RESONANCE, 0) or 0) < 6):
            continue
        if owner is subject or (engine._distance_actor_to_actor(owner, subject) <= 30 and stealth.sees(engine, owner, subject)):
            out.append(owner)
    return out


def _ask_refuse(engine: Any, owner: Any, subject: Any, what: str, intent: Any, preferred: bool) -> bool:
    from . import needle

    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "REFUSE_THE_MOMENT", subject.entity_id, len(engine.events)), owner,
                        "choice:needle.well.refuse", ["refuse"], labels={"refuse": "Refuse the Moment (6 Resonance, 2 Time Debt)"},
                        preferred=["refuse"] if preferred else [], allow_decline=True, default="first" if preferred else "decline",
                        name="Refuse the Moment", feature_id=REFUSE, target_id=subject.entity_id,
                        prompt=f"{subject.display_name} would {what}. Refuse the Moment (your Reaction): it waits until the end of its next turn.")
    if not chosen or chosen[0] != "refuse":
        return False
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, owner, REFUSE, independent=True):
        engine._spend_resource(owner, RESONANCE, 6, REFUSE)
        owner.reaction_available = False
        engine._append_event("REACTION_RESOLVED", REFUSE, actor_id=owner.entity_id, target_ids=(subject.entity_id,),
                             payload={"checkpoint": "REFUSE_THE_MOMENT", "reaction_name": "Refuse the Moment"})
        gain_debt(engine, owner, 2, REFUSE)
        from ..paid_relocation import capture, retain
        retain(engine, ("well_refuse", owner.entity_id, subject.entity_id), capture(engine))
        return True


def _defer(engine: Any, owner: Any, subject: Any, data: dict[str, Any]) -> Any:
    """Well of Hours holds only one Deferred Consequence; creating another releases the first at once."""
    for creature in list(engine.state.actors.values()):
        for held in list(_held(creature, DEFERRED, owner.entity_id)):
            _arrive(engine, creature, held)
    before = set(subject.conditions)
    engine._apply_condition(subject, DEFERRED, REFUSE, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={**data, "turn": int(subject.turns_started), "label": f"Refuse the Moment: {data.get('what')} waits until the end of its next turn"})
    return next((subject.conditions[i] for i in subject.conditions if i not in before), None)


@hook("incoming_damage")
def refuse_damage(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str, source_actor_id: str | None) -> int | None:
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _PACKET)
    if amount <= 0 or engine.__dict__.get(_ARRIVING) == target.entity_id or engine.__dict__.get(_BACKLASH) == target.entity_id:
        return None
    intent = engine._active_intent
    key = (target.entity_id, str(source_definition_id), str(source_actor_id), getattr(intent, "intent_id", None))
    packet = engine.__dict__.get(_PACKET)
    if packet and packet[0] == key:
        holder_cond = next((c for c in _held(target, DEFERRED) if c is packet[1]), None)
        if holder_cond is not None:  # "all damage from one attack, technique packet"
            data = st.data_of(target, holder_cond)
            st.set_data(target, holder_cond, packets=[*(data.get("packets") or []), [int(amount), str(damage_type)]])
            return amount
    source = engine.state.actors.get(source_actor_id or "")
    hostile = source is None or source.team_id != target.team_id
    for owner in _refusers(engine, target):
        ours = owner.team_id == target.team_id and hostile
        if not _ask_refuse(engine, owner, target, f"take {amount} {str(damage_type).lower()} damage", intent, ours and (amount >= target.current_hp or amount >= 15)):
            continue
        from ..paid_relocation import causal_scope, take
        with causal_scope(engine, take(engine, ("well_refuse", owner.entity_id, target.entity_id))):
            held = _defer(engine, owner, target, {"kind": "damage", "what": f"{amount} {str(damage_type).lower()} damage", "packets": [[int(amount), str(damage_type)]],
                                                  "source": str(source_definition_id), "source_actor": source_actor_id})
            engine.__dict__[_PACKET] = (key, held)
            return amount
    return None


@hook("after_save_resolved")
def note_failed_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, _FAILED)
    ctx.engine.__dict__[_FAILED] = (subject.entity_id, ctx.source, ctx.actor.entity_id) if failed and subject is not None else None


@hook("condition_attempt")
def refuse_condition(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> bool | None:
    engine = ctx.engine
    name = str(effect_row.get("condition") or "").lower()
    if not name or subject is None or ctx.actor.team_id == subject.team_id or st.landing(engine, subject) or engine.__dict__.get(_ARRIVING) == subject.entity_id:
        return None
    failed = engine.__dict__.get(_FAILED) == (subject.entity_id, ctx.source, ctx.actor.entity_id)
    if not failed and name not in ("grappled", "restrained", "unconscious"):
        return None
    for owner in _refusers(engine, subject):
        if not _ask_refuse(engine, owner, subject, f"become {name.title()}", ctx.intent, owner.team_id == subject.team_id and name != "prone"):
            continue
        from ..paid_relocation import causal_scope, take
        with causal_scope(engine, take(engine, ("well_refuse", owner.entity_id, subject.entity_id))):
            _defer(engine, owner, subject, {"kind": "condition", "what": f"becoming {name.title()}", **st.delay_condition(ctx, effect_row, name)})
            return False
    return None


@hook("healing_assigned")
def healing_pays_the_wait(engine: Any, subject: Any, amount: int) -> int | None:
    """"Healing received by the subject can be assigned first to deferred damage, even when the subject is at its Hit Point maximum"."""
    from . import needle

    for held in _held(subject, DEFERRED):
        data = st.data_of(subject, held)
        waiting = sum(int(p[0]) for p in data.get("packets") or []) - int(data.get("paid") or 0)
        if data.get("kind") != "damage" or waiting <= 0:
            continue
        chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "DEFERRED_HEALING", subject.entity_id, len(engine.events)), subject,
                            "choice:needle.well.deferred_healing", ["assign"], labels={"assign": f"Pay off the waiting damage ({waiting}) first"},
                            preferred=["assign"], allow_decline=True, name="Refuse the Moment (deferred damage)", feature_id=REFUSE,
                            prompt=f"{subject.display_name} regains {amount} Hit Points. Assign them to the {waiting} damage waiting from Refuse the Moment first?")
        if not chosen or chosen[0] != "assign":
            return None
        paid = min(amount, waiting)
        st.set_data(subject, held, paid=int(data.get("paid") or 0) + paid)
        note(engine, REFUSE, subject, f"{paid} healing pays off {subject.display_name}'s waiting damage ({waiting - paid} left).")
        return amount - paid
    return None


def _arrive(engine: Any, holder: Any, held: Any) -> None:
    """The deferred consequence lands when the protected creature's next turn ends, unless it is answered before then."""
    data = st.data_of(holder, held)
    st.remove(engine, holder, held, "ARRIVED")
    if not holder.active:
        return
    if data.get("kind") == "condition":
        engine.__dict__[_ARRIVING] = holder.entity_id
        try:
            landed = st.land_delayed_condition(engine, holder, data)
        finally:
            engine.__dict__.pop(_ARRIVING, None)
        note(engine, REFUSE, holder, f"The refused moment arrives: {holder.display_name} {'becomes ' + str(data.get('condition')).title() if landed else 'is spared (its source is gone)'}.")
        return
    paid = int(data.get("paid") or 0)
    engine.__dict__[_ARRIVING] = holder.entity_id
    try:
        for amount, kind in data.get("packets") or []:
            left = max(0, int(amount) - paid)
            paid = max(0, paid - int(amount))
            if left and holder.active:
                engine._commit_damage(holder, left, str(kind), str(data.get("source") or REFUSE), data.get("source_actor"), engine._active_intent, reaction_depth=1)
    finally:
        engine.__dict__.pop(_ARRIVING, None)
    note(engine, REFUSE, holder, f"The refused moment arrives: {holder.display_name} takes the waiting damage.")


# ---------------------------------------------------------------------------------------------------------- The Well Has No Bottom
def field_of(owner: Any) -> Any:
    return next(iter(_held(owner, FIELD, owner.entity_id)), None)


def _zone(engine: Any, owner: Any) -> Any:
    field = field_of(owner)
    zone = engine.state.zones.get(str((field.data or {}).get("zone_id") or "")) if field is not None else None
    return zone if zone is not None and zone.active else None


def _inside(engine: Any, owner: Any, creature: Any) -> bool:
    zone = _zone(engine, owner)
    return zone is not None and creature.active and engine._footprint_intersects(creature, zone.affected_cells)


def _image(engine: Any, creature: Any) -> dict[str, Any]:
    return {"x": creature.position.x, "y": creature.position.y, "hp": int(creature.current_hp), "conditions": sorted(creature.conditions)}


def _choose(engine: Any, owner: Any, creatures: list[Any], intent: Any, checkpoint: str, prompt: str) -> list[Any]:
    from . import needle

    if not creatures:
        return []
    ids = [c.entity_id for c in creatures]
    ours = [c.entity_id for c in creatures if c.team_id == owner.team_id]
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, checkpoint, owner.entity_id), owner, "choice:needle.well.chosen", ids,
                        labels={c.entity_id: c.display_name for c in creatures}, preferred=ours or ids[:1], minimum=1, maximum=len(ids), allow_decline=True,
                        name="The Well Has No Bottom", feature_id=WELL, prompt=prompt)
    return [c for c in creatures if c.entity_id in (chosen or [])]


@effect("well_field")
def the_well(ctx: Any, row: dict[str, Any]) -> None:
    """When the field appears, record for every chosen creature in the area its space, current Hit Points and ordinary conditions;
    that record is its Round Image."""
    engine, owner = ctx.engine, ctx.actor
    zone = next((z for z in reversed(list(engine.state.zones.values())) if z.active and z.owner_id == owner.entity_id and str(z.source_definition_id) == ctx.source), None)
    if zone is None:
        return
    _busy(owner)
    for old in list(_held(owner, FIELD)):
        st.remove(engine, owner, old, "REPLACED")
    inside = [c for c in engine.state.actors.values() if c.active and engine._footprint_intersects(c, zone.affected_cells)]
    chosen = _choose(engine, owner, inside, ctx.intent, "WELL_CHOSEN", "The Well Has No Bottom: which creatures in the field get a Round Image?")
    engine._apply_condition(owner, FIELD, WELL, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"zone_id": zone.zone_id, "label": "The Well Has No Bottom: your field of Round Images"})
    field = field_of(owner)
    if field is not None:
        st.set_data(owner, field, chosen=[c.entity_id for c in chosen], images={c.entity_id: _image(engine, c) for c in chosen}, successes={})


def _renew_images(engine: Any, owner: Any, field: Any) -> None:
    """At the start of each of the owner's turns every chosen creature still in the field has its Round Image replaced with its
    current state; a creature that entered may be chosen then."""
    if _zone(engine, owner) is None:
        _collapse(engine, owner, field)
        return
    data = st.data_of(owner, field)
    chosen = list(data.get("chosen") or [])
    new = [c for c in engine.state.actors.values() if c.entity_id not in chosen and _inside(engine, owner, c)]
    chosen += [c.entity_id for c in _choose(engine, owner, new, engine._active_intent, "WELL_NEWCOMERS", "The Well Has No Bottom: choose creatures that entered the field?")]
    images = dict(data.get("images") or {})
    for creature_id in chosen:
        creature = engine.state.actors.get(creature_id)
        if creature is not None and _inside(engine, owner, creature):
            images[creature_id] = _image(engine, creature)
    st.set_data(owner, field, chosen=chosen, images=images)


def _collapse(engine: Any, owner: Any, field: Any) -> None:
    """Collapse of the Well: deferred consequences inside it arrive; Time Debt becomes Temporal Arrears; no second field this fight."""
    zone = engine.state.zones.get(str((field.data or {}).get("zone_id") or ""))
    cells = set(getattr(zone, "affected_cells", ()) or ())
    st.remove(engine, owner, field, "COLLAPSED")
    owner.turn_flags["_round_c8_well_spent"] = True
    for creature in list(engine.state.actors.values()):
        if creature.active and cells and engine._footprint_intersects(creature, tuple(cells)):
            for held in list(_held(creature, DEFERRED)):
                _arrive(engine, creature, held)
    debt = int(owner.resources.get(DEBT, 0) or 0)
    if debt:
        engine._spend_resource(owner, DEBT, debt, WELL)
        room = int(owner.resource_maximums.get(ARREARS, 0) or 0) - int(owner.resources.get(ARREARS, 0) or 0)
        if room > 0:
            engine._gain_resource(owner, ARREARS, min(room, debt), WELL)
        _trim_resonance(engine, owner)
    note(engine, WELL, owner, f"The Well collapses: {owner.display_name}'s Time Debt becomes Temporal Arrears.")


def _friendly_current(engine: Any, actor: Any) -> None:
    """Friendly Current: each chosen willing creature that starts its turn in the field picks one benefit."""
    from . import needle

    for owner in _wells(engine):
        field = field_of(owner)
        if field is None or owner.team_id != actor.team_id or actor.entity_id not in (st.data_of(owner, field).get("chosen") or []) \
                or not _inside(engine, owner, actor):
            continue
        pb = int(_numbers(engine, owner).get("pb") or 2)
        stood = _stood_this_turn(engine, actor)
        pressures = [c for c in actor.conditions.values() if str(c.condition_id).startswith("condition:typed.spirit_awakening_pressure")
                     and c.condition_id != "condition:typed.spirit_awakening_pressure_choice"]
        spots = {c: v for c, v in st.routes(engine, actor, 10).items() if c != actor.position}
        options = {**({"step": "Move up to 10 feet without provoking Opportunity Attacks"} if spots else {}),
                   **({"stand": "Stand up from Prone without spending movement"} if stood is not None or any(str(c.condition_id).endswith(".prone") for c in actor.conditions.values()) else {}),
                   "shield": f"Gain {2 * pb} Temporary Hit Points",
                   **({"calm": "Suppress one Spiritual Pressure effect on you until the end of this turn"} if pressures else {})}
        preferred = "calm" if pressures else "stand" if "stand" in options else "shield"
        chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "FRIENDLY_CURRENT", actor.entity_id), actor, "choice:needle.well.friendly_current",
                            list(options), labels=options, preferred=[preferred], allow_decline=True, name="The Well Has No Bottom (Friendly Current)", feature_id=WELL,
                            prompt="Friendly Current: choose one benefit.")
        pick = chosen[0] if chosen and chosen[0] in options else None
        if pick == "step":
            path = st.choose_route(engine, actor, spots, engine._active_intent, checkpoint="FRIENDLY_STEP", prompt="Friendly Current: move where?",
                                   name="Friendly Current", feature=WELL, stay=False)
            if path is not None:
                from .rider_movement import step

                step(engine, actor, list(path), WELL)
        elif pick == "stand":
            for held in [c for c in actor.conditions.values() if str(c.condition_id).endswith(".prone")]:
                st.remove(engine, actor, held, "STOOD_UP")
            if stood:
                actor.movement_remaining_ft += stood
                engine._append_event("MOVEMENT_GRANTED", WELL, actor_id=actor.entity_id, payload={"distance_ft": stood})
        elif pick == "shield":
            engine._grant_temp_hp(actor, 2 * pb, WELL, owner.entity_id)
        elif pick == "calm" and pressures:
            st.suppress(engine, actor, pressures[0], WELL, owner.entity_id, "Friendly Current", this_turn=True)
        return


def _stood_this_turn(engine: Any, actor: Any) -> int | None:
    """The movement the table took for standing up from Prone as this turn began (half its Speed), or None."""
    for event in reversed(engine.events):
        if event.event_type == "TURN_ENDED":
            return None
        payload = event.payload or {}
        if (event.event_type == "CONDITION_REMOVED" and event.actor_id == actor.entity_id and str(payload.get("condition_id") or "").endswith(".prone")
                and payload.get("checkpoint") == "START_OF_TURN"):
            return engine._effective_speed(actor) // 2
    return None


def _undertow_activity(engine: Any, actor: Any, activity: str, action: Any, *, path: list[dict[str, Any]] | None = None) -> None:
    """Hostile Undertow: the first time each round a hostile creature in the field moves voluntarily, attacks, activates a technique
    or takes a Reaction, it makes a Wisdom save."""
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _STRIKE)
    preserve_pending(engine, _TECHNIQUE)
    for owner in _wells(engine):
        field = field_of(owner)
        if field is None or owner.team_id == actor.team_id or not actor.active:
            continue
        zone = _zone(engine, owner)
        if zone is None:
            continue
        if activity == "move":
            if engine.state.current_actor_id != actor.entity_id or not path:
                continue
            from ..gate2_runtime_models import Position

            start = Position(x=int(path[0]["x"]), y=int(path[0]["y"]))
            if tuple((start.x, start.y)) not in {(c.x, c.y) if hasattr(c, "x") else tuple(c) for c in zone.affected_cells} and not _inside(engine, owner, actor):
                continue
        elif not _inside(engine, owner, actor):
            continue
        key = f"_round_c8_undertow:{owner.entity_id}"
        if int(actor.turn_flags.get(key) or 0) == engine.state.round_number:
            continue
        data = st.data_of(owner, field)
        successes = dict(data.get("successes") or {})
        if int(successes.get(actor.entity_id) or 0) >= 2:
            continue  # "immune to it for the remainder of that activation"
        actor.turn_flags[key] = engine.state.round_number
        ctx = _ctx(engine, owner, WELL, [actor])
        if st.save(ctx, actor, "wis"):
            if activity == "attack":
                engine.__dict__.setdefault(_STRIKE, {})[actor.entity_id] = WELL
            elif activity == "technique" and action is not None:
                rows = list(_rows(((action.parameters or {}).get("typed") or {}).get("effects")))
                if any(r.get("type") == "attack" for r in rows):
                    engine.__dict__.setdefault(_STRIKE, {})[actor.entity_id] = WELL
                elif any(r.get("type") == "save" for r in rows):
                    engine.__dict__.setdefault(_TECHNIQUE, {})[actor.entity_id] = owner.entity_id
            _te().run_effects(ctx, [{"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "target_next_turn"},
                                     "evidence": "The creature also becomes Resonance Marked until the end of its next turn."}])
            continue
        successes[actor.entity_id] = int(successes.get(actor.entity_id) or 0) + 1
        st.set_data(owner, field, successes=successes)
        _undertow_success(engine, owner, actor, ctx)


def _undertow_success(engine: Any, owner: Any, actor: Any, ctx: Any) -> None:
    from . import needle

    options = {"slow": "Its Speed is reduced by 10 feet until the start of its next turn", "still": "It cannot take Reactions until the start of its next turn"}
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "HOSTILE_UNDERTOW", actor.entity_id, len(engine.events)), owner, "choice:needle.well.undertow",
                        list(options), labels=options, preferred=["still"], name="The Well Has No Bottom (Hostile Undertow)", feature_id=WELL, target_id=actor.entity_id,
                        prompt=f"Hostile Undertow: {actor.display_name} succeeded on its save. Choose one.")
    pick = chosen[0] if chosen and chosen[0] in options else "still"
    until = "START_OF_TARGET_NEXT_TURN"
    if pick == "slow":
        _te().run_effects(ctx, [{"type": "speed", "applies_to": "target", "flat": -10, "expires_on": until, "evidence": "reduce its Speed by 10 feet until the start of its next turn"}])
        _cut_movement(engine, actor, 10, WELL)
    else:
        _te().run_effects(ctx, [{"type": "reaction_denied", "applies_to": "target", "expires_on": until, "evidence": "it cannot take Reactions until the start of its next turn"}])


@hook("before_attack")
def undertow_attack(engine: Any, attacker: Any, defender: Any, intent: Any, context: Any) -> dict[str, Any] | None:
    if attacker is not None:
        _undertow_activity(engine, attacker, "attack", None)
    return None


def _bell_trigger(engine: Any, creature: Any, what: str) -> None:
    """Return to the Bell: once in the activation, when a chosen creature in the field takes damage, fails a save, is moved, gains a
    condition or drops to 0 Hit Points, the owner may spend its Reaction to return it to its Round Image."""
    from . import needle

    for owner in _wells(engine):
        field = field_of(owner)
        if field is None or not st.can_react(owner) or _hour(owner):
            continue
        data = st.data_of(owner, field)
        image = (data.get("images") or {}).get(creature.entity_id)
        if data.get("returned") or image is None or not _inside_or_down(engine, owner, creature):
            continue
        ours = creature.team_id == owner.team_id
        lost = int(image.get("hp") or 0) - int(creature.current_hp)
        preferred = ours and (creature.current_hp <= 0 or lost >= max(15, creature.maximum_hp // 3))
        chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "RETURN_TO_THE_BELL", creature.entity_id, len(engine.events)), owner,
                            "choice:needle.well.return_to_the_bell", ["return"], labels={"return": f"Return {creature.display_name} to its Round Image"},
                            preferred=["return"] if preferred else [], allow_decline=True, default="first" if preferred else "decline",
                            name="The Well Has No Bottom (Return to the Bell)", feature_id=WELL, target_id=creature.entity_id,
                            prompt=f"{creature.display_name} {what}. Return to the Bell (your Reaction, once): back to its Round Image "
                                   f"({image.get('x')},{image.get('y')}, {image.get('hp')} Hit Points); your Time Debt becomes its maximum and you take 3d10 Psychic damage.")
        if not chosen or chosen[0] != "return":
            continue
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, owner, WELL, independent=True):
            st.set_data(owner, field, returned=True)
            owner.reaction_available = False
            engine._append_event("REACTION_RESOLVED", WELL, actor_id=owner.entity_id, target_ids=(creature.entity_id,),
                                 payload={"checkpoint": "RETURN_TO_THE_BELL", "reaction_name": "Return to the Bell"})
            _return(engine, owner, creature, image)
            return


def _inside_or_down(engine: Any, owner: Any, creature: Any) -> bool:
    zone = _zone(engine, owner)
    return zone is not None and engine._footprint_intersects(creature, zone.affected_cells)


def _return(engine: Any, owner: Any, creature: Any, image: dict[str, Any]) -> None:
    from ..gate2_runtime_models import DiceSpec, Position
    from . import life_state
    from .needle import step_to

    if life_state.is_dead(creature):
        return  # "Do not restore ... completed death"
    spot = Position(x=int(image["x"]), y=int(image["y"]))
    occupied = engine._occupied_cells_except(creature.entity_id)
    cells = sorted((c for c in engine.grid.cells_in_radius(spot, 3) if engine.grid.distance_ft(spot, c) <= 15
                    and engine.grid.placement_legal(c, footprint=engine._footprint(creature), occupied_cells=occupied)),
                   key=lambda c: (engine.grid.distance_ft(spot, c), c.y, c.x))
    if cells and cells[0] != creature.position:
        step_to(engine, creature, cells[0], WELL)
    kept = set(image.get("conditions") or [])
    for iid, held in list(creature.conditions.items()):
        name = str(held.condition_id).removeprefix("condition:typed.")
        if iid not in kept and any(name == o or name.startswith(o + ".") for o in ORDINARY):
            st.remove(engine, creature, held, "RETURNED")
    if int(image.get("hp") or 0) > creature.current_hp:
        life_state.restore_hp(engine, creature, int(image["hp"]) - creature.current_hp, WELL, owner.entity_id)
    top = int(owner.resource_maximums.get(DEBT, 0) or 0)
    if int(owner.resources.get(DEBT, 0) or 0) < top:
        engine._gain_resource(owner, DEBT, top - int(owner.resources.get(DEBT, 0) or 0), WELL)  # "set your Time Debt to its maximum"
    _busy(owner)
    roll = engine.roller.roll(DiceSpec(count=3, sides=10, modifier=0), actor_id=owner.entity_id, reason=f"DAMAGE:{WELL}")
    engine._record_roll(roll)
    engine.__dict__[_BACKLASH] = owner.entity_id
    engine.__dict__["_damage_unreduced"] = owner.entity_id  # "ignores Resistance and Immunity"
    try:
        engine._commit_damage(owner, int(roll.total), "PSYCHIC", WELL, owner.entity_id, engine._active_intent, reaction_depth=1)
    finally:
        engine.__dict__.pop(_BACKLASH, None)
        if engine.__dict__.get("_damage_unreduced") == owner.entity_id:
            engine.__dict__.pop("_damage_unreduced", None)
    note(engine, WELL, owner, f"Return to the Bell: {creature.display_name} returns to its Round Image.")


# ---------------------------------------------------------------------------------------------------------- buttons and gates
@hook("compile_actions")
def well_buttons(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned, out = info["owned_ids"], []

    def button(key: str, name: str, target: str, range_ft: int | None, rows: list[dict[str, Any]], text: str, source: str) -> Any:
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.well.{key}", display_name=name, owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION,
                                resolution_kind="TYPED", target_kind=target, range_ft=range_ft,
                                parameters={"typed": {"numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": source, "effects": rows},
                                            "expected_damage": 0, "well": key, "description": text})

    if RIPPLE in owned:
        out.append(button("echo", "Echo of the Chosen Step", "SELF", None, [{"type": "well_echo", "applies_to": "self"}],
                          "Ripple of Before (Bonus Action, 1 Resonance, 1 Time Debt): return to your Before-Space -- where a move of 10 feet or more began "
                          "this turn -- if it is a free space within 30 feet, without provoking Opportunity Attacks.", RIPPLE))
    if BORROWED in owned:
        for key, (label, text, debt) in OPTIONS.items():
            if key == "spike" and MIND_SPIKE not in owned:
                continue
            if key == "gaze" and SOUL_GAZE not in owned:
                continue
            target = "HOSTILE_ENTITY" if key in ("strike", "spike", "gaze") else "SELF"
            reach = 60 if key in ("spike", "gaze") else 120 if key == "strike" else None
            out.append(button(f"borrowed_{key}", f"Borrowed Second: {label}", target, reach, [{"type": "well_borrowed", "mode": key, "applies_to": "target" if target != "SELF" else "self",
                                                                                               **({"harmful": True} if key in ("strike", "spike") else {})}],
                              f"Borrowed Second (Bonus Action, 3 Resonance, once a turn): {text}. {debt} Time Debt.", BORROWED + ":" + key))
    return out or None


MIND_SPIKE = "tianxia.path.spirit_awakening.feature.mind_spike"
SOUL_GAZE = "tianxia.path.spirit_awakening.feature.soul_gaze"


@hook("candidate_allowed")
def well_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    key = str((action.parameters or {}).get("well") or "")
    feature = str(st.feature_of(action) or "")
    if (key or feature.startswith(TRADITION)) and _hour(actor):
        return False  # the Hour Comes Due: "you cannot activate a Well of Hours feature"
    # Both historical and current repayment conditions use borrowed_second's
    # shared movement gates, including nested effects and custom travel actions.
    if feature == WELL and actor.turn_flags.get("_round_c8_well_spent"):
        return False  # "You cannot activate The Well Has No Bottom again until ... you complete the Temporal Arrears clearing procedure"
    if key == "echo":
        return None if _before_cell(engine, actor) is not None and int(actor.resources.get(RESONANCE, 0) or 0) >= 1 else False
    if key.startswith("borrowed_"):
        mode = key.removeprefix("borrowed_")
        if actor.turn_flags.get("c8_borrowed_used") or not (int(actor.resources.get(RESONANCE, 0) or 0) >= 3 or _can_drink(engine, actor)):
            return False
        field = field_of(actor)
        if mode in ("strike", "spike") and field is not None and st.data_of(actor, field).get("struck"):
            return False
        target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
        if mode == "rise":
            return None if any(str(c.condition_id).endswith(".prone") for c in actor.conditions.values()) else False
        if mode in ("strike", "spike"):
            if target is None or not _te().bears_mark(target, actor.entity_id, "Resonance"):
                return False
            return None if mode == "spike" or _weapons(engine, actor, target) else False
        if mode == "search":
            return None if st.action_named(engine, actor, "Search") is not None else False
        if mode == "gaze":
            need = 1 if _can_drink(engine, actor) else 4  # Soul Gaze's own 1 Resonance, and Borrowed Second's 3 unless you drink
            return None if st.action_named(engine, actor, "Soul Gaze") is not None and int(actor.resources.get(RESONANCE, 0) or 0) >= need else False
    return None

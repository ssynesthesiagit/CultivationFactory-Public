"""One Barrage's primary and Bonus Action attacks share a hit counter.

Rules source: owner's TAL_BARRAGE_BLITZ_FOCUS, TAL_BARRAGE_BLOWBACK_BARRAGE,
TAL_BARRAGE_PINNING_VOLLEY, TAL_BARRAGE_CASCADING_BARRAGE,
TAL_BARRAGE_HAMMERING_SHOTS, TAL_BARRAGE_DISTRACTING_SHOT, and
TAL_BARRAGE_COURT_OF_FALLING_STARS text in
authority/typed_mechanics/rules_text.json. The same owner's
FIRE_TAL_SCORCHING_RAY_ART text gives the two-rays Burning threshold.
The primary action opens the follow-up (docket_maneuvers.py); the next primary use
starts a new sequence even if it uses the same weapon on the same turn.
Nested primary attacks may set typed['barrage_sequence_continuation'] = True
on their transient context to retain that weapon's existing sequence. This does
not change primary damage/modifiers or persist a new action-catalog field.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

FOCUS = "resource:core.martial_focus"
BLITZ = "TAL_BARRAGE_BLITZ_FOCUS"
BLOWBACK = "TAL_BARRAGE_BLOWBACK_BARRAGE"
PINNING = "TAL_BARRAGE_PINNING_VOLLEY"
HAMMERING = "TAL_BARRAGE_HAMMERING_SHOTS"
DISTRACTING = "TAL_BARRAGE_DISTRACTING_SHOT"
COURT = "TAL_BARRAGE_COURT_OF_FALLING_STARS"
CASCADING = "TAL_BARRAGE_CASCADING_BARRAGE"
COURT_CONDITION = "condition:typed.court_of_falling_stars"
COURT_ALLY = "condition:typed.court_falling_stars_ally"
COURT_TARGET = "condition:typed.court_falling_stars_target"
COURT_SELECT = "court_select_ally"
COURT_REMAINING = "court_allies_remaining"
PIN_CONDITION = "condition:typed.pinning_volley"
STATE = "barrage_sequences"
SCORCHING_RAYS = "FIRE_TAL_SCORCHING_RAY_ART"
RAYS_STATE = "scorching_ray_hits"


def _rays_rule(ctx: Any) -> bool:
    """Only when the typing asks for this rule: a typing whose attack carries after_hits (the Fire review's) already
    applies Burning on the second ray itself."""
    return any(isinstance(row, dict) and row.get("type") == "barrage_hit_rule" and row.get("rule") == "scorching_rays"
               for row in ctx.typed.get("effects") or [])


@hook("attack_modifier_capture_allowed")
def _sequence_modifier_capture(row: dict[str, Any]) -> bool | None:
    """Sequence declarations cannot activate independently after a single hit."""
    if row.get("type") == "barrage_hit_rule":
        return False
    return None


@effect("barrage_hit_rule")
def _declared_rule(ctx: Any, rule: dict[str, Any]) -> None:
    # The reviewed typing declares a sequence rider. A single action's effect
    # cannot observe the later Bonus Action hit; after_hit below resolves it.
    return None


@effect("barrage_court")
def _court(ctx: Any, rule: dict[str, Any]) -> None:
    from ..typed_executor import effect_expiry

    ctx.engine._apply_condition(ctx.actor, COURT_CONDITION, COURT, ctx.actor.entity_id,
                                expires_on=effect_expiry(ctx, rule, ctx.actor, condition=True),
                                data={"label": "Court of Falling Stars"})
    ctx.actor.turn_flags[COURT_REMAINING] = int(ctx.numbers.get("pb") or ctx.actor.proficiency_bonus)
    ctx.rider("Court of Falling Stars lasts 1 minute. Choose up to your Proficiency Bonus allies now; two Barrage hits can restore Martial Focus once per turn.")


@hook("compile_actions")
def _court_selection_action(info: dict[str, Any]) -> list[Any] | None:
    if COURT not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.{COURT_SELECT}",
                             display_name="Court of Falling Stars: choose ally", owner_id=info["actor_id"],
                             economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="ALLY_OR_SELF",
                             parameters={"typed": {"effects": [{"type": "barrage_court_choose_ally"}],
                                                   "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []},
                                         "expected_damage": 0})]


@effect("barrage_court_choose_ally")
def _choose_court_ally(ctx: Any, rule: dict[str, Any]) -> None:
    ally = (ctx.targets or [None])[0]
    if ally is None or ally.entity_id == ctx.actor.entity_id:
        return
    court = next((c for c in ctx.actor.conditions.values() if c.condition_id == COURT_CONDITION), None)
    if court is None or int(ctx.actor.turn_flags.get(COURT_REMAINING) or 0) <= 0:
        return
    ctx.engine._apply_condition(ally, COURT_ALLY, COURT, ctx.actor.entity_id,
                                expires_on=court.expires_on, data={"label": "Court of Falling Stars ally"})
    ctx.actor.turn_flags[COURT_REMAINING] -= 1
    ctx.rider(f"Court of Falling Stars: {ally.display_name} was chosen. Its first eligible attack against a creature hit twice by your Barrage has Advantage.")


@hook("event")
def _court_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == "INTENT_ACCEPTED":
        actor = engine.state.actors.get(kwargs.get("actor_id") or "")
        source = engine.events[-1].source_definition_id if engine.events else ""
        if actor is not None and not source.endswith(f".{COURT_SELECT}"):
            actor.turn_flags.pop(COURT_REMAINING, None)
        return
    if event_type == "CONDITION_REMOVED" and (kwargs.get("payload") or {}).get("condition_id") == COURT_CONDITION:
        for owner_id in kwargs.get("target_ids") or ():
            _clear_court(engine, owner_id)
        return
    if event_type not in {"CONDITION_APPLIED", "ENTITY_DEFEATED"}:
        return
    if event_type == "CONDITION_APPLIED":
        from ..typed_executor import rules

        condition_id = str((kwargs.get("payload") or {}).get("condition_id") or "")
        if condition_id != "condition:core.incapacitated" and (not condition_id.startswith("condition:typed.") or not (
                rules()["conditions"].get(condition_id.removeprefix("condition:typed.")) or {}).get("no_actions")):
            return
    for target_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(target_id)
        if actor is not None and any(row.condition_id == COURT_CONDITION for row in actor.conditions.values()):
            engine._remove_condition(actor, COURT_CONDITION, COURT)
            _clear_court(engine, actor.entity_id)


def _clear_court(engine: Any, owner_id: str) -> None:
    owner = engine.state.actors.get(owner_id)
    if owner is not None:
        owner.turn_flags.pop(COURT_REMAINING, None)
    for actor in engine.state.actors.values():
        for iid, row in list(actor.conditions.items()):
            if row.condition_id in {COURT_ALLY, COURT_TARGET} and row.source_actor_id == owner_id:
                actor.conditions.pop(iid)
                engine._append_event("CONDITION_REMOVED", COURT, actor_id=owner_id,
                                     target_ids=(actor.entity_id,), payload={"condition_id": row.condition_id,
                                                                            "instance_id": iid})


@hook("attack_sequence_start")
def _sequence_start(ctx: Any) -> None:
    kind = ctx.typed.get("maneuver")
    if ctx.typed.get("source") == SCORCHING_RAYS and _rays_rule(ctx):
        ctx.actor.turn_flags[RAYS_STATE] = {}
    if kind == "barrage" and not ctx.typed.get("barrage_sequence_continuation"):
        _put(ctx.actor, ctx.typed.get("maneuver_of"), {
            "base": ctx.typed.get("maneuver_of"), "id": ctx.engine.state.event_sequence + 1,
            "hits": {}, "total": 0, "modifier": (ctx.typed.get("modifier") or {}).get("id"),
            "owned": list(ctx.typed.get("barrage_owned") or []),
        })
    elif kind == "barrage_cascade":
        state = _state(ctx) or {}
        pending = list(state.get("cascade_pending") or [])
        if pending:
            state["cascade_pending"] = pending[1:]
            _put(ctx.actor, ctx.typed.get("maneuver_of"), state)


def _put(actor: Any, base: str, state: dict[str, Any]) -> None:
    sequences = dict(actor.turn_flags.get(STATE) or {})
    sequences[base] = state
    actor.turn_flags[STATE] = sequences


def _state(ctx: Any) -> dict[str, Any] | None:
    if ctx.typed.get("maneuver") not in {"barrage", "barrage_follow_up", "barrage_cascade"}:
        return None
    state = (ctx.actor.turn_flags.get(STATE) or {}).get(ctx.typed.get("maneuver_of"))
    if not isinstance(state, dict):
        return None
    return state


@hook("attack_mode")
def _distracting_mode(ctx: Any, target: Any) -> str | None:
    state = _state(ctx)
    if state and ctx.typed.get("maneuver") == "barrage" and state.get("modifier") == DISTRACTING:
        return "ADVANTAGE"
    if target is not None:
        for ally_marker in ctx.actor.conditions.values():
            if ally_marker.condition_id != COURT_ALLY:
                continue
            if any(row.condition_id == COURT_TARGET and row.source_actor_id == ally_marker.source_actor_id
                   for row in target.conditions.values()):
                ctx.damage_cache["court_advantage"] = (target.entity_id, ally_marker.source_actor_id)
                return "ADVANTAGE"
    return None


@hook("attack_resolved")
def _consume_court_advantage(ctx: Any, target: Any, hit: bool, attack: dict[str, Any]) -> None:
    if ctx.damage_cache.get("court_advantage") is None or target is None:
        return
    target_id, owner_id = ctx.damage_cache.pop("court_advantage")
    if target_id != target.entity_id:
        return
    for iid, row in list(ctx.actor.conditions.items()):
        if row.condition_id == COURT_ALLY and row.source_actor_id == owner_id:
            ctx.actor.conditions.pop(iid)
            ctx.engine._append_event("CONDITION_REMOVED", COURT, actor_id=owner_id,
                                     target_ids=(ctx.actor.entity_id,), payload={"condition_id": COURT_ALLY,
                                                                               "instance_id": iid})
            ctx.rider("Court of Falling Stars: the chosen ally used its one attack with Advantage.")
            break


@hook("attack_damage")
def _hammering_damage(ctx: Any, dice: Any) -> Any:
    state = _state(ctx)
    if not state or ctx.typed.get("maneuver") not in {"barrage_follow_up", "barrage_cascade"} or state.get("modifier") != HAMMERING:
        return None
    from ..gate2_runtime_models import DiceSpec

    if not isinstance(dice, DiceSpec):
        return None
    # Owner text: only the Bonus Action attack regains the positive ability modifier.
    return dice.model_copy(update={"modifier": dice.modifier + max(0, int(ctx.numbers.get("key_mod") or 0))})


@hook("technique_used")
def _finish_primary(ctx: Any) -> None:
    state = _state(ctx)
    if not state or ctx.typed.get("maneuver") != "barrage" or state.get("modifier") != DISTRACTING:
        return
    for flag in ctx.typed.get("opens") or []:
        ctx.actor.turn_flags[flag] = False
    ctx.rider("Distracting Shot: the primary attack had Advantage; the Barrage follow-up was forgone.")


@hook("after_hit")
def _count_hit(ctx: Any, target: Any, kind: str) -> None:
    if ctx.typed.get("source") == SCORCHING_RAYS and _rays_rule(ctx):
        hits = dict(ctx.actor.turn_flags.get(RAYS_STATE) or {})
        hits[target.entity_id] = int(hits.get(target.entity_id) or 0) + 1
        ctx.actor.turn_flags[RAYS_STATE] = hits
        if hits[target.entity_id] == 2:
            ctx.engine._apply_condition(target, "condition:typed.burning", SCORCHING_RAYS,
                                        ctx.actor.entity_id, expires_on="UNTIL_REMOVED", data={"label": "Burning"})
            ctx.rider("Scorching Ray Art: two rays hit this creature; it is Burning.")
    state = _state(ctx)
    if state is None:
        return
    hits = dict(state.get("hits") or {})
    count = int(hits.get(target.entity_id) or 0) + 1
    hits[target.entity_id] = count
    state["hits"] = hits
    state["total"] = int(state.get("total") or 0) + 1
    _put(ctx.actor, ctx.typed.get("maneuver_of"), state)
    owned = set(state.get("owned") or ())
    if CASCADING in owned and ctx.typed.get("maneuver") != "barrage_cascade":
        critical = next((bool((event.payload or {}).get("critical")) for event in reversed(ctx.engine.events[-12:])
                         if event.event_type == "DAMAGE_ROLLED" and event.actor_id == ctx.actor.entity_id
                         and target.entity_id in (event.target_ids or ())), False)
        if critical or target.current_hp <= 0:
            state["cascade_pending"] = [*state.get("cascade_pending", []), target.entity_id]
            _put(ctx.actor, ctx.typed.get("maneuver_of"), state)
            ctx.rider("Cascading Barrage: critical hit or 0 HP; choose a different target for one extra ranged attack without an Action.")
    if state["total"] == 2:
        if BLITZ in owned and ctx.actor.resources.get(FOCUS, 0) < 1:
            ctx.engine._gain_resource(ctx.actor, FOCUS, 1, BLITZ)
            ctx.rider("Blitz Focus: two attacks hit during this Barrage; Martial Focus regained.")
        if (COURT_CONDITION in {c.condition_id for c in ctx.actor.conditions.values()}
                and not ctx.actor.turn_flags.get("barrage_court_focus_used") and ctx.actor.resources.get(FOCUS, 0) < 1):
            ctx.actor.turn_flags["barrage_court_focus_used"] = True
            ctx.engine._gain_resource(ctx.actor, FOCUS, 1, COURT)
            ctx.rider("Court of Falling Stars: two Barrage attacks hit; Martial Focus regained once this turn.")
    if count != 2:
        return
    if COURT_CONDITION in {c.condition_id for c in ctx.actor.conditions.values()}:
        from .effect_durations import token

        ctx.engine._apply_condition(target, COURT_TARGET, COURT, ctx.actor.entity_id,
                                    expires_on=token("start", ctx.actor.entity_id, ctx.actor.turns_started + 1),
                                    data={"label": "Court of Falling Stars target"})
        ctx.rider("Court of Falling Stars: this creature was hit twice by the Barrage; chosen allies can use their Advantage before your next turn.")
    if BLOWBACK in owned and target.active:
        _blowback(ctx, target)
    if state.get("modifier") == PINNING and target.active:
        _pinning(ctx, target)


@hook("candidate_allowed")
def _cascade_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is not None and str(getattr(action, "source_definition_id", "")).endswith(f".{COURT_SELECT}"):
        if int(actor.turn_flags.get(COURT_REMAINING) or 0) <= 0 or not any(
                row.condition_id == COURT_CONDITION for row in actor.conditions.values()):
            return False
        chosen = candidate.target_ids[0] if candidate.target_ids else None
        return bool(chosen and chosen != actor.entity_id and not any(
            row.condition_id == COURT_ALLY and row.source_actor_id == actor.entity_id
            for row in engine.state.actors[chosen].conditions.values()))
    if action is None or ((action.parameters or {}).get("typed") or {}).get("maneuver") != "barrage_cascade":
        return None
    typed = (action.parameters or {}).get("typed") or {}
    state = (actor.turn_flags.get(STATE) or {}).get(typed.get("maneuver_of")) or {}
    pending = list(state.get("cascade_pending") or [])
    if not pending:
        return False
    return bool(candidate.target_ids and candidate.target_ids[0] != pending[0])


def _blowback(ctx: Any, target: Any) -> None:
    from ..typed_executor import Context, block_save

    cache = {"barrage_blowback": True}
    subject = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, cache)
    # Owner text: Strength save, 5-foot push on failure; collision alone makes it Prone.
    block_save(subject, {"type": "save", "ability": "str", "on_fail": [
        {"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}],
        "on_success": []})
    ctx.rider("Blowback Barrage: the second hit forced a Strength save; failure pushes 5 feet.")


@hook("collision")
def _blowback_collision(ctx: Any, target: Any, blocked_at: Any, remaining_ft: int) -> None:
    if not ctx.damage_cache.get("barrage_blowback"):
        return
    ctx.engine._apply_condition(target, "condition:typed.prone", BLOWBACK, ctx.actor.entity_id,
                                expires_on="STAND_UP", data={"label": "Prone"})
    ctx.rider("Blowback Barrage: the push struck a solid obstacle; the creature fell Prone.")


def _pinning(ctx: Any, target: Any) -> None:
    from ..typed_executor import Context, block_save

    subject = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, {})
    block_save(subject, {"type": "save", "ability": "dex", "on_fail": [{
        "type": "condition", "condition": "pinning_volley", "applies_to": "target",
        "expires_on": "START_OF_TARGET_NEXT_TURN"}], "on_success": [{
        "type": "speed", "applies_to": "target", "amount": -10,
        "expires_on": "START_OF_TARGET_NEXT_TURN"}]})
    ctx.rider("Pinning Volley: the second hit forced a Dexterity save; failure sets Speed to 0, success reduces it by 10 feet until its next turn.")

"""Void sphere riders (rider lane C4, 2026-09-30; owner: "i want everything we can automated, keep going until its only the
non-combat ones left"). Printed text: authority/typed_mechanics/rules_text.json and the Sphere of Void core rules (Hollowed, Empty
Step, ordinary temporary effects). Hollowed itself is combat/rules/typed_conditions.json; the Empty Step reaction teleport is
combat/ext/teleport_steps.py. Every hook returns early unless the creature owns the ability (its compiled action, reaction row or
feature row) or holds a condition/state one of these abilities put on it.

- Teleport locks (teleport_gate): Absolute Quiet Gap ("teleportation into or out of the area requires a successful Cultivation
  Check against your Cultivation Save DC"); Void Prison ("the target's teleportation fails unless it first succeeds on a
  Cultivation Check against your Cultivation Save DC"); Still Talisman ("the first hostile teleportation effect that would move
  through, into, or out of the protected target must succeed on a Cultivation Check ... Failed Check: The teleportation fails and
  the Still Talisman ends. Successful Check: The teleportation succeeds and the Still Talisman ends"; effect ``void_still_talisman``
  guards the touched square).
- Void Prison: "the target cannot willingly leave the prison" -- condition ``void_prison`` (Speed 0 while it lasts, its DC stored).
- Void Ward: "If the triggering effect is a Cultivation Attack, area talent, Barrier collision, Force damage, Necrotic damage,
  Psychic damage, or an effect from a creature that is Hollowed, add your Proficiency Bonus to the reduction" (reaction_amount:
  the Proficiency Bonus row counts only then; Barrier collisions stay with the GM).
- Cost-Denying Needle: temporary-only recovery denial is a manual reminder pending a general recovery-provenance seam.
- No-Purchase Body: while Void Shell lasts, Opportunity Attacks against you are made with Disadvantage and
  forced movement against you is reduced by 10 feet (attack_mode / forced_movement_reduction), and the first
  creature each turn that hits you in melee receives a Void Pressure (Empty Vitality or Unsettle Invisibility, asked).
- Void Shell: "once per turn, when a creature hits you with a melee Cultivation Attack, it takes Force damage equal to your
  Proficiency Bonus".
- Void-Sovereign Incarnation: Void Needle hits make the target Hollowed until the start of your next turn; a Hollowed creature's
  missed attack roll lets you Empty Step 10 feet without a Reaction (asked).
- Hollow Path Step (reaction on a miss): Empty Step 20 feet as the Reaction; a Hollowed attacker makes it cost 1 CP/Stamina
  before affordability and payment, in the compiled row's paying pool.
- Void-Walking Guard: after your Void Ward resolves, teleport 10 feet at no extra cost (asked).
- Return the Technique to Nothing (reaction to a technique): the general ``contest_against`` effect compares each creature's
  Cultivation Check (PB + key modifier); you win: ``void_counter_technique`` cancels the pending technique and its cost stays spent;
  you lose or tie: the caster becomes Hollowed until the start of your next turn. Legacy ``void_unmake_technique`` rows delegate
  to the same implementation.
- Void Pressure (effect ``void_pressure``, Ten-Thousand Empty Needles): the user picks Empty Vitality (no Temporary HP) or Unsettle
  Invisibility (no Invisible) or Cost Lock until the start of its next turn; the options share a once-per-turn allowance.
"""
from __future__ import annotations

from typing import Any

from . import effect, hook
from .ability_source import cultivation_check, has_row, mechanic_at, mechanic_of, numbers_of

QUIET_ABS, PRISON, TALISMAN = "TAL_VOID_ABSOLUTE_QUIET_GAP", "TAL_VOID_VOID_PRISON", "TAL_VOID_STILL_TALISMAN"
WARD, COST_DENY, NEEDLE = "TAL_VOID_VOID_WARD", "TAL_VOID_COST_DENYING_NEEDLE", "TAL_VOID_VOID_NEEDLE"
SHELL, NO_PURCHASE, SOVEREIGN = "TAL_VOID_VOID_SHELL", "TAL_VOID_NO_PURCHASE_BODY", "TAL_VOID_VOID_SOVEREIGN_INCARNATION"
PATH_STEP, GUARD, UNMAKE = "TAL_VOID_HOLLOW_PATH_STEP", "TAL_VOID_VOID_WALKING_GUARD", "TAL_VOID_RETURN_THE_TECHNIQUE_TO_NOTHING"
HOLLOWED, PRISONED = "condition:typed.hollowed", "condition:typed.void_prison"
TALISMAN_KIND = "void_still_talisman"
COST_LOCK = "condition:typed.void_cost_lock"
USED = "void_pressure_used"
COST_LOCKED = COST_LOCK  # public compatibility name for the reviewed C13 port


@hook("flight")
def sovereign_flight(engine: Any, actor: Any) -> dict[str, int] | None:
    """Only newly sealed incarnation conditions grant dynamic walking-Speed flight."""
    if any(c.condition_id == "condition:typed.void_sovereign_flight"
           and (c.data or {}).get("void_sovereign_flight") == 1
           for c in actor.conditions.values()):
        return {"fly_speed_ft": max(0, int(engine._effective_speed(actor))), "flight_hover": 1}
    return None


def _hollowed(actor: Any) -> bool:
    return any(c.condition_id == HOLLOWED for c in actor.conditions.values())


def _state(engine: Any, actor: Any, name: str) -> Any:
    from . import states

    return states.active(engine, actor, name)


def _context(engine: Any, owner: Any, source_id: str, targets: list[Any]) -> Any:
    from ..typed_executor import Context

    action = engine.action_catalog.get(source_id) or next(iter(engine.action_catalog.values()))
    typed = {**((action.parameters or {}).get("typed") or {}), "effects": [], "riders": []}
    return Context(engine, owner, action, getattr(engine, "_active_intent", None), typed,
                   list(targets), targets[0] if len(targets) == 1 else None, {})


def _ask(engine: Any, owner: Any, key: str, options: dict[str, str], prompt: str, name: str, preferred: str | None = None) -> str | None:
    from .needle import CHOICE, ask, checkpoint_id

    chosen = ask(engine, None, checkpoint_id(engine, key, owner.entity_id), owner, CHOICE + key, list(options), labels=options,
                 preferred=[preferred or next(iter(options))], allow_decline=True, prompt=prompt, name=name)
    return chosen[0] if chosen else None


# ------------------------------------------------------------------------------------------------ teleport locks
def _cells(zone: Any) -> set[tuple[int, int]]:
    return {(cell.x, cell.y) for cell in zone.affected_cells}


def _touches(engine: Any, cells: set[tuple[int, int]], start: Any, destination: Any, through: bool) -> bool:
    points = {(start.x, start.y), (destination.x, destination.y)}
    if through:
        points |= {tuple(c) if not hasattr(c, "x") else (c.x, c.y) for c in engine.grid.ray_cells(start, destination)}
    return bool(points & cells)


def _is_still_talisman(zone: Any) -> bool:
    record = zone.trigger_profile.get("still_talisman")
    return isinstance(record, dict) and record.get("kind") == TALISMAN_KIND


@hook("teleport_gate")
def void_teleport_locks(ctx: Any, start: Any, destination: Any) -> bool | None:
    from .. import zones
    from . import note

    engine, mover = ctx.engine, ctx.actor
    verdict_key = ("void_teleport_lock", mover.entity_id)
    if ctx.damage_cache.get(verdict_key) is not None:
        return ctx.damage_cache[verdict_key]  # one activation carrying two teleport rows is one teleport
    numbers = dict(ctx.numbers or {}) or numbers_of(engine, mover)
    locks: list[tuple[int, str, Any]] = []
    for zone in zones.typed_zones(engine):
        kind = mechanic_at(engine, zone.source_definition_id)
        if kind == QUIET_ABS and _touches(engine, _cells(zone), start, destination, through=False):
            locks.append((int((zone.trigger_profile.get("numbers") or {}).get("save_dc") or 10), "Absolute Quiet Gap", None))
        elif _is_still_talisman(zone) and engine.state.actors.get(zone.owner_id) is not None \
                and engine.state.actors[zone.owner_id].team_id != mover.team_id and _touches(engine, _cells(zone), start, destination, through=True):
            locks.append((int((zone.trigger_profile.get("numbers") or {}).get("save_dc") or 10), "Still Talisman", zone))
    for condition in mover.conditions.values():
        if condition.condition_id == PRISONED:
            locks.append((int((condition.data or {}).get("dc") or 10), "Void Prison", None))
    result = None
    for dc, name, talisman in locks:
        success = cultivation_check(engine, mover, numbers, dc, ctx.source, f"Cultivation Check to teleport ({name})")
        if talisman is not None:
            zones.remove(engine, talisman, "STILL_TALISMAN_SPENT")  # either way "the Still Talisman ends"
        note(engine, ctx.source, mover, f"{name}: {mover.display_name} {'forces its teleport through' if success else 'cannot teleport'} "
                                        f"(Cultivation Check against DC {dc}).", (mover,))
        if not success:
            result = False
            break
    ctx.damage_cache[verdict_key] = result
    return result


@effect("void_still_talisman")
def still_talisman(ctx: Any, row: dict[str, Any]) -> None:
    """Still Talisman: the touched 5-foot square is guarded for 10 minutes (the fight) against the first hostile teleport through,
    into or out of it (a willing creature standing there is guarded while it stays)."""
    from ..gate2_runtime_models import ZoneState
    from .. import zones

    aim = getattr(ctx.intent, "destination", None) or (ctx.target.position if ctx.target is not None else ctx.actor.position)
    zone_id = f"zone:typed:{ctx.actor.entity_id}:{ctx.engine.state.event_sequence + 1}"
    zone = ZoneState(zone_id=zone_id, source_definition_id=ctx.source, owner_id=ctx.actor.entity_id, center=aim, radius_cells=0,
                     affected_cells=(aim,), concentration_link=False, duration_rounds=100, created_round=ctx.engine.state.round_number,
                     trigger_profile={"kind": zones.KIND, "name": "Still Talisman", "terrain": [], "difficult": None, "obscured": None,
                                      "color": "#6c6f86", "visual": {"material": "generic"}, "triggers": [], "numbers": dict(ctx.numbers),
                                      "still_talisman": {"kind": TALISMAN_KIND, "label": "Still Talisman: the first hostile teleport through, into or out of "
                                                 "this square needs a Cultivation Check against its maker's save DC; the talisman then ends"}})
    ctx.engine.state.zones[zone_id] = zone
    ctx.engine._append_event("ZONE_CREATED", ctx.source, actor_id=ctx.actor.entity_id, payload={"zone": zone.model_dump(mode="json")})


@hook("condition_state")
def prison_state(ctx: Any, subject: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    if str(row.get("condition") or "").lower() != "void_prison":
        return None
    return {"data": {"dc": int(ctx.numbers.get("save_dc") or 10),
                     "label": "Void Prison: cannot willingly leave its space; teleporting needs a Cultivation Check against the caster's save DC"}}


# ------------------------------------------------------------------------------------------------ Void Ward
@hook("reaction_amount")
def ward_bonus(engine: Any, actor: Any, row: dict[str, Any], effect: dict[str, Any]) -> int | None:
    if row.get("feature_id") != WARD or effect.get("formula") != "pb" or effect.get("dice"):
        return None
    kind = str(getattr(engine, "_typed_pending_damage_type", None) or "").upper()
    packet = getattr(engine, "_typed_damage_packet", None) or {}
    qualifies = kind in ("FORCE", "NECROTIC", "PSYCHIC") or str(packet.get("kind") or "").startswith("cultivation")
    rolled = next((event for event in reversed(engine.events[-16:]) if event.event_type in ("DAMAGE_ROLLED", "SAVE_ROLLED", "ATTACK_ROLLED")), None)
    if not qualifies and rolled is not None:
        source = engine.action_catalog.get(rolled.source_definition_id)
        typed = ((source.parameters or {}).get("typed") or {}) if source is not None else {}
        if (typed.get("area") or {}).get("size_ft") and typed.get("weapon") is None:
            qualifies = True  # an area talent
        roller = engine.state.actors.get(rolled.actor_id or "")
        if roller is not None and _hollowed(roller):
            qualifies = True  # an effect from a creature that is Hollowed
    return None if qualifies else 0


# ------------------------------------------------------------------------------------------------ Void Needle riders
@hook("after_hit")
def needle_hit(ctx: Any, target: Any, kind: str) -> None:
    if mechanic_of(ctx.action) != NEEDLE and str((ctx.typed or {}).get("source") or "") != NEEDLE:
        return
    if _state(ctx.engine, ctx.actor, "void_sovereign_incarnation") is not None and target.active:
        from ..typed_executor import block_condition

        block_condition(ctx, {"type": "condition", "condition": "hollowed", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN",
                              "evidence": "Void-Sovereign Incarnation: creatures hit by your Void Needle become Hollowed until the start of your next turn"})


@effect('void_pressure')
def void_pressure(ctx, row):
    """Shared Pressure effect; explicit per-hit talents opt out of Needle's turn gate."""
    from ..typed_executor import block_deny_invisible, block_deny_temp_hp
    from .needle import CHOICE, ask, checkpoint_id

    target = ctx.target
    limited = row.get('once_per_turn', True)
    if target is None or not target.active or (limited and ctx.actor.turn_flags.get(USED)):
        return
    pick = row.get('choice')
    if pick is None:
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'void_pressure', target.entity_id),
            ctx.actor, CHOICE + 'void_pressure', ['vitality', 'cost_lock', 'invisibility'],
            labels={'vitality': 'Empty Vitality: cannot gain Temporary Hit Points until your next turn',
                    'cost_lock': 'Cost Lock: must pay the listed technique costs, without discounts, until your next turn',
                    'invisibility': 'Unsettle Invisibility: cannot become Invisible until your next turn'},
            name='Void Pressure', prompt=f'{ctx.action.display_name} hit {target.display_name}. '
                'Choose one extra effect, at no resource cost (once per turn).', preferred=['cost_lock'])
        pick = picked[0] if picked else None
    if pick not in ('vitality', 'cost_lock', 'invisibility'):
        raise ValueError('unknown Void Pressure')
    if limited:
        ctx.actor.turn_flags[USED] = True
    if pick == 'vitality':
        block_deny_temp_hp(ctx, {'applies_to': 'target', 'expires_on': 'START_OF_SOURCE_NEXT_TURN'})
    elif pick == 'invisibility':
        block_deny_invisible(ctx, {'applies_to': 'target', 'expires_on': 'START_OF_SOURCE_NEXT_TURN'})
    else:
        ctx.engine._apply_condition(target, COST_LOCK, ctx.source, ctx.actor.entity_id,
            expires_on='START_OF_SOURCE_NEXT_TURN', data={'label': f'Cost Lock from {ctx.actor.display_name}: '
                'techniques cost at least their listed Qi, Stamina, Resonance and other resources until that caster’s next turn'})
        if not row.get('no_cost_deny') and any(r.get('block') == 'void_cost_deny' for r in getattr(ctx.engine, 'typed_passive_rows', {}).get(ctx.actor.entity_id, ())):
            ctx.engine._append_event('GM_RIDER', ctx.source, actor_id=ctx.actor.entity_id,
                target_ids=(target.entity_id,), payload={'adjudication_text': True,
                'rider': f'Cost-Denying Needle on {target.display_name}: until {ctx.actor.display_name}’s next turn, '
                'the GM must prevent Qi, Stamina or Resonance recovery from ordinary temporary effects. '
                'Recovery from permanent features still works. Recovery is not blocked automatically; '
                'adjust any disallowed recovery manually.'})


@hook('technique_cost_floor')
def locked_costs(engine, actor, source, listed, proposed):
    if any(c.condition_id in {COST_LOCK, "condition:typed.cost_locked"} and c.source_actor_id and c.source_definition_id for c in actor.conditions.values()):
        return dict(listed)
    return None


# ------------------------------------------------------------------------------------------------ being hit / missed
def _melee(engine: Any, source_id: str, cultivation_only: bool) -> bool:
    action = engine.action_catalog.get(source_id)
    if action is None:
        return False
    typed = (action.parameters or {}).get("typed") or {}
    if action.resolution_kind != "TYPED":
        return not cultivation_only and action.resolution_kind in ("ATTACK", "MULTI_ATTACK") and action.range_ft is None
    kinds = {str(e.get("attack_kind") or "") for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"}
    if cultivation_only:
        return "cultivation_melee" in kinds
    return bool(kinds & {"weapon", "unarmed", "cultivation_melee"}) and not typed.get("range_ft")


@hook("event")
def void_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type not in ("DAMAGE_COMMITTED", "ATTACK_ROLLED", "REACTION_RESOLVED"):
        return
    last = engine.events[-1] if engine.events else None
    source = getattr(last, "source_definition_id", "") if getattr(last, "event_type", None) == event_type else ""
    other = engine.state.actors.get(kwargs.get("actor_id") or "")
    if event_type == "DAMAGE_COMMITTED" and other is not None:
        for target_id in kwargs.get("target_ids") or ():
            target = engine.state.actors.get(target_id)
            if target is not None and target.team_id != other.team_id and target.active:
                _shells(engine, target, other, source)
    elif event_type == "ATTACK_ROLLED" and other is not None and not (kwargs.get("payload") or {}).get("provisional_hit"):
        for target_id in kwargs.get("target_ids") or ():
            target = engine.state.actors.get(target_id)
            if target is not None and target.active and target.team_id != other.team_id and _hollowed(other) \
                    and _state(engine, target, "void_sovereign_incarnation") is not None and not _new_sovereign(engine, target):
                if _ask(engine, target, "void_sovereign_step", {"step": "Empty Step up to 10 feet"},
                        f"Void-Sovereign Incarnation: {other.display_name}, Hollowed, missed {target.display_name}. Empty Step up to 10 feet (no Reaction)?",
                        "Void-Sovereign Incarnation"):
                    from ..typed_executor import run_effects

                    form = _state(engine, target, "void_sovereign_incarnation")
                    run_effects(_context(engine, target, form.source_definition_id, [other]), [{"type": "reaction_teleport", "distance_ft": 10,
                                                                                               "name": "Void-Sovereign Incarnation"}])
    elif event_type == "REACTION_RESOLVED" and source == WARD and other is not None and has_row(engine, other.entity_id, "void_walking_guard"):
        attacker = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
        if _ask(engine, other, "void_walking_guard", {"step": "Teleport 10 feet"},
                f"Void-Walking Guard: after Void Ward, {other.display_name} may teleport 10 feet (no extra cost).", "Void-Walking Guard"):
            from ..typed_executor import run_effects

            run_effects(_context(engine, other, source, [attacker] if attacker is not None else []),
                        [{"type": "reaction_teleport", "distance_ft": 10, "name": "Void-Walking Guard"}])


def _shells(engine: Any, target: Any, attacker: Any, source: str) -> None:
    from ..typed_executor import run_effects

    shell = _state(engine, target, "void_shell")
    if shell is None or not attacker.active:
        return
    turn_key = f"{engine.state.round_number}:{engine.state.current_slot_index}"
    if not _new_shell(target) and _melee(engine, source, cultivation_only=True) and target.turn_flags.get("void_shell_turn") != turn_key:
        target.turn_flags["void_shell_turn"] = turn_key
        run_effects(_context(engine, target, shell.source_definition_id, [attacker]),
                    [{"type": "damage", "applies_to": "target", "formula": "pb", "damage_types": ["force"],
                      "evidence": "Void Shell: once per turn, a creature that hits you with a melee Cultivation Attack takes Force damage equal to your Proficiency Bonus"}])
    if has_row(engine, target.entity_id, "void_no_purchase") and not _new_purchase(engine, target) and _melee(engine, source, cultivation_only=False) \
            and target.turn_flags.get("void_no_purchase_turn") != turn_key and attacker.active:
        target.turn_flags["void_no_purchase_turn"] = turn_key
        run_effects(_context(engine, target, shell.source_definition_id, [attacker]), [{"type": "void_pressure", "applies_to": "target"}])


def _no_purchase_active(engine: Any, actor: Any) -> bool:
    """No-Purchase Body: "While Void Shell is active" owns every clause this plug-in answers for it."""
    return has_row(engine, actor.entity_id, "void_no_purchase") and _state(engine, actor, "void_shell") is not None


@hook("attack_mode")
def no_purchase_opportunity(ctx: Any, target: Any) -> str | None:
    """No-Purchase Body: "Opportunity Attacks against you have Disadvantage" while Void Shell is active.

    Only an actual Opportunity Attack aimed at the Shell-wearing owner is answered, and only when that
    owner compiled the printed No-Purchase Body row. Every other attack, and any creature without the
    talent or without an active Shell, is untouched.
    """
    if target is None or not ((ctx.typed or {}).get("opportunity_of") or "opportunity" in str(ctx.source)):
        return None
    return "DISADVANTAGE" if _no_purchase_active(ctx.engine, target) else None


@hook("forced_movement_reduction")
def no_purchase_movement(ctx: Any, subject: Any) -> int | None:
    """No-Purchase Body: "forced movement against you is reduced by 10 feet" while Void Shell is active.

    Returns the printed 10 feet before the engine moves the creature, so an unwilling shove, push or
    pull against this owner lands 10 feet shorter and stops entirely if less than 10 feet remain.
    """
    return 10 if _no_purchase_active(ctx.engine, subject) else None


# ------------------------------------------------------------------------------------------------ Hollow Path Step
@hook("generic_reaction_costs")
def path_step_costs(engine: Any, actor: Any, other: Any, row: dict[str, Any], costs: list[dict[str, Any]]) -> Any:
    """Only the owner's Hollow Path Step against a Hollowed attacker costs one point."""
    if row.get("feature_id") != PATH_STEP or other is None or not _hollowed(other):
        return None
    return [{**cost, "amount": 1} if int(cost.get("amount") or 0) == 2 else dict(cost) for cost in costs]


@effect("void_path_step")
def path_step(ctx: Any, row: dict[str, Any]) -> None:
    """Empty Step after the generic row pays its actual cost and spends the Reaction."""
    from ..typed_executor import run_effects

    run_effects(ctx, [{"type": "reaction_teleport", "distance_ft": 20, "name": "Hollow Path Step"}])


# ------------------------------------------------------------------------------------------------ Return the Technique to Nothing
@effect("void_unmake_technique")
def unmake_technique(ctx: Any, row: dict[str, Any]) -> None:
    """Legacy saved effect delegates to the same general contest as new rows."""
    from .contests import contest_against
    from dataclasses import replace
    pending = getattr(ctx.engine, "_typed_pending_technique", None) or {}
    caster = ctx.engine.state.actors.get(pending.get("actor") or "") or ctx.target
    if caster is None:
        return
    contest_against(replace(ctx, targets=[caster], target=caster), {
        "actor_check": {"kind": "cultivation", "label": "Cultivation Check"},
        "target_check": {"kind": "cultivation", "label": "Cultivation Check"},
        "on_success": [{"type": "void_counter_technique"}],
        "on_fail": [{"type": "condition", "condition": "hollowed", "applies_to": "target",
                     "expires_on": "START_OF_SOURCE_NEXT_TURN"}]})


@effect("void_counter_technique")
def counter_technique(ctx: Any, row: dict[str, Any]) -> None:
    """Only the printed reaction's successful contest cancels its pending technique."""
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_typed_countered")
    from . import note

    pending = getattr(ctx.engine, "_typed_pending_technique", None) or {}
    caster = ctx.target
    if pending and caster is not None:
        ctx.engine._typed_countered = True
        note(ctx.engine, ctx.source, ctx.actor, f"Return the Technique to Nothing: {caster.display_name}'s technique fails to take hold; its cost is spent.", (caster,))


@hook("compile_block")
def void_blocks(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Markers for passive Void talents read above (combat/rules/feature_blocks.d/riders_c4.json)."""
    if block in ("void_cost_deny", "void_no_purchase", "void_walking_guard", "void_return_to_zero", "void_cause_emptying"):
        return [{**row, "block": block, "keeps_compiling": True,
                 **({"hit_policy": 1} if spec.get("hit_policy") == 1 else {})}]
    return None


# ------------------------------------------------------------------------------------------------ suppressing benefits
RTZ, CER, NULL_SEAL, WORLD = "TAL_VOID_RETURN_TO_ZERO", "TAL_VOID_CAUSE_EMPTYING_REVERSAL", "TAL_VOID_NULLIFICATION_SEAL", "TAL_VOID_WORLD_OF_NOTHING"
_POOLS = ("resource:core.qi", "resource:core.stamina", "resource:core.resonance")


def _pick_benefit(ctx: Any, target: Any, fields: list[str] | None) -> str | None:
    from .benefit_suppression import benefits

    rows = benefits(ctx.engine, target, fields)
    if not rows:
        from . import note

        note(ctx.engine, ctx.source, ctx.actor, f"{ctx.action.display_name}: {target.display_name} has no ordinary temporary benefit to suppress.", (target,))
        return None
    return _ask(ctx.engine, ctx.actor, "void_benefit", {row["id"]: row["label"] for row in rows},
                f"{ctx.action.display_name}: choose the benefit on {target.display_name} to suppress.", ctx.action.display_name)


@effect("void_benefit_pick")
def benefit_pick(ctx: Any, row: dict[str, Any]) -> None:
    """Nullification Seal: "Choose one active ordinary temporary benefit affecting the target" (before its save; the save's rows then
    suppress the chosen one with ``void_benefit_apply``)."""
    target = ctx.target
    if target is not None and target.active:
        ctx.damage_cache[("void_benefit", target.entity_id)] = _pick_benefit(ctx, target, row.get("fields"))


@effect("void_benefit_apply")
def benefit_apply(ctx: Any, row: dict[str, Any]) -> None:
    """{"until": "concentration" | "owner_turn", "repeat_save": "CHA" (optional)}: suppress the benefit chosen for this target."""
    from .benefit_suppression import suppress

    target = ctx.target
    chosen = ctx.damage_cache.get(("void_benefit", target.entity_id)) if target is not None else None
    if not chosen:
        return
    repeat = {"ability": str(row["repeat_save"]).upper(), "dc": int(ctx.numbers.get("save_dc") or 10)} if row.get("repeat_save") else None
    suppress(ctx.engine, ctx.actor, target, chosen, str(row.get("until") or "owner_turn"), ctx.source, repeat,
             label=f"{ctx.action.display_name}: a benefit is suppressed" + (" (it repeats the save at the end of its turns)" if repeat else ""))


@effect("void_suppress_benefit")
def suppress_benefit(ctx: Any, row: dict[str, Any]) -> None:
    """{"fields": ["damage_resistance"], "until": "owner_turn"}: choose one such benefit on the target now and suppress it
    (Nullifying Strike's failed save: "suppress one ordinary temporary Resistance until the start of your next turn")."""
    from .benefit_suppression import suppress

    target = ctx.target
    if target is None or not target.active:
        return
    chosen = _pick_benefit(ctx, target, row.get("fields"))
    if chosen:
        suppress(ctx.engine, ctx.actor, target, chosen, str(row.get("until") or "owner_turn"), ctx.source,
                 label=f"{ctx.action.display_name}: a benefit is suppressed")


def _action_start(engine: Any, source: str) -> int | None:
    for index in range(len(engine.events) - 1, -1, -1):
        event = engine.events[index]
        if event.event_type == "INTENT_ACCEPTED" and event.source_definition_id == source:
            return index
    return None


def _pool(actor: Any, cost: int) -> str | None:
    return next((key for key in _POOLS if actor.resources.get(key, 0) >= cost), None)


@hook("technique_used")
def benefit_reactions(ctx: Any) -> None:
    """Return to Zero ("A creature within 60 feet gains or activates an ordinary temporary benefit ... The target makes a Charisma
    saving throw. Failed Save: The chosen benefit does not take effect. Successful Save: The chosen benefit is suppressed until the
    start of your next turn") and Cause-Emptying Reversal ("A creature within 90 feet activates an ordinary temporary effect that
    would grant a benefit ... Make a Cultivation Check against the triggering creature's Cultivation Save DC ... Successful Check: The
    triggering benefit fails ... Failed Check: The benefit functions, but the target becomes Hollowed until the start of your next
    turn"): offered once the activation's benefits have landed, to a hostile owner with its Reaction and CP."""
    from .benefit_suppression import benefits, cancel, suppress
    from ..typed_executor import block_condition
    from . import note

    engine, caster = ctx.engine, ctx.actor
    start = _action_start(engine, ctx.source)
    if start is None:
        return
    gained: dict[str, list[dict[str, str]]] = {}
    for creature in engine.state.actors.values():
        if not creature.active:
            continue
        rows = [row for row in benefits(engine, creature, since=start)
                if getattr(creature.modifiers.get(row["id"].partition(":")[2]) or creature.conditions.get(row["id"].partition(":")[2]),
                           "source_definition_id", None) == ctx.source]
        if rows:
            gained[creature.entity_id] = rows
    if not gained:
        return
    for reactor in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if not reactor.active or not reactor.reaction_available or reactor.team_id == caster.team_id:
            continue
        for block, mechanic, cost, feet in (("void_return_to_zero", RTZ, 4, 60), ("void_cause_emptying", CER, 8, 90)):
            if not has_row(engine, reactor.entity_id, block) or _pool(reactor, cost) is None:
                continue
            from .reaction_ranges import reach
            feet = reach(engine, reactor, mechanic, feet)
            options = {f"{who}|{row['id']}": f"{engine.state.actors[who].display_name}: {row['label']}" for who, rows in gained.items()
                       for row in rows if engine.state.actors[who].team_id != reactor.team_id
                       and engine._distance_actor_to_actor(reactor, engine.state.actors[who] if block == "void_return_to_zero" else caster) <= feet}
            if not options:
                continue
            name = "Return to Zero" if block == "void_return_to_zero" else "Cause-Emptying Reversal"
            chosen = _ask(engine, reactor, block, options, f"{name}: {caster.display_name} used {ctx.action.display_name}. Spend your Reaction and "
                          f"{cost} CP to undo one benefit it gave?", name)
            if not chosen:
                continue
            who, benefit = chosen.split("|", 1)
            holder = engine.state.actors[who]
            from ..paid_relocation import activation as relocation_activation
            with relocation_activation(engine, reactor, mechanic, independent=True):
                reactor.reaction_available = False
                engine._spend_resource(reactor, _pool(reactor, cost), cost, mechanic)
                dc = int(numbers_of(engine, reactor).get("save_dc") or 10)
                engine._append_event("REACTION_RESOLVED", mechanic, actor_id=reactor.entity_id, target_ids=(holder.entity_id,),
                                     payload={"checkpoint": "BENEFIT_GAINED", "benefit": benefit})
                if block == "void_return_to_zero":
                    roll = engine._roll_save(holder, "CHA", dc, mechanic)
                    if roll is not None and roll.total >= dc:
                        suppress(engine, reactor, holder, benefit, "owner_turn", mechanic, label="Return to Zero: a benefit is suppressed")
                    else:
                        cancel(engine, holder, benefit, mechanic)
                        note(engine, mechanic, reactor, f"Return to Zero: {options[chosen]} does not take effect.", (holder,))
                else:
                    caster_dc = int(numbers_of(engine, caster).get("save_dc") or 10)
                    if cultivation_check(engine, reactor, numbers_of(engine, reactor), caster_dc, mechanic, "Cultivation Check (Cause-Emptying Reversal)"):
                        cancel(engine, holder, benefit, mechanic)
                        note(engine, mechanic, reactor, f"Cause-Emptying Reversal: {options[chosen]} fails.", (holder,))
                    else:
                        block_condition(_context(engine, reactor, mechanic, [caster]),
                                        {"type": "condition", "condition": "hollowed", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN",
                                         "evidence": "Failed Check: The benefit functions, but the target becomes Hollowed until the start of your next turn."})
                return


# ------------------------------------------------------------------------------------------------ Court of the Empty Horizon / World of Nothing
COURT = "TAL_VOID_COURT_OF_THE_EMPTY_HORIZON"
NO_TEMP_HP = "condition:typed.no_temp_hp"
_CHOICES = {"damage": "It takes 2d8 Force, Necrotic, or Psychic damage", "reactions": "It cannot take Reactions until the start of its next turn",
            "healing": "It cannot regain Hit Points until the start of its next turn", "teleport": "It cannot teleport until the start of its next turn",
            "concentration": "Disadvantage on its next Concentration saving throw before the start of its next turn"}


def _courts(engine: Any) -> list[Any]:
    from .. import zones

    return [zone for zone in zones.typed_zones(engine) if mechanic_at(engine, zone.source_definition_id) == COURT]


def _world(zone: Any) -> bool:
    return any(str(row.get("id")) == "world_no_cp" for row in zone.trigger_profile.get("inside") or [])


@effect("void_court_choice")
def court_choice(ctx: Any, row: dict[str, Any]) -> None:
    """Court of the Empty Horizon, an enemy's failed start-of-turn save: "Choose one: it takes 2d8 Force, Necrotic, or Psychic damage; it
    cannot take Reactions until the start of its next turn; it cannot regain HP until the start of its next turn; it cannot teleport until
    the start of its next turn; it has Disadvantage on its next Concentration saving throw before the start of its next turn." The Court's
    owner chooses. World of Nothing: "when an enemy fails the Domain's saving throw, it also cannot benefit from Invisible until the start
    of its next turn"."""
    from ..typed_executor import block_condition, block_deny_invisible, run_effects, stated_expiry

    target = ctx.target
    if target is None or not target.active:
        return
    pick = _ask(ctx.engine, ctx.actor, "void_court_choice", dict(_CHOICES),
                f"Court of the Empty Horizon: {target.display_name} failed its saving throw; choose what the Court does to it.", "Court of the Empty Horizon",
                preferred="damage") or "damage"
    if pick == "damage":
        run_effects(ctx, [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": ["force", "necrotic", "psychic"],
                           "evidence": _CHOICES["damage"]}])
    elif pick == "reactions":
        block_condition(ctx, {"type": "condition", "condition": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN",
                              "evidence": _CHOICES["reactions"]})
    elif pick == "healing":
        run_effects(ctx, [{"type": "healing_reduction", "applies_to": "target", "evidence": "cannot regain Hit Points until the start of its next turn"}])
    elif pick == "teleport":
        block_condition(ctx, {"type": "condition", "condition": "cannot_teleport", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN",
                              "evidence": _CHOICES["teleport"]})
    else:
        ctx.engine._apply_condition(target, "condition:typed.concentration_mode", ctx.source, ctx.actor.entity_id,
                                    expires_on=stated_expiry(ctx, {"expires_on": "START_OF_TARGET_NEXT_TURN"}, target, condition=True),
                                    data={"rule": {"concentration_mode": "DISADVANTAGE", "next": True},
                                          "label": "Disadvantage on its next Concentration save (Court of the Empty Horizon)"})
    zone = next((z for z in _courts(ctx.engine) if z.owner_id == ctx.actor.entity_id and ctx.engine._footprint_intersects(target, z.affected_cells)), None)
    if zone is not None and _world(zone):
        block_deny_invisible(ctx, {"applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"})


def _court_sync(engine: Any) -> None:
    """"Enemies inside the Domain ... cannot gain Temporary HP": a no_temp_hp condition on each enemy standing in a Court, taken off when it
    leaves or the Court ends (filed under the Court's action with the zone's id)."""
    courts = _courts(engine)
    for creature in engine.state.actors.values():
        want = {zone.zone_id: zone for zone in courts if creature.active and engine.state.actors.get(zone.owner_id) is not None
                and engine.state.actors[zone.owner_id].team_id != creature.team_id and engine._footprint_intersects(creature, zone.affected_cells)}
        have = {str((c.data or {}).get("court")): key for key, c in creature.conditions.items() if c.condition_id == NO_TEMP_HP and (c.data or {}).get("court")}
        for zone_id, key in have.items():
            if zone_id not in want:
                condition = creature.conditions.pop(key)
                engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=condition.source_actor_id,
                                     target_ids=(creature.entity_id,), payload={"condition_id": NO_TEMP_HP, "instance_id": key, "reason": "LEFT_COURT"})
        for zone_id, zone in want.items():
            if zone_id not in have:
                engine._apply_condition(creature, NO_TEMP_HP, zone.source_definition_id, zone.owner_id, expires_on="UNTIL_REMOVED",
                                        data={"court": zone_id, "label": "Inside the Court of the Empty Horizon: cannot gain Temporary HP"})


@hook("event")
def court_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type in ("ZONE_CREATED", "ZONE_REMOVED", "MOVEMENT_COMMITTED", "CONCENTRATION_ENDED", "ENTITY_DEFEATED"):
        if _courts(engine) or any((c.data or {}).get("court") for a in engine.state.actors.values() for c in a.conditions.values() if c.condition_id == NO_TEMP_HP):
            _court_sync(engine)


@hook("turn_start")
def court_turn(engine: Any, actor: Any) -> None:
    if _courts(engine) or any((c.data or {}).get("court") for a in engine.state.actors.values() for c in a.conditions.values() if c.condition_id == NO_TEMP_HP):
        _court_sync(engine)


@hook("incoming_damage")
def court_ward(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str, source_actor_id: str) -> int | None:
    """"When an ally inside the Domain takes damage from a supernatural area effect, reduce that damage by your Proficiency Bonus"."""
    source = engine.action_catalog.get(str(source_definition_id or ""))
    typed = ((source.parameters or {}).get("typed") or {}) if source is not None else {}
    if not ((typed.get("area") or {}).get("size_ft")) or typed.get("weapon") is not None:
        return None
    for zone in _courts(engine):
        owner = engine.state.actors.get(zone.owner_id)
        if owner is not None and owner.entity_id != target.entity_id and owner.team_id == target.team_id \
                and engine._footprint_intersects(target, zone.affected_cells):
            return int((zone.trigger_profile.get("numbers") or {}).get("pb") or 2)
    return None


@hook("technique_used")
def world_first_benefit(ctx: Any) -> None:
    """World of Nothing: "the first time an enemy inside the Domain gains an ordinary temporary benefit each round, that benefit is
    suppressed until the start of its next turn"."""
    from .benefit_suppression import benefits, suppress

    engine = ctx.engine
    worlds = [zone for zone in _courts(engine) if _world(zone)]
    if not worlds:
        return
    start = _action_start(engine, ctx.source)
    if start is None:
        return
    for creature in engine.state.actors.values():
        for zone in worlds:
            owner = engine.state.actors.get(zone.owner_id)
            if owner is None or owner.team_id == creature.team_id or not creature.active or not engine._footprint_intersects(creature, zone.affected_cells):
                continue
            flag = f"void_world_benefit_round_{engine.state.round_number}"
            if creature.turn_flags.get(flag):
                continue
            rows = [row for row in benefits(engine, creature, since=start)
                    if getattr(creature.modifiers.get(row["id"].partition(":")[2]) or creature.conditions.get(row["id"].partition(":")[2]),
                               "source_definition_id", None) == ctx.source]
            if rows:
                creature.turn_flags[flag] = True
                suppress(engine, owner, creature, rows[0]["id"], "holder_turn", zone.source_definition_id,
                         label=f"World of Nothing: {rows[0]['label']} is suppressed until its next turn")


# ------------------------------------------------------------------------------------------------ Consume Spellwork
CONSUME = "TAL_VOID_CONSUME_SPELLWORK"
CONSUMED = "condition:typed.void_consumed"


def _technique_action(engine: Any, caster: Any, technique: str) -> Any:
    return next((engine.action_catalog[a] for a in caster.action_ids if a in engine.action_catalog
                 and (mechanic_of(engine.action_catalog[a]) == technique or a == technique)), None)


@effect("void_consume")
def consume_spellwork(ctx: Any, row: dict[str, Any]) -> None:
    """Consume Spellwork (Reaction, a technique targets only you): "Make a Cultivation Check against: 10 + the triggering effect's CP cost
    ... + the triggering creature's Proficiency Bonus. If the effect has no CP cost ..., use half the triggering creature's CR or CL,
    rounded up. Successful Check: Choose one: reduce the damage against you by half; gain Advantage on one saving throw against the
    triggering effect; use Empty Step before the effect resolves; suppress one ordinary rider effect against yourself. ... cannot affect
    area effects unless you are the only target chosen by the effect." Area techniques are left out (the table cannot tell that you are
    their only target); the rider-suppression choice stays with the GM."""
    from ..typed_executor import run_effects
    from . import note

    engine, me = ctx.engine, ctx.actor
    pending = getattr(engine, "_typed_pending_technique", None) or {}
    caster = engine.state.actors.get(pending.get("actor") or "") or ctx.target
    if caster is None:
        return
    action = _technique_action(engine, caster, str(pending.get("technique") or ""))
    typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
    if (typed.get("area") or {}).get("size_ft"):
        note(engine, CONSUME, me, "Consume Spellwork cannot affect an area technique (GM: unless you are its only target).", (caster,))
        return
    theirs = numbers_of(engine, caster)
    cost = sum(int(amount) for resource, amount in (action.costs if action is not None else ()) if resource in _POOLS)
    extra = cost if cost else (int(theirs.get("cl") or 1) + 1) // 2
    dc = 10 + extra + int(theirs.get("pb") or 2)
    if not cultivation_check(engine, me, dict(ctx.numbers or {}) or numbers_of(engine, me), dc, CONSUME, "Cultivation Check (Consume Spellwork)"):
        return
    damaging = any(isinstance(e, dict) and e.get("type") in ("damage", "extra_damage") for e in _walk(typed.get("effects") or []))
    saving = any(isinstance(e, dict) and e.get("type") == "save" for e in _walk(typed.get("effects") or []))
    options = {"halve": "Halve the damage it deals you", "advantage": "Advantage on your saving throw against it", "step": "Empty Step before it resolves"}
    pick = _ask(engine, me, "void_consume", options, f"Consume Spellwork: you consume {caster.display_name}'s {getattr(action, 'display_name', 'technique')}. Choose one.",
                "Consume Spellwork", preferred="halve" if damaging else "advantage" if saving else "step")
    if pick in ("halve", "advantage"):
        engine._apply_condition(me, CONSUMED, CONSUME, me.entity_id, expires_on="END_OF_CURRENT_TURN",
                                data={"mode": pick, "source_action": getattr(action, "source_definition_id", ""),
                                      "label": f"Consume Spellwork: {options[pick].lower()} ({getattr(action, 'display_name', 'the technique')})"})
    elif pick == "step":
        run_effects(ctx, [{"type": "reaction_teleport", "distance_ft": 20, "name": "Consume Spellwork: Empty Step"}])


def _walk(rows: Any):
    for row in rows or []:
        if isinstance(row, dict):
            yield row
            for key in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                yield from _walk(row.get(key))


def _consumed(actor: Any, source: str, mode: str) -> Any:
    return next(((key, c) for key, c in actor.conditions.items() if c.condition_id == CONSUMED and (c.data or {}).get("mode") == mode
                 and (c.data or {}).get("source_action") == source), None)


@hook("damage_pending")
def consume_halves(engine: Any, target: Any, pending: int, source_definition_id: str, source_actor_id: str) -> int | None:
    found = _consumed(target, str(source_definition_id or ""), "halve")
    return pending // 2 if found is not None else None


@hook("save")
def consume_advantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    found = _consumed(subject, ctx.source, "advantage")
    if found is None:
        return None
    subject.conditions.pop(found[0], None)  # "one saving throw"
    ctx.engine._append_event("CONDITION_REMOVED", CONSUME, actor_id=subject.entity_id, target_ids=(subject.entity_id,),
                             payload={"condition_id": CONSUMED, "instance_id": found[0], "reason": "CONSUMED"})
    return {"modes": ["ADVANTAGE"]}


# A2VOID: sealed opt-ins preserve historical packets' damage-event semantics.
def _new_shell(actor: Any) -> bool:
    return any((c.data or {}).get('void_shell_hits') == 1 for c in actor.conditions.values())


def _new_purchase(engine: Any, actor: Any) -> bool:
    return any(r.get('block') == 'void_no_purchase' and r.get('hit_policy') == 1
               for r in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ()))


def _new_sovereign(engine: Any, actor: Any) -> bool:
    form = _state(engine, actor, 'void_sovereign_incarnation')
    action = engine.action_catalog.get(form.source_definition_id) if form is not None else None
    if action is None:
        return False
    rows = ((action.parameters or {}).get('typed') or {}).get('effects') or []
    return any((row.get('condition_data') or {}).get('void_sovereign_outcomes') == 1 for row in rows)


def _actual_turn(engine: Any) -> str:
    current = engine.state.actors[engine.state.current_actor_id]
    return f'{engine.state.round_number}:{current.entity_id}:{current.turns_started}'


@hook('hit_snapshot')
def void_shell_snapshot(engine: Any, attacker: Any, target: Any, attack: Any, intent: Any) -> Any:
    """Capture Shell before damage can end Concentration; no inferred damage hit."""
    shell = _state(engine, target, 'void_shell')
    if shell is None:
        return None
    shell_hit = _new_shell(target)
    purchase = _new_purchase(engine, target)
    if not shell_hit and not purchase:
        return None
    return {'void_shell_hit': {'source': shell.source_definition_id, 'shell': shell_hit,
                              'purchase': purchase, 'numbers': numbers_of(engine, target)}}


@hook('hit_final')
def void_shell_final(ctx: Any, target: Any, kind: str) -> None:
    from ..typed_executor import Context, run_effects
    from .needle import CHOICE, ask, checkpoint_id
    from .choice_prompt import action_context
    from .trigger_source import described

    receipt = ctx.hit_snapshots.get('void_shell_hit')
    if not receipt or not ctx.actor.active:
        return
    notice = getattr(ctx, 'attack_notice', None)
    strike = ctx.attack_effect or {}
    delivery = str(strike.get('attack_kind') or '')
    melee = notice.melee if notice is not None else delivery in ('cultivation_melee', 'unarmed', 'melee') or (
        delivery == 'weapon' and ctx.typed.get('range_ft') is None)
    cultivation = delivery == 'cultivation_melee'
    if not melee:
        return
    engine = ctx.engine
    action = engine.action_catalog[receipt['source']]
    reply = Context(engine, target, action, ctx.intent, {'numbers': receipt['numbers'], 'effects': [], 'riders': []},
                    [ctx.actor], ctx.actor)
    turn_key = _actual_turn(engine)
    if receipt['shell'] and cultivation and target.turn_flags.get('void_shell_turn') != turn_key:
        target.turn_flags['void_shell_turn'] = turn_key
        run_effects(reply, [{'type': 'damage', 'applies_to': 'target', 'formula': 'pb', 'damage_types': ['force']}])
    if not receipt['purchase'] or target.turn_flags.get('void_no_purchase_turn') == turn_key or not ctx.actor.active:
        return
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, 'void_no_purchase', ctx.actor.entity_id), target,
        CHOICE + 'void_no_purchase', ['vitality', 'cost_lock', 'invisibility'],
        labels={'vitality': 'Empty Vitality: no Temporary Hit Points until your next turn',
                'cost_lock': 'Cost Lock: no technique discounts until your next turn',
                'invisibility': 'Unsettle Invisibility: deny temporary supernatural invisibility until your next turn; protected sources need a ruling'},
        allow_decline=True, preferred=['cost_lock'], name='No-Purchase Body',
        prompt_context=action_context(engine, ctx.actor, ctx.source, ctx.actor),
        prompt=f"{described(reply, label='No-Purchase Body', with_creature=True)} hit {target.display_name} in melee. "
               f'Apply one Void Pressure to {ctx.actor.display_name} at no cost? Once per turn.')
    if chosen:
        target.turn_flags['void_no_purchase_turn'] = turn_key
        run_effects(reply, [{'type': 'void_pressure', 'applies_to': 'target', 'choice': chosen[0],
                             'once_per_turn': False, 'no_cost_deny': True}])


@hook('after_miss')
def sovereign_confirmed_miss(ctx: Any, target: Any) -> None:
    """A settled miss, including defensive AC changes; players choose the landing."""
    if target is None or not target.active or not _new_sovereign(ctx.engine, target) or not _hollowed(ctx.actor):
        return
    form = _state(ctx.engine, target, 'void_sovereign_incarnation')
    if form is None:
        return
    turn_key = _actual_turn(ctx.engine)
    free = target.turn_flags.get('void_sovereign_free_turn') != turn_key
    # Empty Step explicitly permits CP or Stamina; other Path pools do not pay for it.
    pools = [key for key in ('resource:core.qi', 'resource:core.stamina') if target.resources.get(key, 0) >= 1]
    options = {'free': 'Empty Step up to 10 feet, no resource cost'} if free else {
        key: f'Empty Step up to 10 feet, pay 1 {"CP" if key.endswith(".qi") else "Stamina"}' for key in pools}
    if not options:
        return
    from .needle import CHOICE, ask, checkpoint_id
    from .choice_prompt import action_context
    from .trigger_source import described
    from .teleport_steps import reaction_teleport

    reply = _context(ctx.engine, target, form.source_definition_id, [ctx.actor])
    reply.intent = ctx.intent
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'void_sovereign_step', target.entity_id),
        target, CHOICE + 'void_sovereign_step', list(options), labels=options,
        preferred=list(options)[:1], allow_decline=True, name='Void-Sovereign Incarnation',
        prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, target),
        prompt=f"{described(reply, label='Void-Sovereign Incarnation', with_creature=True)} missed {target.display_name}. "
               f'{ctx.actor.display_name} is Hollowed. Empty Step up to 10 feet without a Reaction? '
               + ('Your one free Empty Step this turn is available.' if free else 'Your free step this turn is spent; pay 1 CP or 1 Stamina.'))
    if chosen and reaction_teleport(reply, {'distance_ft': 10, 'name': 'Void-Sovereign Incarnation'}):
        if free:
            target.turn_flags['void_sovereign_free_turn'] = turn_key
        else:
            ctx.engine._spend_resource(target, chosen[0], 1, form.source_definition_id)


@hook('compile_actions')
def sovereign_needles(info: dict[str, Any]) -> Any:
    """Seal a two-recipient sibling using the existing player-owned target menu."""
    import copy
    record = (info['mechanics'].get(SOVEREIGN) or {}) if SOVEREIGN in info['owned_ids'] else {}
    if not any((e.get('condition_data') or {}).get('void_sovereign_outcomes') == 1 for e in record.get('effects') or []):
        return None
    made = []
    # "Use Empty Step" grants its use; Incarnation has no Empty Step prerequisite.
    # Keep the existing compiler's target/range interpretation and source effects.
    step_id = 'TAL_VOID_EMPTY_STEP'
    if not any(((action.parameters or {}).get('typed') or {}).get('source') == step_id for action in info['actions']):
        from ..factory_compiler import _target_kind
        from ..gate2_runtime_models import ActionDefinition, EconomyKind
        step = info['mechanics'][step_id]
        target_kind, reach = _target_kind(step, info['numbers']['cl'])
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.{step_id}+sovereign_grant",
            display_name='Empty Step (no cost)', owner_id=info['actor_id'], economy=EconomyKind.BONUS_ACTION,
            resolution_kind='TYPED', target_kind=target_kind, range_ft=reach, costs=(),
            parameters={'expected_damage': 0, 'void_sovereign_granted_step': 1,
                'free_use': {'state': 'void_sovereign_incarnation', 'once': 'turn', 'key': SOVEREIGN + ':grant'},
                'typed': {'source': step_id, 'effects': copy.deepcopy(step['effects']), 'riders': list(step['riders']),
                          'range_ft': reach, 'area': None, 'weapon': None, 'numbers': dict(info['numbers']),
                          'duration': copy.deepcopy(step['duration']), 'coverage': step['coverage']}}))
    for action in info['actions']:
        typed = copy.deepcopy((action.parameters or {}).get('typed') or {})
        if typed.get('source') != NEEDLE:
            continue
        # This sibling selects creatures only; object Pressure cannot apply.
        typed['riders'] = [r for r in typed.get('riders') or [] if not str(r).startswith('Fray Barrier:')
                           and r != 'The damage type is Force here (the default Void type).']
        typed['effects'] = [{'type': 'rider_targets', 'count': 2, 'minimum': 1,
            'range_ft': int(typed.get('range_ft') or action.range_ft or 60), 'effects': typed['effects'],
            'evidence': 'your Void Needle targets up to two creatures within range'}]
        made.append(action.model_copy(update={
            'source_definition_id': action.source_definition_id + '+sovereign_two',
            'display_name': action.display_name + ' (up to two creatures)', 'target_kind': 'SELF',
            'parameters': {**action.parameters, 'typed': typed, 'void_sovereign_two': 1}}))
    return made or None


@hook('candidate_allowed')
def sovereign_needle_available(engine: Any, actor: Any, candidate: Any, action: Any) -> Any:
    if action is not None and (action.parameters or {}).get('void_sovereign_two') == 1:
        return None if _new_sovereign(engine, actor) else False
    if action is not None and (action.parameters or {}).get('void_sovereign_granted_step') == 1 and not _new_sovereign(engine, actor):
        return False
    free = (action.parameters or {}).get('free_use') if action is not None else None
    if free and free.get('state') == 'void_sovereign_incarnation' and _new_sovereign(engine, actor):
        return False if actor.turn_flags.get('void_sovereign_free_turn') == _actual_turn(engine) else None
    return None


@hook('technique_used')
def sovereign_spend_free_step(ctx: Any) -> None:
    free = (ctx.action.parameters or {}).get('free_use') or {}
    if free.get('state') == 'void_sovereign_incarnation' and _new_sovereign(ctx.engine, ctx.actor):
        ctx.actor.turn_flags['void_sovereign_free_turn'] = _actual_turn(ctx.engine)

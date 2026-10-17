"""Shadow (rider lane 10, 2026-09-29): Shadow Anchors and the talents that use them, the Court of the Second Silhouette's lasting
benefits, the Shadow Lurk, the silhouette-swapping reactions and the Shadow-Sovereign's benefits. Rules text: the owner's Sphere
Compendium, "Shadow" (authority/typed_mechanics/rules_text.json; the core rules -- Shadowed Space, Shadow Anchor, Shadow Mark -- are
the compendium's "Core Shadow Rules").

  Shadow Anchor   "A Shadow Anchor occupies one 5-foot space. It lasts for 1 hour. You may maintain a number of Shadow Anchors equal
                  to your Proficiency Bonus."  Shadow Mark: "The creature's silhouette counts as one of your Shadow Anchors."
  Second Silhouette (Space or Object): "Create one Shadow Anchor. The anchor lasts for 1 hour."  -- the action "Second Silhouette:
                  Shadow Anchor" (any square within 60 feet; the table does not check Dim Light, Darkness or a Cast Shadow there).
  Clinging Silhouette (+1 CP): "You may create a Shadow Anchor attached to a creature or object. The anchor moves with its bearer. An
                  unwilling creature makes a Wisdom saving throw ... repeats the saving throw at the end of each of its turns, ending the
                  anchor on a success."  -- "Second Silhouette: clinging anchor" on a creature within 60 feet.
  Long Road Between Lanterns (Action, 5 CP): "Teleport from one of your Shadow Anchors into another Shadow Anchor within range. You may
                  bring a number of willing creatures equal to your Proficiency Bonus. Each creature must begin within 5 feet of the
                  starting anchor and arrive within 5 feet of the destination anchor."  -- offered while the user stands within 5 feet of
                  one of its anchors, to a square within 5 feet of another. New travel policies let the caster invite perceived willing
                  creatures, ask each invitee for consent and let the caster choose each arrival; automatic selection admits only allies.
  Sever the Second Silhouette: "Until the end of your next turn, the target's separated shadow remains in its current space as a
                  Shadow Anchor."
  Court of the Second Silhouette: "Every visible shadow inside the Domain becomes a temporary Shadow Anchor for you" (its squares count
                  as anchors); "You and Allies: Gain +1 AC ... May move 5 feet without provoking opportunity attacks after an enemy misses
                  them"; "Enemies: Cannot benefit from ordinary Invisible against you" (their Invisible does not count in an attack between
                  them and you: the ``masked_conditions`` hook).
  Shadow Lurk     a summon (combat/rules/summons.json "shadow_lurk"); "If the lurk is reduced to 0 HP ... it vanishes and the target
                  becomes Stunned until the end of its next turn" (here the user, whose shadow it is); "Either the target or the lurk may
                  retract it as a Bonus Action" ("Retract Shadow Lurk").
  Shadowless Reversal (Reaction, 5 CP, once per round): "You are hit by an attack: Leave a false silhouette behind and use Shadow Step
                  immediately. If you move outside the attack's reach, line, or area, the attack misses. Your abandoned silhouette remains
                  until the start of your next turn. The first creature entering its space or starting its turn there makes a Dexterity
                  saving throw. Failed Save: Restrained until the start of its next turn. Successful Save: Speed reduced by 10 feet ..."
  Shadow Exchange (Reaction, 4 CP): "You or an ally within 60 feet is hit by an attack: Teleport the protected creature into one visible,
                  unoccupied Shadowed Space within 20 feet ... If this movement carries the creature outside the triggering attack's reach,
                  line, or area, the attack misses that creature."
                  Both answer the hit (the ``hit_response`` hook) with a step to the square that takes the creature farthest out of the
                  attacker's reach (the attack then misses); none out of reach, no answer. A player on Ask me is asked.
  Silhouette Veil "The first opportunity attack made against you each round has Disadvantage."
  Shadow-Sovereign Incarnation: "Shadow Step range becomes 60 feet; use Shadow Step once per turn without spending CP; apply Shadow Mark
                  with Shadow Fang even when the attack misses."
  Two Shadows Crossing (+2 CP): "Carry one willing creature of your size or smaller through Shadow Step. The creature must begin adjacent
                  to you and arrive in an unoccupied space adjacent to your destination."
  Lingering Trace (+1 CP): "A Shadow Mark you apply lasts for 8 hours ... You may track a number of creatures equal to your Proficiency
                  Bonus. If you exceed this limit, choose one older mark to end." (the fight's whole length; the oldest ends)
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook, note

TAG = "shadow_anchor"
WARD = "tianxia.talent.shadow.shadow_ward"


@hook("decision_text")
def ward_decision_text(engine, context, printed_rules):
    source = str(context.get("reaction_source_id") or "").removeprefix("reaction:typed.")
    if source != WARD:
        return None
    row = next((r for r in getattr(engine, "typed_reaction_rows", {}).get(context.get("reactor_id"), [])
                if r.get("feature_id") == WARD), None)
    if row is None:
        return None
    numbers = row.get("numbers") or {}
    cl, modifier = int(numbers.get("cl") or 1), int(numbers.get("key_mod") or 0)
    dice = 3 if cl >= 17 else 2 if cl >= 11 else 1
    amount = f"{dice}d8 {'+' if modifier >= 0 else '-'} {abs(modifier)}"
    return {"summary": f"Reduce the triggering damage to you or an ally within 30 feet by {amount} "
            f"(including your Path key ability modifier). If the protected creature occupies one of your "
            f"Shadowed Spaces (an area created by your Shadow abilities), add {int(numbers.get('pb') or 2)} "
            "(your Proficiency Bonus) to the reduction. "
            "This protects against this damage only."}
MARK = "Shadow Mark"
SECOND, LONG_ROAD, CLINGING = "TAL_SHADOW_SECOND_SILHOUETTE", "TAL_SHADOW_LONG_ROAD_BETWEEN_LANTERNS", "tianxia.talent.shadow.clinging_silhouette"
COURT, SOVEREIGN, STEP = "TAL_SHADOW_COURT_OF_THE_SECOND_SILHOUETTE", "TAL_SHADOW_SHADOW_SOVEREIGN_INCARNATION", "TAL_SHADOW_SHADOW_STEP"
REVERSAL, EXCHANGE, VEIL = "TAL_SHADOW_SHADOWLESS_REVERSAL", "TAL_SHADOW_SHADOW_EXCHANGE", "tianxia.talent.shadow.silhouette_veil"
LURK = "tianxia.talent.shadow.shadow_lurk"
SOVEREIGN_STATE = "condition:typed.shadow_sovereign"
CLING = "condition:typed.shadow_clinging_anchor"
SILHOUETTE = "shadow_silhouette"


def _placed():
    from . import placed

    return placed


def _rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    return (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])


def _kind(engine: Any, actor: Any, kind: str) -> bool:
    return any(row.get("block") == "shadow" and row.get("kind") == kind for row in _rows(engine, actor))


def _mark_id(owner: Any) -> str:
    from ..typed_executor import mark_condition_id

    return mark_condition_id(MARK, owner.entity_id)


def external(engine: Any, owner: Any) -> list[Any]:
    return _placed().of(engine, TAG, owner_id=owner.entity_id)


def _cell_of(engine: Any, zone: Any) -> Any:
    rider = engine.state.actors.get(str(zone.trigger_profile.get("anchor_id") or ""))
    return rider.position if rider is not None and rider.active else zone.affected_cells[0]


def _court(engine: Any, owner: Any) -> Any | None:
    from .. import zones

    return next((zone for zone in zones.typed_zones(engine) if zone.active and zone.owner_id == owner.entity_id
                 and COURT in str(zone.source_definition_id)), None)


def anchors(engine: Any, owner: Any) -> list[Any]:
    """Every square that is one of the owner's Shadow Anchors: its placed anchors, every creature bearing its Shadow Mark, and every
    square of its Court."""
    cells = [_cell_of(engine, zone) for zone in external(engine, owner)]
    mark = _mark_id(owner)
    cells += [actor.position for actor in engine.state.actors.values() if actor.active and any(c.condition_id == mark for c in actor.conditions.values())]
    court = _court(engine, owner)
    if court is not None:
        cells += list(court.affected_cells)
    unique = []
    for cell in cells:
        if all((cell.x, cell.y) != (seen.x, seen.y) for seen in unique):
            unique.append(cell)
    return unique


def place_anchor(engine: Any, owner: Any, cell: Any, source: str, *, on: Any = None, until: str | None = None) -> Any:
    placed = _placed()
    while len(external(engine, owner)) >= int(owner.proficiency_bonus or 2):
        placed.drop(engine, external(engine, owner)[0], "the anchor limit: the oldest ends")
    at = on.position if on is not None else cell
    return placed.place(engine, owner, source=source, tag=TAG, cells=[at], name="Shadow Anchor", material="shadow",
                        placed={"label": f"{owner.display_name}'s Shadow Anchor", **({"until": until} if until else {})},
                        anchor_id=on.entity_id if on is not None else None)


def _occupant(engine: Any, cell: Any) -> Any | None:
    from .rider_support import occupant

    return occupant(engine, cell)


def _pool(info: dict[str, Any]) -> str:
    from ..factory_compiler import RESOURCE_IDS

    return RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")


# ------------------------------------------------------------------------------------------------------------------ actions
def legacy_willing_action(action: Any) -> bool:
    """Recognize only the old serialized, unconditional one-minute willing mark."""
    from .ability_source import mechanic_of

    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    effects = typed.get("effects") or []
    return (mechanic_of(action) == SECOND and typed.get("option_label") == "Willing Creature"
            and getattr(action, "target_kind", None) == "HOSTILE_ENTITY"
            and len(effects) == 1 and effects[0].get("type") == "mark"
            and effects[0].get("mark") == MARK and effects[0].get("applies_to") == "target"
            and (effects[0].get("duration") or {}).get("kind") == "one_minute")


@hook("match_start")
def legacy_willing_catalog(engine: Any) -> None:
    """Supply consent for old bundles without replacing their catalog/history.

    The existing supplemental-action seam runs on fresh construction and reload.
    Only additional_actions exposes this definition, to its original owner.
    """
    from .willing_targets import willing_non_allies

    for action in list(engine.action_catalog.values()):
        if not legacy_willing_action(action):
            continue
        parameters = copy.deepcopy(action.parameters)
        mark = parameters["typed"]["effects"][0]
        mark["applies_to"] = "target"
        parameters["typed"]["effects"] = [{"type": "choose_willing", "target_only": True,
                                            "allow_hostile_target": True,
                                            "range_ft": action.range_ft, "effects": [mark]}]
        parameters["description"] = ("Second Silhouette: use an Action to place your Shadow Mark on yourself or a willing creature "
                                     "within 60 feet for 1 minute, at no cultivation point cost. Their shadow becomes a Shadow Anchor: "
                                     "a location your other Shadow abilities can use, such as for teleportation if you own that ability.")
        supplemental_id = action.source_definition_id + "#willing_saved"
        supplemental = action.model_copy(update={
            "source_definition_id": supplemental_id, "target_kind": "ALLY_OR_SELF", "parameters": parameters})
        for supplied in [supplemental, *(willing_non_allies({"actions": [supplemental]}) or [])]:
            engine.action_catalog.setdefault(supplied.source_definition_id, supplied)


@hook("additional_actions")
def legacy_willing_choices(engine: Any, actor: Any) -> list[str]:
    """Only an owned legacy option grants its supplemental willing action."""
    return [action_id + suffix for action_id in actor.action_ids
            if (action := engine.action_catalog.get(action_id)) is not None
            and action.owner_id == actor.entity_id and legacy_willing_action(action)
            for suffix in ("#willing_saved", "#willing_saved#willing_non_ally")
            if action_id + suffix in engine.action_catalog]


@hook("compile_actions")
def shadow_actions(info: dict[str, Any]) -> list[Any] | None:
    owned = set(info.get("owned_ids") or ())
    if SECOND not in owned:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    numbers, short, actor_id, pool = info.get("numbers") or {}, info["short"], info["actor_id"], _pool(info)

    def make(tag: str, name: str, effects: list[dict[str, Any]], economy: Any, target: str, reach: int | None, costs: list[Any] | None = None,
             **params: Any) -> Any:
        return ActionDefinition(source_definition_id=f"action:typed.{short}.shadow.{tag}", display_name=name, owner_id=actor_id, economy=economy,
                                resolution_kind="TYPED", target_kind=target, range_ft=reach, costs=tuple(costs or ()),
                                parameters={"typed": {"sphere": "tianxia.sphere.shadow",
                                                      "source": {"long_road": LONG_ROAD, "sovereign_step": STEP,
                                                                 "retract_lurk": LURK}.get(tag, SECOND),
                                                      "effects": effects, "numbers": numbers, "duration": {"kind": "instant"}, "riders": []},
                                            "expected_damage": 0, **params})

    out = [make("anchor", "Second Silhouette: Shadow Anchor", [{"type": "shadow_anchor"}], EconomyKind.ACTION, "CELL", 60,
                player_only=True, any_cell=True, shadow_anchor=True,
                description="Second Silhouette on a 5-foot space: create one Shadow Anchor there (1 hour; one per Proficiency Bonus, the oldest ends).")]
    if CLINGING in owned:
        out.append(make("cling_foe", "Second Silhouette: clinging anchor", [{"type": "shadow_cling"}], EconomyKind.ACTION, "HOSTILE_ENTITY", 60,
                        [(pool, 1)], player_only=True,
                        description="Clinging Silhouette (+1 CP): a Shadow Anchor that moves with the creature; it makes a Wisdom save "
                                    "(and repeats it at the end of each of its turns)."))
        out.append(make("cling_ally", "Second Silhouette: clinging anchor (willing)", [{"type": "shadow_cling"}], EconomyKind.ACTION, "ALLY_OR_SELF", 60,
                        [(pool, 1)], player_only=True, description="Clinging Silhouette (+1 CP): a Shadow Anchor that moves with a willing creature."))
    if LONG_ROAD in owned:
        out.append(make("long_road", "Long Road Between Lanterns", [{"type": "shadow_long_road", "self_movement": True, "recipient_policy": 1}], EconomyKind.ACTION, "CELL", 5280, [(pool, 5)],
                        player_only=True, any_cell=True, shadow_long_road=True,
                        description="Teleport from one of your Shadow Anchors (you within 5 feet of it) to within 5 feet of another, with up to "
                                    "your Proficiency Bonus of willing creatures within 5 feet of the start."))
    if LURK in owned:
        out.append(make("retract_lurk", "Retract Shadow Lurk", [{"type": "shadow_retract_lurk"}], EconomyKind.BONUS_ACTION, "SELF", None,
                        player_only=True, shadow_retract=True, description="Shadow Lurk: retract your lurk (Bonus Action)."))
    if SOVEREIGN in owned:
        out.append(make("sovereign_step", "Shadow Step (Shadow-Sovereign, 60 feet)", [{"type": "teleport", "applies_to": "self", "distance_ft": 60}],
                        EconomyKind.BONUS_ACTION, "SELF", 60, [(pool, 1)], requires_condition=SOVEREIGN_STATE, shadow_sovereign_step=True,
                        description="Shadow-Sovereign Incarnation: Shadow Step's range is 60 feet (once per turn without spending CP)."))
    return out


@hook("candidate_allowed")
def shadow_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if legacy_willing_action(action):
        return False  # The owner is offered the consent-bearing supplemental row.
    params = getattr(action, "parameters", None) or {}
    aim = getattr(candidate, "destination", None)
    if params.get("shadow_anchor"):
        if aim is None or (aim.x, aim.y) in (getattr(engine.grid, "blocked", None) or set()):
            return False
        return None if all((aim.x, aim.y) != (cell.x, cell.y) for cell in (_cell_of(engine, z) for z in external(engine, actor))) else False
    if params.get("shadow_long_road"):
        if aim is None:
            return False
        cells = anchors(engine, actor)
        start = [cell for cell in cells if engine.grid.distance_ft(cell, actor.position) <= 5]
        if not start or _occupant(engine, aim) is not None or (aim.x, aim.y) in (getattr(engine.grid, "blocked", None) or set()):
            return False
        return None if any(engine.grid.distance_ft(cell, aim) <= 5 and all((cell.x, cell.y) != (s.x, s.y) for s in start) for cell in cells) else False
    if params.get("shadow_retract"):
        from .. import summons

        return None if [c for c in summons.owned_by(engine, actor.entity_id) if c.active and (c.summon or {}).get("group") == "shadow_lurk"] else False
    return None


@effect("shadow_anchor")
def shadow_anchor(ctx: Any, eff: dict[str, Any]) -> None:
    cell = ctx.damage_cache.get("_checkpoint_aim")
    if cell is None:
        return
    other = _occupant(ctx.engine, cell)
    place_anchor(ctx.engine, ctx.actor, cell, ctx.source, on=other if other is not None and other.team_id == ctx.actor.team_id else None)
    note(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name} makes a Shadow Anchor at {cell.x},{cell.y}.")


@effect("shadow_cling")
def shadow_cling(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects

    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    if target.team_id != owner.team_id:
        before = len(engine.events)
        run_effects(ctx, [{"type": "save", "ability": "wis", "on_fail": [], "on_success": []}])
        rolled = next((e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED"), None)
        if rolled is None or (rolled.payload or {}).get("success"):
            note(engine, ctx.source, owner, f"Clinging Silhouette: {target.display_name} shrugs off the anchor.", (target.entity_id,))
            return
    zone = place_anchor(engine, owner, target.position, ctx.source, on=target)
    if target.team_id != owner.team_id:
        engine._apply_condition(target, CLING, ctx.source, owner.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": f"Clinging Silhouette ({owner.display_name}): repeats its Wisdom save at the end of each of its turns",
                                      "zone_id": zone.zone_id, "dc": int(ctx.numbers.get("save_dc") or 10)})
    note(engine, ctx.source, owner, f"Clinging Silhouette: a Shadow Anchor clings to {target.display_name}.", (target.entity_id,))


@hook("turn_end")
def cling_repeat_save(engine: Any, actor: Any) -> None:
    for iid, condition in list(actor.conditions.items()):
        if condition.condition_id != CLING or not actor.active:
            continue
        dc = int((condition.data or {}).get("dc") or 10)
        roll = engine._roll_save(actor, "WIS", dc, "system:shadow.clinging_silhouette")
        if roll is not None and roll.total >= dc:
            actor.conditions.pop(iid, None)
            engine._append_event("CONDITION_REMOVED", "system:shadow.clinging_silhouette", actor_id=condition.source_actor_id,
                                 target_ids=(actor.entity_id,), payload={"condition_id": CLING, "instance_id": iid})
            zone = engine.state.zones.get(str((condition.data or {}).get("zone_id") or ""))
            if zone is not None and zone.active:
                _placed().drop(engine, zone, "the creature shook the anchor off")


@hook("event")
def anchors_expire(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type not in ("TURN_STARTED", "TURN_ENDED", "ACTOR_DEFEATED", "ENTITY_DEFEATED"):
        return
    for zone in list(_placed().of(engine, TAG)):
        data = _placed().data(zone)
        rider = zone.trigger_profile.get("anchor_id")
        if (data.get("until") and _placed().deadline_due(engine, zone, str(data["until"]))) or \
                (rider and (engine.state.actors.get(rider) is None or not engine.state.actors[rider].active)):
            _placed().drop(engine, zone, "it ended")


@effect("shadow_sever_anchor")
def sever_anchor(ctx: Any, eff: dict[str, Any]) -> None:
    """Sever the Second Silhouette: the separated shadow stays in the target's space as a Shadow Anchor until the end of your next turn."""
    from .effect_durations import token

    target = ctx.target
    if target is None:
        return
    place_anchor(ctx.engine, ctx.actor, target.position, ctx.source, until=token("end", ctx.actor.entity_id, int(ctx.actor.turns_started) + 1))


@effect("shadow_long_road")
def long_road(ctx: Any, eff: dict[str, Any]) -> None:
    from .rider_support import teleport

    engine, actor = ctx.engine, ctx.actor
    aim = ctx.damage_cache.get("_checkpoint_aim")
    cells = anchors(engine, actor)
    start = next((cell for cell in cells if engine.grid.distance_ft(cell, actor.position) <= 5), None)
    end = next((cell for cell in cells if aim is not None and engine.grid.distance_ft(cell, aim) <= 5
                and (start is None or (cell.x, cell.y) != (start.x, start.y))), None)
    if aim is None or start is None or end is None:
        ctx.rider("Long Road Between Lanterns: no anchor to leave from or arrive at.")
        return
    riders = sorted([other for other in engine.state.actors.values() if other.active and other is not actor
                     and engine.grid.distance_ft(other.position, start) <= 5], key=lambda other: (engine.grid.distance_ft(other.position, actor.position), other.entity_id))
    riders = companions(ctx, riders, "shadow_long_road", "Long Road Between Lanterns", int(actor.proficiency_bonus or 2), recipient_policy=eff.get("recipient_policy", 0))
    if not travel(ctx, actor, aim, eff.get("recipient_policy", 0)):
        return
    travelled = 0
    for other in riders:
        free = [cell for cell in _placed().area(engine, end, "sphere", 5)
                if engine.grid.placement_legal(cell, footprint=engine._footprint(other),
                                               occupied_cells=engine._occupied_cells_except(other.entity_id))]
        spot = arrival(ctx, other, free, 'shadow_road_arrival', 'Long Road Between Lanterns', eff.get('recipient_policy', 0))
        if spot is not None:
            travelled += int(travel(ctx, other, spot, eff.get("recipient_policy", 0)))
    note(engine, ctx.source, actor, f"Long Road Between Lanterns: {actor.display_name}" + (f" and {travelled} companion(s)" if travelled else "")
         + f" step through the shadows to {aim.x},{aim.y}.")


# ------------------------------------------------------------------------------------------------------------------ Court
def _in_court_of_ally(engine: Any, creature: Any) -> Any | None:
    for owner in engine.state.actors.values():
        if owner.active and owner.team_id == creature.team_id:
            court = _court(engine, owner)
            if court is not None and any((c.x, c.y) == (creature.position.x, creature.position.y) for c in court.affected_cells):
                return owner
    return None


@hook("ac")
def court_ac(engine: Any, target: Any) -> int | None:
    return 1 if _in_court_of_ally(engine, target) is not None else None


@hook("after_miss")
def court_step(ctx: Any, target: Any) -> None:
    """"May move 5 feet without provoking opportunity attacks after an enemy misses them" (you and your allies in the Court)."""
    engine = ctx.engine
    if target is None or not target.active or ctx.actor.team_id == target.team_id or _in_court_of_ally(engine, target) is None:
        return
    from .needle import CHOICE, ask, checkpoint_id, free_cells, position_of, step_to, cell_id as _cell_id, cell_options as _cell_options

    cells = dict(free_cells(engine, target, 5))
    if len(cells) <= 1:
        return
    options, labels = _cell_options(engine, target, cells)
    away = max(cells, key=lambda cell: (engine.grid.distance_ft(ctx.actor.position, cell), -cell.y, -cell.x))
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "SHADOW_COURT_STEP", target.entity_id, ctx.actor.entity_id), target,
                 CHOICE + "shadow_court_step", options, labels=labels, preferred=[_cell_id(away)], allow_decline=True,
                 prompt=f"Court of the Second Silhouette: {ctx.action.display_name} by {ctx.actor.display_name} misses {target.display_name}; step 5 feet?",
                 target_id=target.entity_id)
    if picked and picked[0] != _cell_id(target.position):
        step_to(engine, target, position_of(picked[0]), f"passive:{COURT}")


@hook("masked_conditions")
def court_invisible(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    """"Enemies: Cannot benefit from ordinary Invisible against you": an enemy inside your Court gets nothing from Invisible in an
    attack between it and you."""
    out: dict[str, set[str]] = {}
    for owner, enemy in ((attacker, target), (target, attacker)):
        court = _court(engine, owner) if owner is not None else None
        if court is None or enemy is None or enemy.team_id == owner.team_id:
            continue
        if any((c.x, c.y) == (enemy.position.x, enemy.position.y) for c in court.affected_cells):
            hidden = {iid for iid, c in enemy.conditions.items() if c.condition_id.endswith(".invisible")}
            if hidden:
                out.setdefault(enemy.entity_id, set()).update(hidden)
    return out or None


# ------------------------------------------------------------------------------------------------------------------ Shadow Lurk
@hook("event")
def lurk_destroyed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"If the lurk is reduced to 0 HP ... it vanishes and the target becomes Stunned until the end of its next turn." """
    if event_type not in ("ACTOR_DEFEATED", "ENTITY_DEFEATED"):
        return
    lurk = engine.state.actors.get(str(kwargs.get("actor_id") or next(iter(kwargs.get("target_ids") or ()), "")))
    record = getattr(lurk, "summon", None) or {}
    if record.get("group") != "shadow_lurk":
        return
    owner = engine.state.actors.get(str(record.get("owner") or ""))
    if owner is None or not owner.active:
        return
    from .effect_durations import token

    engine._apply_condition(owner, "condition:typed.stunned", f"passive:{LURK}", owner.entity_id,
                            expires_on=token("end", owner.entity_id, int(owner.turns_started) + (0 if engine.state.current_actor_id == owner.entity_id else 1)),
                            data={"label": "Stunned: its Shadow Lurk was destroyed"})
    note(engine, f"passive:{LURK}", owner, f"{owner.display_name}'s Shadow Lurk is destroyed: {owner.display_name} is Stunned until the end of its next turn.")


@effect("shadow_retract_lurk")
def retract_lurk(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import summons

    for creature in summons.owned_by(ctx.engine, ctx.actor.entity_id):
        if creature.active and (creature.summon or {}).get("group") == "shadow_lurk":
            summons._leave(ctx.engine, creature, "dismissed", "retracted")


# ------------------------------------------------------------------------------------------------ Shadowless Reversal, Shadow Exchange
def _reach_of(engine: Any, attacker: Any, spec: dict[str, Any]) -> int:
    ranged = spec.get("range_ft")
    if ranged is not None:
        return int(ranged)
    pending = getattr(engine, "_typed_pending_attack", None) or {}
    return int(pending.get("reach") or 5)


def _escape(engine: Any, creature: Any, attacker: Any, reach: int, limit: int, *, player_choice: bool = False) -> Any | None:
    """The unoccupied square within ``limit`` feet of ``creature`` that is farthest from ``attacker`` and outside ``reach``."""
    from .needle import free_cells
    from .teleport_steps import destinations, player_controls
    available = (destinations(engine, creature, limit) if player_choice and player_controls(engine, creature)
                 else free_cells(engine, creature, 10_000))
    cells = [cell for cell in available
             if engine.grid.distance_ft(cell, creature.position) <= limit and engine.grid.distance_ft(cell, attacker.position) > reach]
    return max(cells, key=lambda cell: (engine.grid.distance_ft(cell, attacker.position), -cell.y, -cell.x)) if cells else None


def _pay(engine: Any, reactor: Any, amount: int, source: str) -> bool:
    from .rider_support import cp_pool as _cp_pool

    pool = _cp_pool(reactor)
    if pool is None or reactor.resources.get(pool, 0) < amount:
        return False
    engine._spend_resource(reactor, pool, amount, source)
    return True


@hook("hit_response")
def slip_the_hit(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: Any, effective_ac: int) -> Any:
    from .. import typed_reactions
    from ..typed_executor import _teleport, Context

    reach = _reach_of(engine, attacker, spec)
    choices = []
    if _kind(engine, target, "shadowless_reversal") and typed_reactions._can_react(engine, target) \
            and not target.turn_flags.get(f"shadow_round_reversal:{engine.state.round_number}"):
        choices.append((target, target, "shadowless_reversal", 5, max(5, engine._effective_speed(target) // 2)))
    for reactor in engine.state.actors.values():
        if reactor.active and reactor.team_id == target.team_id and _kind(engine, reactor, "shadow_exchange") and typed_reactions._can_react(engine, reactor) \
                and engine.grid.distance_ft(reactor.position, target.position) <= 60:
            choices.append((reactor, target, "shadow_exchange", 4, 20))
    for reactor, moved, kind, cost, limit in choices:
        spot = _escape(engine, moved, attacker, reach, limit, player_choice=moved is reactor)
        if spot is None:
            continue
        from .rider_support import cp_pool as _cp_pool

        pool = _cp_pool(reactor)
        if pool is None or reactor.resources.get(pool, 0) < cost:
            continue
        from .needle import ask, checkpoint_id

        name = "Shadowless Reversal" if kind == "shadowless_reversal" else "Shadow Exchange"
        action = engine.action_catalog.get(str(spec.get("source_definition_id") or ""))
        from .rider_choices import trigger_name
        triggering = action.display_name if action is not None else trigger_name(engine)
        picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "SHADOW_SLIP", reactor.entity_id, attacker.entity_id), reactor,
                     "choice:needle.shadow_slip", ["use", "pass"], labels={"use": f"{name}: slip out of the attack", "pass": "Let it hit"},
                     preferred=["use"], prompt=f"{name}: {triggering} by {attacker.display_name} hits {moved.display_name}; slip away?", target_id=moved.entity_id,
                     name=name, feature_id=REVERSAL if kind == "shadowless_reversal" else EXCHANGE,
                     prompt_context={"cost": f"Reaction + {cost} {pool.rsplit('.', 1)[-1].title()}", "paying_pool": pool})
        if picked[:1] != ["use"]:
            continue
        source = f"reaction:{REVERSAL if kind == 'shadowless_reversal' else EXCHANGE}"
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, reactor, source, independent=True):
            _pay(engine, reactor, cost, source)
            reactor.reaction_available = False
            from .teleport_steps import player_controls
            player_escape = moved is reactor and player_controls(engine, moved)
            if kind == "shadowless_reversal":
                target.turn_flags[f"shadow_round_reversal:{engine.state.round_number}"] = True
                # Preserve historical AI event ordering; a player's cancelled hop
                # has no abandoned silhouette because they never leave the square.
                if not player_escape:
                    _leave_silhouette(engine, target, source)
            action = next((engine.action_catalog[a] for a in reactor.action_ids if a in engine.action_catalog), None)
            ctx = Context(engine, moved, action, getattr(engine, "_active_intent", None), {"effects": [], "numbers": {}}, [moved], moved)
            if moved is reactor:
                from .teleport_steps import ask_destination, player_controls
                if player_controls(engine, moved):
                    # This is a self escape, not the separate ally-exchange rule.
                    # Keep the AI's historical escape while a player chooses among
                    # visible, open landings outside the triggering attack's reach.
                    from ..gate2_runtime_models import ActionDefinition
                    ctx.typed = {"source": REVERSAL if kind == "shadowless_reversal" else EXCHANGE,
                        "effects": [{"type": "teleport", "applies_to": "self", "distance_ft": limit}],
                        "numbers": {}, "range_ft": limit}
                    ctx.action = ActionDefinition(source_definition_id=source, display_name=name,
                        owner_id=reactor.entity_id, economy="REACTION", resolution_kind="TYPED",
                        target_kind="SELF", range_ft=limit, costs=((pool, cost),),
                        parameters={"typed": ctx.typed})
                    answer = ask_destination(ctx, limit, name=f"{name} after {attacker.display_name}'s {triggering}",
                        destination_filter=lambda cell: engine.grid.distance_ft(cell, attacker.position) > reach)
                    if answer.square is None:
                        continue
                    spot = answer.square
            start = moved.position
            _teleport(ctx, spot)
            if moved.position == start:
                continue
            if player_escape and kind == "shadowless_reversal":
                _leave_silhouette(engine, target, source, position=start)
            note(engine, source, reactor, f"{name}: {moved.display_name} slips into the shadows at {spot.x},{spot.y}; the attack misses.", (attacker.entity_id,))
            from ..attack_outcomes import unconditional_miss

            return unconditional_miss()
    return None


def _leave_silhouette(engine: Any, owner: Any, source: str, *, position: Any = None) -> None:
    """The abandoned silhouette: until the start of your next turn, the first creature entering its space or starting its turn there saves."""
    from .effect_durations import token

    from .needle import save_dc

    numbers = {"save_dc": save_dc(engine, owner)}
    trigger = {"on": ["enter", "start"], "who": "any", "once": True,
               "effects": [{"type": "shadow_silhouette_snare"}]}
    anchor = next((a for a in owner.action_ids if a in engine.action_catalog), source)
    _placed().place(engine, owner, source=anchor, tag=SILHOUETTE, cells=[position if position is not None else owner.position], name="Abandoned silhouette", material="shadow",
                    placed={"label": "Shadowless Reversal: abandoned silhouette", "until": token("start", owner.entity_id, int(owner.turns_started) + 1),
                            "dc": numbers["save_dc"]}, triggers=[trigger], numbers=numbers)


@effect("shadow_silhouette_snare")
def silhouette_snare(ctx: Any, eff: dict[str, Any]) -> None:
    """The first creature (other than its owner) entering the silhouette's space or starting its turn there: Dexterity save -- Restrained
    until the start of its next turn, or Speed -10 feet until the start of its next turn; then the silhouette is spent."""
    from ..typed_executor import run_effects

    engine = ctx.engine
    zone = next((z for z in _placed().of(engine, SILHOUETTE, owner_id=ctx.actor.entity_id)
                 if ctx.target is not None and any((c.x, c.y) == (ctx.target.position.x, ctx.target.position.y) for c in z.affected_cells)), None)
    if zone is None or ctx.target is None or ctx.target.entity_id == ctx.actor.entity_id:
        return
    _placed().drop(engine, zone, "sprung")
    run_effects(ctx, [{"type": "save", "ability": "dex",
                       "on_fail": [{"type": "condition", "applies_to": "target", "condition": "restrained", "duration": "until_start_of_next_turn"}],
                       "on_success": [{"type": "speed", "applies_to": "target", "flat": -10, "duration": "until_start_of_next_turn"}]}])


@hook("event")
def silhouettes_expire(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "TURN_STARTED":
        return
    for zone in list(_placed().of(engine, SILHOUETTE)):
        until = _placed().data(zone).get("until")
        if until and _placed().deadline_due(engine, zone, str(until)):
            _placed().drop(engine, zone, "the silhouette fades")


# ------------------------------------------------------------------------------------------------------------------ Silhouette Veil
@hook("attack_mode")
def veil_first_opportunity(ctx: Any, target: Any) -> str | None:
    if target is None or not (ctx.typed or {}).get("opportunity_of") and "opportunity" not in str(ctx.source):
        return None
    if not any(VEIL in str(c.source_definition_id) for c in target.conditions.values()) and \
            not any(VEIL in str(m.source_definition_id) for m in target.modifiers.values()):
        return None
    key = f"shadow_round_veil:{ctx.engine.state.round_number}"
    if target.turn_flags.get(key):
        return None
    target.turn_flags[key] = True
    return "DISADVANTAGE"


# ------------------------------------------------------------------------------------------------------------------ Sovereign
@effect("shadow_sovereign")
def sovereign_state(ctx: Any, eff: dict[str, Any]) -> None:
    from .needle import pb_rounds, timed_condition

    timed_condition(ctx.engine, ctx.actor, SOVEREIGN_STATE, ctx.source, ctx.actor.entity_id, pb_rounds(ctx.engine, ctx.actor, 10),
                    {"label": "Shadow-Sovereign Incarnation: Shadow Step 60 feet (once a turn without CP); Shadow Fang marks on a miss"})


def _sovereign(actor: Any) -> bool:
    return any(c.condition_id == SOVEREIGN_STATE for c in actor.conditions.values())


@hook("technique_used")
def sovereign_free_step(ctx: Any) -> None:
    actor = ctx.actor
    if not _sovereign(actor) or actor.turn_flags.get("shadow_free_step") or (STEP not in str(ctx.source) and "sovereign_step" not in str(ctx.source)):
        return
    actor.turn_flags["shadow_free_step"] = True
    from .rider_support import refund

    refund(ctx.engine, actor, "Shadow-Sovereign Incarnation: Shadow Step without spending CP", "passive:shadow")


@effect("shadow_fang_miss_mark")
def fang_miss_mark(ctx: Any, eff: dict[str, Any]) -> None:
    """Shadow-Sovereign Incarnation: "apply Shadow Mark with Shadow Fang even when the attack misses"."""
    from ..typed_executor import run_effects

    if ctx.target is not None and _sovereign(ctx.actor):
        run_effects(ctx, [{"type": "mark", "mark": MARK, "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"}}])


# ------------------------------------------------------------------------------------------------ Two Shadows Crossing, Lingering Trace
def mark_applied_in_use(ctx: Any, target: Any) -> bool:
    """Grasping/Lingering augments require this activation's actual new mark.

    A mark retained from an earlier hit must not turn a later miss into a new
    Imprint. Read committed native condition receipts, including refreshes.
    """
    accepted = next((e.sequence for e in reversed(ctx.engine.events)
                     if e.event_type == "INTENT_ACCEPTED"), 0)
    return any(e.sequence > accepted and e.event_type == "CONDITION_APPLIED"
               and e.source_definition_id == ctx.source and target.entity_id in e.target_ids
               and e.payload.get("condition_id") == _mark_id(ctx.actor)
               for e in ctx.engine.events)


@effect("shadow_grasping")
def grasping(ctx: Any, eff: dict[str, Any]) -> None:
    """Newly declared Imprint saves only after this use actually places its mark."""
    from ..typed_executor import run_effects
    if ctx.target is not None and mark_applied_in_use(ctx, ctx.target):
        run_effects(ctx, eff.get("effects") or [])


@effect("shadow_fang_mark")
def fang_hit_mark(ctx: Any, eff: dict[str, Any]) -> None:
    """The hit's optional mark belongs to the attacker, costs no extra CP."""
    from .needle import CHOICE, ask, checkpoint_id
    from ..typed_executor import run_effects
    target = ctx.target
    if target is None or not target.active or not ctx.actor.active:
        return
    chosen = ask(ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, 'shadow_fang_mark', target.entity_id), ctx.actor,
        CHOICE + 'shadow_fang_mark', ['mark'], allow_decline=True,
        labels={'mark': 'Apply your Shadow Mark until your next turn starts'},
        preferred=['mark'], target_id=target.entity_id, name='Shadow Fang',
        prompt=f'Shadow Fang: {ctx.action.display_name} hits {target.display_name}. '
               'Apply your Shadow Mark until your next turn starts? No extra cost. '
               'Its shadow becomes a Shadow Anchor for your other Shadow abilities.')
    if chosen:
        run_effects(ctx, [{'type': 'mark', 'mark': MARK, 'applies_to': 'target',
                          'duration': {'kind': 'until_start_of_your_next_turn'}}])


def companions(ctx: Any, candidates: list[Any], key: str, name: str, maximum: int, *, recipient_policy: int = 0) -> list[Any]:
    """Shadow travel asks the caster whom to invite, then each invitee for willingness."""
    from .rider_choices import pick
    automatic = True
    if recipient_policy == 1:
        from . import ai_controlled
        from ..target_knowledge import located
        # A controller-free interpreter's fallback is also an automatic pick.
        # A recorded manual owner can invite non-allies and ask their consent.
        automatic = ai_controlled(ctx.engine, ctx.actor) or not getattr(ctx.engine, 'typed_control_modes', None)
        candidates = [c for c in candidates if located(ctx.engine, ctx.actor, c)
                      and (not automatic or c.team_id == ctx.actor.team_id)]
    if not candidates:
        return []
    ids = pick(ctx.engine, ctx.actor, key, name, [c.entity_id for c in candidates],
               labels={c.entity_id: f"Invite {c.display_name}" for c in candidates},
               preferred=[c.entity_id for c in candidates if c.team_id == ctx.actor.team_id][:maximum],
               subject=ctx.actor, trigger=ctx.action.display_name + " companion selection", maximum=maximum, intent=ctx.intent,
               automatic=automatic)
    return [c for c in candidates if c.entity_id in ids and
            pick(ctx.engine, c, key + "_consent", name, ["travel"], labels={"travel": f"Travel with {ctx.actor.display_name}"},
                 subject=c, trigger=f"{ctx.action.display_name}: {ctx.actor.display_name} invites {c.display_name}",
                 intent=ctx.intent, automatic=c.team_id == ctx.actor.team_id)]


@effect("shadow_carry")
def carry(ctx: Any, eff: dict[str, Any]) -> None:
    """Two Shadows Crossing: one willing creature of your size or smaller that began adjacent to you arrives in an unoccupied space adjacent
    to your destination (the nearest ally that was adjacent)."""
    from .rider_support import teleport

    engine, actor = ctx.engine, ctx.actor
    accepted = next((e.sequence for e in reversed(engine.events) if e.event_type == "INTENT_ACCEPTED"), 0)
    moved = next((e for e in reversed(engine.events) if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == actor.entity_id
                  and e.sequence > accepted and e.source_definition_id == ctx.source and (e.payload or {}).get("teleport")), None)
    path = (moved.payload or {}).get("path") if moved is not None else None
    if not path:
        return
    from ..gate2_runtime_models import Position

    start = Position(**path[0])
    size = engine._footprint(actor).width_cells
    allies = sorted([other for other in engine.state.actors.values() if other.active and other is not actor
                     and engine.grid.distance_ft(other.position, start) <= 5 and engine._footprint(other).width_cells <= size],
                    key=lambda other: (engine.grid.distance_ft(other.position, start), other.entity_id))
    if not allies:
        return
    allies = companions(ctx, allies, "shadow_crossing", "Two Shadows Crossing", 1, recipient_policy=eff.get("recipient_policy", 0))
    if not allies:
        return
    free = [cell for cell in _placed().area(engine, actor.position, "sphere", 5) if cell != actor.position
            and engine.grid.placement_legal(cell, footprint=engine._footprint(allies[0]),
                                           occupied_cells=engine._occupied_cells_except(allies[0].entity_id))]
    spot = arrival(ctx, allies[0], free, 'shadow_crossing_arrival', 'Two Shadows Crossing', eff.get('recipient_policy', 0))
    if spot is not None and travel(ctx, allies[0], spot, eff.get("recipient_policy", 0)):
        note(engine, ctx.source, actor, f"Two Shadows Crossing: {allies[0].display_name} crosses with {actor.display_name}.")


@effect("shadow_lingering_trace")
def lingering_trace(ctx: Any, eff: dict[str, Any]) -> None:
    """Lingering Trace: the Shadow Mark this use applied lasts (the fight's whole length); past your Proficiency Bonus of lasting marks
    the oldest ends."""
    engine, owner = ctx.engine, ctx.actor
    mark = _mark_id(owner)
    target = ctx.target
    if target is None:
        return
    if eff.get('choose_older') and not mark_applied_in_use(ctx, target):
        return
    found = next(((iid, c) for iid, c in target.conditions.items() if c.condition_id == mark), None)
    if found is None:
        return
    iid, condition = found
    target.conditions.pop(iid, None)
    engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=owner.entity_id, target_ids=(target.entity_id,), payload={"condition_id": mark, "instance_id": iid})
    lasting = sorted(((c.applied_sequence, creature, i) for creature in engine.state.actors.values() for i, c in creature.conditions.items()
                      if c.condition_id == mark and (c.data or {}).get("lingering")), key=lambda row: row[0])
    excess = max(0, len(lasting) - int(owner.proficiency_bonus or 2) + 1)
    if eff.get('choose_older') and excess:
        from .needle import CHOICE, ask, checkpoint_id
        ids = [creature.entity_id for _seq, creature, _old in lasting]
        picked = ask(engine, ctx.intent, checkpoint_id(engine, 'shadow_lingering_limit', target.entity_id),
            owner, CHOICE + 'shadow_lingering_limit', ids, minimum=excess, maximum=excess,
            labels={creature.entity_id: f'End the older mark on {creature.display_name}'
                    for _seq, creature, _old in lasting}, preferred=ids[:excess],
            target_id=target.entity_id, name='Lingering Trace',
            prompt=f'Lingering Trace: {ctx.action.display_name} marks {target.display_name}. '
                   f'You can track {int(owner.proficiency_bonus or 2)} creatures. '
                   f'Choose {excess} older mark to end. The new mark lasts 8 hours; no extra cost.')
        ending = [row for row in lasting if row[1].entity_id in picked]
    else:
        ending = lasting[:excess]
    for _seq, creature, old in ending:
        gone = creature.conditions.pop(old, None)
        if gone is not None:
            engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=owner.entity_id, target_ids=(creature.entity_id,),
                                 payload={"condition_id": mark, "instance_id": old})
    from ..typed_executor import clock_expiry
    engine._apply_condition(target, mark, ctx.source, owner.entity_id,
        expires_on=clock_expiry(engine, 'hours', 8) if eff.get('choose_older') else "UNTIL_REMOVED",
        data={**(condition.data or {}), "lingering": True})


@hook("compile_block")
def shadow_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    return [{**row, "block": "shadow", "kind": spec.get("kind")}] if block == "shadow" else None


# ------------------------------------------------------------------------------------------------------------ Seize the Second Body
@effect("shadow_drag")
def shadow_drag(ctx: Any, eff: dict[str, Any]) -> None:
    """Seize the Second Body: "Move its shadow up to 20 feet and force its body to follow" -- the user moves the creature up to 20 feet to
    an open square it chooses (a forced move: no Opportunity Attacks). By default, the square nearest the user."""
    from .needle import CHOICE, ask, checkpoint_id, free_cells, position_of, step_to, cell_id as _cell_id

    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    reach = int(eff.get("distance_ft") or 20)
    cells = [cell for cell in free_cells(engine, target, reach) if cell != target.position]
    if not cells:
        return
    ordered = sorted(cells, key=lambda cell: (engine.grid.distance_ft(cell, owner.position), cell.y, cell.x))[:16]
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "SEIZE", owner.entity_id, target.entity_id), owner, CHOICE + "shadow_drag",
                 [_cell_id(cell) for cell in ordered], labels={_cell_id(cell): f"Drag it to {cell.x},{cell.y}" for cell in ordered},
                 prompt=f"Seize the Second Body: {ctx.action.display_name} affecting {target.display_name}; where does it go?", target_id=target.entity_id)
    if picked:
        step_to(engine, target, position_of(picked[0]), ctx.source)
        note(engine, ctx.source, owner, f"Seize the Second Body: {target.display_name} is dragged after its shadow.", (target.entity_id,))


# ------------------------------------------------------------------------------------------------------------ World of Living Shadows
WORLD = "TAL_SHADOW_WORLD_OF_LIVING_SHADOWS"


def _world_zone_of(engine: Any, creature: Any, *, hostile: bool) -> Any | None:
    from .. import zones

    for zone in zones.typed_zones(engine):
        if not zone.active or WORLD not in str(zone.source_definition_id):
            continue
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or (owner.team_id != creature.team_id) != hostile:
            continue
        if any((c.x, c.y) == (creature.position.x, creature.position.y) for c in zone.affected_cells):
            return zone
    return None


@hook("ac")
def world_ac(engine: Any, target: Any) -> int | None:
    """World of Living Shadows: "Allies: Gain +1 AC" inside the area."""
    return 1 if _world_zone_of(engine, target, hostile=False) is not None else None


@hook("masked_conditions")
def world_invisible(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    """World of Living Shadows: "Enemies: Cannot benefit from ordinary Invisible" inside the area."""
    out: dict[str, set[str]] = {}
    for creature in (attacker, target):
        if creature is not None and _world_zone_of(engine, creature, hostile=True) is not None:
            hidden = {iid for iid, c in creature.conditions.items() if c.condition_id.endswith(".invisible")}
            if hidden:
                out.setdefault(creature.entity_id, set()).update(hidden)
    return out or None


@hook("stealth_search_mode")
def world_perception(engine: Any, searcher: Any, hidden_foe: Any) -> str | None:
    """World of Living Shadows: "Enemies ... Have Disadvantage on sight-based Wisdom (Perception) checks" inside the area."""
    return "DISADVANTAGE" if _world_zone_of(engine, searcher, hostile=True) is not None else None


# Second pass: new sealed policy rows own all three Ambush checkpoints. Older
# generic reactions keep their original dispatch and recorded behavior.
AMBUSH = 'TAL_SHADOW_AMBUSH_FROM_BELOW'


def _ambush_policy(row: dict[str, Any]) -> bool:
    return row.get('feature_id') == AMBUSH and any(
        e.get('type') == 'shadow_ambush_policy' and e.get('version') == 1
        for e in row.get('effects') or [] if isinstance(e, dict))


@effect('shadow_ambush_policy')
def ambush_policy(ctx: Any, row: dict[str, Any]) -> None:
    """Sealed attribution only; the reaction save owns its printed outcome."""


@hook('row_allowed')
def ambush_native_dispatch(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    if _ambush_policy(row) and not row.get('shadow_ambush_dispatch'):
        return False
    return None


def _ambush(engine: Any, subject: Any, trigger: str) -> None:
    from .. import typed_reactions as reactions, typed_executor as te, target_knowledge, targeting
    from ..gate2_runtime_models import ActionDefinition
    from .needle import ask, checkpoint_id
    from . import run, ai_controlled
    from ..decision_text import costs_text
    from ..typed_amounts import effect_dice
    current = engine.state.actors.get(engine.state.current_actor_id)
    token = f'{engine.state.round_number}:{engine.state.current_slot_index}:{getattr(current, "entity_id", "")}:{getattr(current, "turns_started", 0)}'
    if subject is None or not subject.active or engine.state.terminal_result:
        return
    for owner in list(engine.state.actors.values()):
        # Printed "a creature" permits an explicit manual response to an ally.
        # An automatic harmful response admits only enemies.
        automatic = ai_controlled(engine, owner) or not getattr(engine, "typed_control_modes", None)
        if not owner.active or (automatic and owner.team_id == subject.team_id):
            continue
        for saved in (getattr(engine, 'typed_reaction_rows', {}) or {}).get(owner.entity_id, []):
            if not _ambush_policy(saved):
                continue
            row = {**saved, 'shadow_ambush_dispatch': True}
            key = '_round_shadow_ambush:' + subject.entity_id
            if owner.turn_flags.get(key) == token or not te.bears_mark(subject, owner.entity_id, MARK):
                continue
            if (not target_knowledge.located(engine, owner, subject)
                    or engine._distance_actor_to_actor(owner, subject) > 60
                    or not targeting.line_of_effect(engine, owner, target=subject)
                    or not reactions.can_use_reaction(engine, owner, subject, row)):
                continue
            costs = [(str(c['resource_id']), int(c['amount'])) for c in row.get('costs') or []]
            if any(owner.resources.get(pool, 0) < amount or any(answer is False for answer in
                   run('cost_available', engine, owner, pool, amount, {}))
                   for pool, amount in costs):
                continue
            price = costs_text(costs)
            numbers = row.get('numbers') or {}
            damage = next(e for save in saved['effects'] if save.get('type') == 'save'
                          for e in save.get('on_fail') or [] if e.get('type') == 'damage')
            spec = effect_dice(damage, numbers) or {}
            dice = f"{int(spec.get('count') or 0)}d{int(spec.get('sides') or 0)}"
            chosen = ask(engine, getattr(engine, '_active_intent', None),
                checkpoint_id(engine, 'shadow_ambush', owner.entity_id, subject.entity_id), owner,
                'choice:needle.shadow_ambush', ['use'], allow_decline=True, preferred=['use'],
                automatic=automatic, default='first' if automatic else 'decline',
                name='Ambush From Below', feature_id=AMBUSH, target_id=subject.entity_id,
                labels={'use': f'{subject.display_name}: Dexterity save; {dice} damage and no Reactions on failure, half damage on success'},
                prompt=f'Ambush From Below: {subject.display_name} {trigger} within 60 feet while bearing your Shadow Mark. '
                       f'Use your Reaction and {price}? Once per creature per turn. Reaction loss lasts until its next turn starts.',
                prompt_context={'cost': 'Reaction + ' + price, 'paying_pool': costs[0][0] if costs else ''})
            if not chosen:
                continue
            owner.turn_flags[key] = token
            for pool, amount in costs:
                engine._spend_resource(owner, pool, amount, AMBUSH)
            reactions.open_reaction(engine, row, owner, (subject.entity_id,), 'SHADOW_AMBUSH')
            reactions.spend_reaction(engine, owner, row)
            typed = {'source': AMBUSH, 'effects': saved['effects'], 'numbers': numbers,
                     'duration': {'kind':'instant'}, 'riders': [], 'reaction_attack': True}
            action = ActionDefinition(source_definition_id='reaction:typed.' + AMBUSH,
                display_name='Ambush From Below', owner_id=owner.entity_id, economy='REACTION',
                resolution_kind='TYPED', target_kind='HOSTILE_ENTITY', range_ft=60,
                costs=tuple(costs), parameters={'typed':typed})
            ctx = te.Context(engine, owner, action, getattr(engine, '_active_intent', None), typed, [subject], subject)
            te.run_effects(ctx, saved['effects'])
            engine._append_event('REACTION_RESOLVED', AMBUSH, actor_id=owner.entity_id,
                target_ids=(subject.entity_id,), payload={'checkpoint':'SHADOW_AMBUSH', 'trigger':trigger, 'turn':token})


@hook('event', nested=True)
def ambush_moved(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == 'MOVEMENT_COMMITTED':
        _ambush(engine, engine.state.actors.get(kwargs.get('actor_id')), 'moves')


@hook('attack_completed')
def ambush_attacked(engine: Any, notice: Any, intent: Any) -> None:
    _ambush(engine, engine.state.actors.get(notice.attacker_id), 'attacks')


@hook('turn_end')
def ambush_ended(engine: Any, actor: Any) -> None:
    _ambush(engine, actor, 'ends its turn')


@hook('darkness_lifted')
def mantle_sight(engine: Any, zone: Any, viewer: Any, seen: Any) -> bool | None:
    from .darkness_scope import scope
    from ..typed_executor import condition_rules
    if (zone.trigger_profile.get('visual') or {}).get('darkness') and scope(engine, zone) == 'ordinary' \
            and any(rule.get('shadow_mantle_sight') == 1 for rule in condition_rules(viewer)):
        return True
    return None


@hook('attack_mode')
def mantle_opportunity(ctx: Any, target: Any) -> str | None:
    from ..typed_executor import condition_rules
    if target is not None and (ctx.typed.get('opportunity_of') or 'opportunity' in str(ctx.source)) \
            and any(rule.get('shadow_mantle_opportunity') == 1 for rule in condition_rules(target)):
        return 'DISADVANTAGE'
    return None


def arrival(ctx: Any, creature: Any, cells: list[Any], key: str, name: str, policy: int) -> Any | None:
    """The caster chooses a legal companion landing; AI uses only offered cells."""
    if policy != 1:
        return min(cells, key=lambda cell: (ctx.engine.grid.distance_ft(cell, ctx.actor.position), cell.y, cell.x)) if cells else None
    from .teleport_steps import destination_allowed
    from .needle import cell_id, position_of
    from .rider_choices import pick
    from . import ai_controlled
    cells = [cell for cell in cells if destination_allowed(ctx.engine, creature, cell, 5280, viewer=ctx.actor)]
    if not cells:
        return None
    preferred = min(cells, key=lambda cell: (ctx.engine.grid.distance_ft(cell, ctx.actor.position), cell.y, cell.x))
    chosen = pick(ctx.engine, ctx.actor, key, name, [cell_id(cell) for cell in cells], subject=creature,
        labels={cell_id(cell): f'{creature.display_name} arrives at {cell.x},{cell.y}' for cell in cells},
        preferred=[cell_id(preferred)], optional=True, intent=ctx.intent,
        automatic=ai_controlled(ctx.engine, ctx.actor) or not getattr(ctx.engine, "typed_control_modes", None),
        prompt=f'{name}: choose the unoccupied arrival space for {creature.display_name}. No additional cost.')
    return position_of(chosen[0]) if chosen else None


def travel(ctx: Any, mover: Any, destination: Any, policy: int) -> bool:
    """A selected Shadow landing is an answered native hop, not a second picker."""
    if policy != 1:
        from .rider_support import teleport
        return teleport(ctx, mover, destination)
    from dataclasses import replace
    from .teleport_steps import Destination, hop_key
    from ..typed_executor import block_movement
    moved = replace(ctx, actor=mover, destination=destination)
    # CELL intent / arrival() already chose this square. Match the native row's
    # range-only hop identity, preserving its seals, gates and arrival effects.
    moved.hop_destination[hop_key(moved, 0)] = Destination(destination, True)
    start = mover.position
    block_movement(moved, {"type": "teleport", "applies_to": "self"})
    return mover.position != start

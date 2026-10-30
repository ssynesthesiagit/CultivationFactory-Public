"""Drunken Style's base abilities and core states (rider lane C13, 2026-09-30; owner: "i want everything we can automated, keep going until
its only the non-combat ones left"). Printed: Sphere Compendium, Drunken Style ("Off-Rhythm", "False Opening", Reeling Step, Swaying
Guard, Broken-Rhythm Strike).

Off-Rhythm ("A creature that is Off-Rhythm from you has mistaken your balance ... Off-Rhythm lasts until the start of your next turn. A
creature can be Off-Rhythm from you only once at a time. Applying Off-Rhythm again refreshes the duration."): a typed mark named
"Off-Rhythm" (typed_executor.block_mark: one per creature per owner, refreshed), until the start of your next turn.

False Opening ("that creature has Advantage on the next attack roll it makes against you before the start of your next turn. If it makes
that attack, it becomes Off-Rhythm from you immediately after the attack resolves, whether it hits or misses."): ``drunken_false_opening``
puts ``condition:typed.false_opening`` (data: the opener) on the creature; ``before_attack`` gives its attack on the opener Advantage, and
``after_hit``/``after_miss`` (typed and native attacks) end it and mark it Off-Rhythm from the opener.

Broken-Rhythm Strike ("Special Attack ... Make an Unarmed Strike using the Damage option, an improvised melee weapon attack, or a melee
weapon attack. Hit: The attack deals normal damage, and the target becomes Off-Rhythm from you ... Miss by 5 or Less: You may choose to
create a False Opening for the target"): combat/ext/docket_maneuvers.py's maneuvers hook builds "Broken-Rhythm Strike: <weapon>" from each
melee, unarmed or natural weapon attack -- one attack (combat/ext/special_attacks.py gives the rest of the Attack action), with the
talents that print "with Broken-Rhythm Strike" attached by the compiler's own modifier pass; the miss rider is asked.

Reeling Step (Bonus Action: "move up to 10 feet ... This movement does not provoke Opportunity Attacks from one creature you can see.
Before or after this movement, choose one creature within 10 feet that can see you. ... Wisdom saving throw ... Failed Save: Off-Rhythm
from you ... Successful Save: ... it cannot make Opportunity Attacks against you during the movement"): ``drunken_reeling_step`` runs
before the typed 10 feet of movement it grants: both choices are asked (the AI takes the nearest hostile creature for both);
the shared granted_movement helper resolves a chosen native path immediately, with immunity only during that path.

Swaying Guard (Reaction: "If the attacker is Off-Rhythm from you, impose Disadvantage on the triggering attack roll. If you moved at least
5 feet since the end of your last turn, add your Proficiency Bonus to your AC against the triggering attack. ... If the triggering attack
misses, you may move 5 feet."): the generic ``attacked`` row runs ``drunken_swaying_guard``; ``reaction_subject_allowed`` offers it only
when one of the two ways applies (both: you choose); ``after_miss`` offers the 5-foot step (asked; no Opportunity Attacks).

The rhythm riders at the end of this module answer Slapstick Escape, Staggering Shove, The Floor Betrays You, Lucky-Looking Miss and
Laughing Feint. Laughing Feint's three printed results are placed as real conditions (it cannot make Opportunity Attacks against you,
another creature's next attack roll against it has Advantage, Disadvantage on its next Wisdom (Perception) or Wisdom (Insight) check),
each ending at the start of your next turn.

Ownership: the abilities' own compiled actions/rows; every hook returns early otherwise. Hooks added to the framework: none.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from . import dazed_restriction, effect, hook, note

BROKEN = "TAL_DRUNKEN_STYLE_BROKEN_RHYTHM_STRIKE"
REELING = "TAL_DRUNKEN_STYLE_REELING_STEP"
SWAYING = "TAL_DRUNKEN_STYLE_SWAYING_GUARD"
MARK = "Off-Rhythm"
FALSE_OPENING = "condition:typed.false_opening"
OFF_RHYTHM_ROW = {"type": "mark", "mark": MARK, "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"},
                  "evidence": "the target becomes Off-Rhythm from you until the start of your next turn"}
EMPTY_CUP = "TAL_DRUNKEN_STYLE_EMPTY_CUP_STANCE"
EMPTY_CUP_BLOCK = "drunken_empty_cup"
LOOSE_CUP = "TAL_DRUNKEN_STYLE_LOOSE_CUP_FOOTWORK"
CHAOS = "TAL_DRUNKEN_STYLE_CHAOS_STEP_AWAKENING"
SOVEREIGN = "TAL_DRUNKEN_STYLE_SOVEREIGN_CHAOS_STEP_INCARNATION"
FLIGHT = "condition:typed.drunken_sovereign_flight"
LOOSE_AIM = "condition:typed.drunken_loose_cup_aim"


@hook("compile_block")
def empty_cup_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Retain the owned stance and the compiler's actual worn-armor category."""
    if block in OWNED_BLOCKS:
        # A talent answered by a hook below leaves no action, row or modifier of its own, so without this marker the fight
        # would record no ownership at all and every hook would stay inert for its own owner.
        return [{**row, "block": block, "kind": str(spec.get("kind") or block.rsplit("_", 1)[-1])}]
    if block == "drunken_step_benefit":
        return [{**row, "block": block, "kind": spec.get("kind")}]
    if block != EMPTY_CUP_BLOCK:
        return None
    return [{**row, "block": EMPTY_CUP_BLOCK, "armor": str(numbers.get("armor") or ""), "keeps_compiling": True,
             **({"dodge_reeling": True} if spec.get("dodge_reeling") else {})}]


@hook("flight")
def sovereign_flight(engine: Any, actor: Any) -> dict[str, int] | None:
    if any(c.condition_id == FLIGHT and c.data.get("drunken_sovereign_flight") == 1 for c in actor.conditions.values()):
        from ..movement_speeds import land_speed_grant
        return {**land_speed_grant(engine, actor), "flight_hover": 1}
    return None


def _step_benefit(engine: Any, actor: Any, feature: str) -> bool:
    from .ability_source import compiled_feature_rows
    return any(r.get("block") == "drunken_step_benefit" for r in compiled_feature_rows(engine, actor.entity_id, feature))


@hook("choice_reactors")
def chaos_step_choice_owners(engine: Any) -> tuple[str, ...]:
    """Advertise potential defenders; the service filters to manual control.

    This is a pure ownership query. The miss hook still checks Off-Rhythm,
    the once-per-turn limit and legal movement before asking anyone.
    """
    return tuple(actor.entity_id for actor in engine.state.actors.values()
                 if actor.active and _step_benefit(engine, actor, CHAOS))


@hook("stand_cost")
def empty_cup_standing(engine: Any, actor: Any, normal_cost: int) -> int | None:
    """Empty Cup Stance: holding Focus, without heavy armor, stand for five feet.

    The native posture transition retains movement-budget and standing vetoes.
    Other providers can still grant a cheaper standing cost.
    """
    from .ability_source import compiled_feature_rows

    if not actor.active or actor.resources.get("resource:core.martial_focus", 0) < 1:
        return None
    rows = [row for row in compiled_feature_rows(engine, actor.entity_id, EMPTY_CUP)
            if row.get("block") == EMPTY_CUP_BLOCK]
    if rows and all(row.get("armor", "").lower() != "heavy" for row in rows):
        return 5
    return None


def off_rhythm(creature: Any, owner_id: str) -> bool:
    from ..typed_executor import bears_mark

    return bears_mark(creature, owner_id, MARK)


@effect("drunken_off_rhythm")
def off_rhythm_row(ctx: Any, eff: dict[str, Any]) -> None:
    """"the target becomes Off-Rhythm from you until the start of your next turn": the mark the maneuver and every other
    Off-Rhythm line place (combat/ext/docket_maneuvers.py names it on Broken-Rhythm Strike's own hit)."""
    from ..typed_executor import run_effects
    from . import placed

    run_effects(placed.context(ctx.engine, ctx.actor, ctx.source, {}, list(ctx.targets or ([ctx.target] if ctx.target else []))),
                [copy.deepcopy(OFF_RHYTHM_ROW)])


def _mark(engine: Any, owner: Any, creature: Any, source: str) -> None:
    from ..typed_executor import run_effects
    from . import placed

    run_effects(placed.context(engine, owner, source, {}, [creature]), [copy.deepcopy(OFF_RHYTHM_ROW)])


# ------------------------------------------------------------------------------------------------ Broken-Rhythm Strike
# "Broken-Rhythm Strike: <weapon>" is built by combat/ext/docket_maneuvers.py's maneuvers hook, one per melee, unarmed or
# natural attack, so the compiler's own modifier pass attaches the printed "with Broken-Rhythm Strike" talents to it. It used
# to be built here from the compile_actions hook, which the modifier pass runs before: every talent naming Broken-Rhythm Strike
# reported "no matching ability" and never resolved. Nothing in this module builds those actions any more.


# ------------------------------------------------------------------------------------------------ False Opening
def _lucky_focus(engine: Any, owner: Any, creature: Any, source: str) -> None:
    """Lucky-Looking Miss, first half: "you regain Martial Focus if you did not already have it"."""
    if not _owns(engine, owner, LUCKY):
        return
    pool = "resource:core.martial_focus"
    if int(owner.resources.get(pool, 0)) != 0 or int(owner.resource_maximums.get(pool, 0)) <= 0:
        return
    engine._gain_resource(owner, pool, 1, source)


@effect("drunken_false_opening")
def false_opening(ctx: Any, eff: dict[str, Any]) -> None:
    from .rider_choices import pick

    engine, owner, creature = ctx.engine, ctx.actor, ctx.target
    if creature is None or not creature.active:
        return
    if eff.get("asked") and not pick(engine, owner, "drunken_false_opening", "False Opening", ["open"], subject=creature, preferred=["open"],
                                     labels={"open": f"Create a False Opening: {creature.display_name}'s next attack on you has Advantage, "
                                                     f"then it is Off-Rhythm from you"},
                                     trigger=f"your {ctx.action.display_name} narrowly misses {creature.display_name}"):
        return
    _lucky_focus(engine, owner, creature, ctx.source)
    for iid, row in list(creature.conditions.items()):
        if row.condition_id == FALSE_OPENING and (row.data or {}).get("owner") == owner.entity_id:
            from .condition_ownership import remove_instance

            remove_instance(engine, creature, iid, ctx.source)
    engine._apply_condition(creature, FALSE_OPENING, ctx.source, owner.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"owner": owner.entity_id,
                                  "label": f"False Opening: Advantage on its next attack against {owner.display_name}, then it is Off-Rhythm"})


def _opening(attacker: Any, defender: Any) -> str | None:
    return next((iid for iid, row in attacker.conditions.items()
                 if row.condition_id == FALSE_OPENING and (row.data or {}).get("owner") == defender.entity_id), None)


@hook("before_attack")
def false_opening_advantage(engine: Any, attacker: Any, defender: Any, intent: Any, context: Any) -> dict[str, Any] | None:
    if attacker is None or defender is None or _opening(attacker, defender) is None:
        return None
    return {"mode": "ADVANTAGE"}


def _after_attack(engine: Any, attacker: Any, defender: Any) -> None:
    iid = _opening(attacker, defender) if attacker is not None and defender is not None else None
    if iid is None:
        return
    from .condition_ownership import remove_instance

    row = attacker.conditions[iid]
    remove_instance(engine, attacker, iid, row.source_definition_id)
    if attacker.active and defender.active:
        _mark(engine, defender, attacker, row.source_definition_id)
        note(engine, row.source_definition_id, defender, f"{attacker.display_name} took the False Opening: it is now Off-Rhythm from "
                                                         f"{defender.display_name}.", (attacker,))


@hook("after_hit")
def false_opening_hit(ctx: Any, target: Any, kind: str) -> None:
    _after_attack(ctx.engine, ctx.actor, target)
    _consume_afterimage(ctx, target)
    _swaying_outcome(ctx, target, False)


@hook("after_miss")
def false_opening_miss(ctx: Any, target: Any) -> None:
    _lucky_opening_miss(ctx, target)  # Lucky-Looking Miss reads the opening before this spends it
    _after_attack(ctx.engine, ctx.actor, target)
    _consume_afterimage(ctx, target)
    _swaying_outcome(ctx, target, True)


# ------------------------------------------------------------------------------------------------ Reeling Step
@effect("drunken_reeling_step")
def reeling_step(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects, mark_condition_id
    from .rider_choices import pick
    from .. import stealth

    engine, me = ctx.engine, ctx.actor
    modern = bool(eff.get("step_v2"))
    loose = modern and _step_benefit(engine, me, LOOSE_CUP)
    feet = 10
    if modern and _step_benefit(engine, me, CHAOS):
        feet = 20
    if modern and any(c.condition_id == FLIGHT and c.data.get("drunken_sovereign_flight") == 1 for c in me.conditions.values()):
        feet = 30
    feet += 5 if loose else 0
    failed_target = None
    targets = engine.state.actors.values() if modern else stealth.foes(engine, me)
    foes = sorted((f for f in targets if f.active
                   and engine._distance_actor_to_actor(me, f) <= 10 and stealth.sees(engine, f, me)),
                  key=lambda f: (f.team_id == me.team_id, engine._distance_actor_to_actor(me, f), f.entity_id))
    ignored: list[str] = []
    if foes:
        chosen = pick(engine, me, "drunken_reeling_test", "Reeling Step", [f.entity_id for f in foes], subject=me,
                      labels={f.entity_id: f"{f.display_name} makes a Wisdom save: on a failure it is Off-Rhythm from you; on a success it "
                                           f"cannot make Opportunity Attacks against you during this move" for f in foes},
                      preferred=[foes[0].entity_id], optional=False, trigger="Reeling Step")
        tested = engine.state.actors.get((chosen or [foes[0].entity_id])[0])
        if tested is not None:
            before = len(engine.events)
            from .placed import context

            run_effects(context(engine, me, ctx.source, dict(ctx.numbers), [tested]),
                        [{"type": "save", "ability": "wis", "applies_to": "target", "on_fail": [copy.deepcopy(OFF_RHYTHM_ROW)], "on_success": []}])
            rolled = next((e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED" and e.actor_id == tested.entity_id), None)
            if rolled is not None and (rolled.payload or {}).get("success"):
                ignored.append(tested.entity_id)
            elif modern and any(e.event_type == "CONDITION_APPLIED" and tested.entity_id in e.target_ids
                                and e.source_definition_id == ctx.source and e.payload.get("condition_id") == mark_condition_id(MARK, me.entity_id)
                                for e in engine.events[before:]):
                failed_target = tested
    watchers = sorted((f for f in stealth.foes(engine, me) if stealth.sees(engine, me, f)),
                      key=lambda f: (engine._distance_actor_to_actor(me, f), f.entity_id))
    if watchers:
        chosen = pick(engine, me, "drunken_reeling_oa", "Reeling Step", [f.entity_id for f in watchers], subject=me,
                      labels={f.entity_id: f"Your move does not provoke Opportunity Attacks from {f.display_name}" for f in watchers},
                      preferred=[next((f.entity_id for f in watchers if f.entity_id not in ignored), watchers[0].entity_id)],
                      optional=False, trigger="Reeling Step")
        ignored.append((chosen or [watchers[0].entity_id])[0])
    from .granted_movement import choices, move
    from .needle import cell_id

    terrain_id = None
    if loose:
        before_conditions = set(me.conditions)
        engine._apply_condition(me, "condition:typed.drunken_reeling_terrain", ctx.source, me.entity_id,
            expires_on="UNTIL_REMOVED", data={"rule": {"ignore_difficult": True},
                "label": "Loose-Cup Footwork: ignore nonmagical difficult terrain only during Reeling Step"})
        terrain_id = next((iid for iid in me.conditions if iid not in before_conditions), None)
    from .. import motion
    try:
        with motion.terrain_for(engine, me):
            paths = choices(engine, me, feet)
            options = [cell_id(c.destination) for c in paths]
            labels = {cell_id(c.destination): f"Move to {c.destination.x},{c.destination.y} ({c.movement_cost_ft} feet)" for c in paths}
            chosen = pick(engine, me, "drunken_reeling_move", "Reeling Step", options, subject=me, labels=labels,
                          trigger=f"{eff.get('trigger_name') or 'your Bonus Action'} grants up to {feet} feet of movement; only this move avoids the chosen creatures' Opportunity Attacks")
            if chosen:
                path = next(c for c in paths if cell_id(c.destination) == chosen[0])
                move(engine, me, path, ctx.intent, feet, ignored, name="Reeling Step")
            if loose and failed_target is not None and engine._distance_actor_to_actor(me, failed_target) <= 5:
                from ..typed_executor import effect_expiry
                engine._remove_condition(me, LOOSE_AIM, ctx.source)
                engine._apply_condition(me, LOOSE_AIM, ctx.source, me.entity_id,
                    expires_on=effect_expiry(ctx, {"duration": "until_end_of_turn"}, me, condition=True),
                    data={"target_id": failed_target.entity_id,
                          "label": f"Loose-Cup Footwork: next Broken-Rhythm Strike against {failed_target.display_name} has Advantage this turn"})
    finally:
        if terrain_id is not None:
            from .condition_ownership import remove_instance
            remove_instance(engine, me, terrain_id, ctx.source)


@hook("before_attack")
def loose_cup_aim(engine: Any, attacker: Any, defender: Any, intent: Any, context: Any) -> dict[str, str] | None:
    action = engine.action_catalog.get(context.get("source_id"))
    if action is None or ((action.parameters or {}).get("typed") or {}).get("source") != BROKEN:
        return None
    if any(c.condition_id == LOOSE_AIM and c.data.get("target_id") == defender.entity_id for c in attacker.conditions.values()):
        return {"mode": "ADVANTAGE"}
    return None


@hook("after_hit")
def loose_cup_hit(ctx: Any, target: Any, kind: str) -> None:
    _consume_loose_aim(ctx, target)


@hook("after_miss")
def loose_cup_miss(ctx: Any, target: Any) -> None:
    _consume_loose_aim(ctx, target)


@hook('after_miss')
def chaos_missed_step(ctx: Any, target: Any) -> None:
    """Chaos-Step's defender-owned optional step, once on the actual turn.

    Use the exhaustive native granted paths; no capped cell menu or teleport.
    Only the Off-Rhythm attacker's opportunity attacks are exempted.
    """
    engine = ctx.engine
    if not target.active or not _step_benefit(engine, target, CHAOS) or not off_rhythm(ctx.actor, target.entity_id):
        return
    current = engine.state.actors[engine.state.current_actor_id]
    key = f'{engine.state.round_number}:{current.entity_id}:{current.turns_started}'
    if target.turn_flags.get('drunken_chaos_miss_turn') == key:
        return
    from .. import granted_movement
    from .needle import ask, checkpoint_id
    paths = granted_movement.candidates(engine, target, 10, ctx.intent, CHAOS)
    if not paths:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, 'chaos_missed_step', ctx.source, target.entity_id),
        target, 'choice:needle.chaos_missed_step', list(paths), allow_decline=True, name='Chaos-Step Awakening',
        target_id=target.entity_id,
        labels={k: f'Move {c.movement_cost_ft} feet to square ({c.destination.x}, {c.destination.y})' for k, c in paths.items()},
        prompt=f'Chaos-Step Awakening: Off-Rhythm {ctx.actor.display_name} misses {target.display_name} with {ctx.action.display_name}. Move up to 10 feet, once this turn, without Opportunity Attacks from that creature? No action or points are spent.')
    if picked:
        target.turn_flags['drunken_chaos_miss_turn'] = key
        engine._resolve_movement(target, paths[picked[0]], ctx.intent, granted_ft=10,
                                 ignore_oa_from=(ctx.actor.entity_id,))


def _consume_loose_aim(ctx: Any, target: Any) -> None:
    if ctx.typed.get("source") != BROKEN:
        return
    from .condition_ownership import remove_instance
    for held in list(ctx.actor.conditions.values()):
        if held.condition_id == LOOSE_AIM and held.data.get("target_id") == target.entity_id:
            remove_instance(ctx.engine, ctx.actor, held.instance_id, ctx.source)


@hook("event")
def empty_cup_dodge(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_APPLIED" or (kwargs.get("payload") or {}).get("condition_id") != "condition:core.dodge":
        return
    event = kwargs.get("originating_event")
    action = engine.action_catalog.get(event.source_definition_id) if event is not None else None
    me = engine.state.actors.get(kwargs.get("actor_id"))
    if action is None or action.resolution_kind != "DODGE" or me is None or empty_cup_standing(engine, me, 15) is None:
        return
    from .ability_source import compiled_feature_rows
    if not any(r.get("dodge_reeling") for r in compiled_feature_rows(engine, me.entity_id, EMPTY_CUP)):
        return
    reeling = next((a for a in engine.action_catalog.values() if a.owner_id == me.entity_id
                    and (a.parameters or {}).get("typed", {}).get("source") == REELING), None)
    if reeling is None or engine._effective_speed(me) <= 0:
        return
    from .rider_choices import pick
    if not pick(engine, me, "empty_cup_dodge_reeling", "Empty Cup Stance", ["step"], subject=me,
                labels={"step": "Use Reeling Step as part of Dodge; keep your Bonus Action"},
                trigger="you take Dodge while holding Martial Focus without heavy armor",
                prompt_context={"cost": "No additional Action, Bonus Action or Martial Focus cost"}):
        return
    from .placed import context
    for eff in (reeling.parameters or {}).get("typed", {}).get("effects", []):
        if eff.get("type") == "drunken_reeling_step":
            reeling_step(context(engine, me, reeling.source_definition_id,
                                 reeling.parameters["typed"]["numbers"], [me]), {**eff, "trigger_name": "Dodge"})


# ------------------------------------------------------------------------------------------------ Swaying Guard
SWAY_FLAG = "_round_drunken_swaying"


def moved_since_last_turn(engine: Any, actor: Any) -> int:
    """Feet ``actor`` moved since the end of its last turn (its own moves and the moves made of it)."""
    feet = 0
    for event in reversed(engine.events):
        if event.event_type == "TURN_ENDED" and event.actor_id == actor.entity_id:
            break
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == actor.entity_id:
            path = (event.payload or {}).get("path") or []
            feet += max(0, len(path) - 1) * engine.grid.square_size_ft
    return feet


@hook("reaction_subject_allowed")
def swaying_needs_a_way(engine: Any, reactor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    if row.get("feature_id") != SWAYING:
        return None
    return bool(other is not None and (off_rhythm(other, reactor.entity_id) or moved_since_last_turn(engine, reactor) >= 5))


@effect("drunken_swaying_guard")
def swaying_guard(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects
    from .rider_choices import pick

    engine, me = ctx.engine, ctx.actor
    attacker = ctx.target if ctx.target is not None and ctx.target is not me else None
    ways = []
    if attacker is not None and off_rhythm(attacker, me.entity_id):
        ways.append("disadvantage")
    if moved_since_last_turn(engine, me) >= 5:
        ways.append("ac")
    if not ways:
        return
    pb = int(ctx.numbers.get("pb") or 2)
    labels = {"disadvantage": f"{getattr(attacker, 'display_name', 'The attacker')} is Off-Rhythm: its attack roll has Disadvantage",
              "ac": f"You moved at least 5 feet since your last turn ended: +{pb} AC against this attack"}
    way = (pick(engine, me, "drunken_swaying_way", "Swaying Guard", ways, subject=attacker or me, labels=labels, preferred=[ways[0]],
                optional=False, trigger="an attack roll against you") if len(ways) > 1 else ways) or ways
    if way[0] == "disadvantage":
        run_effects(ctx, [{"type": "disadvantage", "applies_to": "attacker", "on": "the triggering attack roll", "duration": "instant",
                           "evidence": "If the attacker is Off-Rhythm from you, impose Disadvantage on the triggering attack roll."}])
    else:
        run_effects(ctx, [{"type": "ac_bonus", "applies_to": "self", "flat": pb, "on": "the triggering attack", "duration": "special",
                           "evidence": "add your Proficiency Bonus to your AC against the triggering attack"}])
    me.turn_flags[SWAY_FLAG] = f"pending:{getattr(attacker, 'entity_id', '')}"


@hook("before_attack")
def bind_swaying_attack(engine: Any, attacker: Any, defender: Any, intent: Any, context: Any) -> None:
    if defender.turn_flags.get(SWAY_FLAG) == f"pending:{attacker.entity_id}":
        defender.turn_flags[SWAY_FLAG] = f"{getattr(intent, 'intent_id', '')}|{attacker.entity_id}|ATTACK:{context['source_id']}:{context['attack_index']}"


def _swaying_outcome(ctx: Any, defender: Any, missed: bool) -> None:
    """"If the triggering attack misses, you may move 5 feet." (asked; the step provokes no Opportunity Attack)."""
    engine, attacker = ctx.engine, ctx.actor
    if attacker is None or defender is None:
        return
    notice = getattr(ctx, "attack_notice", None)
    reason = f"ATTACK:{notice.source_id}:{notice.attack_index}" if notice else (ctx.attack_result or {}).get("reason")
    token = f"{getattr(ctx.intent, 'intent_id', '')}|{attacker.entity_id}|{reason}"
    if defender.turn_flags.get(SWAY_FLAG) != token:
        return
    defender.turn_flags.pop(SWAY_FLAG, None)
    if not missed or not defender.active:
        return
    from .ability_source import compiled_feature_rows
    if any(r.get("block") == "drunken_afterimage" for r in compiled_feature_rows(engine, defender.entity_id, AFTERIMAGE)):
        engine._apply_condition(defender, AFTERIMAGE_CONDITION, AFTERIMAGE, defender.entity_id,
            expires_on="START_OF_SOURCE_NEXT_TURN", data={"afterimage_v1": True,
                "label": f"Afterimage Sway: your next incoming attack has Disadvantage if within 30 feet and the attacker can perceive you; unused image expires at the start of {defender.display_name}\'s next turn"})
    from .rider_choices import step

    step(engine, defender, "drunken_swaying_step", "Swaying Guard", attacker, 5, f"reaction:{SWAYING}",
         trigger=f"{attacker.display_name}'s guarded attack misses you; move up to 5 feet without provoking that attacker",
         ignored_oa=[attacker.entity_id])


@hook("candidate_allowed")
def reeling_needs_speed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Reeling Step: "You cannot use Reeling Step if your Speed is 0.\""""
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    source = str(typed.get("option_of") or typed.get("source") or "")
    if source == BROKEN and not typed.get("effects"):
        return False  # the record's own empty button: the strike is made through a weapon ("Broken-Rhythm Strike: <weapon>")
    if source != REELING:
        return None
    return engine._effective_speed(actor) > 0


# ============================================================================================ Rhythm riders
# The talents below had a printed core the engine already resolved and one clause that was still only a GM rider.
# Each hook here answers its own talent and returns early for any creature that does not own it
# (combat/ext/fight_ownership.owns_feature), so nothing here changes another Sphere or an older saved fight.
SLAPSTICK = "TAL_DRUNKEN_STYLE_SLAPSTICK_ESCAPE"
STAGGERING = "TAL_DRUNKEN_STYLE_STAGGERING_SHOVE"
FLOOR = "TAL_DRUNKEN_STYLE_THE_FLOOR_BETRAYS_YOU"
LUCKY = "TAL_DRUNKEN_STYLE_LUCKY_LOOKING_MISS"
FEINT = "tianxia.talent.drunken_style.laughing_feint"
DAZED = dazed_restriction.DRUNKEN_DAZED
LUCKY_AIM = "condition:typed.drunken_lucky_aim"
OWNED_BLOCKS = {"drunken_afterimage"} | {f"drunken_{key}" for key in ("laughing_feint", "slapstick_escape", "staggering_shove", "lucky_looking_miss")}


def _owns(engine: Any, actor: Any, feature: str) -> bool:
    """Whether ``actor`` owns ``feature`` in this fight.

    Two recorded forms count, because a talent that only changes another ability leaves no action, passive row or
    reaction of its own: combat/ext/fight_ownership.owns_feature reads the compiled bundle's own rows and action ids, and
    combat/ext/creature_kinds.owns_modifier reads the same bundle's modifier report (the printed "changes this ability"
    record). A creature with neither is not the owner, so every hook here stays inert for it.
    """
    from .creature_kinds import owns_modifier
    from .fight_ownership import owns_feature

    if actor is None:
        return False
    return owns_feature(engine, actor, feature) or owns_modifier(engine, actor, feature)


def _melee(ctx: Any) -> bool:
    """The triggering attack was made with a melee weapon attack or an Unarmed Strike -- not thrown, not shot.

    A thrown weapon is a ranged attack however close the thrower stands (its printed range is the throw), so the
    melee-or-thrown predicate combat/ext/passive_rows.py offers is too wide for a talent whose printed trigger is
    "misses you with a melee attack". Any reach counts: a polearm is still a melee attack at 10 feet.
    """
    from .passive_rows import melee_or_thrown

    return not str(ctx.action.source_definition_id).endswith("#thrown") and melee_or_thrown(ctx)


def _shove_option(ctx: Any) -> bool:
    """The triggering save belongs to the Shove option of an Unarmed Strike (combat/factory_compiler.py's option actions)."""
    return str(ctx.typed.get("unarmed_option") or "").startswith("shove")


# ------------------------------------------------------------------------------------------------ Slapstick Escape
@hook("after_miss")
def slapstick_escape(ctx: Any, target: Any) -> None:
    """Slapstick Escape: "When a creature misses you with a melee attack, you may move 5 feet without provoking
    Opportunity Attacks from that creature. If the attacker was Off-Rhythm from you, you may move 10 feet instead."

    Only that attacker is left unable to make the Opportunity Attack against the step, and only a melee miss answers.
    """
    engine, attacker, me = ctx.engine, ctx.actor, target
    if me is None or attacker is None or not me.active or not attacker.active or me.entity_id == attacker.entity_id:
        return
    if not _melee(ctx) or not _owns(engine, me, SLAPSTICK):
        return
    # "misses you with a melee attack": the attack was made in melee, so the attacker is within that weapon's own reach --
    # a polearm reaches 10 feet, so this reads the attack's reach instead of guessing five.
    from .reach_bonus import current_reach

    if engine._distance_actor_to_actor(attacker, me) > current_reach(engine, attacker, ctx.action):
        return
    feet = 10 if off_rhythm(attacker, me.entity_id) else 5
    from .rider_choices import step

    step(engine, me, "drunken_slapstick_step", "Slapstick Escape", attacker, feet, ctx.source,
         trigger=f"{attacker.display_name}'s melee attack misses you: move up to {feet} feet without provoking that "
                 f"attacker's Opportunity Attack",
         ignored_oa=[attacker.entity_id])


# ------------------------------------------------------------------------------------------------ Staggering Shove
@hook("save")
def staggering_shove_disadvantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Staggering Shove: "the target has Disadvantage on its saving throw" -- only the Shove option, only an
    Off-Rhythm creature."""
    if subject is None or not _shove_option(ctx) or not _owns(ctx.engine, ctx.actor, STAGGERING):
        return None
    return {"bonus": 0, "modes": ["DISADVANTAGE"]} if off_rhythm(subject, ctx.actor.entity_id) else None


@hook("after_save")
def staggering_shove_step(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Staggering Shove: "If the Shove succeeds, you may also move 5 feet into a legal space" that only creature
    cannot make an Opportunity Attack against.

    ``failed`` is the target's own save-failure flag, and a Shove lands exactly when that save fails, so the printed
    five feet are offered on ``failed`` and withheld when the target resists the push.
    """
    if not failed or subject is None or not _shove_option(ctx) or not _owns(ctx.engine, ctx.actor, STAGGERING):
        return
    if not off_rhythm(subject, ctx.actor.entity_id):
        return
    from .rider_choices import step

    step(ctx.engine, ctx.actor, "drunken_staggering_step", "Staggering Shove", subject, 5, ctx.source,
         trigger=f"your Shove lands: {subject.display_name} fails its Strength saving throw, so you may move up to 5 feet "
                 f"into a legal space without provoking that creature's Opportunity Attack",
         ignored_oa=[subject.entity_id])


# ------------------------------------------------------------------------------------------------ The Floor Betrays You
@effect("drunken_dazed")
def drunken_dazed(ctx: Any, eff: dict[str, Any]) -> None:
    """"Failed Save: The target is Prone and Dazed until the start of your next turn": both together."""
    from ..typed_executor import effect_expiry, run_effects

    run_effects(ctx, [{"type": "condition", "applies_to": "target", "condition": "prone", "duration": "instant",
                       "evidence": "The target is Prone and Dazed until the start of your next turn"}])
    for subject in ctx.targets or ([ctx.target] if ctx.target else []):
        dazed_restriction.apply(ctx.engine, subject, DAZED, ctx.source, ctx.actor.entity_id,
                                expires_on=effect_expiry(ctx, {"duration": "until_start_of_your_next_turn"}, subject, condition=True))


@effect("drunken_floor_betrayed_success")
def floor_betrayed_success(ctx: Any, eff: dict[str, Any]) -> None:
    """"Successful Save: The target is Prone, or it is Dazed until the start of your next turn, your choice"."""
    from ..typed_executor import effect_expiry, run_effects
    from .rider_choices import pick

    subject = ctx.target if ctx.target is not None else next(iter(ctx.targets or []), None)
    if subject is None or not subject.active:
        return
    options = ["prone", "dazed"]
    labels = {"prone": f"{subject.display_name} falls Prone",
              "dazed": f"{subject.display_name} is Dazed until the start of your next turn: no Reactions, and an Action or "
                       f"a Bonus Action on its turn, not both"}
    chosen = pick(ctx.engine, ctx.actor, "drunken_floor_betrayed", "The Floor Betrays You", options, subject=subject,
                  labels=labels, preferred=["prone"], trigger=f"{subject.display_name} succeeds the saving throw")
    if (chosen or options)[0] == "dazed":
        dazed_restriction.apply(ctx.engine, subject, DAZED, ctx.source, ctx.actor.entity_id,
                                expires_on=effect_expiry(ctx, {"duration": "until_start_of_your_next_turn"}, subject, condition=True))
    else:
        run_effects(ctx, [{"type": "condition", "applies_to": "target", "condition": "prone", "duration": "instant",
                           "evidence": "The target is Prone, or it is Dazed until the start of your next turn, your choice"}])


# ------------------------------------------------------------------------------------------------ Lucky-Looking Miss
def _lucky_opening_miss(ctx: Any, target: Any) -> None:
    """Lucky-Looking Miss, second half: "If the target attacks you before the start of your next turn and misses, you
    gain Advantage on the next attack roll you make against it before the end of your next turn."

    The False Opening on the attacker is the printed trigger. It is read here, from False Opening's own after_miss and
    before that spends the opening, and the benefit is a real condition on the Drunken Style owner scoped to that one
    creature.
    """
    engine, attacker, me = ctx.engine, ctx.actor, target
    if attacker is None or me is None or not attacker.active or not me.active:
        return
    opening = _opening(attacker, me)
    if opening is None or not _owns(engine, me, LUCKY):
        return  # the talent belongs to the creature that created the False Opening: the one that was attacked
    engine._remove_condition(me, LUCKY_AIM, ctx.source)
    # "before the end of your next turn" -- your turn is the owner's, whoever is acting when the opening's creature misses,
    # so the benefit is held to the end of the owner's own next turn (never the attacker's turn end).
    engine._apply_condition(me, LUCKY_AIM, ctx.source, me.entity_id, expires_on="END_OF_HOLDER_NEXT_TURN",
                            data={"target_id": attacker.entity_id,
                                  "label": f"Lucky-Looking Miss: your next attack roll against {attacker.display_name} "
                                           f"has Advantage before the end of your next turn"})


@hook("before_attack")
def lucky_looking_advantage(engine: Any, attacker: Any, defender: Any, intent: Any, context: Any) -> dict[str, str] | None:
    if attacker is None or defender is None:
        return None
    if any(c.condition_id == LUCKY_AIM and c.data.get("target_id") == defender.entity_id
           for c in attacker.conditions.values()):
        return {"mode": "ADVANTAGE"}
    return None


@hook("after_hit")
def lucky_looking_spent(ctx: Any, target: Any, kind: str) -> None:
    """"the next attack roll you make against it": the benefit is spent by the attack it was for."""
    if target is None:
        return
    _spend_lucky_aim(ctx.engine, ctx.actor, target, ctx.source)


@hook("after_miss")
def lucky_looking_spent_miss(ctx: Any, target: Any) -> None:
    """The printed benefit is for the next attack *roll*, not the next hit, so a miss spends it exactly as a hit does.

    Without this the Advantage survived a whiffed attack and was still live for the following one.
    """
    if target is None:
        return
    _spend_lucky_aim(ctx.engine, ctx.actor, target, ctx.source)


def _spend_lucky_aim(engine: Any, attacker: Any, target: Any, source: str) -> None:
    from .condition_ownership import remove_instance

    for held in list(getattr(attacker, "conditions", {}).values()):
        if held.condition_id == LUCKY_AIM and held.data.get("target_id") == getattr(target, "entity_id", None):
            remove_instance(engine, attacker, held.instance_id, source)


# ------------------------------------------------------------------------------------------------ Laughing Feint
# "When a creature becomes Off-Rhythm from you, choose one of the following." All three printed results belong to the
# creature that just became Off-Rhythm and all three end "before the start of your next turn" -- the talent owner's
# turn, which is the same deadline False Opening above already stores as START_OF_SOURCE_NEXT_TURN.
FEINT_DEADLINE = "START_OF_SOURCE_NEXT_TURN"
FEINT_NO_OA = "condition:typed.drunken_feint_no_oa"
FEINT_ALLY = "condition:typed.drunken_feint_ally_advantage"
FEINT_BAD_READ = "condition:typed.drunken_feint_bad_read"
FEINT_OPTIONS = {
    "no_oa": "it cannot make Opportunity Attacks against you until the start of your next turn",
    "ally_advantage": "the next attack roll against it by a creature other than you has Advantage, before the start of your "
                      "next turn",
    "bad_read": "it has Disadvantage on its next Wisdom (Perception) or Wisdom (Insight) check, before the start of your "
                "next turn",
}
FEINT_CONDITION = {"no_oa": FEINT_NO_OA, "ally_advantage": FEINT_ALLY, "bad_read": FEINT_BAD_READ}

# "its next Wisdom (Perception) or Wisdom (Insight) check": the two skills, and the Wisdom ability they are read with.
# This pair is the one definition of the bad read's scope. It decides both whether a check is covered (the mode) and
# whether the roll that was made spends it (the two hooks below), so the two can never drift apart.
BAD_READ_ABILITY = "WIS"
BAD_READ_SKILLS = ("perception", "insight")


def _names_bad_read(ability: Any, skill: Any) -> bool:
    """Whether one check/save specification is one of the checks the bad read names."""
    return str(ability or "").strip().upper() == BAD_READ_ABILITY \
        and _names_bad_read_skill(skill)


def _names_bad_read_skill(skill: Any) -> bool:
    """Whether one skill name is one of the two the bad read names.

    Skill-only, with no ability test, because that is how ``_bad_read_rule``'s ``check_mode`` table keys itself: the engine
    matches the two skills on the check it is actually rolling. Reading it the same way here is what keeps the mode and the
    spending from drifting -- a roll that was *not* disadvantaged by this condition must not be charged for it.
    """
    return str(skill or "").strip().lower() in BAD_READ_SKILLS


def _names_bad_read_in_text(text: Any) -> bool:
    """Whether a written label names one of the two skills, as whole words only.

    Producers label a recorded check with prose rather than a bare key -- "Perception" (a Search), "Wisdom (Insight)"
    (Break the Glass), "Intelligence (Investigation) or Wisdom (Perception), Analyze" (Analyze) -- so the words have to be
    read out of the sentence. Whole words keep an unrelated label that merely contains the letters out of it.
    """
    lowered = str(text or "").lower()
    return any(re.search(rf"\b{skill}\b", lowered) for skill in BAD_READ_SKILLS)


def _labelled_skills(text: Any) -> list[str]:
    """Every skill name one recorded check's own label names, in the order printed.

    A label either spells the skill out bare ("Perception") or wraps it in the ability it is read with ("Wisdom (Insight)"),
    or lists several -- "Intelligence (Investigation) or Wisdom (Perception), Analyze" is the menu the creature chose from,
    not a statement about the die that was kept.
    """
    label = str(text or "").strip()
    if not label:
        return []
    wrapped = [part.strip() for part in re.findall(r"\(([^()]*)\)", label) if part.strip()]
    return wrapped or [label]


def _rolled_bad_read_check(payload: dict[str, Any]) -> bool:
    """Whether the check this ``CHECK_ROLLED`` event recorded is one the bad read names.

    The event's own label is the authority, because every single-check producer in the game names the check that way. A
    label that offers a *choice* ("Intelligence (Investigation) or Wisdom (Perception), Analyze") is not: the creature rolled
    every option and kept the best, so the label says Perception even when Investigation was the die it kept. Those are
    read from the roll's own reason, which records the skill that was actually used ("CHECK:analyze:perception").
    """
    for key in ("check", "skill"):
        skills = _labelled_skills(payload.get(key))
        if not skills:
            continue
        if len(skills) == 1:
            return _names_bad_read_skill(skills[0]) or _names_bad_read_in_text(skills[0])
        # A menu: the label is the choice, so only the roll can say which option it kept. Producers record that as the
        # reason's last segment, by the "CHECK:<source>:<skill>" convention. It is the answer even when the skill it names
        # is one the label never listed -- an Empirical Tracker's Wisdom (Survival) Analyze is not a Perception check.
        rolled = str((payload.get("actor") or {}).get("reason") or "")
        if rolled.strip().upper().startswith("CHECK:") and ":" in rolled.strip()[6:]:
            return _names_bad_read_skill(rolled.rsplit(":", 1)[-1])
        # No recorded roll to read, so the bad read is not provably spent; spend it anyway rather than let a one-use printed
        # effect hang for the rest of the fight.
        return any(_names_bad_read_skill(name) for name in skills)
    return False


def _bad_read_rule() -> dict[str, Any]:
    """The single authoritative mode source: the engine's own ``check_mode`` rule, read by ``typed_executor.check_modes``.

    It is carried as condition data rather than an ``ability_check_mode`` hook because that is the seam every caller
    already uses -- ``check_modes``/``check_mode``, which the opposed-check resolver calls for *each* participant before
    either die is drawn. A hook on the same effect would have to re-derive the ability scope itself, and the two
    implementations did differ: the data keys on the two skills alone, while the hook also demanded WIS, so a check the
    data covered was refused by the hook. One rule, read through one resolver, for every check in the game.
    """
    return {"check_mode": {skill: "DISADVANTAGE" for skill in ("Perception", "Insight")}}


def _spend_bad_read(engine: Any, subject: Any, source: str | None) -> None:
    """End exactly this creature's own bad-read instances, by id.

    The engine's ``_remove_condition`` would delete every instance of the condition id at once; each Feint is a
    separate caster's separate effect, so they are removed one at a time. ``source`` is the naming source for the removal
    events, and None means "use each instance's own source", which is what an event-driven call has to hand.
    """
    from .condition_ownership import remove_instance

    for held in list(getattr(subject, "conditions", {}).values()):
        if held.condition_id == FEINT_BAD_READ:
            remove_instance(engine, subject, held.instance_id, source or held.source_definition_id)


@hook("mark_applied")
def laughing_feint(ctx: Any, name: str, subject: Any) -> None:
    """Laughing Feint: "When a creature becomes Off-Rhythm from you, choose one of the following" -- asked once, on the
    same mark placement that made it Off-Rhythm, and the chosen result is placed there as a real condition.

    Each result keeps its own printed length: the Opportunity-Attack bar lasts the whole deadline, while the other two
    are spent by the roll they name (hit or miss, taken or observed).
    """
    engine, owner, creature = ctx.engine, ctx.actor, subject
    if name.strip().lower() != MARK.lower() or creature is None or not creature.active:
        return
    if not _owns(engine, owner, FEINT):
        return
    from .condition_ownership import remove_instance
    from .rider_choices import pick

    chosen = pick(engine, owner, "drunken_feint", "Laughing Feint", list(FEINT_OPTIONS), subject=creature,
                  labels={key: f"{creature.display_name}: {text}" for key, text in FEINT_OPTIONS.items()}, preferred=["no_oa"],
                  trigger=f"{creature.display_name} becomes Off-Rhythm from you") or ["no_oa"]
    option = chosen[0]
    condition_id = FEINT_CONDITION.get(option)
    if condition_id is None:
        return
    for iid, held in list(creature.conditions.items()):
        if held.condition_id == condition_id and (held.data or {}).get("owner") == owner.entity_id:
            remove_instance(engine, creature, iid, ctx.source)
    rule = _bad_read_rule() if option == "bad_read" else None
    engine._apply_condition(creature, condition_id, ctx.source, owner.entity_id, expires_on=FEINT_DEADLINE,
                            data={"owner": owner.entity_id, **({"rule": rule} if rule else {}),
                                  "label": f"Laughing Feint: {creature.display_name} {FEINT_OPTIONS[option]}"})


def _allies_of(creature: Any, attacker: Any) -> list[Any]:
    """Every Laughing Feint Advantage ``creature`` holds that ``attacker``'s next attack roll may use.

    "the next attack roll against it by a creature other than you": one roll is the next eligible roll for *every* such
    instance at once, and printed Advantage does not stack with itself, so all of them are spent by that single roll and
    the mode is offered while any of them is still held. An instance the attacker placed itself is never included --
    "by a creature other than you".
    """
    if attacker is None or getattr(creature, "entity_id", None) == getattr(attacker, "entity_id", None):
        return []
    return [c for c in getattr(creature, "conditions", {}).values()
            if c.condition_id == FEINT_ALLY and (c.data or {}).get("owner") != attacker.entity_id]


@hook("opportunity_allowed")
def laughing_feint_no_opportunity(engine: Any, reactor: Any, mover: Any) -> bool | None:
    """"it cannot make Opportunity Attacks against you until the start of your next turn"."""
    if reactor is None or mover is None:
        return None
    held = next((c for c in getattr(reactor, "conditions", {}).values()
                 if c.condition_id == FEINT_NO_OA and (c.data or {}).get("owner") == mover.entity_id), None)
    return False if held is not None else None


@hook("attack_mode")
def laughing_feint_ally_advantage(ctx: Any, target: Any) -> str | None:
    """"the next attack roll against it by a creature other than you has Advantage": the mode only; the matching
    after_hit/after_miss below spend it, so a mode query never burns the printed roll."""
    if target is None:
        return None
    return "ADVANTAGE" if _allies_of(target, ctx.actor) else None


def _spend_feint_ally(engine: Any, target: Any, attacker: Any, source: str) -> None:
    """End every Advantage instance whose next eligible attack roll was just made -- overlapping Feints included.

    Selecting only the first instance left the second one live, and it then wrongly helped the attacker's *next* attack
    roll as well. Each instance is removed by its own id, so other casters' instances of other conditions are untouched.
    """
    from .condition_ownership import remove_instance

    for held in _allies_of(target, attacker):
        remove_instance(engine, target, held.instance_id, source)


@hook("after_hit")
def laughing_feint_ally_hit(ctx: Any, target: Any, kind: str) -> None:
    if target is not None:
        _spend_feint_ally(ctx.engine, target, ctx.actor, ctx.source)


@hook("after_miss")
def laughing_feint_ally_miss(ctx: Any, target: Any) -> None:
    if target is not None:
        _spend_feint_ally(ctx.engine, target, ctx.actor, ctx.source)


@hook("opposed_check_resolved")
def laughing_feint_bad_read_opposed(ctx: Any, target: Any, result: Any, actor_check: dict[str, Any],
                                    target_check: dict[str, Any]) -> None:
    """Spend the bad read for each participant whose *own* check is one of the two the rule names.

    "it has Disadvantage on its next Wisdom (Perception) or Wisdom (Insight) check": in an opposed check both creatures
    roll, and each is told its mode before its die is drawn, so the feinted creature's own check is a real qualifying
    roll. Reading only the CHECK_ROLLED payload missed it -- that payload names the initiating actor's check once
    (``check`` is the constant "Opposed check", ``skill`` is the initiator's), and keeps the defender's roll under
    ``target`` -- so a feinted defender kept the penalty for later checks. This hook receives both check specifications,
    so each participant is charged for its own qualifying roll. A saving throw is not a check and never spends it.
    """
    if target is None:
        return
    for subject, spec in ((ctx.actor, actor_check), (target, target_check)):
        if subject is None or spec.get("kind") == "save":
            continue
        if _names_bad_read(spec.get("ability"), spec.get("skill")):
            _spend_bad_read(ctx.engine, subject, ctx.source)


@hook("event")
def laughing_feint_bad_read_spent(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The bad read is spent by the check it names, taken or observed; a mode query alone never spends it.

    Opposed checks are charged per participant by ``laughing_feint_bad_read_opposed`` above, which can see each side's
    real check; this covers the single checks -- a Search's Perception check, Break the Glass's "Wisdom (Insight)", an
    Analyze -- where the event's own label is the whole signal, read by ``_rolled_bad_read_check``. Each instance is removed
    by its own id, so two casters' bad reads are accounted for separately rather than one call ending both.
    """
    if event_type != "CHECK_ROLLED":
        return
    payload = kwargs.get("payload") or {}
    if payload.get("roll_kind") == "opposed_check":
        return
    if (payload.get("actor") or {}).get("natural_result") is None:
        return
    if not _rolled_bad_read_check(payload):
        return
    subject = engine.state.actors.get(kwargs.get("actor_id") or "")
    if subject is not None:
        _spend_bad_read(engine, subject, None)


# Reviewed A2DRUNK marker opts in; saved modifiers keep their sealed behavior.
AFTERIMAGE = "TAL_DRUNKEN_STYLE_AFTERIMAGE_SWAY"
AFTERIMAGE_CONDITION = "condition:typed.drunken_afterimage"


@hook("before_attack")
def afterimage_attack(engine, attacker, defender, intent, context):
    from .. import stealth
    if any(c.condition_id == AFTERIMAGE_CONDITION and c.data.get("afterimage_v1") for c in defender.conditions.values()) \
            and engine._distance_actor_to_actor(attacker, defender) <= 30 and stealth.sees(engine, attacker, defender):
        return {"mode": "DISADVANTAGE"}


def _consume_afterimage(ctx, defender):
    from .condition_ownership import remove_instance
    notice = getattr(ctx, "attack_notice", None)
    if defender is None or (getattr(ctx, "attack_result", None) is None and not getattr(notice, "roll_id", "")):
        return
    for c in list(defender.conditions.values()):
        if c.condition_id == AFTERIMAGE_CONDITION and c.data.get("afterimage_v1"):
            remove_instance(ctx.engine, defender, c.instance_id, ctx.source)

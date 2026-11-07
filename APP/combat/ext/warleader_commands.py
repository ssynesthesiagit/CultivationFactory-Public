"""Warleader Command Responses and the Momentum-spending talents (sys-resources-states 2026-09-29, the second half of the Warleader
Sphere; the Standards, Shouts and Momentum Marks themselves are combat/ext/warleader.py and warleader_shouts.py).

Source (owner text, authority/typed_mechanics/rules_text.json WARLEADER_BASE_COMMAND_RESPONSES and tianxia.talent.warleader.*; the
Sphere has no Spheres 5e or D&D 5.5e counterpart):
  Command Responses: spending a Momentum Mark is not an Action; only one Command Response per round; "the target must be within
  Command Range and able to perceive your command"; not magical. Step on My Count (a Commanded ally you can see starts its turn,
  ends its turn, or is missed by an attack roll: it moves 5 feet without provoking Opportunity Attacks from one creature you can
  see, through no occupied space or terrain it could not enter). Brace the Line (a Commanded ally you can see is hit by an attack
  roll or fails a Dexterity or Constitution saving throw against an effect that deals damage: the triggering damage is reduced by
  Proficiency Bonus + key ability modifier; a hit that would miss after +2 AC misses instead). Strike on My Count (a Commanded ally
  you can see hits: add your Proficiency Bonus to one damage roll from that attack).
  Talents: Court of Moving Banners (Domain, a minute: Command Range = 60 feet, a Standard held without a Bonus Action, +1 extra
  Momentum Mark per gain, one Command Response per round free), Imperial Mandate of the Living Line (in the Court: Frightened
  immunity while the ally sees or hears you, a free Response once a round when a Commanded ally fails a save, Step 10 feet, Strike
  twice PB), Legion Unending (Standard: 1 Momentum Mark as a Reaction on a Commanded ally who would drop to 0 gives it 2 x CL
  Temporary HP before the damage, gone at the start of your next turn; or 1 Martial Focus instead of the Reaction, ending the
  Standard afterwards), Master's Presence (a Commanded ally starting its turn within 5 feet: Temporary HP = PB, Advantage on the
  next Charmed/Frightened save, or its Frightened ends if the source is a lower CL; once a round per creature), Ordered Retreat
  (an ally Disengages: 1 Momentum Mark; spend 1 more to let an adjacent Commanded ally move 10 feet without Opportunity Attacks),
  Quick Commands (1 Martial Focus: the Standard lasts a minute, or a Shout as a Bonus Action -- the second is warleader_shouts.py),
  and the three rerolls: Coordinated Reflexes, Fortifying Phalanx and Militant Will let the leader spend 1 Momentum Mark so a
  Commanded ally who fails such a save rerolls it and keeps the new roll.
  Talents automated here (AUTO71, 2026-10-05): General's Soul-Standard (CL 15+, once a long rest: at 0 Hit Points but not killed
  outright, spend 1 Martial Focus and every Momentum Mark and stay conscious until the end of your next turn; no healing but a
  feature that restores you from 0 Hit Points; Set the Standard with no Bonus Action; one free Command Response; Unconscious at the
  end of your next turn), the Court's "a Commanded ally that drops to 0 Hit Points inside the Domain may fall Prone and move 5 feet
  before falling Unconscious", Reactive Position (two adjacent Commanded allies swap places on an attack roll or forced movement,
  no Opportunity Attack, and the attack misses if its original target ends up out of reach or range) and Battlefield Coordination
  (1 Momentum Mark: the ally ignores one named source of Disadvantage on that attack roll).
Readings the text does not settle (each a judgment; the report lists them):
  * The leader is a Commanded ally of its own Standards but is not the target of a Command Response ("Commanded ally you can see").
  * Every "Command" talent that spends a Momentum Mark (the three rerolls, Ordered Retreat's second half) shares the one Response
    a round. Court's free Response is that one Response made free (it is "one per round without spending a Momentum Mark").
    Imperial Mandate's Response is an extra one, usable only when a Commanded ally fails a saving throw, and is taken first.
    The Soul-Standard's free Response is available once more on top of the round's own, because the printed line is "you may use
    one Command Response without spending Momentum" rather than "instead of the one you have".
  * Only a Standard the leader holds as its primary counts for a Response ("a secondary ... cannot trigger ... Command Responses").
  * The engine picks the square for Step and Ordered Retreat: toward the nearest foe when the ally is not in reach of one at the start
    of its turn, to fewer adjacent foes otherwise, never leaving the reach of a second foe (the one exempt creature is the first).
  * The built-in AI uses a Response only when it visibly pays (a real move, a hit that turns into a miss, a Brace that is fully used,
    Strike on any hit); a player's leader set to Ask me is asked once per moment (combat/tabletop_service.py _ASK_MOMENTS). A
    turn boundary has no attack in progress, so an Ask me leader is not asked at turn starts and ends (it is, on an attack).
  * "Lower CL" for Master's Presence is a lower Proficiency Bonus (the engine keeps no other CL of a creature).
  * "You remain conscious" is the engine's CONSCIOUS-at-0-HP state, so a hit of at least the leader's Hit Point maximum still kills
    outright ("but not killed outright") and further damage at 0 Hit Points still counts.
  * Reactive Position's swap is a forced move for each ally, which is what "does not provoke Opportunity Attacks" means; the leader
    chooses the partner when more than one Commanded ally stands beside the target (a labelled menu for a player at the table,
    the first eligible ally for a fighter the table plays). "Two Commanded allies" means both creatures, including the original
    target, are Commanded, and the leader is Commanded by its own Standard, so it may be the partner.
  * Reactive Position's forced-movement half: the swap happens before a forced step (forced_movement_attempt) and stops that
    forced move, because the two creatures have already left the squares it was aimed at. The printed text only says they swap.
  * Battlefield Coordination masks a condition for one attack roll, and only the named creature's own attack-roll sources
    (attacks_have) are nameable -- attacks_others_have describes other creatures' attacks and check_mode an ability check, so
    neither is a source of Disadvantage on this roll. A source of Disadvantage the table keeps somewhere other than a condition
    (a field, a printed flat penalty) cannot be named, so those rolls are left alone.
Plug-in surface: hooks hit_response and damage_pending (typed_reactions.on_attack_hit / on_damage), condition_immune
(typed_executor.condition_immune), event, turn_start, turn_end, after_hit, after_miss, after_save, technique_used, attack_resolved,
compile_actions, candidate_allowed, ai_candidate_allowed, zero_hp, healing_pending, before_attack, forced_movement_attempt,
masked_conditions, roll_context_end; effect types warleader_court and warleader_extend. The two "choose" menus (Reactive
Position's partner, Battlefield Coordination's source) travel through warleader.choose and the choice_options hook of
warleader.py, in that module's own choice:warleader. namespace.
Not automated, and the hook each needs: Recall Spirit and Unending Loyalty (a revive event in gate3_reducer), the saving-throw and
ability-check halves of Battlefield Coordination (the Disadvantage sources of a save are gathered inside the locked
gate2_engine._roll_save, which no plug-in may mask), Coordinated Aid (the engine has no Help action), Army Moves as One (a
Commanded ally's own Action list would have to carry a menu of reactions) and Command the Gap (a second Opportunity Attack in one
move needs the locked opportunity-attack loop).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from . import warleader as wl

BASE = "tianxia.talent.warleader."
RESPONSES = "WARLEADER_BASE_COMMAND_RESPONSES"
RESPONSE_KEY = "once_per_round:wl_response"  # holds the round number it was last used in (a key that survives the turn's reset)
MANDATE_KEY = "once_per_round:wl_mandate"
MASTER_KEY = "once_per_round:wl_master"
LEGION = "condition:typed.warleader_legion"
FRIGHTENED = "condition:typed.frightened"
SOUL = "condition:typed.warleader_soul_standard"
SOUL_MARK = wl.once_marker("soul_standard")  # "Use General's Soul-Standard once per long rest" (once per fight here)
SOUL_SOURCE = "warleader:general_s_soul_standard"
SOUL_ACTION = "soul_standard"  # the extension action's id suffix: Set the Standard with no Bonus Action
_LEGACY_SOUL_RESPONSE = "wl_soul_response"  # the base build's turn flag: a Soul-Standard window's one free Command Response
_GAP_KEY = "_wl_command_the_gap"  # transient: the creature Command the Gap has already answered this turn
_PAID = {"momentum": "1 Momentum Mark", "court": "free in the Court", "mandate": "free by Imperial Mandate", "soul": "free by General's Soul-Standard"}
# Battlefield Coordination names one source of Disadvantage to set aside for one roll. The paid frame is
# transient engine state because the payment (before_attack) and the answer (masked_conditions) are different
# hooks, and it is scoped to the roll it paid for: it records the d20 attack frame the payment ran inside, is
# only honoured while that exact frame is the current one, and is dropped by roll_context_end when the frame
# exits -- so a second attack, a nested attack, a failed roll, a cancelled preview and a reloaded fight all
# find no mask, and none of them can keep a benefit nobody paid for.
_ALIGN_FRAME = "_wl_coordination_frame"


# ------------------------------------------------------------------------------------------------------ who may respond
def _round(engine: Any) -> int:
    return int(engine.state.round_number)


def _numbers(engine: Any, leader: Any, talent: str = "command_responses") -> dict[str, Any]:
    for row in wl.rows(engine, leader, "warleader_known"):
        if row.get("talent") == talent and row.get("numbers"):
            return row["numbers"]
    return {"pb": wl.proficiency(leader), "key_mod": 0, "cl": 1}


def _mandate_on(engine: Any, leader: Any) -> bool:
    return wl.court_of(leader) is not None and wl.knows(engine, leader, "imperial_mandate_of_the_living_line")


def _kind(engine: Any, leader: Any, failed_save: bool) -> str | None:
    """How this leader could pay for a Response now: the Soul-Standard's free one, the Mandate's free one (only on a failed
    save, once a round, on top of the round's own), Court's free one, or a Momentum Mark; None when it has used its Response
    this round or has nothing to pay with."""
    if failed_save and _mandate_on(engine, leader) and leader.turn_flags.get(MANDATE_KEY) != _round(engine):
        return "mandate"
    if leader.turn_flags.get(RESPONSE_KEY) == _round(engine):
        return "soul" if _soul_free(engine, leader) else None
    if _soul_free(engine, leader):
        return "soul"  # General's Soul-Standard: "you may use one Command Response without spending Momentum"
    if wl.court_of(leader) is not None:
        return "court"
    return "momentum" if leader.resources.get(wl.MOMENTUM, 0) >= 1 else None


def options(engine: Any, ally: Any, *, failed_save: bool = False) -> list[tuple[Any, dict[str, Any], str]]:
    """The leaders who could give ``ally`` a Command Response right now: Commanded by them, seen by them, not themselves."""
    found = []
    if not ally.active:
        return found
    for leader, data in sorted(wl.leaders(engine), key=lambda pair: pair[0].entity_id):
        if leader.entity_id == ally.entity_id or not wl.knows(engine, leader, "command_responses") or not wl.commanded(engine, leader, data, ally):
            continue
        if not engine._line_of_sight_actor_to_actor(leader, ally):
            continue
        kind = _kind(engine, leader, failed_save)
        if kind is not None:
            found.append((leader, data, kind))
    return found


def _use(engine: Any, leader: Any, kind: str, checkpoint: str) -> bool:
    """Ask a player's leader (Ask me), then pay: the Response is used up for the round and a Momentum Mark spent unless free."""
    from .. import typed_reactions

    if not typed_reactions._consent(engine, {"feature_id": RESPONSES, "ask": True}, leader, checkpoint):
        return False
    if kind == "mandate":
        leader.turn_flags[MANDATE_KEY] = _round(engine)
    elif kind == "soul":
        _soul_spend_response(engine, leader)  # "you may use one Command Response without spending Momentum"
    else:
        leader.turn_flags[RESPONSE_KEY] = _round(engine)
        if kind == "momentum":
            wl.spend_momentum(engine, leader, "warleader:command_response")
    return True


# ------------------------------------------------------------------------------------------------------ moving an ally
def _adjacent_foes(engine: Any, ally: Any, cell: Any) -> set[str]:
    return {other.entity_id for other in engine.state.actors.values()
            if other.active and other.team_id != ally.team_id and engine._distance_actor_to_actor(ally, other, actor_position=cell) <= 5}


def _plan_move(engine: Any, ally: Any, feet: int, mode: str, *, exempt: int | None) -> tuple[Any, list[Any]] | None:
    """The best square within ``feet`` (square by square, around anything that blocks, never through an occupied space) and its path, or
    None when nothing is better than where it stands: ``mode`` "approach" gets nearer to the nearest foe, "shelter" faces fewer foes.
    A path that leaves the reach of more than ``exempt`` foes is out (the order exempts one; the rest would provoke and nothing here
    fires Opportunity Attacks); ``exempt`` None allows any."""
    from ..gate2_runtime_models import Position
    from .frightened_movement import path_allowed

    foes = [other for other in engine.state.actors.values() if other.active and other.team_id != ally.team_id]
    if not foes:
        return None

    def score(cell: Any) -> int:
        if mode == "approach":
            return min(engine._distance_actor_to_actor(ally, foe, actor_position=cell) for foe in foes)
        return len(_adjacent_foes(engine, ally, cell))

    here = score(ally.position)
    if (mode == "shelter" and here == 0) or (mode == "approach" and _adjacent_foes(engine, ally, ally.position)):
        return None
    occupied, footprint, start = engine._occupied_cells_except(ally.entity_id), engine._footprint(ally), ally.position
    came: dict[tuple[int, int], tuple[int, int] | None] = {(start.x, start.y): None}
    frontier = [start]
    for _ in range(feet // engine.grid.square_size_ft):
        grown = []
        for cell in frontier:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    x, y = cell.x + dx, cell.y + dy
                    if not (dx or dy) or (x, y) in came or not (0 <= x < engine.grid.width and 0 <= y < engine.grid.height):
                        continue
                    step = Position(x=x, y=y)
                    if engine.grid.step_legal(cell, step, occupied_cells=occupied, footprint=footprint):
                        came[(x, y)] = (cell.x, cell.y)
                        grown.append(step)
        frontier = grown
    best: tuple[Any, Any, list[Any]] | None = None
    for key in came:
        if came[key] is None:
            continue
        path, walk = [], key
        while walk is not None:
            path.append(Position(x=walk[0], y=walk[1]))
            walk = came[walk]
        path.reverse()
        if not path_allowed(engine, ally, path):
            continue
        if exempt is not None:
            left = set()
            for before, after in zip(path, path[1:]):
                left |= _adjacent_foes(engine, ally, before) - _adjacent_foes(engine, ally, after)
            if len(left) > exempt:
                continue
        cell = path[-1]
        rank = (score(cell), len(path), key)
        if rank[0] < here and (best is None or rank < best[0]):
            best = (rank, cell, path)
    return (best[1], best[2]) if best is not None else None


def _move(engine: Any, ally: Any, plan: tuple[Any, list[Any]], source: str) -> None:
    from .. import zones

    destination, path = plan
    start = ally.position
    ally.position = destination
    engine._append_event("MOVEMENT_COMMITTED", source, actor_id=ally.entity_id,
                         payload={"destination": destination.model_dump(mode="json"), "path": [step.model_dump(mode="json") for step in path],
                                  "cost_ft": 0, "forced": False, "reaction": True})
    zones.on_moved(engine, ally, start, destination)


def _step(engine: Any, ally: Any, when: str) -> None:
    """Step on My Count at the start or end of a Commanded ally's turn, or after an attack missed it."""
    found = options(engine, ally)
    if not found:
        return
    leader, _, kind = found[0]
    feet = 10 if _mandate_on(engine, leader) else 5  # Imperial Mandate: "the ally moves 10 feet instead of 5 feet"
    plan = _plan_move(engine, ally, feet, "approach" if when == "start" else "shelter", exempt=1)
    if plan is None or not _use(engine, leader, kind, f"COMMAND_STEP_{when.upper()}"):
        return
    _move(engine, ally, plan, "warleader:step_on_my_count")
    note(engine, "warleader:step_on_my_count", leader, f"{leader.display_name} calls Step on My Count ({_PAID[kind]}): {ally.display_name} moves {feet} feet "
                                                       "without provoking Opportunity Attacks.", (ally,))


@hook("turn_start")
def turn_started(engine: Any, actor: Any) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, "_wl_brace")
    engine.__dict__.pop("_wl_brace", None)
    if actor.active:
        _step(engine, actor, "start")
        _master_presence(engine, actor)


@hook("turn_end")
def turn_ended(engine: Any, actor: Any) -> None:
    if actor.active:
        _step(engine, actor, "end")


@hook("after_miss")
def missed(ctx: Any, target: Any) -> None:
    if target.team_id != ctx.actor.team_id and target.active:
        _step(ctx.engine, target, "missed")


# ------------------------------------------------------------------------------------------------------ Strike on My Count
def _last_damage_type(engine: Any, target: Any) -> str:
    return next((str((event.payload or {}).get("damage_type") or "UNTYPED") for event in reversed(engine.events[-12:])
                 if event.event_type == "DAMAGE_COMMITTED" and target.entity_id in (event.target_ids or ())), "UNTYPED")


@hook("after_hit")
def strike(ctx: Any, target: Any, kind: str) -> None:
    """Strike on My Count: the leader's Proficiency Bonus (twice, in the Court with Imperial Mandate) on the hit, dealt as a packet of the
    attack's own damage type, as every other on-hit bonus is (typed_executor._on_hit_bonuses)."""
    from .. import typed_executor as te

    engine, ally = ctx.engine, ctx.actor
    if ctx.damage_cache.get("_bonus") or target.team_id == ally.team_id or not target.active:
        return
    found = options(engine, ally)
    if not found:
        return
    leader, _, how = found[0]
    amount = wl.proficiency(leader) * (2 if _mandate_on(engine, leader) else 1)
    if amount < 1 or not _use(engine, leader, how, "COMMAND_STRIKE"):
        return
    note(engine, "warleader:strike_on_my_count", leader, f"{leader.display_name} calls Strike on My Count ({_PAID[how]}): {ally.display_name}'s hit adds {amount} damage.", (target,))
    te._deal(te.Context(engine, ally, ctx.action, ctx.intent, ctx.typed, [target], target, {"_potency_used": True, "_bonus": True}),
             target, amount, _last_damage_type(engine, target))


# ------------------------------------------------------------------------------------------------------ Brace the Line
@hook("hit_response")
def brace_the_hit(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> dict[str, Any] | None:
    """A hit on a Commanded ally: it opens the window in which the damage that follows can be braced, and a hit that would miss after
    +2 AC is turned into a miss now (a natural 20 hits whatever the AC)."""
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, "_wl_brace")
    if target.team_id == attacker.team_id:
        return None
    engine._wl_brace = {**(getattr(engine, "_wl_brace", None) or {}), target.entity_id: "hit"}
    if natural >= int(spec.get("critical_threshold", 20)) or total >= effective_ac + 2:
        return None
    found = options(engine, target)
    if not found:
        return None
    leader, _, kind = found[0]
    if not _use(engine, leader, kind, "COMMAND_BRACE"):
        return None
    engine._wl_brace.pop(target.entity_id, None)
    note(engine, "warleader:brace_the_line", leader, f"{leader.display_name} calls Brace the Line ({_PAID[kind]}): with +2 AC {target.display_name} is missed instead.", (attacker,))
    return {'armor_class': effective_ac + 2, 'hit': False, 'miss_reason': 'armor_class'}


def _damage_row(ctx: Any) -> bool:
    from .. import typed_executor as te

    return any(row.get("type") == "damage" for row in te._walk_rows(ctx.typed.get("effects") or []))


def _last_save(engine: Any, subject: Any) -> dict[str, Any] | None:
    return next(((event.payload or {}) for event in reversed(engine.events[-40:])
                 if event.event_type == "SAVE_ROLLED" and event.actor_id == subject.entity_id and (event.payload or {}).get("dc") is not None), None)


_REROLLS = (("coordinated_reflexes", lambda ctx, ability, named: ability == "DEX" and bool((ctx.typed.get("area") or {}).get("size_ft")), True),
            ("fortifying_phalanx", lambda ctx, ability, named: ability == "CON", True),
            ("militant_will", lambda ctx, ability, named: bool(named & {"charmed", "frightened"}), False))


@hook("after_save")
def failed_save(ctx: Any, subject: Any, ability: str, named: set[str], failed: bool) -> None:
    """A Commanded ally fails a save: the leader's reroll talent (Coordinated Reflexes, Fortifying Phalanx, Militant Will) may spend a Momentum
    Mark to roll it again (the new roll counts, and a success after it is a Momentum Mark); what fails still can be braced when it
    is a Dexterity or Constitution save against damage."""
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_wl_brace")
    engine = ctx.engine
    if not failed or not subject.active or subject.team_id == ctx.actor.team_id:
        return
    for standard, applies, needs_neighbour in _REROLLS:
        if not applies(ctx, ability, named):
            continue
        eligible = {leader.entity_id for leader, data in wl.commanders(engine, subject, standard, primary_only=True)
                    if not needs_neighbour or wl.adjacent_commanded(engine, leader, data, subject)}
        for leader, _, kind in options(engine, subject, failed_save=True):
            if leader.entity_id in eligible and _reroll(ctx, subject, ability, leader, kind, standard):
                break
        if (getattr(engine, "_typed_roll_outcome", None) or {}).get(subject.entity_id) is not None:
            break
    if ability in ("DEX", "CON") and _damage_row(ctx) and (getattr(engine, "_typed_roll_outcome", None) or {}).get(subject.entity_id) != "success":
        engine._wl_brace = {**(getattr(engine, "_wl_brace", None) or {}), subject.entity_id: "save"}


def _reroll(ctx: Any, subject: Any, ability: str, leader: Any, kind: str, standard: str) -> bool:
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_typed_roll_outcome")
    engine = ctx.engine
    rolled = _last_save(engine, subject)
    if rolled is None or not _use(engine, leader, kind, "COMMAND_REROLL"):
        return False
    dc = int(rolled["dc"])
    mode = rolled.get("mode") if rolled.get("mode") in ("ADVANTAGE", "DISADVANTAGE") else None
    fresh = engine._roll_save(subject, ability, dc, ctx.source, extra_mode=mode)
    failed = fresh.total < dc
    engine._typed_roll_outcome = {**(getattr(engine, "_typed_roll_outcome", None) or {}), subject.entity_id: "failure" if failed else "success"}
    name = wl.STANDARDS[standard][0]
    note(engine, f"warleader:{standard}", leader, f"{leader.display_name} lets {subject.display_name} reroll the {ability} save ({name}, {_PAID[kind]}): "
                                                   f"{rolled.get('total')} -> {fresh.total} against DC {dc}; " + ("it still fails." if failed else "it succeeds."), (subject,))
    if not failed:
        wl.gain_momentum(engine, leader, subject, f"succeeded on a {name} reroll")
    return True


@hook("damage_pending")
def pending_damage(engine: Any, target: Any, pending: int, source_definition_id: str, source_actor_id: str | None) -> int:
    """Brace the Line's reduction (the first damage after the hit or failed save that opened its window), then Legion Unending's Temporary HP
    before a drop to 0 Hit Points."""
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, "_wl_brace")
    window = (getattr(engine, "_wl_brace", None) or {}).pop(target.entity_id, None) if pending > 0 else None
    if window:
        for leader, _, kind in options(engine, target, failed_save=window == "save"):
            reduction = max(0, wl.proficiency(leader) + int(_numbers(engine, leader).get("key_mod") or 0))
            # A Response spent on a reduction it cannot fully use is a Momentum Mark wasted.
            if reduction < 1 or pending < reduction or not _use(engine, leader, kind, "COMMAND_BRACE"):
                continue
            note(engine, "warleader:brace_the_line", leader, f"{leader.display_name} calls Brace the Line ({_PAID[kind]}): {target.display_name} takes {reduction} less damage.", (target,))
            from .attack_reduction import remember
            pending = remember(engine, target, pending, pending - reduction, [(reduction, ())])
            break
    return _legion(engine, target, pending)


# ------------------------------------------------------------------------------------------------------ Legion Unending
def _legion(engine: Any, target: Any, pending: int) -> int:
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, "_wl_end_standard")
    preserve_pending(engine, "_wl_legion")
    from .. import typed_reactions

    if pending < 1 or pending < target.current_hp + target.temporary_hp:
        return pending
    for leader, data in wl.commanders(engine, target, "legion_unending", primary_only=True):
        if leader.resources.get(wl.MOMENTUM, 0) < 1:
            continue
        by_reaction = typed_reactions._can_react(engine, leader)
        if not by_reaction and leader.resources.get(wl.FOCUS, 0) < 1:
            continue
        amount = 2 * int(_numbers(engine, leader).get("cl") or 1)
        if pending < target.current_hp + max(target.temporary_hp, amount):
            pass  # it would keep the ally up
        else:
            continue  # it would not: a Momentum Mark for nothing
        if not typed_reactions._consent(engine, {"feature_id": BASE + "legion_unending", "ask": True}, leader, "LEGION_UNENDING"):
            continue
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, leader, "warleader:legion_unending", independent=True):
            wl.spend_momentum(engine, leader, "warleader:legion_unending")
            if by_reaction:
                leader.reaction_available = False
            else:
                engine._spend_resource(leader, wl.FOCUS, 1, "warleader:legion_unending")
                from ..paid_relocation import capture, retain
                retain(engine, ("warleader_end_standard", leader.entity_id), capture(engine))
                engine._wl_end_standard = leader.entity_id  # "doing so ends the active Standard after the triggering effect resolves"
            engine._grant_temp_hp(target, amount, "warleader:legion_unending", leader.entity_id)
            engine._wl_legion = {**(getattr(engine, "_wl_legion", None) or {}), target.entity_id: amount}
            engine._apply_condition(target, LEGION, "warleader:legion_unending", leader.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                    data={"legion": {"amount": amount}, "label": f"Legion Unending: {amount} Temporary HP",
                                          "reading": f"{amount} Temporary HP (twice the leader's CL) given before the damage; they vanish at the start of {leader.display_name}'s next turn."})
            note(engine, "warleader:legion_unending", leader, f"{leader.display_name} spends 1 Momentum Mark on Legion Unending ({'Reaction' if by_reaction else '1 Martial Focus, no Reaction'}): "
                                                                f"{target.display_name} gains {amount} Temporary HP before the damage.", (target,))
            return pending
    return pending


@hook("event")
def events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, "_wl_legion")
    payload = kwargs.get("payload") or {}
    if event_type == "CONDITION_REMOVED" and payload.get("condition_id") == LEGION:
        holder = engine.state.actors.get((kwargs.get("target_ids") or (None,))[0] or "")
        amount = (getattr(engine, "_wl_legion", None) or {}).pop(holder.entity_id, None) if holder is not None else None
        if holder is not None and holder.active and amount is not None and 0 < holder.temporary_hp <= amount:
            before, holder.temporary_hp = holder.temporary_hp, 0  # "These Temporary HP vanish at the start of your next turn."
            engine._append_event("TEMP_HP_GRANTED", "warleader:legion_unending", actor_id=holder.entity_id, target_ids=(holder.entity_id,),
                                 payload={"offered": 0, "before": before, "after": 0})
            note(engine, "warleader:legion_unending", holder, f"{holder.display_name}'s Legion Unending Temporary HP vanish.")
    elif event_type == "INTENT_ACCEPTED" and engine.events and engine.events[-1].source_definition_id == "system:combat.disengage":
        _ordered_retreat(engine, engine.state.actors.get(kwargs.get("actor_id") or ""))


@hook("technique_used")
def window_closed(ctx: Any) -> None:
    _close_windows(ctx.engine)


@hook("attack_resolved")
def attack_over(ctx: Any, target: Any, hit: bool, effect_row: dict[str, Any]) -> None:
    _close_windows(ctx.engine)


def _close_windows(engine: Any) -> None:
    """The damage a hit or a failed save opened a Brace window for is dealt by now; a Legion Unending paid for with Martial Focus ends
    the Standard now that the triggering effect has resolved."""
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, "_wl_brace")
    preserve_pending(engine, "_wl_end_standard")
    engine.__dict__.pop("_wl_brace", None)
    leader = engine.state.actors.get(engine.__dict__.pop("_wl_end_standard", None) or "")
    if leader is not None and wl.standard_of(leader):
        from ..paid_relocation import causal_scope, take
        with causal_scope(engine, take(engine, ("warleader_end_standard", leader.entity_id))):
            engine._remove_condition(leader, wl.CONDITION, "warleader:legion_unending")
            note(engine, "warleader:legion_unending", leader, f"{leader.display_name}'s Standard ends (Legion Unending paid with Martial Focus).")


# ------------------------------------------------------------------------------------------------------ Ordered Retreat
def _ordered_retreat(engine: Any, ally: Any | None) -> None:
    if ally is None or not ally.active:
        return
    for leader, data in sorted(wl.leaders(engine), key=lambda pair: pair[0].entity_id):
        if leader.entity_id == ally.entity_id or not wl.knows(engine, leader, "ordered_retreat") or not wl.commanded(engine, leader, data, ally):
            continue
        wl.gain_momentum(engine, leader, ally, f"{ally.display_name} Disengaged (Ordered Retreat)")
        kind = _kind(engine, leader, False)
        if kind is None:
            continue
        for neighbour in sorted(engine.state.actors.values(), key=lambda other: other.entity_id):
            if neighbour.entity_id in (ally.entity_id, leader.entity_id) or not neighbour.active or neighbour.team_id != leader.team_id \
                    or engine._distance_actor_to_actor(ally, neighbour) > 5 or not wl.commanded(engine, leader, data, neighbour):
                continue
            plan = _plan_move(engine, neighbour, 10, "shelter", exempt=None)
            if plan is None or not _use(engine, leader, kind, "COMMAND_RETREAT"):
                continue
            _move(engine, neighbour, plan, "warleader:ordered_retreat")
            note(engine, "warleader:ordered_retreat", leader, f"{leader.display_name} calls the retreat ({_PAID[kind]}): {neighbour.display_name} moves 10 feet without "
                                                              "provoking Opportunity Attacks.", (neighbour,))
            break


# ------------------------------------------------------------------------------------------------------ Master's Presence
_MASTER_ASKS = (("remove_fear", "MASTER_REMOVE_FEAR"), ("temp_hp", "MASTER_TEMP_HP"), ("advantage", "MASTER_ADVANTAGE"))


def _frightening(engine: Any, actor: Any, leader: Any) -> bool:
    """A Frightened condition whose source is a lower CL than the leader (a lower Proficiency Bonus stands in for it)."""
    for condition in actor.conditions.values():
        source = engine.state.actors.get(condition.source_actor_id or "")
        if condition.condition_id == FRIGHTENED and source is not None and wl.proficiency(source) < wl.proficiency(leader):
            return True
    return False


def _master_presence(engine: Any, ally: Any) -> None:
    from .. import typed_executor as te
    from .. import typed_reactions

    for leader, data in sorted(wl.leaders(engine), key=lambda pair: pair[0].entity_id):
        if leader.entity_id == ally.entity_id or not wl.knows(engine, leader, "master_s_presence") or not wl.commanded(engine, leader, data, ally):
            continue
        if engine._distance_actor_to_actor(leader, ally) > 5 or ally.turn_flags.get(MASTER_KEY) == _round(engine):
            continue
        pb = wl.proficiency(leader)
        choices = [(kind, checkpoint) for kind, checkpoint in _MASTER_ASKS
                   if (kind == "remove_fear" and wl.perceives(engine, leader, ally) and _frightening(engine, ally, leader))
                   or (kind == "temp_hp" and ally.temporary_hp < pb) or kind == "advantage"]
        row = {"feature_id": BASE + "master_s_presence", "ask": True}
        pick = next((kind for kind, checkpoint in choices if typed_reactions._consent(engine, row, leader, checkpoint)), None)
        if pick is None:
            continue
        ally.turn_flags[MASTER_KEY] = _round(engine)  # "A creature can benefit from Master's Presence once per round."
        if pick == "temp_hp":
            engine._grant_temp_hp(ally, pb, "warleader:master_s_presence", leader.entity_id)
            said = f"{pb} Temporary HP"
        elif pick == "remove_fear":
            engine._remove_condition(ally, FRIGHTENED, "warleader:master_s_presence")
            said = "its Frightened condition ends"
        else:
            engine._apply_condition(ally, "condition:typed.save_against", "warleader:master_s_presence", leader.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                    data={"rule": {"save_against": {"mode": "ADVANTAGE", "against": te._save_against_keys("saving throws against charmed and frightened"),
                                                                    "abilities": [], "next": True}},
                                          "label": "Advantage on the next save against Charmed or Frightened (Master's Presence)"})
            said = "Advantage on the next save against Charmed or Frightened"
        note(engine, "warleader:master_s_presence", leader, f"Master's Presence: {ally.display_name} begins its turn beside {leader.display_name} and gains {said}.", (ally,))
        return


# ------------------------------------------------------------------------------------------------------ Court of Moving Banners
def _restand(engine: Any, leader: Any, source: str, expiry: str, *, extended: bool = False) -> None:
    """Put the leader's Standard back with a longer life (the condition's expiry cannot be edited in place)."""
    condition = next((held for held in leader.conditions.values() if held.condition_id == wl.CONDITION), None)
    if condition is None:
        return
    data = {**condition.data}
    if extended:
        data["warleader"] = {**data["warleader"], "extended": True}
    engine._remove_condition(leader, wl.CONDITION, source)
    engine._apply_condition(leader, wl.CONDITION, source, leader.entity_id, expires_on=expiry, data=data)


@effect("warleader_court")
def court(ctx: Any, eff: dict[str, Any]) -> None:
    """Warleader Domain: Court of Moving Banners, a minute (the end of the leader's tenth turn from now). The Standard held now is held for the
    whole Domain; Standards set inside it are too (warleader.set_standard)."""
    engine, leader = ctx.engine, ctx.actor
    expiry = f"END_OF_SOURCE_TURN_AT:{leader.turns_started + 10}"
    engine._apply_condition(leader, wl.COURT, ctx.source, leader.entity_id, expires_on=expiry,
                            data={"label": "Court of Moving Banners",
                                  "reading": "Command Range is the 60-foot Domain; one Standard is held with no Bonus Action; each Momentum Mark gained is doubled (up to the "
                                             "maximum); one Command Response a round is free; an Imperial Mandate adds its powers."})
    _restand(engine, leader, ctx.source, expiry)
    note(engine, ctx.source, leader, f"{leader.display_name} raises the Court of Moving Banners (60-foot Domain, a minute).")


@effect("warleader_extend")
def extend(ctx: Any, eff: dict[str, Any]) -> None:
    """Quick Commands: the Standard lasts a minute, and ends if the leader is Incapacitated (warleader.py, on the condition event)."""
    engine, leader = ctx.engine, ctx.actor
    if wl.standard_of(leader) is None:
        ctx.rider("No Standard is set to extend.")
        return
    _restand(engine, leader, ctx.source, f"END_OF_SOURCE_TURN_AT:{leader.turns_started + 10}", extended=True)
    note(engine, ctx.source, leader, f"{leader.display_name}'s Standard now lasts a minute (Quick Commands).")


EXTEND = "quick_commands_extend"


@hook("compile_actions")
def extension_action(info: dict[str, Any]) -> list[Any] | None:
    """Quick Commands' second option as an action of its own: 1 Martial Focus, no Action of any kind; offered to a player only."""
    if BASE + "quick_commands" not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.{EXTEND}", display_name="Quick Commands: the Standard lasts a minute (1 Martial Focus)",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF", costs=((wl.FOCUS, 1),),
        parameters={"typed": {"effects": [{"type": "warleader_extend", "applies_to": "self",
                                           "evidence": "Quick Commands: make your current Standard last for 1 minute."}],
                              "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True})]


@hook("candidate_allowed")
def extension_legal(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is not None and action.source_definition_id.endswith("." + EXTEND):
        held = wl.standard_of(actor)
        return bool(held) and not held.get("extended")
    return None


@hook("ai_candidate_allowed")
def restraint(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The built-in AI does not raise a second Court while one runs."""
    if action is not None and any(isinstance(row, dict) and row.get("type") == "warleader_court"
                                  for row in ((action.parameters or {}).get("typed") or {}).get("effects") or []):
        return wl.court_of(actor) is None
    return None


def _mandate_frightened_immune(engine: Any, actor: Any) -> Any | None:
    """Imperial Mandate's Frightened immunity for ``actor``: the leader whose Court grants it (Commanded, and it can see or hear
    that leader), or None. Shared by the combat immunity and the Defences card, so both read the same gate."""
    return next((leader for leader, data in wl.leaders(engine)
                 if _mandate_on(engine, leader) and wl.commanded(engine, leader, data, actor) and wl.perceives(engine, leader, actor)), None)


@hook("condition_immune")
def mandate_immunity(engine: Any, actor: Any, name: str) -> bool | None:
    """Imperial Mandate: "Commanded allies are immune to Frightened while they can see or hear you" (in the Court)."""
    if name != "frightened":
        return None
    return True if _mandate_frightened_immune(engine, actor) is not None else None


@hook("defense_description")
def mandate_description(engine: Any, actor: Any) -> list[dict[str, Any]] | None:
    """Imperial Mandate's Frightened immunity, as the Defences card names it: "only while it can see or hear you, in the Court"."""
    leader = _mandate_frightened_immune(engine, actor)
    if leader is None:
        return None
    return [{"feature_id": BASE + "imperial_mandate_of_the_living_line", "conditions": ["frightened"],
             "expires_on": wl.court_of(leader).expires_on, "note": "only while it can see or hear you, in the Court"}]


# ------------------------------------------------------------------------------------------------------ General's Soul-Standard
def _printed_name(engine: Any, source_id: str) -> str:
    """The printed name of whatever a prompt is about -- a catalog action first, then the shared history naming. Never the
    internal id: a player-facing sentence gets a real printed name or nothing at all, so a source nothing resolves (an
    ad-hoc effect id, a hazard) leaves the name empty rather than printing ``action:test.whatever`` at the table."""
    from ..history_text import history_name

    source_id = str(source_id or "")
    action = (getattr(engine, "action_catalog", {}) or {}).get(source_id)
    named = str(getattr(action, "display_name", "") or "") or str(history_name(source_id, {}))
    return "" if not named or named == source_id else named


def _damage_source(engine: Any) -> str:
    """The creature whose action or effect really caused the damage being committed right now, or ``""`` when nothing in
    the fight says.

    The zero-HP seam is handed the *outer* turn's intent, which is not who is hitting this creature: a Warleader who walks
    into an enemy Blackwater zone is damaged with the zone's owner as the source creature while the mover's own intent is
    still the active one, and nested reactions carry the outer intent just the same. Naming that actor here would tell the
    player the Warleader attacked itself.

    Both answers below are the engine's own live contracts for the packet in flight, and both are read before any fall
    back to the intent, so an attack names its attacker and environmental or indirect damage names its true cause:

      * ``combat.pending_damage.current`` -- the immutable packet ``_commit_damage`` opened around this very damage, whose
        ``source_actor_id`` is the creature the caller passed as the source (the zone owner, the attacker, the caster).
      * ``engine.damage_context()`` -- the attack provenance for an attack packet, when one is open.

    A source that is not a creature in this fight (a hazard, an unresolved id) reads as unknown on purpose: the prompt then
    says "something", which is true, rather than naming a creature that did not do it.
    """
    from .. import pending_damage

    packet = pending_damage.current(engine)
    attack = engine.damage_context()
    known = getattr(getattr(engine, "state", None), "actors", None) or {}
    for candidate in (getattr(packet, "source_actor_id", None), getattr(attack, "attacker_id", None)):
        actor = str(candidate or "")
        if actor and actor in known:
            return actor
    return ""


def _incoming(engine: Any, target: Any, source_id: str, intent: Any) -> dict[str, Any]:
    """The trigger metadata for a consent prompt raised because a creature reached 0 Hit Points, naming what actually put
    it there rather than what is answering. The incoming action's printed name and the creature responsible for the damage
    in flight are what the player needs to identify the attack, spell or hazard that caused the drop; both are read from
    the engine's live damage provenance (:func:`_damage_source`), never from the outer turn's intent, which is the wrong
    creature for a zone, an aura or any nested reaction. The responding ability is named by the prompt's own printed rule
    text, so it stays separate from its cause here -- otherwise every prompt would say the creature was reduced to 0 by
    the feature reacting to it, and the Court would name its own leader as the cause of a drop that leader did not cause.

    A genuinely unknown cause names nothing: the prompt says "something" instead of substituting the creature that dropped,
    which would be a lie about who attacked."""
    actor = _damage_source(engine)
    name = _printed_name(engine, source_id or "")
    return {"actor_id": actor, "affected_id": target.entity_id, "target_id": target.entity_id,
            "source_id": source_id or "", "action_name": name,
            "cause": f"reduced to 0 Hit Points by {name or 'something'}",
            "responding_ability": "this feature"}


def _soul_response_spent(held: Any, leader: Any) -> bool:
    """Whether the window's one free Command Response is already spent, reading either shape of window a saved fight can
    carry. A window this build opened records the use in its own condition data as ``response_used`` (an integer, so it
    survives a table commit and a reload). A window saved by the base build carries no such field: its use was a turn
    flag, ``wl_soul_response``, so a fight committed while that window was open must still read as spent when it is
    loaded here -- otherwise the reload quietly hands the leader a second free Response. The new field wins whenever it
    is present, so a flag left over from an earlier turn can never override a window this build opened fresh."""
    data = getattr(held, "data", None) or {}
    if "response_used" in data:
        return int(data.get("response_used") or 0) >= 1
    return bool(leader.turn_flags.get(_LEGACY_SOUL_RESPONSE))


@hook("turn_boundary_start")
def soul_legacy_spend_keeps(engine: Any, actor: Any) -> None:
    """A window saved by the base build recorded its one free Command Response as a turn flag, ``wl_soul_response``.
    The engine discards an ordinary turn flag at the start of every turn (gate2_engine._system_start_turn), while this
    window deliberately runs *through* the end of the leader's next turn, so a fight that reloads such a window and then
    takes a real turn would find the flag cleared and hand the leader a second free Response for a window whose one had
    already been spent.

    This migrates the flag into the window's own ``response_used`` field, which is where a window this build opened keeps
    it, so the spent state crosses the turn-start reset the same way a table commit crosses a reload. It is written at the
    turn boundary -- the last moment the flag still exists -- rather than on load, so nothing is invented at reload time and
    a fight that never advances a turn is left exactly as it was committed. Inert unless the actor is running a legacy-
    format window (no ``response_used`` of its own) with the flag set: a window this build opened already carries its own
    authoritative field and is never touched, and a creature with no window does nothing at all.
    """
    held = _soul(engine, actor)
    if held is None or "response_used" in (getattr(held, "data", None) or {}):
        return
    if actor.turn_flags.get(_LEGACY_SOUL_RESPONSE):
        held.data["response_used"] = 1


def _soul_free(engine: Any, leader: Any) -> bool:
    """Whether the Soul-Standard window still carries its one free Command Response. The use is kept in the window's own
    condition data (an integer, so it survives a table commit and a reload) rather than in a turn flag: the window lasts
    through the end of the leader's next turn, and the engine discards an ordinary turn flag at the start of that turn."""
    held = _soul(engine, leader)
    return held is not None and not _soul_response_spent(held, leader)


def _soul(engine: Any, leader: Any) -> Any | None:
    return next((held for held in leader.conditions.values() if held.condition_id == SOUL), None)


def _soul_spend_response(engine: Any, leader: Any) -> None:
    """Record that the window's one free Command Response is spent, on the window itself."""
    held = _soul(engine, leader)
    if held is not None:
        held.data["response_used"] = 1


def _soul_record_rest_use(engine: Any, leader: Any) -> None:
    """"Use General's Soul-Standard once per long rest" is recorded when the window opens, so it outlives the window and
    cannot be spent twice. A window saved by the base build predates that marker, and a fight that reloads one would
    otherwise be able to use the talent again as soon as the window closed. Writing the marker when the window closes is
    what makes such a fight honest from then on, and it is inert for a window this build opened: the marker is already
    there. Marking here rather than on load keeps it to the one moment the printed rule cares about -- the end of the
    window -- with no save-time hook of its own."""
    if not wl.has_benefited(leader, "soul_standard"):
        wl.mark_benefited(engine, leader, "soul_standard", SOUL_SOURCE, "General's Soul-Standard: already used this long rest",
                          "General's Soul-Standard has been used and cannot be used again until a long rest.")


@hook("zero_hp")
def soul_standard(engine: Any, target: Any, source_id: str, intent: Any) -> str | None:
    """General's Soul-Standard: "When you are reduced to 0 Hit Points but not killed outright, you may expend Martial Focus and
    spend all Momentum Marks. You remain conscious until the end of your next turn." The engine's documented ``zero_hp`` seam is
    the one place a creature is still standing after damage reaches 0 Hit Points, so the window is opened here and the ordinary
    0-HP lifecycle is left to decide the rest: damage at 0 Hit Points still counts, and damage of at least the leader's Hit Point
    maximum still kills outright ("but not killed outright"). Expending Martial Focus is the printed price; the Marks are all of
    the leader's own. "Use General's Soul-Standard once per long rest" is a durable marker on the leader (wl.mark_benefited), so
    recovering the Focus and the Hit Points and dropping again cannot reuse it. A player at the table is asked
    when an action is in progress (typed_reactions._consent, with the trigger metadata the prompt reads). A drop with no
    action behind it (a hazard, a delayed effect) has no question to put, so the Standard is not set there: the Focus is
    kept and the leader falls Unconscious. That is Incapacitation, which ends its Momentum Marks by the printed "until you
    are Incapacitated" rule (warleader.py, CONDITION_APPLIED). A fighter the table plays decides for itself and spends them.
    """
    from .. import typed_reactions

    if not wl.knows(engine, target, "general_s_soul_standard") or not target.active or target.current_hp != 0:
        return None
    # "expend Martial Focus"; "once per long rest"; the window is already running
    if target.resources.get(wl.FOCUS, 0) < 1 or _soul(engine, target) is not None or wl.has_benefited(target, "soul_standard"):
        return None
    if not typed_reactions._consent(engine, {"feature_id": BASE + "general_s_soul_standard", "ask": True}, target, _SOUL_CHECKPOINT,
                                    trigger={**_incoming(engine, target, source_id, intent),
                                             "cost": "1 Martial Focus and every Momentum Mark"}):
        return None
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, target, SOUL_SOURCE, independent=True):
        marks = int(target.resources.get(wl.MOMENTUM, 0) or 0)
        engine._spend_resource(target, wl.FOCUS, 1, SOUL_SOURCE)
        if marks:
            engine._spend_resource(target, wl.MOMENTUM, marks, SOUL_SOURCE)
        engine._apply_condition(target, SOUL, SOUL_SOURCE, target.entity_id, expires_on=f"END_OF_SOURCE_TURN_AT:{target.turns_started + 1}",
                                data={"label": "General's Soul-Standard: conscious at 0 Hit Points", "response_used": 0,
                                      "reading": f"{target.display_name} spends 1 Martial Focus and every Momentum Mark and stays conscious at 0 Hit Points until "
                                                 f"the end of {target.display_name}'s next turn. Healing does nothing but a feature that brings a creature back from 0 Hit Points. "
                                                 f"Set the Standard costs no Bonus Action, and one Command Response is free."})
        wl.mark_benefited(engine, target, "soul_standard", SOUL_SOURCE, "General's Soul-Standard: already used this long rest",
                          "General's Soul-Standard has been used and cannot be used again until a long rest.")
        note(engine, SOUL_SOURCE, target, f"{target.display_name} uses General's Soul-Standard (1 Martial Focus"
                                          + (f" and {marks} Momentum Mark{'s' if marks != 1 else ''}" if marks else "")
                                          + f") and stays conscious at 0 Hit Points until the end of its next turn.")
        return "CONSCIOUS"


@hook("healing_pending")
def soul_standard_healing(engine: Any, subject: Any, amount: int, healer: Any, source: str, kind: str) -> int:
    """"you cannot regain Hit Points except from a feature that restores you from 0 Hit Points": while the window runs, ordinary
    healing is worth nothing. A feature that truly returns the dead (a soul_return row) still works, which is what the printed
    exception names. The log names the healing feature by its printed name, never by its internal id."""
    from ..history_text import history_name

    if kind != "hp" or amount <= 0 or _soul(engine, subject) is None:
        return 0
    action = engine.action_catalog.get(source)
    rows = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects") or []
    if any(isinstance(row, dict) and row.get("type") in {"soul_return", "revive"} for row in rows):
        return 0
    named = getattr(action, "display_name", "") or history_name(source, {source: str(source)})
    note(engine, SOUL_SOURCE, subject, f"{subject.display_name} cannot regain Hit Points from {named} (General's Soul-Standard); "
                                       "only a feature that restores it from 0 Hit Points can.")
    return amount


@hook("event")
def soul_standard_ends(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"if you are still at 0 Hit Points at the end of your next turn, you fall Unconscious normally" (and a soul-return window
    clears the flag)."""
    if event_type != "CONDITION_REMOVED" or (kwargs.get("payload") or {}).get("condition_id") != SOUL:
        return
    subject = engine.state.actors.get((kwargs.get("target_ids") or (None,))[0] or "")
    if subject is None:
        return
    _soul_record_rest_use(engine, subject)  # a window the base build saved carries no once-per-rest marker of its own
    if not subject.active or subject.current_hp > 0 or subject.life_state != "CONSCIOUS":
        return
    from . import life_state

    life_state.fall_unconscious(engine, subject, SOUL_SOURCE)
    note(engine, SOUL_SOURCE, subject, f"{subject.display_name} is still at 0 Hit Points and falls Unconscious (General's Soul-Standard).")


@hook("compile_actions")
def soul_standard_actions(info: dict[str, Any]) -> list[Any] | None:
    """"you may Set the Standard without spending a Bonus Action": one free copy of each Standard this leader knows, offered
    only while the Soul-Standard window runs. The printed window's own permission, in the same shape as Quick Commands'
    extension: a new action that costs no Action of any kind. Marked Objective keeps its printed three benefits, one button
    each, the way the compiler gives it three options."""
    if BASE + "general_s_soul_standard" not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    out = []
    for slug, (name, _text) in wl.STANDARDS.items():
        if slug != "press_the_opening" and BASE + wl.talent_of_standard(slug) not in info["owned_ids"]:
            continue
        for benefit, label in ([(None, "")] if slug != "marked_objective"
                              else [(kind, f" ({wl.OBJECTIVE_BENEFITS[kind]})") for kind in ("attack", "speed", "temp_hp")]):
            row = {"type": "warleader_standard", "standard": slug, "applies_to": "self",
                   "evidence": "General's Soul-Standard: you may Set the Standard without spending a Bonus Action."}
            if benefit is not None:
                row["benefit"] = benefit
            suffix = f".{benefit}" if benefit is not None else ""
            out.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.{SOUL_ACTION}.{slug}{suffix}",
                display_name=f"General's Soul-Standard: Set {name}{label} (no Bonus Action)",
                owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF", costs=(),
                parameters={"typed": {"effects": [row], "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []},
                            "expected_damage": 0}))
    return out


@hook("candidate_allowed")
def soul_standard_legal(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is not None and f".{SOUL_ACTION}." in action.source_definition_id:
        return _soul(engine, actor) is not None
    return None


# ------------------------------------------------------------------------------------------------------ Court's last stand
# The two zero-HP checkpoints below are this plug-in's own decision keys, so the shared moment reader has no plain words
# for them and would fall back to "<someone> just did something <target> can react to" -- a sentence that names neither the
# drop nor the action that caused it. They are spelled once, here, and used by both the consent calls and the
# decision_text hook that words their prompts.
_SOUL_CHECKPOINT = "GENERALS_SOUL_STANDARD"
_COURT_CHECKPOINT = "COURT_LAST_STAND"


def _drop_sentence(engine: Any, trigger: dict[str, Any], *, court: bool = False) -> str:
    """The sentence a player reads when asked because a creature just reached 0 Hit Points: who dropped, to what, and
    which action or effect did it. The attack is named from the trigger metadata the zero-HP hooks recorded (:func:`_
    incoming`), which reads the live damage provenance, so this says what actually happened rather than what is answering."""
    actors = {row.entity_id: row.display_name for row in engine.state.actors.values()}
    fallen = _fallen_name(engine, trigger) or "A creature"
    attacker = actors.get(str(trigger.get("actor_id") or ""), "")
    action = str(trigger.get("action_name") or "")
    if attacker and action:
        because = f"{attacker}'s {action}"
    elif attacker:
        because = attacker
    elif action:
        because = action
    else:
        because = "something with no name on the record"
    where = f" inside {trigger['court_leader']}'s Court of Moving Banners" if court and trigger.get("court_leader") else ""
    return f"{fallen} was reduced to 0 Hit Points{where} by {because}."


def _fallen_name(engine: Any, trigger: dict[str, Any]) -> str:
    """The display name of the creature a 0-HP question is about, or "" when the packet names none. Both of this plug-in's
    zero-HP decisions ask about the creature that just dropped -- for General's Soul-Standard that is the leader itself, for
    Court of Moving Banners it is the Commanded ally the Court is protecting -- so the declining note can name the right one
    instead of assuming it is always a leader.

    The single lookup for that name, shared with :func:`_drop_sentence`; each caller supplies its own fallback wording, so an
    unnamed creature never turns into a guess."""
    actors = {row.entity_id: row.display_name for row in engine.state.actors.values()}
    return str(actors.get(str(trigger.get("affected_id") or ""), "") or "")


@hook("decision_text")
def zero_hp_prompt(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, Any] | None:
    """Presentation metadata for the two 0-HP questions above, through the shared ``decision_text`` seam (which only adds
    words, never answers or effects). Without it the table renders a bare checkpoint name and falls back to "Grey Fang
    just did something Bao can react to", which tells the player neither that Bao dropped nor what did it -- and a test
    that passes an invented ``moment`` reads a different branch than the table actually takes, so the wording has to be
    asserted where the table builds it. Inert unless the decision is one of this plug-in's own two checkpoints."""
    trigger = context.get("choice_trigger") or {}
    moment = str(context.get("checkpoint") or "").removeprefix("TYPED:").split("@")[0]
    if moment == _SOUL_CHECKPOINT:
        name, court = "General's Soul-Standard", False
        summary = ("You are at 0 Hit Points but not killed outright. Spend 1 Martial Focus (your Stamina pool for "
                   "weapon attacks) and every Momentum Mark you carry to stay conscious until the end of your next turn. "
                   "While that window runs, ordinary healing does nothing: only a feature that brings a creature back "
                   "from 0 Hit Points can help. You also Set your Standard without spending a Bonus Action, and one "
                   "Command Response during this window is free. If you are still at 0 Hit Points at the end of that next turn, "
                   "you fall Unconscious. Use Limit: once per long rest.")
        limits = "Use Limit: once per long rest"
    elif moment == _COURT_CHECKPOINT:
        name, court = "Court of Moving Banners", True
        summary = ("A Commanded ally (one your Standard covers) that drops to 0 Hit Points inside the Domain may fall "
                   "Prone and move 5 feet before falling Unconscious. That move is forced, so it does not provoke an "
                   "Opportunity Attack. No resource cost.")
        limits = ""
    else:
        return None
    said = _drop_sentence(engine, trigger, court=court)
    # "You may decline" has to name the creature that drops if you do. It is not always the leader: Court of Moving Banners
    # asks about the Commanded ally that went down, so a note that always said "the leader" told a player moving their own
    # fallen ally that declining would put the commander out instead (AUTO71r3 finding 2).
    dropped = _fallen_name(engine, trigger) or "that creature"
    decline = f"You may decline, and {dropped} falls Unconscious by the ordinary rules instead."
    return {"name": name, "feature_id": str(trigger.get("feature_id") or ""), "trigger": said,
            "summary": summary, "limits": limits, "table_note": decline}


@hook("zero_hp", priority=-10)
def court_last_stand(engine: Any, target: Any, source_id: str, intent: Any) -> str | None:
    """Court of Moving Banners: "when a Commanded ally drops to 0 Hit Points inside the Domain, it may fall Prone and move 5 feet
    before falling Unconscious". The move is forced, so it provokes no Opportunity Attack; the ally then goes down by the ordinary
    0-HP path, which is what "before falling Unconscious" means. Returning None leaves the life state to the ordinary owner."""
    from .. import typed_reactions

    if not target.active or target.current_hp != 0 or target.life_state is not None:
        return None
    row = {"feature_id": BASE + "warleader_domain_court_of_moving_banners", "ask": True}
    for leader, data in sorted(wl.leaders(engine), key=lambda pair: pair[0].entity_id):
        if not wl.court_of(leader) or not wl.commanded(engine, leader, data, target) or engine._distance_actor_to_actor(leader, target) > wl.COURT_RANGE_FT:
            continue
        if not typed_reactions._consent(engine, row, target, "COURT_LAST_STAND", trigger={
                **_incoming(engine, target, source_id, intent),
                "cause": f"dropped to 0 Hit Points inside {leader.display_name}'s Court of Moving Banners",
                "court_leader": leader.display_name, "cost": "no resource cost"}):
            continue
        _step_away(engine, target, 5)
        _force_prone(engine, target)
        note(engine, "warleader:court_of_moving_banners", leader, f"{target.display_name} drops to 0 Hit Points inside the Court of Moving Banners: it falls "
                                                                  f"Prone and moves 5 feet before falling Unconscious.", (target,))
        break
    return None


def _force_prone(engine: Any, target: Any) -> None:
    engine._apply_condition(target, "condition:typed.prone", "warleader:court_of_moving_banners", target.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Prone (Court of Moving Banners)"})


def _step_away(engine: Any, target: Any, feet: int) -> None:
    """A forced move of one square in each of the four printed directions until one is legal, the forced kind: it never provokes
    an Opportunity Attack. The printed order is "fall Prone and move 5 feet"; the creature steps first so the engine's own
    Prone rule (a Prone creature has to stand before it moves) does not refuse the step. The end state is the same either way."""
    from ..gate2_runtime_models import Position

    best = None
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        cell = Position(x=target.position.x + dx, y=target.position.y + dy)
        if not (0 <= cell.x < engine.grid.width and 0 <= cell.y < engine.grid.height):
            continue
        if engine.grid.step_legal(target.position, cell, occupied_cells=engine._occupied_cells_except(target.entity_id),
                                  footprint=engine._footprint(target)):
            best = cell
            break
    if best is None:
        return
    start = target.position
    target.position = best
    engine._append_event("MOVEMENT_COMMITTED", "warleader:court_of_moving_banners", actor_id=target.entity_id,
                         payload={"destination": best.model_dump(mode="json"),
                                  "path": [start.model_dump(mode="json"), best.model_dump(mode="json")], "cost_ft": 0, "forced": True})
    from .. import zones

    zones.on_moved(engine, target, start, best, forced=True)


# ------------------------------------------------------------------------------------------------------ Reactive Position
SWAP = "warleader:reactive_position"
_SWAP_CHOICE = wl.CHOICE + "reactive_position_partner"  # which Commanded ally the target trades places with


def _swap_legal(engine: Any, defender: Any, partner: Any) -> bool:
    """Whether the two creatures may trade squares: each destination must fit that creature's own footprint at its own
    elevation, with both of their own squares vacated (they leave them) and every other creature and terrain column
    where it is. A swap is not a step -- neither creature passes through the squares between the two -- so this asks
    whether each destination is legal rather than whether the diagonal between them is walkable. Checked before the
    Momentum Mark is spent, so an illegal placement never costs anything.

    The complete final arrangement is then checked, not each destination alone: the two of them end up standing where
    the other one was, so a Large creature whose footprint is wider than one square can cover the Medium creature that
    just took its place. Each destination passes every one of those checks on its own and the swap still overlaps, which
    is the placement the engine's own occupied-footprint invariant (gate2_engine, at commit) refuses -- so the answer
    here is the arrangement, not the two independent placements."""
    for mover, other in ((defender, partner), (partner, defender)):
        occupied = engine._occupied_volumes_except(mover.entity_id, ignore_actor_ids=(other.entity_id,))
        if not engine.grid.volume_legal(other.position, footprint=engine._footprint(mover), occupied_cells=occupied):
            return False
    return not _final_volumes_overlap(engine, defender, partner)


def _final_volumes_overlap(engine: Any, defender: Any, partner: Any) -> bool:
    """Whether the two creatures' footprints share a single cell once each has stood in the other's square: the defender's
    own footprint at the partner's position, against the partner's own footprint at the defender's position, in the same
    3D cells the engine's occupied-footprint invariant compares (combat.space.volume, the shared footprint contract).
    A pair the engine treats as sharing occupancy (a rider and its mount, say) is not two bodies in one cell, so it is
    left alone exactly as the engine leaves it."""
    from ..space import volume

    if engine._shared_occupancy_pair(defender.entity_id, partner.entity_id):
        return False
    here = set(volume(partner.position, engine._footprint(defender)))
    there = set(volume(defender.position, engine._footprint(partner)))
    return bool(here & there)


def _swap_pair(engine: Any, defender: Any, moment: str, intent: Any) -> Any | None:
    """Reactive Position: "Two Commanded allies are adjacent to one another, and one of them is targeted by an attack roll or
    forced movement ... The two allies swap places. This movement does not provoke Opportunity Attacks." Both creatures must be
    Commanded (the printed rule says two Commanded allies, so a defender who has stepped out of Command Range does not get the
    talent); the leader is Commanded by its own Standard, so it may be the partner. ``moment`` names the trigger in the prompt
    ("<creature> is attacking it", "it is being pushed or pulled"). The partner is chosen through a labelled menu when a player
    is at the table (warleader.choose) and the first eligible ally otherwise; the swap is a forced move for each, so no
    Opportunity Attack fires."""
    for leader, data in sorted(wl.leaders(engine), key=lambda pair: pair[0].entity_id):
        if not wl.knows(engine, leader, "reactive_position") or leader.resources.get(wl.MOMENTUM, 0) < 1:  # "Cost: Spend 1 Momentum Mark."
            continue
        if not wl.commanded(engine, leader, data, defender):
            continue  # "Two Commanded allies": the original target must be one of them
        partners = [other for other in sorted(engine.state.actors.values(), key=lambda a: a.entity_id)
                    if other.active and other.entity_id != defender.entity_id
                    and other.team_id == defender.team_id and engine._distance_actor_to_actor(defender, other) <= 5
                    and wl.commanded(engine, leader, data, other) and _swap_legal(engine, defender, other)]
        if not partners:
            continue
        asked, chosen = wl.choose(engine, leader, intent, "WARLEADER_REACTIVE_POSITION", _SWAP_CHOICE,
                                  [other.entity_id for other in partners],
                                  labels={other.entity_id: f"{other.display_name}: swap places with {defender.display_name} "
                                                       f"(Reactive Position, 1 Momentum Mark; no Opportunity Attacks)"
                                      for other in partners},
                                  prompt=(f"Reactive Position: {defender.display_name} {moment}. Choose the Commanded ally it trades "
                                          f"places with. It costs 1 Momentum Mark and neither creature provokes an Opportunity Attack."),
                                  name="Reactive Position partner", feature_id=BASE + "reactive_position",
                                  target_id=defender.entity_id)
        partner = next((other for other in partners if other.entity_id == chosen), None) if asked and chosen else \
            (None if asked else partners[0])  # asked and declined: nothing is spent
        if partner is None:
            continue
        wl.spend_momentum(engine, leader, SWAP)
        first, second = defender.position, partner.position
        defender.position, partner.position = second, first
        for who, start, end in ((defender, first, second), (partner, second, first)):
            engine._append_event("MOVEMENT_COMMITTED", SWAP, actor_id=who.entity_id,
                                 payload={"destination": end.model_dump(mode="json"),
                                          "path": [start.model_dump(mode="json"), end.model_dump(mode="json")], "cost_ft": 0, "forced": True})
        from .. import zones

        zones.on_moved(engine, defender, first, second, forced=True)
        zones.on_moved(engine, partner, second, first, forced=True)
        note(engine, SWAP, leader,
             f"{leader.display_name} spends 1 Momentum Mark on Reactive Position: {defender.display_name} and {partner.display_name} swap places "
             "without provoking Opportunity Attacks.", (defender, partner))
        return partner
    return None


def _live_attack(engine: Any) -> str:
    """The printed name of the attack being resolved right now, from the live d20 attack frame. Empty when no attack is
    being rolled (a forced move, or a preview outside a roll), so a sentence built from it stays true either way."""
    frame = engine.d20_context() or {}
    return _printed_name(engine, str(frame.get("source_id") or "")) if frame.get("kind") == "attack" else ""


def _out_of_reach(engine: Any, attacker: Any, defender: Any) -> bool:
    """"If the swap places the original target outside the triggering attack's reach or range, the attack misses." The
    reach or range is the one the attack actually being resolved declares, read through the shared attack geometry
    contract (combat.attack_reach.spec_maximum on the live d20 attack spec: the declared range_ft or reach_ft plus any
    condition-bound reach bonus), so a bow keeps its range and a nested reaction attack answers for its own reach. The
    engine's own check of that same number is what settles the miss; this only says whether the swap moved the target
    out of it, which is what the printed condition asks."""
    from ..attack_reach import spec_maximum

    frame = engine.d20_context() or {}
    spec = frame.get("spec") or {}
    if not spec:
        return False  # no live attack spec to read: the engine's own reach check decides, unchanged
    reach = spec_maximum(engine, attacker, str(frame.get("source_id") or ""), spec)
    return engine._effect_distance(attacker, defender) > int(reach)


@hook("before_attack")
def reactive_position(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    """Reactive Position: the two allies trade places before the attack is rolled; a target now out of the attack's declared
    reach or range misses it ({"force_miss": True} is the documented way to say exactly that, for this one attack, including
    a nested reaction attack, whose own spec is the live one)."""
    if defender is None or attacker is None or attacker.team_id == defender.team_id or not defender.active:
        return None
    # Name the attack that is being resolved, not only who is throwing it: "is being attacked" on its own does not tell a
    # player which attack the swap is answering, which is what the printed trigger is about.
    attack = _live_attack(engine)
    moment = f"is being attacked by {attacker.display_name} with {attack}" if attack else f"is being attacked by {attacker.display_name}"
    partner = _swap_pair(engine, defender, moment, intent)
    if partner is None:
        return None
    if not _out_of_reach(engine, attacker, defender):
        return {}
    return {"force_miss": True, "source_id": SWAP, "label": "Reactive Position"}


@hook("forced_movement_attempt")
def reactive_position_forced(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    """Reactive Position's other printed trigger: "one of them is targeted by an attack roll or forced movement". This hook
    runs before each step of a forced move (combat.movement_paths.forced_steps), so the two Commanded allies trade squares
    there instead of the mover continuing into the square the push chose. The strict reply contract is
    {"stop": True, "source_id", "label"}: the swap stops this forced move, because the creatures have already left the squares
    it was aimed at -- and neither of them provokes an Opportunity Attack, as the printed text says. ``nxt`` is then unused."""
    from ..movement_steps import context

    if mover is None or not mover.active or context(engine, mover).get("forced") is not True:
        return None
    if _swap_pair(engine, mover, "is being pushed or pulled", intent) is None:
        return None
    return {"stop": True, "source_id": SWAP, "label": "Reactive Position"}


# ------------------------------------------------------------------------------------------------------ Battlefield Coordination
COORDINATION = "warleader:battlefield_coordination"
_COORD_CHOICE = wl.CHOICE + "battlefield_coordination_source"  # which source of Disadvantage is set aside for this roll


def _disadvantages(engine: Any, ally: Any, attacker: Any) -> dict[str, str]:
    """Every condition on ``ally`` whose printed rule is what makes *this* attack roll by ``ally`` against ``attacker``
    Disadvantage, by condition instance id: the printed "source of Disadvantage" a leader may name. The pairing of a condition
    with its own rule row is the engine's (typed_executor.condition_rules drops inactive, suppressed and
    sight-disqualified rows), so each row is read against the condition it belongs to, and only ``attacks_have`` counts --
    that field is what the engine reads for this creature's own attack rolls (``attacks_others_have`` describes other
    creatures' attacks and ``check_mode`` an ability check, neither of which is this roll)."""
    from ..condition_names import condition_label
    from ..typed_executor import condition_rules, is_active_typed_condition, rules as typed_rules

    if not engine._line_of_sight_actor_to_actor(ally, attacker):
        return {}
    rows = condition_rules(ally, engine=engine)
    # condition_rules yields one row per condition it keeps (inactive, suppressed and sight-disqualified ones drop
    # out), so the pairing is rebuilt with exactly that filter instead of zipping every stored condition against the
    # surviving rows -- which is how a preceding suppressed condition used to shift the association.
    aliases = typed_rules().get("condition_id_aliases") or {}
    active = [held for held in ally.conditions.values()
              if (is_active_typed_condition(held) or held.condition_id in aliases) and not (held.data or {}).get("suppressed")]
    found: dict[str, str] = {}
    for held, row in zip(active, rows, strict=False):
        value = row.get("attacks_have")
        if value == "DISADVANTAGE" or (isinstance(value, dict) and value.get("mode") == "DISADVANTAGE"):
            found[held.instance_id] = str(held.data.get("label") or condition_label(held.condition_id))
    return found


def _actual_mode(engine: Any, attacker: Any, defender: Any) -> str:
    """The engine's own answer to "how is this attack roll actually being made right now", read through the one contract
    that decides it: ``engine._attack_mode``, which gate4 resolves by merging every ``masked_conditions`` answer.

    Battlefield Coordination needs this because a stored ``attacks_have`` penalty is not the same thing as Disadvantage on
    this roll: a roll made with both Advantage and Disadvantage is Normal, and a source a sense has already set aside does
    not count at all. Asking the engine is what keeps the printed trigger -- a roll actually made *with* Disadvantage --
    honest."""
    return str(engine._attack_mode(attacker, defender) or "NORMAL")


def _contributing(engine: Any, attacker: Any, defender: Any, sources: dict[str, str]) -> dict[str, str]:
    """The sources a leader may name: those the engine is not already ignoring for this roll. A condition a sense has set
    aside -- a Blinded creature's own Blinded toward something its Blindsight reaches, a Hidden one that can somehow be seen
    -- is not a source of Disadvantage on this attack, so naming it would spend a Mark and change nothing. The engine's own
    mask set (senses.masked_conditions, the same contract its attack-mode rule reads) is the authority on that.

    Every other source may be named even when another one still stands: the printed rule is to ignore *one* source for
    the triggering roll, and a roll that keeps its other Disadvantage is what that reads as. Setting one aside can never
    leave the roll as Advantage, because it removes a Disadvantage and adds nothing."""
    from .. import senses

    already = set(senses.masked_conditions(engine, attacker, defender).get(attacker.entity_id, ()))
    return {iid: label for iid, label in sources.items() if iid not in already}


@hook("before_attack")
def battlefield_coordination(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    """Battlefield Coordination: "When a Commanded ally makes an attack roll, saving throw, or ability check with Disadvantage,
    spend 1 Momentum Mark. Choose one source of Disadvantage affecting that roll. The ally ignores that one source of
    Disadvantage for the triggering roll." ``before_attack``'s ``attacker`` is the creature making the roll, so only that
    creature's own ``attacks_have`` sources are named. The named condition is masked for this one attack roll
    (masked_conditions, the shared seam for "this condition's Advantage/Disadvantage does not count for that attack"), for
    this roll only -- the frame is dropped when the roll's d20 scope exits -- so the roll keeps any other source of
    Disadvantage and never becomes Advantage ("Battlefield Coordination does not grant Advantage").

    The Mark is spent only on a roll that is really being made with Disadvantage (:func:`_actual_mode`), and only on a
    source the engine is not already ignoring (:func:`_contributing`), so a roll whose Disadvantage was cancelled -- or
    whose only source is already set aside -- spends nothing at all."""
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _ALIGN_FRAME)
    if attacker is None or defender is None or attacker.team_id == defender.team_id or not attacker.active:
        return None
    # "with Disadvantage" describes how the roll is really being made, so ask the engine before offering anything: a
    # roll that is Normal (its Disadvantage cancelled by an Advantage) or Advantage already is not the printed trigger,
    # and nothing is spent on it.
    if _actual_mode(engine, attacker, defender) != "DISADVANTAGE":
        return None
    sources = _contributing(engine, attacker, defender, _disadvantages(engine, attacker, defender))
    if not sources:
        return None
    frame = engine.d20_context() or {}
    attack = _printed_name(engine, str(frame.get("source_id") or ""))
    what = f"{attacker.display_name} is attacking {defender.display_name} with {attack}" if attack \
        else f"{attacker.display_name} is attacking {defender.display_name}"
    for leader, data in sorted(wl.leaders(engine), key=lambda pair: pair[0].entity_id):
        if not wl.knows(engine, leader, "battlefield_coordination") or leader.resources.get(wl.MOMENTUM, 0) < 1:
            continue
        if not wl.commanded(engine, leader, data, attacker) or not engine._line_of_sight_actor_to_actor(leader, attacker):
            continue
        asked, chosen = wl.choose(engine, leader, intent, "WARLEADER_BATTLEFIELD_COORDINATION", _COORD_CHOICE, sorted(sources),
                                  labels={iid: f"{sources[iid]}: ignored for this one attack roll (Battlefield Coordination, "
                                              f"1 Momentum Mark; the roll keeps any other Disadvantage)" for iid in sorted(sources)},
                                  prompt=(f"Battlefield Coordination: {what} with Disadvantage. Choose the one source of Disadvantage "
                                          f"{attacker.display_name} ignores for that roll. It costs 1 Momentum Mark and never "
                                          f"grants Advantage."),
                                  name="Battlefield Coordination source", feature_id=BASE + "battlefield_coordination",
                                  target_id=attacker.entity_id)
        instance = chosen if asked and chosen else (None if asked else next(iter(sorted(sources))))
        if instance is None:
            continue  # a player at the table who declined: nothing is spent
        wl.spend_momentum(engine, leader, COORDINATION)
        engine.__dict__[_ALIGN_FRAME] = {"roller": attacker.entity_id, "target": defender.entity_id, "instance": instance,
                                         "source": str(frame.get("source_id") or ""), "index": int(frame.get("attack_index") or 1)}
        note(engine, COORDINATION, leader,
             f"{leader.display_name} spends 1 Momentum Mark on Battlefield Coordination: {attacker.display_name} ignores {sources[instance]} "
             "for this attack roll.", (attacker,))
        return {}
    return None


@hook("masked_conditions")
def battlefield_coordination_mask(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    """The one source of Disadvantage Battlefield Coordination paid to ignore, and only while that exact attack roll is the
    one being resolved (the live d20 attack frame must be the frame that paid)."""
    frame = getattr(engine, _ALIGN_FRAME, None) or {}
    if attacker is None or target is None or frame.get("roller") != attacker.entity_id or frame.get("target") != target.entity_id:
        return None
    roll = engine.d20_context() or {}
    if roll.get("kind") != "attack" or roll.get("actor_id") != frame.get("roller") or roll.get("target_id") != frame.get("target") \
            or str(roll.get("source_id") or "") != frame.get("source") or int(roll.get("attack_index") or 1) != frame.get("index"):
        return None
    chosen = frame.get("instance")
    return {attacker.entity_id: {chosen}} if isinstance(chosen, str) else None


@hook("roll_context_end")
def coordination_frame_ends(engine: Any, context: dict[str, Any]) -> None:
    """The paid mask belongs to one roll: it goes when that roll's d20 scope exits, hit or miss, resolved or cancelled, so a
    second attack and a reloaded fight find no mask (the frame is transient engine state, never saved)."""
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _ALIGN_FRAME)
    frame = getattr(engine, _ALIGN_FRAME, None)
    if frame and context.get("kind") == "attack" and context.get("actor_id") == frame.get("roller") \
            and str(context.get("source_id") or "") == frame.get("source") and int(context.get("attack_index") or 1) == frame.get("index"):
        engine.__dict__.pop(_ALIGN_FRAME, None)

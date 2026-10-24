"""Transactional vertical displacement and falling, independent of ability ids.

Native descent dispatches each committed arrival through zones.on_moved as
forced movement. Area entry may revoke a support surface; descent then resumes
within the same transaction and round budget, with one cumulative damage packet.
The existing zone dispatcher owns trigger limits, recipient rules and choices.
"""
from dataclasses import dataclass

from . import ext
from .ext import damage_delivery as delivery
from .flight import profile
from .gate2_runtime_models import DiceSpec, Position

SOURCE = "system:combat.falling"


@dataclass(frozen=True)
class Fall:
    actor_id: str
    distance_ft: int
    cause: str


def supported(engine, actor, position=None):
    """The ground or the top of an explicitly finite solid terrain column.

    Support is a pure query over one projected creature and one square. A
    read-only frame shares it between the route check and every later quote that
    asks about the same square; outside a frame every call computes afresh.
    """
    from .read_queries import shared_query
    from .space import point

    target = position or actor.position
    key = ('falling.supported', id(actor), point(target))
    return shared_query(engine, key, lambda: _supported(engine, actor, target), refs=(actor,))


def _supported(engine, actor, position):
    position = position or actor.position
    if position.z == 0:
        return True
    from .terrain_materials import supported as material_support
    if material_support(engine, actor, position):
        return True
    if not engine.grid.volume_legal(position, footprint=engine._footprint(actor)):
        return False
    if engine.grid.roof_supported(position, engine._footprint(actor)):
        return True
    replies = ext.run_strict('support_surface', engine, actor, position)
    if any(reply is not True for reply in replies):
        raise ValueError('support_surface providers must return True or None')
    if replies:
        return True
    return any(engine.grid.terrain_at((x, y, position.z-1), "BLOCKED")
               for x, y in engine._actor_cells(actor, position))


def required(engine, actor):
    if not engine._on_battlefield(actor):
        return False
    if not actor.position.z or supported(engine, actor):
        return False
    if actor.entity_id in getattr(engine, "_deliberate_falls", ()):
        return True
    # Ask the creature's capability before the climbing hold: Hover or
    # suspension answers False on every square, and a route check visits many
    # of them. The answer is the same either way, and supported squares and
    # deliberate falls keep their original precedence above.
    capability = profile(engine, actor)
    if capability.hover or capability.suspended:
        return False
    from .roof_movement import can_hold
    if can_hold(engine, actor):
        return False
    # The rule rows come from the creature's recorded conditions, not its
    # square; a route check asks the same creature about many endpoints.
    from .read_queries import shared_query
    blocking = shared_query(engine, ('falling.ground_condition', id(actor)),
                            lambda: _blocks_flight(actor), refs=(actor,))
    return (not capability.speed_ft or not actor.active or actor.current_hp <= 0
            or blocking
            or engine._has_condition(actor, "condition:core.prone"))


def can_occupy(engine, actor, position):
    """Whether actor may end a move on this square: ground, a supported surface, or a Hover,
    suspension or recorded grip hold there.

    Unlike required(), this is not "would fall now": an ordinary creature with no
    blocking condition does not fall in empty air, yet it still has no legal place
    to stop there. Subject displacement menus and forced routes use this predicate.
    """
    if not position.z or supported(engine, actor, position):
        return True
    capability = profile(engine, actor)
    if capability.hover or capability.suspended:
        return True
    from .roof_movement import can_hold
    return bool(can_hold(engine, actor, at=position))


def _blocks_flight(actor):
    from .typed_executor import condition_rules
    return any(row.get("no_actions") or row.get("speed_zero") or row.get("ends_on_stand_up")
               for row in condition_rules(actor))


def plan_distance(engine, actor):
    """The distance this creature's pending fall would cover, in feet.

    Public, and the single place that answers it: ``settle`` records it for the
    whole pending set (``engine._fall_plans``) so a ``falling`` provider can ask
    how far a creature is about to fall before any of them has moved, and
    ``_fall`` reads the same answer.
    """
    ground = landing(engine, actor)
    return (actor.position.z - ground.z) * 5 if ground is not None else actor.position.z * 5


def settings(actor):
    """Recorded generic protection data, e.g. an active Featherfall effect."""
    caps = [c.data["fall_speed_ft"] for c in actor.conditions.values() if "fall_speed_ft" in c.data]
    if any(type(value) is not int or value < 5 or value % 5 for value in caps):
        raise ValueError("fall_speed_ft must be positive five-foot increments")
    return (min(caps) if caps else None,
            any(c.data.get("fall_damage_immune") for c in actor.conditions.values()),
            any(c.data.get("fall_lands_upright") for c in actor.conditions.values()))


def remaining_packet(engine, target, amount, damage_type, source, intent):
    """Final falling-damage reduction, after ordinary defenses and HP floors."""
    context = getattr(engine, "_fall_packet", None)
    if context is None or source != SOURCE or context.actor_id != target.entity_id:
        return amount
    prone = bool(getattr(engine, "_fall_land_prone", True))
    defended = amount
    for response in ext.run_strict("falling_damage", engine, target, defended, context, intent):
        if not isinstance(response, dict) or set(response) - {"amount", "land_prone"}:
            raise ValueError("falling_damage must return amount and/or land_prone")
        reduced = response.get("amount", defended)
        if type(reduced) is not int or not 0 <= reduced <= defended:
            raise ValueError("falling_damage requires bounded integer damage")
        if "land_prone" in response and type(response["land_prone"]) is not bool:
            raise ValueError("falling_damage land_prone must be boolean")
        amount = min(amount, reduced)
        prone = prone and response.get("land_prone", True)
    # Avoiding all falling damage also avoids Prone. Temporary HP is applied
    # later and does not change this damage-based landing rule.
    engine._fall_land_prone = prone and amount > 0
    engine._fall_damage_taken = amount
    return amount


def landing(engine, actor):
    """Nearest empty ground footprint; falling never commits an overlapping token.

    A occupied landing square deflects to the nearest legal one, with stable grid
    ordering. If the entire map has no ground space, stop above the obstruction
    and record that exceptional blocked landing instead of crashing the fight.
    """
    start = actor.position
    occupied = engine._occupied_volumes_except(actor.entity_id)
    for z in range(start.z-1, -1, -1):
        candidate = start.model_copy(update={"z": z})
        if supported(engine, actor, candidate) and engine.grid.volume_legal(candidate, footprint=engine._footprint(actor), occupied_cells=occupied):
            return candidate
        if engine.grid.roof_supported(candidate, engine._footprint(actor)):
            # An occupied roof cannot be skipped to land in the room below it.
            # Keep the existing blocked-landing outcome until space is clear.
            return None
    candidates = sorted((max(abs(x-start.x), abs(y-start.y)), x, y)
                        for x in range(engine.grid.width) for y in range(engine.grid.height))
    for _, x, y in candidates:
        candidate = Position(x=x, y=y)
        if engine.grid.volume_legal(candidate, footprint=engine._footprint(actor), occupied_cells=occupied):
            return candidate
    return None


def settle(engine, cause="system:combat.effect", intent=None):
    if getattr(engine, "_settling_falls", False) or not hasattr(engine, "state"):
        return
    from .paid_relocation import observe_falls, falling_scope
    observe_falls(engine)
    def due(actor):
        if not required(engine, actor):
            return False
        rate, _, _ = settings(actor)
        return rate is None or actor.turn_flags.get("fall_round_number") != engine.state.round_number or int(actor.turn_flags.get("fall_round_ft", 0)) < rate
    actors = tuple(actor for actor in engine.state.actors.values() if due(actor))
    if not actors:
        return
    engine._settling_falls = True
    # The distance each creature is about to fall, published before the "falling" providers run so a printed
    # trigger that names a minimum drop can ask about it (transient, never saved, restored on unwind).
    prior_plans = getattr(engine, "_fall_plans", None)
    try:
        intent = intent if intent is not None else getattr(engine, "_active_intent", None)
        if ext.run_strict('falling_prepare', engine, actors, cause, intent):
            raise ValueError('falling_prepare providers must return None')
        actors = tuple(actor for actor in actors if due(actor))
        engine._fall_plans = {actor.entity_id: plan_distance(engine, actor) for actor in actors}
        if ext.run_strict("falling", engine, actors, intent):
            raise ValueError("falling providers must return None")
        if ext.run_strict('falling_ready', engine, actors, cause, intent):
            raise ValueError('falling_ready providers must return None')
        observe_falls(engine)
        for actor in actors:
            if not required(engine, actor):
                continue
            with falling_scope(engine, actor):
                _fall(engine, actor, cause, intent)
    finally:
        engine._fall_plans = prior_plans
        engine._settling_falls = False


def damage_distance(engine, actor, distance, cause, intent):
    """The distance this fall's damage is calculated from, in feet.

    A printed ability may shorten it ("Reduce the fall distance used to calculate
    fall damage by 30 feet"): the shorter distance is answered here, before the
    dice are rolled, so ordinary defenses - Resistance, Vulnerability, flat
    reductions, Temporary HP - reduce what the printed shorter fall deals. The
    default is the distance actually fallen.

    Every provider is asked about the same distance, from one frozen ``fall``,
    and their answers combine by the shortest - as ``remaining_packet`` does for
    damage. Validating each answer against the distance actually fallen and
    folding it in as it is read would make a second provider's registration order
    decide whether a fall resolves at all: on a 100-foot fall an answer of 70 is
    fine once 40 has been taken and raises once it has not.
    """
    answers = ext.run_strict("falling_damage_distance", engine, actor, distance, Fall(actor.entity_id, distance, cause), intent)
    fell = distance
    for answer in answers:
        if type(answer) is not int or not 0 <= answer <= fell:
            raise ValueError("falling_damage_distance requires a bounded integer number of feet")
        distance = min(distance, answer)
    return distance


def unresolved(engine, actor, intent):
    """A fall that could not land at all asks the recorded protections to let go.

    Falling only removes protection it spent: no landing space, or a destination
    a creature now fills, ends the attempt with the fall unspent, so a cushion
    must not survive it and cushion a later fall.
    """
    ext.run_strict("falling_unresolved", engine, actor, intent)


def _fall(engine, actor, cause, intent):
    # Each arrival is a native forced entry, in the accepted action transaction.
    # Entry may remove provisional support. Continue below it before calculating
    # one damage packet for the complete descent; zone receipts still enforce
    # their own per-turn limits. A choice/error unwinds movement and entry alike.
    from . import zones
    rate, immune, upright = settings(actor)
    spent = int(actor.turn_flags.get("fall_round_ft", 0)) if actor.turn_flags.get("fall_round_number") == engine.state.round_number else 0
    distance = 0
    while True:
        previous = actor.position
        ground = landing(engine, actor)
        segment = (previous.z - ground.z) * 5 if ground is not None else previous.z * 5
        if rate is not None:
            segment = min(segment, max(0, rate-spent-distance) // 5 * 5)
        if not segment:
            break
        end_z = previous.z - segment // 5
        destination = previous.model_copy(update={"z": end_z}) if ground is not None and end_z > ground.z else ground
        if destination is None:
            engine._append_event("PASSIVE_TRIGGERED", SOURCE, actor_id=actor.entity_id,
                payload={"log": f"{actor.display_name}'s fall cannot land: no space can fit the creature. Clear a landing space.",
                         "blocked_landing": True})
            unresolved(engine, actor, intent)
            return
        # A slow descent also stops above a newly occupied volume rather than overlapping it.
        occupied = engine._occupied_volumes_except(actor.entity_id)
        if not engine.grid.volume_legal(destination, footprint=engine._footprint(actor), occupied_cells=occupied):
            unresolved(engine, actor, intent)
            return
        distance += segment
        if rate is not None:
            actor.turn_flags.update(fall_round_number=engine.state.round_number, fall_round_ft=spent+distance)
        actor.position = destination
        actor.climbing = False
        engine._append_event("MOVEMENT_COMMITTED", SOURCE, actor_id=actor.entity_id,
            payload={"destination": destination.model_dump(mode="json"),
                     "path": [previous.model_dump(mode="json"), destination.model_dump(mode="json")],
                     "cost_ft": 0, "forced": True, "fall_distance_ft": segment})
        zones.on_moved(engine, actor, previous, destination, forced=True)
        # Nested entry movement owns its destination. Never continue a stale
        # descent after a relocation, lost eligibility, or restored flight.
        if actor.position != destination or not actor.active or engine.state.terminal_result is not None or not required(engine, actor):
            break
    if not distance:
        return
    destination = actor.position
    amount = 0
    if not immune:
        # The fall's damage comes from the distance the printed rules measure it by, which is the distance
        # fallen unless a provider shortens it before the dice are rolled (falling_damage_distance).
        measured = damage_distance(engine, actor, distance, cause, intent)
        if measured >= 10:
            roll = engine.roller.roll(DiceSpec(count=min(20, measured//10), sides=6), actor_id=actor.entity_id, reason="FALLING_DAMAGE")
            engine._record_roll(roll)
            engine._append_event("DAMAGE_ROLLED", SOURCE, actor_id=actor.entity_id, target_ids=(actor.entity_id,), payload=roll.model_dump(mode="json"))
            amount = roll.total
    prior = (getattr(engine, "_fall_packet", None), getattr(engine, "_fall_land_prone", True), getattr(engine, "_fall_damage_taken", 0))
    engine._fall_packet, engine._fall_land_prone, engine._fall_damage_taken = Fall(actor.entity_id, distance, cause), not upright, amount
    # A fall commits its damage outside the typed executor, so it opens the same transient frames a
    # typed commit opens: the damage TYPE it is committing (Bludgeoning), which lets a printed "when
    # you take bludgeoning damage" limit answer a fall instead of standing off, and the delivery
    # record (combat/ext/damage_delivery.py), which lets a printed "damage from a trap, a collapse,
    # falling stone ..." limit tell a fall from a sword. Both read-only and restored, so nothing is
    # written to the journal or the fight state.
    previous_type = getattr(engine, "_typed_pending_damage_type", None)
    try:
        engine._typed_pending_damage_type = "BLUDGEONING"
        with delivery.delivering(engine, SOURCE, hazard=delivery.FALLING):
            engine._commit_damage(actor, amount, "BLUDGEONING", SOURCE, actor.entity_id, intent, reaction_depth=3)
    finally:
        prone, taken = engine._fall_land_prone, engine._fall_damage_taken
        engine._fall_packet, engine._fall_land_prone, engine._fall_damage_taken = prior
        engine._typed_pending_damage_type = previous_type
    landed = supported(engine, actor)
    if landed and prone and not engine._has_condition(actor, "condition:typed.prone"):
        engine._apply_condition(actor, "condition:typed.prone", SOURCE, actor.entity_id, expires_on=None)
    suffix = f" It is still {destination.z*5} ft. above the ground." if not landed else ""
    engine._append_event("PASSIVE_TRIGGERED", SOURCE, actor_id=actor.entity_id,
        payload={"log": f"{actor.display_name} falls {distance} ft. and takes {taken} Bludgeoning damage.{suffix}",
                 "fall_distance_ft": distance, "damage_taken": taken})
    if landed:
        replies = ext.run_strict('fall_landed', engine, actor, Fall(actor.entity_id, distance, cause), intent)
        if replies:
            raise ValueError('fall_landed providers must return None')


def drop(engine, actor, intent=None):
    """Deliberately release support, retaining normal falling protections/hooks."""
    prior = getattr(engine, '_deliberate_falls', ())
    engine._deliberate_falls = (*prior, actor.entity_id)
    actor.climbing = False
    try:
        settle(engine, 'system:combat.jump_down', intent)
    finally:
        engine._deliberate_falls = prior


def displace(engine, actor, steps, source, *, intent=None, settle_after=True):
    """An explicitly authorized launch/descent; no movement payment or OA."""
    if type(steps) is not int:
        raise ValueError("vertical displacement requires integer five-foot steps")
    if steps > 0 and not profile(engine, actor).can_ascend:
        return 0
    previous = actor.position
    path = [previous]
    occupied = engine._occupied_volumes_except(actor.entity_id)
    direction = 1 if steps > 0 else -1
    for _ in range(abs(steps)):
        z = path[-1].z + direction
        if z < 0:
            break
        nxt = path[-1].model_copy(update={"z": z})
        if not engine.grid.volume_step_legal(path[-1], nxt, footprint=engine._footprint(actor), occupied_cells=occupied):
            engine._record_movement_collision(actor, nxt)
            break
        path.append(nxt)
    actor.position = path[-1]
    if len(path) > 1:
        engine._append_event("MOVEMENT_COMMITTED", source, actor_id=actor.entity_id,
            payload={"destination": actor.position.model_dump(mode="json"), "path": [p.model_dump(mode="json") for p in path],
                     "cost_ft": 0, "forced": True})
    if settle_after:
        settle(engine, source, intent)
    return (len(path)-1)*5

"""Bounded, decision-local native attack estimates for ordinary walking.

Uses flight_decision's isolated projection and native attack gates. No turns,
reactions, terrain effects or dice are simulated. Estimates never enter saves
or grant an attack: the real menu is queried again after the actual move.
"""
from . import flight_decision
from .relations import ENEMY, ordinary_turn, relation
from .read_queries import pure
from .walk_features import movement_features

POSITION_LIMIT = 8
METADATA_KEY = 'walk_attack'


def attack_value(action):
    """The one integer damage estimate for an owned action (dice, else its parameter).

    Every comparison in attack_values uses only this, so the "here", upper-bound
    and projected values can never disagree about the same strike.
    """
    if action.damage is not None:
        dice = action.damage
        return (dice.count * (dice.sides + 1) + 2 * dice.modifier) // 2
    return int(action.parameters.get('expected_damage') or 0)


@pure
def attack_values(engine, actor, candidates, known_actors, frame=None, policy=None):
    """At most eight distinct ordinary walk endpoints; cache within this call.

    Cheap approach/escape/cover/objective features rank useful destinations.
    A native reach bound excludes endpoints that cannot improve the current
    attack. An upper damage bound avoids all projections when already able to
    use the strongest owned strike. No unqueried destination earns credit.
    """
    from .attack_reach import maximum
    from .target_knowledge import knowledge
    from .candidate_knowledge import query
    if not ordinary_turn(candidates):
        return {}
    moves = [c for c in candidates if c.kind == 'MOVE' and c.destination is not None
             and c.metadata.get('movement_mode', 'walk') == 'walk'
             and not c.metadata.get('flight_tactics')
             and c.canonical_path and all(p.z == actor.position.z for p in c.canonical_path)
             and c.destination.z == actor.position.z]
    if not moves:
        return {}
    foes = tuple(other for other in known_actors if other.active
                 and relation(engine, actor, other) == ENEMY
                 and (known := knowledge(engine, actor, engine.state.actors[other.entity_id])) is not None
                 and known.mode == 'DIRECT')
    if not foes:
        return {}
    prohibited = set(policy.prohibited_choices) if policy is not None else set()
    here = max((attack_value(engine.action_catalog[c.source_definition_id])
                for c in candidates if c.kind in ('ACTION', 'BONUS_ACTION')
                and c.source_definition_id in engine.action_catalog
                and c.source_definition_id not in prohibited
                and c.metadata.get('target_knowledge') != 'LAST_OBSERVED'
                and any(foe.entity_id in c.target_ids for foe in foes)), default=0)
    # Do not inspect grips, payment hooks or copy the engine if even the
    # unfiltered upper bound cannot beat a presently legal attack.
    possible = {source for source in actor.action_ids if source not in prohibited
                and source in engine.action_catalog and attack_value(engine.action_catalog[source]) > here}
    if not possible:
        return {}
    attacks = tuple(a for a in flight_decision._attacks(engine, actor, own=True)
                    if a.source_definition_id in possible)
    if not attacks:
        return {}
    limits = tuple(maximum(engine, actor, a) for a in attacks)
    reach = None if None in limits else max(limits)
    distances = {}
    def nearest(candidate):
        destination = candidate.destination
        key = (destination.x, destination.y, destination.z)
        if key not in distances:
            distances[key] = min(engine._distance_actor_to_actor(
                actor, foe, actor_position=destination) for foe in foes)
        return distances[key]
    nearby = [c for c in moves if reach is None or nearest(c) <= reach]
    if not nearby:
        return {}
    before = min(engine._distance_actor_to_actor(actor, foe) for foe in foes)
    def cheap(candidate):
        if frame is not None:
            value = sum(v for k, v in movement_features(frame, candidate).items() if k != 'flight')
        else:
            after = nearest(candidate)
            value = max(-5, min(5, (before - after) // engine.grid.square_size_ft))
            value += 8 * int(bool(candidate.metadata.get('cover_from_nearest_hostile')))
        return (-value, bool(candidate.metadata.get('hazard_exposure')),
                len(candidate.metadata.get('reaction_exposure') or ()), candidate.movement_cost_ft,
                candidate.destination.x, candidate.destination.y, candidate.candidate_id)
    view = flight_decision._query_copy(engine)
    ids = frozenset(other.entity_id for other in known_actors if other.entity_id == actor.entity_id
                    or other.entity_id in {foe.entity_id for foe in foes}
                    or relation(engine, actor, other) != ENEMY)
    # Full effect-owner records stay on the copy, but hidden targets cannot
    # enter prospective native geometry, even if the step would reveal them.
    projected_foes = tuple(view.state.actors[foe.entity_id] for foe in foes)
    cache, result = {}, {}
    upper = max(attack_value(action) for action in attacks)
    for candidate in sorted(nearby, key=cheap):
        dest = candidate.destination
        key = (dest.x, dest.y, dest.z, candidate.movement_cost_ft)
        if key not in cache:
            if len(cache) >= POSITION_LIMIT:
                continue
            projected, mover = flight_decision._at(view, actor.entity_id, candidate)
            with query(projected, perceived_actor_ids=ids):
                cache[key] = max((attack_value(action) for action, strike in
                    flight_decision.native_attack_candidates(projected, mover, projected_foes, attacks)), default=0)
        best = cache[key]
        if best > here:
            result[candidate.candidate_id] = {METADATA_KEY: {'here': here, 'best': best, 'gain': best - here}}
            # Cheap ordering has already preferred this route. Once native
            # admission reaches the owned damage upper bound, another origin
            # cannot unlock a stronger strike. Leave all unchecked moves in
            # the menu with no speculative credit instead of querying eight
            # equivalent attacking squares every decision.
            if best >= upper:
                break
    return result

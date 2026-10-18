"""Voluntary passage through creatures the rules let a mover pass (MOVEPASS1).

Printed rule: during your move you can pass through the space of an ally, a
creature that has the Incapacitated condition, a Tiny creature, or a creature
two or more sizes larger or smaller than you. Each such space is Difficult
Terrain for you, and you can never end a move in an occupied space.

This module is the single core seam for that rule. creature_passage.grants
reads passable(...) for every known occupant and turns a True answer into an
ordinary 'difficult' whole-footprint grant, so pathfinding, execution, flight
and the menu all price and block the same way. The stop rule is enforced by
creature_passage.geometry (end_blocked), so no move can end in these spaces.
Hostile talents that allow more are plug-ins: they answer the documented
movement_pass_through hook (combat/ext/__init__.py), which is default-inert.
"""
from .dynamic_size import CATEGORIES, current_category


def incapacitated(actor):
    """True when the actor has the Incapacitated condition, or a named condition that includes it.

    Read from the typed condition table: a row marked counts_as_incapacitated (Incapacitated, Paralyzed,
    Petrified, Stunned, Unconscious in combat/rules/typed_conditions.json) and nothing else. Other states that
    take away Actions (Stone Womb's stone_shell, sleep, Bone Monarch cocoons) are not Incapacitated, so they
    do not open a route through the creature.
    """
    from .typed_executor import condition_rules
    return any(row.get('counts_as_incapacitated') for row in condition_rules(actor))


def passable(engine, mover, other):
    """True when the printed rule lets ``mover`` pass through ``other``'s space.

    Relation comes from combat.relations (never team-identifier comparison).
    Sizes come from the effective category, so transformed creatures count.
    """
    if other.entity_id == mover.entity_id:
        return False
    from . import relations
    if relations.relation(engine, mover, other) == relations.ALLY:
        return True
    if incapacitated(other) or current_category(engine, other) == 'Tiny':
        return True
    gap = abs(CATEGORIES.index(current_category(engine, mover))
              - CATEGORIES.index(current_category(engine, other)))
    return gap >= 2


def passable_occupants(engine, mover):
    """Entity ids of every active creature the built-in rule lets ``mover`` pass."""
    return {other.entity_id for other in engine.state.actors.values()
            if other.active and passable(engine, mover, other)}

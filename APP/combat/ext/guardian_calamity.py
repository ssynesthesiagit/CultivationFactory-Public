"""Stand Against the Calamity (Guardian, AUTO115 2026-10-05): "Plant your stance and refuse destruction."

Rules text: the owner's Sphere Compendium, "Sphere of Guardian", Stand Against the Calamity
(authority/typed_mechanics/rules_text.json, TAL_GUARDIAN_STAND_AGAINST_THE_CALAMITY).

Who has it: a Guardian who owns this talent. The talent compiles to a ``stand_against_the_calamity``
row (combat/rules/feature_blocks.d/auto115_guardian.json, block ``guardian``) and, while it lasts, to
the timed state of the same name (combat/ext/states.py, read here through ``active``). Every hook
below returns at once for a creature without both the owned row and the live state, so other
characters and older saved fights are untouched.

The printed clauses and where each one runs
--------------------------------------------
- "you cannot willingly move" / "ends early if you become Incapacitated or willingly move":
  the ability's ``ends_if_incapacitated`` effect with ``also_on_move``
  (combat/ext/ends_if_incapacitated.py). No hook here; the aura simply stops when that state does.
- "allies inside gain +2 AC": the ``ac`` hook (the ordinary Armor Class sum).
- "allies inside gain Advantage on saving throws": the ``save_mode`` hook, shared by typed and native saves.
- "allies inside reduce all damage taken by your Proficiency Bonus": the ``damage_reduction`` hook,
  a flat amount taken off a packet after Resistance. It is unconditional while the aura lasts, so
  the weighing call (``applied=False``) and the real one (``applied=True``) answer the same number.
- "structures and Formation Anchors inside gain Resistance to all damage": the ``object_damage_defenses``
  hook. Structures are ``RuntimeObjectState`` records in ``engine.state.objects`` and their damage runs through
  combat/ext/objects.deal, not through the creature defense reader, so the resistance is declared on the object
  hook and applied by ``object_rules.work_out`` as ordinary resistance: the same halving, rounding, note and
  suppression, and no stacking with the object's own material.
  Eligibility uses the object's structure preset or explicit ``formation_anchor`` kind;
  ordinary loose objects receive no protection.
- "an enemy attempting to forcibly move one creature inside makes a Strength saving throw. Failed
  Save: the forced movement fails. Successful Save: Move the target only half the normal distance":
  the ``forced_movement_restriction`` hook, before a typed push/pull. ``ctx.actor`` is the creature
  doing the moving, so it is the attacker that makes the save, and "an enemy" is judged against the
  aura's owner. The restriction hook, not ``forced_movement_distance``, because this clause overrides a
  distance rather than choosing one: another ability may also be choosing that push (Moon's Pull), and
  a mandatory cap still holds then.

The aura radius is the printed 30 feet, measured from the Guardian. Only creatures of other teams
count as enemies, and the Guardian's own allies (its own team) are who the printed ally benefits
reach. Stored data is integers and strings only: the state row holds the label and the aura radius.

Shared, not private: the Guardian ownership row lookup is combat/ext/guardian.py's public ``row``,
and the timed state is read through combat/ext/states.py's public ``active``. Nothing here reaches
into another plug-in's private functions.
"""

from __future__ import annotations

from typing import Any

from combat.object_rules import has_tag
from . import hook, note, run
from .guardian import row as guardian_row
from .needle import save_dc
from .states import active

BLOCK = "guardian"
KIND = "stand_against_the_calamity"
STATE = "stand_against_the_calamity"
FEATURE = "TAL_GUARDIAN_STAND_AGAINST_THE_CALAMITY"
RADIUS = 30
DAMAGE_TYPES = {"acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic", "piercing",
                "poison", "radiant", "slashing", "thunder", "psychic"}


def _holder(engine: Any, actor: Any) -> Any:
    """The live Stand Against the Calamity state on ``actor``, or None.

    Ownership and the timed state are both required: an unowned creature, an owner whose aura has
    already ended and an older saved fight without the row all answer None.
    """
    if actor is None or not getattr(actor, "active", False):
        return None
    if guardian_row(engine, actor, KIND) is None:
        return None
    return active(engine, actor, STATE)


def _holders(engine: Any) -> list[tuple[Any, Any]]:
    """Every Guardian currently standing against a calamity, with its live state row."""
    out = []
    for other in sorted(getattr(engine, "state", None).actors.values() if getattr(engine, "state", None) else [],
                        key=lambda a: a.entity_id):
        found = _holder(engine, other)
        if found is not None:
            out.append((other, found))
    return out


def _inside(engine: Any, guardian: Any, recipient: Any, feet: int = RADIUS) -> bool:
    """Whether ``recipient`` stands inside ``guardian``'s printed aura.

    A creature must still be on the field. An object -- a structure, a Formation Anchor or anything else the fight
    keeps in ``state.objects`` -- has no life state and is measured by the square it occupies, so the printed radius
    reaches the built world as well as the fighters.
    """
    if guardian is None or recipient is None or not getattr(recipient, "active", True):
        return False
    if getattr(recipient, "entity_id", None):  # a creature, measured by the cells its body covers
        return engine._distance_actor_to_actor(guardian, recipient) <= feet
    square = getattr(recipient, "position", None)  # an object, measured by the square it stands on
    return square is not None and engine._distance_actor_to_cell(guardian, square) <= feet


def _protected_ally(engine: Any, target: Any) -> Any:
    """The strongest Guardian whose printed ally benefits reach ``target``, or None.

    An ally of that Guardian (same team, not the Guardian itself) standing inside the aura.
    Identical auras do not stack; the highest Proficiency Bonus supplies the reduction.
    """
    covering = []
    for guardian, state in _holders(engine):
        if target is None or guardian.entity_id == target.entity_id or guardian.team_id != target.team_id:
            continue
        if _inside(engine, guardian, target):
            covering.append(guardian)
    return max(covering, key=lambda guardian: int(guardian.proficiency_bonus or 0), default=None)


def _covering_guardians(engine: Any, target: Any) -> list[Any]:
    """All Guardians whose printed aura covers ``target`` as one creature inside it.

    This is the forced-movement clause's own reach: "one creature inside" is any living creature standing in the
    aura, the Guardian itself included, whichever team it fights for. Whether the creature doing the moving is an
    enemy is judged against the aura's owner by the caller, not here.
    """
    if not _is_creature(engine, target):
        return []
    return [guardian for guardian, _state in _holders(engine) if _inside(engine, guardian, target)]


def _is_structure_or_anchor(engine: Any, target: Any) -> bool:
    """Use the object preset's structure classification or an explicit Formation Anchor kind.

    No Anchor is inferred from a name or from being an ordinary loose object.
    """
    if target is None:
        return False
    if _is_creature(engine, target):
        return False
    return has_tag(target, "structure") or has_tag(target, "formation_anchor")


def _is_creature(engine: Any, target: Any) -> bool:
    """Whether this recipient is a living creature rather than a structure or Formation Anchor.

    The fight's object actors (structures, anchors, objects in combat) carry no character sheet: they are
    ``RuntimeObjectState`` records in ``state.objects``, which have an ``object_id`` and no ``entity_id``.
    Summons and familiars are creatures.
    """
    if target is None:
        return False
    return bool(getattr(target, "entity_id", None)) \
        or bool(getattr(target, "proficiency_bonus", None) or getattr(target, "character_id", None)) \
        or bool(getattr(target, "max_hp", None))


# ------------------------------------------------------------------------------------------------ printed ally benefits
@hook("ac")
def calamity_ac(engine: Any, target: Any) -> int:
    """"allies inside gain +2 AC" (Stand Against the Calamity)."""
    return 2 if _protected_ally(engine, target) is not None else 0


@hook("save_mode")
def calamity_saves(engine: Any, subject: Any, ability: str, dc: int, source_id: str,
                   roll_context: dict[str, Any]) -> str | None:
    """"allies inside gain Advantage on saving throws" (Stand Against the Calamity)."""
    if _protected_ally(engine, subject) is None:
        return None
    # Native mode contributions are combined before cancellation. Concentration's
    # existing suppression query must also govern this general saving-throw benefit.
    if source_id == "system:combat.concentration" and any(
            "ADVANTAGE" in (removed or ()) for removed in run("concentration_mode_removed", engine, subject)):
        return None
    return "ADVANTAGE"


@hook("damage_reduction")
def calamity_reduction(engine: Any, target: Any, damage_type: str, typed: Any, source_actor_id: Any,
                        applied: bool = False) -> int | None:
    """"allies inside reduce all damage taken by your Proficiency Bonus" (Stand Against the Calamity).

    While the aura lasts this is a flat amount off every packet that ally takes, so the weighing
    call and the applied call answer the same Proficiency Bonus.
    """
    guardian = _protected_ally(engine, target)
    if guardian is None:
        return None
    return max(0, int(getattr(guardian, "proficiency_bonus", 0) or 0))


@hook("object_damage_defenses")
def calamity_structures(engine: Any, actor: Any, obj: Any, packets: Any, source: Any) -> list[dict[str, Any]] | None:
    """"structures and Formation Anchors inside gain Resistance to all damage" (Stand Against the Calamity).

    Objects are ``RuntimeObjectState`` records in ``engine.state.objects`` and their damage runs through
    ``combat/ext/objects.deal`` -> ``object_rules.work_out``, never through the creature defense reader, so the
    resistance is declared on the object hook and applied by ``work_out`` as ordinary resistance: the same halving,
    the same rounding down and the same suppression as any other Resistance. Living creatures never reach it.
    """
    if not _is_structure_or_anchor(engine, obj):
        return None
    for guardian, _state in _holders(engine):
        if _inside(engine, guardian, obj):
            return [{"kind": "resistance", "damage_types": sorted(DAMAGE_TYPES)}]
    return None


# ------------------------------------------------------------------------------------------------ the enemy Strength save
@hook("forced_movement_restriction")
def calamity_holds(ctx: Any, subject: Any, effect: Any, maximum_ft: int) -> int | None:
    """"an enemy attempting to forcibly move one creature inside makes a Strength saving throw.

    Failed Save: The forced movement fails.  Successful Save: Move the target only half the normal distance." (Stand
    Against the Calamity) -- ``ctx.actor`` is the creature doing the moving, so it is the attacker that makes the save.

    This is a mandatory restriction, not an optional distance: it is answered on ``forced_movement_restriction``,
    which caps whatever distance was chosen, so the printed "the forced movement fails" still holds when another
    ability is also choosing that distance (Moon's Pull, Abyssal Depths' choice of 15/10/5/0).
    """
    attacker = getattr(ctx, "actor", None)
    if attacker is None:
        return None
    caps = []
    # Each hostile owner answers its own trigger. Successful identical effects halve
    # the normal distance once; a failed save wins, independent of entity ordering.
    for guardian in _covering_guardians(ctx.engine, subject):
        if attacker.team_id == guardian.team_id:
            continue
        dc = save_dc(ctx.engine, guardian)
        roll = ctx.engine._roll_save(attacker, "STR", dc, FEATURE)
        if roll is None:
            continue
        distance = maximum_ft // 2 if roll.total >= dc else 0
        caps.append(distance)
        outcome = (f"holds its Strength save and moves {subject.display_name} only {distance} feet."
                   if roll.total >= dc else f"fails its Strength save; {subject.display_name} cannot be forcibly moved.")
        note(ctx.engine, FEATURE, guardian,
             f"Stand Against the Calamity: {attacker.display_name} {outcome}",
             (attacker.entity_id, subject.entity_id))
    return min(caps) if caps else None

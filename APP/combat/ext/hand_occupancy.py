"""Shared physical occupancy for equipment_hands, grapple_parts and wrestling_framework.

Also the shared readiness model for printed "while wielding <weapon>" conditions:
sword_sphere asks ``supports_grips``/``weapon_grips`` for whether a Sword is readied in
hand, not merely carried in inventory.

Readied weapons occupy one resting hand per physical weapon (a Paired weapon
occupies two). Inventory beyond the initial two-hand loadout is stowed, not
magically held. Explicit Draw/Stow choices override that deterministic loadout.
Two-Handed requires a second hand only
when attacking; releasing that grip permits a Grapple. Shields occupy one hand.
Other carried/worn items do not imply a grip. Owning features can contribute
explicit parts/occupants through hand_parts/hand_occupants; never infer limbs
from creature names. Body holds use their owner's grappling_body_parts hook.

Legacy physical holds allocate ordinary hands in sequence order, without
rewriting saves. Explicit holds, shields and weapons can overfill old equipment;
that leaves no free hand rather than silently discarding a hold or item.
Historical catalogs without grip actions or the acquisition policy marker retain
their original weapon policy: no new loadout is inferred or saved. All queries
are pure: no fight-state objects or derived occupancy are persisted.
"""
from __future__ import annotations

import re
from typing import Any
from ..catalog_queries import owned_actions

HANDS = ("hand:left", "hand:right")
GRAPPLED = "condition:typed.grappled"


def supports_grips(engine: Any, actor: Any) -> bool:
    """Opt into managed grips for catalogs compiled with the equipment policy.

    Historical bundles are immutable and have no Draw/Stow actions. Preserve
    their original weapon policy instead of imposing an unmanageable loadout.
    """
    return any(action.parameters.get("equipment_grip")
               or action.parameters.get("equipment_hands_model") == 1
               for action in owned_actions(engine, actor.entity_id))


def resting_hands(action: Any) -> int:
    """Physical grips restored by drawing, recovering or taking this weapon."""
    properties = ((action.parameters.get("typed") or {}).get("weapon") or {}).get("properties") or ""
    return 2 if re.search(r"\bPaired\b(?! Method)", properties, re.I) else 1


def holding_hands(engine: Any, identity: str) -> int:
    """How many hands this weapon needs in order to be *held*, not to be swung.

    The grip you rest the object in is ``resting_hands`` on the weapon's own action, and it is the same for
    everything that carries it (a Two-Handed or Versatile weapon is held in one hand and needs its second
    hand only to attack, as this module's docstring states). ``weapon_requirement`` is deliberately not used
    here: that answers the harder question of swinging it, which is a separate legality check for anything
    that attacks with a caught object. Default-inert: an id this fight's catalog does not hold takes one hand,
    the ordinary case, rather than refusing a catch it cannot price.
    """
    action = engine.action_catalog.get(identity)
    return resting_hands(action) if action is not None else 1


def weapon_grips(engine: Any, actor: Any) -> dict[str, int]:
    """Readied physical weapons, with persisted Draw/Stow overriding legacy defaults."""
    if not supports_grips(engine, actor):
        return {}  # Default-inert for historical catalogs, not a bundle migration.
    from .weapon_hits import available_weapons
    from ..weapon_delivery import weapon_variant_base, physical_weapon_id
    from factory_authoring.starting_kits import item_definition
    from .. import carry
    # Defaults are computed from the original catalog, not remaining gear:
    # dropping a weapon must not spontaneously draw a stowed spare.
    shields = sum((item_definition(str(item.get("item_id") or "")) or {}).get("armor_category") == "shield"
                  for item in (carry.carrying_of(engine, actor.entity_id) or {}).get("items") or [])
    remaining = max(0, len(hand_parts(engine, actor)) - shields)
    defaults = set()
    for action in owned_actions(engine, actor.entity_id):
        identity = action.source_definition_id
        typed = action.parameters.get("typed") or {}
        if (action.owner_id != actor.entity_id or ".weapon." not in identity or physical_weapon_id(identity, action.parameters) != identity
                or not typed.get("weapon") or any(typed.get(key) for key in ("delivered_by", "opportunity_of", "weapon_source_id", "maneuver_of"))
                or action.parameters.get("requires_held_weapon") or weapon_variant_base(action.parameters)):
            continue
        n = resting_hands(action)
        if n <= remaining:
            defaults.add(identity)
            remaining -= n
    choices = actor.equipment_readiness
    out = {}
    for identity, action in available_weapons(engine, actor, include_busy=True).items():
        if ".weapon." not in identity:
            continue
        # Taken equipment is explicitly held through held_by, not an initial kit default.
        ready = choices.get(identity, int(identity in defaults or bool(action.parameters.get("requires_held_weapon"))))
        if ready:
            out[identity] = resting_hands(action)
    return out


def physical_row(engine: Any, row: Any) -> bool:
    if (row.data or {}).get("grapple_source") == "physical" or (row.data or {}).get("grappling_part"):
        return True
    action = engine.action_catalog.get(row.source_definition_id)
    typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
    return typed.get("unarmed_option") == "grapple"


def physical_holds(engine: Any, actor: Any) -> list[tuple[Any, Any]]:
    return [(target, row) for target in engine.state.actors.values() for row in target.conditions.values()
            if row.condition_id == GRAPPLED and row.source_actor_id == actor.entity_id and physical_row(engine, row)]


def hand_parts(engine: Any, actor: Any) -> tuple[str, ...]:
    from . import query
    parts = list(HANDS)
    for extra in query("hand_parts", engine, actor):
        if isinstance(extra, (list, tuple)):
            parts.extend(part for part in extra if isinstance(part, str) and part not in parts)
    return tuple(parts)


def occupancy(engine: Any, actor: Any, *, grips: dict[str, int] | None = None) -> dict[str, tuple[str, ...]]:
    """Map each part to occupants; overflow uses occupied:overflow:N keys.

    Weapon occupant ids are their base actions, shield ids are inventory keys,
    and hold ids are condition instance ids. Consumers may reuse only the
    delivering weapon's own resting grip, never another item's or a hold's.
    """
    from .. import carry
    from . import query
    from factory_authoring.starting_kits import item_definition

    hands = hand_parts(engine, actor)
    occupied: dict[str, list[str]] = {}
    def place(who, part=None):
        key = part or next((p for p in hands if p not in occupied), f"occupied:overflow:{len(occupied)}")
        occupied.setdefault(key, []).append(who)

    for _, row in sorted(physical_holds(engine, actor), key=lambda item: (item[1].applied_sequence, item[1].instance_id)):
        place("hold:" + row.instance_id, (row.data or {}).get("grappling_part"))
    for extra in query("hand_occupants", engine, actor):
        for part, who in (extra if isinstance(extra, dict) else {}).items():
            place(str(who), str(part))
    for item in (carry.carrying_of(engine, actor.entity_id) or {}).get("items") or []:
        if (item_definition(str(item.get("item_id") or "")) or {}).get("armor_category") == "shield" \
                and carry.holds(engine, actor, item["key"]):
            location = carry.owned_item_location(actor, item["key"])
            if location is None:
                place("shield:" + item["key"])
            elif location.startswith("hand:"):
                place("shield:" + item["key"], location.removeprefix("hand:"))
    explicit = {weapon: part for weapon, part in actor.equipment_readiness.items()
                if isinstance(part, str) and part in hands}
    ready = weapon_grips(engine, actor) if grips is None else grips
    # Reserve explicit equipment parts before allocating deterministic defaults.
    for identity in sorted(ready, key=lambda key: key not in explicit):
        for index in range(ready[identity]):
            place("weapon:" + identity, explicit.get(identity) if index == 0 else None)
    return {part: tuple(owners) for part, owners in occupied.items()}


def free_hands(engine: Any, actor: Any, *, occupied: dict[str, tuple[str, ...]] | None = None) -> tuple[str, ...]:
    occupied = occupancy(engine, actor) if occupied is None else occupied
    if any(part.startswith("occupied:overflow:") for part in occupied):
        return ()
    return tuple(part for part in hand_parts(engine, actor) if part not in occupied)


def weapon_requirement(engine: Any, action: Any, *, effect: dict[str, Any] | None = None) -> tuple[str, int] | None:
    """Resolve variants, weapon-delivered talents and opportunity copies, including legacy metadata."""
    from types import SimpleNamespace
    from .weapon_hits import weapon_identity
    typed = (action.parameters or {}).get("typed") or {}
    from ..weapon_delivery import delivery_kind
    weapon_packet = effect is not None and delivery_kind(typed, effect, action.parameters) == 'weapon'
    if not weapon_packet and (typed.get('source') == 'unarmed_strike' or typed.get('unarmed_option')):
        return None  # Unarmed attacks/options do not need the maneuver's original ranged weapon held.
    identity = weapon_identity(SimpleNamespace(engine=engine, action=action, typed=typed))
    base = engine.action_catalog.get(identity)
    weapon = typed.get("weapon") or ((base.parameters.get("typed") or {}).get("weapon") if base else None)
    if not weapon or ".weapon." not in identity:
        return None
    properties = weapon.get("properties") or ""
    requirement = int(action.parameters.get("requires_hands") or 1)
    if re.search(r"\bTwo-Handed(?: Method)?\b", properties, re.I):
        requirement = 2
    requirement = max(requirement, resting_hands(base or action))
    versatile = re.search(r"Versatile \(?(\d+)d(\d+)", properties, re.I)
    damage = weapon.get("damage") or {}
    if versatile and int(damage.get("sides") or 0) == int(versatile.group(2)):
        requirement = 2
    if pair_attack(action):
        requirement = max(2, requirement)
    return identity, requirement


def pair_attack(action: Any) -> bool:
    """Extra Light attacks and their compiled Answering-Weapon variants."""
    typed = action.parameters.get("typed") or {}
    return (typed.get("pair_role") == "answer" or "#offhand" in action.source_definition_id
            or bool(action.parameters.get("following_strike")))


def weapon_capacity(engine: Any, actor: Any, identity: str, *, occupied: dict[str, tuple[str, ...]] | None = None) -> int:
    """Hands available to this weapon after all other physical occupants."""
    occupied = occupancy(engine, actor) if occupied is None else occupied
    own = "weapon:" + identity
    slots = hand_parts(engine, actor)
    blocked = sum(1 for p, owners in occupied.items()
                  if p in slots or p.startswith(("hand:", "occupied:overflow:"))
                  for owner in owners if owner != own)
    return max(0, len(slots) - blocked)


def _versatile_printed_sides(engine: Any, action: Any) -> tuple[int, int] | None:
    """This weapon's printed ``(ordinary, two_handed)`` die sides, or None when it is not Versatile.

    Read from the catalog item, never from the action's own die: that die was already grip-selected at
    compilation, so it cannot say what the other printed grip is.
    """
    from types import SimpleNamespace

    from .weapon_hits import weapon_item

    item = weapon_item(SimpleNamespace(engine=engine, action=action, typed=(action.parameters.get("typed") or {})))
    properties = str(item.get("properties") or "")
    if "versatile" not in properties.lower() or re.search(r"\bTwo-Handed\b", properties, re.I):
        return None
    ordinary = re.search(r"(\d+)d(\d+)", str(item.get("damage") or ""))
    two_handed = re.search(r"Versatile \(?(\d+)d(\d+)", properties, re.I)
    if not ordinary or not two_handed:
        return None
    return int(ordinary.group(2)), int(two_handed.group(2))


def versatile_one_hand(engine: Any, actor: Any, action: Any) -> bool:
    """True when another occupant leaves this Versatile weapon only one hand (its ordinary printed die).

    The narrow one-way form of versatile_die_sides, kept for callers that only need the "downgraded" fact;
    both read the same occupancy, so there is one implementation of the grip question.
    """
    printed = _versatile_printed_sides(engine, action)
    return bool(printed) and versatile_die_sides(engine, actor, action) == printed[0]


def weapon_damage_dice(ctx: Any) -> bool:
    """True when this attack's dice are the weapon's own damage, so a grip may resize them.

    A Versatile grip changes which printed die the weapon swings with. A technique that printed
    its own die instead (Close Haft Strike's level-table die, whatever weapon delivers it) is not
    weapon damage and keeps the die its row names. Damage taken from the weapon's damage --
    including a technique that adds a flat bonus on top of it -- still is, and follows the grip.

    The answer is the executor's own, via Context.weapon_damage_dice: a technique's printed die can
    be numerically identical to the weapon's (both 1d8), so no comparison of the dice can decide it.
    Default False outside a typed attack, where nothing is a weapon die.

    Used by equipment_hands.versatile_grip_die, the one place a grip rewrites a die.
    """
    return bool(getattr(ctx, "weapon_damage_dice", False))


def versatile_die_sides(engine: Any, actor: Any, action: Any) -> int | None:
    """The die sides a Versatile attack should use with the hands actually free right now.

    Owner 2026-09-26: "the two-handed die unless a shield takes the other hand". Both printed dice are
    read from the catalog weapon, never from the action's own (already grip-selected) die, so this
    resolves in either direction: a weapon compiled one-handed returns to its two-handed die when the
    hand frees up, and one compiled two-handed falls back when an occupant takes the other hand. Only the
    die size changes; the die count stays whatever the technique or ability printed.

    Default-inert: a catalog without the managed-grip policy marker (every historical bundle) returns
    None, so its compiled die is authoritative and no saved fight changes.
    """
    if not supports_grips(engine, actor):
        return None
    printed = _versatile_printed_sides(engine, action)
    requirement = weapon_requirement(engine, action)
    if printed is None or printed[0] == printed[1] or requirement is None:
        return None
    return printed[1] if weapon_capacity(engine, actor, requirement[0]) >= 2 else printed[0]


def weapon_allowed(engine: Any, actor: Any, action: Any, *, effect: dict[str, Any] | None = None) -> bool | None:
    if not supports_grips(engine, actor):
        return None
    from .weapon_hits import available_weapons
    requirement = weapon_requirement(engine, action, effect=effect)
    if requirement is None:
        return None
    identity, count = requirement
    if identity not in available_weapons(engine, actor):
        return False  # Occupying a grip does not make a bound weapon usable.
    ready = weapon_grips(engine, actor)
    if identity not in ready:
        # A source may deliver a technique with a weapon it controls without gripping it (a remote technique
        # origin: Sword-Qi Origin's floating Seed Sword). Providers answer only for that exact weapon, and a
        # True answer supplies the grip this one delivery needs; everything else keeps the ordinary grip rule.
        from . import run_strict
        if not any(answer is True for answer in run_strict('weapon_delivery_without_grip', engine, actor, identity)):
            return False
        return True
    occupied = occupancy(engine, actor, grips=ready)
    if any(p.startswith("occupied:overflow:") for p in occupied):
        return False
    # An off-hand/Light attack needs the pair in both hands, not one spare
    # hand reused after stowing the lead weapon. Ordinary attacks can reuse
    # their own resting grip and genuinely empty hands.
    typed = action.parameters.get("typed") or {}
    if pair_attack(action):
        grips = [owners for p, owners in occupied.items() if p in hand_parts(engine, actor)]
        if sum(len(owners) == 1 and owners[0].startswith("weapon:") for owners in grips) < count:
            return False
        answer = engine.action_catalog.get(identity + "#offhand")
        uses = set(typed.get("uses") or ((answer.parameters.get("typed") or {}).get("uses") if answer else []) or [])
        return any(uses.intersection((weapon.parameters.get("typed") or {}).get("opens") or [])
                   for key, weapon in available_weapons(engine, actor).items() if key in ready)
    properties = (typed.get("weapon") or {}).get("properties") or ""
    flexible = "versatile" in properties.lower() and not re.search(r"\bTwo-Handed\b", properties, re.I)
    return weapon_capacity(engine, actor, identity, occupied=occupied) >= (1 if flexible else count)

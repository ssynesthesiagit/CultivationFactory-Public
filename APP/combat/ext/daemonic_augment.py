"""Daemonic Augment's once-per-turn, choose-one typed augmentation.

The compiled modifier (authority/typed_mechanics) attaches one of six option rows to a
qualifying technique.  Four are ordinary typed effects.  Three printed facts need a
little state, so they live here instead of in the shared executor:

* "increase the movement by 5 feet" is a bonus to the triggering effect's own
  forced movement, never a second push of a chosen creature.  The shared
  forced_movement_bonus seam is the one the other movement-increasing
  talents already use (push_lengthening, brute_shove, flesh_crucible);
* "ignore ordinary Resistance to one of those damage types for that instance"
  asks the owner which type at the damage packet (and never during a preview),
  and never pierces Immunity.  Its types are the six named ones the trigger
  deals and, for the printed "or weapon damage" share, the physical type the
  weapon or Unarmed Strike packet itself names;
* "mark one damaged creature ... gain 1 Devoured Essence" places a mark; the
  Essence is gained on the first damage from the owner, not when the mark is
  applied.

Every one of those paths honours the modifier's once-per-turn gate, including
when a different Augment option was the first one used this round.
Movement and Resistance keep deferred marker rows, so the executor never
sets the gate before the packet or push they describe; those two hooks close it
themselves once their effect has actually landed.
"""

from __future__ import annotations

from typing import Any

from .. import pending_damage
from ..effect_eligibility import modifier_key
from . import effect, hook, needle

AUGMENT = "TAL_DAEMONIC_CULTIVATION_DAEMONIC_AUGMENT"
SPHERE = "tianxia.sphere.daemonic_cultivation"
MARK = "daemonic_augment"
ESSENCE = "resource:named.devoured_essence"
CHOICE = "choice:daemonic_augment."
DAMAGED = "daemonic_augment:damaged"  # first creature this activation damaged (damage_cache, activation-local)
PENDING = "daemonic_augment:pending"  # a Mark Creature waiting for that damage (damage_cache, activation-local)
# The printed list: the six named damage types, and "weapon damage" as the physical types a weapon packet
# actually names (typed_executor.resolve_attack_damage delivers a weapon or Unarmed Strike packet with
# weapon.damage_type, so no packet ever carries a "weapon" kind).
NAMED = ("NECROTIC", "PSYCHIC", "FIRE", "POISON", "ACID", "FORCE")
WEAPON_DAMAGE = ("BLUDGEONING", "PIERCING", "SLASHING")
WALK_KEYS = ("effects", "on_hit", "on_miss", "on_fail", "on_success", "triggers", "inside")


def _rows(node: Any):
    """Every typed row below node, in execution order (the shared walkers' child keys)."""
    if isinstance(node, dict):
        yield node
        for key in WALK_KEYS:
            for child in _rows(node.get(key)):
                yield child
    elif isinstance(node, list):
        for child in node:
            yield from _rows(child)


def _marker(typed: dict[str, Any], kind: str) -> dict[str, Any] | None:
    return next((row for row in _rows(typed.get("effects") or []) if row.get("type") == kind), None)


def _spent(engine: Any, actor: Any, marker: dict[str, Any]) -> bool:
    """The Augment is once per turn, not once per option: any option's gate closes the rest."""
    if actor is None:
        return True
    return bool(marker.get("modifier_once") and actor.turn_flags.get(modifier_key(marker)))


def _spend(engine: Any, actor: Any, marker: dict[str, Any]) -> None:
    if actor is not None and marker.get("modifier_once"):
        actor.turn_flags[modifier_key(marker)] = True


def _damage_types(typed: dict[str, Any]) -> tuple[str, ...]:
    """The printed damage types this trigger deals: its damage rows' named types, and the physical type its
    weapon damage delivers (the printed "or weapon damage" share).  Anything else the trigger might deal is not
    in the printed list, so it is never offered."""
    found: list[str] = []
    for row in _rows(typed.get("effects") or []):
        if row.get("type") in ("damage", "half_damage", "extra_damage"):
            found.extend(str(kind).upper() for kind in row.get("damage_types") or [] if str(kind).upper() in NAMED)
    weapon = typed.get("weapon") or {}
    if weapon or any(row.get("type") == "attack" for row in _rows(typed.get("effects") or [])):
        for key in ("damage_type", "damage_types"):
            value = weapon.get(key)
            kinds = [value] if isinstance(value, str) else list(value or [])
            found.extend(str(kind).upper() for kind in kinds if str(kind).upper() in NAMED + WEAPON_DAMAGE)
    return tuple(dict.fromkeys(found))


def _ordinary_resistance(engine: Any, target: Any, kind: str) -> bool:
    """Whether this target actually has ordinary Resistance to kind (not only a one-shot state)."""
    kind = kind.upper()
    for modifier in (getattr(target, "modifiers", {}) or {}).values():
        if getattr(modifier, "target_field", None) == "damage_resistance" and str(getattr(modifier, "value", "")).upper() == kind:
            return True
    if kind in {str(value).upper() for value in getattr(target, "damage_resistances", ()) or ()}:
        return True
    rows = [*(getattr(engine, "typed_reaction_rows", {}) or {}).get(target.entity_id, []),
            *(getattr(engine, "typed_passive_rows", {}) or {}).get(target.entity_id, [])]
    for row in rows:
        if row.get("block") != "defense" or str(row.get("kind") or "resistance") != "resistance":
            continue
        if kind in {str(value).upper() for value in row.get("damage_types") or []}:
            return True
    return False


def _choice(engine: Any, pending: Any, typed: dict[str, Any], target: Any, kind: str) -> str | None:
    """Ask once per activation which printed damage type this instance ignores."""
    offered = list(_damage_types(typed))
    if not offered:
        return None
    cache = getattr(engine, "_daemonic_augment_choices", None)
    if cache is None:
        cache = engine.__dict__["_daemonic_augment_choices"] = {}
    # One answer per activation. The held intent object itself is compared, not its id(): CPython reuses a freed
    # object's id, so a later activation could otherwise inherit an earlier type.
    intent = getattr(engine, "_active_intent", None)
    held = cache.get("resistance")
    if held is not None and held[0] is intent and held[1] == pending.transaction_id:
        return held[2]
    preferred = [kind.upper()] if kind.upper() in offered else offered
    chooser = engine.state.actors.get(getattr(pending, "source_actor_id", "")) or engine.state.actors.get(
        engine.state.current_actor_id)
    if chooser is None:
        return None
    answer = needle.ask(
        engine, intent, "damage_absorbed", chooser,
        f"{CHOICE}resist.{getattr(target, 'entity_id', 'target')}", offered,
        labels={value: value.title() for value in offered}, preferred=preferred,
        prompt="Daemonic Augment: choose the damage type whose ordinary Resistance this instance ignores.",
        name="Daemonic Augment", feature_id=AUGMENT, target_id=getattr(target, "entity_id", None),
    )
    picked = next((str(value).upper() for value in answer if str(value).upper() in offered), preferred[0])
    cache["resistance"] = (intent, pending.transaction_id, picked)
    return picked


def _immune(engine: Any, target: Any, kind: str, typed: dict[str, Any], source_actor_id: Any, source_id: Any) -> bool:
    """The same Immunity test defend() applies to this packet (typed_reactions.target_immune), read-only."""
    from ..typed_reactions import target_immune

    return target_immune(engine, target, kind, typed, source_actor_id, source_definition_id=source_id)


@hook("resistance_ignored")
def _ignore_resistance(engine: Any, kind: str, typed: dict[str, Any], source_actor_id: str,
                       target: Any) -> bool | None:
    """Daemonic Augment's Ignore Resistance: one printed type, one instance, ordinary Resistance only."""
    if target is None:
        return None
    marker = _marker(typed, "daemonic_augment_resistance")
    if marker is None:
        return None
    pending = pending_damage.current(engine)
    if pending is None:
        return None  # a preview/resistance query, not the packet that pays for the option
    actor = engine.state.actors.get(source_actor_id)
    if _spent(engine, actor, marker):
        return None
    kind = str(kind or "").upper()
    if kind not in _damage_types(typed):
        return None
    if not _ordinary_resistance(engine, target, kind):
        return None
    if _immune(engine, target, kind, typed, source_actor_id, getattr(pending, "source_id", None)):
        return None  # Immunity is never pierced: nothing to ignore, so nothing to ask
    return _choice(engine, pending, typed, target, kind) == kind


@hook("damage_defended")
def _settle_resistance(engine: Any, target: Any, damage_type: Any, source_id: Any,
                       source_actor_id: Any, defenses: dict[str, Any]) -> None:
    """A real packet, after every pure defense query: close the gate and record the bypass once."""
    from ..typed_reactions import _typed

    typed = _typed(engine, source_id)
    marker = _marker(typed, "daemonic_augment_resistance")
    if marker is None or target is None or not source_actor_id:
        return
    actor = engine.state.actors.get(source_actor_id)
    if _spent(engine, actor, marker):
        return
    kind = str(damage_type or "").upper()
    if kind not in _damage_types(typed):
        return
    if not _ordinary_resistance(engine, target, kind):
        return
    if _immune(engine, target, kind, typed, source_actor_id, source_id):
        return  # an Immune target takes no Resistance bypass, so nothing was ignored and nothing is spent
    pending = pending_damage.current(engine)
    if pending is None or _choice(engine, pending, typed, target, kind) != kind:
        return
    if not defenses.get("resistance_suppressed") or defenses.get("resist"):
        return
    _spend(engine, actor, marker)
    engine._append_event(
        "PASSIVE_TRIGGERED", AUGMENT, actor_id=source_actor_id, target_ids=(target.entity_id,),
        payload={"automated": True, "trigger": f"Daemonic Augment ignored ordinary {kind.title()} Resistance."},
    )


@hook("forced_movement_bonus")
def _movement_bonus(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> int | None:
    """Increase the triggering effect's movement by 5 feet, never add a second movement."""
    marker = _marker(ctx.typed, "forced_movement_bonus")
    if marker is None or subject is None:
        return None
    if _spent(ctx.engine, ctx.actor, marker):
        return None
    row_key = ("daemonic_augment_movement", id(effect_row))
    chosen_key = ctx.damage_cache.get(("daemonic_augment_movement", "chosen"))
    if chosen_key is None:
        ctx.damage_cache[("daemonic_augment_movement", "chosen")] = row_key
        chosen_key = row_key
    if chosen_key != row_key:
        return None  # one movement row of the trigger, not every push it prints
    amount = int(marker.get("distance_ft") or marker.get("flat") or 5)
    _spend(ctx.engine, ctx.actor, marker)
    return amount


@hook("damage_dealt")
def _mark_pays_on_damage(ctx: Any, target: Any, amount: int, **kwargs: Any) -> None:
    """The first damage from the marker's owner to the marked creature yields 1 Devoured Essence.

    The same hook places a pending Mark Creature: the mark goes only on a creature this activation's damage
    actually reached (DAMAGED / PENDING are activation-local damage_cache keys, never saved).
    """
    from ..typed_executor import bears_mark, mark_condition_id

    engine, actor = ctx.engine, ctx.actor
    if actor is None or target is None or actor.entity_id == target.entity_id:
        return
    if amount > 0:
        ctx.damage_cache.setdefault(DAMAGED, target)
        pending = ctx.damage_cache.pop(PENDING, None)
        if pending is not None:
            _place_mark(ctx, target, pending)  # the marking damage itself pays nothing; the next hit does
            return
    if not bears_mark(target, actor.entity_id, MARK):
        return
    key = f"once_per_round:{AUGMENT}:mark:{target.entity_id}:{engine.state.round_number}"
    if actor.turn_flags.get(key):
        return
    actor.turn_flags[key] = True
    engine._remove_condition(target, mark_condition_id(MARK, actor.entity_id), AUGMENT)
    if actor.resources.get(ESSENCE) is None or actor.resource_maximums.get(ESSENCE) is None:
        return  # no Devoured Essence pool with its own maximum to gain into: no invented cap, nothing gained
    engine._gain_resource(actor, ESSENCE, 1, AUGMENT)


def _place_mark(ctx: Any, target: Any, marker: dict[str, Any]) -> None:
    """Mark one creature this trigger damaged, until the start of the owner's next turn."""
    from ..typed_executor import mark_condition_id

    condition = mark_condition_id(MARK, ctx.actor.entity_id)
    if any(row.condition_id == condition for row in target.conditions.values()):
        return
    ctx.engine._apply_condition(target, condition, AUGMENT, ctx.actor.entity_id,
                                expires_on="START_OF_SOURCE_NEXT_TURN")
    _spend(ctx.engine, ctx.actor, marker)
    ctx.engine._append_event(
        "PASSIVE_TRIGGERED", AUGMENT, actor_id=ctx.actor.entity_id, target_ids=(target.entity_id,),
        payload={"automated": True, "trigger": f"{ctx.actor.display_name} marks {target.display_name}; "
                                               "the first damage gains 1 Devoured Essence."},
    )


@hook("self_gated_effect")
def _self_gated(ctx: Any, effect: dict[str, Any]) -> bool | None:
    """Mark Creature closes the once-per-turn gate only when its damage lands (_place_mark), never on use."""
    return True if effect.get("type") == "daemonic_augment_mark" else None


@effect("daemonic_augment_mark", harmful=False)
def _mark(ctx: Any, effect: dict[str, Any]) -> None:
    """Mark one creature that this trigger damages. With no damage yet, the mark waits for the first hit."""
    marker = _marker(ctx.typed, "daemonic_augment_mark")
    if marker is None or ctx.actor is None:
        return
    damaged = ctx.damage_cache.get(DAMAGED)
    if damaged is not None:
        _place_mark(ctx, damaged, marker)
    elif DAMAGED not in ctx.damage_cache:
        ctx.damage_cache[PENDING] = marker


@effect("daemonic_augment_resistance", harmful=False)
def _resistance_choice(ctx: Any, effect: dict[str, Any]) -> None:
    """Marker row: the hook above reads it; nothing happens at effect time."""
    return None


@effect("forced_movement_bonus", harmful=False)
def _movement_marker(ctx: Any, effect: dict[str, Any]) -> None:
    """Marker row: the hook above increases the triggering movement; it is not itself a push."""
    return None

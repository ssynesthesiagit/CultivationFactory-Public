"""Erase (CL14) -- tianxia.subpath.qi.void_touched_cultivator.feature.erase.

The whole printed record, one plug-in. Ownership is the foundation's: the
compiled action must carry the family source and the permanent Void Scar
recorded at acquisition (combat/ext/void_touched_cultivator.py), and every hook
here returns early unless the actor owns it. A character without the Secret Law
gets no action at all.

One Action and 6 Qi choose exactly one of the three printed modes. Each printed
mode is its own compiled option (reviewed_final.d/void_touched_erase.json), so a
human and an AI seat see all three and never run two at once.

Erase Manifestation chooses one visible active manifestation within 60 feet from
the fight's real state: a lasting typed area (a field, wall, barrier, persistent
area, Formation function), a summoned Cultivation Asset, or an active typed
condition/modifier on a visible creature (a transformation, talisman effect,
possession tether, projected weapon, temporary technique construct). The
authority comparison is the printed one and reads the manifestation's own Source
CL and save DC through the shared effect readers (combat/ext/end_effect.py,
combat/ext/area_suppression.py, combat/ext/source_eligibility.py). Erasing uses
the record's own teardown: an exact condition/modifier removal, zones.remove for
a lasting area, summons.dismiss for a summoned asset, plus a condition's anchored
area. Nothing refunds a cost, and the creator, learned technique, permanent item
and cultivation system stay (the record says they do not).

Erase Substance chooses a real object, Construct, Cultivation Asset, or corpse
without an active spirit within 60 feet. A living creature, an active-soul corpse
(condition:typed.soul_lingering), an artifact, an unwilling sentient item and a
Secret Anchor are not offered. The 10d10 Void damage is one real roll taken
through the engine's own pipelines: combat/ext/objects.deal for a map object
(ignoring ordinary Resistance and Damage Threshold, treating ordinary Immunity as
Resistance through object_rules.work_out's general seam, and doubling once for a
temporary barrier, summoned object, Formation Anchor, vehicle or structure), and
the ordinary typed damage path for a Construct/Asset (the existing
``immunity_as_resistance`` and ``resistance_ignored`` hooks). A nonartifact
unattended object or material section no larger than a 15-foot cube whose Source
CL is lower than the user's is stamped ``erased`` when its Hit Points reach 0.

Erase Cultivation needs a real creature bearing at least 2 of the user's Void
Marks (the foundation's shared counted mark). The target makes a real Charisma
save (8d8 Void damage, half on a success), loses current Cultivation Points
(2 x PB on a failure, PB on a success), and the user chooses one real system of
that creature (Sphere, Subpath, Method, Golden Core, Nascent Soul, Domain
Armament, Foundation system, Path recovery feature, or named Secret/Immortal
feature) through the family's shared reader. The chosen system is taken off the
fight: its passive/reaction rows are retained and the menu/rows are gated, so it
really cannot be used. An ordinary failed save erases it for 1 minute; a
successful save suppresses it until the start of the target's next turn.

Deep Erasure is a real optional 3-mark spend instead of 2 (asked of a player,
declined by an automatic seat) and applies only on a failed save:

  target CL 6+ lower   the user may erase the system indefinitely (asked);
  target CL 3-5 lower  erased until a successful recovery procedure;
  within 2 CL          the normal 1-minute erasure and a repeated Charisma save
                       at the end of each of its turns after the first;
  target CL 3+ higher  suppressed until the end of its next turn unless the user
                       also succeeds on a Cultivation Check against its save DC.

Recovery from a persistent Deep Erasure is a general, default-inert hook:
``recovery_procedure(engine, target, record) -> True`` is asked when the creature
starts a turn (and ``recover`` is the public out-of-combat entry point). Ordinary
rest, healing, Qi recovery and retraining never call it, so none of them clears
an erased system. The printed recovery authorities are out-of-combat scenes and
are quoted in the record's own report rather than simulated in a fight.

Hooks used (all documented in combat/ext/__init__.py):
  compile_action             seal each mode's real target shape and 60-foot range
  candidate_allowed          a mode with no legal target is not offered; the
                             marks gate for Erase Cultivation
  candidate_unavailability   the plain reason beside that veto
  immunity_as_resistance     a Construct/Asset's Immunity is Resistance
  resistance_ignored         ordinary Resistance is ignored
  event                      give a suppressed system's rows back when it ends
  turn_start                 retake rows after a cold reload; ask recovery
  turn_end                   the within-2-CL repeated save
  status_description         plain words for the suppression pills
"""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from . import IMMUNITY_RESISTANCE_KEPT, effect, hook, note
from .void_touched_cultivator import (
    PARENT,
    PREFIX,
    SYSTEM,
    composed_scar,
    family_source,
    mark_count,
    systems,
    take_system_rows,
    give_back_system_rows,
    creature_cl,
    spend_marks,
)

ERASE = PREFIX + "erase"
SUPPRESSED_MANIFESTATION = "condition:typed.erase_suppressed_manifestation"
CHOICE = "choice:needle."
RANGE_FT = 60
MANIFESTATION = "manifestation"
SUBSTANCE = "substance"
CULTIVATION = "cultivation"
_MODE_BY_LABEL = {
    "Erase Manifestation": MANIFESTATION,
    "Erase Substance": SUBSTANCE,
    "Erase Cultivation": CULTIVATION,
}
# Bookkeeping and death-state rows are not a manifestation the printed list names.
_NOT_A_MANIFESTATION = ("soul_lingering", "death_finalized", "life_unconscious", "life_death_save_mode",
                        "erase_suppressed_manifestation", "zone_effect", "zone_membership",
                        "concentration_deadline", "concentration_held")
_STRUCTURE_KINDS = {"barrier", "formation_anchor", "vehicle", "cart", "produce_cart", "rowboat", "ballista"}


# ------------------------------------------------------------------------------------------------ ownership
def _typed(action: Any) -> dict[str, Any]:
    return (getattr(action, "parameters", None) or {}).get("typed") or {}


def mode_of_typed(typed: dict[str, Any] | None) -> str:
    """The printed Erase mode carried by a typed damage profile."""
    return _MODE_BY_LABEL.get(str((typed or {}).get("option_label") or ""), "")


def mode_of(action: Any) -> str:
    """The printed mode this compiled option runs, or "" for another action."""
    if family_source(action) != ERASE:
        return ""
    return _MODE_BY_LABEL.get(str(_typed(action).get("option_label") or ""), "")


def owned(action: Any) -> bool:
    """The exact acquired feature, sealed with the recorded permanent Void Scar."""
    return family_source(action) == ERASE and bool(composed_scar(action))


def _owns(ctx: Any) -> bool:
    return owned(ctx.action) and getattr(ctx.action, "owner_id", None) == ctx.actor.entity_id


def _numbers(ctx: Any) -> dict[str, Any]:
    return dict(getattr(ctx, "numbers", None) or {})


def _source_cl(ctx: Any) -> int:
    numbers = _numbers(ctx)
    return int(numbers.get("source_cl") or numbers.get("cl") or 1)


# ------------------------------------------------------------------------------------------------ choices
def _ask(ctx: Any, chooser: Any, key: str, options: list[str], *, labels: dict[str, str],
         preferred: list[str], prompt: str, allow_decline: bool = False, name: str = "Erase") -> list[str]:
    from .needle import ask, checkpoint_id

    return ask(ctx.engine, getattr(ctx, "intent", None), checkpoint_id(ctx.engine, key, chooser.entity_id, ctx.actor.entity_id),
               chooser, CHOICE + key, options, labels=labels, preferred=preferred,
               target_id=chooser.entity_id, prompt=prompt, name=name, feature_id=ERASE,
               allow_decline=allow_decline)


def _choose(ctx: Any, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not entries:
        return None
    labels = {entry["key"]: entry["label"] for entry in entries}
    ordered = _preferred_order(entries)
    preferred = [entry["key"] for entry in ordered]
    picked = _ask(ctx, ctx.actor, "erase_target", preferred, labels=labels, preferred=preferred,
                  prompt=(f"Erase: choose one manifestation, object or creature within {RANGE_FT} feet. "
                          "The 6 Qi and the Action are already being spent; this choice adds no cost."))
    key = picked[0] if picked else preferred[0]
    return next((entry for entry in entries if entry["key"] == key), None)


def _targets(entry: dict[str, Any]) -> tuple[Any, ...]:
    holder = entry.get("holder")
    return (holder,) if holder is not None else ()


def _preferred_order(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """An enemy's manifestation/asset first, then a structure, then the rest; stable by key."""
    def rank(entry: dict[str, Any]) -> tuple[int, int, str]:
        enemy = entry.get("enemy")
        structure = bool(entry.get("double"))
        return (0 if enemy else 1, 0 if structure else 1, entry["key"])
    return sorted(entries, key=rank)


# ------------------------------------------------------------------------------------------------ target sets
def _visible(engine: Any, actor: Any, cell: Any) -> bool:
    return bool(engine._line_of_sight_actor_to_cell(actor, cell))


def _within(engine: Any, actor: Any, cells: Any) -> bool:
    return any(engine.grid.distance_ft(actor.position, cell) <= RANGE_FT and _visible(engine, actor, cell)
               for cell in cells)


def _perceives(engine: Any, viewer: Any, target: Any) -> bool:
    from .. import senses

    return viewer.entity_id == target.entity_id or senses.perceives(engine, viewer, target)


def _enemy(engine: Any, user: Any, actor_id: str | None) -> bool:
    from ..relations import relation, ENEMY

    owner = engine.state.actors.get(str(actor_id or ""))
    return owner is not None and relation(engine, user, owner) == ENEMY


_SECRET_AUTHORITY = None


def _authority(engine: Any, source: str) -> dict[str, bool]:
    """Whether a manifestation's own printed record is Secret/Immortal, an artifact, or unknown.

    Reads the owner's printed record through the shared reader (combat/ext/source_eligibility.py).
    The printed clause names "Secret authority" explicitly, so a record that says so in its body
    (Hollow Field: "empowered by Secret authority") is read too, not only a category heading. An
    unidentifiable source fails closed: it may be suppressed but never erased.
    """
    import re

    from . import source_eligibility

    action = source_eligibility.catalog_action(engine, source)
    typed_now = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed_now.get("artifact"):
        return {"secret": False, "artifact": True, "unknown": False}
    if str(typed_now.get("source") or source or "").startswith(PARENT):
        # Every record of this Secret Law is Secret authority by its own family
        # provenance (the foundation's docstring and the owner's Secret Law
        # record), not by a word in display prose.
        return {"secret": True, "artifact": False, "unknown": False}
    power = source_eligibility.printed_power(action)
    if power is None:
        return {"secret": False, "artifact": False, "unknown": True}
    typed, text = power
    global _SECRET_AUTHORITY
    if _SECRET_AUTHORITY is None:
        _SECRET_AUTHORITY = re.compile(r"\b(?:Secret(?: (?:authority|law|inheritance))?|Immortal)\b", re.I)
    secret = source_eligibility.protected_power(typed, text, extra_categories=("Secret", "Immortal")) \
        or bool(_SECRET_AUTHORITY.search(text))
    artifact = bool(typed.get("artifact")) or bool(re.search(r"\bartifact(?:[ -]level)?\b", text, re.I))
    return {"secret": secret, "artifact": artifact, "unknown": False}


def _zone_label(engine: Any, zone: Any) -> str:
    from . import ability_source

    name = ability_source.source_label(engine, zone.source_definition_id) or "a lasting effect"
    profile = zone.trigger_profile or {}
    if profile.get("wall"):
        word = "wall"
    elif (profile.get("rule") or {}).get("no_teleport") or (profile.get("rule") or {}).get("barrier"):
        word = "barrier"
    elif profile.get("formation") or (profile.get("profile") or {}).get("formation"):
        word = "Formation function"
    else:
        word = "lasting area"
    owner = engine.state.actors.get(str(zone.owner_id or ""))
    who = f" from {owner.display_name}" if owner is not None else ""
    return f"{name} ({word}{who})"


def manifestations(engine: Any, user: Any) -> list[dict[str, Any]]:
    """Every visible active manifestation within 60 feet, as the fight really stores it."""
    from .. import zones
    from . import area_suppression, end_effect, ability_source
    from .void_touched_empty_palm import effect_dc, effects_on, source_cl

    reader = SimpleNamespace(engine=engine)
    out: list[dict[str, Any]] = []
    active_zones = [zone for zone in zones.typed_zones(engine) if zone.active]
    for zone in active_zones:
        cells = tuple(zone.affected_cells or (zone.center,))
        if not _within(engine, user, cells):
            continue
        ref = SimpleNamespace(source_definition_id=zone.source_definition_id, source_actor_id=zone.owner_id,
                              instance_id=zone.zone_id)
        authority = _authority(engine, zone.source_definition_id)
        out.append({"kind": "zone", "key": zone.zone_id, "item": zone, "holder": None,
                    "source": zone.source_definition_id, "owner": zone.owner_id,
                    "cl": end_effect.source_cl(reader, ref), "dc": area_suppression.save_dc(engine, zone),
                    "enemy": _enemy(engine, user, zone.owner_id), "double": False,
                    "label": f"{_zone_label(engine, zone)} — Source CL {end_effect.source_cl(reader, ref)}"
                             + (" (Secret authority)" if authority["secret"] else ""),
                    "authority": authority})
    for holder in sorted(engine.state.actors.values(), key=lambda row: row.entity_id):
        if engine._distance_actor_to_actor(user, holder) > RANGE_FT or not _perceives(engine, user, holder):
            continue
        summon = holder.summon or {}
        if summon.get("status") == "present" and holder.active:
            source = str(summon.get("source") or "")
            ref = SimpleNamespace(source_definition_id=source, source_actor_id=str(summon.get("owner") or ""),
                                  instance_id=holder.entity_id)
            authority = _authority(engine, source)
            out.append({"kind": "summon", "key": holder.entity_id, "item": holder, "holder": None,
                        "source": source, "owner": str(summon.get("owner") or ""),
                        "cl": end_effect.source_cl(reader, ref),
                        "dc": effect_dc(reader, "summon", holder),
                        "enemy": _enemy(engine, user, str(summon.get("owner") or "")), "double": False,
                        "label": f"{holder.display_name} — a summoned Cultivation Asset, Source CL "
                                 f"{end_effect.source_cl(reader, ref)}"
                                 + (" (Secret authority)" if authority["secret"] else ""),
                        "authority": authority})
        if not holder.active:
            continue
        for kind, key, item in effects_on(reader, holder):
            name = str(getattr(item, "condition_id", "") if kind == "condition" else getattr(item, "target_field", ""))
            if any(part in name for part in _NOT_A_MANIFESTATION):
                continue
            source = str(getattr(item, "source_definition_id", "") or "")
            authority = _authority(engine, source)
            origin = ability_source.source_label(engine, source) or "an effect"
            out.append({"kind": kind, "key": key, "item": item, "holder": holder,
                        "source": source, "owner": str(getattr(item, "source_actor_id", "") or ""),
                        "cl": source_cl(reader, kind, item), "dc": effect_dc(reader, kind, item),
                        "enemy": _enemy(engine, user, str(getattr(item, "source_actor_id", "") or "")),
                        "double": False,
                        "label": f"{end_effect.describe(engine, kind, item)} from {origin}"
                                 f" on {holder.display_name} — Source CL {source_cl(reader, kind, item)}"
                                 + (" (Secret authority)" if authority["secret"] else ""),
                        "authority": authority})
    return out


def _object_source_cl(engine: Any, obj: Any) -> int:
    from . import objects

    creator = objects.created_by(obj)
    if not creator:
        return 0
    action = engine.action_catalog.get(creator)
    numbers = (((getattr(action, "parameters", None) or {}).get("typed") or {}).get("numbers") or {})
    return int(numbers.get("source_cl") or numbers.get("cl") or 0)


def _object_double(obj: Any) -> bool:
    from ..object_rules import has_tag

    component = obj.component or {}
    return (has_tag(obj, "temporary_barrier") or has_tag(obj, "formation_anchor") or has_tag(obj, "structure")
            or component.get("kind") in _STRUCTURE_KINDS or component.get("vehicle") is True)


def object_target_legal(engine: Any, obj: Any) -> bool:
    """The printed Erase Substance refusal list, read from the object's own sealed fields."""
    component = obj.component or {}
    if obj.destroyed or obj.current_hp is None or obj.maximum_hp is None:
        return False
    if not obj.unattended:
        return False  # a living creature, a wielder, or an actively controlled item is not unattended
    if component.get("artifact") or component.get("secret_anchor"):
        return False
    if component.get("sentient") and component.get("willing") is not True:
        return False  # an unwilling sentient item
    return True


def actor_target_legal(target: Any) -> bool:
    """A Construct, a Cultivation Asset, or a corpse without an active spirit."""
    from .creature_kinds import matches
    from .life_state import SOUL

    if target.active:
        return matches(target, ["construct", "cultivation asset"])
    if int(target.current_hp) > 0:
        return False  # an unconscious living creature is still a living creature
    if any(condition.condition_id == SOUL for condition in target.conditions.values()):
        return False  # a corpse whose soul has not departed
    return not target.summon  # a dismissed summon is not a corpse


def substance_targets(engine: Any, user: Any) -> list[dict[str, Any]]:
    """Every legal Erase Substance target within 60 feet, as objects and creatures really stand."""
    from ..object_geometry import target_cells

    out: list[dict[str, Any]] = []
    for obj in sorted(engine.state.objects.values(), key=lambda row: row.object_id):
        if not object_target_legal(engine, obj):
            continue
        cells = tuple(target_cells(engine, obj))
        if not cells or not _within(engine, user, cells):
            continue
        out.append({"kind": "object", "key": obj.object_id, "item": obj,
                    "cl": _object_source_cl(engine, obj), "double": _object_double(obj),
                    "enemy": _enemy(engine, user, obj.owner_id),
                    "label": (f"{_object_name(obj)} — {'unattended object' if obj.unattended else 'object'}"
                              f", Source CL {_object_source_cl(engine, obj)}")})
    for target in sorted(engine.state.actors.values(), key=lambda row: row.entity_id):
        if not actor_target_legal(target):
            continue
        if engine._distance_actor_to_actor(user, target) > RANGE_FT or not _perceives(engine, user, target):
            continue
        from .creature_kinds import matches
        if matches(target, ["construct"]):
            what = "a Construct"
        elif matches(target, ["cultivation asset"]):
            what = "a Cultivation Asset"
        else:
            what = "a corpse without an active spirit"
        out.append({"kind": "actor", "key": target.entity_id, "item": target,
                    "cl": creature_cl(engine, target), "double": False,
                    "enemy": _enemy(engine, user, target.entity_id),
                    "label": f"{target.display_name} — {what}, Source CL {creature_cl(engine, target)}"})
    return out


def _object_name(obj: Any) -> str:
    from ..object_rules import label

    return label(obj)


def _eligible_creatures(engine: Any, user: Any) -> list[Any]:
    return [target for target in engine.state.actors.values()
            if target.active and mark_count(target, user.entity_id) >= 2]


# ------------------------------------------------------------------------------------------------ mode: Erase Manifestation
def erase_manifestation(ctx: Any) -> None:
    from .. import zones
    from . import area_suppression, ability_source, end_effect
    from .effect_durations import round_token

    engine, user = ctx.engine, ctx.actor
    entries = manifestations(engine, user)
    if not entries:
        ctx.rider(f"Erase — Erase Manifestation: no visible active manifestation stands within {RANGE_FT} feet.")
        return
    chosen = _choose(ctx, entries)
    if chosen is None:
        return
    label = str(chosen["label"])
    mine = _source_cl(ctx)
    theirs = int(chosen["cl"])
    authority = chosen.get("authority") or {}
    dc = int(chosen["dc"])
    if not authority.get("secret") and not authority.get("artifact") and not authority.get("unknown") and theirs < mine:
        if _erase(ctx, chosen):
            note(engine, ERASE, user, f"Erase — Erase Manifestation: {label} is erased at once (its non-Secret "
                                      f"Source CL {theirs} is lower than {mine}).", _targets(chosen))
        return
    if authority.get("artifact"):
        if _cultivation_check(ctx, dc, label):
            _suppress_minute(ctx, chosen, round_token)
        return
    if authority.get("secret") or authority.get("unknown") or theirs > mine:
        if not _cultivation_check(ctx, dc, label):
            note(engine, ERASE, user, f"Erase — Erase Manifestation: the Cultivation Check fails; {label} stays.", _targets(chosen))
            return
        if authority.get("secret") and not authority.get("unknown") and mine > theirs and _erase(ctx, chosen):
            note(engine, ERASE, user, f"Erase — Erase Manifestation: {label} is erased (Secret authority, and your "
                                      f"Source CL {mine} exceeds its {theirs}).", _targets(chosen))
            return
        _suppress_minute(ctx, chosen, round_token)
        return
    if _cultivation_check(ctx, dc, label):
        if _erase(ctx, chosen):
            note(engine, ERASE, user, f"Erase — Erase Manifestation: {label} is erased (equal Source CL {theirs}, "
                                      "Cultivation Check succeeded).", _targets(chosen))


def _cultivation_check(ctx: Any, dc: int, label: str) -> bool:
    from .ability_source import cultivation_check_detail

    roll, success = cultivation_check_detail(ctx.engine, ctx.actor, _numbers(ctx), dc, ctx.source)
    note(ctx.engine, ctx.source, ctx.actor,
         f"Erase — Erase Manifestation: Cultivation Check {int(roll.total)} against DC {dc} for {label}: "
         f"{'success' if success else 'failure'}.", ())
    return success


def _erase(ctx: Any, entry: dict[str, Any]) -> bool:
    from .. import zones
    from .. import summons
    from . import end_effect

    engine, user = ctx.engine, ctx.actor
    kind, item = entry["kind"], entry["item"]
    if kind in ("condition", "modifier"):
        holder = entry.get("holder")
        if holder is None:
            return False
        anchored = _anchored_areas(engine, holder, item)  # read before the removal can add its own inside rows
        end_effect.remove_instance(ctx, holder, kind, entry["key"], item)
        rows = holder.conditions if kind == "condition" else holder.modifiers
        removed = entry["key"] not in rows
        if removed:
            for zone in anchored:
                zones.remove(engine, zone, "ERASED")
        return bool(removed)
    if kind == "zone":
        zones.remove(engine, item, "ERASED")
        return True
    if kind == "summon":
        summons.dismiss(engine, item, "ERASED", log=f"Erase — Erase Manifestation: {item.display_name} is unmade.")
        return True
    return False


def _anchored_areas(engine: Any, holder: Any, item: Any) -> list[Any]:
    """Lasting areas this exact effect is the sole Anchor of (the record's dependent-function clause)."""
    from .. import zones

    source = str(getattr(item, "source_definition_id", "") or "")
    if not source:
        return []
    siblings = [condition for condition in holder.conditions.values()
                if condition is not item and str(condition.source_definition_id or "") == source]
    if siblings:
        return []
    return [zone for zone in zones.typed_zones(engine)
            if str((zone.trigger_profile or {}).get("anchor_id") or "") == holder.entity_id
            and zone.source_definition_id == source and zone.active]


def _suppress_minute(ctx: Any, entry: dict[str, Any], round_token: Any) -> None:
    from . import area_suppression, end_effect

    engine, user = ctx.engine, ctx.actor
    kind, item = entry["kind"], entry["item"]
    expiry = round_token(engine, 10)  # 1 minute is ten rounds
    if kind in ("condition", "modifier"):
        holder = entry.get("holder")
        if holder is None:
            return
        end_effect.suppress(holder, kind, entry["key"], item, rounds=10, by=user, engine=engine, boundary="end")
    elif kind == "zone":
        area_suppression.suppress(engine, user, item, expiry, ctx.source)
    elif kind == "summon":
        engine._apply_condition(item, SUPPRESSED_MANIFESTATION, ctx.source, user.entity_id, expires_on=expiry,
                                data={"rule": {"no_actions": True, "no_reactions": True, "speed_zero": True},
                                      "label": (f"Erase — Erase Manifestation: {item.display_name}'s projected form "
                                                "cannot act, take Reactions or move for 1 minute; it remains on the "
                                                "table."),
                                      "source_cl": _source_cl(ctx)})
    note(engine, ERASE, user, f"Erase — Erase Manifestation: {entry['label']} is suppressed for 1 minute. Its "
                              "duration keeps running and its cost is not refunded.", _targets(entry))


# ------------------------------------------------------------------------------------------------ mode: Erase Substance
def _roll_10d10(ctx: Any) -> list[tuple[int, str]]:
    from ..gate2_runtime_models import DiceSpec

    rolled = ctx.engine.roller.roll(DiceSpec(count=10, sides=10, modifier=0), actor_id=ctx.actor.entity_id,
                                    reason=f"DAMAGE:{ctx.source}:erase")
    ctx.engine._record_roll(rolled)
    return [(int(rolled.total), "VOID")]


def erase_substance(ctx: Any) -> None:
    from . import objects
    from .. import typed_executor

    engine, user = ctx.engine, ctx.actor
    entries = substance_targets(engine, user)
    if not entries:
        ctx.rider(f"Erase — Erase Substance: no unattended object, Construct, Cultivation Asset, corpse without an "
                  f"active spirit, or nonliving material stands within {RANGE_FT} feet.")
        return
    chosen = _choose(ctx, entries)
    if chosen is None:
        return
    if chosen["kind"] == "object":
        obj = engine.state.objects.get(chosen["item"].object_id)
        if obj is None or obj.destroyed:
            ctx.rider("Erase — Erase Substance: that object is already gone.")
            return
        packets = _roll_10d10(ctx)
        result = objects.deal(engine, user, obj, packets, ctx.source, ignore_threshold=True,
                              ignore_resistance=True, immunity_as_resistance=True,
                              multiplier=2 if chosen["double"] else 1)
        note(engine, ERASE, user,
             f"Erase — Erase Substance: {chosen['label']} takes {int(result.get('total') or 0)} Void damage"
             + (" (double damage: a temporary barrier, summoned object, Formation Anchor, vehicle or structure)"
                if chosen["double"] else "")
             + ".", ())
        _complete_erasure(ctx, obj, result)
        return
    target = engine.state.actors.get(chosen["item"].entity_id)
    if target is None:
        ctx.rider("Erase — Erase Substance: that target is no longer on the table.")
        return
    ctx.damage_cache["_potency_used"] = True  # the printed amount is exactly 10d10
    typed_executor.run_effects(replace(ctx, targets=[target], target=target),
                               [{"type": "damage", "applies_to": "target", "dice": {"count": 10, "sides": 10},
                                 "damage_types": ["void"], "evidence": "The target takes 10d10 Void damage."}])
    note(engine, ERASE, user,
         f"Erase — Erase Substance: {chosen['label']} takes 10d10 Void damage. It ignores ordinary Resistance and "
         "Damage Threshold, and treats ordinary Immunity as Resistance.", (target,))


def _complete_erasure(ctx: Any, obj: Any, result: dict[str, Any]) -> None:
    """The printed complete-erasure clause: a nonartifact unattended body no larger than a 15-ft cube."""
    if not result.get("destroyed") or not object_target_legal(ctx.engine, obj):
        return
    if _object_source_cl(ctx.engine, obj) >= _source_cl(ctx):
        return
    component = obj.component or {}
    width = component.get("width_cells", 1)
    length = component.get("length_cells", 1)
    if int(width) > 3 or int(length) > 3:
        return
    if obj.height_ft is not None and int(obj.height_ft) > 15:
        return
    if str(component.get("size") or "").lower() in ("huge", "gargantuan"):
        return
    current = ctx.engine.state.objects.get(obj.object_id) or obj
    after = type(current).model_validate({**current.model_dump(mode="json"),
                                          "component": {**(current.component or {}), "erased": 1}})
    ctx.engine._update_object(after, ctx.source, ctx.actor.entity_id)
    note(ctx.engine, ERASE, ctx.actor,
         f"Erase — Erase Substance: the nonartifact unattended body of {_object_name(obj)} (Source CL "
         f"{_object_source_cl(ctx.engine, obj)} is lower than yours) is erased completely; nothing remains to repair.",
         ())


# ------------------------------------------------------------------------------------------------ mode: Erase Cultivation
def erase_cultivation(ctx: Any) -> None:
    from .effect_durations import holder_next_turn, round_token

    engine, user = ctx.engine, ctx.actor
    target = getattr(ctx, "target", None)
    if target is None or target.entity_id not in engine.state.actors:
        ctx.rider("Erase — Erase Cultivation: the chosen creature is no longer on the table.")
        return
    if ctx.damage_cache.get("_erase_marks_spent"):
        return
    commitment = ctx.damage_cache.get("_erase_commitment")
    marks = mark_count(target, user.entity_id)
    if not (commitment and commitment.get("target") == target.entity_id) and marks < 2:
        ctx.rider(f"Erase — Erase Cultivation: {target.display_name} bears {marks} of your Void Marks, and this mode "
                  "needs at least 2.")
        return
    failed = bool(getattr(ctx, "failed_save", False))
    if commitment and commitment.get("target") == target.entity_id:
        deep = bool(commitment["deep"])
    else:
        # Direct callers and older compiled effects keep the same activation semantics.
        deep = marks >= 3 and _ask_deep(ctx, target)
        spent = 3 if deep else 2
        if not spend_marks(engine, user, target, spent, ctx.source, note="Erase — Erase Cultivation"):
            ctx.rider("Erase — Erase Cultivation: the Void Marks are no longer there to spend.")
            return
    ctx.damage_cache["_erase_marks_spent"] = 1
    pb = int(_numbers(ctx).get("pb") or getattr(user, "proficiency_bonus", 0) or 0)
    wanted = 2 * pb if failed else pb
    pool = _pool(ctx, target)
    if pool is not None and wanted > 0:
        took = min(wanted, int(target.resources.get(pool) or 0))
        if took:
            engine._spend_resource(target, pool, took, ctx.source)
    chosen = _choose_system(ctx, target)
    if chosen is None:
        note(engine, ERASE, user, f"Erase — Erase Cultivation: {target.display_name} carries no cultivation system "
                                  "this table tracks, so only the damage and Cultivation Point loss apply.", (target,))
        return
    if failed:
        _erase_system(ctx, target, chosen, deep=deep, holder_next_turn=holder_next_turn, round_token=round_token)
    else:
        _suppress_system(ctx, target, chosen, holder_next_turn(target, "start"), persistent=False)
        note(engine, ERASE, user,
             f"Erase — Erase Cultivation: {target.display_name} succeeds on its Charisma save; its "
             f"{chosen['label']} is suppressed until the start of its next turn.", (target,))


def _ask_deep(ctx: Any, target: Any) -> bool:
    picked = _ask(ctx, ctx.actor, "erase_deep", ["normal", "deep"],
                  labels={"normal": "Normal: spend 2 Void Marks; erase for 1 minute",
                          "deep": "Deep Erasure: spend 3 Void Marks; longer erasure by Source CL"},
                  preferred=["normal"],
                  prompt=(f"Erase — Erase Cultivation on {target.display_name}: spend 3 of your Void Marks instead of "
                          "2 for Deep Erasure? Deep Erasure changes how long the chosen system stays erased."))
    return bool(picked) and picked[0] == "deep"


def _choose_system(ctx: Any, target: Any) -> dict[str, str] | None:
    options = systems(ctx.engine, target)
    if not options:
        return None
    keys = [f"{row['kind']}|{row['value']}" for row in options]
    labels = {f"{row['kind']}|{row['value']}": row["label"] for row in options}
    picked = _ask(ctx, ctx.actor, "erase_system", keys, labels=labels, preferred=keys,
                  prompt=(f"Erase — Erase Cultivation: choose one real cultivation system of {target.display_name} "
                          "to take out of active use. This is the user's choice, not the target's."))
    key = picked[0] if picked else keys[0]
    return next((row for row in options if f"{row['kind']}|{row['value']}" == key), options[0])


def _pool(ctx: Any, target: Any) -> str | None:
    pools = [pool for pool in ("resource:core.qi", "resource:core.stamina", "resource:core.resonance")
             if int(target.resources.get(pool) or 0) > 0]
    if not pools:
        return None
    names = {"resource:core.qi": "Qi", "resource:core.stamina": "Stamina", "resource:core.resonance": "Resonance"}
    preferred = [max(pools, key=lambda pool: (int(target.resources.get(pool) or 0), -pools.index(pool)))]
    picked = _ask(ctx, target, "erase_pool", pools,
                  labels={pool: f"{names[pool]} ({int(target.resources.get(pool) or 0)} left)" for pool in pools},
                  preferred=preferred,
                  prompt=(f"Erase — Erase Cultivation: {target.display_name} loses current Cultivation Points. "
                          "Choose which pool loses them (twice the user's Proficiency Bonus on a failed save, the "
                          "Proficiency Bonus on a successful one)."))
    return picked[0] if picked else preferred[0]


def _erase_system(ctx: Any, target: Any, chosen: dict[str, str], *, deep: bool,
                  holder_next_turn: Any, round_token: Any) -> None:
    engine, user = ctx.engine, ctx.actor
    if not deep:
        _apply_system(ctx, target, chosen, round_token(engine, 10), persistent=False, extra={"band": "minute"})
        note(engine, ERASE, user, f"Erase — Erase Cultivation: {target.display_name} fails its Charisma save; its "
                                  f"{chosen['label']} is erased from active use for 1 minute.", (target,))
        return
    from .. import typed_executor

    delta = creature_cl(engine, target) - _source_cl(ctx)
    if delta <= -6:
        indefinite = _ask_indefinite(ctx, target)
        if indefinite:
            _apply_system(ctx, target, chosen, "UNTIL_REMOVED", persistent=True, extra={"band": "indefinite"})
            note(engine, ERASE, user, f"Erase — Deep Erasure: {target.display_name} is 6 or more Source CL below you; "
                                      f"its {chosen['label']} is erased indefinitely until a listed recovery authority "
                                      "restores it.", (target,))
        else:
            _apply_system(ctx, target, chosen, round_token(engine, 10), persistent=False, extra={"band": "minute"})
            note(engine, ERASE, user, f"Erase — Deep Erasure: {target.display_name} fails its save; its "
                                      f"{chosen['label']} is erased for 1 minute.", (target,))
        return
    if -5 <= delta <= -3:
        _apply_system(ctx, target, chosen, "UNTIL_REMOVED", persistent=True, extra={"band": "recovery"})
        note(engine, ERASE, user, f"Erase — Deep Erasure: {target.display_name} is 3-5 Source CL below you; its "
                                  f"{chosen['label']} stays unusable until it completes a successful recovery "
                                  "procedure (ordinary rest, healing, Qi recovery and retraining do not restore it).",
             (target,))
        return
    if -2 <= delta <= 2:
        dc = int(_numbers(ctx).get("save_dc") or _numbers(ctx).get("dc") or 8)
        _apply_system(ctx, target, chosen, round_token(engine, 10), persistent=False,
                      extra={"band": "repeat", "deep_repeat": 1, "repeat_dc": dc,
                             "applied_turn": int(getattr(target, "turns_started", 0))})
        note(engine, ERASE, user, f"Erase — Deep Erasure: {target.display_name} is within 2 Source CL of you; its "
                                  f"{chosen['label']} is erased for 1 minute and it repeats the Charisma save at the "
                                  "end of each of its turns after the first.", (target,))
        return
    # A target 3 or more Source CL higher: suppress until the end of its next turn unless the check succeeds.
    from .ability_source import cultivation_check_detail

    roll, success = cultivation_check_detail(engine, user, _numbers(ctx), _target_dc(engine, target), ctx.source)
    if success:
        _apply_system(ctx, target, chosen, round_token(engine, 10), persistent=False, extra={"band": "minute"})
        note(engine, ERASE, user, f"Erase — Deep Erasure: the Cultivation Check {int(roll.total)} succeeds against "
                                  f"{target.display_name}'s save DC; its {chosen['label']} is erased for 1 minute.",
             (target,))
    else:
        _apply_system(ctx, target, chosen, holder_next_turn(target, "end"), persistent=False,
                      extra={"band": "next_turn", "label_duration": "until the end of its next turn"})
        note(engine, ERASE, user, f"Erase — Deep Erasure: the Cultivation Check {int(roll.total)} fails; "
                                  f"{target.display_name}'s {chosen['label']} is only suppressed until the end of its "
                                  "next turn.", (target,))


def _ask_indefinite(ctx: Any, target: Any) -> bool:
    picked = _ask(ctx, ctx.actor, "erase_indefinite", ["indefinite", "minute"],
                  labels={"indefinite": "Erase it indefinitely (only a listed recovery authority restores it)",
                          "minute": "Erase it for 1 minute"},
                  preferred=["indefinite"],
                  prompt=(f"Erase — Deep Erasure: {target.display_name} is 6 or more Source CL below you. Erase its "
                          "chosen system indefinitely, or only for 1 minute?"))
    return not picked or picked[0] == "indefinite"


def _target_dc(engine: Any, target: Any) -> int:
    from .end_effect import cultivation_dc

    return int(cultivation_dc(engine, target))


def _apply_system(ctx: Any, target: Any, chosen: dict[str, str], expires_on: str, *, persistent: bool,
                  extra: dict[str, Any] | None = None) -> None:
    engine, user = ctx.engine, ctx.actor
    _clear_erase_system(ctx, target, chosen)
    extra = dict(extra or {})
    if persistent:
        duration = "until a listed recovery authority restores it."
    elif extra.get("label_duration"):
        duration = f"{extra['label_duration']}."
    else:
        duration = "for 1 minute."
    data = {"kind": chosen["kind"], "value": chosen["value"], "label": chosen["label"],
            "rows": take_system_rows(engine, target, chosen["kind"], chosen["value"]),
            "erase_origin": ERASE, "erase": 1, "persistent": 1 if persistent else 0,
            "source_cl": _source_cl(ctx),
            "label_text": (f"Erase — {'Deep Erasure' if persistent else 'Erase Cultivation'}: "
                           f"{target.display_name}'s {chosen['label']} is out of active use {duration}"),
            **extra}
    engine._apply_condition(target, SYSTEM, ctx.source, user.entity_id, expires_on=expires_on, data=data)


def _suppress_system(ctx: Any, target: Any, chosen: dict[str, str], expires_on: str, *, persistent: bool) -> None:
    engine, user = ctx.engine, ctx.actor
    _clear_erase_system(ctx, target, chosen)
    data = {"kind": chosen["kind"], "value": chosen["value"], "label": chosen["label"],
            "rows": take_system_rows(engine, target, chosen["kind"], chosen["value"]),
            "erase_origin": ERASE, "erase": 0, "persistent": 0, "source_cl": _source_cl(ctx),
            "label_text": (f"Erase — Erase Cultivation: {target.display_name}'s {chosen['label']} is suppressed until "
                           "the start of its next turn.")}
    engine._apply_condition(target, SYSTEM, ctx.source, user.entity_id, expires_on=expires_on, data=data)


def _clear_erase_system(ctx: Any, target: Any, chosen: dict[str, str]) -> None:
    """One Erase suppression per system: end an earlier one first (its rows come back eventfully)."""
    for instance_id, condition in list(target.conditions.items()):
        data = condition.data or {}
        if (condition.condition_id == SYSTEM and data.get("erase_origin") == ERASE
                and data.get("kind") == chosen["kind"] and data.get("value") == chosen["value"]):
            ctx.engine._remove_condition_instance(target, instance_id, ctx.source,
                                                  payload={"condition_id": SYSTEM, "instance_id": instance_id,
                                                           "reason": "REPLACED"})


# ------------------------------------------------------------------------------------------------ system gates and lifetime
def _active_erase_system(engine: Any, actor: Any) -> dict[str, Any] | None:
    for condition in actor.conditions.values():
        data = condition.data or {}
        if condition.condition_id == SYSTEM and data.get("erase_origin") == ERASE:
            return data
    return None


def _gates(engine: Any, actor: Any, source: str, sphere: str = "") -> bool:
    for condition in actor.conditions.values():
        data = condition.data or {}
        if condition.condition_id != SYSTEM or data.get("erase_origin") != ERASE:
            continue
        from .void_touched_cultivator import covers

        if covers(data, source, sphere):
            return True
    return False


@hook("candidate_allowed")
def gate_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """An erased/suppressed system is not offered; a mode with no legal target is not offered.

    The system gate applies to every actor's own actions, not only to Erase's
    actions: that is how Erase Cultivation really stops a target using its
    erased Sphere/Subpath/Method. The mode gates below apply only to the owner's
    Erase options.
    """
    if actor is None or action is None:
        return None
    typed = _typed(action)
    source = str(typed.get("source") or "")
    sphere = str(typed.get("sphere") or "")
    if (source or sphere) and _gates(engine, actor, source, sphere):
        return False
    mode = mode_of(action)
    if not mode or getattr(action, "owner_id", None) != actor.entity_id:
        return None
    if getattr(candidate, "metadata", None) and candidate.metadata.get("lazy_action"):
        return None  # the header is a menu entry; the expanded candidates are gated below
    if mode == MANIFESTATION:
        return True if manifestations(engine, actor) else False
    if mode == SUBSTANCE:
        return True if substance_targets(engine, actor) else False
    if mode == CULTIVATION:
        target_id = next(iter(getattr(candidate, "target_ids", None) or ()), None)
        target = engine.state.actors.get(str(target_id or ""))
        return target is not None and mark_count(target, actor.entity_id) >= 2
    return None


@hook("row_allowed")
def gate_rows(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    if actor is None:
        return None
    source = str(row.get("feature_id") or "")
    sphere = str(row.get("sphere") or "")
    if not source and not sphere:
        return None
    return False if _gates(engine, actor, source, sphere) else None


@hook("candidate_unavailability")
def unavailable(engine: Any, actor: Any, candidate: Any, action: Any) -> str | None:
    mode = mode_of(action)
    if not mode or getattr(action, "owner_id", None) != actor.entity_id:
        return None
    if getattr(candidate, "metadata", None) and candidate.metadata.get("lazy_action"):
        return None
    if mode == MANIFESTATION and not manifestations(engine, actor):
        return f"Erase Manifestation needs one visible active manifestation within {RANGE_FT} feet."
    if mode == SUBSTANCE and not substance_targets(engine, actor):
        return (f"Erase Substance needs an unattended object, Construct, Cultivation Asset or corpse without an "
                f"active spirit within {RANGE_FT} feet; living creatures, artifacts and Secret Anchors cannot be "
                "targeted.")
    if mode == CULTIVATION:
        target_id = next(iter(getattr(candidate, "target_ids", None) or ()), None)
        target = engine.state.actors.get(str(target_id or ""))
        if target is None:
            return None
        mine = mark_count(target, actor.entity_id)
        if mine < 2:
            return (f"Erase Cultivation needs a creature bearing at least 2 of your Void Marks; "
                    f"{target.display_name} bears {mine}.")
    return None


@hook("event")
def restore_system_rows(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Give a suppressed system's rows back when its Erase condition ends, however it ended."""
    if event_type != "CONDITION_REMOVED":
        return
    ended = kwargs.get("ended_effect") or (kwargs.get("payload") or {}).get("removed_condition")
    if not isinstance(ended, dict) or ended.get("condition_id") != SYSTEM:
        return
    data = ended.get("data") or {}
    if data.get("erase_origin") != ERASE:
        return
    target = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
    if target is not None:
        give_back_system_rows(engine, target, data)


@hook("turn_start")
def reconcile_and_recover(engine: Any, actor: Any) -> None:
    """Retake rows a cold reload rebuilt, then ask the general recovery contract."""
    for holder in list(engine.state.actors.values()):
        for condition in list(holder.conditions.values()):
            data = condition.data or {}
            if condition.condition_id != SYSTEM or data.get("erase_origin") != ERASE:
                continue
            take_system_rows(engine, holder, str(data.get("kind") or ""), str(data.get("value") or ""))
    for condition in list(actor.conditions.values()):
        data = condition.data or {}
        if (condition.condition_id != SYSTEM or data.get("erase_origin") != ERASE
                or not int(data.get("persistent") or 0)):
            continue
        if _recovery_authority(engine, actor, data):
            _release(engine, actor, condition, "RECOVERED")
            note(engine, ERASE, actor,
                 f"Erase — Deep Erasure: a listed recovery authority restores {actor.display_name}'s "
                 f"{data.get('label') or 'erased system'}.", (actor,))


def _recovery_authority(engine: Any, target: Any, data: dict[str, Any]) -> bool:
    """The general, default-inert recovery contract; no handler means the system stays erased."""
    from . import run_strict

    record = {key: data.get(key) for key in ("kind", "value", "label", "source_cl", "band") if data.get(key) is not None}
    return any(reply is True for reply in run_strict("recovery_procedure", engine, target, record))


def _release(engine: Any, target: Any, condition: Any, reason: str) -> None:
    for instance_id, held in list(target.conditions.items()):
        if held is condition:
            engine._remove_condition_instance(target, instance_id, ERASE,
                                              payload={"condition_id": SYSTEM, "instance_id": instance_id,
                                                       "reason": reason})
            return


def recover(engine: Any, target: Any, reason: str = "RECOVERY") -> int:
    """Clear persistent Deep Erasure only after a handler verifies a printed authority.

    The general recovery_procedure contract checks the erased system against the authority
    that actually occurred; an arbitrary caller-supplied reason is never proof. It never
    clears the ordinary 1-minute erasure, which the engine's own clock ends.
    """
    cleared = 0
    for condition in list(target.conditions.values()):
        data = condition.data or {}
        if (condition.condition_id == SYSTEM and data.get("erase_origin") == ERASE
                and int(data.get("persistent") or 0)
                and _recovery_authority(engine, target, data)):
            _release(engine, target, condition, "RECOVERED")
            cleared += 1
    return cleared


@hook("turn_end")
def repeat_save(engine: Any, actor: Any) -> None:
    """A target within 2 CL repeats the Charisma save at the end of each of its turns after the first."""
    for condition in list(actor.conditions.values()):
        data = condition.data or {}
        if (condition.condition_id != SYSTEM or data.get("erase_origin") != ERASE
                or not int(data.get("deep_repeat") or 0)):
            continue
        if int(getattr(actor, "turns_started", 0)) <= int(data.get("applied_turn") or 0) + 1:
            continue
        dc = int(data.get("repeat_dc") or 0)
        roll = engine._roll_save(actor, "CHA", dc, ERASE)
        if roll is not None and int(roll.total) >= dc:
            _release(engine, actor, condition, "SAVE_SUCCEEDED")
            note(engine, ERASE, actor,
                 f"Erase — Deep Erasure: {actor.display_name} repeats its Charisma save ({int(roll.total)} against "
                 f"DC {dc}) and its {data.get('label') or 'erased system'} is no longer erased.", (actor,))


# ------------------------------------------------------------------------------------------------ damage semantics
@hook("immunity_as_resistance")
def erase_immunity(engine: Any, kind: str, typed: dict[str, Any], source_actor_id: str | None, target: Any) -> Any:
    """Erase Substance: ordinary Immunity is only Resistance, and that Resistance is not ignored.

    The printed clause has two separate sentences -- "Ignores ordinary Resistance" and
    "Treats ordinary Immunity as Resistance" -- so the converted Resistance is the
    Immunity's own rule. ``IMMUNITY_RESISTANCE_KEPT`` tells the shared damage reader to
    keep the halving even though ``erase_resistance`` ignores the creature's own
    ordinary Resistance; any other source keeps the documented downgrade-then-ignore chain.
    """
    if str((typed or {}).get("source") or "") != ERASE or mode_of_typed(typed) != SUBSTANCE:
        return None
    return IMMUNITY_RESISTANCE_KEPT


@hook("resistance_ignored")
def erase_resistance(engine: Any, kind: str, typed: dict[str, Any], source_actor_id: str | None,
                     target: Any = None) -> bool | None:
    """Erase Substance: ordinary Resistance is ignored."""
    if str((typed or {}).get("source") or "") != ERASE or mode_of_typed(typed) != SUBSTANCE:
        return None
    return True


# ------------------------------------------------------------------------------------------------ compilation and plain words
@hook("compile_action")
def shape_erase(action: Any, info: dict[str, Any]) -> Any:
    """Each printed mode's real target shape and its 60-foot range."""
    mode = mode_of(action)
    if not mode:
        return None
    typed = {**_typed(action), "range_ft": RANGE_FT}
    target_kind = "ANY_CREATURE" if mode == CULTIVATION else "SELF"
    return action.model_copy(update={"target_kind": target_kind, "range_ft": RANGE_FT,
                                     "parameters": {**action.parameters, "typed": typed}})


@hook("status_description")
def plain_status(engine: Any, holder: Any, row: Any, data: Any) -> dict[str, Any] | None:
    condition_id = str((row or {}).get("condition_id") or "")
    data = data or {}
    if condition_id == SYSTEM and data.get("erase_origin") == ERASE:
        text = str(data.get("label_text") or "One of its cultivation systems is out of use (Erase).")
        return {"text": text, "display_name": text, "source_ability": "Erase"}
    if condition_id == SUPPRESSED_MANIFESTATION:
        return {"text": str(data.get("label") or "A projection cannot act (Erase)."),
                "display_name": str(data.get("label") or "Suppressed manifestation"),
                "source_ability": "Erase"}
    return None


@effect("void_touched_erase")
def erase_operation(ctx: Any, row: dict[str, Any]) -> None:
    """Resolve the chosen printed mode once per activation."""
    if not _owns(ctx):
        return
    operation = str(row.get("operation") or "")
    if operation == "commitment":
        target = getattr(ctx, "target", None)
        if target is None:
            return
        marks = mark_count(target, ctx.actor.entity_id)
        deep = marks >= 3 and _ask_deep(ctx, target)
        spent = 3 if deep else 2
        if not spend_marks(ctx.engine, ctx.actor, target, spent, ctx.source, note="Erase — Erase Cultivation"):
            return
        ctx.damage_cache["_erase_commitment"] = {"target": target.entity_id, "deep": deep}
    elif operation == MANIFESTATION:
        erase_manifestation(ctx)
    elif operation == SUBSTANCE:
        erase_substance(ctx)
    elif operation == CULTIVATION:
        erase_cultivation(ctx)

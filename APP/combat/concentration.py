"""Holding Concentration techniques without a capacity ceiling (owner continuation ruling:
"a creature can hold any number of concentration techniques, including the same technique
several times, unless they are the same stacking buff"). The earlier CL-based capacity
remains an explicitly selectable rules mode, not the default.

A damaging hit still calls for one Concentration save, and a failure ends only the
most recently started technique. In the legacy capped mode, overflow ends the
oldest. The compiler seals the rules from combat/rules/concentration.json in new
bundles; older bundles retain the original CL1/5/10/15/20 ceilings of 1/2/3/4/5.

The engine's own ``actor.concentration`` stays the most recent one (every check that reads it keeps working); the older
ones are held as conditions (HELD, data "held": the ConcentrationState), applied and removed through the engine's evented
methods, so a saved fight replays them with no change to the saved state. gate2_engine._start_concentration holds the
current one before starting another, and _end_concentration brings the most recent held one back when the current one
ends.

The same technique may be held more than once. Every copy has its own start (ConcentrationState
started_sequence, the sequence of its CONCENTRATION_STARTED event), and what a copy made is told apart from another copy's
of the same technique by when it was made -- an effect belongs to the newest copy that had begun by then -- so ending one
copy takes its own zone, conditions, modifiers and no other's (a Darkness that is still up keeps its own). A buff on a
creature does not stack across copies: the newer one's effect replaces the older's same effect on that creature (supersede,
called from combat/ext/concentration_copies.py); copies aimed at different creatures or areas all stay.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HELD = "condition:typed.concentration_held"
_RULES = Path(__file__).resolve().parent / "rules" / "concentration.json"
_cache: dict[str, Any] = {}
_LEGACY_RULES = {"capacity": "cultivation_level", "limits_by_cl": [[1, 1], [5, 2], [10, 3], [15, 4], [20, 5]]}


def rules() -> dict[str, Any]:
    stamp = _RULES.stat().st_mtime if _RULES.is_file() else 0
    if _cache.get("stamp") != stamp:
        _cache.update(stamp=stamp, rules=json.loads(_RULES.read_text(encoding="utf-8")) if _RULES.is_file() else {})
    return _cache["rules"]


def limit_for_cl(cl: int, configured: dict[str, Any] | None = None) -> int | None:
    """Configured capacity, or None for unlimited; no numeric sentinel or stored infinity."""
    configured = rules() if configured is None else configured
    if configured.get("capacity") == "unlimited":
        return None
    best = 1
    for lowest, count in configured.get("limits_by_cl") or [[1, 1]]:
        if int(cl) >= int(lowest):
            best = int(count)
    return max(1, best)


def rules_for_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Sealed admission rules shared by combat and prefight; absent means legacy CL caps.

    Used by limit() and CombatService. Never consult today's mutable rules for a
    previously compiled bundle, or modify the bundle or its sealed snapshot.
    """
    return bundle.get("concentration_rules") or _LEGACY_RULES


def limit(engine: Any, actor: Any) -> int:
    """Integer admission bound for the locked engine's next activation.

    In unlimited mode the next technique always fits: the bound is the current
    count plus one (at least two to select the engine's hold-current path).
    It is recomputed for every admission, never a large fixed cap or saved value.
    The compiler seals the capacity rules in each new bundle. Old bundles without
    that snapshot retain their CL ceiling; uncompiled legacy fighters retain one.
    Companions use their owner's snapshot when they have no bundle of their own.
    A fighter without a Factory bundle (sealed samples, roster opponents) keeps one slot.
    Built-in fights with no compiled bundles are the sealed sample fights: they keep their original one slot (the owner's
    unlimited ruling is for Factory characters; round 18 reconcile, sealed Gate 2 / Gate 5.1 replays).
    """
    bundles = getattr(engine, "typed_bundle_documents", ()) or ()
    if not bundles:
        return 1
    bundle = next((row for row in bundles if row.get("actor_id") == actor.entity_id), None)
    if bundle is None and getattr(actor, "owner_id", None):
        bundle = next((row for row in bundles if row.get("actor_id") == actor.owner_id
                       and row.get("concentration_rules")), None)
        if bundle is None:
            return 1
    if bundle is None:
        return 1  # a sealed sample / roster fighter without a Factory bundle keeps one slot, also in mixed fights
    configured = rules_for_bundle(bundle)
    capacity = limit_for_cl(int(bundle.get("cl") or 1), configured)
    return max(2, len(sources(actor)) + 1) if capacity is None else capacity


def selection_limit(cl: int, maximum_picks: int, configured: dict[str, Any] | None = None) -> int:
    """Effective concentration allowance for a separately bounded selection menu.

    Used by CombatService's prefight setup; unlimited concentration does not
    remove that menu's independent maximum number of pre-cast buffs.
    Pass the bundle's sealed rules to keep selection consistent with combat.
    """
    capacity = limit_for_cl(cl, configured)
    return maximum_picks if capacity is None else capacity


def held(actor: Any) -> list[tuple[str, Any]]:
    """The older ones it still holds, oldest first: (condition instance id, ConcentrationState)."""
    from .gate2_runtime_models import ConcentrationState

    rows = [(iid, ConcentrationState.model_validate((condition.data or {}).get("held") or {}))
            for iid, condition in actor.conditions.items() if condition.condition_id == HELD and (condition.data or {}).get("held")]
    return sorted(rows, key=lambda row: row[1].started_sequence)


def sources(actor: Any) -> list[str]:
    return [*(state.source_definition_id for _iid, state in held(actor)), *([actor.concentration.source_definition_id] if actor.concentration else [])]


def concentrating_on(actor: Any, source_id: Any) -> bool:
    """Whether it still concentrates on this technique, the current one or one it holds."""
    return bool(source_id) and str(source_id) in sources(actor)


def technique_of(engine: Any, source_id: str) -> str:
    """The technique behind an action: its options and augmented variants ("Darkness + Directional Darkness") are the same
    technique as the ability itself, so casting one again re-shapes it rather than holding a second."""
    action = (getattr(engine, "action_catalog", {}) or {}).get(source_id)
    parameters = (getattr(action, "parameters", None) or {}) if action is not None else {}
    if parameters.get("meld_talent"):
        return f"meld:{parameters['meld_talent']}"  # each Meld is its own technique (they all type as the Meld record)
    typed = parameters.get("typed") or {}
    return str(typed.get("option_of") or typed.get("source") or source_id)


def free_slot(engine: Any, actor: Any) -> bool:
    return len(sources(actor)) < limit(engine, actor)


def _name(engine: Any, source_id: str) -> str:
    action = (getattr(engine, "action_catalog", {}) or {}).get(source_id)
    return getattr(action, "display_name", None) or source_id


def hold_current(engine: Any, actor: Any) -> None:
    """Keep the current one going beside the next (always followed at once by a new CONCENTRATION_STARTED)."""
    state = actor.concentration
    if state is None:
        return
    engine._apply_condition(actor, HELD, state.source_definition_id, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"held": state.model_dump(mode="json"), "label": f"Concentrating: {_name(engine, state.source_definition_id)}"})
    actor.concentration = None


def _drop_condition(engine: Any, actor: Any, instance_id: str, source_id: str, reason: str) -> None:
    condition = actor.conditions.pop(instance_id, None)
    if condition is not None:
        engine._append_event("CONDITION_REMOVED", source_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": condition.condition_id, "instance_id": instance_id, "reason": reason})


def copies(actor: Any, source: str, ending: int | None = None) -> list[int]:
    """When each copy of this technique that it concentrates on began (the current one, the ones it holds, and ``ending``,
    the copy that is being ended and is no longer either), oldest first."""
    starts = {state.started_sequence for _iid, state in held(actor) if state.source_definition_id == source}
    if actor.concentration is not None and actor.concentration.source_definition_id == source:
        starts.add(actor.concentration.started_sequence)
    if ending is not None:
        starts.add(int(ending))
    return sorted(starts)


def made_at(row_id: str, row: Any) -> int | None:
    """The event sequence a condition or modifier was made at: a condition says so (applied_sequence); a modifier's id ends
    in it (engine._add_modifier files it as ``modifier:<source>:<holder>:<sequence>``)."""
    stamp = getattr(row, "applied_sequence", None)
    if stamp is not None:
        return int(stamp)
    tail = str(row_id).rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else None


def owner_copy(sequence: int | None, starts: list[int]) -> int | None:
    """Which copy made something at this event sequence: the newest one that had begun by then (one of unknown age is the
    newest copy's)."""
    if not starts:
        return None
    if sequence is None:
        return starts[-1]
    return max((start for start in starts if start <= sequence), default=starts[0])


def _made_by(sequence: int | None, ending: int | None, starts: list[int]) -> bool:
    """Whether what was made at ``sequence`` goes when the copy that began at ``ending`` ends. With one copy of the
    technique (or no start given) it is all of that technique's."""
    return ending is None or len(starts) < 2 or owner_copy(sequence, starts) == ending


def end_conditions(engine: Any, actor: Any, source: str, ending: int | None, reason: str) -> None:
    """Take off the conditions that last as long as this copy does (expires_on CONCENTRATION_END), wherever they are filed;
    another copy of the same technique keeps its own."""
    starts = copies(actor, source, ending)
    for other in engine.state.actors.values():
        for iid, row in list(other.conditions.items()):
            if row.source_definition_id == source and row.expires_on == "CONCENTRATION_END" and _made_by(made_at(iid, row), ending, starts):
                del other.conditions[iid]
                engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(other.entity_id,),
                                     payload={"instance_id": iid, "reason": reason})


def end_modifiers(engine: Any, actor: Any, source: str, reason: str, ending: int | None = None) -> None:
    """Take off the modifiers that last as long as this concentration does (expires_on CONCENTRATION_END), wherever they are
    filed. The engine's own _end_concentration removes the conditions and leaves these, so a "+2 AC while you concentrate"
    or a stat penalty stamped for the concentration stayed on for the rest of the fight. ``ending`` is the start of the
    copy that ends: another copy of the same technique keeps its own."""
    starts = copies(actor, source, ending)
    for other in engine.state.actors.values():
        for mid, row in list(other.modifiers.items()):
            if row.source_definition_id == source and row.expires_on == "CONCENTRATION_END" and _made_by(made_at(mid, row), ending, starts):
                del other.modifiers[mid]
                engine._append_event("MODIFIER_REMOVED", source, actor_id=actor.entity_id, target_ids=(other.entity_id,),
                                     payload={"modifier_id": mid, "reason": reason})


def end_summons(engine: Any, actor: Any, source: str, reason: str) -> None:
    """A Concentration summon leaves with its technique -- unless another copy of that technique still holds it (there is
    one Painted Beast however many times it was called)."""
    if getattr(engine, "summon_records", None) and not concentrating_on(actor, source):
        from . import summons

        summons.on_concentration_end(engine, actor, source, reason)


def _same_effect(row: Any, new: Any) -> bool:
    """The same modifier field and operation, or the same condition carrying the same rule."""
    if hasattr(row, "modifier_id"):
        return (row.target_field, row.operation) == (new.target_field, new.operation)
    return (row.condition_id, (row.data or {}).get("rule")) == (new.condition_id, (new.data or {}).get("rule"))


def supersede(engine: Any, event: Any) -> None:
    """A newer copy's effect replaces an older copy's same effect on the same creature: the same buff does not stack (owner
    ruling 2026-09-29). Called for each MODIFIER_APPLIED / CONDITION_APPLIED event; only an effect that lasts as long as its
    Concentration (CONCENTRATION_END) of a technique held more than once is looked at. The older copy stays held: it may
    still hold other creatures or an area."""
    holder = engine.state.actors.get(event.target_ids[0]) if event.target_ids else None
    if holder is None:
        return
    payload = event.payload or {}
    modifier = event.event_type == "MODIFIER_APPLIED"
    rows = holder.modifiers if modifier else holder.conditions
    new_id = payload.get("modifier_id" if modifier else "instance_id")
    new = rows.get(new_id)
    if new is None or new.expires_on != "CONCENTRATION_END":
        return
    source = new.source_definition_id
    for caster in engine.state.actors.values():
        starts = copies(caster, source)
        if len(starts) < 2:
            continue
        newest = owner_copy(made_at(new_id, new), starts)
        for row_id, row in list(rows.items()):
            if row is new or row.source_definition_id != source or row.expires_on != "CONCENTRATION_END" \
                    or owner_copy(made_at(row_id, row), starts) == newest or not _same_effect(row, new):
                continue
            del rows[row_id]
            if modifier:
                engine._append_event("MODIFIER_REMOVED", source, actor_id=caster.entity_id, target_ids=(holder.entity_id,),
                                     payload={"modifier_id": row_id, "reason": "SUPERSEDED"})
            else:
                engine._append_event("CONDITION_REMOVED", source, actor_id=caster.entity_id, target_ids=(holder.entity_id,),
                                     payload={"condition_id": row.condition_id, "instance_id": row_id, "reason": "SUPERSEDED"})


def end_held(engine: Any, actor: Any, instance_id: str, reason: str, *, retain_zone: bool = False) -> None:
    """End a held copy and its dependent effects through events.

    retain_zone defaults to False. Paid persistence controls can retain its
    area while ending only this copy; they must provide independent expiry.
    """
    condition = actor.conditions.get(instance_id)
    if condition is None:
        return
    from .gate2_runtime_models import ConcentrationState

    state = ConcentrationState.model_validate((condition.data or {}).get("held") or {})
    source = state.source_definition_id
    _drop_condition(engine, actor, instance_id, source, reason)
    if not retain_zone and state.zone_id and state.zone_id in engine.state.zones:
        zone = engine.state.zones[state.zone_id]
        zone.active = False
        engine._append_event("ZONE_REMOVED", source, actor_id=actor.entity_id, payload={"zone_id": zone.zone_id, "reason": reason})
    end_conditions(engine, actor, source, state.started_sequence, reason)
    end_modifiers(engine, actor, source, reason, state.started_sequence)
    end_summons(engine, actor, source, reason)
    # held: true tells the reducer (gate3_reducer) to keep the current concentration.
    engine._append_event("CONCENTRATION_ENDED", source, actor_id=actor.entity_id,
                         payload={"reason": reason, "started_sequence": state.started_sequence, "held": True})


def end_copy(engine: Any, actor: Any, started_sequence: int, reason: str, *, retain_zone: bool = False) -> None:
    """End exactly one current or held activation through persisted events.

    Shared by Aegis dismissal and Persistent Darkness conversion. retain_zone
    detaches an area before ending Concentration when an ability pays to keep it;
    callers must supply that area's independent expiry. Other copies stay intact.
    """
    current = actor.concentration
    if current is not None and current.started_sequence == started_sequence:
        if retain_zone:
            current.zone_id = None
        engine._end_concentration(actor, reason)
        return
    for instance_id, state in held(actor):
        if state.started_sequence == started_sequence:
            end_held(engine, actor, instance_id, reason, retain_zone=retain_zone)
            return


def resume_latest(engine: Any, actor: Any) -> None:
    """The current one ended: the most recent it holds becomes the current one again."""
    rows = held(actor)
    if actor.concentration is not None or not rows:
        return
    instance_id, state = rows[-1]
    _drop_condition(engine, actor, instance_id, state.source_definition_id, "RESUMED")
    actor.concentration = state
    engine._append_event("CONCENTRATION_STARTED", state.source_definition_id, actor_id=actor.entity_id, payload={"reason": "RESUMED"})


MODE = "condition:typed.concentration_mode"


def save_modes(engine: Any, actor: Any) -> set[str]:
    """Collect unsimplified Concentration save contributions, consuming 'next' rows.

    Apply concentration_mode_removed before returning; the native save caller
    passes this set through roll_context.save_modes to cancel opposing modes
    only after ordinary conditions, checkpoints and save_mode hooks contribute.
    No contributions returns an empty set and preserves ordinary save behavior.
    """
    modes, used = set(), []
    for instance_id, condition in actor.conditions.items():
        rule = ((condition.data or {}).get("rule") or {}) if condition.condition_id == MODE else {}
        if rule.get("concentration_mode") in ("ADVANTAGE", "DISADVANTAGE"):
            modes.add(rule["concentration_mode"])
            if rule.get("next"):
                used.append(instance_id)
    for instance_id in used:
        _drop_condition(engine, actor, instance_id, str(actor.conditions[instance_id].source_definition_id), "CONSUMED")
    # Damage from the side of whoever set the condition (Formations, Suppressing Vein: "Hostile creatures inside the array have
    # Disadvantage on Constitution saving throws made to maintain Concentration caused by damage from your allies"): the
    # damager is the creature whose action is being resolved.
    intent = getattr(engine, "_active_intent", None)
    damager = engine.state.actors.get(intent.actor_id) if intent is not None else None
    from .typed_executor import is_active_typed_condition

    for condition in actor.conditions.values():
        rule = ((condition.data or {}).get("rule") or {}) if is_active_typed_condition(condition) else {}
        mode = rule.get("concentration_vs_allies_of_source")
        setter = engine.state.actors.get(condition.source_actor_id) if mode in ("ADVANTAGE", "DISADVANTAGE") else None
        if setter is not None and damager is not None and damager.entity_id != actor.entity_id and damager.team_id == setter.team_id:
            modes.add(mode)
    from .typed_executor import condition_rules

    # A condition whose own rule presses Concentration (Sickened: combat/rules/typed_conditions.json).
    modes.update(row["concentration_mode"] for row in condition_rules(actor) if row.get("concentration_mode") in ("ADVANTAGE", "DISADVANTAGE"))
    # "Cannot benefit from Advantage on Concentration saving throws" (rider lane C14 seam, combat/ext/__init__.py
    # concentration_mode_removed; Meridian Stillness Field): the named modes do not count. No answer = the modes as before.
    from . import ext

    if ext.has("concentration_mode_removed"):
        for removed in ext.run("concentration_mode_removed", engine, actor):
            modes -= {str(mode) for mode in removed or ()}
    return modes


def save_mode(engine: Any, actor: Any) -> str | None:
    """Legacy standalone query; collect/consume once and cancel opposing modes.

    Native saves use save_modes so later contributions cannot undo cancellation.
    """
    modes = save_modes(engine, actor)
    return next(iter(modes)) if len(modes) == 1 else None


def end_all_held(engine: Any, actor: Any, reason: str) -> None:
    for instance_id, _state in held(actor):
        end_held(engine, actor, instance_id, reason)

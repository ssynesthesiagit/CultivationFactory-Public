"""Augments that let a Concentration technique persist without Concentration, applied after it is made (rider lane C13,
2026-09-30; owner: "i want everything we can automated, keep going until its only the non-combat ones left").

The printed shape, shared by several abilities ("Augment - 2 CP: <it> persists for its remaining duration without
Concentration. You may apply this augment after creating <it> on your turn without spending an Action."):
  Conflagration (Lingering Conflagration), Dreamscape, Qi Bond (Persistent Qi Bond), Turbulent Field (Lingering Turbulence),
  Darkness (its own text and Persistent Darkness) and Meld (its own text and Persistent Meld).
  Apply Glamer's augment ("Augment 2 CP: The glamer lasts for its remaining duration without Concentration"): a Concentration
  Glamer talent (one whose printed Tags name Glamer: Illusory Disguise, Obscuring Glamer, Greater Invisibility) is that technique.
  Place Mandate's Set Mandate ("You may spend 2 CP when placing a Mandate, or later on your turn without an action, to set it for
  the remaining duration. A set Mandate no longer requires Concentration, but it still counts against Mandate Load"): every
  Place Mandate button (combat/ext/imbuement_mandates.py) is that technique; its Load counts the set ones (``persisted`` below).
  Fragrance (Lingering Fragrance, the Flowers sphere): the printed "Area" the caster chose is the technique, so keeping it is
  keeping that drifting fragrance.
Paying the augment while making the technique and paying it right after, on the same turn, is the same 2 CP for the same
result, so one free button covers both: "Keep <technique> without Concentration (2 CP)", offered on your turn while you
concentrate on a copy of that technique (the newest copy, when there are several).

What it does (combat/concentration.py holds the copies): the copy's area stops being tied to the Concentration (its own
duration still runs: the zone's ``duration_rounds``); the conditions and modifiers that last as long as that copy
(CONCENTRATION_END, wherever they are filed, the copy's own -- concentration.made_at/owner_copy) are put back with the rest of
the technique's printed duration instead (combat/ext/effect_durations.py round clock; an hour or longer lasts the fight); a
Meld kept by its "concentration" data flag (combat/ext/docket_senses.py) is put back without it; then the Concentration
ends, leaving all of that standing (gate2 _end_concentration, or the held copy's own record for an older copy). Conditions
retain their instance identity via the evented update API, preserving dependent HP grants and permissions; conversion
is neither removal nor a new grant. Every change
is an ordinary evented condition / zone record, so a saved fight replays it. The caster keeps a record of what was kept: a
``persisted_technique`` condition lasting as long (data: technique, source, the copy's start, the kept condition and modifier ids);
``persisted(engine, actor, technique)`` lists them oldest first and ``end_persisted`` ends one early with all it kept (Mandate Load).

Hooks: compile_actions (the button, only for a character that owns one of the abilities below), candidate_allowed (only while a
copy is held). No hooks added to the framework. Default-inert: nothing for characters without these abilities.
"""

from __future__ import annotations

import copy
import re
from functools import lru_cache
from typing import Any

from . import effect, hook, run_strict

# mechanic id -> (the technique it keeps, the augment's printed name, CP). A talent that repeats the base ability's augment
# (Persistent Darkness, Persistent Meld) keeps the same technique: one button either way.
PERSIST = {
    "FIRE_BASE_CONFLAGRATION": ("FIRE_BASE_CONFLAGRATION", "Lingering Conflagration", 2),
    "DREAMS_BASE_DREAMSCAPE": ("DREAMS_BASE_DREAMSCAPE", "Lingering Dreamscape", 2),
    "TAL_QIWEAVING_QI_BOND": ("TAL_QIWEAVING_QI_BOND", "Persistent Qi Bond", 2),
    "TAL_QIWEAVING_TURBULENT_FIELD": ("TAL_QIWEAVING_TURBULENT_FIELD", "Lingering Turbulence", 2),
    "DARK_BASE_DARKNESS": ("DARK_BASE_DARKNESS", "Persistent Darkness", 2),
    "TAL_DARK_PERSISTENT_DARKNESS": ("DARK_BASE_DARKNESS", "Persistent Darkness", 2),
    "TAL_DARK_MELD": ("TAL_DARK_MELD", "Persistent Meld", 2),
    "TAL_DARK_PERSISTENT_MELD": ("TAL_DARK_MELD", "Persistent Meld", 2),
    "IMBUEMENT_BASE_PLACE_MANDATE": ("IMBUEMENT_BASE_PLACE_MANDATE", "Set Mandate", 2),
    "TAL_ILLUSION_APPLY_GLAMER": ("TAL_ILLUSION_APPLY_GLAMER", "Glamer Augment", 2),
    "TAL_FLOWERS_LINGERING_FRAGRANCE": ("FLOWERS_BASE_FRAGRANCE", "Lingering Fragrance", 2),
}
LABELS = {"TAL_ILLUSION_APPLY_GLAMER": "your glamer"}  # what the button keeps, when it is not the technique's own name
GLAMER = "TAL_ILLUSION_APPLY_GLAMER"
_GLAMER_TAG = re.compile(r"^Tags?:[^\n]*\bGlamer\b", re.M)


@lru_cache(maxsize=1)
def glamer_ids() -> frozenset[str]:
    """The Glamer talents (printed "Tags: ... Glamer"), from the owner's rules text."""
    import json
    from pathlib import Path

    texts = json.loads((Path(__file__).resolve().parents[2] / "authority" / "typed_mechanics" / "rules_text.json").read_text(encoding="utf-8"))
    return frozenset(key for key, text in texts.items() if isinstance(text, str) and _GLAMER_TAG.search(text[:600]))
MANDATE = "IMBUEMENT_BASE_PLACE_MANDATE"
RECORD = "condition:typed.persisted_technique"
MELD_RECORD = "TAL_DARK_MELD"
ACTION_TAG = "persist_augment"


def technique_of(action: Any) -> str | None:
    """Which of the techniques above an action makes (its typed source / option, or a Meld)."""
    parameters = (getattr(action, "parameters", None) or {}) if action is not None else {}
    if parameters.get("meld_talent"):
        return MELD_RECORD
    typed = parameters.get("typed") or {}
    if (typed.get("mandate") or {}).get("side") == "imbue":  # a Place Mandate button (one per Imbue option)
        return MANDATE
    source = str(typed.get("option_of") or typed.get("source") or "")
    if source in glamer_ids():  # Apply Glamer itself, or a Glamer talent
        return GLAMER
    return source if any(source == kept for kept, _name, _cp in PERSIST.values()) else None


@hook("compile_actions")
def persist_buttons(info: dict[str, Any]) -> list[Any] | None:
    owned = set(info["owned_ids"])
    kept = {}
    for mechanic_id, (technique, name, cp) in PERSIST.items():
        if mechanic_id in owned:
            kept.setdefault(technique, (name, cp))
    if not kept:
        return None
    out = []
    for technique, (name, cp) in sorted(kept.items()):
        variants = next((v for v in run_strict("persist_variants", info, technique) if v is not None), None)
        for variant in variants or [{"key": "", "cp": cp, "label": name}]:
            out.append(_persist_button(info, technique, variant))
    return out


def _persist_button(info: dict[str, Any], technique: str, variant: dict[str, Any]) -> Any:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    name, cp = variant["label"], int(variant["cp"])
    label = LABELS.get(technique) or str((info["mechanics"].get(technique) or {}).get("name") or technique)
    rounds = variant.get("rounds")
    duration = (f"{rounds // 10} minute{'s' if rounds != 10 else ''} from setting"
                if isinstance(rounds, int) and rounds > 0 and rounds % 10 == 0 else
                f"{rounds} rounds from setting" if isinstance(rounds, int) and rounds > 0 else "its remaining duration")
    return ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.persist.{technique.lower()}{variant.get('key', '')}",
        display_name=f"{name}: keep {label} without Concentration ({cp} CP{variant.get('price_note', '')})", owner_id=info["actor_id"],
        economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "persist_without_concentration", "technique": technique, "cp": cp, "name": name,
                                           **({"rounds": variant["rounds"], "numbers": info["numbers"]} if "rounds" in variant else {}),
                                           "evidence": f"Augment - {cp} CP: {label} persists for {duration} without "
                                                       f"Concentration. You may apply this augment after creating it on your turn "
                                                       f"without spending an Action."}],
                              "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": f"persist.{technique}"},
                    "expected_damage": 0, "player_only": True, ACTION_TAG: technique})

def _copies(engine: Any, actor: Any, technique: str) -> list[tuple[str | None, Any]]:
    """(held condition instance id or None for the current one, ConcentrationState), oldest first, of this technique's copies."""
    from .. import concentration

    rows = [(iid, state) for iid, state in concentration.held(actor)]
    if actor.concentration is not None:
        rows.append((None, actor.concentration))
    return [(iid, state) for iid, state in rows if technique_of(engine.action_catalog.get(state.source_definition_id)) == technique]


def _pool(actor: Any) -> str | None:
    from .rider_support import cp_pool

    return cp_pool(actor)


@hook("candidate_allowed")
def persist_when_held(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    technique = ((getattr(action, "parameters", None) or {}) if action is not None else {}).get(ACTION_TAG)
    if not technique:
        return None
    eff = ((action.parameters.get("typed") or {}).get("effects") or [{}])[0]
    cp = _cost(engine, actor, eff)
    pool = _pool(actor)
    return bool(_copies(engine, actor, technique)) and pool is not None and int(actor.resources.get(pool, 0)) >= cp


def _cost(engine: Any, actor: Any, eff: dict[str, Any]) -> int:
    value = next(iter(run_strict("persist_cost", engine, actor, eff)), int(eff.get("cp", 2)))
    if type(value) is not int or value < 0:
        raise ValueError("Persistence price must be a nonnegative integer")
    return value


def _start_round(engine: Any, sequence: int) -> int:
    """The round a copy began in: the last turn start at or before its CONCENTRATION_STARTED."""
    round_number = int(engine.state.round_number)
    for event in reversed(engine.events):
        if int(getattr(event, "sequence", 0) or 0) > int(sequence):
            continue
        if event.event_type == "TURN_STARTED":
            return int((event.payload or {}).get("round") or round_number)
    return round_number


def _expiry(engine: Any, action: Any, started_sequence: int) -> str:
    """The rest of the technique's printed duration, counted from when its copy began."""
    from .. import typed_executor
    from . import effect_durations

    duration = dict(((getattr(action, "parameters", None) or {}).get("typed") or {}).get("duration") or {})
    kind = str(duration.get("kind") or "")
    per_unit = (typed_executor.rules().get("duration_rounds") or {}).get(kind)
    if isinstance(per_unit, int) and per_unit >= 1:
        total = max(1, int(duration.get("amount") or 1)) * per_unit
        left = total - (int(engine.state.round_number) - _start_round(engine, started_sequence))
        return effect_durations.round_token(engine, max(1, left))
    return typed_executor.duration_expiry(engine, {**duration, "concentration": False}) or "UNTIL_REMOVED"


@effect("persist_without_concentration")
def persist(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import concentration
    from .condition_ownership import remove_instance

    engine, actor, technique = ctx.engine, ctx.actor, str(eff.get("technique") or "")
    copies = _copies(engine, actor, technique)
    pool, cp = _pool(actor), _cost(engine, actor, eff)
    if not copies or pool is None or int(actor.resources.get(pool, 0)) < cp:
        ctx.rider(f"{eff.get('name')}: you are not concentrating on it, or cannot pay {cp} CP.")
        return
    held_iid, state = copies[-1]
    source = state.source_definition_id
    action = engine.action_catalog.get(source)
    engine._spend_resource(actor, pool, cp, ctx.source)
    run_strict("persist_paid", ctx, eff, cp)
    if eff.get("rounds") is not None:
        from .effect_durations import round_token
        expires = round_token(engine, int(eff["rounds"]))
    else:
        expires = _expiry(engine, action, int(state.started_sequence))
    starts = concentration.copies(actor, source)
    mine = lambda row_id, row: concentration.owner_copy(concentration.made_at(row_id, row), starts) == int(state.started_sequence)  # noqa: E731
    # 1. Its area stays for its own duration.
    if state.zone_id and state.zone_id in engine.state.zones:
        zone = engine.state.zones[state.zone_id]
        zone.concentration_link = False
        engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id, payload={"zone": zone.model_dump(mode="json")})
        state.zone_id = None
    # 2. What lasts as long as the copy lasts for the rest of the duration instead; a Meld drops its Concentration flag.
    kept: dict[str, list[list[str]]] = {"conditions": [], "modifiers": []}
    for holder in engine.state.actors.values():
        before_c, before_m = set(holder.conditions), set(holder.modifiers)
        for iid, row in list(holder.conditions.items()):
            data = dict(row.data or {})
            if row.source_definition_id == source and row.expires_on == "CONCENTRATION_END" and mine(iid, row):
                # Native Melds now use the ordinary concentration expiry too.
                # Detach both representations before ending concentration;
                # otherwise the legacy flag reader removes the kept marker.
                if data.get("concentration") is True and data.get("source") == source:
                    data.update(concentration=False, label=str(data.get("label") or "").replace(" (Concentration)", ""))
                engine._update_condition_data(holder, row, copy.deepcopy(data), ctx.source, expires_on=expires)
                kept["conditions"].append([holder.entity_id, iid])
            elif data.get("concentration") is True and data.get("source") == source:  # a Meld (docket_senses meld_set)
                data.update(concentration=False, label=str(data.get("label") or "").replace(" (Concentration)", ""))
                engine._update_condition_data(holder, row, data, ctx.source)
                kept["conditions"].append([holder.entity_id, iid])
        for mid, row in list(holder.modifiers.items()):
            if row.source_definition_id == source and row.expires_on == "CONCENTRATION_END" and mine(mid, row):
                del holder.modifiers[mid]
                engine._append_event("MODIFIER_REMOVED", ctx.source, actor_id=actor.entity_id, target_ids=(holder.entity_id,),
                                     payload={"modifier_id": mid, "reason": "PERSISTED"})
                engine._add_modifier(holder, row.source_definition_id, row.target_field, row.operation, row.value, row.applies_to,
                                     expires_on=expires)
        kept["conditions"] += [[holder.entity_id, iid] for iid in sorted(set(holder.conditions) - before_c)]
        kept["modifiers"] += [[holder.entity_id, mid] for mid in sorted(set(holder.modifiers) - before_m)]
    # 3. The Concentration ends; what it held stays.
    name = getattr(action, "display_name", None) or eff.get("name")
    engine._apply_condition(actor, RECORD, source, actor.entity_id, expires_on=expires,
                            data={"technique": technique, "source": source, "started": int(state.started_sequence), "kept": kept,
                                  "label": f"{name}: kept without Concentration ({eff.get('name')})"})
    if held_iid is None:
        engine._end_concentration(actor, "PERSISTED")
    else:
        remove_instance(engine, actor, held_iid, ctx.source)
    duration_text = (f"now remains active for {int(eff['rounds']) // 10} minute(s) "
                     if eff.get("rounds") is not None else "now lasts for the rest of its duration ")
    engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"text": f"{eff.get('name')}: {actor.display_name}'s {name} {duration_text}"
                                          f"without Concentration ({cp} CP)."})


def persisted(engine: Any, actor: Any, technique: str) -> list[tuple[str, Any]]:
    """(record instance id, record) of this technique's copies kept without Concentration that still stand, oldest first."""
    rows = [(iid, row) for iid, row in actor.conditions.items() if row.condition_id == RECORD and (row.data or {}).get("technique") == technique]
    return sorted(rows, key=lambda pair: int((pair[1].data or {}).get("started") or 0))


def end_persisted(engine: Any, actor: Any, record_iid: str, source: str, reason: str) -> None:
    """End one kept copy early: the conditions and modifiers it kept, then its record."""
    from .condition_ownership import remove_instance

    record = actor.conditions.get(record_iid)
    if record is None:
        return
    kept = (record.data or {}).get("kept") or {}
    for holder_id, iid in kept.get("conditions") or []:
        holder = engine.state.actors.get(holder_id)
        if holder is not None and iid in holder.conditions:
            remove_instance(engine, holder, iid, source)
    for holder_id, mid in kept.get("modifiers") or []:
        holder = engine.state.actors.get(holder_id)
        if holder is not None and mid in holder.modifiers:
            del holder.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", source, actor_id=actor.entity_id, target_ids=(holder.entity_id,),
                                 payload={"modifier_id": mid, "reason": reason})
    remove_instance(engine, actor, record_iid, source)

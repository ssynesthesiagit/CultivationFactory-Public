"""Suppressing an ongoing area -- the whole of it, or some of its squares -- for a while (rider lane C14,
2026-09-30; BLOCKED_CENSUS.md row 18). Shared helper module: the typed effect ``suppress_area`` below uses it (Lattice
Unraveling); any plug-in may call ``areas_at`` / ``suppress`` / ``suppressed``. Effects on creatures (conditions,
modifiers) already have their own suppression (combat/ext/end_effect.py, benefit_suppression.py); this covers the areas
(walls, barriers, wards, formation arrays, difficult or obscuring ground) that had none. ``suppress`` also takes any
list of squares (a wall section) for a plug-in that picks its own.

Rules: Lattice Unraveling "Make an Unmaking Check against the effect's save DC or formation DC. Success: Suppress the target
effect until the start of your next turn ... Success by 5 or more: The suppression lasts until the end of your next turn."
Spell Ward: "Time spent suppressed still counts against the effect's duration."

How it works. A suppression takes the area's squares (all of them, or the chosen ones) out of ``zone.affected_cells`` and
keeps them on the area itself, in ``zone.trigger_profile["suppressed"]`` (JSON only):
  [{"key": str, "by": actor id, "source": action id, "until": an expiry name (combat/ext/effect_durations.py),
    "all": 0 | 1, "cells": [[x, y], ...] (the squares taken out), "order": [[x, y], ...] (every square, in order, then)}]
Every reader of the area -- walls on the grid, difficult ground, start-of-turn and on-enter triggers, effects on creatures
inside -- simply no longer finds it on those squares. The area's own clock keeps running (created_round / duration_rounds
are untouched), Concentration still ends it, and when the record comes due (checked at every turn start and end) the squares
come back -- unless the area has ended meanwhile. An area that moves with its creator stays suppressed as it moves
(combat/zones.py follow() leaves the suppressed squares out). Every change is the zones module's own update event (the
whole area re-recorded with ZONE_CREATED), so a committed, reloaded or replayed fight rebuilds it exactly.

Only areas stored in the fight are suppressible: the map's painted terrain and areas a plug-in works out each time
(``zones`` hook) have nothing to suppress. Inert: with no ``suppressed`` record on any area, the sweeps return at once.

Typed effect ``suppress_area`` (aimed at a square; the action targets any square in range and sight):
  {"type": "suppress_area",
   "check": {"name": "Unmaking Check"},       # d20 + PB + key ability modifier (+ check bonuses), against the area's own save
                                              # DC (riders_shared.sphere_check rolls it); leave out = no check
   "until": "start_of_your_next_turn", "until_by_5": "end_of_your_next_turn",   # or "end_of_your_next_turn", {"rounds": n}
   "section": "all" | "square",               # the whole area, or only the aimed 5-foot square
   "excludes": ["domain", "formation"],       # areas it cannot touch ("domain": a Domain; "formation": a Formation array)
   "on_success": [...], "on_failure": [...],  # further rows (failure: Lattice's Strain)
   "construct": {"on_success": [...], "on_failure": [...]}}   # a summoned construct standing on the aimed square is the
                                              # target instead (its DC: the save DC of the technique that summoned it)
When several areas cover the square the player is asked which (the AI takes a hostile one first).
"""
from __future__ import annotations

import copy
from typing import Any

from . import effect, hook, note

KEY = "suppressed"
SOURCE = "system:area_suppression"


# ------------------------------------------------------------------------------------------------ queries
def records(zone: Any) -> list[dict[str, Any]]:
    return list((getattr(zone, "trigger_profile", None) or {}).get(KEY) or [])


def suppressed(zone: Any) -> bool:
    """Whether the whole area is suppressed right now."""
    return any(int(row.get("all") or 0) for row in records(zone))


def _stored(engine: Any, zone: Any) -> bool:
    return engine.state.zones.get(zone.zone_id) is zone


def kinds(engine: Any, zone: Any) -> set[str]:
    """What an area is, for a suppressor's exclusions: "domain" (an ability named a Domain), "formation" (a Formation array),
    "wall" (a wall or barrier), "terrain" (difficult or named ground), "obscuring" (it hides what is in or behind it)."""
    from . import formations

    profile = zone.trigger_profile or {}
    out = set()
    action = engine.action_catalog.get(zone.source_definition_id)
    names = [str(getattr(action, "display_name", "") or ""), str(profile.get("name") or ""),
             str((profile.get("source_profile") or {}).get("mechanic_id") or "")]
    if any("domain" in name.lower() for name in names):
        out.add("domain")
    if profile.get(formations.KEY):
        out.add("formation")
    if profile.get("wall"):
        out.add("wall")
    if profile.get("difficult") or profile.get("terrain"):
        out.add("terrain")
    if profile.get("obscured"):
        out.add("obscuring")
    return out


def effect_mundane(engine: Any, source: str, actor_id: str) -> bool | None:
    """Explicit classification from a saved action or passive's effect rows.

    Shared by area suppression and end_effect. All selected top-level rows
    must agree; mixed or legacy sources stay unknown. Read sealed fight rows,
    never current authority. A passive source names exactly one owned option.
    """
    action = engine.action_catalog.get(source)
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {})
    rows = typed.get("effects") or []
    fallback = typed.get("mundane")
    if source.startswith("passive:"):
        feature = source[len("passive:"):]
        saved = [*(getattr(engine, "typed_passive_rows", {}) or {}).get(actor_id, []),
                 *(getattr(engine, "typed_reaction_rows", {}) or {}).get(actor_id, [])]
        matches = []
        for entry in saved:
            if entry.get("feature_id") == feature:
                matches.extend(entry.get("effects") or [])
            for option in entry.get("options") or []:
                if option.get("id") == feature:
                    matches.extend(option.get("effects") or [])
        rows = matches
        fallback = None
    from ..zone_sources import mundane_rows

    return mundane_rows(rows, fallback)


def magical(zone: Any) -> bool | None:
    """Area classification sealed at creation: True magical, False mundane, None unknown."""
    from .. import zone_sources

    value = (zone_sources.of(zone) or {}).get("mundane")
    return not bool(value) if type(value) is int and value in (0, 1) else None


def areas_at(engine: Any, cell: Any, excludes: Any = (), *, magical_only: bool = False) -> list[Any]:
    """The stored, active areas covering ``cell`` (a Position) that a suppressor may choose, oldest first."""
    from .. import zones

    found = []
    for zone in zones.typed_zones(engine):
        if not _stored(engine, zone) or not zone.active or zone.owner_id == zones.MAP_OWNER:
            continue
        if not any(c.x == cell.x and c.y == cell.y for c in zone.affected_cells):
            continue
        if kinds(engine, zone) & set(excludes or ()):
            continue
        if magical_only and magical(zone) is not True:
            continue
        found.append(zone)
    return found


def save_dc(engine: Any, zone: Any) -> int:
    """The area's own save DC: the technique's that made it (its recorded numbers or sealed source profile), else its
    creator's Cultivation Save DC (end_effect.cultivation_dc, the fallback end_effect uses for an effect without one)."""
    from .. import zone_sources
    from . import end_effect

    numbers = (zone.trigger_profile or {}).get("numbers") or {}
    dc = int(numbers.get("save_dc") or (zone_sources.of(zone) or {}).get("save_dc") or 0)
    if dc:
        return dc
    owner = engine.state.actors.get(zone.owner_id)
    return end_effect.cultivation_dc(engine, owner) if owner is not None else 10


# ------------------------------------------------------------------------------------------------ suppress / restore
def _until(engine: Any, by: Any, rule: Any) -> tuple[str, str]:
    """(expiry name, plain wording) for a printed duration."""
    from .effect_durations import round_token, token

    if isinstance(rule, dict) and rule.get("rounds"):
        rounds = int(rule["rounds"])
        return round_token(engine, rounds), f"for {rounds} rounds"
    if rule == "end_of_your_next_turn":
        return token("end", by.entity_id, int(by.turns_started) + 1), f"until the end of {by.display_name}'s next turn"
    return token("start", by.entity_id, int(by.turns_started) + 1), f"until the start of {by.display_name}'s next turn"


def _save(engine: Any, zone: Any) -> None:
    from .. import zones

    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id, payload={"zone": zone.model_dump(mode="json")})
    if zone.trigger_profile.get("wall"):
        zones.sync_walls(engine)
    zones.sync_inside(engine, zone.source_definition_id)


def suppress(engine: Any, by: Any, zone: Any, until: str, source: str, cells: Any = None, *, retain_whole_when_empty: bool = False) -> dict[str, Any] | None:
    """Take ``cells`` (Positions; None = the whole area) out of the stored area ``zone`` until the expiry name ``until``.
    Returns the record, or None when nothing was taken out."""
    from ..gate2_runtime_models import Position

    if type(retain_whole_when_empty) is not bool or (retain_whole_when_empty and cells is not None):
        raise ValueError("Retained whole suppression requires a boolean whole-area opt-in.")
    if not _stored(engine, zone) or not zone.active:
        return None
    order = [[c.x, c.y] for c in zone.affected_cells]
    if retain_whole_when_empty:
        order=[list(c) for c in dict.fromkeys(tuple(c) for c in [*order,
            *(c for r in records(zone) for c in r.get("order") or []),
            *(c for r in records(zone) for c in r.get("cells") or [])])]
    wanted = order if cells is None else [[c.x, c.y] for c in cells]
    taken = [cell for cell in order if cell in wanted]
    if not taken and not (cells is None and retain_whole_when_empty):
        return None
    record = {"key": f"{source}:{engine.state.event_sequence}", "by": by.entity_id, "source": source, "until": str(until),
              "all": int(cells is None), "cells": taken, "order": order}
    zone.affected_cells = tuple(Position(x=x, y=y) for x, y in order if [x, y] not in taken)
    zone.trigger_profile = {**zone.trigger_profile, KEY: [*records(zone), record]}
    _save(engine, zone)
    return record


def _restore(engine: Any, zone: Any, record: dict[str, Any]) -> None:
    from .. import zones
    from ..gate2_runtime_models import Position

    kept = [row for row in records(zone) if row.get("key") != record.get("key")]
    profile = {k: v for k, v in zone.trigger_profile.items() if k != KEY}
    if kept:
        profile[KEY] = kept
    still = {tuple(cell) for row in kept for cell in row.get("cells") or []}
    if zones.moves_with_owner(zone):  # re-centered meanwhile: its squares are worked out again where it now is
        full = [[c.x, c.y] for c in zones.area_cells(engine, zone)]
    else:
        present = [[c.x, c.y] for c in zone.affected_cells]
        full = [cell for cell in record.get("order") or [] if cell in present or cell in record.get("cells")]
        full += [cell for cell in present if cell not in full]
    if any(int(row.get("all") or 0) for row in kept):
        full = []
    zone.affected_cells = tuple(Position(x=x, y=y) for x, y in full if (x, y) not in still)
    zone.trigger_profile = profile
    _save(engine, zone)
    owner = engine.state.actors.get(zone.owner_id)
    note(engine, record.get("source") or SOURCE, owner or zone.owner_id,
         f"{_label(engine, zone)} works again" + ("" if int(record.get("all") or 0) else " on the squares that were suppressed") + ".")


def sweep(engine: Any, ending_id: str | None = None) -> None:
    """Bring back every suppressed square whose time has come (an area that ended meanwhile stays ended)."""
    from .effect_durations import due

    for zone in sorted(engine.state.zones.values(), key=lambda row: row.zone_id):
        if not zone.trigger_profile.get(KEY):
            continue
        for record in records(zone):
            if due(engine, record.get("until"), ending_id):
                if zone.active:
                    _restore(engine, zone, record)
                else:  # ended while suppressed: just forget the record
                    zone.trigger_profile = {**zone.trigger_profile, KEY: [r for r in records(zone) if r.get("key") != record.get("key")]}
                    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id,
                                         payload={"zone": zone.model_dump(mode="json")})


@hook("turn_start")
def _turn_started(engine: Any, actor: Any) -> None:
    sweep(engine)


@hook("turn_end")
def _turn_ended(engine: Any, actor: Any) -> None:
    sweep(engine, ending_id=actor.entity_id)


# ------------------------------------------------------------------------------------------------ the typed effect
def _label(engine: Any, zone: Any) -> str:
    action = engine.action_catalog.get(zone.source_definition_id)
    owner = engine.state.actors.get(zone.owner_id)
    name = str(getattr(action, "display_name", "") or zone.trigger_profile.get("name") or "the area")
    return f"{owner.display_name}'s {name}" if owner is not None else name


def _row(action: Any) -> dict[str, Any] | None:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {})
    return next((row for row in typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "suppress_area"), None)


def _construct(engine: Any, cell: Any) -> Any | None:
    """A summoned construct standing on ``cell``."""
    from . import creature_kinds

    for actor in sorted(engine.state.actors.values(), key=lambda row: row.entity_id):
        if actor.active and actor.summon is not None and creature_kinds.matches(actor, ["construct"]) and \
                engine._footprint_intersects(actor, (cell,)):
            return actor
    return None


def _summoning_dc(engine: Any, creature: Any) -> int:
    """The save DC of the technique that summoned ``creature``, else its summoner's Cultivation Save DC
    (end_effect.cultivation_dc, the same fallback end_effect uses for an effect without a DC of its own)."""
    from . import end_effect

    owner = engine.state.actors.get(str(creature.summon.get("owner") or ""))
    source = str(creature.summon.get("source") or "")
    for action in engine.action_catalog.values():
        if owner is not None and action.owner_id == owner.entity_id and action.source_definition_id.split("#", 1)[0].endswith("." + source):
            dc = int((((action.parameters or {}).get("typed") or {}).get("numbers") or {}).get("save_dc") or 0)
            if dc:
                return dc
    return end_effect.cultivation_dc(engine, owner) if owner is not None else 10


def _section(row: dict[str, Any], cell: Any) -> list[Any] | None:
    """The squares to take out: None (the whole area) or just the aimed square ("section": "square")."""
    return [cell] if str(row.get("section") or "all") == "square" else None


@effect("suppress_area")
def suppress_area(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor
    from . import riders_shared

    engine, actor = ctx.engine, ctx.actor
    cell = getattr(ctx.intent, "destination", None) if ctx.intent is not None else None
    if cell is None:
        ctx.rider(f"{ctx.action.display_name}: no square was aimed at.")
        return
    construct = _construct(engine, cell) if row.get("construct") and not row.get("magical_only") else None
    if construct is not None:
        sub = typed_executor.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [construct], construct, ctx.damage_cache)
        dc = _summoning_dc(engine, construct)
        riders_shared.sphere_check(sub, {"name": (row.get("check") or {}).get("name") or "Check", "dc": dc,
                                         "on_success": copy.deepcopy(row["construct"].get("on_success") or []),
                                         "on_failure": copy.deepcopy(row["construct"].get("on_failure") or [])})
        return
    found = areas_at(engine, cell, row.get("excludes") or (), magical_only=bool(row.get("magical_only")))
    if not found:
        ctx.rider(f"{ctx.action.display_name}: no area there that it can suppress.")
        return
    zone = found[0]
    if len(found) > 1:
        from .needle import CHOICE, ask, checkpoint_id

        hostile = [z.zone_id for z in found if (engine.state.actors.get(z.owner_id) is not None
                                                 and engine.state.actors[z.owner_id].team_id != actor.team_id)]
        labels = {z.zone_id: _label(engine, z) for z in found}
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "area_suppression", cell.x, cell.y), actor, CHOICE + "area_suppression",
                     list(labels), labels=labels, preferred=hostile, name=ctx.action.display_name,
                     prompt=f"{ctx.action.display_name}: which area on that square do you suppress?")
        zone = next((z for z in found if picked and z.zone_id == picked[0]), zone)
    cells = _section(row, cell)
    key = f"suppress_area:{zone.zone_id}"
    ctx.damage_cache[key] = {"zone": zone.zone_id, "cells": None if cells is None else [[c.x, c.y] for c in cells]}
    apply = {"type": "suppress_area_apply", "key": key}
    if row.get("check"):
        riders_shared.sphere_check(ctx, {"name": row["check"].get("name") or "Check", "dc": save_dc(engine, zone),
                                         "on_success": [{**apply, "until": row.get("until")}, *copy.deepcopy(row.get("on_success") or [])],
                                         "on_success_by_5": [{**apply, "until": row["until_by_5"], "extend": True}] if row.get("until_by_5") else [],
                                         "on_failure": copy.deepcopy(row.get("on_failure") or [])})
    else:
        typed_executor.run_effects(ctx, [{**apply, "until": row.get("until")}, *copy.deepcopy(row.get("on_success") or [])])


@effect("suppress_area_apply")
def suppress_area_apply(ctx: Any, row: dict[str, Any]) -> None:
    """The success half of ``suppress_area``. ``extend``: the success by 5 or more, which holds the same squares longer."""
    from ..gate2_runtime_models import Position

    chosen = ctx.damage_cache.get(row.get("key")) or {}
    zone = ctx.engine.state.zones.get(str(chosen.get("zone") or ""))
    if zone is None or not zone.active:
        return
    until, wording = _until(ctx.engine, ctx.actor, row.get("until"))
    if row.get("extend"):
        rows = records(zone)
        if not any(r.get("key") == chosen.get("record") for r in rows):
            return
        zone.trigger_profile = {**zone.trigger_profile, KEY: [{**r, "until": until} if r.get("key") == chosen.get("record") else r
                                                              for r in rows]}
        _save(ctx.engine, zone)
        note(ctx.engine, ctx.source, ctx.actor, f"Success by 5 or more: the suppression lasts {wording}.")
        return
    cells = None if chosen.get("cells") is None else [Position(x=x, y=y) for x, y in chosen["cells"]]
    record = suppress(ctx.engine, ctx.actor, zone, until, ctx.source, cells)
    if record is None:
        return
    chosen["record"] = record["key"]
    part = "" if record["all"] else (" (one 5-foot square)" if len(record["cells"]) == 1 else f" ({len(record['cells']) * 5}-foot section)")
    note(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name} suppresses {_label(ctx.engine, zone)}{part} {wording}: "
         "it does nothing there until then, though its own duration keeps running.")


# ------------------------------------------------------------------------------------------------ offering it
@hook("compile_action")
def aim_at_any_square(action: Any, info: dict[str, Any]) -> Any:
    """An ability with a ``suppress_area`` row is aimed at a square in range and sight (gate4_engine any_cell candidates)."""
    if _row(action) is None or (action.parameters or {}).get("any_cell"):
        return None
    params = copy.deepcopy(action.parameters)
    params["any_cell"] = True
    return action.model_copy(update={"parameters": params, "target_kind": "CELL", "radius_ft": 0})


@hook("candidate_allowed")
def only_where_something_is(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Offered only on a square with an area it can suppress (or, when printed, a summoned construct)."""
    row = _row(action)
    if row is None:
        return None
    cell = getattr(candidate, "destination", None)
    if cell is None:
        return False
    if row.get("construct") and not row.get("magical_only") and _construct(engine, cell) is not None:
        return True
    return bool(areas_at(engine, cell, row.get("excludes") or (), magical_only=bool(row.get("magical_only"))))


@hook("ai_candidate_allowed")
def ai_only_against_foes(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The built-in AI suppresses only an area of the other side (or a foe's construct)."""
    row = _row(action)
    cell = getattr(candidate, "destination", None)
    if row is None or cell is None:
        return None
    construct = _construct(engine, cell) if row.get("construct") and not row.get("magical_only") else None
    if construct is not None:
        return construct.team_id != actor.team_id
    return any(engine.state.actors.get(z.owner_id) is not None and engine.state.actors[z.owner_id].team_id != actor.team_id
               for z in areas_at(engine, cell, row.get("excludes") or (), magical_only=bool(row.get("magical_only"))))


def restore_record(engine: Any, zone: Any, key: str) -> bool:
    """Restore one actual saved suppression record, preserving other sources.

    Source lifetimes may use a recognized UNTIL_REMOVED token when an explicit
    native restoration/removal event owns their end. No matching live record
    means no mutation or event; no saved area can be resurrected by this call.
    """
    if not _stored(engine, zone) or not zone.active:
        return False
    record = next((r for r in records(zone) if r.get("key") == key), None)
    if record is None:
        return False
    _restore(engine, zone, record)
    return True

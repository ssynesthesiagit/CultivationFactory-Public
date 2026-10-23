"""Printed ability lights that ride a lasting state on a creature (docs/specs/LIGHTING_SPEC.md §8.2).

The model is combat/lighting.py; the curated table is combat/rules/light_sources.json, read through
combat/light_sources.py. A row with a ``state`` names the condition id (a prefix, e.g.
"condition:typed.exposed") or "modifier" that the ability files on the creature it affects. While that state is on
an active creature, that creature sheds the row's printed radii -- for exactly as long as the state lasts, because
the state IS the clock and nothing here stores or removes anything.

Rows whose light a zone, a summon or their own producer already carries have no ``state`` and are not emitted by the
state scan: the compiler gives a zone its printed radii (combat/factory_compiler.py::_zone_visual), combat/lighting.py
reads a summon's own light, and each of those producers writes what it prints. That keeps one emitter per printed
light. Two more general seams cover the printed lights whose trigger is not a lasting condition:

``light`` effect (per typed row, SPEC §8.2)
    ``{"type": "light", "applies_to": "self" | "target", "light": <mechanic id>, "duration": ...}`` makes its subjects
    shed the curated row's printed radii on the effect's own clock. A reviewed row that prints the light on a
    creature uses it (Radiant Fist's Dim Light option, Guiding Candle's candle). Radii are always read from the
    table, never restated in code.

``mark_spent`` producer (Summer Pressure)
    "When you spend a Kindled Mark on yourself, you may choose to emit ... until the start of your next turn."
    combat/typed_executor.block_spend_mark announces every spend; this module asks the owning player and files the
    printed light on the same clock. A creature that does not own the talent is untouched.

``reaction_resolved`` producer (The Action Cannot Stay Small)
    The printed overcomplete result "one created, summoned, or conjured effect from the action emits bright light in
    a 20-foot radius ... until the start of your next turn". The engine has no created-effect object, so the light
    rides the creature whose completed action was overcompleted; it is filed only when that creature failed the
    reaction's Constitution save (the printed overcomplete branch).

The state hook is pure and default-inert: a fight with no such state returns None and the field is exactly what the
map and the four stores already say. No saved field, no engine state, no prompt beyond the printed "you may".
"""

from __future__ import annotations

from typing import Any, Iterable

from . import effect, hook

#: Summer Pressure's light is spent, not carried by a lasting condition the compiler already seals.
SUMMER_PRESSURE = "TAL_YANG_SUMMER_PRESSURE"
#: The Action Cannot Stay Small's overcomplete-light branch.
ACTION_CANNOT_STAY_SMALL = "TAL_YANG_THE_ACTION_CANNOT_STAY_SMALL"
#: The compiled passive row that records ownership of talents with no action or passive state of their own.
BLOCK = "printed_light"


def _held(actor: Any) -> list[tuple[str, str]]:
    """Every lasting typed state on the creature as (kind, source id): its conditions and its modifiers.

    ``kind`` is the condition id, or "modifier" for a rider that lands as a modifier. Engine clock rows
    ("condition:typed.concentration_deadline", a concentration deadline, a save marker) are not effect states, and a
    row only matches when its printed mechanic is also named by that state's source, so they never light anything.
    """
    held: list[tuple[str, str]] = [(str(condition.condition_id), str(condition.source_definition_id))
                                   for condition in actor.conditions.values()]
    held.extend(("modifier", str(modifier.source_definition_id)) for modifier in actor.modifiers.values())
    return held


def _names(source: str, mechanic: str) -> bool:
    """Whether ``source`` names ``mechanic`` as a whole token (never as the prefix of a longer id)."""
    start = 0
    while True:
        found = source.find(mechanic, start)
        if found < 0:
            return False
        end = found + len(mechanic)
        before = source[found - 1] if found else ""
        after = source[end] if end < len(source) else ""
        if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
            return True
        start = found + 1


def _carries(state: str, mechanic: str, held: Iterable[tuple[str, str]]) -> bool:
    """Whether one of the creature's states is the one this row names, filed by this mechanic."""
    if state == "modifier":
        return any(kind == "modifier" and _names(source, mechanic) for kind, source in held)
    return any(kind.startswith(state) and _names(source, mechanic) for kind, source in held)


def owns(engine: Any, actor: Any, feature: str) -> bool:
    """Whether this fighter compiled the named printed-light talent (the passive row :func:`seal_owned` writes)."""
    return any(row.get("block") == BLOCK and row.get("feature_id") == feature
               for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, ()))


def shed(engine: Any, subject: Any, mechanic: str, source: str, actor_id: str, expires_on: str | None) -> None:
    """File the curated printed light of ``mechanic`` on ``subject`` for ``expires_on``.

    Public helper for the ``light`` effect and the two producers below. The radii and the name always come from
    combat/rules/light_sources.json, so a printed light has one source of truth. A second light from the same source
    replaces the first instead of stacking; the stored condition is the engine's own ``condition:typed.light`` (it is
    saved, expires and shows on the sheet); no floats and no objects.
    """
    from .. import light_sources
    from ..lighting import LIGHT

    named = light_sources.row(mechanic)
    light = light_sources.light(mechanic)
    if not named or not light or subject is None or not subject.active:
        return
    for instance_id, held in list(subject.conditions.items()):
        if held.condition_id == LIGHT and held.source_actor_id == actor_id and held.source_definition_id == source:
            del subject.conditions[instance_id]
    engine._apply_condition(subject, LIGHT, source, actor_id, expires_on=expires_on,
                            data={"name": named["name"], "source_id": mechanic, "magical": light["magical"],
                                  "bright_ft": light["bright_ft"], "dim_ft": light["dim_ft"]})


@effect("light")
def light_effect(ctx: Any, row: dict[str, Any]) -> None:
    """A typed row that makes its subjects shed the printed light it names.

    ``light`` is the mechanic id of the curated row (or omitted, meaning this action's own source). The effect's own
    duration (or the ability's) is the clock, through the engine's ordinary expiry reader.
    """
    from ..typed_executor import default_subjects, effect_expiry

    mechanic = str(row.get("light") or ctx.source)
    for subject in default_subjects(ctx, row, harmful=False):
        shed(ctx.engine, subject, mechanic, ctx.source, ctx.actor.entity_id,
             effect_expiry(ctx, row, subject, condition=True))


@hook("compile_passives")
def seal_owned(rows: list[dict[str, Any]], info: dict[str, Any]) -> list[dict[str, Any]]:
    """Seal ownership of a printed-light talent the compiler otherwise skips (it has no action and no passive row)."""
    if SUMMER_PRESSURE in info["owned_ids"] and not any(row.get("feature_id") == SUMMER_PRESSURE for row in rows):
        rows = [*rows, {"block": BLOCK, "feature_id": SUMMER_PRESSURE}]
    return rows


@hook("mark_spent")
def summer_pressure(ctx: Any, name: str, subject: Any) -> None:
    """Summer Pressure: spending a Kindled Mark on yourself may emit its printed light until the start of your next turn."""
    if str(name) != "Kindled Mark" or subject is None or subject is not ctx.actor or not owns(ctx.engine, ctx.actor, SUMMER_PRESSURE):
        return
    from .needle import ask, checkpoint_id

    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "summer_pressure", ctx.actor.entity_id), ctx.actor,
                 "choice:needle.summer_pressure", ["emit"], labels={
                     "emit": "Emit bright light in a 10-foot radius and dim light for another 10 feet until the start of your next turn"},
                 allow_decline=True, preferred=["emit"], default="emit", target_id=ctx.actor.entity_id,
                 name="Summer Pressure", feature_id=SUMMER_PRESSURE,
                 prompt=f"Summer Pressure: {ctx.actor.display_name} spent a Kindled Mark on themself. Emit the printed light?")
    if not picked:
        return
    shed(ctx.engine, ctx.actor, SUMMER_PRESSURE, SUMMER_PRESSURE, ctx.actor.entity_id, "START_OF_SELF_NEXT_TURN")


@hook("reaction_resolved")
def overcomplete_light(engine: Any, event: Any) -> None:
    """The Action Cannot Stay Small: the overcomplete result lights the effect the completed action made.

    The engine models no created-effect object, so its carrier is the creature whose action was overcompleted; the
    light exists only on the failed-save branch, which is where the printed result lives.
    """
    if str(getattr(event, "source_definition_id", "")) != ACTION_CANNOT_STAY_SMALL:
        return
    failed = False
    for prior in reversed(engine.events):
        if prior is event:
            continue
        if prior.event_type == "SAVE_ROLLED" and str(prior.source_definition_id) == ACTION_CANNOT_STAY_SMALL:
            failed = not bool((prior.payload or {}).get("success"))
            break
    if not failed or not event.target_ids:
        return
    subject = engine.state.actors.get(event.target_ids[0])
    if subject is not None:
        shed(engine, subject, ACTION_CANNOT_STAY_SMALL, ACTION_CANNOT_STAY_SMALL, event.actor_id, "START_OF_SOURCE_NEXT_TURN")


@hook("light_sources")
def printed_light_sources(engine: Any) -> Any:
    """The light of every printed ability whose lasting state the creature currently holds."""
    from .. import light_sources
    from ..lighting import LightSource

    rows = light_sources.state_rows()
    if not rows:
        return None
    out: list[LightSource] = []
    for actor in list(engine.state.actors.values()):
        if not actor.active:
            continue
        held = _held(actor)
        if not held:
            continue
        cells = frozenset(engine._actor_cells(actor))
        if not cells:
            continue
        for row in rows:
            if not _carries(str(row["state"]), str(row["mechanic"]), held):
                continue
            out.append(LightSource(f"printed:{row['mechanic']}:{actor.entity_id}", str(row["name"]), cells,
                                   int(row["bright_ft"]), int(row["dim_ft"]), None, bool(row.get("magical")),
                                   following=actor.entity_id))
    return out or None

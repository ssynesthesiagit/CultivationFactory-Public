"""Lightning's Arc (rider lane 1, 2026-09-29): "you may Arc to another creature within N feet of the target".

The Lightning sphere's Core Rules define an Arc as a secondary hit on one creature (or object) near the creature a
Lightning technique just hit, with the technique's own printed range for it and its own printed effect on the secondary
target (Lightning Lash: Proficiency Bonus damage to a Charged or Conductive one within 5 feet; Chain Bolt: a Dexterity
save for half the Lash damage and a Charge, then a third for Proficiency Bonus; Crackling Arrow: Proficiency Bonus damage
to one creature within 5 feet).  Until now every one of those was a GM rider, or (Crackling Arrow) hit *everything* near
the target because a "creatures_in_area" damage row was the only way to reach a second creature.

Rows (all plug-in effects, so they ride any typed ability -- an attack's ``on_hit``, a modifier's ``effects``):

  {"type": "arc_begin"}
        Chain Bolt only: remembers whether the hit creature was Conductive *before* the technique marked it Charged, so
        "if both targets were Conductive before this technique resolved" can be checked for the third arc.
  {"type": "arc", "talent": "lash", "range_ft": 5, "needs_conductive": true, "chain": false,
   "effects": [...], "then": {<another arc row>}}
        Pick one creature within ``range_ft`` (raised by an owned ``arc_upgrade`` naming ``talent``) of the creature just
        hit -- hostile to the caster, visible, not the creature it arcs from, and (``needs_conductive``) Charged or
        Conductive -- and run ``effects`` on it.  With several candidates the caster chooses (combat/ext/needle.py's choice
        transport; the AI and an unanswered fight take the nearest).  ``chain`` keeps "no creature can be damaged more than
        once by this technique" and lets ``then`` (a further arc from the arc target) require
        ``"if_all_conductive_before": true``.  ``range_by_cl`` ([[low, high, feet], ...]) replaces ``range_ft`` for a
        range that grows with Cultivation Level (Crackling Arrow: 15 feet at CL 11).
        Further keys (Fivefold Thunder Circuit, Thousand-Spark Volley, One Circuit Under Heaven): ``count`` picks up to that many
        creatures (an integer, or "pb" / "twice_pb"; ``count_offset`` adds to it: the primary target is one of "up to twice your PB"); ``from_any`` measures the range from *any* creature already hit ("within 20
        feet of a previous target"); ``anchor: "actor"`` measures it from the caster instead ("within range"); ``needs_mark``
        (a list of mark names) replaces ``needs_conductive`` with "bears one of these marks from the caster".  Several picks are
        one "choose up to N" prompt when they need no chain, otherwise one prompt per pick, and each may be declined ("up to").
        ``range_if_marked`` ({"mark": "Charged", "range_ft": 15}) widens the range when the creature the arc starts from bears that
        mark ("If the attack hits a Charged target, increase the thunder radius to 15 feet").
        ``all: true`` offers the creatures in the area as one subset choice (unattended: every foe).
        ``allow_allies`` permits allied recipients, ``include_center`` permits the primary target in a report,
        and ``ignore_arc_upgrades`` keeps a thunder report's printed radius independent of Arc upgrades.
        ``creatures_near`` is the same row under a plainer name.
  {"type": "arc_tally"}
        In an ``on_fail``: counts this creature among those that failed the technique's saves.
  {"type": "arc_burst", "min_failed": 3, "radius_ft": 10, "effects": [...]}
        "If at least three targets fail their saves, choose one target that failed": once enough have (the primary target and
        every arc target), the caster picks one of them (the AI the one with the most foes around it) and ``effects`` run on each
        other hostile creature within ``radius_ft`` of it (Fivefold Thunder Circuit's reaction denial).
  {"type": "arc_damage", "basis": "pb" | "primary_half"}
        Lightning damage to the arc target: the caster's Proficiency Bonus, or half of what the creature the arc came
        from was just dealt by this technique (the rolled amount, before that creature's resistances).

An owned ``arc_upgrade`` feature block (combat/rules/feature_blocks.d/riders_lane1.json) widens the Arc of the talents it
names: Arc Primer (Lightning Lash's Arc reaches 10 feet, and a Conductive Arc target also becomes Charged) and Current
Beyond the Skin ("Your Arc range increases to 15 feet"); an upgrade only ever widens an Arc, never narrows one.

"Conductive" here is "bears a Charged or Conductive mark placed by the caster" (typed_executor's own if_marked rule --
"a creature is Conductive if it is currently Charged").  Wet and metallic creatures are not tracked on this table.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

CHARGED, CONDUCTIVE = "Charged", "Conductive"


FIELD = "TAL_LIGHTNING_CONDUCTIVE_FIELD"


def in_conductive_field(engine: Any, actor: Any, subject: Any) -> bool:
    """Conductive Field: "The area is Conductive." A creature inside any active field counts as Conductive (not Charged)."""
    from .. import zones

    return any(zone.active and str(zone.source_definition_id).endswith(FIELD) and zones._inside(engine, subject, zone)
               for zone in engine.state.zones.values())


def is_conductive(actor: Any, subject: Any, engine: Any = None) -> bool:
    """Whether ``subject`` bears a Charged or Conductive mark placed by ``actor``, or stands in the actor's Conductive Field."""
    from .. import typed_executor as te

    return any(te.bears_mark(subject, actor.entity_id, name) for name in (CHARGED, CONDUCTIVE)) or \
        (engine is not None and in_conductive_field(engine, actor, subject))


def _has_mark(engine: Any, actor: Any, row: Any, name: str) -> bool:
    from .. import typed_executor as te

    return te.bears_mark(row, actor.entity_id, name) or (name == CONDUCTIVE and in_conductive_field(engine, actor, row))


@hook("compile_block")
def _compile_arc_upgrade(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "arc_upgrade":
        return None
    return [{**row, "for": [str(name) for name in spec.get("for") or ["*"]], "range_ft": int(spec.get("range_ft") or 0),
             "conductive_becomes_charged": bool(spec.get("conductive_becomes_charged"))}]


def _upgrades(ctx: Any, talent: str) -> list[dict[str, Any]]:
    from .. import typed_reactions

    return [row for row in typed_reactions._rows(ctx.engine, ctx.actor.entity_id, "arc_upgrade") if talent in row["for"] or "*" in row["for"]]


def _range(ctx: Any, eff: dict[str, Any], center: Any = None) -> int:
    feet = int(eff.get("range_ft") or 0)
    wider = eff.get("range_if_marked")  # {"mark": "Charged", "range_ft": 15}: "If the attack hits a Charged target, increase the radius"
    if wider and center is not None:
        from .. import typed_executor as te

        if te.bears_mark(center, ctx.actor.entity_id, str(wider.get("mark") or CHARGED)):
            feet = max(feet, int(wider.get("range_ft") or 0))
    for low, high, value in eff.get("range_by_cl") or []:
        if int(low) <= int(ctx.numbers.get("cl") or 1) <= int(high):
            feet = int(value)
    for row in ([] if eff.get("ignore_arc_upgrades") else _upgrades(ctx, str(eff.get("talent") or ""))):
        feet = max(feet, row["range_ft"])  # "instead of 5 feet" / "increases to 15 feet": only ever a wider Arc
    return feet


def arc_state(ctx: Any) -> dict[str, Any]:
    """Shared per-resolution Arc ledger for Arcs and Lightning Chains; not fight state."""
    state = ctx.damage_cache.get("_arc_state")
    if not isinstance(state, dict):
        state = ctx.damage_cache["_arc_state"] = {"before": {}, "hit": [], "primary": None, "failed": []}
    return state


@effect("arc_begin")
def arc_begin(ctx: Any, eff: dict[str, Any]) -> None:
    primary = ctx.target if ctx.target is not None else (ctx.targets[0] if len(ctx.targets) == 1 else None)
    if primary is None:
        return
    ctx.damage_cache["_arc_state"] = {"before": {primary.entity_id: is_conductive(ctx.actor, primary, ctx.engine)}, "hit": [primary.entity_id],
                                     "primary": primary.entity_id, "failed": []}


@effect("creatures_near")
@effect("arc")
def arc(ctx: Any, eff: dict[str, Any]) -> None:
    center = ctx.target if ctx.target is not None else (ctx.targets[0] if len(ctx.targets) == 1 else None)
    if center is not None:
        _arc_from(ctx, eff, center)


def _count(ctx: Any, eff: dict[str, Any]) -> int:
    raw = eff.get("count", 1)
    pb = int(ctx.numbers.get("pb") or 1)
    return max(1, (pb if raw == "pb" else 2 * pb if raw == "twice_pb" else int(raw)) + int(eff.get("count_offset") or 0))


def _candidates(ctx: Any, eff: dict[str, Any], centers: list[Any], excluded: set[str], feet: int) -> list[Any]:
    """Legal active, visible creatures; hostile candidates precede allies, then nearest first."""
    from .. import stealth
    from .. import typed_executor as te

    engine, actor = ctx.engine, ctx.actor
    marks = [str(name) for name in eff.get("needs_mark") or ([CHARGED, CONDUCTIVE] if eff.get("needs_conductive") else [])]
    found: list[tuple[int, str, Any]] = []
    for row in engine.state.actors.values():
        if not row.active or row.entity_id in excluded or (not eff.get("allow_allies") and
                (row.entity_id == actor.entity_id or row.team_id == actor.team_id)):
            continue
        near = min(engine._distance_actor_to_actor(center, row) for center in centers)
        if near > feet or not stealth.sees(engine, actor, row):
            continue
        if marks and not any(_has_mark(engine, actor, row, name) for name in marks):
            continue
        found.append((near, row.entity_id, row))
    return [row for _, _, row in sorted(found, key=lambda item: (item[2].team_id == actor.team_id, *item[:2]))]


def _arc_from(ctx: Any, eff: dict[str, Any], center: Any) -> None:
    from .. import typed_executor as te
    from . import needle

    engine, actor = ctx.engine, ctx.actor
    if engine.state.terminal_result is not None:
        return
    state = arc_state(ctx)
    if center.entity_id not in state["hit"]:
        state["hit"].append(center.entity_id)
        state["before"].setdefault(center.entity_id, is_conductive(actor, center, engine))
        state["primary"] = state["primary"] or center.entity_id
    if eff.get("if_all_conductive_before") and not all(state["before"].get(who) for who in state["hit"]):
        return
    feet, count = _range(ctx, eff, center), _count(ctx, eff)
    if eff.get("all"):  # "creatures of your choice": unattended default is the foes; a player chooses the subset.
        anchor = [actor] if eff.get("anchor") == "actor" else [center]
        excluded = set() if eff.get("include_center") else set(state["hit"]) | {center.entity_id}
        candidates = _candidates(ctx, eff, anchor, excluded, feet)
        preferred = [row.entity_id for row in candidates if row.team_id != actor.team_id]
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "arc_area", center.entity_id), actor,
                            needle.CHOICE + "arc_area", [row.entity_id for row in candidates],
                            labels={row.entity_id: row.display_name for row in candidates}, preferred=preferred,
                            minimum=0, maximum=len(candidates), allow_decline=True, default_count=len(preferred),
                            default="first" if preferred else "decline", prompt=f"{ctx.action.display_name}: choose creatures within {feet} feet",
                            target_id=center.entity_id)
        for picked in candidates:
            if picked.entity_id not in chosen:
                continue
            _arc_to(ctx, eff, center, picked, state)
        return
    chained = bool(eff.get("chain") or eff.get("from_any") or eff.get("anchor") or count > 1)

    def centers() -> list[Any]:
        if eff.get("anchor") == "actor":
            return [actor]
        if eff.get("from_any"):
            return [engine.state.actors[who] for who in state["hit"] if who in engine.state.actors]
        return [center]

    def pick_rows() -> list[Any]:
        excluded = set(state["hit"]) if chained else {center.entity_id}
        candidates = _candidates(ctx, eff, centers(), excluded, feet)
        if not candidates:
            return []
        ids = [row.entity_id for row in candidates]
        labels = {row.entity_id: row.display_name for row in candidates}
        where = f"within {feet} feet of {center.display_name}" if not eff.get("anchor") else f"within {feet} feet"
        if count > 1 and not eff.get("from_any"):
            chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "arc", center.entity_id), actor, needle.CHOICE + "arc", ids,
                                labels=labels, prompt=f"{ctx.action.display_name}: pick up to {count} creatures {where}",
                                preferred=ids[:count], minimum=0, maximum=count, allow_decline=True, target_id=center.entity_id,
                                default_count=count)
            return [row for row in candidates if row.entity_id in chosen]
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "arc", center.entity_id, len(state["hit"])), actor,
                            needle.CHOICE + "arc", ids, labels=labels, allow_decline=True, minimum=0,
                            prompt=f"{ctx.action.display_name}: Arc to which creature {where}?" if count == 1 else
                            f"{ctx.action.display_name}: next creature {where} (decline to stop)",
                            preferred=[ids[0]], target_id=center.entity_id)
        picked = next((row for row in candidates if chosen and row.entity_id == chosen[0]), None)
        return [picked] if picked is not None else []

    if count > 1 and not eff.get("from_any"):
        for picked in pick_rows()[:count]:  # one "choose up to N" prompt
            _arc_to(ctx, eff, center, picked, state)
        return
    for _ in range(count):  # one pick at a time: each later one may lean on the one before
        rows = pick_rows()
        if not rows or engine.state.terminal_result is not None:
            break
        _arc_to(ctx, eff, center, rows[0], state)


def _arc_to(ctx: Any, eff: dict[str, Any], center: Any, picked: Any, state: dict[str, Any]) -> None:
    from .. import typed_executor as te

    engine, actor = ctx.engine, ctx.actor
    origins = [actor] if eff.get("anchor") == "actor" else \
        [engine.state.actors[who] for who in state["hit"] if who in engine.state.actors] if eff.get("from_any") else [center]
    geometry = {"origin_ids": [row.entity_id for row in origins], "range_ft": _range(ctx, eff, center)}
    was_conductive = is_conductive(actor, picked, engine)
    state["before"][picked.entity_id] = was_conductive
    state["hit"].append(picked.entity_id)
    engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=actor.entity_id, target_ids=(picked.entity_id,),
                         payload={"trigger": f"{actor.display_name}'s lightning arcs from {center.display_name} to {picked.display_name}."})
    sub = te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [picked], picked, ctx.damage_cache,
                     save_geometry=geometry)
    te.run_effects(sub, eff.get("effects") or [])
    if was_conductive and picked.active and any(row["conductive_becomes_charged"] for row in _upgrades(ctx, str(eff.get("talent") or ""))):
        te.run_effects(sub, [{"type": "mark", "mark": CHARGED, "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"},
                              "evidence": "If the Arc target is Conductive, it also becomes Charged until the start of your next turn"}])
    then = eff.get("then")
    if isinstance(then, dict) and picked.active:
        _arc_from(ctx, then, picked)


def _rolled_to(engine: Any, actor: Any, victim_id: str) -> int:
    for event in reversed(engine.events[-40:]):
        if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == actor.entity_id and victim_id in (event.target_ids or ()):
            return int((event.payload or {}).get("rolled_or_pending_damage") or 0)
    return 0


@effect("arc_damage")
def arc_damage(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor as te

    subject = ctx.target if ctx.target is not None else (ctx.targets[0] if len(ctx.targets) == 1 else None)
    if subject is None:
        return
    if eff.get("basis") == "primary_half":
        amount = _rolled_to(ctx.engine, ctx.actor, str(arc_state(ctx).get("primary") or "")) // 2
    else:
        amount = int(ctx.numbers.get("pb") or 0)
    if amount > 0:
        te._deal(ctx, subject, amount, "LIGHTNING")


@effect("arc_tally")
def arc_tally(ctx: Any, eff: dict[str, Any]) -> None:
    subject = ctx.target if ctx.target is not None else (ctx.targets[0] if len(ctx.targets) == 1 else None)
    if subject is not None and subject.entity_id not in arc_state(ctx)["failed"]:
        arc_state(ctx)["failed"].append(subject.entity_id)


@effect("arc_burst")
def arc_burst(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from . import needle

    engine, actor = ctx.engine, ctx.actor
    failed = [engine.state.actors[who] for who in arc_state(ctx)["failed"] if who in engine.state.actors]
    if len(failed) < int(eff.get("min_failed") or 1) or engine.state.terminal_result is not None:
        return
    feet = int(eff.get("radius_ft") or 10)

    def around(center: Any) -> list[Any]:
        return [row for row in engine.state.actors.values() if row.active and row.entity_id not in {actor.entity_id, center.entity_id}
                and row.team_id != actor.team_id and engine._distance_actor_to_actor(center, row) <= feet]

    ranked = sorted(failed, key=lambda row: (-len(around(row)), row.entity_id))
    center = ranked[0]
    if len(ranked) > 1:
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "arc_burst"), actor, needle.CHOICE + "arc_burst",
                            [row.entity_id for row in ranked], labels={row.entity_id: row.display_name for row in ranked},
                            prompt=f"{ctx.action.display_name}: which target that failed does the thunder crack around?",
                            preferred=[center.entity_id], target_id=center.entity_id)
        center = next((row for row in ranked if chosen and row.entity_id == chosen[0]), center)
    engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=actor.entity_id, target_ids=(center.entity_id,),
                         payload={"trigger": f"Thunder cracks around {center.display_name}."})
    for row in around(center):
        te.run_effects(te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [row], row, ctx.damage_cache), eff.get("effects") or [])

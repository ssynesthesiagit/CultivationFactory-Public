"""The Action Cannot Stay Small's selected overcomplete result.

A failed save selects ONE surplus, not all the extracted rule clauses. The
light/Vulnerability result selects an actual new summon, object or area from
the triggering accepted action's event window. Existing effects, updates and
the acting creature are never substituted. The source's timed receipt names
that recipient; light reads its current location and damage defenses consume
only its next-hit Vulnerability, independently of the light's deadline.

The willing branch's inherited typed effects are kept separate in reviewed
data; completing its other result models is outside this lighting correction.
No marker/owned reaction and no receipt means no changed behavior.
"""
from typing import Any

from . import effect, hook

FEATURE = "TAL_YANG_THE_ACTION_CANNOT_STAY_SMALL"
NAME = "The Action Cannot Stay Small"
RECEIPT = "condition:typed.overcomplete_effect"
LOCK = "condition:typed.overcomplete_action_lock"


def _action(ctx: Any) -> Any:
    action = ctx.engine.action_catalog.get(getattr(ctx.engine, "_active_action_source_id", ""))
    return action if action is not None and action.owner_id == ctx.target.entity_id else None


def _created(ctx: Any) -> dict[str, tuple[str, Any]]:
    """Only first creations by this action in this accepted use, never later upserts."""
    from .retained_updates import is_retained_update

    engine, action = ctx.engine, _action(ctx)
    if action is None:
        return {}
    start = next((i for i in range(len(engine.events) - 1, -1, -1)
                  if engine.events[i].event_type == "INTENT_ACCEPTED"
                  and engine.events[i].actor_id == ctx.target.entity_id
                  and engine.events[i].source_definition_id == action.source_definition_id), None)
    if start is None:
        return {}
    seen: set[str] = set()
    found = {}
    for i, event in enumerate(engine.events):
        payload = event.payload or {}
        if event.event_type == "SUMMON_APPEARED":
            keys = [("actor", key) for key in event.target_ids]
        elif event.event_type == "ZONE_CREATED":
            keys = [("zone", str((payload.get("zone") or {}).get("zone_id") or ""))]
        elif event.event_type == "OBJECT_UPDATED":
            keys = [("object", str((payload.get("object") or {}).get("object_id") or ""))]
        else:
            continue
        for kind, key in keys:
            fresh = key and (kind == "actor" or key not in seen)
            seen.add(key)
            if (not fresh or i <= start or is_retained_update(event.event_type, payload)
                    or event.actor_id != ctx.target.entity_id
                    or event.source_definition_id != action.source_definition_id):
                continue
            store = {"actor": engine.state.actors, "zone": engine.state.zones, "object": engine.state.objects}[kind]
            subject = store.get(key)
            if subject is not None and _active(kind, subject):
                found[key] = kind, subject
    from . import ai_controlled
    if ai_controlled(engine, ctx.actor):
        from .. import senses, target_knowledge
        found = {key: (kind, subject) for key, (kind, subject) in found.items()
                 if (target_knowledge.located(engine, ctx.actor, subject) if kind == "actor" else
                     senses.perceives_object(engine, ctx.actor, subject) if kind == "object" else
                     senses.perceives_cell(engine, ctx.actor, subject.center))}
    return found


def _active(kind: str, subject: Any) -> bool:
    return not subject.destroyed if kind == "object" else bool(subject.active)


def _name(kind: str, subject: Any) -> str:
    if kind == "actor":
        return subject.display_name
    name = str((subject.component if kind == "object" else subject.trigger_profile).get("name") or "Created effect")
    at = subject.position if kind == "object" else subject.center
    return f"{name} at ({at.x}, {at.y})"


def _ask(ctx: Any, key: str, labels: dict[str, str]) -> list[str]:
    from .needle import ask, checkpoint_id
    from .trigger_source import action_name

    return ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "overcomplete", key, ctx.actor.entity_id, ctx.target.entity_id),
        ctx.actor, "choice:needle.overcomplete_" + key, list(labels), labels=labels, name=NAME, feature_id=FEATURE,
        target_id=ctx.target.entity_id,
        prompt=f"{NAME}: {ctx.target.display_name} completed {action_name(ctx, 'the triggering action')}. Choose one result.")


@hook("choice_reactors")
def consent_owners(engine: Any) -> tuple[str, ...]:
    # Marks can be created inside the very action being completed. Enroll
    # potential recipients now; surplus checks the actual owned mark later.
    if any(row.get("feature_id") == FEATURE for rows in
           (getattr(engine, "typed_reaction_rows", {}) or {}).values() for row in rows):
        return tuple(engine.state.actors)
    return ()


@effect("yang_action_surplus", harmful=True)
def surplus(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import bears_mark, block_spend_mark, run_effects
    from .willing_targets import asks_consent
    from .trigger_source import action_name

    if ctx.target is None:
        return
    mark = next((name for name in ("Kindled Mark", "Overkindled Mark", "Rising Mark")
                 if bears_mark(ctx.target, ctx.actor.entity_id, name)), None)
    if mark is None:
        return
    willing = asks_consent(ctx.engine, ctx.intent or getattr(ctx.engine, "_active_intent", None), ctx.target, NAME,
        f"{NAME}: {ctx.actor.display_name} answers {ctx.target.display_name}'s {action_name(ctx, 'completed action')}. Accept a complete result, or refuse and make a Constitution saving throw against dangerous surplus?",
        prefer_accept=ctx.actor.team_id == ctx.target.team_id, asker=ctx.actor)
    block_spend_mark(ctx, {"mark": mark, "applies_to": "target"})
    run_effects(ctx, row.get("willing_effects") or [] if willing else [{
        "type": "save", "applies_to": "target", "ability": "con", "dc": "technique_save_dc",
        "on_fail": [{"type": "yang_overcomplete_result"}],
        "on_success": [{"type": "mark", "applies_to": "target", "mark": "Overkindled Mark",
                        "duration": {"kind": "until_removed"}}]}])


@effect("yang_overcomplete_result", harmful=True)
def result(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import run_effects
    from .effect_durations import token

    created = _created(ctx)
    labels = {
        "damage": "The acting creature takes 6d10 Fire, Radiant or Force damage (choose the type)",
        "expose": "The acting creature cannot benefit from Hidden or Invisible until the end of your next turn",
        "reactions": "The acting creature cannot take Reactions or willingly repeat this action until the end of its next turn"}
    if created:
        labels["light"] = "One effect this action created sheds bright light 20 feet and is vulnerable to the next damage roll that hits it before your next turn starts"
    picked = _ask(ctx, "result", labels)
    if not picked:
        return
    selected = picked[0]
    if selected == "damage":
        kind = _ask(ctx, "damage_type", {k: k.title() for k in ("fire", "radiant", "force")})
        if kind:
            run_effects(ctx, [{"type": "damage", "applies_to": "target", "dice": {"count": 6, "sides": 10},
                              "damage_types": kind}])
    elif selected == "expose":
        run_effects(ctx, [{"type": "exposed", "applies_to": "target", "against": "anyone",
                          "benefits": "hidden_or_invisible", "duration": {"kind": "until_end_of_your_next_turn"}}])
    elif selected == "reactions":
        until = token("end", ctx.target.entity_id, int(ctx.target.turns_started) + 1)
        run_effects(ctx, [{"type": "reaction_denied", "applies_to": "target", "expires_on": until}])
        action = _action(ctx)
        if action is not None:
            ctx.engine._apply_condition(ctx.target, LOCK, FEATURE, ctx.actor.entity_id, expires_on=until,
                data={"source": action.source_definition_id, "name": action.display_name,
                      "label": f"{NAME}: cannot repeat {action.display_name} until the end of its next turn"})
    elif selected == "light":
        chosen = _ask(ctx, "recipient", {key: _name(kind, subject) for key, (kind, subject) in created.items()})
        if not chosen:
            return
        key = chosen[0]
        kind, subject = created[key]
        ctx.engine._apply_condition(ctx.actor, RECEIPT, FEATURE, ctx.actor.entity_id,
            expires_on=token("start", ctx.actor.entity_id, int(ctx.actor.turns_started) + 1),
            data={"recipient": key, "kind": kind, "vulnerable": 1, "name": _name(kind, subject),
                  "label": f"{NAME}: {_name(kind, subject)} sheds bright light 20 feet and is vulnerable to its next damage roll until your next turn starts"})


@hook("candidate_allowed")
def no_repeat(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    for held in actor.conditions.values():
        if held.condition_id == LOCK and held.data.get("name") == getattr(action, "display_name", None):
            return False
    return None


def _receipts(engine: Any, recipient: str = "", *, vulnerable: bool = False) -> list[tuple[Any, Any]]:
    return [(owner, held) for owner in engine.state.actors.values() for held in owner.conditions.values()
            if held.condition_id == RECEIPT and (not recipient or held.data.get("recipient") == recipient)
            and (not vulnerable or held.data.get("vulnerable") == 1)]


@hook("light_sources")
def lights(engine: Any) -> Any:
    from .. import light_sources
    from ..lighting import LightSource

    light = light_sources.light(FEATURE)
    out = []
    for owner, held in _receipts(engine):
        kind, key = held.data["kind"], held.data["recipient"]
        store = {"actor": engine.state.actors, "zone": engine.state.zones, "object": engine.state.objects}[kind]
        subject = store.get(key)
        if subject is None or not _active(kind, subject):
            continue
        cells = (engine._actor_cells(subject) if kind == "actor" else
                 [(c.x, c.y) for c in subject.affected_cells] if kind == "zone" else
                 [(subject.position.x, subject.position.y)])
        out.append(LightSource("overcomplete:" + held.instance_id, NAME, frozenset(cells),
            light["bright_ft"], light["dim_ft"], magical=light["magical"],
            following=key if kind == "actor" else None))
    return out or None


@hook("damage_defenses")
def vulnerability(engine: Any, target: Any, damage_type: str, typed: Any, source_actor_id: str | None) -> Any:
    if _receipts(engine, target.entity_id, vulnerable=True):
        return [{"kind": "vulnerability", "damage_types": [damage_type]}]
    return None


@hook("object_damage_defenses")
def object_vulnerability(engine: Any, actor: Any, obj: Any, packets: Any, source: str) -> Any:
    if _receipts(engine, obj.object_id, vulnerable=True):
        return [{"kind": "vulnerability", "damage_types": sorted({kind for _, kind in packets})}]
    return None


@hook("wall_defenses")
def wall_vulnerability(ctx: Any, zone: Any, stats: dict[str, Any]) -> Any:
    if _receipts(ctx.engine, zone.zone_id, vulnerable=True):
        kind = str(((ctx.typed or {}).get("wall_weapon") or {}).get("damage_type") or "UNTYPED").upper()
        return {**stats, "vulnerable": sorted(set(stats.get("vulnerable") or ()) | {kind})}
    return None


def _consume(engine: Any, key: str) -> None:
    for owner, held in _receipts(engine, key, vulnerable=True):
        engine._update_condition_data(owner, held, {**held.data, "vulnerable": 0,
            "label": f"{NAME}: {held.data['name']} sheds bright light 20 feet until your next turn starts (next-hit Vulnerability spent)"}, FEATURE)


@hook("event", nested=True)
def damage_consumes(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == "DAMAGE_COMMITTED":
        for key in kwargs.get("target_ids") or ():
            _consume(engine, key)
    elif event_type == "OBJECT_UPDATED" and "damage" in (kwargs.get("payload") or {}):
        _consume(engine, str(((kwargs["payload"].get("object") or {}).get("object_id")) or ""))


@hook("wall_attack_damage")
def wall_hit(ctx: Any, zone: Any, section: Any, amount: int, melee: bool) -> None:
    _consume(ctx.engine, zone.zone_id)

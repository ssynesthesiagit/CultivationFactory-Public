"""Shared helpers for the Spirit Awakening Tradition plug-ins (rider lane C8, 2026-09-30: "i want everything we can automated").

Used by combat/ext/ancestral_channeler.py and the other C8 tradition modules (each module's docstring names the helpers it uses).
No gameplay of its own except the ownership block below.

Ownership: combat/rules/feature_blocks.d/riders_c8.json gives a character that owns a tradition feature one passive row
``{"block": "spirit_tradition", "kind": "<feature suffix>", "feature_id": ...}`` (compiled by ``ownership_block``; an entry with
``"keeps_compiling": true`` is an action feature whose typed action still compiles). ``row(engine, actor, kind)`` is the question every C8 hook asks first, so its hooks are inert
for anyone else and for fights saved before (their bundles carry no such row).

Public helpers:
  row(engine, actor, kind)             the actor's compiled ownership row of that kind, or None
  feature_of(action)                   the mechanic id an action was compiled from (an option's parent), or ""
  is_spirit_feature(action)            True for a Spirit Awakening Path feature or Spirit Tradition feature action
  activation_events(engine, ctx)       the fight events this typed activation produced so far (start index noted at technique_start;
                                       transient, never saved; a replay re-runs the same activation and notes it again)
  damaged_by(engine, ctx)              creatures this activation dealt positive damage (HP or Temporary HP) to, in event order
  affected_by(engine, ctx)             creatures this activation targeted or changed (damage, conditions, healing, Temporary HP)
  context(engine, actor, action, targets, numbers=None)
                                       a typed_executor.Context for running typed effect rows as ``action`` of ``actor``
  numbers(engine, actor)               the actor's compiled Cultivation numbers (pb, save_dc, key_mod, cl) from any of its typed
                                       actions; for reactions and triggered riders that have no action of their own
  feature_action(engine, actor, feature)
                                       the actor's compiled action for ``feature``, or a stand-in carrying its id and numbers()
  action_named(engine, actor, name)    the actor's compiled action with that display name (e.g. "Mind Spike"), or None
  run_action(engine, actor, action, target, intent, effects=None)
                                       run ``action``'s typed effects (or ``effects``) against ``target`` as ``actor``
  mind_spike(engine, actor, target, intent, *, dice_delta=0, maximize=False)
                                       the actor's own Mind Spike against ``target`` with ``dice_delta`` damage dice ("one die fewer": -1)
                                       or its damage dice maximized on a failed save; False when the actor has no Mind Spike
  save(ctx, subject, ability, on_fail=None, on_success=None)
                                       one typed saving throw by ``subject`` against ctx's numbers; True when it failed
  remove(engine, holder, condition, reason)
                                       take that exact condition instance off ``holder`` (evented CONDITION_REMOVED)
  suppress(engine, holder, condition, source, by, why)
                                       hide that exact condition instance until the end of ``holder``'s next turn; it comes back
                                       then (suppressed_effects clock) if its own time has not run out (restore at turn_end below);
                                       ``clock``: whose next turn it lasts through (default the holder's)
  delay_condition(ctx, effect_row, name) / land_delayed_condition(engine, holder, data) / landing(engine, holder)
                                       keep a typed condition held back now; apply it later from its source (False when that
                                       creature is gone); landing is True while it is being applied
  routes(engine, actor, feet, through=(), ignore_plain_difficult=False, all_creatures=False)
                                       legal unoccupied end squares within ``feet`` and the route to each (grid.reachable); the start
                                       square is included with an empty route. ``through``: creatures whose spaces the route may cross;
                                       ``all_creatures``: any; ``ignore_plain_difficult``: the map's (nonmagical) difficult terrain is free.
  plain_difficult(engine)              the map's own (nonmagical) difficult squares
  choose_route(engine, actor, options, intent, *, checkpoint, prompt, name, feature, preferred=None, stay=True)
                                       ask ``actor`` (needle.ask) for one of ``options`` (routes() output); the chosen route, or None
                                       (stayed / declined). The AI takes ``preferred`` (else staying put).
  can_react(actor)                     the creature can take a Reaction now (active, Reaction unspent, no condition denying Reactions)
  pick_creature(engine, intent, chooser, creatures, *, checkpoint, choice_id, prompt, name, feature_id, preferred=None,
                allow_decline=False)   one creature the chooser picks through needle.ask (player on Ask me is asked; an AI chooser
                                       takes ``preferred`` or the first); None on decline or when nobody qualifies. needle.ask's
                                       transport only carries choice ids under "choice:needle." -- use "choice:needle.<topic>.<name>".
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

BLOCK = "spirit_tradition"
SPIRIT_PREFIXES = ("tianxia.path.spirit_awakening.", "tianxia.tradition.spirit.")
_STARTS = "_c8_activation_starts"


@hook("compile_block")
def ownership_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    # "keeps_compiling": the feature is also an action (or options): it still compiles as it did (typed_reactions.compile_blocks).
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), **({"keeps_compiling": True} if spec.get("keeps_compiling") else {})}]


@effect("spirit_tradition")
def documented_elsewhere(ctx: Any, row: dict[str, Any]) -> None:
    """A typed marker row naming the plug-in that runs the feature (``runs``); it does nothing itself (not a GM line)."""
    return None


def row(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    if actor is None:
        return None
    return next((entry for entry in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
                 if entry.get("block") == BLOCK and entry.get("kind") == kind), None)


def feature_of(action: Any) -> str:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    return str(typed.get("option_of") or typed.get("source") or "")


def is_spirit_feature(action: Any) -> bool:
    return feature_of(action).startswith(SPIRIT_PREFIXES)


def proficient_weapon(typed: dict[str, Any]) -> bool:
    """True when a compiled attack row is a weapon attack the owner is proficient with.

    Several printed Spirit features qualify a rider with "a weapon you are proficient with" (Flow After the
    Strike; a Martial Strike on the Compass Strike). The compiler already records the character's own training on
    every compiled weapon row (``factory_compiler._weapon_proficiency`` writes ``proficient`` next to ``weapon``),
    so the table reads that field instead of counting every compiled weapon attack as qualified. Rows that carry
    no ``weapon`` are unarmed strikes, natural weapons or techniques, which need no proficiency and return False
    here only because they are never weapon rows; callers that accept those kinds test for them first.
    """
    return bool(typed.get("weapon")) and typed.get("proficient") is not False


@hook("technique_start")
def note_activation_start(engine: Any, actor: Any, action: Any) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _STARTS)
    engine.__dict__.setdefault(_STARTS, {})[(actor.entity_id, action.source_definition_id)] = len(engine.events)
    return None


def activation_events(engine: Any, ctx: Any) -> list[Any]:
    start = (engine.__dict__.get(_STARTS) or {}).get((ctx.actor.entity_id, ctx.source))
    return list(engine.events[start:]) if start is not None else []


def damaged_by(engine: Any, ctx: Any) -> list[Any]:
    out: list[Any] = []
    for event in activation_events(engine, ctx):
        if event.event_type != "DAMAGE_COMMITTED" or event.source_definition_id != ctx.source:
            continue
        payload = event.payload or {}
        if int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) <= 0:
            continue
        for target_id in event.target_ids:
            creature = engine.state.actors.get(target_id)
            if creature is not None and creature is not ctx.actor and creature not in out:
                out.append(creature)
    return out


_CHANGED = {"DAMAGE_COMMITTED", "CONDITION_APPLIED", "MODIFIER_APPLIED", "HEALING_APPLIED", "TEMP_HP_GRANTED"}


def affected_by(engine: Any, ctx: Any) -> list[Any]:
    out: list[Any] = [creature for creature in ctx.targets if creature is not None and creature is not ctx.actor]
    for event in activation_events(engine, ctx):
        if event.event_type not in _CHANGED or event.source_definition_id != ctx.source:
            continue
        for target_id in event.target_ids:
            creature = engine.state.actors.get(target_id)
            if creature is not None and creature is not ctx.actor and creature not in out:
                out.append(creature)
    return out


def context(engine: Any, actor: Any, action: Any, targets: list[Any], numbers: dict[str, Any] | None = None, intent: Any = None) -> Any:
    from .. import typed_executor

    typed = dict((action.parameters or {}).get("typed") or {})
    if numbers is not None:
        typed["numbers"] = dict(numbers)
    return typed_executor.Context(engine, actor, action, intent if intent is not None else engine._active_intent, typed,
                                  list(targets), targets[0] if len(targets) == 1 else None, {})


def numbers(engine: Any, actor: Any) -> dict[str, Any]:
    """The actor's compiled cultivation numbers (Proficiency Bonus, Cultivation Save DC, key modifier, CL), read from any of its typed
    actions -- for reactions and triggered riders that have no action of their own."""
    for action_id in actor.action_ids:
        action = engine.action_catalog.get(action_id)
        found = (((action.parameters or {}).get("typed") or {}).get("numbers") if action is not None else None) or {}
        if found.get("save_dc"):
            return dict(found)
    return {"pb": 2, "save_dc": 10, "key_mod": 0, "cl": 1}


def feature_action(engine: Any, actor: Any, feature: str) -> Any:
    """Return the primary compiled feature action, then a derived action or stand-in.

    Spirit tradition repeat saves and triggered riders use this helper. Derived
    actions can carry the same typed source (for example a feature's upkeep
    options); prefer the compiled id ending in the full feature id so repeat
    saves retain the originating feature's numbers and event identity.
    """
    for action_id in actor.action_ids:
        action = engine.action_catalog.get(action_id)
        if action is not None and feature_of(action) == feature and action_id.endswith(feature):
            return action
    for action_id in actor.action_ids:
        action = engine.action_catalog.get(action_id)
        if action is not None and feature_of(action) == feature:
            return action
    base = next(iter(engine.action_catalog.values()))
    return base.model_copy(update={"source_definition_id": feature, "display_name": feature.rsplit(".", 1)[-1].replace("_", " ").title(),
                                   "parameters": {"typed": {"numbers": numbers(engine, actor), "effects": [], "riders": []}}})


def action_named(engine: Any, actor: Any, name: str) -> Any:
    return next((engine.action_catalog[a] for a in actor.action_ids if a in engine.action_catalog and engine.action_catalog[a].display_name == name), None)


def run_action(engine: Any, actor: Any, action: Any, target: Any, intent: Any, effects: list[Any] | None = None) -> None:
    from .. import typed_executor

    typed = dict((action.parameters or {}).get("typed") or {})
    typed["numbers"] = dict(typed.get("numbers") or {})
    ctx = typed_executor.Context(engine, actor, action, intent if intent is not None else engine._active_intent, typed, [target], target, {})
    typed_executor.run_effects(ctx, effects if effects is not None else typed.get("effects") or [])


def drop_held(engine: Any, chooser: Any, holder: Any, feature: str, intent: Any = None, *, triggering_command: str = "") -> bool:
    """Choose a real, removable held object and journal its ordinary dropped state."""
    from . import needle, scoundrel_riders

    items = [item for item in scoundrel_riders.held_possessions(engine, holder)
             if not any(item.get(flag) for flag in ("artifact", "soul_bound", "fused", "protected", "sealed"))]
    if not items:
        from . import note
        note(engine, feature, chooser, f"{holder.display_name} has no removable held object.", (holder.entity_id,))
        return False
    options = {str(item["object"]): item for item in items}
    ability = getattr(engine.action_catalog.get(feature), "display_name", None) or feature.rsplit(".", 1)[-1].replace("_", " ").title()
    trigger = f" after {triggering_command}" if triggering_command else ""
    picked = needle.ask(engine, intent or engine._active_intent,
        needle.checkpoint_id(engine, "SPIRIT_DROP", holder.entity_id), chooser,
        "choice:needle.spirit.drop", list(options),
        labels={key: str(item.get("name") or "Object") for key, item in options.items()},
        preferred=list(options)[:1], name=f"{ability}: drop a held object", feature_id=feature,
        target_id=holder.entity_id,
        prompt=f"{ability}{trigger}: choose one held object for {holder.display_name} to drop at its feet; no extra cost.")
    return bool(picked and scoundrel_riders.drop_held_object(engine, holder, options[picked[0]], source=feature, by=chooser))


def _effect_rows(effects: Any):
    for entry in effects or []:
        if isinstance(entry, dict):
            yield entry
            for key in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                yield from _effect_rows(entry.get(key))


def mind_spike(engine: Any, actor: Any, target: Any, intent: Any, *, dice_delta: int = 0, maximize: bool = False) -> bool:
    import copy

    spike = action_named(engine, actor, "Mind Spike")
    if spike is None:
        return False
    from factory_authoring.typed_mechanics import dice_for_cl

    typed = (spike.parameters or {}).get("typed") or {}
    effects = copy.deepcopy(typed.get("effects") or [])
    for entry in _effect_rows(effects):
        if entry.get("type") != "damage":
            continue
        if entry.get("dice_by_cl"):
            entry["dice_by_cl"] = [[low, high, max(0, count + dice_delta), sides] for low, high, count, sides in entry["dice_by_cl"]]
        elif isinstance(entry.get("dice"), dict):
            entry["dice"] = {**entry["dice"], "count": max(0, int(entry["dice"].get("count") or 1) + dice_delta)}
        if maximize:  # "maximum damage on its damage dice": the dice become their highest total
            dice = dice_for_cl(entry.get("dice_by_cl"), (typed.get("numbers") or {}).get("cl")) or entry.get("dice") or {}
            entry["flat"] = int(entry.get("flat") or 0) + int(dice.get("count") or 0) * int(dice.get("sides") or 0)
            entry["dice"], entry["dice_by_cl"] = None, None
    run_action(engine, actor, spike, target, intent, effects)
    return True


def save(ctx: Any, subject: Any, ability: str, on_fail: list[Any] | None = None, on_success: list[Any] | None = None) -> bool:
    from .. import typed_executor

    before = len(ctx.engine.events)
    sub = context(ctx.engine, ctx.actor, ctx.action, [subject], ctx.numbers, ctx.intent)
    typed_executor.block_save(sub, {"type": "save", "ability": ability, "applies_to": "target", "on_fail": on_fail or [], "on_success": on_success or []})
    rolled = [e for e in ctx.engine.events[before:] if e.event_type == "SAVE_ROLLED" and e.actor_id == subject.entity_id]
    if not rolled:
        return False
    payload = rolled[-1].payload or {}
    if "success" in payload:
        return not payload["success"]
    return int((payload.get("roll") or payload).get("total") or 0) < int(payload.get("dc") or 0)


def remove(engine: Any, holder: Any, condition: Any, reason: str) -> None:
    for iid, held in list(holder.conditions.items()):
        if held is condition:
            holder.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=held.source_actor_id,
                                 target_ids=(holder.entity_id,), payload={"condition_id": held.condition_id, "instance_id": iid, "reason": reason})


def pick_creature(engine: Any, intent: Any, chooser: Any, creatures: list[Any], *, checkpoint: str, choice_id: str, prompt: str,
                  name: str, feature_id: str, preferred: Any = None, allow_decline: bool = False) -> Any:
    from . import needle

    creatures = [creature for creature in creatures if creature is not None]
    if not creatures:
        return None
    by_id = {creature.entity_id: creature for creature in creatures}
    first = preferred.entity_id if preferred is not None and preferred.entity_id in by_id else creatures[0].entity_id
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, checkpoint, feature_id), chooser, choice_id, list(by_id),
                        labels={key: creature.display_name for key, creature in by_id.items()}, prompt=prompt, preferred=[first],
                        allow_decline=allow_decline, name=name, feature_id=feature_id,
                        default="decline" if allow_decline and preferred is None else "first")
    return by_id.get(chosen[0]) if chosen else None


def can_react(actor: Any) -> bool:
    """Shared predicate (typed_reactions.can_react) without a row: honors reaction denial, SUPPRESS and disabling rules."""
    from ..typed_reactions import can_react as shared

    return shared(None, actor)


def plain_difficult(engine: Any) -> set[tuple[int, int]]:
    from .. import zones

    return {(cell.x, cell.y) for zone in zones.map_zones(engine) if zone.trigger_profile.get("difficult") for cell in zone.affected_cells}


def routes(engine: Any, actor: Any, feet: int, *, through: tuple[Any, ...] = (), ignore_plain_difficult: bool = False,
           all_creatures: bool = False) -> dict[Any, tuple[tuple[Any, ...], int]]:
    """Legal unoccupied ends within ``feet`` of ``actor`` and the route to each (the start itself, with an empty route, included)."""
    occupied = engine._occupied_cells_except(actor.entity_id)
    passable = set() if all_creatures else set(occupied)
    for creature in through:
        passable -= set(engine._actor_cells(creature))
    difficult = engine._hostile_difficult_cells(actor)
    if ignore_plain_difficult:
        difficult = difficult - plain_difficult(engine)
    footprint = engine._footprint(actor)
    found = engine.grid.reachable(actor.position, movement_ft=feet, occupied_cells=passable, difficult_cells=difficult, footprint=footprint)
    out = {actor.position: ((actor.position,), 0)}
    for cell, (path, cost) in found.items():
        if cost <= feet and cell != actor.position and engine.grid.placement_legal(cell, footprint=footprint, occupied_cells=occupied):
            out[cell] = (tuple(path), int(cost))
    return out


def choose_route(engine: Any, actor: Any, options: dict[Any, tuple[tuple[Any, ...], int]], intent: Any, *, checkpoint: str, prompt: str,
                  name: str, feature: str, preferred: Any = None, stay: bool = True,
                  target_id: str | None = None) -> tuple[Any, ...] | None:
    from . import needle

    ordered = sorted(options, key=lambda cell: (cell != preferred, options[cell][1], cell.y, cell.x))  # the preferred square first
    ids = [needle.cell_id(cell) for cell in ordered if stay or cell != actor.position][:48]
    labels = {needle.cell_id(cell): (f"Move to {cell.x},{cell.y} ({options[cell][1]} ft)" if cell != actor.position else "Stay where you are")
              for cell in ordered}
    first = needle.cell_id(preferred) if preferred is not None else needle.cell_id(actor.position)
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, checkpoint, actor.entity_id), actor, f"choice:needle.{checkpoint.lower()}",
                        ids, labels=labels, prompt=prompt, preferred=[first] if first in ids else [], allow_decline=True,
                        default="first", name=name, feature_id=feature, target_id=target_id)
    if not chosen:
        return None
    cell = needle.position_of(chosen[0])
    found = next((path for spot, (path, _cost) in options.items() if spot == cell), None)
    return found if found and len(found) > 1 else None


# ------------------------------------------------------------------------------------------ what a placed condition remembers
_DATA = "c8_round_data:"


def _instance_id(holder: Any, condition: Any) -> str | None:
    return next((key for key, held in holder.conditions.items() if held is condition), None)


def data_of(holder: Any, condition: Any) -> dict[str, Any]:
    """A placed condition's data together with what ``set_data`` changed since it was placed."""
    iid = _instance_id(holder, condition)
    extra = holder.turn_flags.get(_DATA + iid) if iid is not None else None
    return {**(condition.data or {}), **(extra or {})}


def set_data(holder: Any, condition: Any, **changes: Any) -> None:
    """Change what a placed condition remembers (successful saves so far, "used once", the round it was last used). A saved fight is
    replayed from its events, and a condition's data is recorded only by the commit that placed it, so changing ``condition.data`` later
    is lost on reload (the replay then fails its state check). The changes are kept on the holder's turn flags instead: every commit
    records them, and a key holding "_round_" survives the start of the holder's turns (gate2_engine._system_start_turn)."""
    iid = _instance_id(holder, condition)
    if iid is not None:
        key = _DATA + iid
        holder.turn_flags[key] = {**(holder.turn_flags.get(key) or {}), **changes}


# ------------------------------------------------------------------------------------------ suppressed until the end of its next turn
SUPPRESSED = "condition:typed.spirit_suppressed"


def suppress(engine: Any, holder: Any, condition: Any, source: str, by: str, why: str, *, clock: Any = None, this_turn: bool = False) -> None:
    """Suppress one condition instance "until the end of the creature's next turn" (Echo Scribe's Rewrite the Margin, Grief Eater's Eat
    the Bitter Memory): taken off now, put back at the end of its next turn with its own remaining time (combat/ext/suppressed_effects.py).
    ``this_turn``: back at the end of the current turn of the clock creature instead (Well of Hours' Friendly Current, "until the end of
    the turn")."""
    from .suppressed_effects import lifetime

    iid = next((key for key, held in holder.conditions.items() if held is condition), None)
    if iid is None:
        return
    lifetime_clock = lifetime(engine, holder, condition)
    holder.conditions.pop(iid)
    engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=by, target_ids=(holder.entity_id,),
                         payload={"condition_id": condition.condition_id, "instance_id": iid, "reason": "SUPPRESSED"})
    keeper = clock if clock is not None else holder  # whose next turn it lasts through ("until the end of your next turn": the user's)
    engine._apply_condition(holder, SUPPRESSED, source, by, expires_on="UNTIL_REMOVED",
                            data={"condition": condition.model_dump(mode="json"), "lifetime": lifetime_clock, "clock_actor": keeper.entity_id,
                                  "restore_after_turn": int(keeper.turns_started) + (0 if this_turn else 1),
                                  "label": f"{condition.condition_id.rsplit('.', 1)[-1].replace('_', ' ').title()} suppressed until the end of "
                                           f"{'this' if this_turn else 'its next'} turn ({why})"})


@hook("turn_end")
def restore_suppressed(engine: Any, ending: Any, *, nominal: bool = False) -> None:
    from .suppressed_effects import restore, saved_lifetime
    from .effect_durations import custom_turn_due

    for holder in list(engine.state.actors.values()):
        for iid, held in list(holder.conditions.items()):
            data = held.data or {}
            if held.condition_id != SUPPRESSED or str(data.get("clock_actor") or holder.entity_id) != ending.entity_id \
                    or not custom_turn_due(ending, int(data.get("restore_after_turn") or 0),
                                           holder.turn_flags, iid, nominal=nominal):
                continue  # until the end of the clock creature's next turn
            holder.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=held.source_actor_id, target_ids=(holder.entity_id,),
                                 payload={"condition_id": SUPPRESSED, "instance_id": iid, "reason": "ENDED"})
            restore(engine, holder, data.get("condition") or {}, saved_lifetime(holder, held))


@hook("nominal_slot_boundary")
def nominal_suppression(engine: Any, actor: Any, checkpoint: str) -> None:
    if checkpoint == "END_OF_TURN":
        restore_suppressed(engine, actor, nominal=True)


# ------------------------------------------------------------------------------------------ a condition that waits, then lands
LANDING = "_c8_delayed_landing"


def delay_condition(ctx: Any, effect_row: dict[str, Any], name: str) -> dict[str, Any]:
    """What to keep of a typed condition held back now and applied later (Fate Reader's Borrowed Ending, Grief Eater's Hold the Door)."""
    import copy

    return {"condition": name, "row": copy.deepcopy(effect_row), "source": ctx.source, "source_actor": ctx.actor.entity_id}


def landing(engine: Any, holder: Any) -> bool:
    """True while a delayed condition is being applied to ``holder`` (so no delaying reaction answers it again)."""
    return engine.__dict__.get(LANDING) == holder.entity_id


def land_delayed_condition(engine: Any, holder: Any, data: dict[str, Any]) -> bool:
    """Apply a delayed condition from its original source; False (nothing applied) when that creature is gone."""
    from .. import typed_executor

    source = engine.state.actors.get(str(data.get("source_actor") or ""))
    if source is None or not source.active or not holder.active:
        return False
    action = engine.action_catalog.get(str(data.get("source") or "")) or feature_action(engine, source, str(data.get("source") or ""))
    typed = dict((action.parameters or {}).get("typed") or {})
    typed["numbers"] = dict(typed.get("numbers") or numbers(engine, source))
    ctx = typed_executor.Context(engine, source, action, engine._active_intent, typed, [holder], holder, {})
    engine.__dict__[LANDING] = holder.entity_id
    try:
        typed_executor.block_condition(ctx, dict(data.get("row") or {"type": "condition", "applies_to": "target", "condition": data.get("condition")}))
    finally:
        engine.__dict__.pop(LANDING, None)
    return True

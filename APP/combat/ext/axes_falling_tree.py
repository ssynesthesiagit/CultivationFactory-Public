"""Law of the Falling Tree (Axes, CL 10): the fallen body, shield, gate or line shakes loose the ground around it.

Owner text (APP/authority/typed_mechanics/rules_text.json, TAL_AXES_LAW_OF_THE_FALLING_TREE):
"When you knock a creature Prone, reduce a creature to 0 HP, destroy a significant object, or suppress a barrier panel with an
Axes talent, you may spend 1 CP, 1 Stamina, or expend Martial Focus. Choose one creature within 10 feet of the fallen target or
broken object. That creature makes a Dexterity saving throw. Failed Save: It falls Prone or is pushed 10 feet away from the
fall. Successful Save: It moves 5 feet to a space of its choice that is not closer to you, if it can."

Why it needed a plug-in: the talent compiled one inert ``rider`` row (authority/typed_mechanics/reviewed_final.d/
review_sw-athletics.json), so no Dexterity save, no Prone, no push and no withdrawal ever reached the table. Its trigger also
names a *different* creature than the one that fell, which no modifier on the attack can express -- which is why the sweep guard
(tests/test_review_sw-athletics.py::test_law_of_the_falling_tree_is_not_a_modifier_on_every_hewing_strike) keeps it off every
Hewing Strike option, and it stays that way here.

How it runs
  * Ownership and the printed save are this talent's feature block (combat/rules/feature_blocks.d/auto53.json, block
    "axes_falling_tree", kind "falling_tree"): the payment alternatives, the Dex save and both outcome branches are data, sealed
    into the bundle's typed_passives by combat/typed_reactions.py compile_blocks. Without that row every hook here returns
    early, so no other character and no old saved fight changes.
  * The trigger is the owner's own doing with an Axes talent (an action or a rider it delivered): a creature it knocked Prone
    for the first time (a refresh of a Prone it already carried is not a new fall, and neither is the wielder going down),
    one it actually took from above 0 Hit Points down to 0, or an object it destroyed (an OBJECT_UPDATED record; the broken
    object is its own anchor, which the printed text names). Suppressing a barrier panel stays the GM's: a panel's
    suppression is not a recorded state on this table (reported as the remaining rider).
  * The owner is asked at the moment of the fall, while the fallen creature is still on the map: pay 1 Qi, 1 Stamina or 1
    Martial Focus (the printed alternatives, named from the pools it can actually pay), then name one creature within 10
    feet of the fallen one. Every prompt names the action that brought it down, not "a blow".
  * A Failed Save is the printed pair -- the wielder chooses Prone or the 10-foot push (Ask me; the AI takes Prone). The push
    runs away from the *fall* (the fallen creature or the broken object), not away from the wielder, and goes through the
    shared forced-movement path, so the pushed creature still answers with its own reactions. A Successful Save is the
    creature's own withdrawal: it picks a legal square up to 5 feet off that is not closer to the owner and moves there
    through the shared voluntary-movement path (combat/ext/needle.py candidates, granted_movement.resolve_path), so the
    5 feet come out of its own movement allowance, leave its space normally, and "if it can" stays true -- a creature that
    has spent its movement is left standing instead of being asked a question it cannot pay for.  When it cannot move, the
    log names which of the three reasons applies -- squares exist but all of them are nearer the wielder, the creature
    has no movement or no square at all, or the movement it has is spent -- so a player is never told their movement is
    spent when it is not, nor told it has no square when it has not been offered one.
"""

from __future__ import annotations

from .map_positions import map_position

from typing import Any

from . import effect, hook, note
from .needle import CHOICE, ask, checkpoint_id

TALENT = "TAL_AXES_LAW_OF_THE_FALLING_TREE"


@hook("match_start")
def record_push_bounds_policy(engine: Any) -> None:
    """New owning fights bound push routes before the forced-movement question.

    Unstamped saves keep the previous positive-edge route length and therefore
    the same reaction question; negative-coordinate crashes have no committed
    preimage to preserve. The existing genesis carries only an integer.
    """
    from .fight_ownership import owns_feature

    if not any(owns_feature(engine, actor, TALENT) for actor in engine.state.actors.values()):
        return
    for event in engine.events:
        if event.event_type == "MATCH_CREATED":
            event.payload["axes_push_bounds_policy"] = 1
            return


def bounded_push_route(engine: Any) -> bool:
    """Whether this fight bound the newer route geometry at creation."""
    return any(e.event_type == "MATCH_CREATED" and e.payload.get("axes_push_bounds_policy") == 1
               for e in engine.events)
BLOCK = "axes_falling_tree"
SPHERE = "tianxia.sphere.axes"
WITHIN = 10  # "one creature within 10 feet of the fallen target or broken object"
PRONE = ("condition:typed.prone", "condition:core.prone")


# ------------------------------------------------------------------------------------------------- ownership
@hook("compile_block")
def compile_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Seal this talent's printed save and payment alternatives into the owner's passive rows."""
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "numbers": dict(numbers),
             "costs": [list(part) for part in (spec.get("costs") or [])],
             "save": dict(spec.get("save") or {})}]


def _owned(engine: Any, actor: Any) -> dict[str, Any] | None:
    """This talent's own row for ``actor``, or None (no row, no behaviour)."""
    return next((row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, ())
                 if row.get("block") == BLOCK and row.get("kind") == "falling_tree"), None)


def _axes_source(engine: Any, source_id: str, actor: Any) -> bool:
    """Whether ``source_id`` is one of ``actor``'s own Axes-sphere actions ("with an Axes talent")."""
    if not str(source_id or "").startswith("action:"):
        return False
    action = engine.action_catalog.get(str(source_id))
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    if not typed or (typed.get("sphere") != SPHERE and not str(typed.get("source") or "").startswith("TAL_AXES")):
        return False
    return getattr(action, "owner_id", None) == actor.entity_id


# ------------------------------------------------------------------------------------------------- the fall
def _fell(engine: Any, event_type: str, kwargs: dict[str, Any]) -> tuple[Any, Any] | None:
    """(owner, what fell) when this owner's own Axes talent knocked a creature Prone, brought one to 0 HP, or destroyed an object.

    Each branch reads the printed condition, not a near miss:
      * "knock a creature Prone" needs a *new* knockdown. A refresh of a Prone the creature
        already carries is not a knock, and the owner knocking itself down is not "a creature".
      * "reduce a creature to 0 HP" needs the creature to have been standing and to be at 0 now:
        its Hit Points before the blow, not the damage rolled.  DAMAGE_COMMITTED's ``reduced_to``
        is the damage, so reading it fired on every hit; a packet entirely absorbed by Temporary Hit
        Points or prevented before it landed takes none, and a creature already down at 0 HP was not
        reduced to 0 again.  Both are read from the packet the engine already records.
      * "destroy a significant object" needs a destroyed object that took damage.
    """
    payload = kwargs.get("payload") or {}
    targets = tuple(kwargs.get("target_ids") or ())
    owner = engine.state.actors.get(kwargs.get("actor_id") or "")
    if owner is None or not owner.active or not _owned(engine, owner):
        return None
    if not _axes_source(engine, str(kwargs.get("source_definition_id") or ""), owner):
        return None
    fallen: Any = None
    if event_type == "CONDITION_APPLIED" and str(payload.get("condition_id") or "") in PRONE:
        target = engine.state.actors.get(targets[0]) if targets else None
        # a *new* knockdown only: not the owner itself, and not a creature that was already Prone
        # (the condition carrying this very event is excluded, since it is already recorded)
        if target is not None and target is not owner and target.active and not _already_prone(
                target, str(payload.get("instance_id") or "")):
            fallen = target
    elif event_type == "DAMAGE_COMMITTED":
        target = engine.state.actors.get(targets[0]) if targets else None
        if target is not None and _reduced_to_zero(target, payload):
            fallen = target
    elif event_type == "OBJECT_UPDATED":
        record = payload.get("object") or {}
        if record.get("destroyed") and int((payload.get("damage") or {}).get("taken") or 0) > 0:
            fallen = engine.state.objects.get(str(record.get("object_id") or "")) or \
                (engine.state.objects.get(targets[0]) if targets else None)
    if fallen is None:
        return None
    return (owner, fallen)


def _reduced_to_zero(creature: Any, payload: dict[str, Any]) -> bool:
    """Whether this blow is the one that took ``creature`` from above 0 Hit Points down to 0.

    "reduce a creature to 0 HP" is a change of state, so all three of these have to hold, and the engine's own
    DAMAGE_COMMITTED packet already records all three:
      * ``remaining_hp`` is 0 now -- it is at 0, not merely wounded;
      * ``hp_damage`` is positive -- the blow actually took Hit Points off it.  A packet that was entirely
        absorbed by Temporary Hit Points, or prevented before it landed, carries none and reduced nothing;
      * it was still standing when the blow landed.  The engine settles a creature's 0-HP state (Dying, Stable
        or defeated) *after* this event is recorded, so a life state here means this creature was already down at
        0 HP and is not being reduced to 0 for the first time.
    """
    if int(payload.get("remaining_hp", 1) or 0) > 0:
        return False
    if int(payload.get("hp_damage") or 0) <= 0:
        return False
    if not getattr(creature, "active", False) or getattr(creature, "life_state", None) is not None:
        return False
    return True


def _already_prone(creature: Any, instance_id: str) -> bool:
    """Whether ``creature`` carried Prone before the condition instance ``instance_id`` landed.

    "Knock a creature Prone" is a change of state, so a second Prone condition on a creature that
    is already down (a refresh, a second knock in the same hit) is not a new fall.
    """
    return any(condition.condition_id in PRONE
               for instance, condition in getattr(creature, "conditions", {}).items() if instance != instance_id)


def _name(fallen: Any) -> str:
    return str(getattr(fallen, "display_name", None) or getattr(fallen, "name", None) or "it")


def _away(engine: Any, other: Any, fallen: Any) -> int:
    """Feet from ``other`` to the fallen creature or the broken object."""
    if hasattr(fallen, "position") and hasattr(fallen, "entity_id"):
        return engine._distance_actor_to_actor(other, fallen)
    return engine._distance_actor_to_cell(other, fallen.position)


@hook("event", nested=True)
def falling_tree(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The printed fall: the owner is asked while the fallen creature or the broken object is still on the map."""
    found = _fell(engine, event_type, kwargs)
    if found is None:
        return
    owner, fallen = found
    row = _owned(engine, owner) or {}
    pool = _ask_pool(engine, owner, fallen, row)
    if pool is None:
        return
    target = _ask_creature(engine, owner, fallen)
    if target is None:
        return
    engine._spend_resource(owner, pool, 1, TALENT)
    _save(engine, owner, target, row, fallen)


def _near(engine: Any, owner: Any, fallen: Any) -> list[Any]:
    """Active creatures other than the owner and the fallen one, within 10 feet of the fallen one."""
    return sorted((other for other in engine.state.actors.values()
                   if other.active and other.entity_id != owner.entity_id
                   and getattr(other, "entity_id", None) != getattr(fallen, "entity_id", None)
                   and _away(engine, other, fallen) <= WITHIN),
                  key=lambda other: (_away(engine, other, fallen), other.entity_id))


def _ask_pool(engine: Any, owner: Any, fallen: Any, row: dict[str, Any]) -> str | None:
    """The printed payment alternatives ("1 CP, 1 Stamina, or expend Martial Focus"); declining spends nothing."""
    from ..factory_compiler import RESOURCE_IDS
    from ..resource_labels import resource_name

    alternatives = row.get("costs") or [[{"resource": "cp", "amount": 1}], [{"resource": "stamina", "amount": 1}],
                                       [{"resource": "martial_focus", "amount": 1}]]
    pools: list[str] = []
    for alternative in alternatives:
        for part in alternative:
            pool = RESOURCE_IDS.get(str(part.get("resource")) or "")
            if pool and pool not in pools:
                pools.append(pool)
    affordable = [pool for pool in pools if int(owner.resources.get(pool, 0) or 0) >= 1]
    if not affordable:
        note(engine, TALENT, owner,
             f"Law of the Falling Tree: {owner.display_name} has no Cultivation Points, Stamina or Martial Focus to spend.")
        return None
    names = [resource_name(pool) for pool in affordable]
    picked = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "AXES_FALLING_TREE_COST", owner.entity_id, getattr(fallen, "entity_id", "object")), owner,
                 CHOICE + "axes_falling_tree_cost", affordable,
                 labels={pool: f"Spend 1 {resource_name(pool)}" for pool in affordable},
                 preferred=[affordable[0]], maximum=1, allow_decline=True,
                 prompt=f"Law of the Falling Tree: {owner.display_name}'s {_blow(engine)} brought {_name(fallen)} down. "
                        f"Spend 1 {_or(names)} to shake the ground loose around it and force one creature beside it to make "
                        f"a Dexterity saving throw.", name="Law of the Falling Tree: what it costs", feature_id=TALENT,
                 prompt_context=_trigger_context(engine, owner))
    return picked[0] if picked else None


def _or(names: list[str]) -> str:
    """The printed alternatives, read plainly: "A, B or C"."""
    return " or ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " or " + names[-1]


def _ask_creature(engine: Any, owner: Any, fallen: Any) -> Any | None:
    near = _near(engine, owner, fallen)
    if not near:
        note(engine, TALENT, owner, f"Law of the Falling Tree: no creature stands within 10 feet of {_name(fallen)}.")
        return None
    picked = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "AXES_FALLING_TREE", owner.entity_id, getattr(fallen, "entity_id", "object")), owner,
                 CHOICE + "axes_falling_tree", [other.entity_id for other in near],
                 labels={other.entity_id: other.display_name for other in near},
                 preferred=[other.entity_id for other in near if other.team_id != owner.team_id][:1] or [near[0].entity_id],
                 maximum=1, allow_decline=True,
                 prompt=f"Law of the Falling Tree: {owner.display_name}'s {_blow(engine)} brought {_name(fallen)} down. "
                        f"Name one creature within 10 feet of {_name(fallen)} to make a Dexterity saving throw.",
                 name="Law of the Falling Tree", feature_id=TALENT,
                 prompt_context=_trigger_context(engine, owner))
    return engine.state.actors.get(picked[0]) if picked else None


def _blow(engine: Any) -> str:
    """The printed triggering action by name, so the prompt says what actually caused the fall."""
    from .rider_choices import trigger_name

    return trigger_name(engine)


def _trigger_context(engine: Any, owner: Any) -> dict[str, str]:
    """Display-only metadata naming the action this free trigger rode."""
    intent = getattr(engine, "_active_intent", None)
    if intent is None:
        return {}
    action = engine.action_catalog.get(getattr(intent, "source_definition_id", "") or "")
    return {"source_definition_id": getattr(action, "source_definition_id", "") or "",
            "action_name": getattr(action, "display_name", "") or "",
            "action_actor_id": owner.entity_id}


# ------------------------------------------------------------------------------------------------- the save
def _save(engine: Any, owner: Any, target: Any, row: dict[str, Any], fallen: Any) -> None:
    """The printed Dexterity save, through the executor's own save, defenses and reactions."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..typed_executor import Context, run_effects

    from .needle import save_dc

    spec = row.get("save") or {}
    # the printed DC is the owner's own Cultivation Save DC, read from its compiled abilities (as every typed save does)
    typed = {"source": TALENT, "sphere": SPHERE, "effects": [], "duration": {"kind": "instant"},
             "anchor": _anchor(fallen),
             "numbers": {**dict(row.get("numbers") or {}), "save_dc": save_dc(engine, owner)}}
    action = ActionDefinition(source_definition_id=f"passive:{TALENT}", display_name="Law of the Falling Tree",
                              owner_id=owner.entity_id, economy=EconomyKind.NONE, resolution_kind="TYPED",
                              target_kind="HOSTILE_ENTITY", parameters={"typed": typed})
    ctx = Context(engine, owner, action, getattr(engine, "_active_intent", None), typed, [target], target, {})
    run_effects(ctx, [{"type": "axes_falling_tree", "applies_to": "target", **spec}])


def _anchor(fallen: Any) -> dict[str, Any]:
    """Where the fall happened: the printed push is "10 feet away from the fall", not away from the wielder.

    Carried on the save's own typed row (a plain dictionary of strings and integers) so the outcome
    branches can push away from the fallen creature or the broken object whichever it was.
    """
    position = getattr(fallen, "position", None)
    if position is None:
        return {}
    return {"x": int(position.x), "y": int(position.y), "z": int(position.z),
            "name": str(getattr(fallen, "display_name", None) or getattr(fallen, "name", None) or "the fall")}


@effect("axes_falling_tree")
def falling_tree(ctx: Any, row: dict[str, Any]) -> None:
    """The printed line: that creature makes a Dexterity saving throw (DC: the owner's Cultivation Save DC)."""
    from ..typed_executor import block_save

    target = ctx.target
    if target is None or not target.active:
        return
    block_save(ctx, {"type": "save", "applies_to": "target", "ability": str(row.get("ability") or "dex"),
                     "dc": row.get("dc") or "technique_save_dc",
                     "evidence": row.get("evidence") or "Law of the Falling Tree: that creature makes a Dexterity saving throw.",
                     "on_fail": list(row.get("on_fail") or []), "on_success": list(row.get("on_success") or [])})


@effect("axes_falling_tree_fall")
def fall(ctx: Any, row: dict[str, Any]) -> None:
    """"it falls Prone or is pushed 10 feet away from the fall": the wielder chooses which of the two happens."""
    from ..typed_executor import run_effects
    from .rider_choices import pick

    target = ctx.target
    if target is None or not target.active:
        return
    options = [option for option in row.get("options") or [] if option.get("effects")]
    if not options:
        return
    labels = {str(option["key"]): str(option.get("label") or option["key"]) for option in options}
    fallen = str((ctx.typed.get("anchor") or {}).get("name") or "the fall")
    # the wielder chooses between the two printed outcomes; the subject is the creature that failed the
    # save (the one actually affected), not the wielder who is choosing
    chosen = pick(ctx.engine, ctx.actor, "axes_falling_tree_fall", "Law of the Falling Tree", list(labels), subject=target,
                  labels=labels, preferred=[str(options[0]["key"])], optional=False,
                  trigger=f"{ctx.actor.display_name}'s {_blow(ctx.engine)} brought {fallen} down")
    picked = next((option for option in options if str(option["key"]) == (chosen or [str(options[0]["key"])])[0]), options[0])
    run_effects(ctx, picked["effects"])
    ctx.rider(f"Law of the Falling Tree: {target.display_name} {labels[str(picked['key'])]}.")


@effect("axes_falling_tree_push")
def push(ctx: Any, row: dict[str, Any]) -> None:
    """"is pushed 10 feet away from the fall": pushed away from where it fell, not away from the wielder.

    The engine's ordinary ``forced_movement`` row runs away from its caster, which is the wrong anchor
    for this line: the fall is a *different* creature or the broken object. The route is built from the
    anchor the save recorded and then handed to the shared forced-movement path, so the pushed creature
    still gets its own reactions, the same legal-square checks and the same interruption rules.
    """
    from ..gate2_runtime_models import Position
    from ..movement_paths import resolve

    target = ctx.target
    anchor = ctx.typed.get("anchor") or {}
    if target is None or not target.active or not anchor:
        return
    feet = int(row.get("distance_ft") or 10)
    centre = Position(x=int(anchor.get("x") or 0), y=int(anchor.get("y") or 0), z=int(anchor.get("z") or 0))
    current = target.position
    if current == centre:
        ctx.rider(f"Law of the Falling Tree: {target.display_name} is standing on the fall, so it cannot be pushed "
                  f"away from it.")
        return
    cells = max(1, feet // ctx.engine.grid.square_size_ft)
    path = [current]
    for _ in range(cells):
        # each square steps further from the fall, the way the engine's own push re-aims a route
        step_x = (current.x > centre.x) - (current.x < centre.x)
        step_y = (current.y > centre.y) - (current.y < centre.y)
        if not (step_x or step_y):
            break
        next_cell = map_position(ctx.engine, current.x + step_x, current.y + step_y, z=current.z)
        if next_cell is None:
            x, y = current.x + step_x, current.y + step_y
            if x < 0 or y < 0 or bounded_push_route(ctx.engine):
                break
            # Legacy positive-edge routes were clipped by the movement resolver
            # after it offered reactions using the originally requested length.
            next_cell = Position(x=x, y=y, z=current.z)
        current = next_cell
        path.append(current)
    if len(path) == 1:
        return
    # Strict movement failures are the shared CheckpointError and must roll the owning transaction back
    # rather than commit a half-done push with the owner's point already paid (combat/ext/__init__.py,
    # "Strict movement failures ... escape enclosing event or typed-reaction guards").  Ordinary collision
    # or interruption is not an error: the movement resolver reports those itself and returns the distance
    # it actually managed to move.
    resolve(ctx.engine, target, path, ctx.source, kind="forced", feet=feet, intent=ctx.intent,
            source_actor_id=ctx.actor.entity_id)
    if target.active and target.position != path[0]:
        ctx.rider(f"Law of the Falling Tree: {target.display_name} is pushed "
                  f"{int(ctx.engine.grid.distance_ft(path[0], target.position))} feet away from "
                  f"{str(anchor.get('name') or 'the fall')}.")


@effect("axes_falling_tree_withdraw")
def withdraw(ctx: Any, row: dict[str, Any]) -> None:
    """"it moves 5 feet to a space of its choice that is not closer to you, if it can": the creature picks its own square.

    The printed line is the creature's *own* move, so it runs through the shared voluntary-movement path
    (``granted_movement.resolve_path`` with ``use_movement``): the 5 feet come out of its own movement
    allowance and it leaves its space normally, which can provoke Opportunity Attacks.  That is also the
    rule authority for the cost: the talent does not say the step is free, and a move a creature makes
    spends the movement it has.  "if it can" is the engine's own remaining-movement budget, so a creature
    that has already used its movement this turn is left standing rather than asked to move something it
    cannot pay for.  The old code offered squares from a five-foot *grant* and then executed them against
    the creature's real budget, so a spent recipient was asked a question whose only legal answer raised
    ``GATE2_MOVEMENT_BUDGET_EXCEEDED``; candidates are now filtered by the same budget the executor
    charges, before anybody is asked.
    """
    from .. import granted_movement

    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    intent = getattr(engine, "_active_intent", None)
    if target is None or not target.active or intent is None:
        return
    feet = int(row.get("distance_ft") or 5)
    start = target.position
    options, reachable = {}, {}  # squares the printed line allows at all, before the creature's own budget
    candidates = granted_movement.candidates(engine, target, feet, intent, TALENT)
    for key, candidate in candidates.items():
        destination = candidate.destination
        if engine.grid.distance_ft(start, destination) > feet or \
                engine.grid.distance_ft(destination, owner.position) < engine.grid.distance_ft(start, owner.position):
            continue
        reachable[key] = candidate
        if _beyond_budget(engine, target, candidate):
            continue
        options[key.replace("step:", "cell:", 1)] = candidate
    if not options:
        if not reachable and candidates:
            # Space is there and the creature could step to it; every one of those spaces is nearer to the
            # wielder than where it already stands, which is what the printed line rules out.
            ctx.rider(f"Law of the Falling Tree: {target.display_name} has no space of its choice within {feet} feet "
                      f"that is not closer to {owner.display_name}, so it stays where it is.")
            return
        if not candidates:
            # Nothing to consider at all: the creature has no movement of its own to spend (a speed of zero, a
            # hold, a creature held fast) or no square within reach to spend it on.  Say neither of the other
            # two things: this is not "it has not the movement left", and it is not a claim about squares.
            ctx.rider(f"Law of the Falling Tree: {target.display_name} cannot step clear of the fall, so it stays "
                      f"where it is.")
            return  # "if it can": it cannot, so it does not move
        budget = _remaining(engine, target, ())
        ctx.rider(f"Law of the Falling Tree: {target.display_name} has not the movement left to step clear of the fall "
                  f"({budget} feet of its movement remain"
                  f"{'' if budget == 1 else 's'}), so it stays where it is.")
        return  # "if it can": nothing it can pay for, so it does not move
    ids = sorted(options, key=lambda key: (options[key].movement_cost_ft, key))[:16]
    picked = ask(engine, intent, checkpoint_id(engine, "AXES_FALLING_TREE_WITHDRAW", owner.entity_id, target.entity_id), target,
                 CHOICE + "axes_falling_tree_withdraw", ids,
                 labels={key: f"Move to {options[key].destination.x},{options[key].destination.y}" for key in ids},
                 preferred=[ids[0]], maximum=1, target_id=target.entity_id, name="Law of the Falling Tree: where it steps",
                 feature_id=TALENT,
                 prompt=f"Law of the Falling Tree: {owner.display_name}'s {_blow(engine)} brought "
                        f"{str((ctx.typed.get('anchor') or {}).get('name') or 'it')} down. {target.display_name} may move up to "
                        f"{feet} feet of its own movement to a space of its choice that is not closer to "
                        f"{owner.display_name}.",
                 prompt_context=_trigger_context(engine, owner))
    if not picked or picked[0] not in options:
        return  # a declined withdrawal leaves the creature where it stands
    chosen = options[picked[0]]
    spent = granted_movement.resolve_path(engine, target, chosen.canonical_path, TALENT,
                                          feet=chosen.movement_cost_ft, intent=intent, use_movement=True)
    if spent:
        ctx.rider(f"Law of the Falling Tree: {target.display_name} steps {spent} feet clear of the fall, away from "
                  f"{owner.display_name}.")


def _beyond_budget(engine: Any, target: Any, candidate: Any) -> bool:
    """Whether ``candidate`` costs more movement than ``target`` has left in the mode that route uses.

    The executor charges ``flight.remaining`` for the route's own movement mode, so the menu has to ask the
    same question the charge will ask; otherwise a square is offered that the creature cannot pay for.
    """
    from .. import flight

    return int(candidate.movement_cost_ft or 0) > _remaining(engine, target, candidate.canonical_path)


def _remaining(engine: Any, target: Any, path: Any) -> int:
    """The movement ``target`` has left for ``path``'s own mode (walking or flying), as the executor counts it."""
    from .. import flight
    from ..granted_movement import movement_mode

    try:
        mode = movement_mode(engine, target, tuple(path))
    except ValueError:
        return 0
    return int(flight.remaining(engine, target, mode))

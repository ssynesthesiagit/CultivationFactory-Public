"""Ten-Thousand Parasite Vessel riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Ten-Thousand Parasite Vessel (the Brood record, the five features and their Normalized
Procedures). Brood (``resource:named.brood``, maximum PB, + 3 while Ten-Thousand Worm Demon Body lasts) is gained by
combat/ext/subpath_pools.py. Owned rows: ``{"type": "path_passive", "kind": "parasite", "role": "brood" | "gnaw" | "substitution" |
"sovereign"}``; Infesting Strike is a path_riders ``paid_hit`` row running ``parasite_strike``; the transformation is the named
state "ten_thousand_worm_demon_body".

Internal Brood      at the start of your turn (asked, 1 Brood): 1d8 + CON Hit Points (2d8 at CL11, 3d8 at CL17); not at 0 Hit Points
                    except once per Worm Demon Body (then: stand, lose every Brood, the transformation ends).
Infesting Strike    + 1d8 Poison or Necrotic, then a Constitution save: Infested until the end of your next turn
                    (``condition:typed.infested``, its data the owner, the save DC and the damage type dealt). One Infested
                    creature at a time (PB with Parasite Sovereignty); a new one past the limit asks which to end, or declines.
Gnawing Infestation the first time on its own turn an Infested creature spends Cultivation Points, takes the Dash action, has
                    moved 15 feet willingly, regains Hit Points or gains Temporary Hit Points: 3d8 of the recorded type, no
                    healing or Temporary Hit Points until the start of its next turn, and the Infestation ends; otherwise it
                    repeats the Constitution save at the end of its turn, ending on a success.
Brood Substitution  its hit half is the generic Reaction (4d8 + CON off the hit); failing a Dexterity or Constitution save against
                    a damaging effect asks here (Reaction, 2 Brood, once per round) and takes 4d8 + CON off that effect's next
                    damage packet (hook damage_reduction). Either way: an asked 10-foot move without provoking and a
                    Swarm-Shell (a square of difficult terrain) in the space you left, until the start of your next turn.
Parasite Sovereignty  this Subpath's Poison and Necrotic damage ignores Resistance (hook resistance_ignored); PB Infested
                    creatures; once per round after Gnawing damage one asked benefit (PB Hit Points, 1 Brood, a 10-foot move,
                    or 2 x PB Temporary Hit Points).
Ten-Thousand Worm Demon Body  its state: Resistance to all damage but Fire, Radiant, Psychic and Void; no Grapple or Restrained
                    from a weapon, unarmed or ordinary action; + 1 Brood at the start of each of your turns; Brood Tide (an
                    Action while it lasts, 3 Brood, 30-foot cone) — see ``brood_tide``; at 0 Hit Points while it lasts (once) you
                    go down Dying rather than leaving the map, so Internal Brood can raise you at the start of your turn.
Every hook returns early for a creature without these rows, conditions or state.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.ten_thousand_parasite_vessel.feature."
BROOD = "resource:named.brood"
INFESTED = "condition:typed.infested"
WORM = "ten_thousand_worm_demon_body"
CP = "resource:core.qi"


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "parasite"}


def _row(engine: Any, actor: Any, role: str) -> dict[str, Any] | None:
    return next((row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
                 if row.get("block") == "path_rider" and row.get("kind") == "parasite" and row.get("role") == role), None)


def _worm(engine: Any, actor: Any) -> Any:
    from .states import active

    return active(engine, actor, WORM) if actor is not None else None


@hook("pass_through")
def worm_passage(engine: Any, mover: Any, occupant: Any) -> str | None:
    return "difficult" if _worm(engine, mover) is not None else None


@hook("save")
def disease_resistance(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if 'brood' in _roles(ctx.engine, subject) and 'category:disease' in set(named or ()):
        return {'bonus': 0, 'modes': ['ADVANTAGE']}
    return None


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


def _numbers(engine: Any, owner: Any) -> dict[str, Any]:
    row = next((r for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(owner.entity_id, []) if r.get("kind") == "parasite"), {}) or {}
    return {"pb": int(owner.proficiency_bonus or 2), "cl": int(row.get("cl") or 1), "save_dc": int(row.get("save_dc") or 10)}


_NAMES = {"internal_brood": "Internal Brood", "gnawing_infestation": "Gnawing Infestation", "parasite_sovereignty": "Parasite Sovereignty",
          "brood_substitution": "Brood Substitution"}


def _ctx(engine: Any, owner: Any, targets: list[Any], source: str) -> Any:
    """A Context for ``owner`` outside its own action, attributed to the feature ``source`` (not a borrowed catalog action)."""
    from .. import typed_executor as te
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    action = ActionDefinition(source_definition_id=PREFIX + source, display_name=_NAMES.get(source, source), owner_id=owner.entity_id,
                              economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY")
    typed = {"source": PREFIX + source, "effects": [], "numbers": _numbers(engine, owner), "duration": {"kind": "instant"}, "riders": []}
    return te.Context(engine, owner, action, _intent(engine), typed, list(targets), targets[0] if len(targets) == 1 else None, {})


def _con(engine: Any, actor: Any) -> int:
    return next((int((((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("con_mod") or 0)
                 for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                 and (((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("con_mod") is not None), 0)


# ------------------------------------------------------------------------------------------------------ Internal Brood
@hook("turn_start_choice")
def internal_brood(engine: Any, actor: Any) -> None:
    from .subpath_pools import gain

    worm = _worm(engine, actor)
    if worm is not None and actor.active:
        gain(engine, actor, BROOD, PREFIX + WORM, normal=False)  # "Gain 1 Brood at the start of each turn"
    if "brood" not in _roles(engine, actor) or not actor.active or int(actor.resources.get(BROOD, 0) or 0) < 1:
        return
    down = actor.current_hp <= 0
    if down and (worm is None or (worm.data or {}).get("revived")):
        return  # "cannot heal you at 0 Hit Points" (the Worm Demon Body lets it, once)
    if not down and actor.current_hp >= actor.maximum_hp:
        return
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    cl = _numbers(engine, actor)["cl"]
    dice = 3 if cl >= 17 else 2 if cl >= 11 else 1
    intent = _intent(engine)
    picked = ask(engine, intent, checkpoint_id(engine, "internal_brood", actor.entity_id), actor, "choice:needle.internal_brood", ["heal"],
                 labels={"heal": f"Spend 1 Brood: regain {dice}d8 + Constitution modifier Hit Points"
                                 + (" (you rise, lose every Brood, and the Worm Demon Body ends)" if down else "")},
                 allow_decline=True, target_id=actor.entity_id, name="Internal Brood", prompt="Internal Brood: spend a Brood to heal?")
    if not picked:
        return
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, actor, PREFIX + "internal_brood", independent=True):
        engine._spend_resource(actor, BROOD, 1, PREFIX + "internal_brood")
        ctx = _ctx(engine, actor, [actor], "internal_brood")
        te.run_effects(ctx, [{"type": "healing", "applies_to": "self", "dice": {"count": dice, "sides": 8}, "flat": _con(engine, actor), "evidence": "Internal Brood"}])
        if down and worm is not None:
            worm.data = {**(worm.data or {}), "revived": True}
            for iid, held in list(actor.conditions.items()):
                if held.condition_id == "condition:typed.prone":  # "stand without movement"
                    del actor.conditions[iid]
                    engine._append_event("CONDITION_REMOVED", PREFIX + "internal_brood", actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                         payload={"condition_id": held.condition_id, "instance_id": iid, "reason": "STOOD"})
            left = int(actor.resources.get(BROOD, 0) or 0)
            if left:
                engine._spend_resource(actor, BROOD, left, PREFIX + WORM)
            _end_worm(engine, actor)


@hook("self_recovery")
def brood_self_recovery(engine: Any, actor: Any) -> bool | None:
    """Internal Brood raises a downed host that still has a Brood and can use it.

    Pure query for gate2_engine's victory check: that creature's own start-of-turn
    choice restores Hit Points, so its side is not defeated while it holds it.
    """
    worm = _worm(engine, actor)
    if (not actor.active or actor.current_hp > 0 or worm is None
            or (worm.data or {}).get("revived")
            or int(actor.resources.get(BROOD, 0) or 0) < 1 or "brood" not in _roles(engine, actor)):
        return None
    return True


def _end_worm(engine: Any, actor: Any) -> None:
    from .states import PREFIX as STATE

    for iid, held in list(actor.conditions.items()):
        if held.condition_id == STATE + WORM:
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", PREFIX + WORM, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": held.condition_id, "instance_id": iid, "reason": "ENDED"})


@hook("zero_hp")
def worm_goes_down_dying(engine: Any, target: Any, source_id: str, intent: Any) -> str | None:
    """At 0 Hit Points during the Worm Demon Body (not yet used, with Brood): Dying, so Internal Brood can raise it on its turn.
    combat/ext/life_state.py answers first for creatures its own rules keep Dying; only one answer is allowed."""
    worm = _worm(engine, target)
    if worm is None or (worm.data or {}).get("revived") or int(target.resources.get(BROOD, 0) or 0) < 1 or "brood" not in _roles(engine, target):
        return None
    from .life_state import UNCONSCIOUS, wants_dying

    if wants_dying(engine, target):
        return None
    engine._apply_condition(target, UNCONSCIOUS, source_id, target.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Unconscious at 0 HP", "rule": {"no_actions": True, "no_reactions": True, "speed_zero": True,
                                  "attacked_with": "ADVANTAGE", "save_mode": {"STR": "AUTO_FAIL", "DEX": "AUTO_FAIL"}}})
    return "DYING"


# ---------------------------------------------------------------------------------------------------- Infesting Strike
def _pierce(engine: Any, owner: Any) -> None:
    engine._parasite_pierce = owner.entity_id if "sovereign" in _roles(engine, owner) else None


@hook("resistance_ignored")
def sovereign_pierce(engine: Any, kind: str, typed: Any, source_actor_id: Any, target: Any = None) -> bool | None:
    """"Poison and Necrotic damage from this Subpath ignores Resistance" (Parasite Sovereignty)."""
    if str(kind).upper() not in ("POISON", "NECROTIC") or not source_actor_id:
        return None
    if getattr(engine, "_parasite_pierce", None) == source_actor_id:
        return True
    source = engine.state.actors.get(source_actor_id)
    if str((typed or {}).get("source") or "").startswith(PREFIX) and source is not None and "sovereign" in _roles(engine, source):
        return True
    return None


@effect("parasite_strike")
def parasite_strike(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    start = len(engine.events)
    _pierce(engine, owner)
    try:
        te.run_effects(ctx, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 1, "sides": 8}, "damage_types": ["poison", "necrotic"],
                              "evidence": "Infesting Strike: + 1d8"}])
    finally:
        engine._parasite_pierce = None
    kind = next((str((e.payload or {}).get("damage_type") or "POISON").upper() for e in reversed(engine.events[start:])
                 if e.event_type == "DAMAGE_COMMITTED" and target.entity_id in (e.target_ids or ())), "POISON")
    if target.active:
        te.run_effects(ctx, [{"type": "save", "ability": "con", "evidence": "Infesting Strike: Constitution saving throw",
                              "on_fail": [{"type": "infest", "kind": kind}], "on_success": []}])


def _infested_by(engine: Any, owner: Any) -> list[tuple[Any, str]]:
    return [(c, iid) for c in engine.state.actors.values() for iid, held in c.conditions.items()
            if held.condition_id == INFESTED and (held.data or {}).get("owner") == owner.entity_id]


def infest(ctx: Any, target: Any, kind: str) -> bool:
    """Create (or refresh) owner's Infestation on ``target``; past the owner's limit, ask which to end or decline."""
    from .needle import ask, checkpoint_id

    engine, owner = ctx.engine, ctx.actor
    held = _infested_by(engine, owner)
    mine = [iid for creature, iid in held if creature.entity_id == target.entity_id]
    limit = int(owner.proficiency_bonus or 2) if "sovereign" in _roles(engine, owner) else 1
    others = [(creature, iid) for creature, iid in held if creature.entity_id != target.entity_id]
    if not mine and len(others) >= limit:
        options = {creature.entity_id: creature for creature, _ in others}
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "infest_limit", target.entity_id), owner, "choice:needle.infest_limit", list(options),
                     labels={k: f"End the Infestation on {c.display_name}" for k, c in options.items()}, allow_decline=True, target_id=target.entity_id,
                     name="Infested", prompt=f"You already maintain {len(others)} Infestation(s). End one to infest {target.display_name}, or decline the new one?")
        if not picked or picked[0] not in options:
            return False
        _end_infestation(engine, options[picked[0]], "REPLACED", owner)
    for iid in mine:
        _end_infestation(engine, target, "REFRESHED", owner)
    turn = int(owner.turns_started) + 1  # "until the end of your next turn"
    engine._apply_condition(target, INFESTED, PREFIX + "internal_brood", owner.entity_id, expires_on=f"END_OF_SOURCE_TURN_AT:{turn}",
                            data={"label": f"Infested ({kind.title()})", "owner": owner.entity_id, "dc": int(ctx.numbers.get("save_dc") or 10),
                                  "kind": kind})
    return True


@effect("infest")
def infest_effect(ctx: Any, row: dict[str, Any]) -> None:
    if ctx.target is not None and ctx.target.active:
        infest(ctx, ctx.target, str(row.get("kind") or "POISON").upper())


def _end_infestation(engine: Any, creature: Any, reason: str, owner: Any) -> None:
    for iid, held in list(creature.conditions.items()):
        if held.condition_id == INFESTED and (held.data or {}).get("owner") == owner.entity_id:
            del creature.conditions[iid]
            engine._append_event("CONDITION_REMOVED", PREFIX + "internal_brood", actor_id=owner.entity_id, target_ids=(creature.entity_id,),
                                 payload={"condition_id": INFESTED, "instance_id": iid, "reason": reason})


# ------------------------------------------------------------------------------------------------- Gnawing Infestation
def _gnawers(engine: Any, creature: Any) -> list[tuple[Any, Any]]:
    """(owner, condition) for each Infestation on ``creature`` whose owner has Gnawing Infestation."""
    out = []
    for held in list(creature.conditions.values()):
        if held.condition_id != INFESTED:
            continue
        owner = engine.state.actors.get(str((held.data or {}).get("owner") or ""))
        if owner is not None and "gnaw" in _roles(engine, owner):
            out.append((owner, held))
    return out


def gnaw(engine: Any, creature: Any, owner: Any, held: Any, why: str) -> None:
    """3d8 of the recorded type, no healing until the start of its next turn, the Infestation ends; Parasite Sovereignty's benefit."""
    from .. import typed_executor as te

    kind = str((held.data or {}).get("kind") or "POISON").lower()
    _end_infestation(engine, creature, "GNAWED", owner)
    note(engine, PREFIX + "gnawing_infestation", owner, f"Gnawing Infestation: {creature.display_name} {why}; the brood inside it feeds.", (creature.entity_id,))
    ctx = _ctx(engine, owner, [creature], "gnawing_infestation")
    ctx.target = creature
    _pierce(engine, owner)
    try:
        te.run_effects(ctx, [{"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "damage_types": [kind], "evidence": "Gnawing Infestation: 3d8"}])
    finally:
        engine._parasite_pierce = None
    if creature.active:
        te.run_effects(ctx, [{"type": "healing_reduction", "applies_to": "target", "evidence": "It cannot regain Hit Points until the start of its next turn."},
                             {"type": "deny_temp_hp", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN",
                              "evidence": "It cannot gain Temporary Hit Points until the start of its next turn."}])
    _sovereign_benefit(engine, owner)


def _sovereign_benefit(engine: Any, owner: Any) -> None:
    if "sovereign" not in _roles(engine, owner) or not owner.active or owner.turn_flags.get("_round_parasite_sovereign") == int(engine.state.round_number):
        return
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step
    from .subpath_pools import gain

    owner.turn_flags["_round_parasite_sovereign"] = int(engine.state.round_number)
    pb = int(owner.proficiency_bonus or 2)
    labels = {"heal": f"Regain {pb} Hit Points", "brood": "Gain 1 Brood", "move": "Move 10 feet without provoking", "temp": f"Gain {2 * pb} Temporary Hit Points"}
    intent = _intent(engine)
    picked = ask(engine, intent, checkpoint_id(engine, "parasite_sovereignty", owner.entity_id), owner, "choice:needle.parasite_sovereignty", list(labels),
                 labels=labels, target_id=owner.entity_id, name="Parasite Sovereignty", prompt="Parasite Sovereignty: the brood fed. Choose one.")
    choice = picked[0] if picked else "heal"
    ctx = _ctx(engine, owner, [owner], "parasite_sovereignty")
    if choice == "heal":
        te.run_effects(ctx, [{"type": "healing", "applies_to": "self", "flat": pb, "evidence": "Parasite Sovereignty"}])
    elif choice == "brood":
        gain(engine, owner, BROOD, PREFIX + "parasite_sovereignty", normal=False)
    elif choice == "temp":
        te.run_effects(ctx, [{"type": "temp_hp", "applies_to": "self", "flat": 2 * pb, "evidence": "Parasite Sovereignty"}])
    else:
        paths = routes(engine, owner, 10)
        pick = ask(engine, intent, checkpoint_id(engine, "parasite_move", owner.entity_id), owner, "choice:needle.parasite_move", sorted(paths),
                   allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=owner.entity_id,
                   prompt="Parasite Sovereignty: move up to 10 feet without provoking.") if paths else None
        if pick and pick[0] in paths:
            step(engine, owner, paths[pick[0]], PREFIX + "parasite_sovereignty")


def _trigger(engine: Any, creature: Any, why: str) -> None:
    if creature is None or not creature.active or engine.state.current_actor_id != creature.entity_id:
        return  # "during its turn"
    for owner, held in _gnawers(engine, creature):
        gnaw(engine, creature, owner, held, why)


@hook("event")
def gnawing_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if event_type == "RESOURCE_SPENT" and payload.get("resource_id") == CP and int(payload.get("amount") or 0) > 0:
        _trigger(engine, engine.state.actors.get(kwargs.get("actor_id") or ""), "spends Cultivation Points")
    elif event_type == "HEALING_APPLIED" and int(payload.get("after") or 0) > int(payload.get("before") or 0):
        _trigger(engine, engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), "")), "regains Hit Points")
    elif event_type == "TEMP_HP_GRANTED" and int(payload.get("after") or 0) > int(payload.get("before") or 0):
        _trigger(engine, engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), "")), "gains Temporary Hit Points")
    elif event_type == "MOVEMENT_COMMITTED" and not payload.get("forced") and not payload.get("teleport") and not payload.get("dragged_by"):
        creature = engine.state.actors.get(kwargs.get("actor_id") or "")
        if creature is None or not any(c.condition_id == INFESTED for c in creature.conditions.values()) or engine.state.current_actor_id != creature.entity_id:
            return
        stamp = _stamp(engine)
        record = creature.turn_flags.get("_round_infested_moved") or {}
        total = (int(record.get("ft") or 0) if record.get("stamp") == stamp else 0) + max(0, len(payload.get("path") or []) - 1) * engine.grid.square_size_ft
        creature.turn_flags["_round_infested_moved"] = {"stamp": stamp, "ft": total}
        if total >= 15:
            _trigger(engine, creature, "moves 15 feet")


@hook("action_completed")
def gnawing_dash(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    if str(source_definition_id) == "system:combat.dash":
        _trigger(engine, actor, "takes the Dash action")


@hook("turn_end")
def gnawing_repeat_save(engine: Any, actor: Any) -> None:
    """"If not triggered, it repeats the Constitution save at the end of its turn, ending Infestation on a success."."""
    from .. import typed_executor as te

    for owner, held in _gnawers(engine, actor):
        ctx = _ctx(engine, owner, [actor], "gnawing_infestation")
        ctx.numbers["save_dc"] = int((held.data or {}).get("dc") or ctx.numbers.get("save_dc") or 10)
        te.run_effects(ctx, [{"type": "save", "ability": "con", "evidence": "Gnawing Infestation: repeated Constitution saving throw",
                              "on_fail": [], "on_success": [{"type": "parasite_cleared", "owner": owner.entity_id}]}])


@effect("parasite_cleared")
def parasite_cleared(ctx: Any, row: dict[str, Any]) -> None:
    owner = ctx.engine.state.actors.get(str(row.get("owner") or ""))
    if ctx.target is not None and owner is not None:
        _end_infestation(ctx.engine, ctx.target, "SAVED", owner)


# -------------------------------------------------------------------------------------------------- Brood Substitution
def _damaging_save(ctx: Any, ability: str) -> bool:
    def walk(rows: Any) -> Any:
        for row in rows or []:
            if isinstance(row, dict):
                yield row
                for key in ("on_hit", "on_fail", "on_success", "effects"):
                    yield from walk(row.get(key))

    return any(row.get("type") == "save" and str(row.get("ability") or "").upper()[:3] == ability[:3]
               and any(isinstance(f, dict) and f.get("type") in ("damage", "extra_damage") for f in walk(row.get("on_fail")))
               for row in walk(ctx.typed.get("effects")))


@hook("after_save_resolved")
def substitution_on_a_failed_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    engine = ctx.engine
    if not failed or subject is None or subject.team_id == ctx.actor.team_id or "substitution" not in _roles(engine, subject):
        return
    if str(ability).upper()[:3] not in ("DEX", "CON") or not subject.reaction_available or int(subject.resources.get(BROOD, 0) or 0) < 2:
        return
    if not _damaging_save(ctx, str(ability).upper()) or _substituted_this_round(engine, subject):
        return
    from ..gate2_runtime_models import DiceSpec
    from .needle import ask, checkpoint_id

    intent = ctx.intent or _intent(engine)
    picked = ask(engine, intent, checkpoint_id(engine, "brood_substitution", subject.entity_id), subject, "choice:needle.brood_substitution", ["use"],
                 labels={"use": "Reaction, 2 Brood: take 4d8 + Constitution modifier off its damage, move 10 feet, leave a Swarm-Shell"},
                 allow_decline=True, default="decline", target_id=subject.entity_id, name="Brood Substitution",
                 prompt=f"Brood Substitution: you failed the save against {ctx.action.display_name}. Swap in the swarm?")
    if not picked:
        return
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, subject, PREFIX + "brood_substitution", independent=True):
        subject.reaction_available = False
        engine._spend_resource(subject, BROOD, 2, PREFIX + "brood_substitution")
        subject.turn_flags["_round_brood_substitution"] = int(engine.state.round_number)
        roll = engine.roller.roll(DiceSpec(count=4, sides=8, modifier=_con(engine, subject)), actor_id=subject.entity_id, reason=f"REDUCTION:{PREFIX}brood_substitution")
        engine._record_roll(roll)
        subject.turn_flags["_brood_shield"] = int(roll.total)
        engine._append_event("REACTION_RESOLVED", PREFIX + "brood_substitution", actor_id=subject.entity_id, target_ids=(ctx.actor.entity_id,),
                             payload={"checkpoint": "SAVE_FAILED", "reduction": int(roll.total)})
        subject.turn_flags['_round_brood_swap_pending'] = {'intent_id': getattr(ctx.intent, 'intent_id', None) or getattr(ctx.engine, '_active_intent_id', None)}


def _substituted_this_round(engine: Any, actor: Any) -> bool:
    if actor.turn_flags.get("_round_brood_substitution") == int(engine.state.round_number):
        return True
    for event in reversed(engine.events):
        if event.event_type == "ROUND_STARTED":
            break
        if event.event_type == "REACTION_RESOLVED" and event.actor_id == actor.entity_id and str(event.source_definition_id).endswith("brood_substitution"):
            return True
    return False


@hook("row_allowed")
def substitution_once(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    """Once per round across both halves (the save half is asked here, the hit half is the generic Reaction)."""
    if str(row.get("feature_id") or "").endswith("brood_substitution") and actor.turn_flags.get("_round_brood_substitution") == int(engine.state.round_number):
        return False
    return None


@hook("damage_reduction")
def brood_shield(engine: Any, target: Any, damage_type: str, typed: Any, source_actor_id: Any, applied: bool = False) -> int | None:
    amount = int(target.turn_flags.get("_brood_shield") or 0)
    if not amount:
        return None
    if applied:
        target.turn_flags.pop("_brood_shield", None)  # "reduce the triggering damage packet" (one packet)
    return amount


@effect("brood_swap")
def brood_swap(ctx: Any, row: dict[str, Any]) -> None:
    """The hit half's move and Swarm-Shell (the generic Reaction's effect row)."""
    ctx.actor.turn_flags["_round_brood_substitution"] = int(ctx.engine.state.round_number)
    ctx.actor.turn_flags['_round_brood_swap_pending'] = {'intent_id': getattr(ctx.intent, 'intent_id', None) or getattr(ctx.engine, '_active_intent_id', None)}


@hook('event', nested=True)
def substitution_after_damage(engine: Any, event_type: str, kwargs: Any) -> None:
    if event_type != 'DAMAGE_COMMITTED':
        return
    event = engine.events[-1] if engine.events else None
    event_intent = getattr(event, 'trigger_or_intent_id', None)
    for aid in kwargs.get('target_ids') or ():
        actor = engine.state.actors.get(aid)
        pending = actor.turn_flags.get('_round_brood_swap_pending') if actor is not None else None
        if pending and pending.get('intent_id') == event_intent:
            actor.turn_flags.pop('_round_brood_swap_pending', None)
            # DAMAGE_COMMITTED runs before Gate 2 settles defeat. A lethal packet
            # therefore still leaves the actor marked active at this seam.
            if actor.active and actor.current_hp > 0:
                _swap(engine, _intent(engine), actor)


@hook('action_completed')
def substitution_resolution_cleanup(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    """A save-triggered swap belongs to its enclosing accepted action only."""
    intent_id = getattr(_intent(engine), 'intent_id', None) or getattr(engine, '_active_intent_id', None)
    for creature in engine.state.actors.values():
        pending = creature.turn_flags.get('_round_brood_swap_pending')
        if pending and pending.get('intent_id') == intent_id:
            creature.turn_flags.pop('_round_brood_swap_pending', None)


def _swap(engine: Any, intent: Any, actor: Any) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    start = actor.position
    paths = routes(engine, actor, 10)
    if paths:
        picked = ask(engine, intent or _intent(engine), checkpoint_id(engine, "brood_swap", actor.entity_id), actor, "choice:needle.brood_substitution_move",
                     sorted(paths), allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths},
                     target_id=actor.entity_id, name="Brood Substitution", prompt="Brood Substitution: move up to 10 feet without provoking?")
        if picked and picked[0] in paths:
            step(engine, actor, paths[picked[0]], PREFIX + "brood_substitution")
    if actor.position == start:
        return  # the shell appears only where it is legal: your space is still yours
    ctx = _ctx(engine, actor, [actor], "brood_substitution")
    ctx.target = actor
    first = set(engine.state.zones)
    te.run_effects(ctx, [{"type": "terrain_patch", "difficult": "all", "radius_ft": 0, "center": {"x": start.x, "y": start.y}, "name": "Swarm-Shell",
                          "duration": {"kind": "rounds", "amount": 1}, "evidence": "Swarm-Shell: creatures move through it as difficult terrain"}])
    from .bound_objects import place
    for zid in set(engine.state.zones) - first:
        place(ctx, {'name': 'Swarm-Shell', 'ac': 'save_dc', 'hp': '2*cl',
                    'immune': ['POISON', 'PSYCHIC'], 'vulnerable': ['FIRE', 'RADIANT'],
                    'native_lifecycle': True}, zone_ids=[zid], position=start)


@hook("turn_boundary_start", priority=-100)
def expire_swarm_shell(engine: Any, actor: Any, *, checkpoint: Any = None) -> None:
    from .. import zones
    for zone in list(engine.state.zones.values()):
        if zone.active and zone.owner_id == actor.entity_id and zone.source_definition_id == PREFIX + "brood_substitution":
            zones.remove(engine, zone, "DURATION_ENDED")


# -------------------------------------------------------------------------------------------- Ten-Thousand Worm Demon Body
@hook("condition_attempt")
def worm_slips_holds(ctx: Any, subject: Any, effect: Any) -> bool | None:
    """"Cannot be Grappled or Restrained by ordinary physical effects": a weapon, unarmed or ordinary action's hold."""
    name = str((effect or {}).get("condition") or "").lower()
    if name not in ("grappled", "restrained") or subject is None or _worm(ctx.engine, subject) is None:
        return None
    source = str((ctx.typed or {}).get("source") or "")
    return False if not source.startswith(("tianxia.", "TAL_")) else None


@hook("compile_actions")
def brood_tide(info: dict[str, Any]) -> list[Any] | None:
    """Brood Tide: an Action while the Worm Demon Body lasts (3 Brood, 30-foot cone)."""
    mid = PREFIX + WORM
    if mid not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    numbers = dict(info["numbers"])
    typed = {"source": mid, "numbers": numbers, "area": {"shape": "cone", "size_ft": 30}, "duration": {"kind": "instant"}, "riders": [],
             "effects": [{"type": "brood_tide"}]}
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.{mid}.brood_tide", display_name="Brood Tide", owner_id=info["actor_id"],
                             economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="CELL", range_ft=30,
                             costs=((BROOD, 3),), parameters={"typed": typed, "expected_damage": 36, "brood_tide": True})]


@hook("candidate_allowed")
def brood_tide_while_transformed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if (getattr(action, "parameters", None) or {}).get("brood_tide") and _worm(engine, actor) is None:
        return False
    return None


@effect("brood_tide")
def brood_tide_effect(ctx: Any, row: dict[str, Any]) -> None:
    """Each creature in the cone: a Constitution save; failure 8d8 (the type chosen by the table's damage rule), Infested (an
    Infestation it already had from you gnaws first), Speed - 15 until the end of its next turn; success half, Speed - 5 until
    the start of its next turn."""
    from .. import typed_executor as te
    from .effect_durations import token

    engine, owner = ctx.engine, ctx.actor
    targets = [t for t in (ctx.targets or []) if t.active and t.team_id != owner.team_id]
    damage = {"type": "damage", "applies_to": "target", "dice": {"count": 8, "sides": 8}, "damage_types": ["poison", "necrotic"]}
    for foe in targets:
        sub = te.Context(engine, owner, ctx.action, ctx.intent, ctx.typed, [foe], foe, ctx.damage_cache)
        _pierce(engine, owner)
        try:
            te.run_effects(sub, [{"type": "save", "ability": "con", "evidence": "Brood Tide: Constitution saving throw",
                                  "on_fail": [damage,
                                              {"type": "speed", "applies_to": "target", "flat": -15, "expires_on": token("end", foe.entity_id, int(foe.turns_started) + 1)},
                                              {"type": "brood_tide_infest"}],
                                  "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": ["poison", "necrotic"]},
                                                 {"type": "speed", "applies_to": "target", "flat": -5, "expires_on": "START_OF_TARGET_NEXT_TURN"}]}])
        finally:
            engine._parasite_pierce = None


@effect("brood_tide_infest")
def brood_tide_infest(ctx: Any, row: dict[str, Any]) -> None:
    engine, owner, foe = ctx.engine, ctx.actor, ctx.target
    if foe is None or not foe.active:
        return
    kind = next((str((e.payload or {}).get("damage_type") or "POISON").upper() for e in reversed(engine.events)
                 if e.event_type == "DAMAGE_COMMITTED" and foe.entity_id in (e.target_ids or ())), "POISON")
    old = next((held for held in foe.conditions.values() if held.condition_id == INFESTED and (held.data or {}).get("owner") == owner.entity_id), None)
    if old is not None and "gnaw" in _roles(engine, owner):
        gnaw(engine, foe, owner, old, "is caught in the Brood Tide")  # "immediately triggers Gnawing Infestation ... then gains a new Infestation"
    if foe.active:
        infest(ctx, foe, kind)

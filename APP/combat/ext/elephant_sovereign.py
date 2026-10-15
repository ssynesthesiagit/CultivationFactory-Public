"""White Elephant Sovereign Body riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, White Elephant Sovereign Body (the five features and their Normalized Procedures). Owned
rows: ``{"type": "path_passive", "kind": "elephant", "role": "frame" | "tusks" | "remembers" | "mountain" | "king"}``; the Large form
is the named state "mountain_walking_large" (toggled by Mountain-Walking Sovereign's Bonus Action, ``sovereign_size``); the King is
the named state "world_bearing_elephant_king". Both forms use native dynamic_size growth; functional size
bonuses are separate from their actual footprints. Trampling is owned by elephant_trample.py.

Sovereign Frame     one size larger (hook size_steps) for grappling, shoving and pushing and when something tries to move you;
                    Advantage on saves against being pushed, pulled, knocked Prone or moved.
Ivory Charge        once per turn, an unarmed hit after 15+ feet of this turn's willing movement straight toward the target (every
                    step closer): + PB Bludgeoning or Force, then a Strength save: pushed 10 feet, or 5.
Shelter Beneath the Tusks  when a creature within 15 feet is hit (asked; Reaction, 1 Stamina, once per round; hook confirmed_hit_interception): move
                    up to 10 feet toward it without provoking; next to it, choose: become the target (the same roll against your
                    AC; on a hit the damage is yours), Half Cover (+ 2 AC against that roll) or 2d10 + CON off its damage.
The Body Remembers  a hostile creature that damages your Hit Points is Remembered for the scene (a private owner record; PB of them, a new one
                    past the limit asks which to forget, or is declined): it gets no Advantage from being unseen against you, once
                    per turn + 2d8 Bludgeoning or Force on a hit against one, + PB on your saves against its moves, grapples,
                    Frightened and Restrained.
Mountain-Walking Sovereign  the Bonus Action turns the Large form on or off: + 5 feet unarmed reach, three sizes larger for the size
                    counts (Large plus two), Speed - 5 feet, ordinary difficult terrain ignored, and once per turn after 10 feet of
                    willing movement an asked 5-foot push of an adjacent creature no more than two sizes larger.
World-Bearing Elephant King  its state (typed: Resistance but Psychic, Void; Speed + 20; a following zone of hostile difficult
                    terrain): unarmed strikes roll 2d8 (hook attack_damage), once per turn + 4d8 on a hit, allies within 10 feet
                    get Half Cover when a ranged attack's line crosses your space, and a creature of your CL or lower cannot push,
                    pull or knock you Prone. Huge counts as two sizes larger.
Every hook returns early for a creature without these rows or states.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.white_elephant_sovereign_body.feature."
LARGE = "mountain_walking_large"
KING = "world_bearing_elephant_king"
STAMINA = "resource:core.stamina"
LEVELS = {"frame": 3, "tusks": 6, "remembers": 10, "mountain": 14, "king": 18}


@hook("choice_options")
def sovereign_choices(engine: Any, intent: Any, checkpoint: str, reactor_id: str, choice_id: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Publish the family's actual damage options through the native chooser."""
    from .needle import option_spec
    return option_spec(choice_id, context, "choice:elephant.")


@hook("compile_actions")
def sovereign_profile(info: dict[str, Any]) -> None:
    """Use the common owning-Path profile, never another Path's higher CL."""
    if any(mid.startswith(PREFIX) for mid in info["owned_ids"]):
        from ..activation_settlement import path_numbers
        profile = path_numbers(info, "tianxia.path.body_refining")
        info["passives"].append({"block": "elephant_profile", "numbers": profile,
            "compiled_frame_carry":int(PREFIX+"sovereign_frame" in info['owned_ids'] and int(profile['cl'])>=3)})


@hook("compile_action")
def sovereign_action_profile(action: Any, info: dict[str, Any]) -> Any:
    from copy import deepcopy
    from ..activation_settlement import path_numbers
    typed = (action.parameters or {}).get("typed") or {}
    if not str(typed.get("option_of") or typed.get("source") or "").startswith(PREFIX):
        return None
    parameters = deepcopy(action.parameters)
    parameters["typed"]["numbers"] = path_numbers(info, "tianxia.path.body_refining")
    return action.model_copy(update={"parameters": parameters})


@hook("carrying_capacity_scale")
def frame_carrying(info: dict[str, Any]) -> int | None:
    from ..activation_settlement import path_numbers
    if PREFIX + "sovereign_frame" in info["owned_ids"] and int(path_numbers(info, "tianxia.path.body_refining")["cl"]) >= 3:
        size = str((info["owner_sheet"].get("identity") or {}).get("size") or "Medium").title()
        return None if size == "Small" else 2
    return None


@hook("runtime_carrying_capacity")
def sovereign_carrying_capacity(engine: Any, actor: Any, capacity: int) -> int | None:
    if not body_numbers(engine, actor) or actor.entity_id not in getattr(engine, "actor_footprints", {}):
        return None
    from ..dynamic_size import CATEGORIES, base_category, current_category
    def factor(rank: int) -> int:
        # Twice the ordinary capacity multiplier, so Tiny uses an integer.
        return 1 if rank == 0 else 2 if rank <= 2 else 2 ** (rank - 1)
    base = CATEGORIES.index(base_category(engine, actor))
    actual = CATEGORIES.index(current_category(engine, actor))
    functional = sovereign_size_steps(engine, actor, "act", {"carry"}) or 0
    # The bundle already includes the Frame's permanent size permission.
    frame = any(row.get("block") == "elephant_profile" and row.get("compiled_frame_carry")
                for row in engine.typed_passive_rows.get(actor.entity_id, ()))
    compiled = factor(base + 1) if frame and base != 1 else factor(base)
    return capacity * factor(actual + functional) // compiled


def body_numbers(engine: Any, actor: Any) -> dict[str, Any]:
    """Public family profile shared with the King's native trampling consumer."""
    profile = next((dict(row["numbers"]) for row in getattr(engine, "typed_passive_rows", {}).get(actor.entity_id, ())
                    if row.get("block") == "elephant_profile"), {})
    if profile:
        from ..cultivation_access import effective_cl
        cl = effective_cl(engine, actor, int(profile['cl']))
        if cl < int(profile['cl']):
            pb = 2+max(0,cl-1)//4
            delta = int(profile.get('pb',actor.proficiency_bonus))-pb
            for key in ('save_dc','attack_bonus'):
                if key in profile:
                    profile[key] -= delta
            profile.update(cl=cl,pb=pb)
    return profile


def body_pb(engine: Any, actor: Any) -> int:
    """Body's suppressed Proficiency Bonus, independent of other Path levels."""
    return int(body_numbers(engine, actor).get("pb") or actor.proficiency_bonus or 2)


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "elephant"
            and _cl(engine, actor.entity_id) >= LEVELS.get(str(row.get("role")), 21)}


def active_form(engine: Any, actor: Any, name: str) -> Any:
    from .states import active
    from ..alternative_payments import owned

    level = 18 if name == KING else 14
    source = PREFIX + (KING if name == KING else "mountain_walking_sovereign")
    return active(engine, actor, name) if actor is not None and _cl(engine, actor.entity_id) >= level and owned(engine, actor, source) else None


def _stamp(engine: Any) -> str:
    current = engine.state.actors.get(engine.state.current_actor_id)
    return f"{engine.state.round_number}:{engine.state.current_actor_id}:{current.turns_started if current else 0}"


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


def _cl(engine: Any, actor_id: str) -> int:
    actor = engine.state.actors.get(actor_id)
    profile = body_numbers(engine, actor) if actor is not None else {}
    if profile:
        return int(profile["cl"])
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == actor_id), None)
    return int((bundle or {}).get("cl") or 0)


def _con(engine: Any, actor: Any) -> int:
    return next((int((((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("con_mod") or 0)
                 for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                 and (((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("con_mod") is not None), 0)


# -------------------------------------------------------------------------------------------------- size and saves
@hook("size_steps")
def sovereign_size_steps(engine: Any, creature: Any, role: str, purposes: Any) -> int | None:
    roles = _roles(engine, creature)
    if not roles:
        return None
    large = active_form(engine, creature, LARGE)
    purposes = set(purposes or ())
    frame = {"carry", "carrying", "drag", "dragging", "lift", "lifting", "push", "forced", "grapple", "shove"}
    mountain = {"carry", "carrying", "lift", "lifting", "grapple", "shove"} | ({"forced"} if role == "resist" else set())
    if "dragging" in purposes:
        mountain -= {"carry", "carrying"}
    functional = 2 if large and purposes & mountain else 1 if "frame" in roles and purposes & frame else 0
    return functional or None  # actual size now comes from the native footprint


@hook("candidate_allowed")
def sovereign_level_gate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    source = str(typed.get("option_of") or typed.get("source") or "")
    minimum = {PREFIX + "mountain_walking_sovereign": 14, PREFIX + KING: 18}.get(source)
    if minimum is not None and _cl(engine, actor.entity_id) < minimum:
        return False
    return None


@hook("save")
def sovereign_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if ctx is None or subject is None:
        return None
    roles = _roles(ctx.engine, subject)
    names = {str(n).lower() for n in named or ()}
    out: dict[str, Any] = {"bonus": 0, "modes": []}
    if "frame" in roles and names & {"forced_movement", "prone"}:
        out["modes"].append("ADVANTAGE")  # "Advantage on saves against being pushed, pulled, knocked Prone, or moved"
    if "remembers" in roles and _remembered(ctx.actor, subject) and names & {"forced_movement", "grappled", "frightened", "restrained"}:
        out["bonus"] += body_pb(ctx.engine, subject)
    return out if out["bonus"] or out["modes"] else None


@hook("save_mode")
def sovereign_native_saves(engine: Any, target: Any, ability: str, dc: int, source_id: str, roll_context: Any) -> str | None:
    if "frame" in _roles(engine, target) and set((roll_context or {}).get("named") or ()) & {"forced_movement", "prone"}:
        return "ADVANTAGE"
    return None


# ------------------------------------------------------------------------------------------------------ Ivory Charge
def _charged_ft(engine: Any, actor: Any, target: Any) -> int:
    """Feet of this turn's willing movement in the latest run of steps each ending closer to ``target``."""
    from ..gate2_runtime_models import Position
    run = 0
    goal = target.position
    endpoint = actor.position
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED":
            break
        payload = event.payload or {}
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == target.entity_id:
            path = [Position.model_validate(p) for p in payload.get("path") or [] if isinstance(p, dict)]
            if not path:
                break  # an origin is required to reconstruct distance at an earlier step
            goal = path[0]
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == actor.entity_id and (payload.get("forced") or payload.get("teleport")):
            break
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == actor.entity_id and not payload.get("forced") and not payload.get("teleport"):
            path = [Position.model_validate(p) for p in payload.get("path") or [] if isinstance(p, dict)]
            for a, b in reversed(list(zip(path, path[1:]))):
                if b != endpoint or engine.grid.distance_ft(b, goal) >= engine.grid.distance_ft(a, goal):
                    return run
                run += int(engine.grid.distance_ft(a, b))
                endpoint = a
    return run


# ------------------------------------------------------------------------------------------------------ hit riders
@hook("hit_snapshot")
def sovereign_hit_snapshot(engine: Any, actor: Any, target: Any, attack_context: Any, intent: Any) -> dict[str, Any] | None:
    """Freeze native approach/mark/form facts at the hit, before reactions move bodies."""
    roles = _roles(engine, actor)
    king = active_form(engine, actor, KING)
    if not roles and not king:
        return None
    return {"white_elephant_sovereign":{
        "roles":sorted(roles), "approach_ft":_charged_ft(engine,actor,target) if "frame" in roles else 0,
        "remembered":int("remembers" in roles and _remembered(target,actor)), "king":int(king is not None),
        "numbers":body_numbers(engine,actor)}}


@hook("hit_final")
def sovereign_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    receipt = ctx.hit_snapshots.get("white_elephant_sovereign") or {}
    roles = set(receipt['roles']) if receipt else _roles(engine, actor)
    king = bool(receipt.get("king")) if receipt else active_form(engine, actor, KING) is not None
    if (not roles and not king) or target is None or not target.active:
        return
    from .. import typed_executor as te

    stamp = _stamp(engine)
    approach = int(receipt['approach_ft']) if receipt else _charged_ft(engine,actor,target)
    sub = ctx.on_hit_context(target, action=ctx.action,
        typed={**ctx.typed, "numbers":receipt.get("numbers") or body_numbers(engine, actor) or ctx.numbers}, damage_cache={})
    def damage_type(name: str) -> list[str]:
        from .needle import ask, checkpoint_id
        picked = ask(engine, ctx.intent, checkpoint_id(engine, name, target.entity_id), actor,
                     "choice:elephant." + name, ["bludgeoning", "force"],
                     labels={"bludgeoning": "Bludgeoning damage", "force": "Force damage"},
                     target_id=target.entity_id, name=name.replace("_", " ").title(),
                     prompt=f"{name.replace('_', ' ').title()}: choose the extra damage for the creature hit by {actor.display_name}'s attack.")
        return [picked[0] if picked and picked[0] in {"bludgeoning", "force"} else "bludgeoning"]
    if "frame" in roles and kind == "unarmed" and actor.turn_flags.get("_round_ivory_charge") != stamp \
            and approach >= 15:
        actor.turn_flags["_round_ivory_charge"] = stamp
        push = lambda ft: {"type": "forced_movement", "applies_to": "target", "distance_ft": ft, "direction": "away"}
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "flat": int(sub.numbers.get('pb') or body_pb(engine,actor)), "damage_types": damage_type("ivory_charge"),
                              "evidence": "Ivory Charge: + Proficiency Bonus"},
                             {"type": "save", "ability": "str", "evidence": "Ivory Charge: Strength saving throw", "on_fail": [push(10)], "on_success": [push(5)]}])
    if "remembers" in roles and target.active and (receipt.get("remembered") if receipt else _remembered(target, actor)) and actor.turn_flags.get("_round_remembered_hit") != stamp:
        actor.turn_flags["_round_remembered_hit"] = stamp
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": damage_type("the_body_remembers"),
                              "evidence": "The Body Remembers: + 2d8"}])
    if king and target.active and actor.turn_flags.get("_round_king_hit") != stamp:
        actor.turn_flags["_round_king_hit"] = stamp
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 4, "sides": 8}, "damage_types": damage_type("world_bearing_elephant_king"),
                              "evidence": "World-Bearing Elephant King: + 4d8"}])


@hook("attack_damage")
def king_unarmed_die(ctx: Any, dice: Any) -> Any:
    """"Unarmed strikes deal 2d8 before modifiers" while the King lasts."""
    if dice is None or not active_form(ctx.engine, ctx.actor, KING):
        return None
    if not any(isinstance(e, dict) and e.get("attack_kind") == "unarmed" for e in (ctx.typed or {}).get("effects") or []):
        return None
    return dice.model_copy(update={"count": 2, "sides": 8})


# ---------------------------------------------------------------------------------------------- The Body Remembers
RECORDS = '_round_elephant_remembered_records'
MEMORY_SOURCE = PREFIX+'the_body_remembers'


def remembered_records(owner: Any) -> dict[str, dict[str, Any]]:
    """Private primitive records, shared with this family's journey adapter.

    The owner holds its memory; the other creature gains no public condition.
    Actor snapshots do not expose turn flags to another creature's AI seat.
    """
    if owner is None:
        return {}
    stored = owner.turn_flags.get(RECORDS)
    if not isinstance(stored, dict):
        return {}
    return {aid:dict(record) for aid,record in stored.items()
            if isinstance(record,dict) and record.get('owner_id')==owner.entity_id
            and record.get('remembered_id')==aid and record.get('source_id')==MEMORY_SOURCE
            and type(record.get('source_cl')) is int and record['source_cl'] >= 10
            and type(record.get('acquisition_event')) is int and record['acquisition_event'] >= 0
            and type(record.get('record_number')) is int and record['record_number'] > 0}


def _remembered(creature: Any, owner: Any) -> bool:
    return creature is not None and creature.entity_id in remembered_records(owner)


@hook("event", nested=True)
def remember_the_blow(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get('payload') or {}
    if (event_type != "DAMAGE_COMMITTED" or int(payload.get("hp_damage") or 0) < 1
            or 'hp_before' in payload and int(payload['hp_before']) < 1):
        return
    source = engine.state.actors.get(kwargs.get("actor_id") or "")
    from ..relations import relation, ENEMY
    for target_id in kwargs.get("target_ids") or ():
        owner = engine.state.actors.get(target_id)
        if (owner is None or source is None or relation(engine, source, owner) != ENEMY
                or (source.summon or {}).get("owner") == owner.entity_id
                or source.owner_id == owner.entity_id or "remembers" not in _roles(engine, owner) or _remembered(source, owner)):
            continue
        held = remembered_records(owner)
        while len(held) >= body_pb(engine, owner):
            from .needle import ask, checkpoint_id

            options = {f"memory:{record['record_number']}":aid for aid,record in held.items()}
            labels = {key:f"Forget remembered attacker {held[aid]['record_number']}" for key,aid in options.items()}
            picked = ask(engine, _intent(engine), checkpoint_id(engine, "remembered", source.entity_id), owner, "choice:needle.body_remembers", list(options),
                         labels=labels, allow_decline=True, target_id=source.entity_id,
                         name="The Body Remembers", prompt=f"The Body Remembers: {owner.display_name} was damaged by an attacker. Forget one remembered creature to record this attacker, or decline?")
            if not picked or picked[0] not in options:
                break
            gone = held.pop(options[picked[0]])
            engine._append_event('PASSIVE_TRIGGERED',MEMORY_SOURCE,actor_id=owner.entity_id,target_ids=(owner.entity_id,),
                payload={'log':f"{owner.display_name} forgets remembered attacker {gone['record_number']}."})
        if len(held) >= body_pb(engine, owner):
            continue  # declining the new record never discards an existing memory
        from ..observer_information import direction
        event = kwargs['originating_event']
        record_number = 1+max((int(r['record_number']) for r in held.values()),default=0)
        held[source.entity_id] = {'owner_id':owner.entity_id,'source_id':MEMORY_SOURCE,
            'record_number':record_number,'source_cl':_cl(engine,owner.entity_id),'remembered_id':source.entity_id,
            'direction':direction(owner.position,source.position) if engine._distance_actor_to_actor(owner,source)<=120 else 'unknown',
            'acquisition_event':event.sequence,'acquisition_transaction':event.transaction_id}
        owner.turn_flags[RECORDS] = held
        engine._append_event('PASSIVE_TRIGGERED',MEMORY_SOURCE,actor_id=owner.entity_id,target_ids=(owner.entity_id,),
            payload={'log':f"{owner.display_name} remembers attacker {record_number} until this scene ends."})


@hook('event',nested=True)
def remembered_capacity(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """A live PB reduction asks the owner which excess scene records to forget."""
    if event_type not in {'CONDITION_APPLIED','CONDITION_REMOVED','TURN_STARTED'}:
        return
    from .needle import ask, checkpoint_id
    for owner in engine.state.actors.values():
        held = remembered_records(owner)
        if not held or 'remembers' not in _roles(engine,owner):
            continue  # unavailable records remain dormant, rather than being destroyed
        excess = len(held)-body_pb(engine,owner)
        if excess <= 0:
            continue
        options = {f"memory:{r['record_number']}":aid for aid,r in held.items()}
        picked = ask(engine,_intent(engine),checkpoint_id(engine,'remembered_capacity',owner.entity_id),
            owner,'choice:needle.body_remembers',list(options),minimum=excess,maximum=excess,
            labels={key:f"Forget remembered attacker {held[aid]['record_number']}" for key,aid in options.items()},
            target_id=owner.entity_id,name='The Body Remembers',
            prompt=f"The Body Remembers: {owner.display_name}'s Proficiency Bonus now permits {body_pb(engine,owner)} remembered creatures. Choose {excess} to forget.")
        for key in picked:
            if key in options:
                held.pop(options[key],None)
        owner.turn_flags[RECORDS] = held


@hook('event',nested=True)
def remembered_last_direction(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type not in {'MOVEMENT_COMMITTED','TURN_STARTED','CONDITION_REMOVED'}:
        return
    from ..observer_information import direction
    for owner in engine.state.actors.values():
        held = remembered_records(owner)
        if not held or 'remembers' not in _roles(engine,owner):
            continue
        for aid,record in held.items():
            creature = engine.state.actors.get(aid)
            if creature is None or engine._distance_actor_to_actor(owner,creature)>120:
                continue
            current = direction(owner.position,creature.position)
            if record.get('direction') != current:
                record['direction'] = current
        owner.turn_flags[RECORDS] = held


@hook("observer_information_rows")
def remembered_directions(engine: Any, viewer: Any) -> list[dict[str, Any]] | None:
    """Private coarse direction only: never grants identity, sight or targeting."""
    if (not viewer.active or viewer.life_state in {'DYING','STABLE'}
            or any(str(c.condition_id).endswith('unconscious') for c in viewer.conditions.values())
            or "remembers" not in _roles(engine, viewer)):
        return None
    from ..observer_information import direction
    return [{"kind": "direction", "viewer_id": viewer.entity_id, "source_id": PREFIX + "the_body_remembers",
             "authority_actor_id": viewer.entity_id,
             "details": {"direction": direction(viewer.position, creature.position),
                         "label": "The Body Remembers: remembered attacker "+str(remembered_records(viewer)[creature.entity_id]['record_number'])}}
            for creature in engine.state.actors.values() if _remembered(creature, viewer)
            and engine._distance_actor_to_actor(viewer, creature) <= 120]


@hook("ability_check_hazard_mode")
def sovereign_resists_checks(engine: Any, actor: Any, ability: str, skill: Any, opponent: Any, hazards: Any) -> str | None:
    if "frame" in _roles(engine, actor) and set(hazards or ()) & {"forced_movement", "push", "pull", "prone", "unwilling_movement"}:
        return "ADVANTAGE"
    return None


@hook("d20_bonus")
def remembered_check_bonus(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    frame = engine.d20_context() or {}
    if frame.get("kind") != "check":
        return None
    subject = engine.state.actors.get(roll.actor_id)
    source = engine.state.actors.get(frame.get("source_actor_id"))
    hazards = set(frame.get("hazards") or ())
    if subject is None or source is subject or "remembers" not in _roles(engine, subject) or not _remembered(source, subject):
        return None
    if hazards & {"forced_movement", "grappled", "frightened", "restrained"}:
        return {"source_id": PREFIX + "the_body_remembers", "bonus": body_pb(engine, subject)}
    return None


@hook("masked_conditions")
def remembered_unseen(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    """"It cannot gain Advantage against you merely by being unseen"."""
    if target is None or attacker is None or "remembers" not in _roles(engine, target) or not _remembered(attacker, target):
        return None
    from ..senses import rules as sense_rules

    hidden = set(sense_rules().get("hidden_conditions") or [])
    ids = {iid for iid, held in attacker.conditions.items() if held.condition_id in hidden}
    return {attacker.entity_id: ids} if ids else None


@hook("attack_mode_removed")
def remembered_unseen_geometry(engine: Any, attacker: Any, target: Any, ranged: Any) -> list[str] | None:
    if target is not None and "remembers" in _roles(engine, target) and _remembered(attacker, target):
        return ["ADVANTAGE:unseen"]
    return None


# ------------------------------------------------------------------------------------------ Shelter Beneath the Tusks
@hook("confirmed_hit_interception")
def shelter_beneath_the_tusks(engine: Any, attacker: Any, target: Any, spec: Any, total: int, natural: int, effective_ac: int) -> Any:
    guards = [g for g in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if g.active and g.entity_id != target.entity_id
              and "tusks" in _roles(engine, g) and g.reaction_available and int(g.resources.get(STAMINA, 0) or 0) >= 1
              and g.turn_flags.get("_round_tusks") != int(engine.state.round_number) and engine._distance_actor_to_actor(g, target) <= 15]
    for guard in guards:
        answer = _tusks(engine, guard, attacker, target, spec, total, natural, effective_ac)
        if answer is not False and (answer is not None or spec.get('confirmed_hit_recipient')):
            return answer
    return None


def _tusks(engine: Any, guard: Any, attacker: Any, target: Any, spec: Any, total: int, natural: int, effective_ac: int) -> Any:
    from ..gate2_runtime_models import DiceSpec
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    intent = _intent(engine)
    picked = ask(engine, intent, checkpoint_id(engine, "tusks", target.entity_id), guard, "choice:needle.shelter_beneath_the_tusks", ["use"],
                 labels={"use": "Reaction, 1 Stamina: move up to 10 feet toward it and shield it"}, allow_decline=True, default="decline",
                 target_id=target.entity_id, name="Shelter Beneath the Tusks",
                 prompt=f"Shelter Beneath the Tusks: an attack hits a creature within 15 feet of {guard.display_name}. Spend your Reaction and 1 Stamina to move up to 10 feet without provoking and protect it?")
    if not picked:
        return False
    with activation(engine, guard, PREFIX + "shelter_beneath_the_tusks"):
        guard.reaction_available = False
        guard.turn_flags["_round_tusks"] = int(engine.state.round_number)
        engine._spend_resource(guard, STAMINA, 1, PREFIX + "shelter_beneath_the_tusks")
        engine._append_event("REACTION_RESOLVED", PREFIX + "shelter_beneath_the_tusks", actor_id=guard.entity_id, target_ids=(attacker.entity_id,),
                             payload={"checkpoint": "ALLY_HIT", "protects": target.entity_id})
        now = engine._distance_actor_to_actor(guard, target)
        if now > engine.grid.square_size_ft:
            def distance(path):
                moved = guard.model_copy(update={'position': path[-1]})
                return engine._distance_actor_to_actor(moved, target)
            paths = {k: p for k, p in routes(engine, guard, 10).items() if distance(p) < now}
            paths['stay'] = [guard.position]
            if paths:
                nearest = min(paths, key=lambda k: (distance(paths[k]), len(paths[k]), k))
                move = ask(engine, intent, checkpoint_id(engine, "tusks_move", guard.entity_id), guard, "choice:needle.tusks_move", sorted(paths),
                           labels={k: "Stay here" if k == 'stay' else "Move to " + k.removeprefix("cell:") for k in paths}, preferred=[nearest], target_id=guard.entity_id,
                           name="Shelter Beneath the Tusks", prompt="Shelter Beneath the Tusks: move up to 10 feet toward it.")
                chosen = move[0] if move and move[0] in paths else nearest
                step(engine, guard, paths[chosen], PREFIX + "shelter_beneath_the_tusks")
        if engine._distance_actor_to_actor(guard, target) > engine.grid.square_size_ft or not guard.active:
            return None  # not adjacent: the attack resolves normally
        labels = {"cover": "Grant it Half Cover against this attack", "reduce": "Take 2d10 + Constitution modifier off its damage"}
        from .redirection import legal_target
        effect = ((spec or {}).get("checkpoint_context") or {}).get("effect") or {}
        unique = any(effect.get(key) for key in ("requires_unique_anatomy", "requires_bond", "requires_mark", "requires_identity"))
        if not unique and legal_target(engine, attacker, guard, (spec or {}).get("range_ft") or (spec or {}).get("reach_ft") or 5):
            labels = {"target": "Become the target instead", **labels}
        option = ask(engine, intent, checkpoint_id(engine, "tusks_option", target.entity_id), guard, "choice:needle.tusks_option", list(labels), labels=labels,
                     target_id=target.entity_id, name="Shelter Beneath the Tusks", prompt="Shelter Beneath the Tusks: choose one.")
        choice = option[0] if option and option[0] in labels else "reduce"
        if choice == "cover":
            old_cover, _ = engine._attack_defense(attacker, target, spec)
            covered_ac = effective_ac + max(0, 2 - old_cover)
            return (covered_ac, False) if natural != 20 and total < covered_ac else None
        if choice == "reduce":
            roll = engine.roller.roll(DiceSpec(count=2, sides=10, modifier=_con(engine, guard)), actor_id=guard.entity_id, reason=f"REDUCTION:{PREFIX}shelter_beneath_the_tusks")
            engine._record_roll(roll)
            previous = target.turn_flags.get('_tusk_reduce') or {}
            carried = int(previous.get('amount',0)) if previous.get('roll_id') == spec.get('attack_roll_id') else 0
            target.turn_flags["_tusk_reduce"] = {"by": attacker.entity_id, "amount": carried+max(0, int(roll.total)),
                                                "roll_id": str(spec.get("attack_roll_id") or "")}
            return None
        spec["confirmed_hit_recipient"] = {"target_id": guard.entity_id, "source_id": PREFIX + "shelter_beneath_the_tusks"}
        _, guard_ac = engine._attack_defense(attacker, guard, spec)
        if natural != 20 and total < guard_ac:
            note(engine, PREFIX + "shelter_beneath_the_tusks", guard, f"Shelter Beneath the Tusks: {guard.display_name} takes the blow on the tusks; it misses.")
            return guard_ac, False  # terminal numerical comparison against the replacement target
        return None


@hook("damage_pending")
def tusks_damage(engine: Any, target: Any, pending: int, source_definition_id: str, source_actor_id: str) -> int | None:
    reduce = target.turn_flags.get("_tusk_reduce")
    packet = engine.damage_context()
    if reduce and reduce.get("by") == source_actor_id and packet is not None and reduce.get("roll_id") == packet.roll_id:
        cut = min(pending,int(reduce.get("amount") or 0))
        left = int(reduce.get("amount") or 0)-cut
        if left:
            target.turn_flags['_tusk_reduce'] = {**reduce,'amount':left}
        else:
            target.turn_flags.pop('_tusk_reduce',None)
        return pending-cut
    return None


@hook("attack_completed")
def tusks_packet_ended(engine: Any, notice: Any, intent: Any) -> None:
    target = engine.state.actors.get(notice.target_id)
    if target is not None and (target.turn_flags.get("_tusk_reduce") or {}).get("by") == notice.attacker_id:
        target.turn_flags.pop("_tusk_reduce", None)


# ------------------------------------------------------------------------------------------- Mountain-Walking Sovereign
def end_sovereign_form(engine: Any, actor: Any, name: str, *, reason: str = "FORM_REPLACED") -> None:
    """Retire one source-owned form without touching its paid scene counter."""
    from ..effect_endings import remove_instance
    from .. import zones
    from .ability_source import mechanic_at
    source = PREFIX + (KING if name == KING else "mountain_walking_sovereign")
    for kind, rows in (("condition", actor.conditions), ("modifier", actor.modifiers)):
        for key, held in list(rows.items()):
            if held.source_actor_id == actor.entity_id and (mechanic_at(engine, held.source_definition_id) or held.source_definition_id) == source:
                remove_instance(engine, actor, kind, key, held.source_definition_id, payload={"reason":reason})
    for zone in list(engine.state.zones.values()):
        if zone.owner_id == actor.entity_id and (mechanic_at(engine, zone.source_definition_id) or zone.source_definition_id) == source and zone.active:
            zones.remove(engine, zone, reason)


@effect("sovereign_size")
def sovereign_size(ctx: Any, row: dict[str, Any]) -> None:
    """The Bonus Action: become Large, or return to normal size."""
    from .states import PREFIX as STATE, slug

    engine, actor = ctx.engine, ctx.actor
    from .. import dynamic_size
    held = active_form(engine, actor, LARGE)
    if held is not None:
        for iid, h in list(actor.conditions.items()):
            if h.condition_id in (STATE + slug(LARGE), "condition:typed.ignore_difficult", dynamic_size.CONDITION) and h.source_definition_id == PREFIX + "mountain_walking_sovereign":
                del actor.conditions[iid]
                engine._append_event("CONDITION_REMOVED", PREFIX + "mountain_walking_sovereign", actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                     payload={"condition_id": h.condition_id, "instance_id": iid, "reason": "NORMAL_SIZE"})
        dynamic_size.sync(engine, ctx.source)
        return
    category = dynamic_size.fitting_category(engine, actor, "Large")
    if category != "Large":
        note(engine, ctx.source, actor, f"Mountain-Walking Sovereign: there is no room for {actor.display_name} to become Large.")
        return
    end_sovereign_form(engine, actor, KING)
    dynamic_size.apply_growth(engine, actor, "Large", PREFIX + "mountain_walking_sovereign", source_actor_id=actor.entity_id, expires_on="UNTIL_REMOVED")
    engine._apply_condition(actor, STATE + slug(LARGE), PREFIX + "mountain_walking_sovereign", actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Mountain-Walking Sovereign: Large", "name": LARGE})
    engine._apply_condition(actor, "condition:typed.ignore_difficult", PREFIX + "mountain_walking_sovereign", actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Large: ordinary difficult terrain costs no extra movement"})


@hook("event")
def sovereign_growth(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    from .states import PREFIX as STATE, slug
    from .. import dynamic_size
    payload = kwargs.get("payload") or {}
    if event_type == "CONDITION_APPLIED" and payload.get("condition_id") == STATE + slug(KING):
        actor = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
        if actor is not None and active_form(engine, actor, KING) is not None:
            held = active_form(engine, actor, KING)
            end_sovereign_form(engine, actor, LARGE)
            dynamic_size.apply_growth(engine, actor, "Huge", held.source_definition_id, source_actor_id=actor.entity_id,
                                      expires_on=payload.get("expires_on"))
    if event_type == "CONDITION_APPLIED" and str(payload.get("condition_id") or "").endswith("unconscious"):
        actor = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
        if actor is not None:
            from .condition_ownership import remove_instance
            for held in list(actor.conditions.values()):
                if held.source_definition_id in (PREFIX + KING, PREFIX + "mountain_walking_sovereign"):
                    remove_instance(engine, actor, held.instance_id, held.source_definition_id)


@hook("speed")
def large_is_slower(engine: Any, actor: Any) -> int | None:
    return -5 if active_form(engine, actor, LARGE) else None


@hook("event")
def mountain_push(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"Once per turn after moving 10 feet, automatically push one adjacent creature 5 feet unless it is more than two sizes larger"."""
    if event_type != "MOVEMENT_COMMITTED":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    payload = kwargs.get("payload") or {}
    if actor is None or payload.get("forced") or payload.get("teleport") \
            or not active_form(engine, actor, LARGE) or actor.turn_flags.get("_round_mountain_push") == _stamp(engine):
        return
    moved = 0
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED":
            break
        p = event.payload or {}
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == actor.entity_id and not p.get("forced") and not p.get("teleport"):
            moved += max(0, len(p.get("path") or []) - 1) * engine.grid.square_size_ft
    if moved < 10:
        return
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id
    from .states import context

    ctx = context(engine, actor, PREFIX + "mountain_walking_sovereign", [actor], {})
    from ..dynamic_size import CATEGORIES, current_category
    actual_rank = lambda c: CATEGORIES.index(current_category(engine,c))
    near = {c.entity_id: c for c in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if c.active and c.entity_id != actor.entity_id
            and engine._distance_actor_to_actor(actor, c) <= engine.grid.square_size_ft
            and actual_rank(c) <= actual_rank(actor) + 2}
    if not near:
        return
    from ..observer_information import direction
    options = {f'adjacent:{i}':c for i,c in enumerate(near.values(),1)}
    picked = ask(engine, _intent(engine), checkpoint_id(engine, "mountain_push", actor.entity_id), actor, "choice:needle.mountain_push", list(options),
                 labels={k: f"Push adjacent creature {i} ({direction(actor.position,c.position)}) 5 feet" for i,(k,c) in enumerate(options.items(),1)}, allow_decline=True, target_id=actor.entity_id,
                 name="Mountain-Walking Sovereign", prompt="Mountain-Walking Sovereign: shoulder an adjacent creature 5 feet aside?")
    if picked and picked[0] in options:
        actor.turn_flags["_round_mountain_push"] = _stamp(engine)
        push_ctx = context(engine, actor, PREFIX + "mountain_walking_sovereign", [options[picked[0]]], body_numbers(engine,actor))
        push_ctx.target = options[picked[0]]
        te.run_effects(push_ctx, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}])


# ------------------------------------------------------------------------------------------ World-Bearing Elephant King
@hook("cover")
def king_shelters_allies(engine: Any, attacker: Any, target: Any) -> int | None:
    from ..relations import relation, ALLY
    best = None
    for king in engine.state.actors.values():
        if not king.active or king.entity_id == target.entity_id or relation(engine, king, target) != ALLY or not active_form(engine, king, KING):
            continue
        if engine._distance_actor_to_actor(king, target) > 10:
            continue
        space = {(c.x, c.y) if hasattr(c, "x") else tuple(c) for c in engine._actor_cells(king)}
        if space & set(engine.grid.ray_cells(attacker.position, target.position)[1:-1]):
            best = 2
    return best


@hook("forced_distance")
def king_is_anchored(engine: Any, mover: Any, source: Any, distance_ft: int) -> int | None:
    if mover is None or source is None or source.entity_id == mover.entity_id or not active_form(engine, mover, KING):
        return None
    from ..reaction_trigger import current_trigger
    trigger = current_trigger(engine) or {}
    if trigger.get("actor_id") == source.entity_id and trigger.get("target_id") == mover.entity_id and "source_cl" in trigger:
        return distance_ft if not trigger.get("ignores_bodily_anchoring") and int(trigger["source_cl"]) <= _cl(engine, mover.entity_id) else None
    from ..paid_relocation import current_activation
    receipt = current_activation(engine)
    action = engine.action_catalog.get(receipt.source_id if receipt is not None and receipt.actor_id == source.entity_id
                                      else getattr(engine, "_active_action_source_id", ""))
    if action is not None and (action.parameters.get("typed") or {}).get("ignores_bodily_anchoring"):
        return None
    from ..activation_settlement import profile
    source_cl = profile(engine, source, action)["source_cl"] if action else _cl(engine, source.entity_id)
    return distance_ft if source_cl <= _cl(engine, mover.entity_id) else None


@hook("forced_movement_reduction")
def king_typed_anchoring(ctx: Any, subject: Any) -> int | None:
    if (subject is ctx.actor or not active_form(ctx.engine, subject, KING)
            or ctx.typed.get("ignores_bodily_anchoring")):
        return None
    if int(ctx.numbers.get("cl") or _cl(ctx.engine, ctx.actor.entity_id)) <= _cl(ctx.engine, subject.entity_id):
        return int(ctx.forced_movement_distance_ft or 0)
    return None


@hook("condition_attempt")
def king_stays_up(ctx: Any, subject: Any, effect: Any) -> bool | None:
    if str((effect or {}).get("condition") or "").lower() != "prone" or subject is None or not active_form(ctx.engine, subject, KING):
        return None
    if ctx.actor is subject or ctx.typed.get("ignores_bodily_anchoring") or int(ctx.numbers.get("cl") or _cl(ctx.engine, ctx.actor.entity_id)) > _cl(ctx.engine, subject.entity_id):
        return None
    return False


@hook("subject_teleport_attempt")
def king_resists_hostile_teleport(ctx: Any, subject: Any, start: Any, destination: Any) -> bool | None:
    if (subject is ctx.actor or subject.team_id == ctx.actor.team_id
            or not active_form(ctx.engine, subject, KING) or ctx.typed.get("ignores_bodily_anchoring")):
        return None
    return False if int(ctx.numbers.get("cl") or 1) <= _cl(ctx.engine, subject.entity_id) else None


DORMANT = "elephant_dormant:"


@hook("state_event")
def sovereign_dormancy(engine: Any, event: Any) -> None:
    """Family consumer of native cultivation caps; preserve original expiry.

    Source-owned conditions and modifiers retain their instances and clocks
    while their mechanical names are dormant. Restoring a cap cannot refund a
    cost, refresh a scene limit, or recreate a state whose duration expired.
    """
    if event.event_type not in {"CONDITION_APPLIED", "CONDITION_REMOVED", "LIFE_STATE_CHANGED"} or getattr(engine, "_elephant_dormancy_busy", False):
        return
    engine._elephant_dormancy_busy = True
    try:
        from .ability_source import mechanic_at
        from .. import dynamic_size
        for actor in engine.state.actors.values():
            if not body_numbers(engine, actor):
                continue
            level = _cl(engine, actor.entity_id)
            unconscious = actor.life_state in {"DYING", "STABLE"} or any(str(c.condition_id).endswith("unconscious") for c in actor.conditions.values())
            if unconscious:
                end_sovereign_form(engine, actor, KING, reason="UNCONSCIOUS")
                end_sovereign_form(engine, actor, LARGE, reason="UNCONSCIOUS")
                continue
            for iid, held in list(actor.conditions.items()):
                source = mechanic_at(engine, held.source_definition_id) or held.source_definition_id
                minimum = {PREFIX + "mountain_walking_sovereign": 14, PREFIX + KING: 18}.get(source)
                if minimum is None:
                    continue
                if unconscious or level == 0 and minimum == 14:
                    del actor.conditions[iid]
                    engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=actor.entity_id,
                        target_ids=(actor.entity_id,), payload={"condition_id":held.condition_id,"instance_id":iid,"reason":"FORM_ENDED"})
                    continue
                dormant = held.condition_id.startswith(DORMANT)
                if dormant == (level < minimum):
                    continue
                name = held.condition_id.removeprefix(DORMANT) if dormant else DORMANT + held.condition_id
                actor.conditions[iid] = held.model_copy(update={"condition_id":name})
                engine._append_event("CONDITION_APPLIED", held.source_definition_id, actor_id=actor.entity_id,
                    target_ids=(actor.entity_id,), payload={"condition_id":name,"instance_id":iid,"expires_on":held.expires_on})
            for mid, modifier in list(actor.modifiers.items()):
                source = mechanic_at(engine, modifier.source_definition_id) or modifier.source_definition_id
                if source != PREFIX + KING:
                    continue
                if unconscious:
                    del actor.modifiers[mid]
                    engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=actor.entity_id,
                        target_ids=(actor.entity_id,), payload={"modifier_id":mid,"reason":"FORM_ENDED"})
                    continue
                dormant = modifier.target_field.startswith(DORMANT)
                if dormant != (level < 18):
                    field = modifier.target_field.removeprefix(DORMANT) if dormant else DORMANT + modifier.target_field
                    actor.modifiers[mid] = modifier.model_copy(update={"target_field":field})
                    engine._append_event("MODIFIER_APPLIED", modifier.source_definition_id, actor_id=actor.entity_id,
                        target_ids=(actor.entity_id,), payload={"modifier_id":mid,"target_field":field,"value":modifier.value})
        dynamic_size.sync(engine, event.source_definition_id)
    finally:
        engine._elephant_dormancy_busy = False


@hook("difficult_zone_exempt")
def dormant_king_terrain(engine: Any, actor: Any, zone: Any) -> bool | None:
    from .ability_source import mechanic_at
    if (mechanic_at(engine, zone.source_definition_id) or zone.source_definition_id) != PREFIX + KING:
        return None
    owner = engine.state.actors.get(zone.owner_id)
    return True if owner is None or not active_form(engine, owner, KING) else None

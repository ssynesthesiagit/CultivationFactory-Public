"""Nine-Star Meridian Body riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, "27. Nine-Star Meridian Body". Celestial Marks (resource:named.celestial_mark) use
the shared body_modes_scene_resources scene and native paid-activation receipts. This provider grants 1 at Initiative,
3 with Constellation Circuit, and one per round after a resolved positive Stamina payment on a qualifying Body feature.
subpath_pools applies gains and the effective maximum (PB, or PB + 3 with Constellation Circuit). Owned rows:
``{"type": "path_passive", "kind": "nine_star", "role": "constellation"}``; effects ``star_step``, ``ac_against``, ``orbital_step``,
``nine_star_state``.

Star-Lit Acupoints   paid hit (1 Mark, once per turn): + 1d8 Force or Radiant and the asked result (move 5 ft, push 5, pull 5,
                     or +1 AC against that creature until the start of your next turn).
Orbital Body         its Reaction (1 Mark) after an attack hits or a failed Dexterity damaging save: 2d8 + CON off one packet
                     after type/percentage defenses, then (asked) move 10 feet without provoking after that packet resolves,
                     or 15 feet if this feature and earlier modifiers brought it to 0.
Constellation Circuit  while you have 3 or more Marks you count one size larger when resisting forced movement (size_steps);
                     a Mark gained at maximum gives one overflow benefit instead (asked; each at most once a round): Temporary
                     HP PB, a 5-foot move without provoking, or + PB on your next Strength or Dexterity save.
Nine-Star Incarnation  state "nine_star_incarnation": unarmed strikes may deal Force or Radiant, once per turn + 4d8 on a hit,
                     once per round after an unarmed hit a Strength save (asked push or pull: 20 feet and Prone, or 5 feet), and a
                     creature of your CL or lower cannot push, pull, knock you Prone or move you against your will.
Every hook returns early for a creature without these rows or states.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.nine_star_meridian_body.feature."
MARKS = "resource:named.celestial_mark"
INCARNATION = "nine_star_incarnation"
GUARD = "condition:typed.ac_against"


def _roles(engine: Any, actor: Any) -> set[str]:
    from .body_modes_scene_resources import available
    if not available(engine, actor, PREFIX + 'constellation_circuit', 14):return set()
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "nine_star"}


def _state(engine: Any, actor: Any) -> bool:
    from .states import active

    from .body_modes_scene_resources import available
    from .body_modes_scene_resources import bundle_of
    held=active(engine,actor,INCARNATION) if actor is not None else None
    return (actor is not None and held is not None and held.source_actor_id==actor.entity_id
            and held.source_definition_id.endswith(PREFIX+'nine_star_incarnation')
            and _owned_bundle(bundle_of(engine,actor),PREFIX+'nine_star_incarnation')
            and available(engine, actor, PREFIX + 'nine_star_incarnation', 18))


def _stamp(engine: Any) -> str:
    from .body_modes_scene_resources import turn_key
    return turn_key(engine)


def _cl(engine: Any, actor: Any) -> int:
    from .body_modes_scene_resources import effective_body_cl
    return effective_body_cl(engine, actor)


def _move(ctx: Any, mover: Any, feet: int, choice_id: str, name: str) -> None:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    paths = routes(ctx.engine, mover, feet, native=True)
    if not paths:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "nine_star_move", mover.entity_id), mover, choice_id, sorted(paths),
                 allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=mover.entity_id,
                 prompt=f"{name}: {mover.display_name} may move up to {feet} feet without provoking Opportunity Attacks.")
    if picked and picked[0] in paths:
        step(ctx.engine, mover, paths[picked[0]], {'choice:needle.star_step':PREFIX+'star_lit_acupoints',
            'choice:needle.orbital_body_move':PREFIX+'orbital_body','choice:needle.constellation_move':PREFIX+'constellation_circuit'}[choice_id], native=True, feet=feet, intent=ctx.intent)


@effect("star_step")
def star_step(ctx: Any, row: dict[str, Any]) -> None:
    _move(ctx, ctx.actor, int(row.get("feet") or 5), "choice:needle.star_step", str(row.get("name") or "Star-Lit Acupoints"))


# ------------------------------------------------------------------------------------- +1 AC against one creature
@effect("ac_against")
def ac_against(ctx: Any, row: dict[str, Any]) -> None:
    """+N AC against attacks made by the triggering target (a condition on you; hit_response turns a hit that would miss)."""
    target = ctx.target
    if target is None:
        return
    for iid, held in list(ctx.actor.conditions.items()):
        if held.condition_id == GUARD and held.source_definition_id == ctx.source:
            ctx.engine._remove_condition_instance(ctx.actor, iid, ctx.source, expected=held)
    ctx.engine._apply_condition(ctx.actor, GUARD, ctx.source, ctx.actor.entity_id, expires_on=str(row.get("expires_on") or "START_OF_SELF_NEXT_TURN"),
                                data={"against": target.entity_id, "amount": int(row.get("amount") or 1),
                                      "label": f"+{int(row.get('amount') or 1)} AC against {target.display_name}"})


@hook("hit_response")
def ac_against_hit(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> tuple[int, bool] | None:
    from .body_modes_scene_resources import available
    if not available(engine,target,PREFIX+'star_lit_acupoints',3):return
    bonus = sum(int((c.data or {}).get("amount") or 0) for c in target.conditions.values()
                if c.condition_id == GUARD and (c.data or {}).get("against") == attacker.entity_id)
    if not bonus or natural == 20 or total >= effective_ac + bonus:
        return None
    return effective_ac + bonus, False


# -------------------------------------------------------------------------------------------------- Orbital Body
@effect("orbital_step")
def orbital_step(ctx: Any, row: dict[str, Any]) -> None:
    """Park the move for after the attack (15 feet replaces 10 when the reduction brought the damage to 0)."""
    other = ctx.target
    if other is None:
        return
    held = dict(ctx.actor.turn_flags.get("_round_orbital_step") or {})
    held.update({"attacker": other.entity_id, "feet": max(int(held.get("feet") or 0), int(row.get("feet") or 10)),
                 "stamp": f"{ctx.engine.state.event_sequence}"})
    ctx.actor.turn_flags["_round_orbital_step"] = held


@hook("attack_resolved")
def orbital_move(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    if target is None:
        return
    held = target.turn_flags.get("_round_orbital_step")
    if not isinstance(held, dict) or held.get("attacker") != ctx.actor.entity_id:
        return
    target.turn_flags.pop("_round_orbital_step", None)
    if target.active:
        from .states import context

        sub = context(ctx.engine, target, PREFIX + "orbital_body", [target], {})
        sub.intent = ctx.intent
        _move(sub, target, int(held.get("feet") or 10), "choice:needle.orbital_body_move", "Orbital Body")


# ----------------------------------------------------------------------------------------- Constellation Circuit
@hook("size_steps")
def steady_constellation(engine: Any, creature: Any, role: str, purposes: Any) -> int | None:
    if role != "resist" or creature is None or "constellation" not in _roles(engine, creature):
        return None
    if int(creature.resources.get(MARKS, 0) or 0) < 3:
        return None
    return 1 if "forced" in purposes else None


def _overflow(engine: Any, actor: Any, intent: Any) -> None:
    key = "_round_pool_overflow:" + MARKS
    pending = int(actor.turn_flags.get(key) or 0)
    if pending <= 0 or "constellation" not in _roles(engine, actor):
        actor.turn_flags.pop(key, None)
        return
    actor.turn_flags.pop(key, None)
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id
    from .states import context

    used = set(str(actor.turn_flags.get("_round_constellation_used") or "").split("|")) if str(actor.turn_flags.get("_round_constellation_round")) == str(engine.state.round_number) else set()
    for _ in range(pending):
        labels = {k: v for k, v in {"temp_hp": f"Gain {_pb(engine,actor)} Temporary Hit Points", "move": "Move 5 feet without provoking",
                                    "save": "+ Proficiency Bonus on your next Strength or Dexterity save"}.items() if k not in used}
        if not labels:
            return
        picked = ask(engine, intent, checkpoint_id(engine, "constellation", actor.entity_id), actor, "choice:needle.constellation_overflow", list(labels),
                     labels=labels, target_id=actor.entity_id, name="Constellation Circuit",
                     prompt="Constellation Circuit: a Celestial Mark at maximum becomes one benefit.")
        choice = picked[0] if picked else next(iter(labels))
        used.add(choice)
        actor.turn_flags["_round_constellation_used"] = "|".join(sorted(used))
        actor.turn_flags["_round_constellation_round"] = str(engine.state.round_number)
        ctx = context(engine, actor, PREFIX + "constellation_circuit", [actor], {"pb": _pb(engine,actor)}).with_source(PREFIX+"constellation_circuit")
        ctx.intent = intent
        if choice == "temp_hp":
            te.run_effects(ctx, [{"type": "temp_hp", "applies_to": "self", "formula": "pb"}])
        elif choice == "move":
            _move(ctx, actor, 5, "choice:needle.constellation_move", "Constellation Circuit")
        else:
            which = ask(engine, intent, checkpoint_id(engine, "constellation_save", actor.entity_id), actor, "choice:needle.constellation_save",
                        ["Strength", "Dexterity"], target_id=actor.entity_id, prompt="Constellation Circuit: your next Strength or Dexterity save?")
            engine._apply_condition(actor, "condition:typed.constellation_save", PREFIX + "constellation_circuit", actor.entity_id,
                                    expires_on="START_OF_SELF_NEXT_TURN",
                                    data={"ability": (which or ["Strength"])[0][:3].upper(), "bonus": _pb(engine,actor),
                                          "label": f"+ Proficiency Bonus on your next {(which or ['Strength'])[0]} save"})


@hook("action_completed")
def overflow_after_action(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:

    _overflow(engine, actor, getattr(engine, "_active_intent", None))


@hook("turn_start_choice")
def overflow_at_turn_start(engine: Any, actor: Any) -> None:

    _overflow(engine, actor, getattr(engine, "_active_intent", None))


@hook("save")
def constellation_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if subject is None:
        return None
    held = next((c for c in subject.conditions.values() if c.source_definition_id==PREFIX+"constellation_circuit" and c.source_actor_id==subject.entity_id and c.condition_id == "condition:typed.constellation_save"
                 and str((c.data or {}).get("ability")) == str(ability).upper()[:3]), None)
    if held is None:
        return None
    subject.conditions.pop(held.instance_id)
    ctx.engine._append_event("CONDITION_REMOVED", PREFIX + "constellation_circuit", actor_id=subject.entity_id, target_ids=(subject.entity_id,),
                             payload={"condition_id": held.condition_id, "instance_id": held.instance_id, "reason": "CONSUMED"})
    return {"bonus": int(held.data.get("bonus") or 0), "modes": []} if "constellation" in _roles(ctx.engine,subject) else None


# ----------------------------------------------------------------------------------------- Nine-Star Incarnation
@hook("attack_damage_types")
def incarnation_types(ctx: Any, attack: Any, kinds: Any) -> list[str] | None:
    # The actual attack determines permission. A natural-weapon ID or another
    # unarmed sibling effect cannot relabel this attack.
    unarmed = attack.get("attack_kind") == "unarmed"
    if not _state(ctx.engine, ctx.actor) or not unarmed:
        return None
    return list(dict.fromkeys([*(str(k).upper() for k in kinds or []), "FORCE", "RADIANT"]))


@hook("after_hit")
def incarnation_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or not target.active or not _state(engine, actor):
        return
    from .. import typed_executor as te

    if actor.turn_flags.get("_round_nine_star_hit") != _stamp(engine):
        from .needle import ask, checkpoint_id
        selected = ask(engine,ctx.intent,checkpoint_id(engine,'nine_star_hit',target.entity_id),actor,
            'choice:needle.nine_star_hit',['force','radiant'],allow_decline=True,
            labels={'force':'Add 4d8 Force damage','radiant':'Add 4d8 Radiant damage'},
            prompt=f'Nine-Star Incarnation: {actor.display_name} hit {target.display_name}. Add 4d8 damage to this hit once this turn, with no extra cost?',target_id=target.entity_id)
        if selected:
            actor.turn_flags["_round_nine_star_hit"] = _stamp(engine)
            te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}).with_source(PREFIX+"nine_star_incarnation"),
                       [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 4, "sides": 8}, "damage_types": [selected[0]],
                         "evidence": "Nine-Star Incarnation: once per turn + 4d8"}])
    if kind != "unarmed" or not target.active or actor.turn_flags.get("_round_nine_star_pull") == int(engine.state.round_number):
        return
    from .needle import ask, checkpoint_id

    picked = ask(engine, ctx.intent, checkpoint_id(engine, "nine_star_pull", target.entity_id), actor, "choice:needle.nine_star_pull", ["away", "toward"],
                 labels={"away": f"Push {target.display_name}", "toward": f"Pull {target.display_name}"}, target_id=target.entity_id, allow_decline=True,
                 name="Nine-Star Incarnation", prompt=f"Nine-Star Incarnation: {target.display_name} makes a Strength save; push or pull it?")
    if not picked:return
    actor.turn_flags["_round_nine_star_pull"] = int(engine.state.round_number)
    direction = picked[0]
    row = next((r for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []) if r.get("block") == "path_rider" and r.get("kind") == "nine_star"), {})
    form_action=next((a for a in engine.action_catalog.values() if a.owner_id==actor.entity_id and (a.parameters.get('typed') or {}).get('source')==PREFIX+'nine_star_incarnation'),None)
    dc = int((((form_action.parameters.get('typed') or {}).get('numbers') or {}).get('save_dc') if form_action else None) or row.get('save_dc') or 10)
    sub = ctx.on_hit_context(target, action=ctx.action, typed={**ctx.typed, 'numbers': {**(ctx.typed.get('numbers') or {}), 'save_dc': dc}}, damage_cache={})
    from .states import active
    held=active(engine,actor,INCARNATION)
    source_cl=int(((held.data or {}).get('numbers') or {}).get('cl') or _cl(engine,actor))
    sub.typed={**sub.typed,'numbers':{**sub.numbers,'source_cl':source_cl}}
    sub=sub.with_source(PREFIX+'nine_star_incarnation')
    te.run_effects(sub, [{"type": "save", "ability": "str", "evidence": "Nine-Star Incarnation: Strength saving throw",
                          "on_fail": [{"type": "forced_movement", "applies_to": "target", "distance_ft": 20, "direction": direction, "nine_star_optional_distance": True},
                                      {"type": "condition", "applies_to": "target", "condition": "prone"}],
                          "on_success": [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": direction}]}])


@hook("forced_movement_reduction")
def anchored(ctx: Any, subject: Any) -> int:
    if subject is None or ctx.actor is subject or not _state(ctx.engine, subject):
        return 0
    return 2**31 if _physical_authority_blocked(ctx, subject) else 0


@hook("condition_attempt")
def anchored_prone(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> bool | None:
    if subject is None or ctx.actor is subject or str((effect_row or {}).get("condition") or "").lower() != "prone" or not _state(ctx.engine, subject):
        return None
    return False if _physical_authority_blocked(ctx, subject, effect_row) else None


@hook('flight')
def constellation_flight(engine: Any, actor: Any) -> dict[str, Any] | None:
    if _state(engine,actor):return {'fly_speed_ft':60,'flight_hover':1}
    if 'constellation' in _roles(engine, actor) and int(actor.resources.get(MARKS, 0)) >= 3:
        return {'fly_speed_ft': 30, 'flight_hover': 1}
    return None


@hook('condition_attempt')
def airborne_constellation(ctx: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    from ..falling import supported
    if (subject is not None and str(row.get('condition', '')).lower() == 'prone'
            and 'constellation' in _roles(ctx.engine, subject)
            and int(subject.resources.get(MARKS, 0)) >= 3 and not supported(ctx.engine, subject)):
        return False
    return None


@effect('nine_star_impact_ground')
def impact_ground(ctx: Any, row: dict[str, Any]) -> None:
    from . import placed
    from ..gate2_runtime_models import Position
    from ..targeting import line_of_effect
    center = ctx.actor.position
    # Only actual supporting surfaces inside the radial volume become broken
    # ground. An aerial impact can strike a nearby floor, never empty sky.
    from collections import defaultdict
    layers=defaultdict(list);radius=int(row['radius_ft']);reach=radius//ctx.engine.grid.square_size_ft
    for z in range(max(0,center.z-reach),center.z+reach+1):
        for x in range(ctx.engine.grid.width):
            for y in range(ctx.engine.grid.height):
                pos=Position(x=x,y=y,z=z)
                if ctx.engine.grid.distance_ft(center,pos)>radius:continue
                if not (z==0 or ctx.engine.grid.roof_supported(pos) or ctx.engine.grid.terrain_at((x,y,z-1),'BLOCKED')):continue
                if not ctx.engine.grid.volume_legal(pos,occupied_cells=set()):continue
                if line_of_effect(ctx.engine,ctx.actor,destination=pos):layers[z].append(pos)
    for cells in layers.values():
        placed.place(ctx.engine, ctx.actor, source=ctx.source, tag='nine_star_rubble', cells=cells,
                     name='Falling-Star Descent rubble: difficult terrain until repaired',shape='painted',
                     difficult='all', duration_rounds=None, numbers=ctx.numbers,
                     extra={'profile':{'repair_seconds':60,'repair_tools':['tianxia.mortal.gear.shovel','tianxia.mortal.tool.mason_s_tools']}})
    if layers:
        from .terrain_repair import ensure_action
        ensure_action(ctx.engine)


@hook('state_event')
def constellation_mark_change(engine: Any, event: Any) -> None:
    if event.event_type not in {'RESOURCE_SPENT', 'RESOURCE_GAINED', 'RESOURCE_EXPIRED'} or event.payload.get('resource_id') != MARKS:
        return
    actor=engine.state.actors.get(event.actor_id)
    if actor is not None and 'constellation' in _roles(engine, actor):
        # A paid activation may spend the Marks that sustain this flight and
        # establish replacement flight later in the same resolution. Defer
        # fall settlement to the activation boundary in that case. The payer
        # can be a reacting creature, so retain its id rather than assuming
        # the action's actor is the one that lost flight.
        if getattr(engine, '_active_intent', None) is not None:
            pending = engine.__dict__.setdefault('_constellation_flight_loss_pending', set())
            pending.add(actor.entity_id)
        else:
            from ..falling import settle
            settle(engine, event.source_definition_id, None)


@hook('resolution_final')
def settle_constellation_flight_loss(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> None:
    """Settle all deferred Mark-flight losses after the current activation."""
    pending = engine.__dict__.pop('_constellation_flight_loss_pending', set())
    if 'constellation' in _roles(engine, actor):
        pending.add(actor.entity_id)
    from ..falling import settle
    if pending:
        settle(engine, action.source_definition_id, intent)


FAMILY = PREFIX.removesuffix('.feature.')
LEVELS = dict(zip((PREFIX+n for n in ('star_lit_acupoints','orbital_body','falling_star_descent','constellation_circuit','nine_star_incarnation')),(3,6,10,14,18)))


def _owned_bundle(bundle,feature):
    return (any(r.get('feature_id')==feature for key in ('typed_passives','typed_reactions') for r in bundle.get(key,())) or
            any(((a.get('parameters') or {}).get('typed') or {}).get('source')==feature for a in bundle.get('action_catalog',())))


@hook('body_mode_profiles')
def nine_profile(bundle):
    if not any(_owned_bundle(bundle,f) for f in LEVELS):return
    limits=[c[0] for a in bundle.get('action_catalog',[]) if ((a.get('parameters') or {}).get('typed') or {}).get('source')==PREFIX+'nine_star_incarnation' for c in a.get('costs',[]) if str(c[0]).startswith('resource:uses.')]
    return [{'source':FAMILY,'name':'Nine-Star Meridian Body','feature_levels':dict(LEVELS),'scene_resources':[MARKS],'scene_limits':limits}]


@hook('match_start',priority=-100)
def scene_initiative(engine):
    from .body_modes_scene_resources import scene_record,set_record,available
    from .subpath_pools import gain
    for actor in engine.state.actors.values():
        record=scene_record(engine,actor,FAMILY)
        if record is None or record.data.get('initiative'):continue
        # Initiative is a scene receipt; suppressed benefits do not earn a second
        # receipt when suppression ends or this combat is rejoined.
        data={**record.data,'initiative':1}
        set_record(engine,actor,FAMILY,data)
        amount=3 if 'constellation' in _roles(engine,actor) else 1
        gain(engine,actor,MARKS,FAMILY,normal=False,count=amount)


@hook('paid_activation_resolved')
def resolved_stamina_mark(engine,actor,receipt):
    from .body_modes_scene_resources import scene_record,available
    from .subpath_pools import gain
    record=scene_record(engine,actor,FAMILY)
    if record is None:return
    from .body_modes_scene_resources import bundle_of,set_record
    bundle=bundle_of(engine,actor)
    from ..combat_world_facts import clock
    context='combat:'+str(engine.state.match_seed)
    clock_tick=int(clock(engine))//6 if 'scene_field_clock' in bundle else None
    token=context+':'+str(engine.state.round_number)
    if record.data.get('mark_round_token')==token:return
    if clock_tick is not None and record.data.get('mark_context')!=context and record.data.get('mark_clock_tick')==clock_tick:return
    source=receipt['source']
    if not (source.startswith('tianxia.path.body_refining.') or source.startswith('tianxia.subpath.body.')):return
    if not available(engine,actor,FAMILY,3,requires_conscious=False):return
    # Net payment and activation identity are supplied by the common producer.
    from .body_modes_scene_resources import qualifying_activation
    if not qualifying_activation(engine,actor,receipt,FAMILY):return
    gain(engine,actor,MARKS,FAMILY)
    if actor.turn_flags.get('_round_pool_gain:'+MARKS)==engine.state.round_number:
        record=scene_record(engine,actor,FAMILY)
        set_record(engine,actor,FAMILY,{**record.data,'mark_round_token':token,'mark_context':context,**({'mark_clock_tick':clock_tick} if clock_tick is not None else {})})
    _overflow(engine,actor,getattr(engine,'_active_intent',None))


@hook('reaction_rows',priority=100)
def orbital_at_packet_only(engine,aid,block,rows):
    if block=='generic':return [r for r in rows if r.get('feature_id')!=PREFIX+'orbital_body']


@hook('damage_response_reduction')
def orbital_packet(engine,target,amount,damage_type,source_id,source_actor_id):
    from .body_modes_scene_resources import available,bundle_of
    from ..save_context import damage_save
    from ..pending_damage import packet_scratch
    from ..typed_reactions import can_use_reaction,open_reaction
    from ..activation_payments import reaction_completed
    from ..gate2_runtime_models import DiceSpec
    from .needle import ask,checkpoint_id
    from .choice_costs import Payment
    feature=PREFIX+'orbital_body'
    row=next((r for r in engine.typed_reaction_rows.get(target.entity_id,()) if r.get('feature_id')==feature),None)
    if row is None or amount<0 or not available(engine,target,feature,6):return
    attack=engine.damage_context()
    hit=attack is not None and (attack.source_id,attack.attacker_id,attack.target_id)==(source_id,source_actor_id,target.entity_id)
    saved=damage_save(engine,target.entity_id,source_id,source_actor_id)
    if not hit and not (saved and saved.ability=='DEX' and saved.failed):return
    other=engine.state.actors.get(source_actor_id)
    if not can_use_reaction(engine,target,other,row) or target.resources.get(MARKS,0)<1:return
    picked=ask(engine,getattr(engine,'_active_intent',None),checkpoint_id(engine,'orbital_packet',target.entity_id),target,
        'choice:needle.orbital_body',['use'],allow_decline=True,labels={'use':'Spend 1 Mark and Reaction'},
        payment=Payment(MARKS,1),feature_id=feature,name='Orbital Body',target_id=target.entity_id,
        prompt=f'Orbital Body: {target.display_name} was hit or failed a Dexterity save. Spend 1 Mark and your Reaction to reduce this damage by 2d8 + Constitution modifier, then move 10 feet without provoking, or 15 feet if this feature reduces the packet to 0?')
    if not picked:return
    engine._spend_resource(target,MARKS,1,feature)
    if not reaction_completed(engine,target,feature):return
    checkpoint=checkpoint_id(engine,'orbital_resolved',target.entity_id)
    open_reaction(engine,row,target,tuple([source_actor_id] if source_actor_id else []),checkpoint)
    from .body_modes_scene_resources import constitution_modifier
    reduction=engine.roller.roll(DiceSpec(count=2,sides=8,modifier=constitution_modifier(engine,target)),actor_id=target.entity_id,reason='DAMAGE_REDUCTION:'+feature)
    engine._record_roll(reduction)
    applied=min(amount,max(0,reduction.total))
    scratch=packet_scratch(engine)
    if scratch is not None:scratch['nine_star_orbital']={'target':target.entity_id,'feet':15 if applied==amount else 10}
    engine._append_event('REACTION_RESOLVED',feature,actor_id=target.entity_id,target_ids=(target.entity_id,),
        payload={'checkpoint':checkpoint,'reduction':applied,'pending_before':amount,'pending_after':amount-applied})
    return applied


@hook('state_event')
def orbital_after_packet(engine,event):
    if event.event_type!='DAMAGE_COMMITTED':return
    from ..pending_damage import packet_scratch
    scratch=packet_scratch(engine) or {}
    pending=scratch.pop('nine_star_orbital',None)
    if not pending or pending['target'] not in event.target_ids:return
    actor=engine.state.actors[pending['target']]
    from .body_modes_scene_resources import available
    # Orbital Body has no above-zero HP prerequisite. The shared authority and
    # consciousness gate handles ordinary incapacity and explicit exceptions.
    if available(engine,actor,PREFIX+'orbital_body',6):
        from .states import context
        ctx=context(engine,actor,PREFIX+'orbital_body',[actor],{})
        ctx.intent=getattr(engine,'_active_intent',None)
        _move(ctx,actor,pending['feet'],'choice:needle.orbital_body_move','Orbital Body')


def _physical_authority_blocked(ctx,subject,effect=None):
    typed={**(ctx.typed or {}),**((ctx.typed or {}).get('_movement_effect') or {}),**(effect or {})}
    tags=set(typed.get('source_tags') or ())
    if typed.get('ignores_gravity') or typed.get('ignores_bodily_anchoring') or tags & {'ignores_gravity','ignores_bodily_anchoring','teleportation','spatial_displacement'}:return False
    source_cl=ctx.numbers.get('source_cl',ctx.numbers.get('cl'))
    return type(source_cl) is int and source_cl>0 and source_cl<=_cl(ctx.engine,subject)


@hook('damage_defenses')
def incarnation_resistance(engine,target,damage_type,typed,source_actor_id):
    if _state(engine,target) and str(damage_type).upper() not in ('PSYCHIC','VOID'):
        return [{'kind':'resistance','damage_types':[str(damage_type).upper()],'feature_id':PREFIX+'nine_star_incarnation'}]


@hook('zones')
def incarnation_gravity(engine):
    """The retained form owns its moving aura, including after journey reload."""
    from ..gate2_runtime_models import Position,ZoneState
    result=[]
    for owner in engine.state.actors.values():
        if owner.position is None or not _state(engine,owner):continue
        cells=tuple(Position(x=x,y=y,z=z) for z in range(max(0,owner.position.z-2),owner.position.z+3)
                    for x in range(engine.grid.width) for y in range(engine.grid.height)
                    if engine.grid.distance_ft(owner.position,Position(x=x,y=y,z=z))<=10)
        result.append(ZoneState(zone_id='zone:aura:nine_star:'+owner.entity_id,source_definition_id=PREFIX+'nine_star_incarnation',
            owner_id=owner.entity_id,center=owner.position,radius_cells=2,affected_cells=cells,
            concentration_link=False,duration_rounds=None,created_round=0,
            trigger_profile={'kind':'TYPED','name':'Nine-Star Incarnation: hostile creatures move through difficult terrain within 10 feet',
                'difficult':'hostile','shape':'emanation','size_ft':10,'follows_owner':True,'aura':True,
                'terrain':[],'triggers':[],'inside':[],'visual':{'material':'stars'}}))
    return result or None


@hook('compile_actions')
def light_actions(info):
    feature=PREFIX+'star_lit_acupoints'
    if feature not in info['owned_ids']:return
    from .body_modes_scene_resources import setting_action
    return [setting_action(info,feature,'star_light.'+str(value),'Star-Lit Acupoints: '+('Emit Dim Light' if value else 'Suppress Dim Light'),
        {'type':'nine_star_light','value':value},'Once during your turn, with at least 1 Mark, emit or suppress Dim Light within 5 feet. It costs no action or Mark and reveals your space normally.',batch=False) for value in (0,1)]


@hook('candidate_allowed')
def light_allowed(engine,actor,candidate,action):
    if action is None:return
    if not any(e.get('type')=='nine_star_light' for e in (action.parameters.get('typed') or {}).get('effects',())):return
    return actor.resources.get(MARKS,0)>=1 and engine.state.current_actor_id==actor.entity_id and actor.turn_flags.get('_round_nine_star_light')!=_stamp(engine)


@effect('nine_star_light')
def change_light(ctx,row):
    if ctx.actor.resources.get(MARKS,0)<1 or ctx.engine.state.current_actor_id!=ctx.actor.entity_id or ctx.actor.turn_flags.get('_round_nine_star_light')==_stamp(ctx.engine):
        raise ValueError('Star-Lit Acupoints requires at least 1 Mark and one unused light change during your turn.')
    ctx.actor.turn_flags['_round_nine_star_light']=_stamp(ctx.engine)
    ctx.engine._remove_condition(ctx.actor,'condition:typed.nine_star_light',PREFIX+'star_lit_acupoints')
    ctx.engine._apply_condition(ctx.actor,'condition:typed.nine_star_light',PREFIX+'star_lit_acupoints',ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
        data={'visible':int(row['value']),'label':'Star-Lit Acupoints: '+('5-foot Dim Light' if row['value'] else 'light suppressed')})


@hook('light_sources')
def star_light(engine):
    from .body_modes_scene_resources import available
    return [{'level':'dim','radius_ft':5,'position':actor.position.model_dump(mode='json'),
             'holder_id':actor.entity_id}
            for actor in engine.state.actors.values() if actor.position is not None and
            actor.resources.get(MARKS,0)>=1 and available(engine,actor,PREFIX+'star_lit_acupoints',3) and
            any(c.condition_id=='condition:typed.nine_star_light' and c.data.get('visible') for c in actor.conditions.values())]


@hook('state_event')
def settle_mode_flight_changes(engine,event):
    if event.event_type not in ('CONDITION_APPLIED','CONDITION_REMOVED'):return
    condition_id=event.payload.get('condition_id','')
    if condition_id not in ('condition:typed.cultivation_suppression','condition:typed.state.nine_star_incarnation','condition:typed.life_unconscious','condition:typed.unconscious','unconscious'):return
    if not any(nine_profile(b) for b in getattr(engine,'typed_bundle_documents',())):return
    from ..falling import settle
    settle(engine,event.source_definition_id,getattr(engine,'_active_intent',None))


def _journey_form(session,aid):
    import json
    from .body_modes_scene_resources import AUTHORITY,journey_available
    actor=session.state['actors'][aid]
    if not journey_available(session,aid,PREFIX+'nine_star_incarnation',18):return False
    return any(r['kind']=='condition' and json.loads(r['model']).get('condition_id')=='condition:typed.state.nine_star_incarnation'
               for r in actor.get('source_states',{}).get(AUTHORITY,{}).get('effects',[]))


@hook('journey_options')
def journey_incarnation_option(session,aid):
    from .body_modes_scene_resources import AUTHORITY,journey_available
    actor=session.state['actors'][aid]
    if not _owned_bundle(actor['bundle'],PREFIX+'nine_star_incarnation') or not journey_available(session,aid,PREFIX+'nine_star_incarnation',18):return
    profile=nine_profile(actor['bundle'])[0]
    if actor['resources'].get(MARKS,0)<5 or actor['resources'].get('resource:core.stamina',0)<6:return
    if any(actor['resources'].get(r,1)<1 for r in profile.get('scene_limits',[])):return
    return [{'id':'nine_star_incarnation','kind':'nine_star_incarnation','payload':{},
        'label':actor['name']+': Nine-Star Incarnation — spend 6 Stamina and 5 Marks; transform for 1 minute, once this scene.'}]


@hook('journey_command')
def journey_incarnation(session,aid,kind,payload):
    if kind!='nine_star_incarnation':return
    import json
    from ..journey import require
    from .body_modes_scene_resources import AUTHORITY,journey_body_cl
    actor=session.state['actors'][aid]
    require(not payload and journey_incarnation_option(session,aid),'Nine-Star Incarnation is not available or cannot be paid.')
    event_start=len(session.state['events'])
    for resource,amount in (('resource:core.stamina',6),(MARKS,5)):
        actor['resources'][resource]-=amount
        session.emit('RESOURCE_SPENT',aid,source=PREFIX+'nine_star_incarnation',resource_id=resource,amount=amount)
    profile=nine_profile(actor['bundle'])[0]
    balances={}
    for resource in profile.get('scene_limits',[]):
        actor['resources'][resource]=0;balances[resource]=0
    managed=actor.setdefault('source_states',{}).setdefault(AUTHORITY,{})
    record=managed.setdefault('records',{}).get(FAMILY,{})
    record['scene_limits']=balances
    model={'condition_id':'condition:typed.state.nine_star_incarnation','source_definition_id':PREFIX+'nine_star_incarnation',
           'source_actor_id':aid,'data':{'name':INCARNATION,'label':'Nine-Star Incarnation','ends_if_unconscious':True,'numbers':{'cl':journey_body_cl(session,aid)}}}
    managed.setdefault('effects',[])[:]=[r for r in managed.get('effects',[]) if not (r['kind']=='condition' and json.loads(r['model']).get('condition_id')==model['condition_id'])]
    managed['effects'].append({'kind':'condition','model':json.dumps(model,sort_keys=True),'remaining_num':60,'remaining_den':1})
    session.emit('BODY_TRANSFORMATION_STARTED',aid,source=PREFIX+'nine_star_incarnation',duration_seconds=60)
    from .body_modes_scene_resources import complete_journey_activation
    complete_journey_activation(session,aid,PREFIX+'nine_star_incarnation',event_start)
    return True


@hook('journey_properties')
def journey_profile(session,aid):
    actor=session.state['actors'][aid]
    from .body_modes_scene_resources import journey_available
    if _journey_form(session,aid):
        import json
        from fractions import Fraction
        from .body_modes_scene_resources import AUTHORITY
        row=next(r for r in actor.get('source_states',{}).get(AUTHORITY,{}).get('effects',[]) if r['kind']=='condition' and json.loads(r['model']).get('condition_id')=='condition:typed.state.nine_star_incarnation')
        expiry=session.clock()+Fraction(row['remaining_num'],row['remaining_den'])
        return {'fly_speed_ft':60,'flight_hover':1,'expiry_num':expiry.numerator,'expiry_den':expiry.denominator}
    if _owned_bundle(actor['bundle'],PREFIX+'constellation_circuit') and actor['resources'].get(MARKS,0)>=3 and journey_available(session,aid,PREFIX+'constellation_circuit',14):
        return {'fly_speed_ft':30,'flight_hover':1}


@hook('journey_state_changed')
def journey_unconscious_form(session,aid):
    import json
    from .body_modes_scene_resources import AUTHORITY
    actor=session.state['actors'][aid]
    if not actor['incapacitated']:return
    state=actor.get('source_states',{}).get(AUTHORITY,{})
    state['effects']=[r for r in state.get('effects',[]) if not (r['kind']=='condition' and json.loads(r['model']).get('condition_id')=='condition:typed.state.nine_star_incarnation')]


@effect('nine_star_state')
def incarnation_state(ctx,row):
    from dataclasses import replace
    from .states import state
    state(replace(ctx,typed={**ctx.typed,'numbers':{**ctx.numbers,'cl':_cl(ctx.engine,ctx.actor)}}),row)


@hook('forced_movement_distance')
def incarnation_distance(ctx,subject,row,longest):
    if not row.get('nine_star_optional_distance'):return
    from .needle import ask,checkpoint_id
    options=[str(n) for n in range(longest,-1,-ctx.engine.grid.square_size_ft)]
    chosen=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'nine_star_distance',subject.entity_id),ctx.actor,
        'choice:needle.nine_star_distance',options,preferred=[str(longest)],
        labels={n:('No movement' if n=='0' else f'Move {subject.display_name} {n} feet') for n in options},
        prompt=f'Nine-Star Incarnation: choose how far to move {subject.display_name}, up to {longest} feet along the legal push or pull route. Prone still applies on a failed save.',target_id=subject.entity_id)
    return int((chosen or [str(longest)])[0])


@hook('subpath_pool_maximum')
def effective_mark_maximum(engine,actor,resource,maximum):
    from .body_modes_scene_resources import bundle_of
    if resource==MARKS and nine_profile(bundle_of(engine,actor)):
        return _pb(engine,actor)+(3 if 'constellation' in _roles(engine,actor) else 0)


@hook('journey_options')
def light_travel_options(session,aid):
    from .body_modes_scene_resources import AUTHORITY,journey_available
    actor=session.state['actors'][aid]
    record=actor.get('source_states',{}).get(AUTHORITY,{}).get('records',{}).get(FAMILY)
    if record is None or not journey_available(session,aid,PREFIX+'star_lit_acupoints',3) or actor['resources'].get(MARKS,0)<1 or record.get('light_tick')==int(session.clock())//6:return
    return [{'id':'star_light:'+str(value),'kind':'nine_star_light','payload':{'visible':value},
        'label':'Star-Lit Acupoints: '+('emit Dim Light within 5 feet' if value else 'suppress Dim Light')+'; once this six-second turn, without an action or Mark.'} for value in (0,1)]


@hook('journey_command')
def light_travel_change(session,aid,kind,payload):
    if kind!='nine_star_light':return
    import json
    from ..journey import require
    from .body_modes_scene_resources import AUTHORITY
    require(set(payload)=={'visible'} and type(payload['visible']) is int and payload['visible'] in (0,1) and light_travel_options(session,aid),'Choose an available light change with at least 1 Mark.')
    actor=session.state['actors'][aid];managed=actor['source_states'][AUTHORITY]
    managed['records'][FAMILY]['light_tick']=int(session.clock())//6
    condition='condition:typed.nine_star_light'
    effects=managed.setdefault('effects',[])
    effects[:]=[r for r in effects if not (r['kind']=='condition' and json.loads(r['model']).get('condition_id')==condition)]
    effects.append({'kind':'condition','model':json.dumps({'condition_id':condition,'source_definition_id':PREFIX+'star_lit_acupoints','source_actor_id':aid,
        'data':{'visible':payload['visible'],'label':'Star-Lit Acupoints: '+('5-foot Dim Light' if payload['visible'] else 'light suppressed')}})})
    session.emit('CELESTIAL_LIGHT_CHANGED',aid,visible=payload['visible'],radius_ft=5,source=PREFIX+'star_lit_acupoints')
    return True


@hook('journey_paid_activation_resolved')
def journey_stamina_mark(session,aid,receipt):
    from .body_modes_scene_resources import AUTHORITY,journey_available,journey_body_pb,queue_journey_choice
    actor=session.state['actors'][aid]
    record=actor.get('source_states',{}).get(AUTHORITY,{}).get('records',{}).get(FAMILY)
    if record is None or record.get('mark_clock_tick')==receipt['round'] or not journey_available(session,aid,FAMILY,3,requires_conscious=False):return
    if not receipt['source'].startswith(('tianxia.path.body_refining.','tianxia.subpath.body.')):return
    prior=set(record.get('nonhostile_sources',[]))
    if receipt['source'] in prior:return
    record['nonhostile_sources']=sorted(prior|{receipt['source']})
    record['mark_round_token']='elapsed:'+str(receipt['round']);record['mark_clock_tick']=receipt['round'];record['mark_context']='journey'
    maximum=journey_body_pb(session,aid)+(3 if _owned_bundle(actor['bundle'],PREFIX+'constellation_circuit') and journey_available(session,aid,PREFIX+'constellation_circuit',14) else 0)
    if actor['resources'].get(MARKS,0)<maximum:
        actor['resources'][MARKS]+=1
        session.emit('RESOURCE_GAINED',aid,source=FAMILY,resource_id=MARKS,amount=1)

    elif _owned_bundle(actor['bundle'],PREFIX+'constellation_circuit') and journey_available(session,aid,PREFIX+'constellation_circuit',14):
        used=record.get('overflow_used',[]) if record.get('overflow_round')==receipt['round'] else []
        if len(used)<3:queue_journey_choice(session,aid,PREFIX+'constellation_circuit','overflow',{'completion_event':receipt['completion_event']})


def _pb(engine,actor):
    from .body_modes_scene_resources import effective_body_pb
    return effective_body_pb(engine,actor)


@hook('object_damage_admission')
def impact_object_admission(engine,attacker,obj,packets,source,*,area_scope_resolved=False):
    from .ability_source import mechanic_at
    if (mechanic_at(engine,source) or source)!=PREFIX+'falling_star_descent':return
    c=obj.component or {}
    if c.get('world_scale') is True:return False
    bounded_class=(any(c.get(key) is True for key in ('temporary_barrier','vehicle','structure','formation_anchor'))
                   or obj.object_kind=='FORMATION_ANCHOR')
    # Native map object stats explicitly retain artifact=False for ordinary DMG
    # placements. An unknown object lacking classification is never guessed.
    ordinary=obj.unattended and c.get('artifact') is False and not c.get('cultivation_object')
    return bool(bounded_class or ordinary)


@hook('difficult_zone_exempt')
def dormant_legacy_gravity(engine,actor,zone):
    """Old sealed bundles may contain the former persisted aura profile."""
    if zone.source_definition_id.endswith(PREFIX+'nine_star_incarnation'):
        owner=engine.state.actors.get(zone.owner_id)
        if owner is not None and not _state(engine,owner):return True


@hook('body_journey_choice_options')
def outside_overflow_options(session,aid,pending):
    if pending['source']!=PREFIX+'constellation_circuit' or pending['kind']!='overflow':return
    from .body_modes_scene_resources import AUTHORITY
    record=session.state['actors'][aid]['source_states'][AUTHORITY]['records'][FAMILY]
    used=set(record.get('overflow_used',[])) if record.get('overflow_round')==int(session.clock())//6 else set()
    rows=[]
    for choice,label in [('temp_hp','gain Temporary Hit Points equal to Proficiency Bonus'),('save_str','add Proficiency Bonus to the next Strength save before your next turn'),('save_dex','add Proficiency Bonus to the next Dexterity save before your next turn')]:
        if ('save' if choice.startswith('save_') else choice) in used:continue
        rows.append({'id':'overflow:'+choice,'kind':'body_mode_choice','payload':{'choice':choice,'parameters':{}},
            'label':'Constellation Circuit: '+label+'; this earned overflow costs no extra Mark or action.'})
    if 'move' not in used:
        from ..gate2_runtime_models import Position
        actor=session.state['actors'][aid];old=Position.model_validate(actor['position'])
        from .journey_flight import granted_destinations
        for cell in granted_destinations(session,aid,5):
            rows.append({'id':'overflow:move:'+str(cell),'kind':'body_mode_choice','payload':{'choice':'move','parameters':{'destination':cell}},
                'label':f'Constellation Circuit: move to square {cell["x"]},{cell["y"]}, {cell.get("z",0)*5} feet high without provoking; no action, extra Mark or ordinary movement.'})
    if not rows:
        rows.append({'id':'overflow:remain','kind':'body_mode_choice','payload':{'choice':'move','parameters':{'destination':dict(session.state['actors'][aid]['position'])}},
            'label':'Constellation Circuit: no legal 5-foot movement exists; remain in place and consume this round’s movement overflow.'})
    return rows


@hook('body_journey_choice_resolve')
def outside_overflow_resolve(session,aid,pending,choice,parameters):
    if pending['source']!=PREFIX+'constellation_circuit' or pending['kind']!='overflow':return
    import json
    from fractions import Fraction
    from .body_modes_scene_resources import AUTHORITY,journey_health
    from ..journey import require
    offered=outside_overflow_options(session,aid,pending)
    require(any(r['payload']=={'choice':choice,'parameters':parameters} for r in offered),'Choose an available overflow benefit.')
    actor=session.state['actors'][aid];state=actor['source_states'][AUTHORITY];record=state['records'][FAMILY]
    tick=int(session.clock())//6
    used=set(record.get('overflow_used',[])) if record.get('overflow_round')==tick else set()
    used.add('save' if choice.startswith('save_') else choice);record.update(overflow_round=tick,overflow_used=sorted(used))
    from .body_modes_scene_resources import journey_body_pb
    pb=journey_body_pb(session,aid)
    if choice=='temp_hp':
        from .journey_flight import movement_rules
        if any(rule.get('temp_hp_denied') for rule in movement_rules(session,aid)):
            session.emit('TEMP_HP_PREVENTED',aid,source=pending['source'])
        else:
            health=journey_health(session,aid);before=int(health.get('temporary_hp',0))
            health['temporary_hp']=max(before,pb)
            session.emit('TEMP_HP_GRANTED',aid,source=pending['source'],offered=pb,before=before,after=health['temporary_hp'])
    elif choice=='move':
        actor['position']=parameters['destination']
        session.emit('GRANTED_MOVEMENT_COMMITTED',aid,source=pending['source'],destination=actor['position'],cost_ft=0)
    else:
        condition='condition:typed.constellation_save';ability='STR' if choice=='save_str' else 'DEX'
        remaining=Fraction((tick+1)*6)-session.clock()
        state.setdefault('effects',[])[:]=[r for r in state.get('effects',[]) if not (r['kind']=='condition' and json.loads(r['model']).get('condition_id')==condition)]
        state['effects'].append({'kind':'condition','remaining_num':remaining.numerator,'remaining_den':remaining.denominator,
            'model':json.dumps({'condition_id':condition,'source_definition_id':pending['source'],'source_actor_id':aid,
                'data':{'ability':ability,'bonus':pb,'label':'Constellation Circuit: + Proficiency Bonus on next '+ability+' save'}})})
    return True


@hook('compile_action')
def source_owned_terrain_and_gravity(action,info):
    """Disable inferred pre-arrival/scene zones when this source owns the field.

    Falling-Star creates physical ground at its actual arrival. Incarnation's
    moving gravitational field is derived from the timed form. Text inference
    must not create another unrepairable or independently surviving copy.
    """
    typed=action.parameters.get('typed') or {}
    if typed.get('source') not in (PREFIX+'falling_star_descent',PREFIX+'nine_star_incarnation'):return
    updated={k:v for k,v in typed.items() if k!='zone_spec'}
    if typed.get('source')==PREFIX+'falling_star_descent':
        # Ground and object effects belong to the same activation even if its
        # creature damage defeats the final opponent.
        updated['hold_victory_until_resolved']=True
    if updated!=typed:return action.model_copy(update={'parameters':{**action.parameters,'typed':updated}})

"""Hundred-Venom Body (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Hundred-Venom Body (the five features and their Normalized Procedures).
Owned rows: ``{"type": "path_passive", "kind": "hundred_venom", "role": "furnace" | "sovereign" | "poisoned_world" |
"myriad"}``; Venom Furnace itself is a paid unarmed-hit rider (path_riders ``paid_hit``) whose option runs ``venom_furnace``.

Venom Furnace        after an unarmed hit, 1 Stamina, once per turn (asked): + 2d6 Poison (4d6 with Myriad-Venom Immortal; +
                     Proficiency Bonus once after a Swallow the Poison that avoided the poison), then a Constitution save:
                     failure, Poisoned until the start of your next turn (and Sovereign Venoms, below).
Three Sovereign Venoms  on that failed save, one Venom (asked; two different ones with Myriad-Venom), until the end of your next
                     turn: Nerve (no Reactions, Disadvantage on its next attack roll), Blood (2d6 Poison at the start of its next
                     turn, then it ends), Marrow (Speed -15 feet, Disadvantage on its next Strength or Dexterity save, asked).
                     Only one Venom of yours on a creature: a new one replaces every part of the old. Myriad: on a successful
                     save, one Venom until the start of the creature's next turn.
Swallow the Poison   its Reaction (1 Stamina, once per round) answers acid or poison damage (the compiled reduction; a packet it
                     brings to 0 stores the adaptation), a failed save against poison (a d20 rewrite: + Proficiency Bonus; a save
                     turned into a success stores it) or being Poisoned (asked: the condition waits until the end of your next
                     turn and then begins for what is left of its duration, or never if that has run out -- which stores it).
                     The adaptation: your next Venom Furnace before the end of your next turn deals + Proficiency Bonus Poison.
Poisoned Body, Poisoned World  your Body Refining Poison damage ignores Resistance; once per round, after a hostile creature
                     within your unarmed reach damages you (typed damage), Grapples you, or starts its turn Grappling you, you may
                     spend 1 Stamina (asked): its Constitution save, 3d8 Poison and one Venom, or half and no Venom.
Myriad-Venom Immortal  Poison and Poisoned immunity (compiled defense and condition immunity rows); your Body Refining Poison
                     treats Poison Immunity as Resistance and then ignores it; the Venom Furnace changes above.
"Your Body Refining Poison" is the damage these features deal and your unarmed strikes (which Venom Furnace lets deal Poison).
Every hook returns early for a creature without these rows.
"""

from __future__ import annotations

from ..paid_relocation import activation

from contextlib import contextmanager
from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.hundred_venom_body.feature."
VENOMS = PREFIX + "three_sovereign_venoms"
SWALLOW = PREFIX + "swallow_the_poison"
ADAPTED = "condition:typed.venom_adaptation"
VENOM = "condition:typed.sovereign_venom"
BLOOD = "condition:typed.blood_venom"
DELAYED = "condition:typed.swallowed_poison"
CARRIED_POISON = "condition:typed.swallowed_poison_continuation"
STAMINA = "resource:core.stamina"
LABELS = {"nerve": "Nerve Venom: no Reactions and Disadvantage on its next attack roll",
          "blood": "Blood Venom: 2d6 Poison damage at the start of its next turn",
          "marrow": "Marrow Venom: Speed -15 feet and Disadvantage on its next Strength or Dexterity saving throw"}


def _roles(engine: Any, actor: Any, *, passive: bool = False, requires_conscious: bool = True) -> set[str]:
    from .body_modes_scene_resources import available
    levels={'furnace':3,'sovereign':10,'poisoned_world':14,'myriad':18}
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "hundred_venom"
            and ((passive and embodied_venom_traits(engine,actor,"defense",row) is not False)
                 or not passive and available(engine,actor,row['feature_id'],levels[row['role']],requires_conscious=requires_conscious))}


def _pb(actor: Any, engine: Any = None) -> int:
    if engine is not None:
        from .body_modes_scene_resources import effective_body_pb
        return effective_body_pb(engine,actor)
    return int(getattr(actor, 'proficiency_bonus', 0) or 2)


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


# ----------------------------------------------------------------------------------------- Body Refining Poison
@contextmanager
def body_poison(engine: Any, actor: Any, *, source: str, origin: dict | None = None):
    """Scope one exact native Body delivery, including a retained creator.

    Retained origin is produced from the actual acquired actor when its Venom
    is created. This is a read-only damage context; it registers no actor,
    action, command, position, consent or independent activation.
    """
    from .body_modes_scene_resources import effective_body_cl
    previous = engine.__dict__.get("_body_poison")
    origin=origin or {}
    engine.__dict__['_body_poison']={'actor':actor.entity_id,'source':source,
        'roles':list(origin['source_roles'] if 'source_roles' in origin else _roles(engine,actor,requires_conscious=False)),
        'cl':int(origin.get('source_cl') or effective_body_cl(engine,actor)),
        'created_by':origin.get('created_by') or source}
    try:yield
    finally:engine.__dict__['_body_poison']=previous


def packet_source(engine,typed,source_actor_id):
    """Read the exact public delivery identity for uncatalogued Body riders.

    A nested different source cannot inherit the outer Body frame. Speculative
    typed queries naming another source also keep their own identity.
    """
    from .damage_delivery import identity
    source=str((typed or {}).get('source') or '')
    frame=engine.__dict__.get('_body_poison') or {}
    if (frame.get('actor')==source_actor_id and frame.get('source')==identity(engine)
            and source in ('',frame.get('source'))):return frame['source']
    return source


def poison_packet_roles(engine,typed,source_actor_id):
    frame=engine.__dict__.get('_body_poison') or {}
    if (frame.get('actor')==source_actor_id and frame.get('source')==packet_source(engine,typed,source_actor_id)):
        levels={'furnace':3,'sovereign':10,'poisoned_world':14,'myriad':18}
        return {r for r in frame.get('roles',()) if frame['cl']>=levels.get(r,1000)}
    actor=engine.state.actors.get(str(source_actor_id or ''))
    return _roles(engine,actor,requires_conscious=False) if actor is not None else set()


def _body_poison(engine: Any, kind: str, typed: Any, source_actor_id: Any) -> bool:
    if str(kind).upper() != "POISON" or not source_actor_id:
        return False
    source = packet_source(engine,typed,source_actor_id)
    if source.startswith(("tianxia.subpath.body.", "tianxia.path.body_refining.feature.")):
        return True
    # The ordinary unarmed strike's Furnace conversion is a bodily feature.
    # A Sphere technique merely containing an unarmed attack is not one.
    return source in {"unarmed_strike", "body_refining_unarmed_strike", "tianxia.sphere.iron_fist"}


@hook("resistance_ignored")
def poison_ignores_resistance(engine: Any, kind: str, typed: Any, source_actor_id: Any, target: Any = None) -> bool | None:
    if not ({"poisoned_world", "myriad"} & poison_packet_roles(engine,typed,source_actor_id)) or not _body_poison(engine, kind, typed, source_actor_id):
        return None
    return True


@hook("immunity_as_resistance")
def immunity_is_resistance(engine: Any, kind: str, typed: Any, source_actor_id: Any, target: Any) -> bool | None:
    if "myriad" not in poison_packet_roles(engine,typed,source_actor_id) or not _body_poison(engine, kind, typed, source_actor_id):
        return None
    return True


# ------------------------------------------------------------------------------------------------ Venom Furnace
def _context(engine: Any, owner: Any, target: Any, intent: Any, source: str, name: str) -> Any:
    """A Context of ``owner`` against ``target`` whose conditions and damage carry ``source`` (exact removal later)."""
    from .. import typed_executor as te
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    action = ActionDefinition(source_definition_id=source, display_name=name, owner_id=owner.entity_id, economy=EconomyKind.NONE,
                              resolution_kind="TYPED", target_kind="HOSTILE_ENTITY")
    numbers = {"pb": _pb(owner,engine), "cl": int(getattr(owner, "cultivation_level", 0) or 0) or 1}
    row = next((r for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(owner.entity_id, []) if r.get("kind") == "hundred_venom"), {})
    numbers.update({"save_dc": int(row.get("save_dc") or 10), "cl": int(row.get("cl") or numbers["cl"]), "pb": int(row.get("pb") or numbers["pb"])})
    return te.Context(engine, owner, action, intent, {"source":source,"effects": [], "numbers": numbers, "duration": {"kind": "instant"}, "riders": []},
                      [target], target, {})


@effect("venom_furnace")
def venom_furnace(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    roles = _roles(engine, owner)
    bonus = 0
    adapted = next((c for c in owner.conditions.values() if c.condition_id == ADAPTED), None)
    if adapted is not None:
        owner.conditions.pop(adapted.instance_id)
        engine._append_event("CONDITION_REMOVED", adapted.source_definition_id, actor_id=owner.entity_id, target_ids=(owner.entity_id,),
                             payload={"condition_id": ADAPTED, "instance_id": adapted.instance_id, "reason": "CONSUMED"})
        bonus = _pb(owner,engine)
    sub = _context(engine, owner, target, ctx.intent, PREFIX + "venom_furnace", "Venom Furnace")
    with body_poison(engine, owner,source=sub.source):
        te.run_effects(sub, [{"type": "damage", "applies_to": "target", "dice": {"count": 4 if "myriad" in roles else 2, "sides": 6}, "flat": bonus,
                              "damage_types": ["poison"], "evidence": "Venom Furnace"}])
    _furnace_save(sub, roles)


def _furnace_save(sub: Any, roles: set[str]) -> None:
    from .. import typed_executor as te
    target = sub.target
    if not target.active:
        return
    fail: list[dict[str, Any]] = [{"type": "condition", "applies_to": "target", "condition": "poisoned", "expires_on": "START_OF_SOURCE_NEXT_TURN"}]
    success: list[dict[str, Any]] = []
    if "sovereign" in roles:
        fail.append({"type": "sovereign_venom", "count": 2 if "myriad" in roles else 1})
        if "myriad" in roles:
            success.append({"type": "sovereign_venom", "count": 1, "brief": True})
    te.run_effects(sub, [{"type": "save", "ability": "con", "evidence": "Venom Furnace: Constitution saving throw", "on_fail": fail, "on_success": success}])


# --------------------------------------------------------------------------------------------- Sovereign Venoms
def state_markers(target,owner):
    from .benefit_suppression import SUPPRESSED
    from ..gate2_runtime_models import ConditionInstance
    result=[]
    for c in target.conditions.values():
        if c.condition_id==VENOM and c.source_actor_id==owner.entity_id:result.append(c)
        elif c.condition_id==SUPPRESSED and c.data.get('until')=='source_available':
            model=c.data.get('model') or {}
            if model.get('condition_id')==VENOM and model.get('source_definition_id')==VENOMS and model.get('source_actor_id')==owner.entity_id:
                result.append(ConditionInstance.model_validate(model))
    return result


def _clear(engine: Any, owner: Any, target: Any, names: set[str] | None = None) -> None:
    """End selected named states and exactly their associated mechanical rows."""
    markers = [c for c in state_markers(target,owner) if c.source_definition_id == VENOMS
               and (names is None or (c.data or {}).get("venom") in names)]
    condition_ids = {iid for c in markers for iid in (c.data or {}).get("condition_ids", [])}
    condition_ids.update(c.instance_id for c in markers)
    modifier_ids = {mid for c in markers for mid in (c.data or {}).get("modifier_ids", [])}
    from .benefit_suppression import SUPPRESSED,cancel
    for iid,held in list(target.conditions.items()):
        if held.condition_id==SUPPRESSED and held.data.get('until')=='source_available':
            model=held.data.get('model') or {};key=model.get('instance_id') or model.get('modifier_id')
            if model.get('source_definition_id')==VENOMS and model.get('source_actor_id')==owner.entity_id and (names is None or key in condition_ids|modifier_ids):
                cancel(engine,target,'condition:'+iid,VENOMS)
    for iid, held in list(target.conditions.items()):
        if held.source_definition_id == VENOMS and held.source_actor_id == owner.entity_id and (names is None or iid in condition_ids):
            engine._remove_condition_instance(target, iid, VENOMS, expected=held)
    for mid, held in list(target.modifiers.items()):
        if held.source_definition_id == VENOMS and held.source_actor_id == owner.entity_id and (names is None or mid in modifier_ids):
            del target.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", VENOMS, actor_id=owner.entity_id, target_ids=(target.entity_id,),
                                 payload={"modifier_id": mid, "reason": "REPLACED"})


@effect("sovereign_venom")
def sovereign_venom(ctx: Any, row: dict[str, Any]) -> None:
    apply_venoms(ctx.engine, ctx.actor, ctx.target, ctx.intent, int(row.get("count") or 1), brief=bool(row.get("brief")),origin=ctx.source,numbers={**dict(ctx.numbers),**({"activation_roles":ctx.typed["activation_roles"]} if "activation_roles" in ctx.typed else {})})


def apply_venoms(engine: Any, owner: Any, target: Any, intent: Any, count: int, *, brief: bool = False, origin: str = PREFIX+"venom_furnace", numbers: dict | None = None) -> None:
    from .. import typed_executor as te
    from .effect_durations import token
    from .needle import ask, checkpoint_id

    if target is None or not target.active or "sovereign" not in (numbers.get("activation_roles",()) if numbers and "activation_roles" in numbers else _roles(engine, owner)):
        return
    existing = {c.data.get("venom"): c for c in state_markers(target,owner)}
    preserved: set[str] = set()
    myriad = "myriad" in (numbers.get("activation_roles",()) if numbers and "activation_roles" in numbers else _roles(engine, owner))
    if myriad and existing:
        # Reapplication may replace either or both named states. Keeping a
        # state keeps its original clock and unspent rider; it is not renewed.
        modes = ["replace_all", *["keep:" + v for v in sorted(existing)]]
        mode_labels = {"replace_all": "Replace both Sovereign Venoms"}
        mode_labels.update({"keep:" + v: "Keep " + v.title() + " Venom with its remaining duration; replace the other Venom"
                            for v in existing})
        if len(existing) == 1:
            mode_labels["replace_all"] = "Replace the existing Sovereign Venom"
        mode = ask(engine, intent, checkpoint_id(engine, "sovereign_reapply", target.entity_id), owner,
                   "choice:needle.sovereign_reapply", modes, labels=mode_labels,
                   target_id=target.entity_id, name="Three Sovereign Venoms",
                   prompt=f"Three Sovereign Venoms on {target.display_name}: choose which existing Venoms to replace.")
        if mode and mode[0].startswith("keep:"):
            preserved.add(mode[0].split(":", 1)[1])
            count = 1
    options = [v for v in ["blood", "nerve", "marrow"] if v not in preserved]
    picked = ask(engine, intent, checkpoint_id(engine, "sovereign_venom", target.entity_id), owner, "choice:needle.sovereign_venom", options,
                 labels=LABELS, minimum=count, maximum=count, preferred=options[:count], target_id=target.entity_id, name="Three Sovereign Venoms",
                 prompt=f"Three Sovereign Venoms: choose {'one Venom' if count == 1 else f'{count} different Venoms'} for {target.display_name}"
                        f"{' (until the start of its next turn)' if brief else ' (until the end of your next turn)' }.")
    chosen = [o for o in options if o in (picked or options[:count])][:count]
    expires = token("start", target.entity_id, int(target.turns_started) + 1) if brief else token("end", owner.entity_id, int(owner.turns_started) + 1)
    _clear(engine, owner, target, set(existing) - preserved if preserved else None)
    ctx = _context(engine, owner, target, intent, VENOMS, "Three Sovereign Venoms")
    if numbers:
        ctx.typed['numbers'].update({k:v for k,v in numbers.items() if k!='activation_roles'})
        ctx.typed['source_cl_locked']=1
    creator=origin if origin==PREFIX+'poisoned_body_poisoned_world' else VENOMS
    for venom in chosen:
        before_conditions, before_modifiers = set(target.conditions), set(target.modifiers)
        engine._apply_condition(target, VENOM, VENOMS, owner.entity_id, expires_on=expires, data={"venom": venom, "source_cl": int(ctx.numbers["cl"]), "label": LABELS[venom],"created_by":origin,"creator_feature":creator,
                **({"speed_penalty_group":"sovereign_marrow","speed_penalty_ft":15,"speed_penalty_all_modes":True} if venom=="marrow" else {})})
        if venom == "nerve":
            te.run_effects(ctx, [{"type": "reaction_denied", "applies_to": "target", "expires_on": expires},
                                 {"type": "disadvantage", "applies_to": "target", "on": "its next attack roll", "expires_on": expires}])
        elif venom == "blood":
            engine._apply_condition(target, BLOOD, VENOMS, owner.entity_id, expires_on=expires,
                                    data={"label": "Blood Venom: 2d6 Poison at the start of its next turn", "source_cl": int(ctx.numbers["cl"]),
                                          'next_turn_at':int(target.turns_started)+1,'created_by':origin,'creator_feature':creator,
                                          'source_actor_snapshot':owner.model_copy(update={'conditions':{},'modifiers':{},'turn_flags':{},'concentration':None,
                                              'action_ids':(),'reaction_ids':(),'passive_ids':(),'augment_ids':()}).model_dump_json(),
                                          'source_roles':list(numbers['activation_roles']) if numbers and 'activation_roles' in numbers else sorted(_roles(engine,owner,requires_conscious=False)),
                                          'source_numbers':dict(ctx.numbers)})
        elif venom == "marrow":
            ability = ask(engine, intent, checkpoint_id(engine, "marrow_venom", target.entity_id), owner, "choice:needle.marrow_venom", ["Strength", "Dexterity"],
                          target_id=target.entity_id, prompt=f"Marrow Venom: {target.display_name}'s next Strength or Dexterity saving throw has Disadvantage.")
            te.run_effects(ctx, [{"type": "disadvantage", "applies_to": "target", "on": f"its next {(ability or ['Strength'])[0]} saving throw", "expires_on": expires}])
        marker = next(c for iid, c in target.conditions.items()
                      if iid not in before_conditions and c.condition_id == VENOM)
        engine._update_condition_data(target, marker, {**marker.data,
            "condition_ids": [iid for iid in target.conditions if iid not in before_conditions and iid != marker.instance_id],
            "modifier_ids": [mid for mid in target.modifiers if mid not in before_modifiers]}, VENOMS)
    note(engine, VENOMS, owner, f"Three Sovereign Venoms: {', '.join(v.title() for v in chosen)} Venom on {target.display_name}.", (target,))


@hook("turn_resources_refreshed")
def blood_venom(engine: Any, actor: Any) -> None:
    """"At the start of the target's next turn, it takes one 2d6 Poison damage packet, then Blood Venom ends"."""
    from .. import typed_executor as te

    from .benefit_suppression import SUPPRESSED,cancel
    # Refresh runs before TURN_STARTED subscribers. Reconcile the shared Body
    # suppression clock here so a deadline at this exact turn boundary restores
    # Blood before its one-shot packet is consumed.
    from .body_modes_scene_resources import source_clock
    source_clock(engine, actor)
    hidden_blood=[c for c in actor.conditions.values() if c.condition_id==SUPPRESSED
                  and c.data.get('until')=='source_available' and (c.data.get('model') or {}).get('condition_id')==BLOOD]
    for held in hidden_blood:
        original=held.data['model']
        if int(original.get('data',{}).get('next_turn_at',actor.turns_started))>actor.turns_started:continue
        source=original['source_actor_id']
        for marker in list(actor.conditions.values()):
            model=marker.data.get('model') or {}
            if marker.condition_id==SUPPRESSED and marker.data.get('until')=='source_available' and model.get('source_actor_id')==source and (
                    model.get('condition_id')==BLOOD or model.get('condition_id')==VENOM and model.get('data',{}).get('venom')=='blood'):
                cancel(engine,actor,'condition:'+marker.instance_id,VENOMS)
    for held in [c for c in actor.conditions.values() if c.condition_id == BLOOD]:
        owner = engine.state.actors.get(held.source_actor_id)
        if owner is None and held.data.get('source_actor_snapshot'):
            from ..gate2_runtime_models import ActorState
            owner=ActorState.model_validate_json(held.data['source_actor_snapshot'])
            if owner.entity_id!=held.source_actor_id:raise ValueError('The retained Venom creator identity changed.')
        actor.conditions.pop(held.instance_id, None)
        engine._append_event("CONDITION_REMOVED", VENOMS, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": BLOOD, "instance_id": held.instance_id, "reason": "RESOLVED"})
        if owner is None or not actor.active:
            continue
        # Blood resolves once. Its marker is part of the same named state.
        for iid, marker in list(actor.conditions.items()):
            if marker.condition_id == VENOM and marker.source_actor_id == held.source_actor_id and (marker.data or {}).get("venom") == "blood":
                engine._remove_condition_instance(actor, iid, VENOMS, expected=marker)
        sub = _context(engine, owner, actor, _intent(engine), VENOMS, "Blood Venom")
        sub.typed["numbers"]["cl"] = int((held.data or {}).get("source_cl") or sub.numbers["cl"])
        sub.typed['source_cl_locked']=1
        if held.data.get('source_numbers'):sub.typed['numbers'].update(held.data['source_numbers'])
        with body_poison(engine, owner,source=sub.source,origin=held.data):
            te.run_effects(sub, [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 6}, "damage_types": ["poison"], "evidence": "Blood Venom"}])


# ------------------------------------------------------------------------------------------- Swallow the Poison
def _adapt(engine: Any, owner: Any, *, source_cl: int | None = None, origin: str = "", origin_actor: str = "") -> None:
    """The stored adaptation: the next Venom Furnace before the end of the owner's next turn deals + Proficiency Bonus Poison."""
    from .effect_durations import token

    for iid, held in list(owner.conditions.items()):
        if held.condition_id == ADAPTED:
            engine._remove_condition_instance(owner, iid, SWALLOW, expected=held)
    from .body_modes_scene_resources import effective_body_cl
    engine._apply_condition(owner, ADAPTED, SWALLOW, owner.entity_id, expires_on=token("end", owner.entity_id, int(owner.turns_started) + 1),
                            data={"label": "Swallow the Poison: next Venom Furnace + Proficiency Bonus Poison",
                                  "source_cl":source_cl if source_cl is not None else effective_body_cl(engine,owner),
                                  "uses":1,"bonus":"proficiency_bonus","eligible_activation":PREFIX+"venom_furnace",
                                  "originating_source":origin,"originating_actor":origin_actor,"acquisition_round":int(engine.state.round_number)})


@effect("venom_adaptation")
def venom_adaptation(ctx: Any, row: dict[str, Any]) -> None:
    # Acid is eligible for reduction, but only zero matching Poison stores
    # adaptation. The shared reduction dispatcher still owns the actual roll.
    if str(getattr(ctx.engine, "_typed_pending_damage_type", "")).upper() != "POISON":
        return
    from ..pending_damage import current
    packet = current(ctx.engine)
    source = ctx.engine.state.actors.get(packet.source_actor_id) if packet is not None else None
    delivery = ctx.engine.action_catalog.get(packet.source_id) if packet is not None else None
    typed = ((delivery.parameters or {}).get('typed') or {}) if delivery is not None else {'source':packet.source_id} if packet is not None else {}
    source_id=packet.source_actor_id if packet is not None else None
    if ("myriad" in poison_packet_roles(ctx.engine,typed,source_id)
            and _body_poison(ctx.engine,"POISON",typed,source_id)):
        # Swallow can defend against the packet, but its rule does not name
        # Myriad's explicit exception permitting beneficial hostile intake.
        return
    _adapt(ctx.engine, ctx.actor,origin=packet.source_id if packet else "",origin_actor=packet.source_actor_id or "" if packet else "")


def _swallow_key() -> str:
    return "once_per_round:typed." + SWALLOW  # the Reaction row's own once-per-round key (typed_reactions._once_key)


def _swallow_ready(engine: Any, owner: Any) -> bool:
    from ..typed_executor import condition_rules

    from .body_modes_scene_resources import available
    return (available(engine,owner,SWALLOW,6) and any(r.get("feature_id") == SWALLOW for r in (getattr(engine, "typed_reaction_rows", {}) or {}).get(owner.entity_id, []))
            and owner.turn_flags.get(_swallow_key()) != int(engine.state.round_number) and int(owner.resources.get(STAMINA, 0) or 0) >= 1
            and owner.active and owner.reaction_available and not any(rule.get("no_reactions") for rule in condition_rules(owner)))


def _swallow_guard(engine: Any, holder: Any, rctx: Any) -> bool:
    named = set(rctx.named or ())
    return (rctx.roller is holder.actor and bool(named & {"poisoned", "category:poison", "category:disease", "category:ordinary_disease"}) and rctx.dc is not None
            and _swallow_ready(engine, holder.actor))


def _swallow_used(engine: Any, holder: Any, rctx: Any) -> None:
    holder.actor.turn_flags[_swallow_key()] = int(engine.state.round_number)


def _swallow_after(engine: Any, holder: Any, rctx: Any, new: Any) -> None:
    if rctx.dc is not None and int(new.total) >= int(rctx.dc):
        _adapt(engine, holder.actor,origin=rctx.source_id or "",origin_actor=getattr(rctx.source_actor,"entity_id","") or "")


def _register_swallow() -> None:
    from .d20_rewrite import Rule, register, row_holders

    register(Rule("swallow_the_poison_save", "Swallow the Poison (+ Proficiency Bonus to a failed save against poison or disease)", feature=SWALLOW,
                  rolls=("save",), who="self", when="failed", op="choose", reaction=True, costs=((("stamina", 1),),), checkpoint="D20_REROLL_SAVE",
                  finder=row_holders("swallow_the_poison_save", SWALLOW), guard=_swallow_guard,
                  ai=lambda engine, holder, rctx: rctx.dc is not None and rctx.total + _pb(holder.actor,engine) >= int(rctx.dc),
                  on_use=_swallow_used, after=_swallow_after,
                  choose=lambda engine, holder, rctx: rctx.natural, bonus=lambda engine, holder, rctx: _pb(holder.actor,engine),
                  say=lambda engine, holder, rctx, new: f"Swallow the Poison: {holder.actor.display_name} adds its Proficiency Bonus to the save."))


_register_swallow()


@hook("condition_attempt")
def delay_poisoned(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> bool | None:
    """"Delay Poisoned until the end of your next turn" (the Reaction, asked)."""
    if subject is None or str((effect_row or {}).get("condition") or "").lower() != "poisoned" or not _swallow_ready(ctx.engine, subject):
        return None
    from .. import typed_executor as te

    if te.condition_immune(ctx.engine, subject, "poisoned"):
        return None
    from .effect_durations import token
    from .needle import ask, checkpoint_id

    engine = ctx.engine
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "swallow_delay", subject.entity_id), subject, "choice:needle.swallow_the_poison_delay", ["delay"],
                 labels={"delay": "Delay Poisoned until the end of your next turn (Reaction, 1 Stamina)"}, allow_decline=True, target_id=subject.entity_id,
                 name="Swallow the Poison", prompt=f"Swallow the Poison: {ctx.action.display_name} would Poison {subject.display_name}.")
    if not picked:
        return None
    original = te.effect_expiry(ctx, effect_row, subject, condition=True) or "UNTIL_REMOVED"
    # Capture an absolute turn token now: the engine-native names are only
    # meaningful at their own boundary and cannot be compared later at onset.
    if original == "START_OF_SOURCE_NEXT_TURN":
        original = token("start", ctx.actor.entity_id, int(ctx.actor.turns_started) + 1)
    elif original == "END_OF_HOLDER_NEXT_TURN":
        original = token("end", subject.entity_id, int(subject.turns_started) + 1)
    elif original == "END_OF_CURRENT_TURN":
        current=engine.state.actors[engine.state.current_actor_id]
        original=token("end",current.entity_id,int(current.turns_started))
    condition_data = te.condition_save_data(ctx, effect_row)
    if isinstance(effect_row.get("condition_label"), str):
        condition_data["label"] = effect_row["condition_label"]
    from .. import typed_reactions

    from .body_modes_scene_resources import effective_body_cl
    with activation(engine, subject, SWALLOW):
        typed_reactions._open(engine, {"feature_id": SWALLOW}, subject, (ctx.actor.entity_id,), "CONDITION_PENDING")
        subject.reaction_available = False
        subject.turn_flags[_swallow_key()] = int(engine.state.round_number)
        engine._spend_resource(subject, STAMINA, 1, SWALLOW)
        engine._apply_condition(subject, DELAYED, SWALLOW, ctx.actor.entity_id, expires_on=token("end", subject.entity_id, int(subject.turns_started) + 1),
                                data={"label": "Swallow the Poison: Poisoned is delayed", "expires_on": original, "source": ctx.source,
                                      "condition_data": condition_data,"source_cl":effective_body_cl(engine,subject)})
        note(engine, SWALLOW, subject, f"Swallow the Poison: {subject.display_name} holds the poison until the end of its next turn.", (ctx.actor,))
        return False


@hook("effect_expiring")
def delayed_poison_begins(engine: Any, holder: Any, row: Any) -> None:
    if getattr(row, "condition_id", None) != DELAYED or row.source_definition_id!=SWALLOW:
        return
    from .effect_durations import due

    original = str((row.data or {}).get("expires_on") or "UNTIL_REMOVED")
    if due(engine, original):
        _adapt(engine, holder,source_cl=row.data.get("source_cl"),origin=str(row.data.get("source") or ""),origin_actor=row.source_actor_id or "")  # its source ran out during the delay: the poison never began
        return
    # Old saved delays have no condition_data: retain their label-only behavior.
    # New delays restore only the captured data, even if the caster or its DC changed.
    from copy import deepcopy

    data = deepcopy((row.data or {}).get("condition_data") or {})
    data.setdefault("label", "Poisoned (delayed by Swallow the Poison)")
    before=set(holder.conditions)
    engine._apply_condition(holder, "condition:typed.poisoned", str((row.data or {}).get("source") or SWALLOW), row.source_actor_id,
                            expires_on=original, data=data)
    # Preserve the original condition's exact metadata. Native journey
    # continuation uses a separate source-owned record, never an extra key on
    # an unrelated caster's condition or a legacy saved delay.
    if any(iid not in before and c.condition_id=='condition:typed.poisoned' for iid,c in holder.conditions.items()) and any(b.get('journey_setup') is not None and b.get('actor_id')==holder.entity_id
           for b in engine.typed_bundle_documents):
        engine._apply_condition(holder,CARRIED_POISON,SWALLOW,holder.entity_id,expires_on=original,
            data={'label':'Poisoned continued after Swallow the Poison',
                  'source':str((row.data or {}).get('source') or SWALLOW),'source_actor':row.source_actor_id})


@hook('turn_start')
def expired_poison_source_at_start(engine,actor):
    settle_expired_poison_sources(engine)


@hook('turn_end')
def expired_poison_source_at_end(engine,actor):
    settle_expired_poison_sources(engine,ending_id=actor.entity_id)


def settle_expired_poison_sources(engine,*,ending_id=None):
    """Prevent onset and store adaptation at the actual source expiry boundary."""
    from .effect_durations import due
    for holder in engine.state.actors.values():
        for held in list(holder.conditions.values()):
            if held.condition_id==DELAYED and held.source_definition_id==SWALLOW and due(engine,held.data.get('expires_on'),ending_id):
                if engine._remove_condition_instance(holder,held.instance_id,SWALLOW,expected=held):
                    _adapt(engine,holder,source_cl=held.data.get('source_cl'),origin=str(held.data.get("source") or ""),origin_actor=held.source_actor_id or "")


# ------------------------------------------------------------------------------ Poisoned Body, Poisoned World
def _retaliate(engine: Any, owner: Any, other: Any, intent: Any, why: str) -> None:
    from .. import typed_executor as te
    from ..typed_reactions import attack_reaches
    from .needle import ask, checkpoint_id

    from ..relations import relation, ENEMY
    from ..stealth import sees

    if (not owner.active or other is None or not other.active or relation(engine, owner, other) != ENEMY
            or "poisoned_world" not in _roles(engine, owner)):
        return
    # Actual contact identifies a maintained grappler; otherwise consult the
    # owner's native senses rather than granting AI omniscient targeting.
    contact = any(c.condition_id.endswith(".grappled") and c.source_actor_id == other.entity_id
                  for c in owner.conditions.values())
    if not contact and not sees(engine, owner, other):
        return
    if owner.turn_flags.get("_round_poisoned_world") == int(engine.state.round_number) or int(owner.resources.get(STAMINA, 0) or 0) < 1:
        return
    if not attack_reaches(engine, owner, other, {"attack_kind": "unarmed"}):
        return
    picked = ask(engine, intent, checkpoint_id(engine, "poisoned_world", other.entity_id), owner, "choice:needle.poisoned_body_poisoned_world", ["use"],
                 labels={"use": f"Spend 1 Stamina: {other.display_name} makes a Constitution save (3d8 Poison and a Venom)"}, allow_decline=True,
                 target_id=other.entity_id, name="Poisoned Body, Poisoned World", prompt=f"Poisoned Body, Poisoned World: {why}.")
    if not picked:
        return
    with activation(engine, owner, PREFIX + "poisoned_body_poisoned_world"):
        owner.turn_flags["_round_poisoned_world"] = int(engine.state.round_number)
        engine._spend_resource(owner, STAMINA, 1, PREFIX + "poisoned_body_poisoned_world")
        sub = _context(engine, owner, other, intent, PREFIX + "poisoned_body_poisoned_world", "Poisoned Body, Poisoned World")
        with body_poison(engine, owner,source=sub.source):
            te.run_effects(sub, [{"type": "save", "ability": "con", "evidence": "Poisoned Body, Poisoned World: Constitution saving throw",
                                  "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "damage_types": ["poison"]},
                                              {"type": "sovereign_venom", "count": 1}],
                                  "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": ["poison"]}]}])


@hook("event", nested=True)
def poisoned_world_damaged(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Native and typed committed packets share one post-damage caller.

    Exclude retaliation by its actual source, never by its displayed name or
    damage type. A child copy therefore cannot cause a retaliation chain.
    """
    frame=engine.__dict__.get('_body_poison') or {}
    world_origin=(frame.get('created_by')==PREFIX+'poisoned_body_poisoned_world' and frame.get('source')==kwargs.get('source_definition_id') and frame.get('actor')==kwargs.get('actor_id'))
    if event_type != "DAMAGE_COMMITTED" or kwargs.get("source_definition_id") == PREFIX + "poisoned_body_poisoned_world" or world_origin:
        return
    payload = kwargs.get("payload") or {}
    if int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) <= 0:
        return
    other = engine.state.actors.get(kwargs.get("actor_id"))
    for aid in kwargs.get("target_ids") or ():
        owner = engine.state.actors.get(aid)
        if owner is not None and owner is not other and "poisoned_world" in _roles(engine, owner):
            _retaliate(engine, owner, other, _intent(engine), f"{other.display_name} damaged {owner.display_name}" if other else "hostile damage")


@hook("event", nested=True)
def poisoned_world_grappled(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Both native and typed Grapples publish the same committed state event."""
    if event_type != "CONDITION_APPLIED" or (kwargs.get("payload") or {}).get("condition_id") not in {
            "condition:typed.grappled", "condition:core.grappled"}:
        return
    other = engine.state.actors.get(kwargs.get("actor_id"))
    for aid in kwargs.get("target_ids") or ():
        owner = engine.state.actors.get(aid)
        if owner is not None and owner is not other and other is not None:
            _retaliate(engine, owner, other, _intent(engine), f"{other.display_name} Grappled {owner.display_name}")


@hook("turn_start_choice")
def poisoned_world_grappler(engine: Any, actor: Any) -> None:
    for owner in list(engine.state.actors.values()):
        if owner is actor or not _roles(engine, owner):
            continue
        if any(c.condition_id.endswith(".grappled") and c.source_actor_id == actor.entity_id for c in owner.conditions.values()):
            _retaliate(engine, owner, actor, _intent(engine), f"{actor.display_name} starts its turn Grappling {owner.display_name}")


@hook("row_allowed")
def swallow_source_allowed(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    """Retaliation is expressly not hostile poison intake for Swallow."""
    if row.get("feature_id") != SWALLOW:
        return None
    from .body_modes_scene_resources import available
    if not available(engine,actor,SWALLOW,6):return False
    from .damage_delivery import identity
    frame=engine.__dict__.get('_body_poison') or {}
    return False if identity(engine) == PREFIX + "poisoned_body_poisoned_world" or (frame.get('created_by')==PREFIX+'poisoned_body_poisoned_world' and frame.get('source')==identity(engine)) else None


@hook("save_roll_tags")
def poison_save_tags(ctx: Any, subject: Any, ability: str, named: frozenset[str]) -> list[str] | None:
    """Carry only explicit source categories into this owner's rewrite prompt."""
    if not _swallow_ready(ctx.engine, subject):
        return None
    return sorted(named & {"category:poison", "category:disease", "category:ordinary_disease"})


@hook("effect_subject_allowed")
def ordinary_disease_immunity(ctx: Any, row: dict[str, Any], subject: Any) -> bool | None:
    """Only a source's explicit ordinary-disease category invokes immunity.

    Neither a toxic name nor a disease-only category supplies ordinary status.
    Higher authority categories take precedence over ordinary classification.
    """
    if "myriad" not in _roles(ctx.engine, subject,passive=True):
        return None
    categories = set(row.get("save_categories") or row.get("source_categories") or ())
    if "ordinary_disease" in categories and not categories & {"tribulation", "curse", "foundation", "secret", "conceptual", "higher_authority"}:
        return False
    return None


@hook("condition_applied")
def furnace_poison_refresh(ctx: Any, name: str, subject: Any) -> None:
    """Refresh one caster's Poisoned instance; preserve unrelated poison."""
    if ctx.source != PREFIX + "venom_furnace" or name != "poisoned" or subject is None:
        return
    held = sorted((c for c in subject.conditions.values()
                   if c.condition_id == "condition:typed.poisoned" and c.source_actor_id == ctx.actor.entity_id
                   and c.source_definition_id == ctx.source), key=lambda c: c.applied_sequence)
    for previous in held[:-1]:
        ctx.engine._remove_condition_instance(subject, previous.instance_id, ctx.source, expected=previous)
    if held:
        ctx.engine._update_condition_data(subject, held[-1], {**held[-1].data, "source_cl": int(ctx.numbers["cl"])}, ctx.source)


@hook("attack_damage_type_choice")
def furnace_unarmed_type(ctx: Any, attack: dict, target: Any, kinds: list[str], index: int) -> str | None:
    if (attack.get("attack_kind") != "unarmed" or "furnace" not in _roles(ctx.engine, ctx.actor) or "POISON" not in kinds
            or (ctx.typed.get('weapon') or {}).get('natural_source')=='tianxia.sphere.iron_fist'):
        return None
    from .needle import ask, checkpoint_id
    ordinary = [str(k).upper() for k in kinds if str(k).upper() != "POISON"]
    choices = [*ordinary, "POISON"]
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine,"furnace_type",target.entity_id,index),ctx.actor,
        "choice:needle.venom_furnace_type",choices,
        labels={k:("Replace every ordinary damage type of this unarmed strike with Poison" if k == "POISON"
                   else "Deal the unarmed strike's ordinary " + k.title() + " damage") for k in choices},
        preferred=choices[:1],target_id=target.entity_id,name="Venom Furnace",
        prompt=f"Venom Furnace: {ctx.actor.display_name}'s unarmed strike against {target.display_name}: choose its damage type (no Stamina cost).")
    return chosen[0] if chosen else choices[0]



@hook("damage_packet_selection")
def furnace_confirmed_hit(ctx: Any, target: Any, packet_kinds: tuple[str, ...]) -> None:
    """Declare on the confirmed hit, before its primary damage commits.

    Reuses the shared paid-hit stamp so the historical after-hit dispatcher
    cannot charge/deliver this same use a second time. A transient record binds
    the later save to this immutable attack roll, never to recent event names.
    """
    provenance = ctx.attack_damage_context
    spec = ctx.attack_defense_spec
    if (provenance is None or provenance.kind != "unarmed" or spec is None
            or "furnace" not in _roles(ctx.engine, ctx.actor)):
        return
    owner, engine = ctx.actor, ctx.engine
    source = PREFIX + "venom_furnace"
    flag = "condition:typed.path_hit_limit." + source
    from .body_modes_scene_resources import turn_key
    stamp = turn_key(engine)
    from .path_riders import claim_paid_hit
    claim_paid_hit(ctx, source)
    legacy=f"{engine.state.round_number}:{engine.state.current_actor_id}"
    started=int(stamp.rsplit(':',1)[-1])
    if any(c.condition_id == flag and (c.data.get('stamp')==stamp or c.data.get('stamp')==legacy and c.applied_sequence>=started)
           for c in owner.conditions.values()) or owner.resources.get(STAMINA,0) < 1:
        return
    from .needle import ask, checkpoint_id
    picked = ask(engine, ctx.intent, checkpoint_id(engine,"path_hit",source,target.entity_id),owner,
        "choice:needle.path_hit."+source,["Use Venom Furnace"],allow_decline=True,target_id=target.entity_id,
        name="Venom Furnace",prompt=f"Venom Furnace: {owner.display_name}'s unarmed strike hit {target.display_name}. Spend 1 Stamina for {4 if 'myriad' in _roles(engine,owner) else 2}d6 extra Poison damage, then a Constitution save (failure: Poisoned until your next turn starts)?")
    if not picked:
        return
    roles=_roles(engine,owner)
    sub = _context(engine,owner,target,ctx.intent,source,"Venom Furnace")
    captured=dict(sub.numbers)
    engine._spend_resource(owner,STAMINA,1,source)
    engine._remove_condition(owner,flag,source)
    engine._apply_condition(owner,flag,source,owner.entity_id,expires_on="UNTIL_REMOVED",data={"stamp":stamp,"label":"Venom Furnace: used this turn"})
    bonus = 0
    adapted = next((c for c in owner.conditions.values() if c.condition_id == ADAPTED),None)
    if adapted:
        engine._remove_condition_instance(owner,adapted.instance_id,SWALLOW,expected=adapted)
        bonus = _pb(owner,engine)
    from ..gate2_runtime_models import DiceSpec
    dice = DiceSpec(count=4 if "myriad" in roles else 2,sides=6,modifier=bonus)
    roll = engine.roller.roll(dice,actor_id=owner.entity_id,reason="DAMAGE:"+source,critical=False)
    engine._record_roll(roll)
    engine._append_event("DAMAGE_ROLLED",source,actor_id=owner.entity_id,target_ids=(target.entity_id,),
        payload={**roll.model_dump(mode="json"),"critical":False,"attack_roll_id":provenance.roll_id})
    combined = (str(spec.get("damage_type") or "").upper() == "POISON"
                and (not ({"poisoned_world","myriad"} & roles)
                     or _body_poison(engine,"POISON",ctx.typed,owner.entity_id)))
    if combined:
        spec["damage"] = spec["damage"].model_copy(update={"modifier":spec["damage"].modifier+roll.total})
    from ..paid_relocation import preserve_pending
    preserve_pending(engine,"_hundred_venom_hits")
    engine.__dict__.setdefault("_hundred_venom_hits",{})[provenance.roll_id] = {
        "bonus":roll.total,"combined":combined,"roles":sorted(roles),"cl":captured["cl"],"pb":captured["pb"],"save_dc":captured["save_dc"]}


@hook("attack_damage_final")
def furnace_after_hit_damage(engine: Any, owner: Any, target: Any, provenance: Any, intent: Any) -> None:
    pending = engine.__dict__.get("_hundred_venom_hits",{}).pop(provenance.roll_id,None)
    if pending is None:
        return
    from dataclasses import replace
    from .. import typed_executor as te
    target = engine.state.actors.get(provenance.target_id, target)
    sub = _context(engine,owner,target,intent,PREFIX+"venom_furnace","Venom Furnace")
    sub.typed["numbers"].update({k:pending[k] for k in ("cl","pb","save_dc")})
    sub.typed['source_cl_locked']=1
    sub = replace(sub,attack_damage_context=replace(provenance,source_id=PREFIX+"venom_furnace",critical=False,component="attached"),
                  critical_hit=False,continue_after_defeat=True)
    if not pending["combined"]:
        with body_poison(engine,owner,source=sub.source,origin={"source_roles":pending["roles"],"source_cl":pending["cl"]}):
            te.run_effects(sub,[{"type":"damage","applies_to":"target","flat":pending["bonus"],"damage_types":["poison"]}])
    sub.typed["activation_roles"]=pending["roles"]
    _furnace_save(sub,set(pending["roles"]))


@hook('cultivation_effect_binding')
def venom_creator_binding(engine,holder,item):
    if item.source_definition_id!=VENOMS:return None
    owner=engine.state.actors.get(item.source_actor_id)
    if owner is None:return None
    key=getattr(item,'instance_id',None) or getattr(item,'modifier_id',None)
    marker=next((c for c in state_markers(holder,owner) if c.instance_id==key or key in c.data.get('condition_ids',()) or key in c.data.get('modifier_ids',())),None)
    creator=(marker.data if marker else getattr(item,'data',{})).get('creator_feature')
    return {'feature':creator} if creator in (VENOMS,PREFIX+'poisoned_body_poisoned_world') else None


@hook('cultivation_row_available')
def embodied_venom_traits(engine,actor,block,row):
    if block=='defense' and row.get('feature_id') in (PREFIX+'venom_furnace',PREFIX+'myriad_venom_immortal'):
        from .body_modes_scene_resources import SUPPRESSION
        if any(c.condition_id==SUPPRESSION and c.data.get('disable_embodied_traits')==1
               and (c.data.get('feature_id')==row['feature_id'] or c.data.get('system') in ('body','all','tianxia.path.body_refining'))
               for c in actor.conditions.values()):return False
        # Printed bodily Resistance/Immunity and save protection remain
        # embodied durability. This grants no unavailable activation or type.
        return True

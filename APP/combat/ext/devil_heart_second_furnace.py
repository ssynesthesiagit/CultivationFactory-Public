"""Second Furnace activation consumers; common native state is furnace_runtime.

Overdraw is an explicit alternative payment quoted before affordability. Promised
Corruption and Devil Qi settle only after the activation; anti-daemonic interruption
retains already paid Qi and invokes the printed immediate unreduced payment.
Augment is once per turn and activation, and uses actual added-damage receipts.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

DEMON_SEED_OVERDRAW = "tianxia.subpath.qi.devil_heart_second_furnace.feature.demon_seed_overdraw"
QI = "resource:core.qi"
CORRUPTION = "resource:named.corruption"
DEVIL_QI = "resource:named.devil_qi"
DEVIL_QI_AUGMENT = "tianxia.subpath.qi.devil_heart_second_furnace.feature.devil_qi_augment"
CHOICE = "condition:typed.demon_seed_overdraw_choice"
USED_AUGMENT = "typed_once_turn:devil_qi_augment"
RIDER_NAMES = {"damage": "extra damage", "no_reactions": "no Reactions", "push": "push 5 feet",
               "pull": "pull 5 feet", "speed": "Speed reduced by 10 feet", "temp_hp": "Temporary Hit Points",
               "armament": "move Domain Armament"}
OPTIONS = {"temp_hp": "Temporary Hit Points", "move": "Move 5 Feet", "armament": "Move Domain Armament", "advantage": "Advantage on a Check"}


@hook("history_event_metadata")
def augment_history_name(event: dict[str, Any], events: Any) -> dict[str, str] | None:
    """Give the independently attributed Augment outcomes their plain player name."""
    source = str((event.get("payload") or {}).get("display_source_id") or event.get("source_definition_id") or "")
    prefix = DEVIL_QI_AUGMENT + "."
    if not source.startswith(prefix) or source[len(prefix):] not in RIDER_NAMES:
        return None
    return {"display_name": "Devil-Qi Augment: " + RIDER_NAMES[source[len(prefix):]]}


def _rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "devil_heart_second_furnace" and row.get("kind") == "demon_seed_overdraw"]


def _owns_augment(engine: Any, actor: Any) -> bool:
    return any(row.get("block") == "devil_heart_second_furnace" and row.get("kind") == "devil_qi_augment"
               for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


QI_PATH_FEATURE_PREFIX = "tianxia.path.qi_cultivation."
QUALIFYING_PREFIXES = (QI_PATH_FEATURE_PREFIX, "tianxia.subpath.", "tianxia.talent.", "tianxia.recorded_art.",
                       "tianxia.forged_technique.", "recorded_art.", "forged_technique.")


def _qualifying_source(ctx: Any) -> bool:
    """Printed sources only: Qi Path features, Subpath features, Sphere abilities, Recorded Arts, Forged Techniques and
    weapon-delivered cultivation techniques. Owner ruling (2026-10-11): all Sphere abilities count as talents.
    Other Path features and generated basic weapon attacks do not qualify merely because they carry a weapon.

    Factory runtime ids are opaque. Resolve explicit damage attribution, or the compiled row's printed source/owning
    menu feature, through the shared authority reader. Forged Techniques retain provenance even with user-chosen ids.
    Stable legacy source namespaces remain supported only when there is no authority record to classify.
    """
    from ..typed_numbers import authority_mechanics

    typed = ctx.typed or {}
    if "cost_damage" in getattr(ctx,"damage_source_flags",()):return False
    if (getattr(ctx.action,"parameters",None) or {}).get("armament")=="attack":return True
    mechanics = authority_mechanics()
    attribution = getattr(ctx, "effect_source", None)
    if not attribution and typed.get("forged_from") in mechanics:
        return True
    source = str(attribution or typed.get("option_of") or typed.get("source")
                 or getattr(ctx.action, "source_definition_id", "") or ctx.source or "")
    # Named passive damage keeps the enclosing action for delivery/targeting,
    # but its own printed ability determines Augment eligibility.
    source = source.removeprefix("passive:")
    row = mechanics.get(source)
    if row is not None:
        kind = row.get("kind")
        return bool((kind == "path_feature" and row.get("path_id") == "tianxia.path.qi_cultivation")
                    or kind == "subpath_feature"
                    or row.get("sphere_id")
                    or row.get("weapon_delivery") or (row.get("range") or {}).get("weapon_delivery"))
    return source.startswith(QUALIFYING_PREFIXES)


def _consecrated_source_cl(ctx: Any, target: Any) -> int:
    """Compatibility reader for explicit native Consecration sources."""
    from .furnace_runtime import consecrated_cl
    return consecrated_cl(ctx.engine,target)


def _prompt_context(ctx: Any, target: Any) -> dict[str, Any]:
    """Shared triggering-action metadata for every augment prompt: the enclosing action, the creature it hit, and the
    augment's own Devil Qi price (never the enclosing action's cost)."""
    action_name = getattr(ctx.action, "display_name", None) or "the enclosing attack"
    from .furnace_runtime import engine_benefits
    return {"source_definition_id": DEVIL_QI_AUGMENT, "action_name": action_name,
            "action_actor_id": ctx.actor.entity_id, "affected_id": target.entity_id, "cost": "No Devil Qi during Second Engine" if engine_benefits(ctx.engine,ctx.actor) else "1 Devil Qi"}


def _ask(ctx: Any, target: Any, key: str, options: list[str], labels: dict[str, str], prompt: str,
         *, allow_decline: bool = False, chooser: Any = None) -> list[str]:
    from .needle import CHOICE as NEEDLE_CHOICE, ask, checkpoint_id

    chooser = chooser or ctx.actor
    return ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "DEVIL_QI_AUGMENT", ctx.actor.entity_id,
                                                       target.entity_id, key), chooser,
               NEEDLE_CHOICE + "devil_qi_augment", options, labels=labels, allow_decline=allow_decline,
               automatic=True, default="decline" if allow_decline else "first", target_id=target.entity_id,
               name="Devil-Qi Augment", feature_id=DEVIL_QI_AUGMENT, prompt=prompt,
               prompt_context=_prompt_context(ctx, target))


def _armament_present(actor: Any) -> bool:
    return any(c.condition_id == "condition:typed.domain_armament" for c in actor.conditions.values())


def move_armament_choice(ctx: Any, target: Any, distance_ft: int = 15, *, feature_id: str = DEVIL_QI_AUGMENT, name: str = "Devil-Qi Augment", furnace_link: bool = False) -> bool:
    """Shared optional armament positioning for Augment and furnace_core.

    distance_ft bounds this one grant; native control range and saved event/state
    remain qi_path's. Never creates an armament. Returns True only when the
    selected point became the armament's saved position; decline or failure
    leaves an optional once-per-turn movement unspent.
    """
    from . import qi_path
    from .needle import ask, cell_id, checkpoint_id

    armed = qi_path.armament_condition(ctx.actor)
    if armed is None:
        return False
    bonus = qi_path.armament_movement_bonus(ctx.engine,ctx.actor)
    from .furnace_runtime import armament_offer
    current = qi_path.armament_point(ctx.actor)
    max_range = qi_path.armament_control_range(ctx.engine, ctx.actor)
    candidates = []
    from ..target_knowledge import can_see
    occupied = {cell for other in ctx.engine.state.actors.values() if other.active and can_see(ctx.engine,ctx.actor,other)
                for cell in ctx.engine._actor_cells(other)}
    for x in range(ctx.engine.grid.width):
        for y in range(ctx.engine.grid.height):
            cell = (x, y)
            distance = int(ctx.engine.grid.distance_ft(current, cell))
            if (distance > 0 and distance <= distance_ft + bonus
                    and int(ctx.engine.grid.distance_ft(cell, ctx.actor.position)) <= max_range
                    and ctx.engine.grid.placement_legal(cell, occupied_cells=occupied)
                    and armament_offer(ctx.engine,ctx.actor,current,cell,link=furnace_link)):
                candidates.append(ctx.actor.position.model_copy(update={"x": int(x), "y": int(y)}))
    if not candidates:
        return False
    displayed_distance=distance_ft+bonus
    options = [cell_id(point) for point in sorted(candidates, key=lambda p: (p.x, p.y))]
    labels = {cell_id(point): f"Move the Domain Armament to ({point.x}, {point.y})" for point in candidates}
    from .choice_prompt import action_context
    from ..senses import perceives_cell
    automatic_cells=[cell_id(p) for p in candidates if perceives_cell(ctx.engine,ctx.actor,p)]
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "DEVIL_QI_AUGMENT_ARMAMENT" if feature_id == DEVIL_QI_AUGMENT else "FURNACE_ARMAMENT:" + feature_id, ctx.actor.entity_id,
                                                        target.entity_id), ctx.actor,
                 "choice:needle.devil_qi_augment_armament", options, labels=labels, allow_decline=True,
                 automatic=True, automatic_options=automatic_cells, default="decline", target_id=target.entity_id, name=name,
                 feature_id=feature_id,
                 prompt=f"{name}: move your Domain Armament up to {displayed_distance} feet. "
                        f"Choose its new space.",
                 prompt_context={**action_context(ctx.engine, ctx.actor, ctx.action.source_definition_id, target, action=ctx.action),
                                 "cost": "No extra cost"})
    if not picked:
        return False
    point = next((p for p in candidates if cell_id(p) == picked[0]), None)
    if point is not None:
        if furnace_link:
            from .furnace_runtime import move_link
            move_link(ctx.with_source(feature_id),point,distance_ft)
        else:
            qi_path.move_armament(ctx.engine, ctx.actor, point, ctx.source, distance_ft=distance_ft)
        return qi_path.armament_point(ctx.actor) == (int(point.x), int(point.y))
    return False


def _apply_rider(ctx: Any, target: Any, rider: str) -> None:
    from .. import typed_executor as te

    ctx = ctx.with_source(DEVIL_QI_AUGMENT + "." + rider)
    if rider == "no_reactions":
        te.run_effects(ctx.on_hit_context(target), [{"type": "condition", "applies_to": "target",
                                                     "condition": "reaction_denied",
                                                     "expires_on": "START_OF_TARGET_NEXT_TURN"}])
    elif rider in ("push", "pull"):
        te.run_effects(ctx.on_hit_context(target), [{"type": "forced_movement", "applies_to": "target",
                                                     "distance_ft": 5, "direction": "away" if rider == "push" else "toward"}])
    elif rider == "speed":
        te.run_effects(ctx.on_hit_context(target), [{"type": "speed", "applies_to": "target", "flat": -10, "source_owned": True,
                                                     "expires_on": "START_OF_TARGET_NEXT_TURN"}])
    elif rider == "temp_hp":
        from .furnace_runtime import temp_hp
        temp_hp(ctx.engine,ctx.actor,DEVIL_QI_AUGMENT)
    elif rider == "armament":
        move_armament_choice(ctx, target)


@hook("damage_packet_selection")
def augment_packet_selection(ctx: Any, target: Any, packet_kinds: tuple[str, ...]) -> None:
    """Select a mixed hit's delivery before damage; a decline never spends the use."""
    ctx.damage_cache.pop("_devil_qi_packet", None)
    actor = ctx.actor
    from .furnace_runtime import engine_benefits
    if (len(packet_kinds) < 2
            or not _owns_augment(ctx.engine, actor) or not _qualifying_source(ctx)
            or actor.turn_flags.get(USED_AUGMENT) or (int(actor.resources.get(DEVIL_QI, 0)) < 1 and not engine_benefits(ctx.engine,actor))):
        return
    selected = _ask(ctx, target, "packet", list(packet_kinds),
        {"weapon": "Add Devil-Qi Augment to the weapon damage only",
         "technique": "Add Devil-Qi Augment to the technique damage only"},
        f"Devil-Qi Augment: {ctx.action.display_name} hits {target.display_name}. Choose which damage "
        "receives the extra dice and rider (1 Devil Qi if you accept after it deals damage).")
    if selected:
        ctx.damage_cache["_devil_qi_packet"] = selected[0]


@hook("damage_dealt")
def devil_qi_augment(ctx: Any, target: Any, amount: int) -> None:
    """Offer one printed augment after eligible damage, once on each creature's turn."""
    engine, actor = ctx.engine, ctx.actor
    from .furnace_runtime import engine_benefits,source_numbers
    from dataclasses import replace
    own=source_numbers(engine,actor,DEVIL_QI_AUGMENT)
    ctx=replace(ctx,typed={**ctx.typed,"numbers":{**ctx.numbers,**own}})
    pending = (ctx.damage_cache or {}).get("_devil_qi_augment_pending")
    if pending and target is not None and target.entity_id == pending.get("target_id"):
        if amount > 0 and not pending.get("save_success"):
            _apply_rider(ctx, target, str(pending["rider"]))
        return
    from .furnace_runtime import acquired,usable
    if acquired(actor) and not usable(engine,actor):return
    if (amount <= 0 or int(ctx.numbers.get("cl",1))<6 or target is None
            or not _owns_augment(engine, actor) or not _qualifying_source(ctx)
            or (int(actor.resources.get(DEVIL_QI, 0) or 0) < 1 and not engine_benefits(engine,actor))
            or actor.turn_flags.get(USED_AUGMENT)):
        return
    selected = ctx.damage_cache.get("_devil_qi_packet")
    if selected and selected != ctx.damage_packet_kind:
        return
    cl = int(ctx.numbers.get("cl") or 1)
    dice = 4 if cl >= 17 else 3 if cl >= 11 else 2
    if activation_augmented(ctx):return
    price = "Use the Engine’s free Augment" if engine_benefits(engine,actor) else "Spend 1 Devil Qi"
    ask_prompt = (f"{price} to add {dice}d8 necrotic, psychic, or force damage and a rider to "
                  f"{target.display_name}?")
    offer = _ask(ctx, target, "offer", ["augment", "skip"],
                 {"augment": price + " to add damage and choose a rider", "skip": "Save your Devil Qi"},
                 ask_prompt, allow_decline=True)
    if not offer or offer[0] != "augment":
        ctx.damage_cache.pop("_devil_qi_packet", None)
        return

    damage_type = _ask(ctx, target, "damage_type", ["necrotic", "psychic", "force"],
                       {"necrotic": "Necrotic damage", "psychic": "Psychic damage", "force": "Force damage"},
                       f"Devil-Qi Augment: choose the extra damage type against {target.display_name}.")[0]
    rider_options = ["no_reactions", "push", "pull", "speed", "temp_hp"]
    rider_labels = {
        "no_reactions": f"{target.display_name} cannot take Reactions until its next turn starts",
        "push": f"Push {target.display_name} 5 feet", "pull": f"Pull {target.display_name} 5 feet",
        "speed": f"Reduce {target.display_name}'s Speed by 10 feet until its next turn starts",
        "temp_hp": f"Gain Temporary Hit Points equal to {2 if engine_benefits(engine,actor) else 1} times your Proficiency Bonus",
    }
    if _armament_present(actor):
        rider_options.append("armament")
        rider_labels["armament"] = "Move your Domain Armament up to 15 feet"
    rider = _ask(ctx, target, "rider", rider_options, rider_labels,
                 f"Devil-Qi Augment: choose one rider for damaging {target.display_name}.")[0]

    from .. import typed_executor as te

    consecrated_cl = _consecrated_source_cl(ctx, target)
    damage_effect = {"type": "damage", "applies_to": "target", "dice": {"count": dice, "sides": 8},
                     "damage_types": [damage_type], "evidence": f"Devil-Qi Augment: add {dice}d8 {damage_type.title()} damage"}
    if consecrated_cl >= cl and consecrated_cl > 0:
        # Consecrated Resistance: the protected creature MAY make the CON save; its owner decides (AI decides automatically).
        choice = _ask(ctx, target, "consecrated", ["save", "decline"],
                      {"save": f"Make a Constitution save against {actor.display_name}'s Cultivation Save DC "
                               f"{int(ctx.numbers.get('save_dc') or 10)}: on success take half the extra damage and ignore the rider",
                       "decline": "Skip the save: take the full extra damage and the rider"},
                      f"Devil-Qi Augment: {target.display_name} is protected by a consecrated effect. "
                      f"Make a Constitution save against {actor.display_name}'s Cultivation Save DC "
                      f"{int(ctx.numbers.get('save_dc') or 10)}?",
                      allow_decline=True, chooser=target)
        if choice and choice[0] == "save":
            damage_effect = {"type": "save", "applies_to": "target", "ability": "CON",
                             # This save resolves bonus damage belonging to the
                             # selected hit, so its failure keeps that hit's
                             # critical and attack-only defense context.
                             "inherit_attack_damage_context": True,
                             "on_success": [{"type": "half_damage"}],
                             "on_fail": [damage_effect]}

    actor.turn_flags[USED_AUGMENT] = True
    mark_activation_augmented(ctx)
    if not engine_benefits(engine,actor):
        engine._spend_resource(actor, DEVIL_QI, 1, "passive:" + DEVIL_QI_AUGMENT)
    cache = ctx.damage_cache
    cache["_devil_qi_augment_pending"] = {"target_id": target.entity_id, "rider": rider}
    try:
        te.run_effects(ctx.on_hit_context(target).with_source(DEVIL_QI_AUGMENT + ".damage"), [damage_effect])
    finally:
        cache.pop("_devil_qi_augment_pending", None)


@hook("after_save_resolved")
def devil_qi_consecrated_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Mark the in-flight augment save outcome so a successful save cannot apply its rider."""
    pending = (ctx.damage_cache or {}).get("_devil_qi_augment_pending")
    if pending and subject is not None and subject.entity_id == pending.get("target_id") and ability.upper() == "CON":
        pending["save_success"] = not bool(failed)


@hook("compile_block")
def devil_heart_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "devil_heart_second_furnace":
        return None
    return [{**row, "block": "devil_heart_second_furnace", "kind": spec.get("kind")}]


@hook("payment_substitution")
def overdraw_quote(engine, actor, source, costs, missing):
    return quote_overdraw(engine,actor,source,costs,missing,emperor=False)


@hook("payment_substitution")
def emperor_quote(engine,actor,source,costs,missing):
    return quote_overdraw(engine,actor,source,costs,missing,emperor=True)


def quote_overdraw(engine, actor, source, costs, missing, *, emperor):
    from . import furnace_runtime as f
    from ..alternative_payments import PaymentAlternative
    if not f.owns(engine,actor) or not f.usable(engine,actor) or f.ordinary_suppressed(actor):return None
    profile=f.source_profile(engine,source)
    total=costs.get(QI,0)
    if total<1 or not profile.get('ordinary_qi') or profile.get('cannot_further_reduce'):return None
    if profile.get('another_creature'):return None
    if actor.resources.get(CORRUPTION,0)>=10 and f.condition(actor,f.UNSTABLE):return None
    if emperor and (not f.engine_benefits(engine,actor) or actor.turn_flags.get('_round_emperor_overdraw')==engine.state.round_number):return None
    if not emperor and actor.turn_flags.get('typed_once_turn:demon_seed_overdraw'):return None
    pb=int(f.numbers_of(engine,actor).get('pb',actor.proficiency_bonus))
    floor=1 if any(profile.get(k) for k in ('legendary','artifact','secret','secret_law','immortal','immortal_art',
        'permanent','indefinite','strategic_travel','world_scale','expensive_materials','sacrifice')) and not profile.get('explicit_zero') else 0
    cut=min(total-floor,pb*(2 if emperor else 1))
    if cut<=0 or any(r!=QI for r in missing):return None
    feature=f.ENGINE if emperor else DEMON_SEED_OVERDRAW
    label='Emperor’s Overdraw' if emperor else 'Demon Seed Overdraw'
    gains=((CORRUPTION,2 if emperor else 1),)
    plans=[]
    if missing.get(QI,0)<=cut:
        plans.append(PaymentAlternative(feature,label,((QI,cut),),resolution_gains=gains))
    # Substitution pays the remaining cost; it does not reduce that cost again.
    # Use the existing Core consumer's public eligibility, not a second schema.
    from .furnace_core import devil_payment_permitted
    if devil_payment_permitted(engine,actor,source):
        maximum=min(total-cut,actor.resources.get(DEVIL_QI,0))
        for split in range(max(1,missing.get(QI,0)-cut),maximum+1):
            plans.append(PaymentAlternative(feature,label+f'; pay {split} remaining Qi with Devil Qi',
                ((QI,cut+split),),costs=((DEVIL_QI,split),),resolution_gains=gains))
    return tuple(plans) or None


@hook('payment_shortfall_paid')
def accept_overdraw(engine,actor,source,plan,intent):
    from . import furnace_runtime as f
    if plan.source_id not in (DEMON_SEED_OVERDRAW,f.ENGINE):return
    ctx=f.context(engine,actor,plan.source_id)
    if actor.resources.get(CORRUPTION,0)>=10:f.breach(ctx)
    if plan.source_id==f.ENGINE:actor.turn_flags['_round_emperor_overdraw']=engine.state.round_number
    else:actor.turn_flags['typed_once_turn:demon_seed_overdraw']=1


@hook('activation_settlement')
def settle_overdraw(ctx):
    from . import furnace_runtime as f
    from ..activation_payments import receipts
    records=[e for e in receipts(ctx) if e.source_definition_id in (DEMON_SEED_OVERDRAW,f.ENGINE)]
    if not records:return None
    cl=int(f.source_numbers(ctx.engine,ctx.actor,DEMON_SEED_OVERDRAW)['cl'])
    interrupted=any(c.condition_id==f.INTERFERENCE and c.data.get('anti_daemonic') and
        c.data.get('second_suppressed') and int(c.data['source_cl'])>=cl for c in ctx.actor.conditions.values())
    if not interrupted:return None
    for held in list(ctx.actor.conditions.values()):
        if held.condition_id==f.INTERFERENCE and held.data.get('interrupt_next_activation'):
            data={**held.data,'interrupt_next_activation':0}
            ctx.engine._remove_condition_instance(ctx.actor,held.instance_id,held.source_definition_id)
            ctx.engine._apply_condition(ctx.actor,held.condition_id,held.source_definition_id,held.source_actor_id,
                expires_on=held.expires_on,data=data)
    # The committed ward may explicitly interrupt this resolution rather than
    # suppressing the organ before activation admission. Its source owns timing.
    # Cancel the promised gains even if the original feature can continue.
    for record in records:
        ctx.engine._append_event('ACTIVATION_PAYMENT_SETTLED',record.source_definition_id,actor_id=ctx.actor.entity_id,
            payload={'payment_sequence':record.sequence,'interrupted':1})
    cost=sum(n for rid,n in ctx.action.costs if rid==QI)
    if ctx.actor.resources.get(QI,0)>=cost:
        ctx.engine._spend_resource(ctx.actor,QI,cost,ctx.source)
        return None
    ctx.engine._append_event('PASSIVE_TRIGGERED',DEMON_SEED_OVERDRAW,actor_id=ctx.actor.entity_id,
        payload={'log':'Anti-daemonic interruption: the original activation fails because its unreduced Qi cost cannot be paid; Qi already spent remains spent.'})
    return False


@hook('technique_resolved')
def demon_seed_overdraw(ctx):
    from . import furnace_runtime as f
    from ..activation_payments import receipts
    settled={e.payload.get('payment_sequence') for e in ctx.engine.events
        if e.event_type=='ACTIVATION_PAYMENT_SETTLED' and not e.payload.get('interrupted')}
    for record in receipts(ctx):
        if record.source_definition_id==DEMON_SEED_OVERDRAW and record.sequence in settled:
            if f.gain(ctx.engine,ctx.actor,'overdraw',limited=False):
                f.reinforcement(ctx.with_source(DEMON_SEED_OVERDRAW))


def activation_key(ctx):
    """The actual native causal activation; zones retain their creating owner."""
    from ..paid_relocation import current_activation
    key=ctx.damage_cache.get('_second_furnace_activation')
    if key:return key
    view=current_activation(ctx.engine)
    return view.activation_id if view else f'{ctx.engine._transaction_id}:{ctx.actor.entity_id}:{ctx.source}'


def activation_augmented(ctx):
    key=activation_key(ctx)
    return any(c.condition_id=='condition:typed.second_furnace_augmented_activation' and c.data.get('activation_id')==key
        for c in ctx.actor.conditions.values())


def mark_activation_augmented(ctx):
    ctx.engine._apply_condition(ctx.actor,'condition:typed.second_furnace_augmented_activation',DEVIL_QI_AUGMENT,
        ctx.actor.entity_id,expires_on='UNTIL_REMOVED',data={'activation_id':activation_key(ctx),
        'label':'Devil-Qi Augment already applied to this activation'})


@hook('zone_created')
def retain_augment_activation(ctx,zone):
    if _owns_augment(ctx.engine,ctx.actor) and _qualifying_source(ctx):
        zone.trigger_profile['second_furnace_activation']=activation_key(ctx)


@hook('zone_trigger_context')
def restore_augment_activation(ctx,zone,creature,moment):
    if zone.trigger_profile.get('second_furnace_activation'):
        ctx.damage_cache['_second_furnace_activation']=zone.trigger_profile['second_furnace_activation']

"""Gōruden's source-owned golden-body progression.

Existing native hooks handle AC, named bodily saves/checks, Stamina Guard,
falling, unarmed hit riders, zones and final lethal-damage replacement. This
provider supplies the family's cosmetic state, ally choices, target-anchored
light and statue lifecycle. Costs, ownership, limits, turns and replay use the
ordinary compiled bundle and transactional engine contracts. New choices are
inert without the corresponding acquired feature or active source condition.
See docs/mechanics/goruden.md for producers, callers and persisted state.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.goruden.feature."
STATUE = "condition:typed.golden_statue"
NO_BENEFIT = "condition:typed.no_invisible_benefit"
ALL = ("ACID", "BLUDGEONING", "COLD", "FIRE", "FORCE", "LIGHTNING", "NECROTIC", "PIERCING", "RADIANT", "SLASHING", "THUNDER")


def _rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "path_rider" and row.get("kind") == kind]


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}"


# ----------------------------------------------------------------------------------------------------------- Gilded Bones
@hook("soak_dice")
def gilded_guard(engine: Any, target: Any, row: dict[str, Any], spend: int, dice: Any) -> Any:
    if not _rows(engine, target, "gilded_guard") or not str(row.get("feature_id") or "").endswith("feature.stamina_guard"):
        return None
    from .needle import ask, checkpoint_id
    from .choice_prompt import action_context

    # Only packet provenance can identify nested damage reliably. The existing
    # seam covers confirmed attacks; other damage intentionally stays unnamed.
    packet = engine.damage_context()
    source_actor = engine.state.actors.get(packet.attacker_id) if packet else None
    context = action_context(engine, source_actor, packet.source_id, target) if packet and packet.target_id == target.entity_id else {
        "action_name": "", "source_definition_id": "", "action_actor_id": "", "affected_id": target.entity_id}

    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "gilded_guard", target.entity_id),
                 target, "choice:needle.gilded_guard", ["gilded", "standard"],
                 labels={"gilded": f"Gilded Guard: {2 * spend}d8 ({spend} Stamina x 2d8)", "standard": f"Standard Guard: {spend}d{dice.sides}"},
                 prompt=f"Gilded Bones: {target.display_name}'s Stamina Guard spends {spend} Stamina; choose the dice.",
                 target_id=target.entity_id, prompt_context=context)
    if picked != ["gilded"]:
        return None
    from ..pending_damage import packet_scratch
    scratch = packet_scratch(engine)
    if scratch is not None:
        scratch['goruden_gilded_guard'] = target.entity_id
    return dice.model_copy(update={"count": 2 * int(spend), "sides": 8})


@hook("event", nested=True)
def gilded_after(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "DAMAGE_COMMITTED":
        return
    from ..pending_damage import packet_scratch
    scratch = packet_scratch(engine)
    for target_id in kwargs.get("target_ids") or ():
        if scratch is None or scratch.get('goruden_gilded_guard') != target_id:
            continue
        scratch.pop('goruden_gilded_guard')
        target = engine.state.actors.get(target_id)
        payload = kwargs.get("payload") or {}
        if target is None or not target.active or int(payload.get("hp_damage") or 0) <= 0:
            continue
        if target.turn_flags.get("_round_gilded_thp") == _stamp(engine):
            continue
        target.turn_flags["_round_gilded_thp"] = _stamp(engine)
        pb = int(next((row.get("pb") for row in _rows(engine, target, "gilded_guard")), 2) or 2)
        engine._grant_temp_hp(target, pb, PREFIX + "gilded_bones", target.entity_id)


# ----------------------------------------------------------------------------------------------------------- Golden Sheen
def _unarmored(engine: Any, actor: Any) -> bool:
    if any(row.get('unarmored_defense_selected') is False for row in _rows(engine, actor, 'golden_sheen')):
        return False
    for bundle in getattr(engine, "typed_bundle_documents", ()) or ():
        if bundle.get("actor_id") == actor.entity_id:
            return not any(item.get("worn") and str(item.get("kind") or item.get("category") or "armor").lower() != "shield"
                           for item in (bundle.get("carrying") or {}).get("items") or [])
    return True


@hook("ac")
def sheen_ac(engine: Any, target: Any) -> int | None:
    return 1 if _rows(engine, target, "golden_sheen") and _unarmored(engine, target) else None


@hook("save")
def sheen_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if subject is None or not _rows(ctx.engine, subject, "golden_sheen") or not _unarmored(ctx.engine, subject):
        return None
    tags = {str(n).removeprefix("category:") for n in named or ()}
    legacy = {"poisoned", "sickened", "disease", "corrosion", "bodily_decay", "physical_deformation"}
    qualified = set().union(*(set(row.get('against', legacy)) for row in _rows(ctx.engine, subject, 'golden_sheen')))
    return {"bonus": 0, "modes": ["ADVANTAGE"]} if qualified & tags else None


@hook("falling_damage")
def gilded_fall(engine: Any, target: Any, amount: int, fall: Any, intent: Any) -> dict[str, Any] | None:
    if not _rows(engine, target, "gilded_guard") or fall.distance_ft > 60:
        return None
    return {"amount": 0, "land_prone": True}


@hook("save")
def gilded_bone_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if subject is None or not _rows(ctx.engine, subject, "gilded_guard"):
        return None
    if {str(n).removeprefix("category:") for n in named or ()} & {"crushing", "fracture", "bone_breaking"}:
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@hook("ability_check_hazard_mode")
def golden_bodily_checks(engine: Any, actor: Any, ability: str, skill: Any, against: Any, hazards: Any) -> str | None:
    tags = {str(n).removeprefix("category:") for n in hazards or ()}
    bone = _rows(engine, actor, "gilded_guard") and tags & {"crushing", "fracture", "bone_breaking"}
    sheen = _rows(engine, actor, "golden_sheen") and _unarmored(engine, actor) and tags & {
        "disease", "poisoned", "corrosion", "bodily_decay", "physical_deformation"}
    return "ADVANTAGE" if bone or sheen else None


# ---------------------------------------------------------------------------------------------------------- Immortal Gold
@effect("golden_statue")
def golden_statue(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    if not any(r.get('block')=='generic' and r.get('feature_id')==PREFIX+'immortal_gold'
               for r in (getattr(engine,'typed_reaction_rows',{}) or {}).get(actor.entity_id,())):
        return
    if actor.concentration is not None:
        engine._end_concentration(actor, reason='INCAPACITATED')
    engine._apply_condition(actor, STATUE, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Golden statue: Incapacitated, Speed 0, Resistance to all damage; ends at the start of its turn",
                                  "cl": int(ctx.numbers.get("cl") or 1), "pb": int(ctx.numbers.get("pb") or 2),
                                  "native_restoration": int(bool(_rows(engine, actor, "immortal_gold_final"))),
                                  "rule": {"no_actions": True, "no_reactions": True, "speed_zero": True}})
    for kind in ALL:
        engine._add_modifier(actor, ctx.source, "damage_resistance", "ADD", kind, "SELF", expires_on="UNTIL_REMOVED")
    for kind in ("POISON", "PSYCHIC"):
        engine._add_modifier(actor, ctx.source, "damage_immunity", "ADD", kind, "SELF", expires_on="UNTIL_REMOVED")


def _statue(actor: Any) -> Any:
    return next((c for c in actor.conditions.values() if c.condition_id == STATUE), None)


@hook("effect_subject_allowed")
def statue_unmoved(ctx: Any, eff: dict[str, Any], subject: Any) -> bool | None:
    """"An effect whose Source CL is lower than yours cannot move you" while a statue."""
    held = _statue(subject) if subject is not None else None
    if held is None or (eff or {}).get("type") not in ("forced_movement", "teleport", "movement"):
        return None
    from .cultivation_contests import holds_position
    if int(ctx.numbers.get("cl") or 1) < int((held.data or {}).get("cl") or 1) or holds_position(ctx.engine, subject, ctx.actor, PREFIX + "immortal_gold", source_numbers=ctx.numbers):
        return False
    return None


@hook("subject_teleport_attempt")
def statue_teleport(ctx: Any, subject: Any, start: Any, destination: Any) -> bool | None:
    return statue_unmoved(ctx, {"type": "teleport"}, subject)


@hook("turn_start")
def statue_wakes(engine: Any, actor: Any) -> None:
    held = _statue(actor)
    if held is None or not actor.active:
        return
    source = held.source_definition_id
    actor.conditions.pop(held.instance_id)
    engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"condition_id": STATUE, "instance_id": held.instance_id})
    for mid, modifier in list(actor.modifiers.items()):
        if modifier.source_definition_id == source and modifier.target_field in ("damage_resistance", "damage_immunity"):
            del actor.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"modifier_id": mid, "reason": "STATUE_ENDED"})
    from .healing_policy import ordinary_preparation
    heal = min(actor.maximum_hp - actor.current_hp, 5 * int((held.data or {}).get("pb") or 2))
    native = bool((held.data or {}).get('native_restoration'))
    if native:
        from ..typed_executor import stored_healing_reductions
        from .life_state import heal_to
        offered = 5 * int((held.data or {}).get('pb') or 2)
        # Query restrictions without consuming any next-healing allowance.
        # A legal block prevents the free Aura as stated in the full normalized
        # source; ordinary damage, reduced healing and a full HP total do not.
        permitted = stored_healing_reductions(engine, actor, offered, consume=False,
                                              healer=actor, source=source) > 0
        heal = heal_to(engine, actor, offered, source, actor.entity_id)
        if not permitted:
            note(engine, source, actor, f"Immortal Gold: {actor.display_name}'s statue ends, but restoration is prevented; Golden Aura does not activate.")
            return
    elif heal > 0:
        if ordinary_preparation(engine, actor):
            from .life_state import heal_to
            heal = heal_to(engine, actor, 5 * int((held.data or {}).get("pb") or 2), source, actor.entity_id)
        else:
            before = actor.current_hp
            actor.current_hp += heal
            engine._append_event("HEALING_APPLIED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"offered": heal, "before": before, "after": actor.current_hp})
    note(engine, source, actor, f"Immortal Gold: {actor.display_name} leaves its golden statue and regains {heal} Hit Points.")
    aura = next((a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                 and ((a.parameters or {}).get("typed") or {}).get("source") == PREFIX + "golden_aura"
                 and ((a.parameters or {}).get("typed") or {}).get("zone_spec")), None)
    if aura is None:
        return
    from .. import typed_executor as te, zones

    typed = dict(aura.parameters["typed"])
    ctx = te.Context(engine, actor, aura, getattr(engine, "_active_intent", None), typed, [], None, {})
    if typed.get("zone_spec"):
        zones.create(ctx, typed["zone_spec"])
    te.run_effects(ctx, typed.get("effects") or [])
    note(engine, source, actor, f"Immortal Gold: {actor.display_name}'s Golden Aura starts without its cost.")


# ---------------------------------------------------------------------------------------------- no Invisible benefit
@effect("no_invisible_benefit")
def no_invisible_benefit(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import effect_subjects, stated_expiry

    for subject in effect_subjects(ctx, row, harmful=True):
        if subject.active:
            if row.get('source_owned'):
                from .condition_ownership import refresh_owned
                refresh_owned(ctx.engine, subject, NO_BENEFIT, ctx.actor.entity_id, ctx.source)
            else:
                ctx.engine._remove_condition(subject, NO_BENEFIT, ctx.source)
            ctx.engine._apply_condition(subject, NO_BENEFIT, ctx.source, ctx.actor.entity_id,
                                        expires_on=stated_expiry(ctx, row, subject, condition=True) or "START_OF_TARGET_NEXT_TURN",
                                        data={"label": "Cannot benefit from Invisible"})


@hook("masked_conditions")
def invisible_masked(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    out: dict[str, set[str]] = {}
    for creature in (attacker, target):
        if creature is None or not any(c.condition_id == NO_BENEFIT for c in creature.conditions.values()):
            continue
        hidden = {iid for iid, c in creature.conditions.items() if c.condition_id in ("condition:typed.invisible", "condition:core.invisible")}
        if hidden:
            out[creature.entity_id] = hidden
    return out or None


# Family state is carried by ordinary conditions: table transactions, rollback,
# save/reload and mechanical replay own it. These are choices, never inferred
# willingness or source tags. The same compiled actions are usable by all seats.
SHEEN_HIDDEN = 'condition:typed.golden_sheen_suppressed'
AURA_CHOICE = 'condition:typed.golden_aura_choice'


def visible_sheen(engine: Any, actor: Any, target: Any) -> bool:
    """Public family query: a perceptible transformation, not merely a gold name."""
    from ..senses import perceives
    return bool(_rows(engine, actor, 'golden_sheen') and _unarmored(engine, actor)
                and not any(c.condition_id == SHEEN_HIDDEN for c in actor.conditions.values())
                and target is not None and perceives(engine, target, actor, sight_only=True))


@hook('compile_actions')
def golden_commands(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    owned = set(info['owned_ids'])
    if PREFIX+'immortal_gold' in owned:
        info['passives'].append({'block':'path_rider', 'kind':'immortal_gold_final',
                                 'feature_id':PREFIX+'immortal_gold', 'name':'Immortal Gold'})
    if PREFIX+'golden_aura' in owned:
        for action in info.get('actions') or ():
            typed = (action.parameters or {}).get('typed') or {}
            if typed.get('source') == PREFIX+'golden_aura':
                action.parameters['typed'] = {**typed, 'golden_ally_choices':1, 'manual_inline_choice':True}
    if not owned.intersection({PREFIX+'golden_sheen', PREFIX+'golden_aura'}):
        return None
    out = []
    def command(key, label, effect_row, target='SELF', range_ft=0, setting=True):
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.goruden.{key}", display_name=label,
            owner_id=info['actor_id'], economy=EconomyKind.NONE, resolution_kind='TYPED',
            target_kind=target, range_ft=range_ft,
            parameters={'setting_only':setting, 'player_only':True, 'expected_damage':0,
                        'typed':{'source':PREFIX+('golden_sheen' if key.startswith('sheen') else 'golden_aura'),
                                 'numbers':{**info['numbers'], 'ability_mods':dict(info['mods'])}, 'effects':[effect_row], 'riders':[],
                                 'duration':{'kind':'instant'}}}))
    if PREFIX+'golden_sheen' in owned:
        for reveal, word in ((0,'Suppress'),(1,'Reveal')):
            command('sheen_'+str(reveal), f'Golden Sheen: {word} visible gold',
                    {'type':'golden_sheen_visibility', 'visible':reveal})
        command('sheen_intimidation', 'Golden Sheen: Intimidation check',
                {'type':'golden_intimidation'}, 'ANY_CREATURE', 60, False)
    if PREFIX+'golden_aura' in owned:
        for include, word in ((0,'Exclude'),(1,'Include')):
            command('aura_'+str(include), f'Golden Aura: {word} ally',
                    {'type':'golden_aura_inclusion', 'include':include}, 'ALLY_OR_SELF', 10)
    return out


@effect('golden_sheen_visibility')
def sheen_visibility(ctx: Any, row: dict[str, Any]) -> None:
    if not _rows(ctx.engine, ctx.actor, 'golden_sheen'):
        return
    ctx.engine._remove_condition(ctx.actor, SHEEN_HIDDEN, ctx.source)
    if not row['visible']:
        ctx.engine._apply_condition(ctx.actor, SHEEN_HIDDEN, ctx.source, ctx.actor.entity_id,
                                   expires_on='UNTIL_REMOVED', data={'label':'Golden Sheen: visible gold suppressed; defenses remain'})
    note(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name} {'reveals' if row['visible'] else 'suppresses'} the visible golden sheen; no action or resource cost.")


@effect('golden_intimidation')
def golden_intimidation(ctx: Any, row: dict[str, Any]) -> None:
    """Native ability choice and roll; no social outcome or target consent inferred."""
    from .needle import ask, checkpoint_id
    from ..ability_checks import ability_modifier, skill_bonus
    if not _rows(ctx.engine, ctx.actor, 'golden_sheen') or ctx.target is None:
        return
    options = ['CHA', 'CON'] if visible_sheen(ctx.engine, ctx.actor, ctx.target) else ['CHA']
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine,'golden_intimidation',ctx.target.entity_id),
                 ctx.actor, 'choice:needle.goruden.intimidation', options,
                 labels={'CHA':'Charisma (Intimidation)', 'CON':'Constitution (Intimidation): visible golden transformation'},
                 preferred=[options[-1]], target_id=ctx.target.entity_id,
                 prompt=f"Golden Sheen: {ctx.actor.display_name} makes an Intimidation check toward {ctx.target.display_name}; choose the ability modifier. No action or Stamina cost; the GM decides the social outcome.")
    ability = picked[0] if picked else 'CHA'
    cha = ability_modifier(ctx.actor, 'CHA', numbers=ctx.numbers)
    total = skill_bonus(ctx.engine, ctx.actor, 'Intimidation', cha)
    bonus = total - cha + ability_modifier(ctx.actor, ability, numbers=ctx.numbers)
    # An ordinary check has no invented social DC or implied social outcome.
    # The native roller's d20 scope keeps pending choices and roll provenance.
    from . import run, floored
    bonus += sum(int(n) for n in run('check_bonus', ctx, ctx.actor) if isinstance(n, int))
    with ctx.engine.d20_scope({'kind':'check', 'actor_id':ctx.actor.entity_id,
                              'target_id':ctx.target.entity_id, 'source_id':ctx.source,
                              'source_actor_id':ctx.actor.entity_id,
                              'ability':ability, 'skill':'Intimidation'}):
        roll = ctx.engine.roll_check(modifier=bonus, actor_id=ctx.actor.entity_id,
                                     reason=f'CHECK:{ctx.source}', ability=ability,
                                     skill='Intimidation', against_creature=ctx.target)
    ctx.engine._record_roll(roll)
    roll = floored(ctx.engine, ctx.actor, roll, ability=ability, skill='Intimidation')
    ctx.engine._append_event('CHECK_ROLLED',ctx.source,actor_id=ctx.actor.entity_id,
                             target_ids=(ctx.target.entity_id,),payload={
                                 'actor':roll.model_dump(mode='json'), 'ability':ability,
                                 'skill':'Intimidation', 'outcome':'GM adjudicates social outcome'})


def _aura_choice(engine: Any, zone: Any, subject: Any, include: bool) -> None:
    owner = engine.state.actors[zone.owner_id]
    for c in list(owner.conditions.values()):
        if c.condition_id == AURA_CHOICE and (c.data or {}).get('zone_id') == zone.zone_id and (c.data or {}).get('subject_id') == subject.entity_id:
            from .condition_ownership import remove_instance
            remove_instance(engine,owner,c.instance_id,zone.source_definition_id)
    engine._apply_condition(owner,AURA_CHOICE,zone.source_definition_id,owner.entity_id,
                            expires_on='UNTIL_REMOVED', data={'zone_id':zone.zone_id,'subject_id':subject.entity_id,
                            'include':int(include),'label':f"Golden Aura: {subject.display_name} {'included' if include else 'excluded'}"})


def _ask_aura(engine: Any, zone: Any, subject: Any, intent: Any) -> None:
    from .needle import ask, checkpoint_id
    owner = engine.state.actors[zone.owner_id]
    if subject is owner or subject.team_id != owner.team_id:
        return
    picked = ask(engine,intent,checkpoint_id(engine,'golden_aura_ally',zone.zone_id,subject.entity_id),
                 owner,'choice:needle.goruden.aura_ally',['include','exclude'],preferred=['include'],
                 labels={'include':f'Include {subject.display_name}', 'exclude':f'Exclude {subject.display_name}'},
                 target_id=subject.entity_id,
                 prompt=f"Golden Aura: {owner.display_name}, include {subject.display_name}? While within 10 feet: Advantage against Frightened and Necrotic Resistance; temporary hit points equal to Proficiency Bonus once this activation. Benefits last while inside until this 1-minute activation ends. No additional action or cost.")
    _aura_choice(engine,zone,subject,picked==['include'])


@hook('zone_created')
def golden_aura_created(ctx: Any, zone: Any) -> None:
    if ctx.typed.get('source') != PREFIX+'golden_aura' or not ctx.typed.get('golden_ally_choices'):
        return
    from .. import zones
    for previous in list(ctx.engine.state.zones.values()):
        if (previous.active and previous.owner_id == zone.owner_id
                and previous.source_definition_id == zone.source_definition_id):
            zones.remove(ctx.engine, previous, 'REPLACED')
    # Stamp newly compiled activations only; old saved zones retain their policy.
    zone.trigger_profile['golden_ally_choices'] = 1
    for subject in ctx.engine.state.actors.values():
        if subject.active and zones.actor_inside_zone(ctx.engine,subject,zone):
            _ask_aura(ctx.engine,zone,subject,ctx.intent)


@hook('zone_recipient_allowed')
def golden_aura_recipient(engine: Any, zone: Any, subject: Any, spec: dict[str, Any]) -> bool | None:
    if not zone.trigger_profile.get('golden_ally_choices') or spec.get('who') != 'ally':
        return None
    owner = engine.state.actors.get(zone.owner_id)
    if owner is None or subject is owner:
        return None
    return any(c.condition_id==AURA_CHOICE and (c.data or {}).get('zone_id')==zone.zone_id
               and (c.data or {}).get('subject_id')==subject.entity_id and (c.data or {}).get('include')==1
               for c in owner.conditions.values())


@hook('turn_start_choice')
def golden_aura_start_choice(engine: Any, actor: Any) -> None:
    from .. import zones
    for zone in zones.typed_zones(engine):
        if zone.trigger_profile.get('golden_ally_choices') and zones.actor_inside_zone(engine,actor,zone):
            _ask_aura(engine,zone,actor,getattr(engine,'_active_intent',None))
    if any(z.active and z.trigger_profile.get('golden_ally_choices') for z in engine.state.zones.values()):
        zones.sync_inside(engine, PREFIX+'golden_aura')


@hook('zone_arrival')
def golden_aura_arrival(engine: Any, mover: Any, start: Any, end: Any, forced: bool) -> None:
    from .. import zones
    for zone in zones.typed_zones(engine):
        if not zone.trigger_profile.get('golden_ally_choices'):
            continue
        if zone.owner_id != mover.entity_id:
            if not zones.actor_inside_zone(engine,mover,zone,start) and zones.actor_inside_zone(engine,mover,zone,end):
                _ask_aura(engine,zone,mover,getattr(engine,'_active_intent',None))
        else:
            for subject in engine.state.actors.values():
                if subject.active and engine.grid.distance_ft(start,subject.position)>10 and engine.grid.distance_ft(end,subject.position)<=10:
                    _ask_aura(engine,zone,subject,getattr(engine,'_active_intent',None))


@effect('golden_aura_inclusion')
def golden_aura_inclusion(ctx: Any, row: dict[str, Any]) -> None:
    from .. import zones
    if ctx.target is None or ctx.target is ctx.actor or ctx.target.team_id!=ctx.actor.team_id:
        return
    for zone in zones.typed_zones(ctx.engine):
        if zone.owner_id==ctx.actor.entity_id and zone.trigger_profile.get('golden_ally_choices') and zones.actor_inside_zone(ctx.engine,ctx.target,zone):
            _aura_choice(ctx.engine,zone,ctx.target,bool(row['include']))
    zones.sync_inside(ctx.engine,ctx.source)


@hook('candidate_allowed')
def golden_command_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = ((getattr(action,'parameters',None) or {}).get('typed') or {})
    if any(r.get('type')=='golden_aura_inclusion' for r in typed.get('effects') or []):
        if candidate.target_ids == (actor.entity_id,):
            return False
        return any(z.active and z.owner_id==actor.entity_id and z.trigger_profile.get('golden_ally_choices') for z in engine.state.zones.values())
    return None


@effect('radiant_fist_light')
def radiant_fist_light(ctx: Any, row: dict[str, Any]) -> None:
    """Same native visual-light/anchor/owner-turn contract as Wax Candlelight."""
    from .. import zones
    from ..gate2_runtime_models import ZoneState
    from .effect_durations import next_owner_turn
    if ctx.target is None or not any(r.get('feature_id')==PREFIX+'radiant_fist' for r in _rows(ctx.engine,ctx.actor,'paid_hit')):
        return
    for zone in list(ctx.engine.state.zones.values()):
        if zone.active and zone.owner_id==ctx.actor.entity_id and zone.trigger_profile.get('name')=='Radiant Fist: Dim Light' and zone.trigger_profile.get('anchor_id')==ctx.target.entity_id:
            zones.remove(ctx.engine,zone,'REFRESHED')
    zid=f'zone:goruden:light:{ctx.engine.state.event_sequence+1}'
    zone=ZoneState(zone_id=zid,source_definition_id=ctx.source,owner_id=ctx.actor.entity_id,
                   center=ctx.target.position,radius_cells=10//ctx.engine.grid.square_size_ft,
                   affected_cells=(ctx.target.position,),concentration_link=False,duration_rounds=None,
                   created_round=ctx.engine.state.round_number,
                   trigger_profile={'kind':zones.KIND,'name':'Radiant Fist: Dim Light','anchor_id':ctx.target.entity_id,
                                    'visual':{'material':'radiance','light':{'radius_ft':10,'level':'dim'}},
                                    'start_of_owner_turn':next_owner_turn(ctx.actor),'triggers':[],'inside':[],'numbers':{}})
    ctx.engine.state.zones[zid]=zone
    ctx.engine._append_event('ZONE_CREATED',ctx.source,actor_id=ctx.actor.entity_id,payload={'zone':zone.model_dump(mode='json')})
    note(ctx.engine,ctx.source,ctx.actor,f'Radiant Fist: {ctx.target.display_name} sheds Dim Light for 10 feet until the start of {ctx.actor.display_name}’s next turn; no additional cost.')


@hook('row_allowed')
def immortal_gold_checkpoint(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    """One survival implementation; saved ownership/cost/use rows stay authoritative."""
    if (_rows(engine, actor, 'immortal_gold_final')
            and row.get('feature_id') == PREFIX+'immortal_gold'
            and row.get('native_checkpoint') != 'IMMORTAL_GOLD'):
        return False
    return None


@hook('lethal_damage')
def immortal_gold_rescue(engine: Any, target: Any, amount: int, damage_type: str,
                         source_id: str, source_actor_id: str | None, intent: Any) -> int | None:
    if not _rows(engine, target, 'immortal_gold_final'):
        return None
    from ..damage_allocation import lethal_threshold
    from ..typed_executor import condition_rules
    from .life_state import massive
    from ..typed_reactions import commit_checkpoint_response, triggered_context
    loss = lethal_threshold(engine,target,amount,source_actor_id,source_id=source_id,damage_type=damage_type)
    if (target.current_hp<=0 or loss<target.current_hp or loss-target.current_hp>=massive(engine,target)
            or any(r.get('death_prevention_denied') for r in condition_rules(target))):
        return None
    attacker=engine.state.actors.get(source_actor_id)
    # This feature takes no Action or Reaction. The general reaction admission
    # helper rejects reaction_denied even for a free row, so this family's
    # self-trigger reads its actual acquired costs and use counter directly.
    from ..resource_costs import as_dict
    saved = next((r for r in (getattr(engine, 'typed_reaction_rows', {}) or {}).get(target.entity_id, ())
                  if r.get('block') == 'generic' and r.get('feature_id') == PREFIX+'immortal_gold'), None)
    if saved is None:
        return None
    row = {**saved, 'native_checkpoint':'IMMORTAL_GOLD'}
    if any(target.resources.get(c['resource_id'], 0) < c['amount']
           for raw in row.get('costs') or () if (c := as_dict(raw))):
        return None
    from .needle import ask,checkpoint_id
    from .choice_prompt import action_context
    picked=ask(engine,intent,checkpoint_id(engine,'immortal_gold',target.entity_id),target,
               'choice:needle.goruden.immortal_gold',['survive'],allow_decline=True,
               labels={'survive':'Spend 6 Stamina: remain at 1 HP as a golden statue'},
               name='Immortal Gold',feature_id=PREFIX+'immortal_gold',target_id=target.entity_id,
               prompt=f'Immortal Gold: {target.display_name} would reach 0 HP. Spend 6 Stamina and your once-per-scene use, with no action or Reaction? Remain at 1 HP as an aware, Incapacitated statue until your next turn; then heal 5 times Proficiency Bonus and start Golden Aura for free.',
               prompt_context={**action_context(engine,attacker,source_id,target),
                               'cost':'6 Stamina; once per scene; no action or Reaction'})
    if not picked:
        return None
    commit_checkpoint_response(engine,target,target,row,'IMMORTAL_GOLD')
    if not target.active or target.current_hp <= 0:
        return None
    ctx=triggered_context(engine,target,target,row,intent)
    golden_statue(ctx,{})
    return 1


@effect('goruden_radiant_damage')
def radiant_damage(ctx: Any, row: dict[str, Any]) -> None:
    """Static creature kinds or an actual active, source-scoped corruption effect."""
    from .creature_kinds import matches
    from ..observer_information import SOURCE, sources
    from ..typed_executor import is_active_typed_condition, run_effects
    if ctx.target is None or not any(r.get('feature_id')==PREFIX+'radiant_fist'
                                    for r in _rows(ctx.engine,ctx.actor,'paid_hit')):
        return
    corrupted = any(s.get('holder_id')==ctx.target.entity_id
                    and 'daemonic_corruption' in s.get('tags',())
                    and s.get('condition') is not None
                    and (s['condition'].condition_id == SOURCE or is_active_typed_condition(s['condition']))
                    for s in sources(ctx.engine))
    doubled = corrupted or matches(ctx.target,['undead','fiend','daemonic','daemonic corruption'])
    run_effects(ctx,[{'type':'extra_damage','applies_to':'target',
                     'formula':'double_pb' if doubled else 'pb','damage_types':['radiant']}])


@hook('settings_batch_key')
def sheen_cosmetic_setting(action: Any) -> tuple | None:
    """Existing journaled off-turn settings transport; cosmetic state only."""
    typed = (action.parameters or {}).get('typed') or {}
    effects = typed.get('effects') or []
    if (typed.get('source') == PREFIX+'golden_sheen' and len(effects) == 1
            and effects[0] in ({'type':'golden_sheen_visibility','visible':0},
                               {'type':'golden_sheen_visibility','visible':1})):
        return ('goruden', 'visible_sheen')
    return None


@hook('compile_bundle')
def seal_sheen_calculation(bundle: dict[str, Any], info: dict[str, Any]) -> dict[str, Any] | None:
    if any(r.get('kind') == 'golden_sheen' for r in bundle.get('typed_passives') or ()):
        # The projection already records the actual chosen AC calculation.
        # Seal that native provenance on this family's passive; no new mode or
        # numerical guess is introduced. Historical sheets retain their policy.
        import json
        ac = info['owner_sheet']['ability_scores_and_statistics'].get('armor_class') or {}
        if isinstance(ac, str):
            ac = json.loads(ac)
        generation = ac.get('generation') if isinstance(ac, dict) else None
        if isinstance(generation, dict) and 'calculation_feature_id' in generation:
            selected = generation['calculation_feature_id'] == 'tianxia.path.body_refining.feature.unarmored_defense'
            for passive in bundle['typed_passives']:
                if passive.get('kind') == 'golden_sheen' and passive.get('feature_id') == PREFIX+'golden_sheen':
                    passive['unarmored_defense_selected'] = selected
    return bundle


def aura_benefit_choices(engine: Any, subject: Any, intent: Any) -> bool:
    """Collect source-owner inclusion at an actual benefit, never a quote."""
    from .. import zones
    if subject is None:return False
    if not any(z.active and z.trigger_profile.get('golden_ally_choices')
               for z in (getattr(getattr(engine,'state',None),'zones',{}) or {}).values()):
        return False
    eligible=False
    for zone in zones.typed_zones(engine):
        owner=engine.state.actors.get(zone.owner_id)
        if (not zone.trigger_profile.get('golden_ally_choices') or owner is None
                or owner is subject or owner.team_id!=subject.team_id
                or not zones.actor_inside_zone(engine,subject,zone)):
            continue
        _ask_aura(engine,zone,subject,intent)
        eligible=True
    if eligible:zones.sync_inside(engine,PREFIX+'golden_aura')
    return eligible


@hook('before_damage_defenses')
def aura_before_necrotic_damage(engine: Any, subject: Any, amount: int, kind: str,
                               source: str, source_actor_id: str | None) -> None:
    if amount>0 and str(kind).upper()=='NECROTIC':
        aura_benefit_choices(engine,subject,getattr(engine,'_active_intent',None))


@hook('save')
def aura_before_frightened_save(ctx: Any, subject: Any, ability: str, named: Any) -> None:
    if 'frightened' in {str(n).removeprefix('category:') for n in named or ()}:
        # Native condition modes are read by _roll_save after this transactional
        # save hook. The chosen aura rule supplies ordinary, cancellable Advantage.
        aura_benefit_choices(ctx.engine,subject,ctx.intent)

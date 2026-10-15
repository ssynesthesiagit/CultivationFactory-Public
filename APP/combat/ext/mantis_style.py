"""Mantis Style's source-owned five-feature native progression.

Acquisition consumes journey_acquisition, fact input consumes the named owner's
fact_consent_admission, and diagnosis publishes through observer_information.
Hit choices use the native transactional transport before damage. Physical
Grapples reuse hand_occupancy/grapple_parts and their evented lifecycle. Each
callback is inert without its acquired row or attributed persistent condition.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from copy import deepcopy

PREFIX = "tianxia.subpath.body.mantis_style.feature."
EYE = "condition:typed.eye_of_the_mantis"
LOCK = "condition:typed.joint_lock"


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "mantis"}


def _row(engine: Any, actor: Any) -> dict[str, Any]:
    return next((r for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
                 if r.get("block") == "path_rider" and r.get("kind") == "mantis"), {})


def _stamp(engine: Any) -> str:
    current=engine.state.actors[engine.state.current_actor_id]
    return f"{engine.state.round_number}:{engine.state.current_slot_index}:{current.entity_id}:{current.turns_started}"


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


def _grip(target: Any, owner: Any) -> Any:
    return next((c for c in target.conditions.values() if c.condition_id.endswith(".grappled") and c.source_actor_id == owner.entity_id), None)


def _eye(target: Any, owner: Any) -> Any:
    return next((c for c in target.conditions.values() if c.condition_id == EYE and c.source_actor_id == owner.entity_id), None)


# ------------------------------------------------------------------------------------------------ Mantis Hooks
@hook("confirmed_hit_damage_dice")
def hooks_light_blow(engine, actor, target, spec, intent, source, critical):
    """Choose total normal-damage replacement before the first damage die."""
    from .attack_scope import current
    from .needle import ask, checkpoint_id
    from ..gate2_runtime_models import DiceSpec
    frame = current(engine)
    if (not frame or frame['actor_id'] != actor.entity_id or frame['source'] != source
            or frame['effect'].get('attack_kind') != 'unarmed' or 'hooks' not in _roles(engine,actor)
            or actor.turn_flags.get('_round_mantis_hooks') == _stamp(engine)):
        return None
    ctx=frame['context']
    if not grapple_legal(ctx,target):return None
    modifier=max(0,int((ctx.typed.get('weapon') or {}).get('ability_modifier') or 0))
    picked=ask(engine,intent,checkpoint_id(engine,'mantis_light',target.entity_id),actor,
        'choice:needle.mantis_hooks_light',['light'],allow_decline=True,default='decline',
        labels={'light':f'Deal only {modifier} damage; the Grapple save has Disadvantage'},
        name='Mantis Hooks',target_id=target.entity_id,
        prompt=f'Mantis Hooks: {ctx.action.display_name} hit {target.display_name}. Before any damage dice, reduce all normal damage to your attack ability modifier? No cost.')
    if not picked:return None
    spec['fixed_damage']=modifier
    spec['normal_damage_replaced']=True
    ctx.damage_cache['_mantis_light_target']=target.entity_id
    return DiceSpec(count=1,sides=4,modifier=0)


def mantis_parts(engine,actor):
    """Read actual free manipulators from the public native anatomy contracts."""
    from .hand_occupancy import free_hands,occupancy
    from . import query
    occupied=occupancy(engine,actor)
    parts=[{'id':key,'label':key.removeprefix('hand:').replace('_',' ').title()+' hand'}
        for key in free_hands(engine,actor)]
    parts.extend(p for group in query('grappling_body_parts',engine,actor) for p in (group or [])
        if isinstance(p,dict) and str(p.get('id','')).startswith('body:') and p['id'] not in occupied)
    return {p['id']:str(p.get('label') or 'Eligible body part') for p in parts}


def grapple_legal(ctx,target):
    from ..typed_executor import size_rank
    from ..attack_reach import maximum
    save={'type':'save','max_size_larger':1,'on_fail':[{'type':'condition','condition':'grappled'}]}
    return (target is not None and target.active and ctx.actor.active
        and bool(mantis_parts(ctx.engine,ctx.actor))
        and ctx.engine._distance_actor_to_actor(ctx.actor,target)<=maximum(ctx.engine,ctx.actor,ctx.action,base=5)
        and size_rank(ctx,target,'subject',save)<=size_rank(ctx,ctx.actor,'actor',save)+1)


@hook("after_hit")
def mantis_hooks(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    light = ctx.damage_cache.pop("_mantis_light_target", None) == getattr(target,"entity_id",None)
    if kind != "unarmed" or target is None or not target.active or "hooks" not in _roles(engine, actor):
        return
    if actor.turn_flags.get("_round_mantis_hooks") == _stamp(engine) or not grapple_legal(ctx,target):
        return
    from .needle import ask, checkpoint_id

    picked = ask(engine, ctx.intent, checkpoint_id(engine, "mantis_hooks", target.entity_id), actor, "choice:needle.mantis_hooks", ["grapple"],
                 labels={"grapple": f"Grapple {target.display_name} (its Strength or Dexterity save)"}, allow_decline=True, target_id=target.entity_id,
                 name="Mantis Hooks", prompt=f"Mantis Hooks: {ctx.action.display_name} hit {target.display_name}. Attempt a Grapple without another action or Stamina? It lasts until released, escaped, or the hold becomes invalid.")
    if not picked:
        return
    parts=mantis_parts(engine,actor)
    if not parts:return
    selected=ask(engine,ctx.intent,checkpoint_id(engine,'mantis_part',target.entity_id),actor,
        'choice:needle.mantis_grappling_part',list(parts),labels=parts,target_id=target.entity_id,
        name='Mantis Hooks',prompt=f'Mantis Hooks: choose the free hand or eligible body part that holds {target.display_name}. No additional action or Stamina; the part maintains the Grapple until it ends.') if len(parts)>1 else [next(iter(parts))]
    if not selected:return
    actor.turn_flags["_round_mantis_hooks"] = _stamp(engine)
    from .. import typed_executor as te

    dc = int(_row(engine, actor).get("save_dc") or (ctx.typed.get("numbers") or {}).get("save_dc") or 10)
    save = {"type": "save", "ability": "STR_OR_DEX", "target_choice": True, "name": "Mantis Hooks", "max_size_larger": 1, "evidence": "Mantis Hooks: Strength or Dexterity save (the target's choice)",
            "on_fail": [{"type": "condition", "condition": "grappled", "applies_to": "target", "until_escape": True, "grappling_part": selected[0], "condition_data": {"source_cl": int(ctx.numbers["cl"]), "escape_dc": dc}}]}
    engine.__dict__["_mantis_hooked"] = target.entity_id if light else None
    try:
        te.run_effects(ctx.on_hit_context(target, action=ctx.action, effect_source=PREFIX+'mantis_hooks', typed={**ctx.typed, 'physical_grapple': True, 'effects': [save], 'numbers': {**(ctx.typed.get('numbers') or {}), 'save_dc': dc}}, damage_cache={}), [save])
    finally:
        engine.__dict__["_mantis_hooked"] = None


def _grapple_save(ctx: Any) -> bool:
    return any(isinstance(row, dict) and row.get("type") == "save" and row.get("max_size_larger") is not None
               and any(isinstance(f, dict) and f.get("condition") == "grappled" for f in row.get("on_fail") or []) for row in ctx.typed.get("effects") or [])


@hook("save")
def mantis_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if subject is None or ctx.actor is subject:
        return None
    engine, owner = ctx.engine, ctx.actor
    modes = []
    if engine.__dict__.get("_mantis_hooked") == subject.entity_id:
        modes.append("DISADVANTAGE")  # the light blow
    eye = _eye(subject, owner)
    if eye is not None and _grapple_save(ctx):
        modes.append("DISADVANTAGE")  # Eye of the Mantis: Advantage on your attempts to Grapple it
    if eye is not None and ctx.source.split("#")[0].endswith(PREFIX + "joint_lock") and eye.data.get("lock_turn") != _stamp(engine) \
            and engine.state.current_actor_id == owner.entity_id:
        modes.append("DISADVANTAGE")  # its first save against Joint Lock during each of your turns
    return {"bonus": 0, "modes": modes} if modes else None


# ------------------------------------------------------------------------------------------------- Joint Lock
@hook("candidate_allowed")
def lock_needs_your_grapple(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {})
    if not any(isinstance(e, dict) and e.get("type") == "joint_lock" for e in typed.get("effects") or []):
        return None
    targets = [engine.state.actors.get(t) for t in (getattr(candidate, "target_ids", None) or ())]
    return None if targets and all(t is not None and _grip(t, actor) is not None and engine._distance_actor_to_actor(actor,t)<=int(_grip(t,actor).data.get('reach_ft',5)) for t in targets) else False


@effect("joint_lock")
def joint_lock(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    target = ctx.target
    grip = _grip(target, ctx.actor) if target is not None else None
    if grip is None:
        return
    te.run_effects(ctx, [{"type": "save", "ability": "dex", "evidence": "Joint Lock: Dexterity saving throw",
                          "on_fail": [{"type": "joint_lock_hold", "grip": grip.instance_id}],
                          "on_success": [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN"}]}])


@effect("joint_lock_hold")
def joint_lock_hold(ctx: Any, row: dict[str, Any]) -> None:
    """Restrained until the start of your next turn or until that Grapple ends (never longer: a new one replaces it)."""
    target = ctx.target
    if target is None or not target.active or row.get("grip") not in target.conditions:
        return
    from ..typed_executor import condition_immune
    if condition_immune(ctx.engine, target, "restrained") or condition_immune(ctx.engine, target, "joint_lock"):
        return
    for iid, held in list(target.conditions.items()):
        if held.condition_id == "condition:typed.restrained" and (held.data or {}).get("joint_lock_grip") and held.source_actor_id == ctx.actor.entity_id:
            del target.conditions[iid]
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(target.entity_id,),
                                     payload={"condition_id": held.condition_id, "instance_id": iid, "reason": "REFRESHED"})
    ctx.engine._apply_condition(target, "condition:typed.restrained", ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"joint_lock_grip": row["grip"], "source_cl": int(ctx.numbers["cl"]), "label": "Joint Lock: Restrained while the Grapple lasts"})


@hook("event")
def lock_ends_with_the_grapple(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_REMOVED":
        return
    ended = (kwargs.get("payload") or {}).get("instance_id")
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        for iid, held in list((target.conditions if target is not None else {}).items()):
            if (held.data or {}).get("joint_lock_grip") == ended:
                del target.conditions[iid]
                engine._append_event("CONDITION_REMOVED", PREFIX + "joint_lock", actor_id=held.source_actor_id, target_ids=(target_id,),
                                     payload={"condition_id": held.condition_id, "instance_id": iid, "reason": "GRAPPLE_ENDED"})


# ----------------------------------------------------------------------------------------------- Rapid Pincer
@hook("compile_actions")
def rapid_pincer(info: dict[str, Any]) -> list[Any] | None:
    # Source-owned acquisition projection: seal the ability already selected by
    # the natural-weapon producer. Legacy natural attacks omit this component;
    # damage totals cannot distinguish it from other attack damage bonuses.
    if any(str(mid).startswith(PREFIX) for mid in info['owned_ids']):
        for base in info['actions']:
            typed=base.parameters.get('typed') or {}
            weapon=typed.get('weapon') or {}
            ability=weapon.get('ability')
            if ability in info['mods'] and any(e.get('type')=='attack' and e.get('attack_kind')=='unarmed' for e in typed.get('effects') or []):
                from .attack_abilities import option_scopes
                ordinary=['STR','CON'] if typed.get('source')=='tianxia.path.body_refining.feature.iron_fist' else [ability]
                allowed,_=option_scopes(ordinary,{**info,'kind':'unarmed','source':typed.get('source')})
                base.parameters['typed']={**typed,'weapon':{**weapon,'ability_modifier':int(info['mods'][ability])},
                    'mantis_ordinary_abilities':{key:int(info['mods'][key]) for key in allowed}}
    mechanic = info["mechanics"].get(PREFIX + "rapid_pincer") or {}
    if PREFIX + "rapid_pincer" not in info["owned_ids"] or not any(isinstance(e, dict) and e.get("kind") == "mantis" and e.get("role") == "pincer"
                                                                  for e in mechanic.get("effects") or []):
        return None
    import copy

    from ..gate2_runtime_models import EconomyKind

    out = []
    for base in info["actions"]:
        typed = (base.parameters or {}).get("typed") or {}
        if base.economy != EconomyKind.ACTION or ".natural." not in base.source_definition_id or "#" in base.source_definition_id \
                or (base.parameters or {}).get("player_only") or not typed.get("weapon"):
            continue
        variant = copy.deepcopy(typed)
        for eff in variant.get('effects') or []:
            if isinstance(eff,dict) and eff.get('type')=='attack' and eff.get('attack_kind')=='unarmed':
                eff['count']=int(eff.get('count') or 1)+1
                if eff.get('count_by_cl'):
                    eff['count_by_cl']=[[low,high,int(n)+1] for low,high,n in eff['count_by_cl']]
                break
        original_count=next((int(e.get('count') or 1) for e in typed.get('effects') or [] if e.get('type')=='attack'),1)
        for e in typed.get('effects') or []:
            if e.get('type')=='attack':
                for low,high,n in e.get('count_by_cl') or []:
                    if low<=int(info['numbers'].get('cl') or 1)<=high:original_count=int(n);break
                break
        out.append(base.model_copy(update={"source_definition_id": base.source_definition_id + "#rapid_pincer",
                                           "display_name": base.display_name + " (Rapid Pincer)",
                                           "parameters": {**base.parameters, "rapid_pincer": True, "typed": variant,
                                                          "expected_damage": int(base.parameters.get("expected_damage") or 0) * (original_count+1) // original_count}}))
    return out or None


@hook("candidate_allowed")
def pincer_once_per_turn(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not (getattr(action, "parameters", None) or {}).get("rapid_pincer"):
        return None
    return False if actor.turn_flags.get("_round_rapid_pincer") == _stamp(engine) else None


@hook("action_completed")
def pincer_used(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    if str(source_definition_id).endswith("#rapid_pincer"):
        actor.turn_flags["_round_rapid_pincer"] = _stamp(engine)


# --------------------------------------------------------------------------------------------- Eye of the Mantis
@effect("eye_of_the_mantis")
def eye_of_the_mantis(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .. import observer_information as information
    engine,owner,target=ctx.engine,ctx.actor,ctx.target
    if target is None or not target.active:return
    from ..stealth import sees
    if engine._distance_actor_to_actor(owner,target)>60 or not sees(engine,owner,target):return
    for iid,held in list(target.conditions.items()):
        if held.condition_id==EYE and held.source_actor_id==owner.entity_id:
            engine._remove_condition_instance(target,iid,PREFIX+'eye_of_the_mantis',expected=held)
    expires=te.clock_expiry(engine,'minutes',1) or 'UNTIL_REMOVED'
    engine._apply_condition(target,EYE,PREFIX+'eye_of_the_mantis',owner.entity_id,expires_on=expires,
        data={'label':f'Eye of the Mantis ({owner.display_name})','source_cl':int(ctx.numbers['cl'])})
    details=diagnosis(ctx,target)
    publish_diagnosis(engine,owner,ctx.source,target,details,expires)
    note(engine,PREFIX+'eye_of_the_mantis',owner,
        f'Eye of the Mantis on {target.display_name}: a private diagnosis is available to {owner.display_name}; benefits last 1 minute, ending beyond 1 mile.',(target,))


@hook("attack_mode")
def eye_first_attack(ctx: Any, target: Any) -> str | None:
    if target is None:
        return None
    eye = _eye(target, ctx.actor)
    if eye is None or eye.data.get("attack_turn") == _stamp(ctx.engine):
        return None
    return "ADVANTAGE"


PARENT=PREFIX.removesuffix('.feature.')
LEVELS={'mantis_hooks':3,'joint_lock':6,'rapid_pincer':10,'eye_of_the_mantis':14,'death_of_a_thousand_cuts':18}
CUTS='condition:typed.mantis_cuts_next_save'


@hook('journey_source_sheet')
def acquired_sheet(sheet,session,actor_id):
    saved=session.state['actors'][actor_id].get('source_states',{}).get(PARENT,{}).get('sheet')
    if saved:
        sheet=deepcopy(sheet)
        sheet['path_and_subpath']=deepcopy(saved)
        return sheet
    return None


@hook('journey_acquisition')
def acquire(session,actor_id,source,payload,sheet):
    """Open School selection derives earned milestones, never accepts feature IDs."""
    if source!=PARENT:return None
    from ..journey import require
    from ..canonical import canonical_sha256
    require(payload=={'operation':'select'},'Choose Mantis Style; feature IDs and fabricated receipts are not accepted.')
    identity=sheet.get('identity') or {}
    require(identity.get('path')=='Body Refining','Mantis Style requires the Body Refining Path.')
    cl=identity.get('cultivation_level')
    require(type(cl) is int and cl>=3,'Mantis Style requires Body Refining CL3.')
    paths=deepcopy(sheet.get('path_and_subpath') or {})
    bindings=paths.get('bindings') or []
    prior={paths.get('subpath_record_id'),*(paths.get('subpath_record_ids') or [])}
    prior|={b.get('subpath_id') for b in bindings if b.get('path_id')=='tianxia.path.body_refining'}
    prior|={r.get('subpath_id') for r in paths.get('subpaths',[]) if r.get('owning_path_id')=='tianxia.path.body_refining'}
    features=list(paths.get('path_feature_record_ids') or [])
    require(not any(s and s!=PARENT and str(s).startswith('tianxia.subpath.body.') for s in prior)
        and not any(s.startswith('tianxia.subpath.body.') and not s.startswith(PREFIX) for s in features),
        'Choose one Body Refining Subpath; changing it requires its actual replacement procedure.')
    earned=[PREFIX+f for f,level in LEVELS.items() if cl>=level]
    paths['path_feature_record_ids']=list(dict.fromkeys([*features,*earned]))
    paths['subpath_record_id']=PARENT
    paths['subpath_record_ids']=[PARENT]
    paths['bindings']=[b for b in bindings if b.get('path_id')!='tianxia.path.body_refining']+[
        {'path_id':'tianxia.path.body_refining','subpath_id':PARENT}]
    receipt=canonical_sha256({'source':source,'actor':actor_id,'cl':cl,'earned':earned,'revision':session.state['revision']})
    paths['subpath_acquisition']={'source_rule':PARENT,'route':'open_school','earned_features':earned,
        'path_level':cl,'access_receipt':receipt,'clock':int(session.clock())}
    session.state['actors'][actor_id].setdefault('source_states',{}).setdefault(PARENT,{})['sheet']=deepcopy(paths)
    sheet['path_and_subpath']=paths
    session.emit('SOURCE_ACQUIRED',actor_id,source=source,acquisition_id=receipt,earned_features=earned,source_cl=cl)
    return {'sheet':sheet,'acquisition_id':receipt}


@hook('choice_reactors')
def mantis_choices(engine):
    if any(_roles(engine,a) for a in engine.state.actors.values()):return tuple(engine.state.actors)
    return None


@hook('attack_sequence_strike')
def pincer_strike(ctx,attack,declared_target,index,count):
    """Own per-strike target/ancestry choices within the ordinary attack loop."""
    if not ctx.action.parameters.get('rapid_pincer') or 'pincer' not in _roles(ctx.engine,ctx.actor):return None
    from .needle import ask,checkpoint_id
    from ..attack_declaration import can_target
    key='_mantis_pincer_replace'
    if index==1:
        if ctx.typed.get('granted_attack') or ctx.actor.turn_flags.get('_round_rapid_pincer')==_stamp(ctx.engine):
            raise ValueError('Rapid Pincer is available only once per turn during an Attack action.')
        selected=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'pincer_replace',ctx.source),ctx.actor,
            'choice:needle.pincer_replace',[str(i+1) for i in range(count-1)],
            labels={str(i+1):f'Replace strike {i+1} with two unarmed strikes' for i in range(count-1)},
            prompt=f'Rapid Pincer: choose one strike of {ctx.action.display_name} to replace. Once this turn; no additional action or Stamina.',name='Rapid Pincer')
        ctx.damage_cache[key]=int(selected[0])
        ctx.actor.turn_flags['_round_rapid_pincer']=_stamp(ctx.engine)
    recipient_action=ctx.action.model_copy(update={'parameters':{**ctx.action.parameters,'rapid_pincer':False}})
    options=[t for t in ctx.engine.state.actors.values() if t.active
        and can_target(ctx.engine,ctx.actor,t,ctx.source,action=recipient_action,effect=attack,index=index)]
    if not options:return {'target_id':None,'additional_attack':False}
    from ..relations import relation,ENEMY
    automatic=[t.entity_id for t in options if relation(ctx.engine,ctx.actor,t)==ENEMY]
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'pincer_target',str(index)),ctx.actor,
        'choice:needle.pincer_target',[t.entity_id for t in options],
        labels={t.entity_id:f'Unarmed strike {index}: {t.display_name}' for t in options},
        preferred=[declared_target.entity_id] if declared_target in options else [options[0].entity_id],
        automatic_options=automatic,name='Rapid Pincer',prompt=f'Rapid Pincer: choose the creature for strike {index}; resolve this strike before the next.')
    return {'target_id':picked[0] if picked else None,'additional_attack':index==ctx.damage_cache[key]+1}


@hook('damage_packet_selection')
def cuts_at_hit(ctx,target,packet_kinds):
    """Named source consumer on the existing confirmed-hit packet seam."""
    if (getattr(ctx,'attack_effect',None) or {}).get('attack_kind')!='unarmed':return
    rows=(getattr(ctx.engine,'typed_passive_rows',{}) or {}).get(ctx.actor.entity_id,[])
    row=next((r for r in rows if r.get('feature_id')==PREFIX+'death_of_a_thousand_cuts'),None)
    if not row or ctx.actor.resources.get('resource:core.stamina',0)<4:return
    if ctx.actor.turn_flags.get('_round_mantis_cuts')==_stamp(ctx.engine):return
    from .needle import ask,checkpoint_id
    labels={'No Reactions':f'{target.display_name} cannot take Reactions until the start of its next turn',
        'Speed 0':f'{target.display_name}\'s Speed becomes 0 until the start of its next turn',
        'Disadvantage on its next Concentration save':'Disadvantage on its next Concentration save before the end of your next turn',
        'Disadvantage against your Grapple or Joint Lock':'Disadvantage on its next save against being Grappled or Joint Lock before the end of your next turn',
        'Drop a held object':'Dexterity save; on failure, drop one perceived, nonartifact held object'}
    objects=drop_options(ctx,target)
    if not objects:labels.pop('Drop a held object')
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'path_hit',row['feature_id'],target.entity_id),ctx.actor,
        'choice:needle.path_hit.'+row['feature_id'],list(labels),labels=labels,allow_decline=True,
        name='Death of a Thousand Cuts',target_id=target.entity_id,
        prompt=f'Death of a Thousand Cuts: {ctx.action.display_name} hit {target.display_name}. Pay 4 Stamina for +6d6 Piercing and exactly one rider; once this turn.')
    if not picked:return
    choice=picked[0]
    item=None
    if choice=='Drop a held object':
        obj=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'mantis_drop',target.entity_id),ctx.actor,
            'choice:needle.mantis_drop',list(objects),labels={k:v['name'] for k,v in objects.items()},
            target_id=target.entity_id,name='Death of a Thousand Cuts',
            prompt=f'Choose one nonartifact object held by {target.display_name}; a failed Dexterity save drops it in its space.')
        item=objects[obj[0]]
    ctx.engine._spend_resource(ctx.actor,'resource:core.stamina',4,row['feature_id'])
    ctx.actor.turn_flags['_round_mantis_cuts']=_stamp(ctx.engine)
    from .. import typed_executor as te
    spec=ctx.attack_defense_spec
    if not spec.get('normal_damage_replaced'):
        # Piercing joins a Piercing primary packet before defenses. For another
        # primary type, preserve attack provenance and one per-type component.
        from ..gate2_runtime_models import DiceSpec
        dice=DiceSpec(count=6,sides=6,modifier=0)
        roll=ctx.engine.roller.roll(dice,actor_id=ctx.actor.entity_id,reason='MANTIS_CUTS_DAMAGE',critical=ctx.critical_hit)
        ctx.engine._record_roll(roll)
        if spec.get('damage_type')=='PIERCING':
            spec['damage']=spec['damage'].model_copy(update={'modifier':spec['damage'].modifier+roll.total})
        else:
            spec.setdefault('damage_components',[]).append((roll.total,'PIERCING'))
    if choice=='No Reactions':
        te.run_effects(ctx,[{'type':'reaction_denied','applies_to':'target','expires_on':'START_OF_TARGET_NEXT_TURN'}])
    elif choice=='Speed 0':
        te.run_effects(ctx,[{'type':'speed','applies_to':'target','becomes':0,'expires_on':'START_OF_TARGET_NEXT_TURN'}])
    elif choice.startswith('Disadvantage'):
        kind='concentration' if choice=='Disadvantage on its next Concentration save' else 'grapple'
        for held in list(target.conditions.values()):
            if held.condition_id==CUTS and held.data.get('kind')==kind:
                ctx.engine._remove_condition_instance(target,held.instance_id,ctx.source,expected=held)
        ctx.engine._apply_condition(target,CUTS,row['feature_id'],ctx.actor.entity_id,
            expires_on=f'END_OF_SOURCE_TURN_AT:{int(ctx.actor.turns_started)+1}',
            data={'kind':kind,'source_cl':int(row['cl']),'label':labels[choice]})
    else:
        # Selection happens before the save, with a stable object identity.
        te.run_effects(ctx,[{'type':'save','ability':'dex','on_fail':[
            {'type':'mantis_drop','object':item['object']}]}])


def drop_options(ctx,target):
    from .scoundrel_riders import held_possessions,can_drop_held_object
    from ..stealth import sees
    if not sees(ctx.engine,ctx.actor,target):return {}
    return {item['object']:item for item in held_possessions(ctx.engine,target)
        if can_drop_held_object(ctx.engine,target,item)
        and not any(item.get(flag) for flag in ('integrated','body_part','worn'))}


@effect('mantis_drop')
def drop_object(ctx,row):
    from .scoundrel_riders import drop_held_object
    item=drop_options(ctx,ctx.target).get(row['object'])
    if item:drop_held_object(ctx.engine,ctx.target,item,source=ctx.source,by=ctx.actor)


@hook('save')
def cuts_save(ctx,subject,ability,named):
    if ctx is None or not ('grappled' in (named or ()) or ctx.source.endswith(PREFIX+'joint_lock')):return None
    return consume_cuts(ctx.engine,subject,'grapple')


def consume_cuts(engine,subject,kind):
    held=[c for c in subject.conditions.values() if c.condition_id==CUTS and c.data.get('kind')==kind]
    if not held:return None
    for c in held:engine._remove_condition_instance(subject,c.instance_id,c.source_definition_id,expected=c)
    return {'bonus':0,'modes':['DISADVANTAGE']}


@hook('save_mode')
def cuts_concentration(engine,target,ability,dc,source,context):
    # The native concentration resolver names this roll; ordinary CON saves
    # are not proof that the target is maintaining Concentration.
    if source!='system:combat.concentration':return None
    return 'DISADVANTAGE' if consume_cuts(engine,target,'concentration') else None


@hook('presentation_hidden_conditions')
def private_eye(engine,actor):
    from ..observer_information import READING
    return [c.instance_id for c in actor.conditions.values() if c.condition_id==READING]


@hook('event')
def eye_distance(engine,event_type,kwargs):
    if event_type not in {'MOVEMENT_COMPLETED','ACTOR_MOVED','POSITION_CHANGED','CONDITION_REMOVED','TURN_STARTED'}:return
    for target in engine.state.actors.values():
        for c in list(target.conditions.values()):
            if c.condition_id!=EYE:continue
            owner=engine.state.actors.get(c.source_actor_id)
            if owner is None or engine._distance_actor_to_actor(owner,target)>5280:
                engine._remove_condition_instance(target,c.instance_id,c.source_definition_id,expected=c)


def diagnosis(ctx,target):
    """Read only current native mechanics, then honor attributed concealment."""
    from .. import typed_reactions, concentration
    from .. import ext
    from ..save_context import bonus_details
    saves={}
    for ability in ('STR','DEX','CON'):
        bonuses=ext.run_strict('save_bonus',ctx.engine,target,ability,0,'',None)
        detail,_=bonus_details(ctx.engine,target,ability,0,'',None)
        saves[ability]=int(target.saving_throws.get(ability,0))+sum(bonuses)+detail
    defenses=typed_reactions.defense_display(ctx.engine,target)
    suppressed={str(m.value).upper() for m in target.modifiers.values() if m.target_field=='resistance_suppressed'}
    def defense_types(tier):
        found=[]
        for entry in defenses[tier]:
            kind=entry.get('damage_type')
            if not kind:continue  # Condition immunities are outside the printed disclosure.
            if tier=='resistances' and kind.upper() in suppressed:continue
            if tier=='resistances' and kind=='All damage types' and suppressed:
                kind+=' except '+', '.join(k.title() for k in sorted(suppressed))
            label=kind+((' ('+entry['note']+')') if entry.get('note') else '')
            if label not in found:found.append(label)
        return sorted(found)
    physical={'grappled','restrained','prone','poisoned','stunned','paralyzed','blinded','deafened','exhaustion','burning','bleeding','slowed','petrified','unconscious','incapacitated'}
    result={'current_hp':target.current_hp,'maximum_hp':target.maximum_hp,
        'armor_class':target.armor_class+ctx.engine._ac_modifier(target),
        'resistances':defense_types('resistances'),
        'immunities':defense_types('immunities'),
        'concentration':int(bool(concentration.sources(target))),
        'physical_conditions':sorted({c.condition_id.rsplit('.',1)[-1] for c in target.conditions.values()
            if c.condition_id.rsplit('.',1)[-1] in physical}),
        'lowest_physical_saves':[k for k,v in saves.items() if v==min(saves.values())]}
    # Every live concealing source is explicit: either an authored active effect
    # profile or an admitted native table-owner fact, never inferred from prose.
    records=[]
    for held in target.conditions.values():
        profile=(held.data.get('information_profile') or {}).get('diagnosis_concealment')
        if profile:
            from ..observer_information import source_profile
            authority=source_profile(ctx.engine,held.source_definition_id,held.data).get('authority')
            records.append({**profile,'authority':'protected' if authority=='protected' else profile.get('authority','ordinary')})
    for profile in records:
        if int(profile.get('source_cl',0))<int(ctx.numbers['cl']) and profile.get('authority')!='protected':continue
        data=[k for k in profile.get('data',[]) if k in result]
        if not data:continue
        dc=int(profile['save_dc'])
        roll=ctx.engine.roll_check(modifier=int(ctx.numbers['pb'])+int(ctx.numbers['key_mod']),
            actor_id=ctx.actor.entity_id,reason='CHECK:'+ctx.source+':diagnosis',
            ability='CON',skill='Cultivation',against_creature=target)
        ctx.engine._record_roll(roll)
        ctx.engine._append_event('CHECK_ROLLED',ctx.source,actor_id=ctx.actor.entity_id,target_ids=(target.entity_id,),
            payload={'actor':roll.model_dump(mode='json'),'dc':dc,'success':roll.total>=dc,'check':'Cultivation Check (Eye of the Mantis)','history_hidden':True})
        if roll.total<dc:
            for key in data:result[key]='concealed'
    return result


@hook('fact_admission_schema')
def concealment_schema(session,source,subject,kind):
    if source!=PARENT or kind!='diagnosis_concealment':return None
    return {'value_type':'document','maximum_seconds':86400,'authority':'table_owner',
        'document_schema':{'type':'object','additionalProperties':False,
            'required':['effect_source','source_cl','save_dc','data'],
            'properties':{'effect_source':{'type':'string','minLength':1,'pattern':r'\S'},
                'source_cl':{'type':'integer','minimum':1},'save_dc':{'type':'integer','minimum':0},
                'authority':{'enum':['ordinary','protected']},'active':{'type':'integer','enum':[0,1]},
                'data':{'type':'array','minItems':1,'uniqueItems':True,
                    'items':{'enum':list(DIAGNOSIS_FIELDS)}}}},
        'description':'The native GM records the exact source, CL, save DC and listed data that an actual diagnosis-concealing effect protects.'}


def diagnosis_authority_profiles(session,actor_id):
    """Project current admissions or the actual native effects they created."""
    from ..fact_consent_admission import KEY,read,digest
    from fractions import Fraction
    from math import ceil
    from jsonschema import Draft202012Validator
    from ..journey import require
    ledger=session.state['actors'][actor_id].get('source_states',{}).get(PARENT,{}).get('wards',{})
    latest={}
    for rec in session.state.get(KEY,[]):
        if rec['source']==PARENT and rec['kind']=='diagnosis_concealment' and rec['subject']==actor_id:
            latest[rec['scope']]=rec
    # A newer declaration replaces its scope even after its own expiry. Native
    # continuation can carry an actual effect into a new journey without
    # fabricating a new admission or changing the original receipt.
    for saved in ledger.values():
        rec=saved['admission']
        latest.setdefault(rec['scope'],rec)
    profiles=[]
    validator=Draft202012Validator(concealment_schema(session,PARENT,actor_id,'diagnosis_concealment')['document_schema'])
    for rec in latest.values():
        require(rec.get('source')==PARENT and rec.get('subject')==actor_id
            and rec.get('kind')=='diagnosis_concealment' and rec.get('authority')=='table_owner'
            and rec.get('receipt_id')==digest({k:v for k,v in rec.items() if k!='receipt_id'}),
            'The continued diagnosis admission failed its source/authority/replay commitment.')
        saved=ledger.get(rec['receipt_id'])
        if saved is not None:
            if saved.get('ended'):continue
            remaining=Fraction(saved['expires_num'],saved['expires_den'])-session.clock()
            value=saved['value']
        else:
            live=read(session,PARENT,actor_id,rec['kind'],rec['scope'],actor_id)
            if not live or live['receipt_id']!=rec['receipt_id']:continue
            remaining=Fraction(live['expires_at'])-session.clock()
            value=live['value']
        if remaining<=0 or value.get('active',1)==0:continue
        require(validator.is_valid(value),'Name the actual concealing source, Source CL, save DC and listed diagnostic fields.')
        profiles.append({**deepcopy(value),'seconds':ceil(remaining),
            'remaining_num':remaining.numerator,'remaining_den':remaining.denominator,
            'receipt_id':rec['receipt_id'],'admission':deepcopy(rec)})
    return profiles


@hook('journey_combat_bundle')
def current_concealment_bundle(bundle,session,actor_id):
    profiles=diagnosis_authority_profiles(session,actor_id)
    if not profiles and 'mantis_diagnosis_authority' not in bundle:return None
    updated=deepcopy(bundle)
    if profiles:updated['mantis_diagnosis_authority']=profiles
    else:updated.pop('mantis_diagnosis_authority',None)
    return updated


@hook('journey_acquired')
def project_diagnosis_authority(session,actor_id,source,acquisition_id):
    if source!=PARENT:return
    from ..canonical import canonical_sha256
    for aid,actor in session.state['actors'].items():
        updated=current_concealment_bundle(actor['bundle'],session,aid)
        if updated is not None:
            updated.pop('bundle_sha256',None)
            updated['bundle_sha256']=canonical_sha256(updated)
            actor['bundle']=updated


DIAGNOSIS_FIELDS=('current_hp','maximum_hp','armor_class','resistances','immunities','concentration','physical_conditions','lowest_physical_saves')


def mantis_deadline(engine,remaining):
    """Convert an exact remaining duration to the next observable native slot."""
    from fractions import Fraction
    from math import ceil
    count=max(1,len(engine.state.initiative_order))
    now_slots=engine.state.round_number*count+engine.state.current_slot_index
    deadline=Fraction(now_slots*6,count)+remaining
    end_slot=ceil(deadline*count/6)
    return f'START_OF_SLOT_AT:{end_slot//count}:{end_slot%count}',deadline


@hook('match_initialize')
def initialize_concealment(engine):
    from fractions import Fraction
    for bundle in getattr(engine,'typed_bundle_documents',()):
        actor=engine.state.actors.get(bundle['actor_id'])
        if actor is None:continue
        for profile in bundle.get('mantis_diagnosis_authority',[]):
            remaining=Fraction(profile.get('remaining_num',profile['seconds']),profile.get('remaining_den',1))
            if remaining<=0:continue
            expiry,deadline=mantis_deadline(engine,remaining)
            engine._apply_condition(actor,'condition:typed.mantis_diagnosis_concealment',profile['effect_source'],actor.entity_id,
                expires_on=expiry,
                data={'information_profile':{'diagnosis_concealment':{**{k:profile[k] for k in ('source_cl','save_dc','data')},'authority':profile.get('authority','ordinary')}},
                    'authority':'table_owner','receipt_id':profile['receipt_id'],'label':'Concealed from supernatural diagnosis',
                    'mantis_deadline_num':deadline.numerator,'mantis_deadline_den':deadline.denominator})


@hook('attack_damage_type_choice')
def hooks_damage_type(ctx,effect,target,kinds,index):
    if effect.get('attack_kind')!='unarmed' or 'hooks' not in _roles(ctx.engine,ctx.actor) or len(kinds)<2:return None
    from .needle import ask,checkpoint_id
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'mantis_type',target.entity_id,str(index)),ctx.actor,
        'choice:needle.mantis_damage_type',list(kinds),labels={k:k.title()+' damage' for k in kinds},
        preferred=[kinds[0]],target_id=target.entity_id,name='Mantis Hooks',
        prompt=f'Mantis Hooks: choose the damage type of {ctx.action.display_name} against {target.display_name}. No cost.')
    return picked[0] if picked else None


@hook('movement_landed')
def reconcile_mantis_distance(engine,mover,previous,destination,intent,forced):
    for target in engine.state.actors.values():
        for c in list(target.conditions.values()):
            if not c.source_definition_id.endswith(PREFIX+'mantis_hooks') and c.condition_id!=EYE:continue
            owner=engine.state.actors.get(c.source_actor_id)
            limit=5280 if c.condition_id==EYE else int(c.data.get('reach_ft',5))
            if owner is None or engine._distance_actor_to_actor(owner,target)>limit:
                engine._remove_condition_instance(target,c.instance_id,c.source_definition_id,expected=c)


@hook('attack_roll_finished')
def eye_attack_spent(ctx,target,effect,roll_id):
    if not roll_id:return
    eye=_eye(target,ctx.actor)
    if eye is not None and eye.data.get('attack_turn')!=_stamp(ctx.engine):
        ctx.engine._update_condition_data(target,eye,{**eye.data,'attack_turn':_stamp(ctx.engine)},PREFIX+'eye_of_the_mantis')


def journey_projection(session):
    """Read native journey bundles/snapshots through the existing combat readers.

    This temporary mechanical projection is never played or saved as a fight.
    Original persisted health is restored after initialization, so constructor
    turn hooks cannot create travel healing or resources. Travel admission has
    already excluded unexported timed modifiers and Concentration.
    """
    from pathlib import Path
    from ..gate4_engine import Gate4ControllerEngine
    from ..canonical import canonical_sha256
    from ..gate2_runtime_models import ConditionInstance
    import json
    bundles=[]
    for aid,row in session.state['actors'].items():
        from . import transform
        bundle=transform('journey_combat_bundle',deepcopy(row['bundle']),session,aid)
        bundle.pop('mantis_travel_eyes',None)
        for pool in bundle['actor_template']['resources']:
            pool['initial']=row['resources'].get(pool['resource_id'],pool['initial'])
        bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)
        bundles.append(bundle)
    engine=Gate4ControllerEngine(Path(__file__).resolve().parents[2],typed_bundles=tuple(bundles),
        match_seed=session.state['journey_id']+':mantis:'+str(session.state['revision']),
        roster_setup={'primary_actor_ids':list(session.state['actors']),
            'team_by_actor':{aid:'team:journey' for aid in session.state['actors']},
            'starting_positions':{aid:row['position'] for aid,row in session.state['actors'].items()}},
        battlefield=session.state['battlefield'])
    for aid,row in session.state['actors'].items():
        actor=engine.state.actors[aid]
        snapshot=row.get('encounter_snapshot')
        actor.current_hp=snapshot['current_hp'] if snapshot else actor.maximum_hp
        if snapshot:
            actor.maximum_hp=snapshot['maximum_hp'];actor.active=bool(snapshot['active'])
            actor.conditions={key:ConditionInstance.model_validate(json.loads(raw)) for key,raw in snapshot['conditions'].items()}
        actor.resources=deepcopy(row['resources'])
    return engine


def journey_eye_actions(session,actor_id):
    actor=session.state['actors'][actor_id]
    return [row for row in actor['bundle']['action_catalog']
        if (row.get('parameters',{}).get('typed') or {}).get('source')==PREFIX+'eye_of_the_mantis']


@hook('journey_options')
def journey_eye_options(session,actor_id):
    if session.state['phase']!='travel' or not journey_eye_actions(session,actor_id):return None
    actor=session.state['actors'][actor_id]
    if actor['incapacitated'] or actor['resources'].get('resource:core.stamina',0)<3:return []
    from ..stealth import sees
    engine=journey_projection(session);owner=engine.state.actors[actor_id]
    return [{'id':'mantis_eye:'+target.entity_id,'kind':'mantis_eye','payload':{'target':target.entity_id},
        'label':f'Eye of the Mantis: diagnose {target.display_name}; 3 Stamina, 1 minute, within 60 feet.'}
        for target in engine.state.actors.values() if target.active and sees(engine,owner,target)
        and engine._distance_actor_to_actor(owner,target)<=60]


@hook('journey_command')
def journey_eye_activate(session,actor_id,kind,payload):
    if kind!='mantis_eye':return None
    from ..journey import require
    require(set(payload)=={'target'} and any(row['payload']==payload for row in journey_eye_options(session,actor_id) or []),
        'Eye of the Mantis requires an owned feature, 3 Stamina and one visible creature within 60 feet.')
    from .. import typed_executor as te
    engine=journey_projection(session);owner=engine.state.actors[actor_id];target=engine.state.actors[payload['target']]
    action=next(a for a in engine.action_catalog.values() if a.owner_id==actor_id
        and (a.parameters.get('typed') or {}).get('source')==PREFIX+'eye_of_the_mantis')
    typed=action.parameters['typed']
    ctx=te.Context(engine,owner,action,None,typed,[target],target,{})
    before=len(engine.events)
    profile=diagnosis(ctx,target)
    for event in engine.events[before:]:
        if event.event_type=='CHECK_ROLLED':
            session.emit('CULTIVATION_CHECK_ROLLED',actor_id,source=PREFIX+'eye_of_the_mantis',
                outcome=deepcopy(event.payload))
    actor=session.state['actors'][actor_id]
    actor['resources']['resource:core.stamina']-=3
    expiry=session.clock()+60
    actor.setdefault('source_states',{}).setdefault(PARENT,{}).setdefault('eyes',{})[target.entity_id]={
        'target':target.entity_id,'profile':profile,'source_cl':int(typed['numbers']['cl']),
        'expires_num':expiry.numerator,'expires_den':expiry.denominator,
        'clock_journey_id':session.state['journey_id'],'remaining_num':60,'remaining_den':1}
    session.emit('MANTIS_EYE_ACTIVATED',actor_id,target_id=target.entity_id,stamina_spent=3,duration_seconds=60)
    sync_journey_eye(session)
    return True


@hook('journey_properties')
def journey_eye_reading(session,actor_id):
    from fractions import Fraction
    eyes=session.state['actors'][actor_id].get('source_states',{}).get(PARENT,{}).get('eyes',{})
    active={key:deepcopy(eye) for key,eye in eyes.items()
        if session.clock()<Fraction(eye['expires_num'],eye['expires_den'])}
    if not active:return None
    return {'mantis_private_diagnoses':active,'mantis_private_diagnosis':list(active.values())[-1]}


def sync_journey_eye(session):
    from fractions import Fraction
    from math import ceil
    from ..gate2_runtime_models import Position
    from ..canonical import canonical_sha256
    for aid,actor in session.state['actors'].items():
        state=actor.get('source_states',{}).get(PARENT,{})
        eyes=state.get('eyes',{})
        bundle=actor['bundle'];continued=[]
        if not eyes and 'mantis_travel_eyes' not in bundle:continue
        for key,eye in list(eyes.items()):
            target=session.state['actors'].get(eye['target'])
            expired=session.clock()>=Fraction(eye['expires_num'],eye['expires_den'])
            far=target is None or session.grid.distance_ft(Position.model_validate(actor['position']),Position.model_validate(target['position']))>5280
            if expired or far:
                eyes.pop(key)
                session.emit('MANTIS_EYE_ENDED',aid,target_id=eye['target'],reason='duration' if expired else 'distance')
            else:
                remaining=Fraction(eye['expires_num'],eye['expires_den'])-session.clock()
                eye['remaining_num'],eye['remaining_den']=remaining.numerator,remaining.denominator
                eye['clock_journey_id']=session.state['journey_id']
                continued.append({**deepcopy(eye),'remaining_seconds':ceil(remaining)})
        if continued:bundle['mantis_travel_eyes']=continued
        else:bundle.pop('mantis_travel_eyes',None)
        bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)


@hook('journey_elapsed')
def journey_eye_clock(session,actor_id,before,seconds,moving):
    sync_journey_eye(session)
    sync_ward_clock(session,actor_id)


@hook('journey_state_changed')
def journey_eye_distance(session,actor_id):
    sync_journey_eye(session)
    sync_ward_clock(session,actor_id)


@hook('match_initialize')
def continue_travel_eye(engine):
    from fractions import Fraction
    for bundle in getattr(engine,'typed_bundle_documents',()):
        owner=engine.state.actors.get(bundle['actor_id'])
        if owner is None:continue
        for eye in bundle.get('mantis_travel_eyes',[]):
            if eye['remaining_seconds']<=0:continue
            target=engine.state.actors.get(eye['target'])
            if target is None or engine._distance_actor_to_actor(owner,target)>5280:continue
            remaining=Fraction(eye['remaining_num'],eye['remaining_den'])
            if remaining<=0:continue
            expiry,deadline=mantis_deadline(engine,remaining)
            engine._apply_condition(target,EYE,PREFIX+'eye_of_the_mantis',owner.entity_id,expires_on=expiry,
                data={'source_cl':eye['source_cl'],'label':'Eye of the Mantis (continued from travel)',
                    'mantis_deadline_num':deadline.numerator,'mantis_deadline_den':deadline.denominator})
            publish_diagnosis(engine,owner,PREFIX+'eye_of_the_mantis',target,eye['profile'],expiry)


@hook('journey_initialize')
def resume_mantis_clock(session,actor_id):
    """Continue remaining travel time across a finished/reopened journey."""
    from fractions import Fraction
    actor=session.state['actors'][actor_id]
    eyes=actor.get('source_states',{}).get(PARENT,{}).get('eyes',{})
    for eye in eyes.values():
        if eye.get('clock_journey_id')!=session.state['journey_id']:
            remaining=Fraction(eye.get('remaining_num',0),eye.get('remaining_den',1))
            expiry=session.clock()+remaining
            eye['expires_num'],eye['expires_den']=expiry.numerator,expiry.denominator
            eye['clock_journey_id']=session.state['journey_id']
    sync_journey_eye(session)


def publish_diagnosis(engine,owner,source,target,profile,expiry):
    """Refresh this target's private activation snapshot, retaining other targets."""
    from .. import observer_information as information
    for held in list(owner.conditions.values()):
        details=held.data.get('details') or {}
        if held.condition_id==information.READING and details.get('feature')=='Eye of the Mantis' and details.get('target_id')==target.entity_id:
            engine._remove_condition_instance(owner,held.instance_id,source,expected=held)
    information.publish(engine,owner,source,owner,'declaration',
        {'feature':'Eye of the Mantis','target_id':target.entity_id,'profile':deepcopy(profile)},expiry)


@hook('event')
def eye_lock_save_spent(engine,event_type,kwargs):
    if event_type!='SAVE_ROLLED':return
    source=str(kwargs.get('source_definition_id') or '')
    if not source.split('#')[0].endswith(PREFIX+'joint_lock'):return
    action=engine.action_catalog.get(source)
    target=engine.state.actors.get(kwargs.get('actor_id'))
    owner=engine.state.actors.get(action.owner_id) if action is not None else None
    if owner is None or target is None or engine.state.current_actor_id!=owner.entity_id:return
    eye=_eye(target,owner)
    if eye is not None and eye.data.get('lock_turn')!=_stamp(engine):
        engine._update_condition_data(target,eye,{**eye.data,'lock_turn':_stamp(engine)},source)


@hook('attack_spec_choice')
def mantis_ordinary_attack_choice(ctx,target,attack,spec,index):
    """Consume the body's already-owned ordinary options, separately each strike."""
    options=ctx.typed.get('mantis_ordinary_abilities')
    if attack.get('attack_kind')!='unarmed' or not options:return
    # Earlier public choice providers (e.g. Wrong-Hand Strike) already fold the
    # ordinary choices into their single per-strike menu.
    if spec['typed'].get('resolved_attack_ability'):return
    from .attack_abilities import strike_options,strike_attack_only_options,select_strike_ability
    from .needle import ask,checkpoint_id
    ordinary=strike_options(ctx,options)
    attack_only=strike_attack_only_options(ctx)
    if set(ordinary)&set(attack_only):raise ValueError('Attack-only choice conflicts with an ordinary ability')
    choices={**ordinary,**{key:value['modifier'] for key,value in attack_only.items()}}
    names={'STR':'Strength','DEX':'Dexterity','CON':'Constitution','INT':'Intelligence','WIS':'Wisdom','CHA':'Charisma'}
    selected=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'mantis_ability',target.entity_id,str(index)),ctx.actor,
        'choice:needle.mantis_attack_ability',list(choices),
        labels={key:(attack_only[key]['label']+' (attack only)' if key in attack_only else names.get(key,key)+' for attack and damage') for key in choices},
        preferred=[max(choices,key=choices.get)],target_id=target.entity_id,name='Choose unarmed strike ability',
        prompt=f'{ctx.action.display_name}, strike {index} against {target.display_name}: choose a legal attack ability. No additional action or resource cost.')
    if not selected:return
    key=selected[0];original=int(ctx.typed['weapon']['ability_modifier'])
    select_strike_ability(ctx,spec,key,choices[key],original_modifier=original,
        fixed_unarmed='fixed_damage' in ctx.typed['weapon'],damage_modifier=original if key in attack_only else None)


@hook('compile_action')
def mantis_strike_target_domain(action,info):
    if not any(str(mid).startswith(PREFIX) for mid in info['owned_ids']):return None
    typed=action.parameters.get('typed') or {}
    if typed.get('weapon') and any(e.get('type')=='attack' and e.get('attack_kind')=='unarmed' for e in typed.get('effects') or []):
        return action.model_copy(update={'target_kind':'ANY_CREATURE'})
    return None


def eye_remaining(engine, condition):
    """Remaining native round-slot clock, in exact six-second round fractions."""
    from fractions import Fraction
    from .effect_durations import parse_round
    count = max(1, len(engine.state.initiative_order))
    if 'mantis_deadline_num' in condition.data:
        deadline=Fraction(condition.data['mantis_deadline_num'],condition.data['mantis_deadline_den'])
        now=Fraction(6*(engine.state.round_number*count+engine.state.current_slot_index),count)
        return max(Fraction(0),deadline-now)
    clock = parse_round(condition.expires_on)
    if clock is None:
        return Fraction(0)
    count = max(1, len(engine.state.initiative_order))
    slots = (clock[0] - engine.state.round_number) * count + clock[1] - engine.state.current_slot_index
    return max(Fraction(0), Fraction(6 * slots, count))


def managed_eye_condition(condition):
    from ..observer_information import READING
    return (condition.source_definition_id.endswith(PREFIX+'eye_of_the_mantis')
            and (condition.condition_id == EYE or
                 condition.condition_id == READING and
                 condition.data.get('details', {}).get('feature') == 'Eye of the Mantis'))


@hook('journey_snapshot_actor')
def eye_snapshot(actor, session, actor_id, engine):
    """The original terminal actor remains immutable; export is below."""
    if not any(managed_eye_condition(c) for c in actor.conditions.values()):
        return None
    copied = actor.model_copy(deep=True)
    copied.conditions = {key:c for key,c in copied.conditions.items() if not managed_eye_condition(c)}
    return copied


@hook('journey_encounter_settled')
def export_combat_eyes(session, actor_id, engine, creature):
    from .. import observer_information as information
    actor = session.state['actors'][actor_id]
    state = actor.get('source_states', {}).get(PARENT)
    eyes = {}
    profiles = {c.data.get('details', {}).get('target_id'):c.data['details']['profile']
        for c in creature.conditions.values() if managed_eye_condition(c)
        and c.condition_id == information.READING}
    for target in engine.state.actors.values():
        for mark in target.conditions.values():
            if mark.condition_id != EYE or mark.source_actor_id != actor_id or not managed_eye_condition(mark):
                continue
            remaining = eye_remaining(engine, mark)
            if remaining <= 0 or target.entity_id not in profiles:
                continue
            expiry = session.clock() + remaining
            eyes[target.entity_id] = {'target':target.entity_id, 'profile':deepcopy(profiles[target.entity_id]),
                'source_cl':int(mark.data['source_cl']), 'expires_num':expiry.numerator,
                'expires_den':expiry.denominator, 'remaining_num':remaining.numerator,
                'remaining_den':remaining.denominator, 'clock_journey_id':session.state['journey_id']}
    if state is None and not eyes:
        return
    state = actor.setdefault('source_states', {}).setdefault(PARENT, {})
    state['eyes'] = eyes
    from math import ceil
    from fractions import Fraction
    from ..canonical import canonical_sha256
    bundle = actor['bundle']
    if eyes:
        bundle['mantis_travel_eyes'] = [{**deepcopy(eye),
            'remaining_seconds':ceil(Fraction(eye['remaining_num'], eye['remaining_den']))}
            for eye in eyes.values()]
    else:
        bundle.pop('mantis_travel_eyes', None)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)
    session.emit('MANTIS_EYES_CONTINUED', actor_id, target_ids=sorted(eyes))


def sync_ward_clock(session,actor_id):
    from fractions import Fraction
    from ..canonical import canonical_sha256
    actor=session.state['actors'][actor_id]
    wards=actor.get('source_states',{}).get(PARENT,{}).get('wards',{})
    from ..fact_consent_admission import KEY
    latest={}
    for rec in session.state.get(KEY,[]):
        if rec['source']==PARENT and rec['subject']==actor_id and rec['kind']=='diagnosis_concealment':
            latest[rec['scope']]=rec['receipt_id']
    for receipt,saved in wards.items():
        if saved.get('ended'):continue
        scope=saved['admission']['scope']
        if scope in latest and latest[scope]!=receipt:
            saved['ended']=1
            saved['remaining_num'],saved['remaining_den']=0,1
            continue
        remaining=Fraction(saved['expires_num'],saved['expires_den'])-session.clock()
        if remaining<=0:
            saved['ended']=1
            saved['remaining_num'],saved['remaining_den']=0,1
        else:
            saved['remaining_num'],saved['remaining_den']=remaining.numerator,remaining.denominator
    updated=current_concealment_bundle(actor['bundle'],session,actor_id)
    if updated is not None:
        updated.pop('bundle_sha256',None)
        updated['bundle_sha256']=canonical_sha256(updated)
        actor['bundle']=updated


@hook('journey_initialize')
def continue_ward_clock(session,actor_id):
    from fractions import Fraction
    wards=session.state['actors'][actor_id].get('source_states',{}).get(PARENT,{}).get('wards',{})
    for saved in wards.values():
        if saved.get('ended') or saved.get('clock_journey_id')==session.state['journey_id']:continue
        expiry=session.clock()+Fraction(saved['remaining_num'],saved['remaining_den'])
        saved['expires_num'],saved['expires_den']=expiry.numerator,expiry.denominator
        saved['clock_journey_id']=session.state['journey_id']
    sync_ward_clock(session,actor_id)


def native_ward_profiles(engine,actor_id):
    return {row['receipt_id']:row for bundle in getattr(engine,'typed_bundle_documents',())
        if bundle['actor_id']==actor_id for row in bundle.get('mantis_diagnosis_authority',[])}


def managed_ward(condition,profiles):
    profile=profiles.get(condition.data.get('receipt_id'))
    return (condition.condition_id=='condition:typed.mantis_diagnosis_concealment'
        and condition.data.get('authority')=='table_owner' and profile is not None
        and condition.source_definition_id==profile['effect_source'])


@hook('journey_snapshot_actor')
def ward_snapshot(actor,session,actor_id,engine):
    profiles=native_ward_profiles(engine,actor_id)
    if not any(managed_ward(c,profiles) for c in actor.conditions.values()):return None
    copied=actor.model_copy(deep=True)
    copied.conditions={key:c for key,c in copied.conditions.items() if not managed_ward(c,profiles)}
    return copied


@hook('journey_encounter_settled')
def export_wards(session,actor_id,engine,creature):
    from ..fact_consent_admission import KEY
    profiles=native_ward_profiles(engine,actor_id)
    if not profiles:return
    actor=session.state['actors'][actor_id]
    ledger=actor.setdefault('source_states',{}).setdefault(PARENT,{}).setdefault('wards',{})
    for receipt,profile in profiles.items():
        admission=profile.get('admission') or next((r for r in session.state.get(KEY,[]) if r['receipt_id']==receipt),None)
        if admission is None:raise ValueError('A continued ward requires its actual native admission receipt.')
        saved={'admission':deepcopy(admission),'ended':1}
        ward=next((c for c in creature.conditions.values() if c.data.get('receipt_id')==receipt and managed_ward(c,profiles)),None)
        remaining=eye_remaining(engine,ward) if ward is not None else 0
        if remaining>0:
            expiry=session.clock()+remaining
            value=deepcopy(ward.data['information_profile']['diagnosis_concealment'])
            value['effect_source']=ward.source_definition_id
            saved={'admission':deepcopy(admission),'value':value,
                'expires_num':expiry.numerator,'expires_den':expiry.denominator,
                'remaining_num':remaining.numerator,'remaining_den':remaining.denominator,
                'clock_journey_id':session.state['journey_id']}
        ledger[receipt]=saved
    sync_ward_clock(session,actor_id)
    session.emit('MANTIS_CONCEALMENTS_CONTINUED',actor_id,receipt_ids=sorted(profiles))

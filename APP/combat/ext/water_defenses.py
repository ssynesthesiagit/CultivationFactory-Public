"""Water Shield, Water Whip and Mirror-Water Reply through owned compiled rows.

Old saved reaction catalogs and old Whip effects are unchanged. Native forced
paths preserve footprint, collision, defenses and entry hazards without OAs.

Shared API: shield_routes supplies legal forced routes to Water Shield and
water_second_pass.water_lash_shift; the caller chooses the allowed distance.
"""
from . import effect, hook, note, run
from .needle import CHOICE, ask, checkpoint_id
SHIELD='TAL_WATER_WATER_SHIELD'
WHIP='TAL_WATER_WATER_WHIP'
BLOCK='water_defenses'


def shield_distance(engine, owner):
    """Incarnation extends only its owner's Water Shield while its state lasts."""
    from .states import active
    return 30 if active(engine, owner, 'ocean_sovereign_incarnation') else 10


@hook('compile_block')
def compile_defense(block,spec,row,numbers):
    if block==BLOCK:
        return [{**row,'block':BLOCK,'kind':spec['kind'],'numbers':dict(numbers),'cw2r2':True}]
    return None


def water_contact(engine,owner,target):
    for z in engine.state.zones.values():
        a=engine.action_catalog.get(z.source_definition_id)
        source=((a.parameters or {}).get('typed') or {}).get('source') if a is not None else None
        if z.active and z.owner_id==owner.entity_id and source=='WATER_BASE_SHAPE_CURRENT' and engine._footprint_intersects(target,z.affected_cells):
            return True
    return False


@effect('water_whip_hold')
def whip(ctx,eff):
    from .cp_pools import of
    from .choice_costs import payable
    from ..typed_executor import run_effects, mark_condition_id
    target=ctx.target
    if target is None or not target.active:
        return
    payment=payable(ctx.actor,of(ctx.actor,at_least=1) or '',1)
    if payment is None or any(r is False for r in run('cost_available',ctx.engine,ctx.actor,payment.pool,1,{})):
        return
    if not ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'WATER_WHIP',target.entity_id),ctx.actor,
               CHOICE+'water_whip',['use'],allow_decline=True,name='Water Whip',feature_id=WHIP,target_id=target.entity_id,
               payment=payment,labels={'use':'Pay 1 CP: Strength save or Grappled by water until the end of your next turn'},
               prompt=f'Water Whip: Water Lash hit {target.display_name}. Pay {payment.quote()}? A failed Strength save Grapples it '
                      'by water until the end of your next turn; while held, it is also Soaked. '
                      f'It may use an Action to escape with Athletics or Acrobatics against DC {int(ctx.numbers.get("save_dc") or 10)}.'):
        return
    payment.pay(ctx.engine,ctx.actor,WHIP)
    before=set(target.conditions)
    run_effects(ctx,[{'type':'save','ability':'str','applies_to':'target',
        'on_fail':[{'type':'condition','condition':'grappled','applies_to':'target','duration':'until_end_of_your_next_turn',
                    'condition_data':{'reach_ft':None,'water_whip':1},'evidence':'Water Whip: Grappled by water until the end of your next turn'}],
        'on_success':[]}])
    # None bypasses the native physical-reach default during application. Omit
    # it from saved data: water holds neither expire by distance nor drag.
    for iid in set(target.conditions)-before:
        held=target.conditions[iid]
        if (held.condition_id=='condition:typed.grappled' and held.source_actor_id==ctx.actor.entity_id
                and held.data.get('water_whip')):
            held.data.pop('reach_ft',None)
            # Keep a separate Soaked instance: another Water effect's Soaked
            # must survive escape. linked_holds removes only this child when
            # its persisted parent instance ends (escape or source expiry).
            ctx.engine._apply_condition(target,mark_condition_id('Soaked',ctx.actor.entity_id),
                ctx.source,ctx.actor.entity_id,expires_on=held.expires_on,
                data={'parent_hold':iid,'label':'Water Whip: Soaked while Grappled'})


@hook('escape_check_choice_required')
def whip_escape_choice(ctx,effect,dc,grips,hazards):
    """The held target chooses either printed skill through the shared selector."""
    if any(c.data.get('water_whip') for c in grips):
        return {'name':'Water Whip','feature_id':WHIP}
    return None


@hook('final_damage')
def shield(engine,target,amount,damage_type,source_id,source_actor_id,intent):
    intent=intent or getattr(engine,'_active_intent',None)
    if amount<=0 or intent is None:
        return None
    # An enclosing area action may also cause falling or other incidental harm.
    # Only this packet's delivery action can establish area-effect provenance.
    action=engine.action_catalog.get(source_id)
    typed=((action.parameters or {}).get('typed') or {}) if action is not None else {}
    area=typed.get('area') or (getattr(action,'radius_ft',None) if action is not None else None)
    if not area and engine.damage_context() is None:
        return None
    from .passive_rows import row_of
    from ..stealth import sees
    from ..target_knowledge import located
    from .cp_pools import of
    from .choice_costs import payable
    from ..typed_executor import condition_rules
    from ..gate2_runtime_models import DiceSpec
    remaining=amount
    for owner in sorted(engine.state.actors.values(),key=lambda a:a.entity_id):
        if remaining<=0:
            break
        row=row_of(engine,owner.entity_id,BLOCK,'shield')
        if (row is None or not owner.active or owner.life_state is not None or not owner.reaction_available
                or engine._distance_actor_to_actor(owner,target)>30
                or (owner is not target and not (located if row.get('cw2r2') else sees)(engine,owner,target))
                or any(r.get('no_reactions') for r in condition_rules(owner))):
            continue
        payment=payable(owner,of(owner,at_least=1) or '',1)
        if payment is None or any(r is False for r in run('cost_available',engine,owner,payment.pool,1,{})):
            continue
        n=row['numbers'];cl=int(n.get('cl') or 1);count=3 if cl>=17 else 2 if cl>=11 else 1
        name=getattr(action,'display_name',None) or 'damage'
        incarnate=shield_distance(engine,owner)==30
        movement_text=('If this reduces the damage, you may move it up to 30 feet, even if it is not Soaked '
                       'or in your Basin or Current, without Opportunity Attacks.' if incarnate else
                       'If it is Soaked or in your Basin or Current, you may move it up to 10 feet without Opportunity Attacks.')
        if not ask(engine,intent,checkpoint_id(engine,'WATER_SHIELD',owner.entity_id,target.entity_id,source_id),owner,
                   CHOICE+'water_shield',['use'],allow_decline=True,name='Water Shield',feature_id=SHIELD,target_id=target.entity_id,
                   payment=payment,automatic=owner.team_id==target.team_id,
                   labels={'use':f'Spend your Reaction and 1 CP: reduce damage by {count}d10 + your key modifier'},
                   prompt=f'Water Shield: {target.display_name} takes {remaining} {damage_type} damage from {name}. '
                          f'Spend your Reaction and {payment.quote()} to reduce it by {count}d10 + your key modifier? '
                          +movement_text):
            continue
        payment.pay(engine,owner,SHIELD);owner.reaction_available=False
        rolled=engine.roller.roll(DiceSpec(count=count,sides=10,modifier=int(n.get('key_mod') or 0)),actor_id=owner.entity_id,reason='WATER_SHIELD_REDUCTION')
        engine._record_roll(rolled)
        engine._append_event('DAMAGE_ROLLED',SHIELD,actor_id=owner.entity_id,target_ids=(target.entity_id,),
                             payload={'expression':rolled.expression,'total':rolled.total,'roll_id':rolled.roll_id})
        from ..support_values import resolve_reduction
        selected = resolve_reduction(engine, owner, target, SHIELD, int(rolled.total), remaining)
        reduced=min(remaining,max(0,selected))
        engine._append_event('REACTION_RESOLVED',SHIELD,actor_id=owner.entity_id,target_ids=(target.entity_id,),
                             payload={'ability':'Water Shield','reduction':reduced,'pending_before':remaining,'pending_after':remaining-reduced})
        remaining-=reduced
        soaked=any(c.condition_id.startswith('condition:typed.mark.soaked.') for c in target.conditions.values())
        if (incarnate and reduced>0) or soaked or water_contact(engine,owner,target):
            # DAMAGE_COMMITTED is delivered even when the shield absorbs all HP
            # damage. Store only a string; pauses roll back the whole attack.
            owner.turn_flags['auto38_shield_pending:'+target.entity_id]=source_id
        note(engine,SHIELD,owner,f'Water Shield reduces damage to {target.display_name} by {reduced}.',(target,))
    return {'amount':remaining} if remaining!=amount else None


@hook('event',nested=True)
def shield_movement(engine,event_type,kwargs):
    if event_type!='DAMAGE_COMMITTED':
        return
    from .. import movement_paths
    intent=getattr(engine,'_active_intent',None)
    for tid in kwargs.get('target_ids') or ():
        target=engine.state.actors.get(tid)
        if target is None:
            continue
        for owner in sorted(engine.state.actors.values(),key=lambda a:a.entity_id):
            key='auto38_shield_pending:'+tid
            if owner.turn_flags.get(key)!=kwargs.get('source_definition_id'):
                continue
            owner.turn_flags.pop(key,None)
            if intent is None or not target.active:
                continue
            distance=shield_distance(engine,owner)
            routes=shield_routes(engine,target,distance)
            if not routes:
                continue
            pick=ask(engine,intent,checkpoint_id(engine,'WATER_SHIELD_STEP',owner.entity_id,tid),owner,
                     CHOICE+'water_shield_step',list(routes),allow_decline=True,name='Water Shield movement',feature_id=SHIELD,
                     target_id=tid,labels={k:f'Move {target.display_name} to square {p[-1].x},{p[-1].y}, {p[-1].z*5} feet high' for k,p in routes.items()},
                     prompt=f'Water Shield protected {target.display_name}. Choose a legal destination within {distance} feet, without '
                            'Opportunity Attacks or spending its normal movement; terrain and entry hazards still apply.')
            if pick:
                from ..typed_reactions import triggered_context
                from .passive_rows import row_of
                row=row_of(engine,owner.entity_id,BLOCK,'shield')
                ctx=triggered_context(engine,owner,target,
                    {'feature_id':SHIELD,'name':'Water Shield','numbers':(row or {}).get('numbers') or {},
                     'effects':[]},intent)
                movement_paths.resolve(engine,target,routes[pick[0]],SHIELD,kind='forced',feet=distance,intent=intent,
                                       provokes=False,source_actor_id=owner.entity_id,ctx=ctx)


def shield_routes(engine,target,distance_ft=10):
    """Pure displacement menu, ignoring Speed and movement terrain cost.

    Full volumes and observed occupancy prune every step; the native forced
    resolver checks actual occupancy, reactions, hazards and support on commit.
    """
    from collections import deque
    from ..gate2_runtime_models import Position
    occupied=engine._occupied_volumes_except(target.entity_id,observed=True)
    footprint=engine._footprint(target)
    paths={target.position:(target.position,)}
    queue=deque([target.position])
    while queue:
        cell=queue.popleft();path=paths[cell]
        if (len(path)-1)*5>=distance_ft:
            continue
        for dz in (-1,0,1):
            for dy in (-1,0,1):
                for dx in (-1,0,1):
                    if (dx,dy,dz)==(0,0,0) or cell.z+dz<0 or cell.x+dx<0 or cell.y+dy<0:
                        continue
                    nxt=Position(x=cell.x+dx,y=cell.y+dy,z=cell.z+dz)
                    if nxt in paths or not engine.grid.volume_step_legal(cell,nxt,occupied_cells=occupied,footprint=footprint):
                        continue
                    paths[nxt]=(*path,nxt);queue.append(nxt)
    return {f'step:{cell.x},{cell.y}'+(f',{cell.z}' if cell.z else ''):path for cell,path in paths.items() if cell!=target.position}


REPLY = 'TAL_WATER_MIRROR_WATER_REPLY'


@hook('compile_reaction')
def compile_reply(row, info):
    """Seal the owned Reply's water qualification; saved catalogs stay unchanged."""
    if row.get('feature_id') != REPLY or REPLY not in info['owned_ids']:
        return None
    # A Basin OR a Soaked protected creature qualifies. The generic prose
    # classifier cannot express that disjunction as a required attacker mark.
    return {**row, 'water_reply': 1, 'requires_mark': None,
            'requires_self_mark': None, 'requires_zone_los': None}


@hook('reaction_geometry_allowed')
def reply_qualification(engine, reactor, source, subject, row):
    """Pure qualification on the actual protected self/ally, before payment."""
    if not row.get('water_reply'):
        return None
    from .water_second_pass import mist_basins, SOAKED
    return (any(c.condition_id.startswith(SOAKED) for c in subject.conditions.values())
            or any(engine._footprint_intersects(subject, zone.affected_cells)
                   for zone in mist_basins(engine, reactor)))


@effect('water_reply_protected')
def reply_protected(ctx, eff):
    """The reaction target stays the attacker; only this bundle uses protects."""
    from dataclasses import replace
    from ..typed_executor import run_effects
    protected = ctx.engine.state.actors.get(ctx.typed.get('protects') or ctx.actor.entity_id)
    if protected is None or not protected.active:
        return
    run_effects(replace(ctx, targets=[protected], target=protected), eff.get('effects') or [])


@effect('water_reply_opening')
def reply_opening(ctx, eff):
    """One incoming attack, owned by the reactor even on the attacker's turn."""
    from .effect_durations import token
    target = ctx.target
    if target is None or not target.active:
        return
    ctx.engine._add_modifier(target, ctx.source, 'incoming_attack_mode', 'SET', 'ADVANTAGE', 'NEXT_ATTACK',
        expires_on=token('start', ctx.actor.entity_id, ctx.actor.turns_started + 1),
        source_actor_id=ctx.actor.entity_id, spend_on_roll=True)
    note(ctx.engine, ctx.source, ctx.actor,
         f'Mirror-Water Reply: the next attack roll against {target.display_name} has Advantage '
         f'before the start of {ctx.actor.display_name}’s next turn.', (target,))



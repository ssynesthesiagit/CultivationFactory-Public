"""Burden the Flying Thing's table-scale vertical grounding response.

The native floor/finite-column support geometry supplies the surface. Plane,
projection permission and narrative grounding exemptions remain explicit riders.
"""
from . import effect, hook
from .earth_responses import rows, marked, spend_mark, response_context, save_dc, response_available, T

FEATURE=T+'BURDEN_THE_FLYING_THING'
HELD='condition:typed.earth_grounding'



def vertical_surface(engine, creature):
    """Only choose vertical descent when that surface is actually nearest.

    Side faces and disconnected platforms need the retained route choice;
    rejecting them preserves the mark rather than grounding toward wrong terrain.
    """
    from ..falling import supported
    origin = creature.position
    ground = next((origin.model_copy(update={'z': z}) for z in range(origin.z-1,-1,-1)
                   if supported(engine,creature,origin.model_copy(update={'z': z}))), None)
    if ground is None:
        return False
    distance = engine.grid.distance_ft(origin, ground)
    if distance > 60:
        return False
    # A nearer solid voxel can supply a side face. Never silently substitute
    # the floor for it, even when the floor also lies inside the printed range.
    for (x,y), spans in engine.grid.terrain_spans.get('BLOCKED',{}).items():
        for bottom, top in spans:
            z = min(origin.z, (top+4)//5 if top is not None else origin.z)
            z = max(z, (bottom+4)//5)
            surface = origin.model_copy(update={'x':x,'y':y,'z':z})
            if engine.grid.distance_ft(origin,surface) < distance:
                return False
    return True


def respond(engine, creature):
    from ..falling import supported
    from ..target_knowledge import located
    from ..typed_executor import block_save
    from .rider_choices import pick, trigger_name
    if not creature.active or supported(engine,creature) or not creature.position.z:
        return
    # Native support is the arena floor or an elevated solid column directly
    # below the creature. Separate side platforms/projection exemptions are
    # not silently inferred from x/y projection.
    for owner in engine.state.actors.values():
        if (not owner.active or owner.team_id==creature.team_id or not rows(engine,owner,'flying')
                or not marked(creature,owner.entity_id) or not response_available(engine,owner)
                or not located(engine,owner,creature)):
            continue
        if not vertical_surface(engine, creature):
            continue
        picked=pick(engine,owner,'earth_flying','Burden the Flying Thing',['SPEND'],subject=creature,
            preferred=['SPEND'],labels={'SPEND':'Spend Burden Mark; Strength save, descend and prevent gaining altitude'},
            prompt=f'Burden the Flying Thing: {trigger_name(engine)} left {creature.display_name} unsupported near the ground. '
                   'Spend your Burden Mark for free, without an Action, Reaction, or Cultivation Point? '
                   'On a failed Strength save, it descends up to 30 feet, cannot gain altitude until the start of its next turn, '
                   'and falls Prone if it lands. On a success, it descends 10 feet and cannot gain altitude until the end of its current turn.')
        if not picked:
            continue
        owner.turn_flags['earth_spent_round']=engine.state.round_number
        owner.turn_flags['_round_earth_response']=engine.state.round_number
        spend_mark(engine,owner,creature,FEATURE)
        ctx=response_context(engine,owner,creature,FEATURE,'Burden the Flying Thing')
        ctx.typed['numbers']={'save_dc':save_dc(engine,owner)}
        # Native typed save owns modifiers, d20 rewrite, result and events.
        block_save(ctx,{'type':'save','ability':'STR','on_fail':[{'type':'earth_ground_descent','feet':30,'failed':True}],
                        'on_success':[{'type':'earth_ground_descent','feet':10,'failed':False}]})
        break


@effect('earth_ground_descent')
def descent(ctx,row):
    from ..falling import supported,displace
    from ..typed_executor import run_effects
    from .effect_durations import token
    target=ctx.target
    if target is None:
        return
    displace(ctx.engine,target,-min(target.position.z,int(row['feet'])//5),ctx.source,
             intent=ctx.intent,settle_after=False)
    failed=row.get('failed') is True
    ctx.engine._apply_condition(target,HELD,ctx.source,ctx.actor.entity_id,
        expires_on=token('start',target.entity_id,target.turns_started+1) if failed else 'END_OF_CURRENT_TURN',
        data={'cannot_gain_altitude':1,'label':('Burden the Flying Thing: cannot gain altitude until the start of its next turn' if failed else 'Burden the Flying Thing: cannot gain altitude until the end of its current turn')})
    if failed and supported(ctx.engine,target):
        run_effects(ctx,[{'type':'condition','condition':'prone','applies_to':'target','duration':'instant'}])


@hook('turn_start')
def unsupported_turn(engine,creature):
    respond(engine,creature)


@hook('event')
def unsupported_movement(engine,event_type,kwargs):
    if event_type not in ('MOVEMENT_COMMITTED','TELEPORT_COMMITTED'):
        return
    if event_type=='MOVEMENT_COMMITTED' and (kwargs.get('payload') or {}).get('forced'):
        return
    creature=engine.state.actors.get(kwargs.get('actor_id'))
    if creature is not None:
        respond(engine,creature)


@hook('action_completed')
def unsupported_action(engine,actor,economy,source):
    # Covers hover/levitation gained by an action and native teleport receipts.
    respond(engine,actor)

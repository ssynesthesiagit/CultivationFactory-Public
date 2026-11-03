"""Elemental Prayer: fixed patron, exclusive delivery and source-tagged resistance.

Shared helper module: shugenja_terrain and zone_tick_producers use choose_patron
to record the same existing patron. patron queries the saved choice.
"""
from . import effect, hook
PRAYER = 'tianxia.subpath.qi.shugenja.feature.elemental_prayer'
PATRON = 'condition:typed.shugenja_patron'
PATRONS = ('air','cold','earth','fire','lightning','metal','water','wood')
TYPES = dict(zip(PATRONS, ('thunder','cold','bludgeoning','fire','lightning','slashing','bludgeoning','piercing')))
SAVES = {'cold':'CON','earth':'DEX','fire':'DEX','water':'STR','wood':'DEX'}

CHOICES = {'earth': ('bludgeoning','force'), 'metal': ('slashing','force'),
           'water': ('bludgeoning','cold'), 'wood': ('piercing','poison')}

def patron(actor):
    return next((c.data['patron'] for c in actor.conditions.values() if c.condition_id == PATRON), None)

def choose_patron(ctx):
    from .needle import ask, checkpoint_id
    chosen = patron(ctx.actor)
    if chosen is None:
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'shugenja_patron'), ctx.actor,
            'choice:needle.shugenja_patron', list(PATRONS), labels={k:k.title() for k in PATRONS},
            name='Elemental Patron', feature_id=PRAYER,
            prompt='Choose the Elemental Patron recorded when you gained Shugenja. It fixes your resistance and Prayer throughout the fight. Recording it costs nothing.')
        if not picked: return
        chosen = picked[0]
        ctx.engine._apply_condition(ctx.actor, PATRON, ctx.source, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
            data={'patron':chosen,'label':'Elemental Patron: '+chosen.title()})
    return chosen

@hook('fight_setup_tasks')
def patron_tasks(engine):
    from ..alternative_payments import owned
    return [{'actor_id':a.entity_id,'source_id':PRAYER} for a in engine.state.actors.values()
            if owned(engine,a,PRAYER) and patron(a) is None] or None

@hook('fight_setup')
def record_patron(engine,actor,source,intent):
    if source != PRAYER: return None
    from .states import context
    ctx = context(engine,actor,source,[actor],{})
    ctx.intent = intent
    choose_patron(ctx)
    return True

@hook('damage_defenses')
def narrow_resistance(engine,target,damage_type,typed,source_actor_id):
    from ..alternative_payments import owned
    if not owned(engine,target,PRAYER): return None
    chosen = patron(target)
    if chosen is None or str(damage_type).lower() != TYPES[chosen]: return None
    if chosen in CHOICES:  # the four patrons whose printed element only their own abilities carry
        tags = {str(t).lower() for t in typed.get('source_tags', [])}
        if chosen not in tags: return None
    return [{'kind':'resistance','damage_types':[str(damage_type).upper()],'feature_id':PRAYER}]

@hook('defense_description')
def narrow_resistance_description(engine,target):
    """Elemental Prayer's patron Resistance, as the Defences card names it, for the four patrons whose
    element the printed ability must declare.

    Same ownership, patron and damage-type gates the damage hook reads. Whether the incoming ability declares
    that element is read from the packet combat carries, which the card has none of, so it reads as a plain
    qualifier. The other four patrons declare no element, so their Resistance needs no packet and the card
    already lists it through the standing damage_defenses rows. Pure."""
    from ..alternative_payments import owned
    if not owned(engine,target,PRAYER): return None
    chosen = patron(target)
    if chosen is None or chosen not in CHOICES: return None
    return [{'feature_id': PRAYER, 'damage_types': [str(TYPES[chosen]).upper()],
             'note': f'only against damage from {chosen.title()} abilities'}]

@effect('shugenja_prayer', harmful=True)
def prayer(ctx,row):
    from dataclasses import replace
    from .needle import ask, checkpoint_id
    from .. import typed_executor as te
    chosen = choose_patron(ctx)
    if chosen is None: return
    damage_type = TYPES[chosen]
    if chosen in CHOICES:
        from .choice_prompt import action_context
        picked = ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'shugenja_damage',chosen),ctx.actor,
            'choice:needle.shugenja_damage',list(CHOICES[chosen]),preferred=[damage_type],
            labels={k:k.title() for k in CHOICES[chosen]},name='Elemental Prayer',feature_id=PRAYER,
            prompt=f'Choose the damage type for Elemental Prayer against {ctx.target.display_name}. It costs 1 Qi and one Action.',
            target_id=ctx.target.entity_id,
            prompt_context=action_context(ctx.engine, ctx.actor, ctx.action.source_definition_id, ctx.target, action=ctx.action))
        if picked: damage_type = picked[0]
    cl = int(ctx.numbers.get('cl') or 1)
    count = 4 if cl >= 17 else 3 if cl >= 11 else 2
    dmg = {'type':'damage','applies_to':'target','dice':{'count':count,'sides':8},
           'formula':'key_ability_modifier','damage_types':[damage_type],
           'evidence':f'Elemental Prayer: {count}d8 + key modifier {damage_type} damage'}
    rider = []
    if chosen in ('air','water'):
        direction = 'away'
        if chosen == 'water':
            picked = ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'shugenja_water',ctx.target.entity_id),
                ctx.actor,'choice:needle.shugenja_water',['push','pull'],labels={'push':'Push 5 feet','pull':'Pull 5 feet'},
                name='Elemental Prayer',feature_id=PRAYER,target_id=ctx.target.entity_id,
                prompt=f'Elemental Prayer: choose to push or pull {ctx.target.display_name} 5 feet on a failed save. No additional cost.')
            direction = 'toward' if picked and picked[0] == 'pull' else 'away'
        rider = [{'type':'forced_movement','applies_to':'target','distance_ft':5,'direction':direction}]
    elif chosen in ('fire','lightning'):
        rider = [{'type':'condition','applies_to':'target','condition':'reaction_denied','expires_on':'START_OF_TARGET_NEXT_TURN'}]
    elif chosen == 'cold':
        rider = [{'type':'speed','applies_to':'target','flat':-10,'expires_on':'START_OF_SOURCE_NEXT_TURN'}]
    elif chosen == 'earth':
        rider = [{'type':'condition','applies_to':'target','condition':'prone'}]
    elif chosen == 'wood': rider = [{'type':'shugenja_wood_terrain'}]
    effects = ([{'type':'attack','attack_kind':'cultivation_ranged','count':1,'on_hit':[dmg,*rider]}]
        if chosen in ('air','lightning','metal') else
        [{'type':'save','ability':SAVES[chosen],'applies_to':'target','on_fail':[dmg,*rider],'on_success':[{'type':'half_damage'}]}])
    te.run_effects(replace(ctx,typed={**ctx.typed,'patron_tag':chosen,'source_tags':[chosen]}),effects)

@hook('cover_reduction')
def metal_cover(engine,attacker,target,cover):
    if cover != 2 or patron(attacker) != 'metal': return None
    from ..shot_geometry import action
    current = action(engine,attacker)
    if current is not None and any(r.get('type') == 'shugenja_prayer' for r in current.parameters.get('typed',{}).get('effects',[])):
        return 1
    return None

@effect('shugenja_wood_terrain', harmful=True)
def wood(ctx,row):
    from .. import zones
    from dataclasses import replace
    from ..gate2_runtime_models import Position
    inner = replace(ctx,intent=ctx.intent.model_copy(update={'destination':ctx.target.position}))
    cells = tuple(Position(x=x,y=y,z=ctx.target.position.z)
        for x,y in ctx.engine.grid.footprint_cells(ctx.target.position,ctx.engine._footprint(ctx.target)))
    zones.create(inner,{'name':'Elemental Prayer: Wood','shape':'cube','size_ft':5,'cells':cells,
        'duration':{'kind':'special'},'difficult':'all',
        'profile':{'shugenja_wood':1,'until_owner_turn':int(ctx.actor.turns_started+1)}})

@hook('turn_boundary_start')
def wood_expiry(engine,actor,*args):
    from .. import zones
    for zone in list(engine.state.zones.values()):
        profile = zone.trigger_profile.get('profile') or {}
        if zone.active and zone.owner_id == actor.entity_id and profile.get('shugenja_wood') and actor.turns_started >= profile['until_owner_turn']:
            zones.remove(engine,zone,'EXPIRED')

@hook('compile_action')
def prayer_value(action, info):
    typed = action.parameters.get('typed') or {}
    if not any(r.get('type') == 'shugenja_prayer' for r in typed.get('effects', [])):
        return None
    numbers = typed['numbers']
    count = 4 if numbers['cl'] >= 17 else 3 if numbers['cl'] >= 11 else 2
    return action.model_copy(update={'parameters': {**action.parameters, 'expected_damage':int(count * 4.5 + numbers['key_mod'])}})

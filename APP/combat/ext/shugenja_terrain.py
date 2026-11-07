"""Terrain Attunement's initiative choices, using confirmed scene terrain.

Terrain provenance is a scene fact recorded by the player, never guessed by AI.
The combat benefit resolves before turn one, exactly once per scene. Reading
natural principles is a noncombat information check and remains source text.
"""
from . import effect, hook
TERRAIN = 'tianxia.subpath.qi.shugenja.feature.terrain_attunement'
BLOCK = 'shugenja_terrain'

@effect('shugenja_terrain_ownership')
def declaration(ctx,row):
    pass

@hook('compile_passives')
def ownership(rows,info):
    if TERRAIN not in info['owned_ids']: return rows
    return [*rows,{'block':BLOCK,'feature_id':TERRAIN,'numbers':dict(info['numbers']),
                  'trigger_owner':'shugenja_terrain'}]

@hook('fight_setup_tasks')
def tasks(engine):
    from ..alternative_payments import owned
    return [{'actor_id':a.entity_id,'source_id':TERRAIN} for a in engine.state.actors.values()
            if owned(engine,a,TERRAIN)] or None

@hook('fight_setup')
def attune(engine,actor,source,intent):
    if source != TERRAIN: return None
    from .needle import ask,checkpoint_id
    from .states import context
    from .shugenja_prayer import choose_patron
    from .. import typed_executor as te
    from . import qi_path
    from .devil_heart_second_furnace import move_armament_choice
    row=next(r for r in engine.typed_passive_rows[actor.entity_id] if r.get('block')==BLOCK)
    ctx=context(engine,actor,source,[actor],row['numbers']).with_source(TERRAIN)
    ctx.intent=intent
    chosen=choose_patron(ctx)
    descriptions={
        'air':'outdoors with 100 feet of unobstructed sky',
        'cold':'natural ice or snow occupying a 10-foot cube within 60 feet',
        'earth':'natural soil, stone or mountain within 60 feet',
        'fire':'natural or uncontrolled flame occupying a 5-foot space',
        'lightning':'an active storm overhead or natural lightning in the previous minute',
        'metal':'100 pounds of exposed worked or natural metal within 60 feet',
        'water':'natural water occupying a 10-foot cube within 60 feet',
        'wood':'living vegetation occupying a 10-foot cube within 60 feet'}
    confirmed=ask(engine,intent,checkpoint_id(engine,'shugenja_terrain_confirm'),actor,
        'choice:needle.shugenja_terrain_confirm',['confirm'],labels={'confirm':'Confirm qualifying terrain'},
        automatic=False,allow_decline=True,default='decline',name='Terrain Attunement',feature_id=TERRAIN,
        prompt=f'Terrain Attunement: confirm {descriptions[chosen]} was present when Initiative was rolled. '
        'Terrain created by you or a willing ally in the previous 10 minutes does not qualify. '
        'Decline if these scene facts are not established. AI never guesses terrain provenance.')
    if not confirmed: return True
    options=['qi','temp_hp','move']
    if qi_path.armament_condition(actor) is not None: options.append('armament')
    selected=ask(engine,intent,checkpoint_id(engine,'shugenja_terrain_benefit'),actor,
        'choice:needle.shugenja_terrain_benefit',options,preferred=['temp_hp'],
        labels={'qi':f'Regain your Proficiency Bonus ({row["numbers"]["pb"]}) Qi','temp_hp':f'Gain twice your Proficiency Bonus ({2 * int(row["numbers"]["pb"])}) Temporary Hit Points',
                'move':'Move up to half your Speed without provoking',
                'armament':'Move your Domain Armament up to its normal movement'},
        name='Terrain Attunement',feature_id=TERRAIN,
        prompt='Terrain Attunement: choose one benefit for this scene. No action or resource cost.')
    if selected:
        kind=selected[0]
        if kind=='qi': te.run_effects(ctx,[{'type':'gain_resource','applies_to':'self','resource_id':'resource:core.qi','formula':'pb'}])
        elif kind=='temp_hp': te.run_effects(ctx,[{'type':'temp_hp','applies_to':'self','flat':2*int(row['numbers']['pb'])}])
        elif kind=='move': te.run_effects(ctx,[{'type':'rider_step','distance_ft':engine._effective_speed(actor)//2,'no_oa':True,'label':'Terrain Attunement'}])
        elif kind=='armament':
            from ..alternative_payments import owned
            linked=owned(engine,actor,'tianxia.path.qi_cultivation.feature.domain_armament_link')
            move_armament_choice(ctx,actor,30 if linked else 20,feature_id=TERRAIN,name='Terrain Attunement')
    return True

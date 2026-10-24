"""Dust Cultivator native actions and source-owned particle state.

The five consumers share actual typed acquisition, activation, conditions,
fields, saves, damage and table choices. Physiological exclusions use the
native explicit trait reader; names and damage kinds never supply anatomy.
Cloud save penalties stay activation-local. All additions abstain without
their exact owned source, condition or field profile.
"""
from dataclasses import replace
from typing import Any

from . import effect, hook

CLOUD = 'tianxia.subpath.qi.dust_cultivator.feature.dust_cloud'
CHOKING = 'tianxia.subpath.qi.dust_cultivator.feature.choking_dust'
FREE_CHOKING = 'typed_once_turn:dust_cultivator:free_choking'


def eligible(target: Any, mode: str) -> bool:
    from ..physiology import trait
    from .creature_kinds import matches
    if mode == 'breathing':
        return trait(target, 'breath_dependent') is not False
    return trait(target, 'has_body') is not False and not matches(target, ['incorporeal', 'incorporeal undead'])


@effect('dust_choking_save', harmful=True)
def choking_save(ctx: Any, row: dict[str, Any]) -> None:
    from .. import zones, typed_executor as te
    from ..gate2_runtime_models import DiceSpec
    for target in te.effect_subjects(ctx, {'applies_to': 'target'}, harmful=True):
        if not eligible(target, str(row['mode'])):
            ctx.engine._append_event('PASSIVE_TRIGGERED', ctx.source, actor_id=ctx.actor.entity_id,
                target_ids=(target.entity_id,), payload={'log': 'Choking Dust requires a breathing creature' if row['mode']=='breathing' else 'Eroding Dust requires a corporeal creature'})
            continue
        inside = any(z.active and z.owner_id == ctx.actor.entity_id and CLOUD in z.source_definition_id
                     and zones._inside(ctx.engine, target, z) for z in zones.typed_zones(ctx.engine))
        penalty = te._roll(ctx, DiceSpec(count=1, sides=4), 'DUST_CLOUD_PENALTY') if inside else 0
        sub = replace(ctx, target=target, targets=[target],
                      typed={**ctx.typed, 'dust_cloud_save_penalty': int(penalty)})
        # Keep the nested save in the ordinary typed ``effects`` branch. The
        # compiler, modifier composer, and executor all traverse that contract.
        te.run_effects(sub, row.get('effects') or [])


@hook('save')
def cloud_penalty(ctx: Any, target: Any, ability: str, named: Any) -> dict[str, int] | None:
    penalty = ctx.typed.get('dust_cloud_save_penalty')
    return {'bonus': -int(penalty)} if penalty else None


@effect('dust_eroding_ac', harmful=True)
def eroding_ac(ctx: Any, row: dict[str, Any]) -> None:
    """The printed reduction does not stack, including another caster's use."""
    from .. import typed_executor as te
    te.run_effects(ctx.with_source(CHOKING), [{**row, 'type': 'ac_bonus', 'source_owned': True,
                                            'refresh_across_owners': True}])


@hook('ai_candidate_allowed')
def choking_ai_recipient(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or (action.parameters.get('typed') or {}).get('source') != CHOKING:
        return None
    from ..relations import relation, ENEMY
    return bool(candidate.target_ids) and all(relation(engine, actor, engine.state.actors[aid]) == ENEMY
                                            for aid in candidate.target_ids)


@hook('compile_actions')
def cloud_move_action(info: dict[str, Any]) -> list[Any] | None:
    if CLOUD not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition
    # A CELL action so the shared menu and AI candidates enumerate concrete
    # destinations. candidate_allowed keeps only the source-owned legal ones:
    # a 20-foot open-air route that ends within 60 feet of the caster or their
    # Domain Armament. The range covers such an end point when the cloud is
    # tethered to an Armament rather than to the caster.
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.dust_cloud.move",
        display_name='Dust Cloud: move', owner_id=info['actor_id'], economy='NONE',
        resolution_kind='TYPED', target_kind='CELL', range_ft=120,
        parameters={'typed': {'source': CLOUD, 'numbers': info['numbers'], 'duration': {'kind':'instant'},
            'effects':[{'type':'dust_move_cloud'}], 'riders':[], 'manual_inline_choice':True},
            'dust_cloud_move': True, 'any_cell': True, 'ai_allow_empty_area': True,
            'ai_requires_perceived_destination': True,
            'description':'Once during your turn, move your Dust Cloud up to 20 feet for no action or Qi, keeping it within 60 feet of you or your Domain Armament.'})]


@hook('candidate_allowed')
def cloud_move_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not action.parameters.get('dust_cloud_move'):
        return None
    if (actor.turn_flags.get('moved_zone:Dust Cloud') or primordial(actor)
            or any(z.trigger_profile.get('dust_body_suppression') for z in clouds(engine,actor))):return False
    aim=candidate.destination
    # Historical CELL actions retain their accepted destinations. New native
    # commands use one source-owned square choice, without a false 10,000-ft
    # range or an unrelated straight line of effect from the caster.
    return cloud_destination(engine,actor,aim) if aim is not None else bool(cloud_move_points(engine,actor))


# All family state is sourced by compiled ownership and committed conditions or
# zones. These public readers are shared by the family's five consumers.
MATTER = 'tianxia.subpath.qi.dust_cultivator.feature.dust_to_dust'
STORM = 'tianxia.subpath.qi.dust_cultivator.feature.sandstorm_field'
PRIMORDIAL = 'tianxia.subpath.qi.dust_cultivator.feature.primordial_dust'
FORM = 'condition:typed.dust_cultivator_primordial_dust_flight'


def source_of(action: Any) -> str:
    typed = action.parameters.get('typed') or {}
    return str(typed.get('option_of') or typed.get('source') or '').split('#')[0]


def primordial(actor: Any) -> Any:
    """The actor's native one-minute particle transformation, or None."""
    return next((c for c in actor.conditions.values() if c.condition_id == FORM
                 and c.source_actor_id == actor.entity_id and PRIMORDIAL in c.source_definition_id
                 and c.data.get('dust_primordial')), None)


def clouds(engine: Any, actor: Any) -> list[Any]:
    """Active clouds made by this actor, never another caster's dust."""
    return [z for z in engine.state.zones.values() if z.active and z.owner_id == actor.entity_id
            and CLOUD in z.source_definition_id]


@hook('compile_action')
def dust_actions(action: Any, info: dict[str, Any]) -> Any:
    from copy import deepcopy
    source = source_of(action)
    if source not in {CLOUD, CHOKING, MATTER, STORM, PRIMORDIAL}:
        return None
    typed = deepcopy(action.parameters['typed'])
    update = {}
    if source in (CLOUD,STORM):
        if typed.get('area') is not None:typed['area']['opening_width_milliinch']=1
        if typed.get('zone_spec') is not None:typed['zone_spec']['opening_width_milliinch']=1
    if source in (MATTER,STORM,PRIMORDIAL):
        # Recovery can ask this owner during another actor's action, after
        # suppression or removal. Enroll from the compiled grant, not the
        # currently active body or an unrelated action/reaction.
        typed['manual_inline_choice'] = True
    if source == PRIMORDIAL:
        # Its only target is its own body. Erosion belongs to actual transit.
        update['target_kind'] = 'SELF'
        typed.pop('zone_spec', None)
        typed.pop('area', None)
        for effect_row in typed.get('effects') or []:
            if effect_row.get('condition') == 'dust_cultivator_primordial_dust_flight':
                effect_row.setdefault('condition_data', {})['source_cl'] = int(info['numbers']['cl'])
    if source == STORM:
        update.update(target_kind='CELL', range_ft=90)
    if source == MATTER and any(e.get('type') == 'save' for e in typed.get('effects') or []):
        update['target_kind'] = 'ANY_CREATURE'
    if source == MATTER and any(e.get('type') == 'object_damage' for e in typed.get('effects') or []):
        update['target_kind'] = 'OBJECT'
        for row in typed['effects']:
            if row.get('type') == 'object_damage':
                row['type'] = 'dust_object_damage'
    return action.model_copy(update={**update, 'parameters': {**action.parameters, 'typed': typed, **({'any_cell': True} if source in (CLOUD,STORM) and not action.parameters.get('dust_particle_cloud') else {})}})


@hook('compile_actions')
def particle_choking_actions(info: dict[str, Any]) -> list[Any] | None:
    if not {PRIMORDIAL, CHOKING} <= set(info['owned_ids']):
        return None
    from copy import deepcopy
    from ..gate2_runtime_models import EconomyKind
    result = []
    for action in info['actions']:
        if source_of(action) != CHOKING:
            continue
        for free in (True, False):
            typed = deepcopy(action.parameters['typed'])
            # Particle form extends targeting to every creature inside its cloud;
            # paid and free uses keep the same one-creature target domain.
            result.append(action.model_copy(update={
                'source_definition_id': action.source_definition_id + ('.primordial_free' if free else '.primordial_paid'),
                'display_name': 'Primordial Dust: ' + action.display_name + (' (free)' if free else ' (2 Qi)'),
                'economy': EconomyKind.BONUS_ACTION, 'range_ft': 60,
                'costs': () if free else action.costs,
                'parameters': {**action.parameters, 'typed': typed, 'dust_particle_choking': 'free' if free else 'paid',
                    'description': 'Bonus Action: Choking Dust against one creature, including any creature in your Dust Cloud. Once per turn you can use it for 0 Qi; other uses cost 2 Qi. Requires Primordial Dust.'}}))
    return result or None


@hook('candidate_allowed')
def dust_family_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    source = source_of(action)
    mode = action.parameters.get('dust_particle_choking')
    if mode:
        return bool(primordial(actor)) and (mode != 'free' or not actor.turn_flags.get(FREE_CHOKING))
    if source == CHOKING and primordial(actor):
        return False
    if source == CLOUD and not action.parameters.get('dust_cloud_move'):
        return bool(primordial(actor)) == bool(action.parameters.get('dust_particle_cloud'))
    if source == MATTER and any(e.get('type') in ('object_damage','dust_object_damage') and e.get('flat')==40
            for e in (action.parameters.get('typed') or {}).get('effects') or []):
        obj=engine.state.objects.get(next(iter(candidate.target_ids),None))
        if obj is None or object_source_cl(engine,obj)!=0:
            return False
    if source == MATTER and action.parameters.get('dust_construct'):
        from .creature_kinds import matches
        return bool(candidate.target_ids) and all(matches(engine.state.actors[aid], ['construct']) for aid in candidate.target_ids)
    if action.parameters.get('dust_cloud_move') and primordial(actor):
        return False
    return None


@hook('technique_used')
def particle_choking_used(ctx: Any) -> None:
    if ctx.action.parameters.get('dust_particle_choking') == 'free':
        ctx.actor.turn_flags[FREE_CHOKING] = 1


@effect('dust_defense_ac', harmful=True)
def defense_ac(ctx: Any, row: dict[str, Any]) -> None:
    """One Erode Defense reduction across casters, refreshed on its new clock."""
    from ..typed_executor import run_effects
    run_effects(ctx.with_source(MATTER), [{**row, 'type': 'ac_bonus', 'source_owned': True,
                                           'refresh_across_owners': True}])


@hook('compile_actions')
def construct_erosion_actions(info: dict[str, Any]) -> list[Any] | None:
    if MATTER not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition
    template=next((a for a in info['actions'] if source_of(a)==MATTER),None)
    numbers=dict((template.parameters['typed']['numbers'] if template is not None else info['numbers']))
    count = 8 if int(numbers['cl']) >= 17 else 6
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.{MATTER}.reduce_construct",
        display_name='Dust to Dust: Reduce Structure (Construct)', owner_id=info['actor_id'],
        economy='ACTION', resolution_kind='TYPED', target_kind='ANY_CREATURE', range_ft=60,
        costs=(('resource:core.qi',4),), parameters={'dust_construct': True,
            'typed': {'source':MATTER,'numbers':numbers,'min_cl':10,'manual_inline_choice':True,'duration':{'kind':'instant'},'riders':[],
                'effects':[{'type':'dust_construct_damage','applies_to':'target','dice':{'count':count,'sides':8},'damage_types':['force','necrotic']}]},
            'expected_damage': count*4, 'description':'Action, 4 Qi: one Construct within 60 feet takes '+str(count)+'d8 Force or Necrotic damage. Against Source CL no higher than yours, ignore Resistance and Damage Threshold, but never Immunity.'})]


@effect('dust_construct_damage', harmful=True)
def construct_damage(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .creature_kinds import matches
    for target in te.effect_subjects(ctx, row, harmful=True):
        if not matches(target, ['construct']):
            continue
        sub = replace(ctx, targets=[target], target=target)
        te.run_effects(sub, [{**row, 'type':'damage'}])


@hook('object_targets')
def dust_object_targets(engine: Any, actor: Any, action: Any) -> list[str] | None:
    if source_of(action)!=MATTER or not any(e.get('type')=='dust_object_damage' for e in (action.parameters.get('typed') or {}).get('effects') or []):
        return None
    return [obj.object_id for obj in engine.state.objects.values() if not obj.destroyed and obj.current_hp is not None
            and object_allowed(engine,action,obj)]


def object_allowed(engine: Any, action: Any, obj: Any) -> bool:
    effects=(action.parameters.get('typed') or {}).get('effects') or []
    from ..object_rules import has_tag
    for row in effects:
        if row.get('type')!='dust_object_damage':continue
        if row.get('flat')==40 and object_source_cl(engine,obj)!=0:return False
        if any(not has_tag(obj,tag) for tag in row.get('needs') or []):return False
        if any(has_tag(obj,tag) or obj.component.get(tag) for tag in row.get('forbids') or []):return False
    return True


@hook('object_action', priority=-20)
def dust_object_action(engine: Any, actor: Any, action: Any, obj: Any, candidate: Any, intent: Any) -> bool | None:
    if source_of(action)!=MATTER or not any(e.get('type')=='dust_object_damage' for e in (action.parameters.get('typed') or {}).get('effects') or []):
        return None
    from ..typed_executor import resolve_typed
    resolve_typed(engine,actor,None,action,candidate,intent)
    return True


@effect('dust_object_damage', harmful=True)
def dust_object_damage(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .objects import deal
    obj=ctx.engine.state.objects.get(next(iter(ctx.intent.target_ids),None))
    if obj is None or obj.destroyed or not object_allowed(ctx.engine,ctx.action,obj):return
    ctx.damage_cache['_object']=obj
    if row.get('flat')==40:
        # Fixed damage has no roll to receive Qi Technique Potency.
        amount,kind=40,te.choose_damage_type(ctx,list(row['damage_types']),[])
    else:
        amount,kind=te._damage_roll(ctx,row)
    target_cl=object_source_cl(ctx.engine,obj)
    bypass=not row.get('dust_source_cl_gate') or (target_cl is not None and target_cl<=int(ctx.numbers['cl']))
    deal(ctx.engine,ctx.actor,obj,[(int(amount),str(kind).upper())],ctx.source,
         ignore_threshold=bool(row.get('ignore_threshold') and bypass),
         ignore_resistance=bool(row.get('ignore_resistance') and bypass))


@hook('before_target_reactions')
def storm_choose_viewers(ctx: Any) -> None:
    if source_of(ctx.action) != STORM:
        return
    from ..relations import relation, ALLY
    from .needle import ask, checkpoint_id, CHOICE
    allies = [a for a in ctx.engine.state.actors.values() if a.active and a is not ctx.actor
              and relation(ctx.engine, ctx.actor, a) == ALLY]
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'dust_storm_allies', ctx.source), ctx.actor,
        CHOICE+'dust_storm_allies', [a.entity_id for a in allies],
        labels={a.entity_id:a.display_name for a in allies}, minimum=0, maximum=len(allies), allow_decline=True,
        preferred=[a.entity_id for a in allies], default='all',
        prompt='Sandstorm Field: choose allies who see normally through this field for 1 minute while you maintain Concentration. You always see normally. Creating the field costs an Action and 6 Qi.') if allies else []
    ctx.damage_cache['dust_storm_viewers'] = [ctx.actor.entity_id, *selected]


@effect('dust_storm_viewers')
def storm_viewers(ctx: Any, row: dict[str, Any]) -> None:
    from .tabik_dark import zone_made_now, republish
    zone = zone_made_now(ctx)
    if zone is None:
        return
    zone.trigger_profile['dust_viewers'] = list(ctx.damage_cache.get('dust_storm_viewers') or [ctx.actor.entity_id])
    republish(ctx.engine, zone, ctx.source)


@hook('obscurement_ignored')
def storm_sight(engine: Any, zone: Any, viewer: Any, seen: Any) -> bool | None:
    if (zone.trigger_profile.get('profile') or {}).get('dust_family') != 'sandstorm':
        return None
    return viewer.entity_id in zone.trigger_profile.get('dust_viewers', [zone.owner_id])


@hook('attack_mode')
def storm_ranged_attack(ctx: Any, target: Any) -> str | None:
    # The 10-foot crossing rule also applies when both endpoints are outside.
    # Delivery, not a numeric target-selection range, identifies a ranged roll.
    from ..attack_delivery import is_ranged
    if not is_ranged((ctx.attack_effect or {}).get('attack_kind'),ctx.typed.get('range_ft'),ctx.typed.get('weapon')):
        return None
    for zone in ctx.engine.state.zones.values():
        if not zone.active or (zone.trigger_profile.get('profile') or {}).get('dust_family') != 'sandstorm':
            continue
        if ctx.actor.entity_id in zone.trigger_profile.get('dust_viewers', [zone.owner_id]):
            continue
        from .. import senses, zones
        from ..space import ray
        if senses.pierces(ctx.engine,zone,ctx.actor,target) or zones.obscuration_ignored(ctx.engine,zone,ctx.actor,target):
            continue
        from ..spatial_areas import positions_inside_zone
        def inside(point):
            return positions_inside_zone(ctx.engine,[point],zone)
        path = ray(ctx.actor.position,target.position)
        # Half-square units count the entering/leaving half cells exactly;
        # two endpoints within adjacent squares span 5 feet, not 10 feet.
        half_squares = sum(int(inside(a))+int(inside(b)) for a,b in zip(path,path[1:]))
        if half_squares * ctx.engine.grid.square_size_ft >= 20:
            return 'DISADVANTAGE'
    return None


@effect('dust_primordial_cloud')
def primordial_cloud(ctx: Any, row: dict[str, Any]) -> None:
    from .. import zones
    from .tabik_dark import republish
    release_lesser_physical_holds(ctx)
    for zone in clouds(ctx.engine, ctx.actor):
        zone.concentration_link = False
        zone.radius_cells = 4
        zone.trigger_profile.update(size_ft=20, follows_owner=True, centered_on_self=True)
        zone.center = ctx.actor.position
        zone.affected_cells = zones.unsuppressed_cells(zone,zones.area_cells(ctx.engine,zone))
        republish(ctx.engine, zone, ctx.source)
        release_cloud_concentration(ctx.engine,zone,'Primordial Dust sustains its cloud',retain_zone=True)


@hook('zone_created')
def cloud_particle_shape(ctx: Any, zone: Any) -> None:
    if CLOUD not in zone.source_definition_id:
        return
    from .. import zones
    # A creator maintains at most one cloud even while no concentration ties it.
    for old in clouds(ctx.engine, ctx.actor):
        retire_cloud(ctx.engine,old,'Replaced by the new Dust Cloud')
    if primordial(ctx.actor):
        zone.concentration_link = False
        zone.radius_cells = 4
        zone.trigger_profile.update(size_ft=20, follows_owner=True, centered_on_self=True)
        zone.center = ctx.actor.position
        zone.affected_cells = zones.unsuppressed_cells(zone,zones.area_cells(ctx.engine,zone))


@hook('damage_defenses')
def primordial_defenses(engine: Any, target: Any, damage_type: str, typed: Any, source_actor_id: str) -> list[Any] | None:
    if not primordial(target) or damage_type in ('FORCE','RADIANT','VOID'):
        return None
    return [{'kind':'resistance','damage_types':[damage_type],'feature_id':PRIMORDIAL,'name':'Primordial Dust'}]


@hook('opportunity_allowed')
def primordial_opportunity(engine: Any, reactor: Any, mover: Any) -> bool | None:
    return False if primordial(mover) else None


@hook('pass_through')
def primordial_passage(engine: Any, mover: Any, occupant: Any) -> str | None:
    return 'difficult' if primordial(mover) else None


@hook('condition_attempt')
def primordial_holds(ctx: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    form = primordial(subject)
    tags=set((row.get('information_profile') or {}).get('tags') or ())
    physical=(row.get('physical') is True or row.get('hold_kind')=='ordinary_physical' or ctx.typed.get('physical_grapple') is True
              or ctx.typed.get('unarmed_option')=='grapple' or 'physical_restraint' in tags)
    cl=ctx.numbers.get('cl')
    if (form is None or row.get('condition') not in ('grappled','restrained')
            or not physical or type(cl) is not int or cl<0):
        return None
    if cl <= int(form.data['source_cl']):
        return False
    return None



@hook('pass_through_entered')
def primordial_erosion(engine: Any, mover: Any, occupant: Any, intent: Any) -> None:
    form = primordial(mover)
    if form is None or engine.state.current_actor_id != mover.entity_id:
        return
    from ..relations import relation, ENEMY
    if relation(engine, mover, occupant) != ENEMY:
        return
    key = 'dust_erosion:'+occupant.entity_id
    if mover.turn_flags.get(key):
        return
    mover.turn_flags[key] = 1
    from .. import typed_executor as te
    action = engine.action_catalog.get(form.source_definition_id)
    if action is None:
        return
    typed = {**action.parameters['typed'], 'duration':{'kind':'instant'}}
    ctx = te.Context(engine,mover,action,intent,typed,[occupant],occupant,{})
    te.run_effects(ctx,[{'type':'save','ability':'con','applies_to':'target',
        'on_fail':[{'type':'damage','applies_to':'target','dice':{'count':4,'sides':8},'damage_types':['necrotic']},
                   {'type':'condition','condition':'blinded','applies_to':'target','expires_on':'START_OF_TARGET_NEXT_TURN'}],
        'on_success':[{'type':'half_damage'}]}])


@hook('resistance_ignored')
def construct_resistance(engine: Any, kind: str, typed: dict[str, Any], source_actor_id: str, target: Any) -> bool | None:
    if target is None or not any(e.get('type') == 'dust_construct_damage' for e in typed.get('effects') or []):
        return None
    if str(typed.get('source') or '') != MATTER:
        return None
    bundle = next((b for b in engine.typed_bundle_documents if b.get('actor_id') == target.entity_id), {})
    return int(bundle.get('cl') or 1) <= int((typed.get('numbers') or {}).get('cl') or 1)


def cloud_tethered(engine: Any, actor: Any, aim: Any) -> bool:
    from .qi_path import armament_condition,armament_point
    from ..gate2_runtime_models import Position
    origins=[actor.position]
    if armament_condition(actor) is not None:
        coords=armament_point(actor)
        origins.append(Position(x=coords[0],y=coords[1],z=coords[2] if len(coords)>2 else 0))
    return any(engine.grid.distance_ft(p,aim)<=60 for p in origins)


def cloud_reachable_centers(engine: Any, cloud: Any) -> dict[Any,int]:
    """Shortest native open-air routes, at most 20 feet; creatures do not seal air."""
    from collections import deque
    from itertools import product
    from ..gate2_runtime_models import Position
    from ..read_queries import memo
    from ..opening_passage import grid_with_minimum
    grid=grid_with_minimum(engine,1)
    def calculate():
        start=cloud.center;found={start:0};queue=deque([start])
        directions=tuple(d for d in product((-1,0,1),repeat=3) if any(d))
        while queue:
            point=queue.popleft();cost=found[point]+engine.grid.square_size_ft
            if cost>20:continue
            for dx,dy,dz in directions:
                if point.z+dz<0 or not engine.grid.in_bounds((point.x+dx,point.y+dy)):continue
                nxt=Position(x=point.x+dx,y=point.y+dy,z=point.z+dz)
                if nxt in found or not grid.volume_step_legal(point,nxt):continue
                found[nxt]=cost;queue.append(nxt)
        return found
    return memo(engine,('dust_cloud_air_routes',cloud.zone_id,cloud.center),calculate)


def cloud_move_points(engine: Any, actor: Any) -> dict[Any,int]:
    points={}
    for cloud in clouds(engine,actor):
        for point,cost in cloud_reachable_centers(engine,cloud).items():
            if cost and cloud_tethered(engine,actor,point):points[point]=cost
    return points


def cloud_destination(engine: Any, actor: Any, aim: Any) -> bool:
    """One legal source-owned move, including the caster OR Armament tether."""
    return aim is not None and cloud_tethered(engine,actor,aim) and any(
        aim in cloud_reachable_centers(engine,cloud) for cloud in clouds(engine,actor))


@effect('dust_move_cloud')
def move_cloud(ctx: Any, row: dict[str, Any]) -> None:
    from .. import zones,senses
    from ..gate2_runtime_models import Position
    from .needle import ask,checkpoint_id,cell_id,parse_cell
    from .tabik_dark import republish
    aim=ctx.intent.destination
    if aim is None:
        points=cloud_move_points(ctx.engine,ctx.actor)
        ordered=sorted(points,key=lambda p:(points[p],p.z,p.y,p.x))
        ids=[cell_id(p,include_altitude=True) for p in ordered]
        known=[cell_id(p,include_altitude=True) for p in ordered if senses.perceives_cell(ctx.engine,ctx.actor,p)]
        selected=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'dust_cloud_move',ctx.actor.entity_id),ctx.actor,
            'choice:needle.dust_cloud_move',ids,
            labels={cell_id(p,include_altitude=True):f'Dust Cloud to {p.x},{p.y}, {p.z*5} feet up ({points[p]} feet moved)' for p in ordered},
            prompt=f'{ctx.actor.display_name}: move your Dust Cloud up to 20 feet, for no action or Qi. It must end within 60 feet of you or your Domain Armament. Its remaining duration is unchanged.',
            preferred=known[:1],minimum=0,maximum=1,allow_decline=True,default='first',automatic_options=known,
            name='Dust Cloud: move',feature_id=CLOUD)
        if not selected:return
        x,y,z=parse_cell(selected[0]);aim=Position(x=x,y=y,z=z)
    if not cloud_destination(ctx.engine,ctx.actor,aim):return
    for zone in clouds(ctx.engine,ctx.actor):
        zone.center=aim
        zone.affected_cells=zones.unsuppressed_cells(zone,zones.area_cells(ctx.engine,zone))
        republish(ctx.engine,zone,ctx.source)
    ctx.actor.turn_flags['moved_zone:Dust Cloud']=1


@hook('ai_candidate_allowed')
def cloud_move_known_destination(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not action.parameters.get('dust_cloud_move'):return None
    from .. import senses
    return any(senses.perceives_cell(engine,actor,p) for p in cloud_move_points(engine,actor))


@hook('damage_type_choice')
def dust_damage_choice(ctx: Any, kinds: list[str], targets: list[Any]) -> str | None:
    if source_of(ctx.action) not in {MATTER,STORM} or len(kinds) < 2:
        return None
    from ..fact_consent_admission import admit_choice
    from .effect_durations import token
    key = ('dust_damage_type',tuple(kinds))
    if key not in ctx.damage_cache:
        obj = ctx.damage_cache.get('_object')
        label = ', '.join(t.display_name for t in targets) or (str(obj.component.get('name') or 'the selected object') if obj is not None else 'the selected object')
        triggered=bool(ctx.damage_cache.get('dust_field_trigger'))
        price='No action or additional Qi; this is the field’s entry/start trigger.' if triggered else 'This uses the declared action and Qi cost.'
        # The choice records the caster's intention, never a defender's hidden
        # traits. Both printed kinds are known even on an automatic turn.
        record=admit_choice(ctx,ctx.actor,source_of(ctx.action),'dust_damage_type',
            ctx.source+':'+':'.join(kinds),list(kinds),labels={k:k.title() for k in kinds},
            prompt=f'{ctx.action.display_name}: choose the damage type for {label}. {price} Decline uses {kinds[0].title()}.',
            expires_on=token('end',ctx.actor.entity_id,ctx.actor.turns_started),automatic_options=list(kinds)) if ctx.intent is not None else None
        ctx.damage_cache[key]=record['value'] if record else kinds[0]
    return ctx.damage_cache[key]


def object_source_cl(engine: Any, obj: Any) -> int | None:
    """Read native profile, Formation membership or the committed creation event.

    Only authenticated map furniture is mundane by default. An untracked
    object never becomes ordinary merely because its creator was not stamped.
    """
    unknown=None
    explicit=obj.component.get('source_cl')
    if type(explicit) is int:return explicit if explicit>=0 else unknown
    from . import formations,objects
    for zone in engine.state.zones.values():
        profile=formations.record(zone)
        if profile and any(member.object_id==obj.object_id for member in formations.objects_of(engine,zone)):
            cl=profile.get('cl')
            return cl if type(cl) is int and cl>0 else unknown
    source=objects.created_by(obj) or str(obj.component.get('source') or '')
    if not source:
        creation=next((event for event in engine.events if event.event_type=='OBJECT_UPDATED'
            and (event.payload.get('object') or {}).get('object_id')==obj.object_id),None)
        if creation is not None:source=creation.source_definition_id
    if not source or source==objects.SOURCE:
        rows=(getattr(engine,'battlefield_document',{}) or {}).get('map_objects') or []
        return 0 if not obj.component.get('artifact') and any(objects.object_id(row)==obj.object_id for row in rows) else unknown
    from .source_eligibility import catalog_action
    action=catalog_action(engine,source)
    if action is None:return unknown
    cl=((action.parameters.get('typed') or {}).get('numbers') or {}).get('cl')
    return cl if type(cl) is int and cl>0 else unknown


@hook('compile_actions')
def particle_cloud_action(info: dict[str, Any]) -> list[Any] | None:
    """Compile a concentration-free cloud before admission, never refund it later."""
    if not {CLOUD,PRIMORDIAL} <= set(info['owned_ids']):
        return None
    from copy import deepcopy
    result=[]
    for action in info['actions']:
        if source_of(action)!=CLOUD or action.parameters.get('dust_cloud_move'):
            continue
        typed=deepcopy(action.parameters['typed'])
        typed['duration']={**typed['duration'],'concentration':False}
        typed['area']={'shape':'sphere','size_ft':20,'centered_on_self':True}
        result.append(action.model_copy(update={
            'source_definition_id':action.source_definition_id+'.primordial',
            'concentration':False,'target_kind':'SELF','parameters':{**action.parameters,'typed':typed,'dust_particle_cloud':True}}))
    return result or None


@hook('event',nested=True)
def particle_form_ended(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type!='CONDITION_REMOVED' or (kwargs.get('payload') or {}).get('condition_id') not in (FORM,FORM.replace('condition:typed.','condition:typed.suppressed.',1)):
        return
    actor=engine.state.actors.get(next(iter(kwargs.get('target_ids') or ()),None))
    if actor is None or primordial(actor):
        return
    ended=kwargs.get('ended_effect') or {}
    action=engine.action_catalog.get(ended.get('source_definition_id'))
    if (action is None or action.owner_id!=actor.entity_id or source_of(action)!=PRIMORDIAL
            or ended.get('source_actor_id')!=actor.entity_id or not (ended.get('data') or {}).get('dust_primordial')):
        return
    settle_particle_position(engine,actor,action)
    from .. import zones
    for zone in clouds(engine,actor):
        if zone.trigger_profile.get('follows_owner') and not zone.concentration_link:
            zones.remove(engine,zone,'Primordial Dust ended')


@hook('zone_created')
def dust_field_source(ctx: Any, zone: Any) -> None:
    """Publish authored family facts in the named observer owner's contract."""
    source=source_of(ctx.action)
    if source not in (CLOUD,STORM):
        return
    zone.trigger_profile['information_profile']={
        'tags':['dust','qi_field'] if source==CLOUD else ['particulate_field','qi_field'],
        'source_cl':int(ctx.numbers['cl']),'save_dc':int(ctx.numbers['save_dc']),
        'authority':'ordinary'}


@hook('zone_view_blocked')
def dust_clear_detail(engine: Any, zone: Any, viewer: Any, target: Any, *, sight_only: bool=False) -> bool | None:
    """Limit clear visual detail only; never turn dust into a line-of-effect wall."""
    if not sight_only or not zone.active or CLOUD not in zone.source_definition_id:
        return None
    if viewer.entity_id==zone.owner_id:
        return False
    from .. import senses
    from ..space import ray
    from ..spatial_areas import positions_inside_zone
    if senses.pierces(engine,zone,viewer,target,sight_only=True):
        return False
    def inside(point):
        return positions_inside_zone(engine,[point],zone)
    path=ray(viewer.position,target.position)
    units=sum(int(inside(a))+int(inside(b)) for a,b in zip(path,path[1:]))
    return units*engine.grid.square_size_ft>20


def release_lesser_physical_holds(ctx: Any) -> None:
    """Use the existing hold owner's provenance and linked-marker cleanup."""
    from .physical_holds import source,end_hold
    from .condition_ownership import remove_instance
    for condition in list(ctx.actor.conditions.values()):
        if condition.condition_id not in ('condition:typed.grappled','condition:typed.restrained'):
            continue
        physical,cl=source(ctx.engine,condition)
        if physical and type(cl) is int and cl>=0 and cl<=int(ctx.numbers['cl']):
            end_hold(ctx,condition.instance_id)
            continue
        # Other explicitly physical cultivated effects retain their own source
        # profile; names, damage types and the victim's CL never classify them.
        profile=condition.data.get('information_profile') or {}
        from .source_eligibility import catalog_action
        action=catalog_action(ctx.engine,condition.source_definition_id)
        typed=(action.parameters.get('typed') or {}) if action is not None and action.owner_id==condition.source_actor_id else {}
        explicit=(typed.get('physical_grapple') is True or typed.get('unarmed_option')=='grapple'
                  or 'physical_restraint' in (profile.get('tags') or ()))
        cl=profile.get('source_cl')
        if cl is None:cl=(typed.get('numbers') or {}).get('cl')
        if explicit and type(cl) is int and 0<=cl<=int(ctx.numbers['cl']):
            remove_instance(ctx.engine,ctx.actor,condition.instance_id,ctx.source)


@hook('event',nested=True)
def particle_hold_created(engine: Any, event_type: str, kwargs: dict[str,Any]) -> None:
    if event_type!='CONDITION_APPLIED':return
    for aid in kwargs.get('target_ids') or ():
        actor=engine.state.actors.get(aid)
        if actor is not None:reconcile_particle_holds(engine,actor)


def reconcile_particle_holds(engine: Any, actor: Any) -> None:
    form=primordial(actor)
    if form is None:return
    from .. import typed_executor as te
    action=engine.action_catalog.get(form.source_definition_id)
    if action is None:return
    ctx=te.Context(engine,actor,action,getattr(engine,'_active_intent',None),action.parameters['typed'],[actor],actor,{})
    release_lesser_physical_holds(ctx)


@hook('retained_instance_updated')
def particle_state_updated(engine: Any, holder: Any, kind: str, key: str, item: Any) -> None:
    if (kind!='condition' or item.source_actor_id!=holder.entity_id
            or PRIMORDIAL not in item.source_definition_id or not item.data.get('dust_primordial')):
        return
    if (item.condition_id not in (FORM,FORM.replace('condition:typed.','condition:typed.suppressed.',1))
            or holder.conditions.get(key) is not item):return
    action=engine.action_catalog.get(item.source_definition_id)
    if action is None or action.owner_id!=holder.entity_id or source_of(action)!=PRIMORDIAL:return
    from . import area_suppression
    active=primordial(holder)
    if active is None:
        settle_particle_position(engine,holder,action)
    if active is not None:
        from .. import typed_executor as te
        ctx=te.Context(engine,holder,action,getattr(engine,"_active_intent",None),action.parameters["typed"],[holder],holder,{})
        primordial_cloud(ctx,{})  # Reconcile a normal Cloud created during the suppression gap.
    for cloud in clouds(engine,holder):
        if not cloud.trigger_profile.get('follows_owner') or cloud.concentration_link:continue
        saved=cloud.trigger_profile.get('dust_body_suppression')
        if active is not None:
            if saved:
                cloud.trigger_profile.pop('dust_body_suppression',None)
                if not area_suppression.restore_record(engine,cloud,saved):
                    from .tabik_dark import republish
                    republish(engine,cloud,cloud.source_definition_id)
        elif not saved:
            record=area_suppression.suppress(engine,holder,cloud,'UNTIL_REMOVED',
                action.source_definition_id,retain_whole_when_empty=True)
            if record:
                cloud.trigger_profile['dust_body_suppression']=record['key']
                from .tabik_dark import republish
                republish(engine,cloud,cloud.source_definition_id)
    if active is not None:reconcile_particle_holds(engine,holder)


@hook('zone_trigger_context')
def dust_trigger_choice(ctx: Any, zone: Any, creature: Any, moment: str) -> None:
    if STORM in zone.source_definition_id:
        ctx.damage_cache['dust_field_trigger']=True


def reconcile_particle_removal(engine: Any) -> None:
    """Dust Cloud's explicit, source-qualified environmental dispersal clause."""
    from ..observer_information import world_sources
    from .. import zones,typed_executor as te
    from ..spatial_areas import reaches,positions_inside_zone
    from ..gate2_runtime_models import Position
    from .tabik_dark import republish
    sources=world_sources(engine)
    if not sources:return
    for cloud in list(engine.state.zones.values()):
        if not cloud.active or CLOUD not in cloud.source_definition_id:continue
        cl=int((cloud.trigger_profile.get('numbers') or {}).get('cl') or 0)
        dc=int((cloud.trigger_profile.get('numbers') or {}).get('save_dc') or 0)
        if cl<1 or dc<1:continue
        for source in sources:
            profile=source['profile']
            if profile['targets']=='mundane' or not set(profile['removes'])&{'smoke','dust','airborne_particles'}:continue
            # Ordinary much-lower authority cannot erase the Qi field by
            # repeatedly activating a countermeasure (Shared Qi R4 §2).
            if cl-source['cl']>=6:continue
            center=source['position'];area={'shape':profile['shape'],'size_ft':profile['size_ft'],'height_ft':profile['height_ft']}
            radius=int(cloud.trigger_profile['size_ft'])//engine.grid.square_size_ft
            spec=cloud.trigger_profile
            volume=[Position(x=x,y=y,z=z)
                for x in range(max(0,cloud.center.x-radius),min(engine.grid.width,cloud.center.x+radius+1))
                for y in range(max(0,cloud.center.y-radius),min(engine.grid.height,cloud.center.y+radius+1))
                for z in range(max(0,cloud.center.z-radius),cloud.center.z+radius+1)
                if positions_inside_zone(engine,[(x,y,z)],cloud)]
            if not volume or not all(reaches(engine,center,center,p,area) for p in volume):continue
            # The map owner records this source's printed contest cadence. Its
            # ongoing action is never borrowed from a nearby creature.
            attempts=cloud.trigger_profile.setdefault('dust_world_contests',{})
            previous=attempts.get(source['id'])
            if previous is not None and engine.state.round_number-previous<profile['cadence_rounds']:continue
            attempts[source['id']]=engine.state.round_number
            roll=engine.roller.d20(modifier=profile['check_bonus'],actor_id='map',reason='PARTICLE_REMOVAL:'+source['source'])
            engine._record_roll(roll)
            engine._append_event('CHECK_ROLLED',source['source'],actor_id='map',
                payload={'actor':roll.model_dump(mode='json'),'dc':dc,'success':roll.total>=dc,
                    'roll_kind':'dc_check','against':"Dust Cloud's Cultivation Save DC",'check':'Cultivation Check',
                    'display_name':profile['name'],'zone_id':cloud.zone_id})
            republish(engine,cloud,cloud.source_definition_id)
            if roll.total>=dc:
                retire_cloud(engine,cloud,profile['name']+' disperses the whole Dust Cloud')
                break


@hook('event')
def dust_environment_changed(engine: Any, event_type: str, kwargs: dict[str,Any]) -> None:
    if event_type in ('ZONE_CREATED','MOVEMENT_COMMITTED','TURN_STARTED') and not getattr(engine,'_dust_environment_busy',False):
        engine._dust_environment_busy=True
        try:reconcile_particle_removal(engine)
        finally:engine._dust_environment_busy=False


def release_cloud_concentration(engine: Any, cloud: Any, reason: str, *, retain_zone: bool=False) -> None:
    """Release only the current/held native copy linked to this cloud instance."""
    from .. import concentration
    owner=engine.state.actors.get(cloud.owner_id)
    if owner is None:return
    copies=[state for _iid,state in concentration.held(owner)]
    if owner.concentration is not None:copies.append(owner.concentration)
    for state in copies:
        if state.zone_id==cloud.zone_id:
            concentration.end_copy(engine,owner,state.started_sequence,reason,retain_zone=retain_zone)


def retire_cloud(engine: Any, cloud: Any, reason: str) -> None:
    from .. import zones
    release_cloud_concentration(engine,cloud,reason)
    if cloud.active:zones.remove(engine,cloud,reason)


@hook('technique_used')
def release_cloud_removed_during_creation(ctx: Any) -> None:
    # ZONE_CREATED observers can disperse a cloud before zones.create attaches
    # its concentration copy. Settle that exact copy after normal attachment;
    # never refund cost or end a sibling field/copy.
    if source_of(ctx.action)!=CLOUD:return
    for zone in ctx.engine.state.zones.values():
        if not zone.active and zone.owner_id==ctx.actor.entity_id and CLOUD in zone.source_definition_id:
            release_cloud_concentration(ctx.engine,zone,'Dust Cloud was dispersed while appearing')


def owns_particle_form(engine: Any, actor: Any) -> bool:
    """Compiled native ownership, including before the transformation begins."""
    return any(action.owner_id==actor.entity_id and source_of(action)==PRIMORDIAL
               for action in engine.action_catalog.values())


@hook('hold_tracking')
def particle_hold_tracking(engine: Any, actor: Any) -> bool | None:
    return True if owns_particle_form(engine,actor) else None


@hook('linked_hold_tracking')
def particle_linked_hold_tracking(engine: Any, actor: Any, tracking: str) -> bool | None:
    # The producing row must still name its physical kind and actual parent.
    return True if owns_particle_form(engine,actor) else None


@hook('movement_opening_width')
def particle_opening_width(engine: Any, actor: Any) -> int | None:
    return 1000 if primordial(actor) else None


@hook('transit_stop_allowed')
def particle_transit_stop(engine: Any, actor: Any) -> bool | None:
    # The printed prohibition is at turn end, rather than after each move.
    return True if primordial(actor) else None


@hook('pass_through_stop')
def particle_occupied_stop(engine: Any, mover: Any, occupant: Any) -> bool | None:
    """Use the current scoped endpoint seam; entry still needs passage."""
    return True if primordial(mover) else None


@hook('turn_end')
def particle_illegal_end(engine: Any, actor: Any) -> None:
    form=primordial(actor)
    if form is None:return
    settle_particle_position(engine,actor,engine.action_catalog[form.source_definition_id],turn_end=True)


def settle_particle_position(engine: Any, actor: Any, action: Any, *, turn_end: bool=False) -> None:
    """Settle lost passage and illegal turn ends through one eventful path.

    Grant loss never removes/restores the retained body or changes its clock.
    Only the printed illegal turn-end clause deals damage; suppression/removal
    merely restores a legal placement before the transaction is committed.
    """
    if not actor.active or not engine._on_battlefield(actor):return
    from ..opening_passage import solid_grid
    from ..gate2_runtime_models import Position,DiceSpec
    from .. import typed_executor as te
    grid=solid_grid(engine);occupied=engine._occupied_volumes_except(actor.entity_id)
    footprint=engine._footprint(actor)
    if grid.volume_legal(actor.position,footprint=footprint,occupied_cells=occupied):return
    origin=actor.position
    # Enumerate distance shells; all equally near legal spaces remain available.
    choices=[]
    for distance in range(1,max(grid.width,grid.height,origin.z+2)+1):
        choices=[Position(x=x,y=y,z=z)
            for z in range(max(0,origin.z-distance),origin.z+distance+1)
            for y in range(max(0,origin.y-distance),min(grid.height,origin.y+distance+1))
            for x in range(max(0,origin.x-distance),min(grid.width,origin.x+distance+1))
            if max(abs(x-origin.x),abs(y-origin.y),abs(z-origin.z))==distance
            and grid.volume_legal((x,y,z),footprint=footprint,occupied_cells=occupied)]
        if choices:break
    if not choices:raise ValueError('Primordial Dust requires a nearest legal space on the battlefield.')
    from .needle import ask,checkpoint_id,cell_id,CHOICE
    intent=getattr(engine,'_active_intent',None)
    ids={cell_id(p,include_altitude=True):p for p in choices}
    key='dust_illegal_end' if turn_end else 'dust_passage_lost'
    prompt=('Primordial Dust: choose a nearest legal space. Ending your turn inside a creature or solid object moves you there and deals 4d10 Force damage.'
        if turn_end else f'Primordial Dust: {actor.display_name} has lost particle form while inside a creature or solid object. Choose a nearest legal space to move to; this recovery costs no movement and deals no damage.')
    trigger=engine.action_catalog.get(getattr(engine,'_active_action_source_id',None))
    if not turn_end and trigger is not None:
        cause=engine.state.actors.get(trigger.owner_id)
        prompt+=f' Trigger: {cause.display_name if cause else actor.display_name} uses {trigger.display_name}.'
    selected=ask(engine,intent,checkpoint_id(engine,key,actor.entity_id),actor,
        CHOICE+key,list(ids),labels={key:f'Space ({p.x}, {p.y}), {p.z*5} feet high' for key,p in ids.items()},
        minimum=1,maximum=1,allow_decline=False,preferred=[next(iter(ids))],
        prompt=prompt,name='Primordial Dust',target_id=actor.entity_id)
    actor.position=ids[selected[0]]
    engine._append_event('MOVEMENT_COMMITTED',action.source_definition_id,actor_id=actor.entity_id,
        payload={'destination':actor.position.model_dump(mode='json'),'path':[origin.model_dump(mode='json'),actor.position.model_dump(mode='json')],
                 'cost_ft':0,'forced':True})
    from ..movement_steps import landed
    from .. import zones
    landed(engine,actor,origin,actor.position,intent,forced=True)
    zones.on_moved(engine,actor,origin,actor.position,forced=True)
    engine._remove_zone_leave_conditions(actor)
    if not turn_end:return
    ctx=te.Context(engine,actor,action,intent,{**action.parameters['typed'],'duration':{'kind':'instant'}},[actor],actor,{})
    amount=te._roll(ctx,DiceSpec(count=4,sides=10),'PRIMORDIAL_SETTLEMENT')
    te._deal(ctx,actor,amount,'FORCE')


# Native scene ownership is supplied by JourneyStore, not inferred from a rest,
# inactivity, or the end of a fight. Only this source's printed use is restored.
SCENE_STATE = 'tianxia.subpath.qi.dust_cultivator'


def primordial_use_counters(bundle: dict[str, Any]) -> set[str]:
    """The compiler's actual once-use costs, qualified by owned source."""
    return {key for action in bundle.get('action_catalog', [])
        if ((action.get('parameters', {}).get('typed') or {}).get('option_of')
            or (action.get('parameters', {}).get('typed') or {}).get('source')) == PRIMORDIAL
        and action.get('owner_id') == bundle.get('actor_id')
        for key, amount in action.get('costs', [])
        if key.startswith('resource:uses.') and amount == 1}


def save_particle_scene(session: Any, actor_id: str, spent: int) -> None:
    actor = session.state['actors'][actor_id]
    actor.setdefault('source_states', {})[SCENE_STATE] = {
        'scene_id': session.state.get('scene_id', session.state['journey_id']),
        'primordial_spent': int(spent)}


@hook('journey_initialize')
def restore_particle_scene(session: Any, actor_id: str) -> None:
    from ..journey import require
    actor = session.state['actors'][actor_id]
    counters = primordial_use_counters(actor['bundle'])
    if not counters:
        return
    saved = actor.get('source_states', {}).get(SCENE_STATE)
    if saved is None:
        save_particle_scene(session, actor_id, int(any(actor['resources'].get(k, 1) == 0 for k in counters)))
        return
    require(isinstance(saved, dict) and set(saved) == {'scene_id', 'primordial_spent'}
        and type(saved['scene_id']) is str and saved['scene_id']
        and type(saved['primordial_spent']) is int and saved['primordial_spent'] in (0, 1),
        'Dust continuation needs its recorded scene identity and spent-use flag.')
    session.state.setdefault('scene_id', saved['scene_id'])
    # Joining a party does not end either creature's previous situation or
    # renew a use. Adopt this session's opaque continuation identity while
    # retaining each creature's actual spent flag and an audit of the relabel.
    if session.state['scene_id'] != saved['scene_id']:
        session.emit('SOURCE_SCENE_CONTINUED', actor_id, source=PRIMORDIAL,
            previous_scene=saved['scene_id'], current_scene=session.state['scene_id'],
            text='Dust scene use continues with the party; no use, Qi or health is recovered.')
    for key in counters:
        actor['resources'][key] = 1 - saved['primordial_spent']
    save_particle_scene(session, actor_id, saved['primordial_spent'])


@hook('journey_encounter_settled')
def settle_particle_scene(session: Any, actor_id: str, engine: Any, creature: Any) -> None:
    counters = primordial_use_counters(session.state['actors'][actor_id]['bundle'])
    if counters:
        # These are the actual terminal native cost balances, never a declared
        # or fixture-supplied activation receipt.
        save_particle_scene(session, actor_id, int(any(creature.resources.get(k, 1) == 0 for k in counters)))


@hook('journey_scene_end')
def renew_particle_scene(session: Any, previous: str, current: str) -> None:
    for actor_id, actor in session.state['actors'].items():
        counters = primordial_use_counters(actor['bundle'])
        if not counters:
            continue
        for key in counters:
            actor['resources'][key] = 1
        save_particle_scene(session, actor_id, 0)
        session.emit('SOURCE_SCENE_USE_RENEWED', actor_id, source=PRIMORDIAL,
            previous_scene=previous, next_scene=current,
            text='Primordial Dust is available once in the new scene; Qi and health are unchanged.')

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
    clear_erosion_modifiers(ctx, CHOKING)
    te.run_effects(ctx.with_source(CHOKING), [{**row, 'type': 'ac_bonus', 'source_owned': True}])


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
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.dust_cloud.move",
        display_name='Dust Cloud: move', owner_id=info['actor_id'], economy='NONE',
        resolution_kind='TYPED', target_kind='CELL', range_ft=10000,
        parameters={'typed': {'source': CLOUD, 'numbers': info['numbers'], 'duration': {'kind':'instant'},
            'effects':[{'type':'dust_move_cloud'}], 'riders':[]},
            'dust_cloud_move': True, 'any_cell': True, 'ai_allow_empty_area': True,
            'ai_requires_perceived_destination': True,
            'description':'Once during your turn, move your Dust Cloud up to 20 feet for no action or Qi, keeping it within 60 feet of you or your Domain Armament.'})]


@hook('candidate_allowed')
def cloud_move_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not action.parameters.get('dust_cloud_move'):
        return None
    aim = candidate.destination
    return aim is not None and not actor.turn_flags.get('moved_zone:Dust Cloud') and not primordial(actor) and cloud_destination(engine, actor, aim)


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
                    'description': 'Bonus Action: Choking Dust against one creature, including any creature in your Dust Cloud. The first use each turn costs 0 Qi; further uses cost 2 Qi. Requires Primordial Dust.'}}))
    return result or None


@hook('candidate_allowed')
def dust_family_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    source = source_of(action)
    mode = action.parameters.get('dust_particle_choking')
    if mode:
        return bool(primordial(actor)) and (mode != 'free' or not actor.turn_flags.get('dust_free_choking'))
    if source == CHOKING and primordial(actor):
        return False
    if source == CLOUD and not action.parameters.get('dust_cloud_move'):
        return bool(primordial(actor)) == bool(action.parameters.get('dust_particle_cloud'))
    if source == MATTER and any(e.get('type')=='object_damage' and e.get('flat')==40
            for e in (action.parameters.get('typed') or {}).get('effects') or []):
        obj=engine.state.objects.get(next(iter(candidate.target_ids),None))
        if obj is None or object_source_cl(engine,obj)>0:
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
        ctx.actor.turn_flags['dust_free_choking'] = 1


@effect('dust_defense_ac', harmful=True)
def defense_ac(ctx: Any, row: dict[str, Any]) -> None:
    """One Erode Defense reduction across casters, refreshed on its new clock."""
    from ..typed_executor import run_effects
    clear_erosion_modifiers(ctx, MATTER)
    run_effects(ctx.with_source(MATTER), [{**row, 'type': 'ac_bonus', 'source_owned': True}])


@hook('compile_actions')
def construct_erosion_actions(info: dict[str, Any]) -> list[Any] | None:
    if MATTER not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition
    count = 8 if int(info['numbers']['cl']) >= 17 else 6
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.{MATTER}.reduce_construct",
        display_name='Dust to Dust: Reduce Structure (Construct)', owner_id=info['actor_id'],
        economy='ACTION', resolution_kind='TYPED', target_kind='ANY_CREATURE', range_ft=60,
        costs=(('resource:core.qi',4),), parameters={'dust_construct': True,
            'typed': {'source':MATTER,'numbers':info['numbers'],'min_cl':10,'duration':{'kind':'instant'},'riders':[],
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


@hook('object_action', priority=-20)
def dust_object_action(engine: Any, actor: Any, action: Any, obj: Any, candidate: Any, intent: Any) -> bool | None:
    if source_of(action) != MATTER:
        return None
    typed = action.parameters.get('typed') or {}
    effects = [e for e in typed.get('effects') or [] if e.get('type') == 'object_damage']
    if not effects:
        return None
    from .. import typed_executor as te
    from .objects import deal
    ctx = te.Context(engine, actor, action, intent, typed, [], None, {})
    ctx.damage_cache['_object'] = obj
    for row in effects:
        if row.get('flat')==40 and object_source_cl(engine,obj)>0:
            return True
        amount, kind = te._damage_roll(ctx, row)
        bypass = not row.get('dust_source_cl_gate') or object_source_cl(engine,obj) <= int(ctx.numbers['cl'])
        deal(engine, actor, obj, [(int(amount), str(kind).upper())], ctx.source,
             ignore_threshold=bool(row.get('ignore_threshold') and bypass),
             ignore_resistance=bool(row.get('ignore_resistance') and bypass))
    return True


@hook('before_target_reactions')
def storm_choose_viewers(ctx: Any) -> None:
    if source_of(ctx.action) != STORM:
        return
    from ..relations import relation, ALLY
    from ..target_knowledge import located
    from .needle import ask, checkpoint_id, CHOICE
    allies = [a for a in ctx.engine.state.actors.values() if a.active and a is not ctx.actor
              and relation(ctx.engine, ctx.actor, a) == ALLY and located(ctx.engine, ctx.actor, a)]
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
    if not ctx.typed.get('range_ft') and not ctx.action.parameters.get('ranged'):
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
        cells = {(p.x,p.y) for p in zone.affected_cells}
        base = zone.center.z * ctx.engine.grid.square_size_ft
        height = int(zone.trigger_profile.get('height_ft') or 30)
        def inside(point):
            x,y,z = point
            return (x,y) in cells and base <= z * ctx.engine.grid.square_size_ft < base+height
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
        zone.affected_cells = zones.area_cells(ctx.engine, zone)
        republish(ctx.engine, zone, ctx.source)
    # Releasing the concentration after unlinking cannot erase the surviving
    # cloud. It frees concentration for another legal field.
    conc = ctx.actor.concentration
    if conc is not None and CLOUD in conc.source_definition_id:
        from .. import concentration
        concentration.end_copy(ctx.engine, ctx.actor, conc.started_sequence, 'Primordial Dust sustains its cloud', retain_zone=True)


@hook('zone_created')
def cloud_particle_shape(ctx: Any, zone: Any) -> None:
    if CLOUD not in zone.source_definition_id:
        return
    from .. import zones
    # A creator maintains at most one cloud even while no concentration ties it.
    for old in clouds(ctx.engine, ctx.actor):
        old.active = False
        ctx.engine._append_event('ZONE_REMOVED', old.source_definition_id, actor_id=ctx.actor.entity_id,
                                payload={'zone_id':old.zone_id})
    if primordial(ctx.actor):
        zone.concentration_link = False
        zone.radius_cells = 4
        zone.trigger_profile.update(size_ft=20, follows_owner=True, centered_on_self=True)
        zone.center = ctx.actor.position
        zone.affected_cells = zones.area_cells(ctx.engine, zone)


@hook('damage_defenses')
def primordial_defenses(engine: Any, target: Any, damage_type: str, typed: Any, source_actor_id: str) -> list[Any] | None:
    if not primordial(target) or damage_type in ('FORCE','RADIANT','VOID'):
        return None
    return [{'kind':'resistance','damage_types':[damage_type]}]


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
    physical=(row.get('physical') is True or ctx.typed.get('physical_grapple') is True
              or ctx.typed.get('unarmed_option')=='grapple' or 'physical_restraint' in tags)
    cl=ctx.numbers.get('cl')
    if (form is None or row.get('condition') not in ('grappled','restrained')
            or not physical or type(cl) is not int or cl<1):
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


def cloud_destination(engine: Any, actor: Any, aim: Any) -> bool:
    """Printed movement tether: caster OR a live Domain Armament, not both."""
    from .qi_path import armament_condition, armament_point
    from ..gate2_runtime_models import Position
    origins = [actor.position]
    if armament_condition(actor) is not None:
        x,y = armament_point(actor)
        origins.append(Position(x=x,y=y))
    if not any(engine.grid.distance_ft(p,aim) <= 60 for p in origins):
        return False
    return any(engine.grid.distance_ft(z.center,aim) <= 20
               and not any(tuple(c) in engine.grid.blocked for c in engine.grid.ray_cells(z.center,aim))
               for z in clouds(engine,actor))


@effect('dust_move_cloud')
def move_cloud(ctx: Any, row: dict[str, Any]) -> None:
    from .. import zones
    from .tabik_dark import republish
    aim = ctx.intent.destination
    if aim is None or not cloud_destination(ctx.engine,ctx.actor,aim):
        return
    for zone in clouds(ctx.engine,ctx.actor):
        zone.center = aim
        zone.affected_cells = zones.area_cells(ctx.engine,zone)
        republish(ctx.engine,zone,ctx.source)
    ctx.actor.turn_flags['moved_zone:Dust Cloud'] = 1


@hook('damage_type_choice')
def dust_damage_choice(ctx: Any, kinds: list[str], targets: list[Any]) -> str | None:
    if source_of(ctx.action) not in {MATTER,STORM} or len(kinds) < 2:
        return None
    from .needle import ask,checkpoint_id,CHOICE
    key = ('dust_damage_type',tuple(kinds))
    if key not in ctx.damage_cache:
        obj = ctx.damage_cache.get('_object')
        label = ', '.join(t.display_name for t in targets) or (str(obj.component.get('name') or 'the selected object') if obj is not None else 'the selected object')
        chosen = ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'dust_damage_type',ctx.source),ctx.actor,
            CHOICE+'dust_damage_type',list(kinds),labels={k:k.title() for k in kinds},
            prompt=f'{ctx.action.display_name}: choose the damage type for {label}. This uses the declared action and Qi cost.',
            preferred=list(kinds)[:1],name=ctx.action.display_name,feature_id=source_of(ctx.action))
        ctx.damage_cache[key] = chosen[0] if chosen else kinds[0]
    return ctx.damage_cache[key]


def clear_erosion_modifiers(ctx: Any, source: str) -> None:
    """A printed same-name defense penalty replaces earlier casters' instances."""
    from ..typed_executor import effect_subjects
    for subject in effect_subjects(ctx,{'applies_to':'target'},harmful=True):
        for mid, modifier in list(subject.modifiers.items()):
            if modifier.source_definition_id == source and modifier.target_field == 'armor_class':
                ctx.engine._remove_modifier_instance(subject,mid,ctx.source,actor_id=ctx.actor.entity_id,
                    payload={'modifier_id':mid,'reason':'REFRESHED'})


def object_source_cl(engine: Any, obj: Any) -> int:
    """Native authored CL or creator action CL; ordinary map furniture is CL 0."""
    if type(obj.component.get('source_cl')) is int:
        return obj.component['source_cl']
    from .objects import created_by
    source = created_by(obj) or str(obj.component.get('source') or '')
    if not source:
        return 0
    action = engine.action_catalog.get(source)
    if action is None:
        # Unknown cultivated authority must not be treated as ordinary matter.
        return 1000000
    return int(((action.parameters.get('typed') or {}).get('numbers') or {}).get('cl') or 1000000)


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


@hook('event')
def particle_form_ended(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type!='CONDITION_REMOVED' or (kwargs.get('payload') or {}).get('condition_id')!=FORM:
        return
    actor=engine.state.actors.get(next(iter(kwargs.get('target_ids') or ()),None))
    if actor is None or primordial(actor):
        return
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
    from .. import senses,typed_executor as te
    from ..space import ray
    from ..gate2_runtime_models import Position
    if senses.pierces(engine,zone,viewer,target,sight_only=True):
        return False
    cells={(p.x,p.y) for p in zone.affected_cells}
    area={'shape':'sphere','size_ft':int(zone.trigger_profile['size_ft'])}
    def inside(point):
        x,y,z=point
        return (x,y) in cells and te.in_area(engine,zone.center,zone.center,Position(x=x,y=y,z=z),area)
    path=ray(viewer.position,target.position)
    units=sum(int(inside(a))+int(inside(b)) for a,b in zip(path,path[1:]))
    return units*engine.grid.square_size_ft>20


def release_lesser_physical_holds(ctx: Any) -> None:
    """Transformation ends native lower/equal-CL physical holds already present."""
    from .source_eligibility import catalog_action
    from .condition_ownership import remove_instance
    for condition in list(ctx.actor.conditions.values()):
        if condition.condition_id not in ('condition:typed.grappled','condition:typed.restrained'):
            continue
        profile=condition.data.get('information_profile') or {}
        action=catalog_action(ctx.engine,condition.source_definition_id)
        typed=(action.parameters.get('typed') or {}) if action is not None else {}
        physical=(typed.get('physical_grapple') is True or typed.get('unarmed_option')=='grapple'
                  or 'physical_restraint' in (profile.get('tags') or ()))
        cl=profile.get('source_cl') or (typed.get('numbers') or {}).get('cl')
        if physical and type(cl) is int and cl>=1 and cl<=int(ctx.numbers['cl']):
            remove_instance(ctx.engine,ctx.actor,condition.instance_id,ctx.source)

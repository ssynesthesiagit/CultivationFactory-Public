"""Primordial Syllable: native source contests and all four printed modes.

Consent belongs to each recipient. Passage uses a transient native flight-route
capability only during the granted move; it creates neither flight state nor a
teleport. Every endpoint remains in the chooser, with no top-N truncation.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from . import effect, hook

FEATURE = 'tianxia.subpath.qi.mantra_cultivator.feature.primordial_syllable'
PASSAGE = ContextVar('mantra_passage', default=None)


@hook('button_description')
def syllable_help(row):
    typed = (row.get('parameters') or {}).get('typed') or {}
    selected = next((r for r in typed.get('effects',()) if r.get('type')=='primordial_syllable'), None)
    if selected is None:
        return None
    mode = selected['mode']
    text = {'shattering': 'Hostile creatures make Constitution saves: 10d8 ' + selected.get('damage_type','Thunder').title()
                + ' damage and Prone on failure; half damage without being knocked down on success. Unattended objects, temporary barriers, vehicles, structures and Formation Anchors take double damage.',
            'stillness':'Hostile creatures make Charisma saves. Failure: Stunned until the end of your next turn. Success: no Reactions until the start of their next turn.',
            'renewal':'Each willing creature heals 5d8 plus your Qi key ability modifier Hit Points and may end one Charmed, Deafened, Frightened, Poisoned or Restrained condition from an equal or lower Cultivation Level source. Against a higher-level source, immediately repeat its save with Advantage instead.',
            'passage':'Choose up to your Proficiency Bonus in willing creatures. Move each up to 60 feet to a legal place it can see, without Opportunity Attacks. The move can cross open air and gaps, but cannot pass solid barriers, Total Cover, sealed Formations or spaces too small. This is movement, not teleportation.'}[mode]
    return ('Action; spend 8 Qi; once per scene. A 60-foot-radius sphere originates from you or your Domain Armament. '
            'You can use it while Silenced. Sound suppression of no higher Cultivation Level in the area pauses only until this technique finishes; explicit superior protections remain. ' + text)


@hook('compile_action')
def syllable_metadata(action, info):
    typed = action.parameters.get('typed') or {}
    feature = typed.get('option_of') or typed.get('source')
    if feature == FEATURE:
        # Spell-component restrictions are not imported. This printed exception
        # bypasses ordinary silence, not Incapacitated or absolute authority.
        return action.model_copy(update={'parameters': {**action.parameters,
            'typed': {**typed, 'voice_exception': True}}})


def source_profile(engine, source):
    action = engine.action_catalog.get(source)
    return (action.parameters.get('typed') or {}) if action else {}


def sound_rule(rule):
    return any(rule.get(k) for k in ('silenced', 'cant_speak', 'sound_blocked', 'voice_sealed', 'audible_techniques_blocked'))


def suppressible(ctx, profile, source_cl):
    from ..source_authority import explicit_superior
    authority = profile.get('protection_authority') or profile.get('source_profile') or {}
    return (type(source_cl) is int and 0 < source_cl <= int(ctx.numbers['cl'])
            and not explicit_superior(profile) and not explicit_superior(authority))


def targets(ctx):
    from ..action_geometry import point
    from ..spatial_areas import actor_in_area
    origin = point(ctx.engine, ctx.actor)
    area = {'shape': 'sphere', 'size_ft': 60}
    return origin, [a for a in ctx.engine.state.actors.values() if a.active
                    and actor_in_area(ctx.engine, a, origin, origin, area)]


def receives(ctx,recipient,origin):
    from ..sound_transmission import boundaries,path_allowed
    from ..spatial_areas import actor_positions
    from ..object_geometry import target_cells
    cells = (target_cells(ctx.engine, recipient) if hasattr(recipient, 'object_id')
             else actor_positions(ctx.engine, recipient))
    # A large target is acoustically exposed if any occupied cell has a clear
    # path; testing only its anchor incorrectly rejects reachable portions.
    return any((rows := boundaries(ctx.engine,ctx.actor,recipient,origin=origin,at=cell)) is not None
               and path_allowed(ctx,rows) for cell in cells)


@effect('primordial_syllable')
def syllable(ctx, row):
    from .. import zones as zone_rules
    from ..typed_executor import run_effects, area_cells
    from ..effect_suspension import suspend
    from .end_effect import condition_rule, known_source_cl
    from . import placed
    from .willing_targets import asks_consent
    from .rider_choices import pick
    from ..spatial_areas import positions_inside_zone
    from ..source_authority import ABSOLUTE
    origin, pool = targets(ctx)
    volume = (origin, *area_cells(ctx.engine, origin, origin,
                                  {'shape':'sphere','size_ft':60}, include_altitude=True))
    held_zones, held_conditions = [], []
    from ..sound_transmission import suspend_boundaries, boundaries, path_allowed
    from ..gate2_runtime_models import Position
    from ..typed_executor import in_area
    map_sources = [r for r in ((getattr(ctx.engine,'battlefield_document',None) or {}).get('sound') or {}).get('boundaries',())
        if r.get('kind') in {'silence','ward'} and not r.get('absolute')
        and type(r.get('source_cl')) is int and r['source_cl'] <= int(ctx.numbers['cl'])
        and any(in_area(ctx.engine,origin,origin,Position(x=x,y=y,z=origin.z),{'shape':'sphere','size_ft':60}) for x,y in r['cells'])]
    for zone in zone_rules.typed_zones(ctx.engine):
        profile = source_profile(ctx.engine, zone.source_definition_id)
        inside = zone.trigger_profile.get('inside') or []
        is_sound = any(sound_rule(r.get('rule') or {}) for r in inside) or zone.trigger_profile.get('sound_suppression')
        cl = placed.source_cl(ctx.engine,zone)
        # Overlap is measured in native 3D geometry, including a large field
        # whose centre lies outside the Syllable but whose edge intersects it.
        overlap = any(positions_inside_zone(ctx.engine, [(p.x,p.y,p.z)], zone)
                      for p in volume)
        if is_sound and overlap and suppressible(ctx, profile, cl):
            held_zones.append(zone)
    for actor in pool:
        for c in actor.conditions.values():
            if sound_rule(condition_rule(c, c.condition_id.removeprefix('condition:typed.'))):
                profile = {**source_profile(ctx.engine,c.source_definition_id),
                           **{k:c.data[k] for k in ('protection_authority','source_profile','absolute','authority','tags') if k in c.data}}
                if suppressible(ctx, profile, known_source_cl(ctx, c)):
                    held_conditions.append((actor, c))
    if map_sources:
        ctx.engine._append_event('PASSIVE_TRIGGERED',ctx.source,actor_id=ctx.actor.entity_id,
            payload={'text':'Primordial Syllable temporarily suspends eligible sound suppression until it finishes.',
                     'sound_sources':[{'name':r['name'],'source_cl':r['source_cl']} for r in map_sources]})
    with suspend(ctx.engine, ctx.source, held_zones, held_conditions), suspend_boundaries(ctx.engine,map_sources):
        # Activation's silence exception does not erase a remaining superior,
        # physical or explicit absolute sound protection. Deafness alone is
        # never queried here; the printed source does not require hearing.
        pool = [a for a in pool if receives(ctx,a,origin)]
        kind = row['mode']
        if kind in {'shattering', 'stillness'}:
            hostile = [a for a in pool if a.team_id != ctx.actor.team_id]
            inner = replace(ctx, targets=hostile, target=None)
            if kind == 'shattering':
                damage_type = row['damage_type']
                damage = {'type': 'damage', 'applies_to': 'target', 'dice': {'count': 10, 'sides': 8}, 'damage_types': [damage_type]}
                run_effects(inner, [{'type': 'save', 'applies_to': 'enemies_in_area', 'ability': 'con',
                    'on_fail': [damage, {'type': 'condition', 'condition': 'prone', 'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'}],
                    'on_success': [{'type': 'half_damage'}]}])
                # Objects do not make creature saves; native object geometry
                # preserves cover even when this blast destroys a barrier.
                from .objects import area_reaches, deal
                from ..typed_executor import _damage_roll
                from ..object_rules import has_tag
                objects = [o for o in ctx.engine.state.objects.values() if not o.destroyed
                    and o.current_hp is not None and any(has_tag(o, tag) for tag in
                        ('unattended','temporary_barrier','vehicle','structure','formation_anchor'))
                    and area_reaches(ctx.engine, origin, origin, o, {'shape': 'sphere', 'size_ft': 60})
                    and receives(ctx,o,origin)]
                from .docket_walls import defense_stats, hit_points_left, damage_section
                from ..typed_executor import in_area
                walls = []
                for zone in zone_rules.typed_zones(ctx.engine):
                    stats = defense_stats(inner, zone) if zone.trigger_profile.get('wall') else None
                    if not stats:
                        continue
                    for cell in zone.affected_cells:
                        if (hit_points_left(zone,cell)>0 and in_area(ctx.engine,origin,origin,cell,{'shape':'sphere','size_ft':60})
                                and ctx.engine.grid.line_of_sight(origin,cell)):
                            from types import SimpleNamespace
                            if receives(ctx,SimpleNamespace(position=cell),origin):
                                walls.append((zone,cell,stats))
                            if stats['scope']=='wall':
                                break
                if objects or walls:
                    amount, dtype = _damage_roll(inner, damage)
                    for obj in objects:
                        deal(ctx.engine, ctx.actor, obj, [(amount, dtype)], ctx.source, multiplier=2)
                    for zone,cell,stats in walls:
                        dealt=0 if dtype in stats['immune'] else amount*2
                        if dtype in stats.get('resist',()):dealt//=2
                        if dtype in stats.get('vulnerable',()):dealt*=2
                        damage_section(ctx.engine,zone,cell,dealt,ctx.source,dtype)
            else:
                run_effects(inner, [{'type': 'save', 'applies_to': 'enemies_in_area', 'ability': 'cha',
                    'on_fail': [{'type': 'condition', 'applies_to': 'target', 'condition': 'stunned', 'expires_on': 'END_OF_SOURCE_NEXT_TURN'}],
                    'on_success': [{'type': 'condition', 'applies_to': 'target', 'condition': 'reaction_denied', 'expires_on': 'START_OF_TARGET_NEXT_TURN'}]}])
        else:
            eligible = pool
            if kind == 'passage':
                from .. import stealth
                preferred = [a.entity_id for a in eligible if a.team_id == ctx.actor.team_id
                             and (a is ctx.actor or stealth.sees(ctx.engine, ctx.actor, a))]
                chosen = pick(ctx.engine, ctx.actor, 'syllable_recipients', 'Primordial Syllable: Passage',
                    [a.entity_id for a in eligible], subject=ctx.actor, intent=ctx.intent, optional=True, minimum=0,
                    maximum=int(ctx.numbers['pb']), preferred=preferred[:int(ctx.numbers['pb'])],
                    labels={a.entity_id:a.display_name for a in eligible},
                    prompt=f'Primordial Syllable: Passage. Choose up to {ctx.numbers["pb"]} willing creatures within 60 feet to move up to 60 feet without Opportunity Attacks. No extra Qi cost.')
                eligible = [a for a in eligible if a.entity_id in chosen]
            for actor in eligible:
                if not asks_consent(ctx.engine, ctx.intent, actor, ctx.action.display_name,
                    f'{ctx.actor.display_name} uses {ctx.action.display_name}: does {actor.display_name} accept '
                    + ('healing and the option to end one condition?' if kind == 'renewal' else 'movement up to 60 feet, without Opportunity Attacks?'),
                    prefer_accept=actor.team_id == ctx.actor.team_id, asker=ctx.actor):
                    continue
                inner = replace(ctx, targets=[actor], target=actor)
                if kind == 'renewal':
                    run_effects(inner, [{'type': 'healing', 'applies_to': 'target', 'dice': {'count': 5, 'sides': 8}, 'formula': 'key_ability_modifier'}])
                    cleanse(inner)
                else:
                    passage(inner)


def cleanse(ctx):
    from .end_effect import known_source_cl, condition_rule
    from .condition_ownership import remove_instance
    from .rider_choices import pick
    actor = ctx.target
    allowed = {'charmed','deafened','frightened','poisoned','restrained'}
    conditions = []
    for c in actor.conditions.values():
        name = c.condition_id.removeprefix('condition:typed.')
        rule = condition_rule(c, name)
        # Features may carry a listed condition under their own stable ID.
        semantic = {name, str(rule.get('condition') or ''), str(rule.get('condition_id') or '')}
        if semantic.isdisjoint(allowed) or known_source_cl(ctx, c) is None:
            continue
        conditions.append(c)
    if not conditions:
        return
    options = {str(i):c for i,c in enumerate(conditions)}
    labels = {key: 'End ' + c.condition_id.rsplit('.',1)[-1].title() if known_source_cl(ctx,c) <= int(ctx.numbers['cl'])
              else 'Repeat the save against ' + c.condition_id.rsplit('.',1)[-1].title() + ' with Advantage'
              for key,c in options.items()}
    chosen = pick(ctx.engine, actor, 'syllable_cleanse', 'Primordial Syllable: Renewal', list(options),
        subject=actor, intent=ctx.intent, labels=labels, preferred=list(options)[:1],
        prompt=f'Primordial Syllable: Renewal healed {actor.display_name}. You may end one listed condition; a higher Cultivation Level source instead allows an immediate save with Advantage. No additional cost.')
    if not chosen:
        return
    c = options[chosen[0]]
    if known_source_cl(ctx,c) <= int(ctx.numbers['cl']):
        remove_instance(ctx.engine, actor, c.instance_id, ctx.source)
    else:
        spec = c.data.get('repeat_save') or c.data.get('origin_save')
        if spec:
            roll = ctx.engine._roll_save(actor, spec['ability'], spec['dc'], c.source_definition_id,
                extra_mode='ADVANTAGE', roll_context={'source_actor_id':c.source_actor_id,'named':[c.condition_id.rsplit('.',1)[-1]]})
            if roll and roll.total >= spec['dc']:
                remove_instance(ctx.engine, actor, c.instance_id, ctx.source)


@contextmanager
def passage_scope(engine, actor):
    token = PASSAGE.set((engine, actor.entity_id))
    try:
        yield
    finally:
        PASSAGE.reset(token)


@hook('flight')
def passage_capability(engine, actor):
    if PASSAGE.get() == (engine, actor.entity_id):
        return {'fly_speed_ft':60, 'flight_hover':1}


def passage(ctx):
    from .granted_movement import choices, move
    from .needle import ask, checkpoint_id, cell_id
    from ..senses import perceives_cell
    actor = ctx.target
    with passage_scope(ctx.engine, actor):
        paths = choices(ctx.engine, actor, 60)
        paths = [c for c in paths if perceives_cell(ctx.engine, actor, c.destination)]
        options = {cell_id(c.destination, include_altitude=True) + ':' + c.candidate_id:c for c in paths}
        stay = cell_id(actor.position, include_altitude=True)
        labels = {key:f'Move {actor.display_name} to {c.destination.x}, {c.destination.y}, height {c.destination.z * 5} feet' for key,c in options.items()}
        labels[stay] = f'Leave {actor.display_name} in place'
        chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine,'syllable_destination',actor.entity_id),ctx.actor,
            'choice:needle.syllable_destination', list(labels), labels=labels, preferred=[stay],
            prompt=f'Primordial Syllable: Passage. Move {actor.display_name} up to 60 feet to a place it can see; no Opportunity Attacks. Walls and sealed boundaries still block the route.')
        if chosen and chosen[0] in options and chosen[0] != stay:
            move(ctx.engine, actor, options[chosen[0]], ctx.intent, 60, list(ctx.engine.state.actors), name='Primordial Syllable: Passage')
    from .. import falling
    falling.settle(ctx.engine, intent=ctx.intent, cause=ctx.source)

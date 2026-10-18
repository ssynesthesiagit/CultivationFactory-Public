"""Paper Cultivator actor profiles, Qi Subpath Compendium R19.

Uses the public summon catalogue and native scheduler. Appearance is descriptive
only: profiles never import the creator's equipment, powers, senses or damage.
"""
from copy import deepcopy
from . import hook, effect

PREFIX = 'tianxia.subpath.qi.paper_cultivator.feature.'
FAMILIAR = PREFIX + 'folded_familiar'
CLONE = PREFIX + 'paper_clone'
DRAGON = PREFIX + 'paper_dragon'


def special(key, name, effects, *, kind='SELF', reach=None, numbers=None, **parameters):
    row = {'id': key, 'name': name, 'effects': effects, 'target_kind': kind,
           'range_ft': reach, 'parameters': {'player_only': False, **parameters}}
    if numbers:
        row['numbers'] = dict(numbers)
    return row


def profile(name, ac, hp, speed, **extra):
    return {'name': name, 'ac': ac, 'hp': hp, 'speed': speed,
            'saves_from_owner': True, 'vulnerable_damage': ['FIRE'],
            'immune_damage': ['POISON', 'PSYCHIC'],
            'immune_conditions': ['charmed', 'frightened', 'poisoned'],
            'attacks': [], **extra}


@hook('summon_catalog')
def profiles(table, info):
    owned = set(info['owned_ids'])
    if not owned.intersection((FAMILIAR, CLONE, DRAGON)):
        return None
    if FAMILIAR in owned:
        for form, speed in (('crane', 30), ('fox', 50), ('turtle', 20), ('hound', 40)):
            key = 'paper_familiar_' + form
            table['sources'][FAMILIAR + '#' + form] = {
                'ability': FAMILIAR, 'family': 'paper_familiar', 'family_name': 'Folded Familiar',
                'creature': key, 'arrives': 'action', 'count': 1, 'command': 'free_once',
                'range_ft': 5, 'command_range_ft': None,
                'actor_policy': {'basic_actions': ['Dash', 'Disengage', 'Dodge', 'Help', 'Hide', 'Search']}}
            # Crane View and Ink Trail have no native observation/fact consumer yet;
            # do not advertise menu actions that only write inert conditions.
            specials = ([special('form', 'Folded Shelter', [{'type': 'paper_familiar_form', 'form': form}],
                         kind='ANY_CREATURE', reach=5)] if form == 'turtle' else
                        [special('form', 'Warning Rustle', [{'type': 'paper_familiar_form', 'form': form}])] if form == 'hound' else [])
            table['creatures'][key] = profile('Paper ' + form.title(), 13, '2*cl', speed,
                size='tiny', specials=specials)
    if CLONE in owned:
        table['sources'][CLONE] = {'creature': 'paper_clone', 'arrives': 'action', 'count': 1,
            'command': 'free_once', 'command_range_ft': None, 'range_ft': 30,
            'duration_rounds': 100, 'choose_visible_space': True,
            'actor_policy': {'basic_actions': [], 'appearance_only': 1}}
        table['creatures']['paper_clone'] = profile('Paper Clone', 14, 1, 30,
            immune_conditions=[], specials=[special('imitate', 'Imitate ordinary gestures and speech',
                [{'type': 'paper_imitate'}])])
    if DRAGON in owned:
        source = table['sources'][DRAGON]
        source.update(choose_visible_space=True, duration_rounds=10, command_range_ft=None,
            actor_policy={'basic_actions': ['Dash', 'Disengage', 'Dodge', 'Help', 'Hide', 'Search']})
        dragon = table['creatures']['paper_dragon']
        dragon['saves_from_owner'] = True
        # Carry only records consent; until the mounted-movement consumer exists,
        # keep it out of the command menu rather than presenting a nonfunctional ride.
        dragon['specials'] = [special('wingbeat', 'Wingbeat', [{'type': 'paper_wingbeat'}],
            kind='CELL', reach=15, numbers={'save_dc': 'dc'}, any_cell=True)]
    for source in table['sources'].values():
        if source.get('ability') == FAMILIAR or source.get('creature') in ('paper_dragon', 'paper_clone'):
            source.setdefault('actor_policy', {}).update(printed_reactions_only=1,
                owning_path='tianxia.path.qi_cultivation')
    return table


@hook('compile_summon')
def seal_profile(bundle, info):
    source = bundle['summon']['source']
    if source not in (FAMILIAR, CLONE, DRAGON):
        return None
    if source == DRAGON:
        bundle['summon']['appearance_traits'] = {'fly_speed_ft': 50}
    if source == FAMILIAR and info['group'].endswith('_crane'):
        bundle['summon']['appearance_traits'] = {'fly_speed_ft': 50, 'flight_hover': True}
    return bundle


@hook('compile_bundle')
def clone_walk(bundle, info):
    clones = [c for c in bundle.get('summons', ()) if c['summon']['source'] == CLONE]
    dragons = [c for c in bundle.get('summons', ()) if c['summon']['source'] == DRAGON]
    if not clones and not dragons:
        return None
    groups = {c['summon']['group'] for c in (*clones, *dragons)}
    for action in bundle['action_catalog']:
        if action.get('parameters', {}).get('summon_group') in groups:
            action['parameters'].pop('inert', None)
    for clone in clones:
        clone['actor_template']['speed_ft'] = bundle['actor_template']['speed_ft']
    if dragons:
        command = next((a for a in bundle['action_catalog']
            if a.get('parameters', {}).get('summon_command') == 'paper_dragon'), None)
        if command is not None:
            recharge = deepcopy(command)
            recharge['source_definition_id'] += '.recharge_wingbeat'
            recharge['display_name'] = 'Command Paper Dragon and recharge Wingbeat (2 Qi)'
            recharge['costs'] = [['resource:core.qi', 2]]
            recharge['parameters']['typed']['effects'].insert(0, {'type': 'paper_recharge_wingbeat'})
            recharge['parameters']['paper_recharge'] = True
            bundle['action_catalog'].append(recharge)
            bundle['actor_template']['action_ids'].append(recharge['source_definition_id'])
    return bundle


@effect('paper_recharge_wingbeat')
def recharge_wingbeat(ctx, row):
    from ..summons import owned_by
    for dragon in owned_by(ctx.engine, ctx.actor.entity_id, 'paper_dragon'):
        if dragon.active:
            dragon.summon['wingbeat_used'] = 0


@hook('candidate_allowed')
def wingbeat_available(engine, actor, candidate, action):
    if action is None:
        return None
    if (actor.summon or {}).get('source') == DRAGON and action.display_name == 'Wingbeat':
        return False if actor.summon.get('wingbeat_used') else None
    if action.parameters.get('paper_recharge'):
        from ..summons import commandable
        return None if any(a.summon.get('wingbeat_used') for a in commandable(engine, actor, 'paper_dragon')) else False
    return None


@hook('summon_appeared')
def paper_senses(engine, owner, creature, source):
    if (creature.summon or {}).get('source') != DRAGON:
        return
    creature.summon['wingbeat_used'] = 0
    engine._apply_condition(creature, 'condition:typed.sense', DRAGON, owner.entity_id,
        expires_on=creature.summon.get('expires_on') or 'UNTIL_REMOVED',
        data={'sense': 'darkvision', 'range_ft': 60, 'label': 'Darkvision 60 feet'})
    engine._apply_condition(creature, 'condition:typed.sense', DRAGON + ':qi', owner.entity_id,
        expires_on=creature.summon.get('expires_on') or 'UNTIL_REMOVED',
        data={'sense': 'qi_sensing', 'range_ft': 30, 'label': 'Qi Sensing 30 feet'})


@effect('paper_imitate')
def imitate(ctx, row):
    if (ctx.actor.summon or {}).get('source') != CLONE:
        return
    ctx.rider('The Paper Clone imitates its creator’s ordinary gestures and movement. Its paper form is apparent on physical inspection; it gains no equipment properties, powers or senses.')


@effect('paper_wingbeat')
def wingbeat(ctx, row):
    from dataclasses import replace
    from ..typed_executor import run_effects
    from ..gate2_runtime_models import Position
    from .. import senses
    if (ctx.actor.summon or {}).get('source') != DRAGON:
        return
    owner = ctx.engine.state.actors[ctx.actor.summon['owner']]
    if ctx.actor.summon.get('wingbeat_used'):
        return
    from .needle import ask, checkpoint_id
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'wingbeat', ctx.actor.entity_id),
        owner, 'choice:needle.paper_wingbeat_damage', ['BLUDGEONING', 'FORCE'],
        labels={'BLUDGEONING': 'Bludgeoning', 'FORCE': 'Force'}, preferred=['FORCE'],
        name='Paper Dragon — Wingbeat', prompt='Wingbeat: choose damage for this 15-foot cone. Creatures make a Strength save; a failure deals 2d8 damage, pushes 15 feet and knocks Prone. A success deals half and pushes 5 feet.')
    ctx.actor.summon['wingbeat_used'] = 1
    destination = getattr(ctx.intent, 'destination', None)
    if destination is None:
        return
    # Native grid cone, not a radius approximation; includes friendly creatures.
    from .. import zones
    direction = Position(x=destination.x, y=destination.y, z=destination.z)
    dx, dy = direction.x-ctx.actor.position.x, direction.y-ctx.actor.position.y
    for target in ctx.engine.state.actors.values():
        if not target.active or target.entity_id == ctx.actor.entity_id:
            continue
        tx, ty = target.position.x-ctx.actor.position.x, target.position.y-ctx.actor.position.y
        dot, cross = dx*tx+dy*ty, abs(dx*ty-dy*tx)
        if dot <= 0 or cross > dot or ctx.engine.grid.distance_ft(ctx.actor.position, target.position) > 15:
            continue
        if not ctx.engine.grid.line_of_physical_transmission(ctx.actor.position, target.position):
            continue
        damage = {'type': 'damage', 'dice': {'count': 2, 'sides': 8}, 'damage_type': picked[0]}
        run_effects(replace(ctx, target=target, targets=[target]), [{'type': 'save', 'ability': 'STR',
            'on_fail': [damage, {'type': 'forced_movement', 'direction': 'away', 'distance_ft': 15},
                {'type': 'condition', 'condition': 'prone', 'applies_to': 'target'}],
            'on_success': [{'type': 'half_damage'}, {'type': 'forced_movement', 'direction': 'away', 'distance_ft': 5}]}])


@effect('paper_carry')
def carry(ctx, row):
    # Passenger admission and actual movement use the shared carry contract.
    from ..fact_consent_admission import admit_choice
    from .effect_durations import token
    if (ctx.actor.summon or {}).get('source') != DRAGON or ctx.target is None:
        return
    if ctx.target.size_category not in ('Tiny', 'Small', 'Medium', 'Large'):
        return
    accepted = admit_choice(ctx, ctx.target, DRAGON, 'passenger', ctx.actor.entity_id, ['accept'],
        labels={'accept': 'Ride the Paper Dragon'}, prompt=f'{ctx.target.display_name}: ride {ctx.actor.display_name}? Mounting uses your normal movement; you spend no Qi.',
        expires_on=token('start', ctx.target.entity_id, int(ctx.target.turns_started)+1),
        readers=[ctx.actor.summon['owner']], automatic_options=['accept'] if ctx.target.team_id == ctx.actor.team_id else [])
    if accepted:
        ctx.engine._apply_condition(ctx.target, 'condition:typed.paper_passenger', DRAGON, ctx.actor.entity_id,
            expires_on='UNTIL_REMOVED', data={'carrier': ctx.actor.entity_id, 'label': 'Carried by Paper Dragon'})


@effect('paper_familiar_form')
def familiar_form(ctx, row):
    from .effect_durations import token
    if (ctx.actor.summon or {}).get('source') != FAMILIAR:
        return
    owner = ctx.engine.state.actors[ctx.actor.summon['owner']]
    form = row['form']
    if form == 'crane':
        ctx.engine._apply_condition(owner, 'condition:typed.paper_crane_view', FAMILIAR, ctx.actor.entity_id,
            expires_on=token('start', owner.entity_id, int(owner.turns_started)+1),
            data={'perception_actor': ctx.actor.entity_id, 'label': 'Seeing and hearing through Paper Crane'})
    elif form == 'turtle' and ctx.target is not None:
        from ..fact_consent_admission import admit_choice
        deadline = token('start', owner.entity_id, int(owner.turns_started)+1)
        if admit_choice(ctx, ctx.target, FAMILIAR, 'shelter', ctx.actor.entity_id, ['accept'],
            labels={'accept': 'Accept Folded Shelter'}, prompt=f'Folded Shelter: {ctx.target.display_name} gains +2 AC against one ranged attack until {owner.display_name} next starts a turn. Accept at no cost?',
            expires_on=deadline, automatic_options=['accept'] if ctx.target.team_id == ctx.actor.team_id else []):
            for mid, modifier in tuple(ctx.target.modifiers.items()):
                if modifier.source_definition_id == FAMILIAR and modifier.target_field == 'armor_class_vs_ranged':
                    ctx.engine._remove_modifier_instance(ctx.target, mid, FAMILIAR, expected=modifier)
            ctx.engine._add_modifier(ctx.target, FAMILIAR, 'armor_class_vs_ranged', 'ADD', 2,
                'ALWAYS', expires_on=deadline)
    elif form == 'fox' and ctx.target is not None:
        ctx.engine._apply_condition(ctx.actor, 'condition:typed.ink_trail', FAMILIAR, owner.entity_id,
            expires_on=token('start', owner.entity_id, int(owner.turns_started)+1),
            data={'target': ctx.target.entity_id, 'label': 'Following an Ink Trail within 300 feet'})


@hook('attack_completed')
def consume_folded_shelter(engine, notice, intent):
    if notice.melee:
        return
    target = engine.state.actors.get(notice.target_id)
    if target is None:
        return
    for mid, modifier in tuple(target.modifiers.items()):
        if modifier.target_field == 'armor_class_vs_ranged' and modifier.source_definition_id.startswith(FAMILIAR):
            engine._remove_modifier_instance(target, mid, modifier.source_definition_id, expected=modifier)

"""Paper Cultivator actor profiles, Qi Subpath Compendium R19.

Uses the public summon catalogue and native scheduler. Appearance is descriptive
only: profiles never import the creator's equipment, powers, senses or damage.
"""
from copy import deepcopy
import json
from . import hook, effect

PREFIX = 'tianxia.subpath.qi.paper_cultivator.feature.'
FAMILIAR = PREFIX + 'folded_familiar'
CLONE = PREFIX + 'paper_clone'
DRAGON = PREFIX + 'paper_dragon'
# "Size: Tiny or Small, chosen during creation" (Folded Familiar).
FAMILIAR_SIZES = ('tiny', 'small')
# Warning Rustle's printed trigger and its two printed outcomes.
RUSTLE_DISTANCE_FT = 10
RUSTLE_FT = 5


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
            # Each printed form ability is published with its own consumer below.
            # Crane View needs no target; Ink Trail and Folded Shelter choose a
            # creature. Warning Rustle is a printed Reaction, not an Action, and
            # is dispatched by the engine rather than the command menu.
            specials = {
                'crane': [special('form', 'Crane View', [{'type': 'paper_familiar_form', 'form': 'crane'}])],
                'fox': [special('form', 'Ink Trail', [{'type': 'paper_familiar_form', 'form': 'fox'}],
                         kind='ANY_CREATURE', reach=30)],
                'turtle': [special('form', 'Folded Shelter', [{'type': 'paper_familiar_form', 'form': 'turtle'}],
                         kind='ANY_CREATURE', reach=5)],
                'hound': []}[form]
            # "Size: Tiny or Small, chosen during creation": the choice is asked at
            # creation (choose_familiar_size) and read by combat/summons.py, which
            # builds the actor's real size and occupied-square footprint from it.
            table['creatures'][key] = profile('Paper ' + form.title(), 13, '2*cl', speed,
                size='tiny', specials=specials,
                **({'innate_reaction': {
                    'name': 'Warning Rustle', 'kind': 'enters_range',
                    'range_ft': RUSTLE_DISTANCE_FT, 'free': True,
                    'subject_relation': 'hostile',
                    'effects': [{'type': 'paper_warning_rustle'}]}}
                   if form == 'hound' else {}))
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
        # Carry is a published command with a real consumer (paper_carry below):
        # it admits a passenger through the shared consent contract and grants the
        # carrier's movement the passenger spends.
        dragon['specials'] = [special('wingbeat', 'Wingbeat', [{'type': 'paper_wingbeat'}],
            kind='CELL', reach=15, numbers={'save_dc': 'dc'}, any_cell=True),
            special('carry', 'Carry a willing creature', [{'type': 'paper_carry'}],
            kind='ANY_CREATURE', reach=5)]
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


@hook('summon_appeared')
def choose_familiar_size(engine, owner, creature, source):
    """"Size: Tiny or Small, chosen during creation."

    Asked once per actual creation from the shared transactional choice transport,
    and stored as a plain string on the summon record, so combat/summons.py can
    build the real actor size and occupied-square footprint and both survive a
    table commit and a cold reload.
    """
    record = creature.summon or {}
    if record.get('source') != FAMILIAR:
        return
    from .needle import ask, checkpoint_id
    from .effect_durations import token
    picked = ask(engine, None, checkpoint_id(engine, 'folded_familiar_size', creature.entity_id),
        owner, 'choice:needle.paper_familiar_size', list(FAMILIAR_SIZES),
        labels={'tiny': 'Tiny', 'small': 'Small'}, preferred=['tiny'],
        name='Folded Familiar — size', target_id=creature.entity_id,
        prompt=f'Folded Familiar: {owner.display_name} folds a familiar of the size you choose now. '
               'Tiny fits almost anywhere; Small is a larger body with the same statistics. '
               'The familiar acts immediately after your turn and Dodges unless you command it. '
               'This choice adds no cost.')
    if len(picked) != 1 or picked[0] not in FAMILIAR_SIZES:
        raise ValueError('Folded Familiar requires one creation size')
    creature.summon['familiar_size'] = picked[0]
    creature.size_category = picked[0].title()
    creature.summon['size'] = picked[0]
    from ..footprint_registry import resolve_actor_footprint
    engine.actor_footprints[creature.entity_id], _ = resolve_actor_footprint(
        creature.entity_id, summon_record=creature.summon)
    engine._append_event('PASSIVE_TRIGGERED', FAMILIAR, actor_id=owner.entity_id,
        target_ids=(creature.entity_id,),
        payload={'text': f'{creature.display_name} is {picked[0]} and lasts until it is destroyed, dismissed or replaced.',
                 'familiar_size': picked[0]})


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


@effect('paper_warning_rustle')
def warning_rustle(ctx, row):
    """Warning Rustle (Paper Hound): choose the adjacent ally it warns, and that
    ally's outcome. Dispatched as the Hound's own printed Reaction by the engine."""
    record = ctx.actor.summon or {}
    if record.get('source') != FAMILIAR or str(record.get('group') or '').rsplit('_', 1)[-1] != 'hound':
        return
    owner = ctx.engine.state.actors.get(record.get('owner') or '')
    if owner is None:
        return
    from .needle import ask, checkpoint_id
    from ..activation_settlement import path_numbers
    allies = sorted(
        (other for other in ctx.engine.state.actors.values()
         if other.active and other.entity_id != ctx.actor.entity_id
         and other.team_id == ctx.actor.team_id
         and ctx.engine._distance_actor_to_actor(ctx.actor, other) <= RUSTLE_FT),
        key=lambda other: (other.entity_id != owner.entity_id, other.entity_id))
    if not allies:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'warning_rustle_ally', ctx.actor.entity_id),
        owner, 'choice:needle.paper_warning_rustle_ally', [other.entity_id for other in allies],
        labels={other.entity_id: other.display_name for other in allies},
        name='Paper Hound — Warning Rustle', target_id=ctx.actor.entity_id,
        prompt=f'Warning Rustle: a hostile creature the Paper Hound can perceive came within '
               f'{RUSTLE_FT} feet of it. Choose the one adjacent ally it warns. That ally then moves '
               f'{RUSTLE_FT} feet without provoking Opportunity Attacks, or gains Temporary Hit Points '
               'equal to your Proficiency Bonus. The Hound can warn once per round.')
    if not picked:
        return
    ally = ctx.engine.state.actors.get(picked[0])
    if ally is None or not ally.active:
        return
    numbers = path_numbers({'owner_sheet': {}, 'numbers': {}, 'pb': int(owner.proficiency_bonus or 0)},
                           'tianxia.path.qi_cultivation')
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'warning_rustle_choice', ctx.actor.entity_id),
        ally, 'choice:needle.paper_warning_rustle_effect', ['move', 'temporary_hp'],
        labels={'move': f'Move {RUSTLE_FT} feet without provoking Opportunity Attacks',
                'temporary_hp': 'Gain Temporary Hit Points equal to your Proficiency Bonus'},
        name='Warning Rustle — ally choice', target_id=ally.entity_id,
        prompt=f'{ally.display_name}: the Paper Hound rustles a warning. Move {RUSTLE_FT} feet without '
               'provoking Opportunity Attacks, or gain Temporary Hit Points equal to your Proficiency '
               'Bonus. Either outcome ends the warning.')
    from dataclasses import replace
    from ..typed_executor import run_effects
    if chosen and chosen[0] == 'temporary_hp':
        run_effects(replace(ctx, actor=ally, target=ally, targets=[ally]),
                    [{'type': 'temp_hp', 'applies_to': 'target', 'flat': int(numbers.get('pb') or 0)}])
    else:
        _rustle_move(ctx.engine, ally)


def _rustle_move(engine, ally):
    """Grant the warned ally 5 feet of movement that provokes no Opportunity Attack.

    Uses the ordinary granted-movement receipt and the native OA exemption scope,
    so the movement still costs the ally's own pool and follows every ordinary rule.
    """
    from ..granted_movement import move as granted_move
    from ..gate2_runtime_models import Position
    options = []
    for y in range(engine.grid.height):
        for x in range(engine.grid.width):
            for z in range(engine.grid.depth if hasattr(engine.grid, 'depth') else 1):
                cell = Position(x=x, y=y, z=z)
                if engine.grid.distance_ft(ally.position, cell) > RUSTLE_FT:
                    continue
                if not engine.grid.placement_legal(cell, footprint=engine._footprint(ally),
                                                   occupied_cells=engine._occupied_cells_except(ally.entity_id)):
                    continue
                options.append(cell)
    if not options:
        return
    options.sort(key=lambda cell: engine.grid.distance_ft(ally.position, cell))
    destination = options[-1]
    start = ally.position
    ally.position = destination
    engine._append_event('MOVEMENT_COMMITTED', FAMILIAR, actor_id=ally.entity_id,
        payload={'destination': destination.model_dump(mode='json'),
                 'path': [start.model_dump(mode='json'), destination.model_dump(mode='json')],
                 'cost_ft': 0, 'teleport': False, 'forced': True,
                 'no_opportunity_attacks': True})
    from .. import zones
    zones.on_moved(engine, ally, start, destination, forced=True)


@hook('compile_bundle')
def clone_exchange_reaction(bundle, info):
    """Paper Exchange (Paper Clone): the owner's printed Reaction, offered when an
    attack roll targets the owner while the Clone is within 30 feet.

    Cost 1 Qi, swap positions before the roll resolves so the attack targets the
    Clone, and the Clone is destroyed after the attack resolves either way.
    """
    if not any(c['summon']['source'] == CLONE for c in bundle.get('summons', ())):
        return None
    bundle['typed_reactions'] = [r for r in bundle['typed_reactions']
                                 if r.get('feature_id') != CLONE + '.paper_exchange']
    bundle['typed_reactions'].append({'block': 'generic', 'feature_id': CLONE + '.paper_exchange',
        'name': 'Paper Exchange', 'kind': 'attacked', 'subject_relation': 'self',
        'costs': [{'resource_id': 'resource:core.qi', 'amount': 1}],
        'ask': bool(bundle.get('reaction_plan', {}).get('ask')),
        'effects': [{'type': 'paper_exchange'}]})
    return bundle


@hook('candidate_allowed')
def exchange_available(engine, actor, candidate, action):
    if action is None or 'paper_exchange' not in json.dumps(action.parameters or {}):
        return None
    from ..summons import owned_by
    return None if any(c.active for c in owned_by(engine, actor.entity_id, 'paper_clone')) else False


@effect('paper_exchange')
def paper_exchange(ctx, row):
    """Swap the owner with the Clone before the roll resolves, then destroy it."""
    from ..summons import owned_by, dismiss
    clone = next((c for c in owned_by(ctx.engine, ctx.actor.entity_id, 'paper_clone') if c.active), None)
    if clone is None:
        return
    engine = ctx.engine
    if engine._distance_actor_to_actor(ctx.actor, clone) > 30:
        return
    owner_cell, clone_cell = ctx.actor.position, clone.position
    occupied = engine._occupied_cells_except(ctx.actor.entity_id)
    occupied.difference_update(engine.grid.footprint_cells(
        clone_cell, footprint=engine._footprint(clone)))
    occupied.difference_update(engine.grid.footprint_cells(
        owner_cell, footprint=engine._footprint(ctx.actor)))
    if not engine.grid.placement_legal(clone_cell, footprint=engine._footprint(ctx.actor),
                                       occupied_cells=occupied):
        return
    if not engine.grid.placement_legal(owner_cell, footprint=engine._footprint(clone),
                                       occupied_cells=occupied):
        return
    ctx.actor.position, clone.position = clone_cell, owner_cell
    engine._append_event('MOVEMENT_COMMITTED', CLONE, actor_id=ctx.actor.entity_id,
        target_ids=(clone.entity_id,),
        payload={'destination': clone_cell.model_dump(mode='json'),
                 'path': [owner_cell.model_dump(mode='json'), clone_cell.model_dump(mode='json')],
                 'cost_ft': 0, 'teleport': True, 'forced': True,
                 'text': 'Paper Exchange: the owner and the Paper Clone trade places.'})
    from .. import zones
    zones.on_moved(engine, ctx.actor, owner_cell, clone_cell, forced=True)
    pending = getattr(engine, '_typed_pending_attack', None)
    if pending is None or pending.get('target') != ctx.actor.entity_id:
        return
    pending['paper_exchange_redirect'] = clone.entity_id
    clone.summon['paper_exchange_pending'] = 1


@hook('attack_target_redirect')
def redirect_paper_exchange(engine, attacker, target, intent):
    pending = getattr(engine, '_typed_pending_attack', None) or {}
    clone_id = pending.get('paper_exchange_redirect')
    if not clone_id or pending.get('target') != target.entity_id:
        return None
    clone = engine.state.actors.get(clone_id)
    return clone if clone is not None and clone.active else None


@hook('attack_resolved')
def finish_paper_exchange(ctx, target, hit, effect):
    from ..summons import dismiss
    record = target.summon or {}
    if record.get('source') == CLONE and record.get('paper_exchange_pending'):
        record.pop('paper_exchange_pending', None)
        dismiss(ctx.engine, target, 'Paper Exchange destroys the Clone after the attack resolves.')


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

"""Mercurial Cultivator's single owned native provider.

Source: Qi Subpath Compendium R19, Mercurial Cultivator; Shared Qi Rules R4.
Ownership is sealed by compilation; a matching display name grants nothing.
Activation-local choices share Context.damage_cache across recipients/strikes.
Conditions and native resource/economy events survive table replay and reload.
"""
from . import hook, effect
from .passive_rows import row_of
from contextvars import ContextVar
from contextlib import contextmanager

_REPOSITION = ContextVar('mercurial_reposition', default=None)
_ESCAPE_SAVE = ContextVar('mercurial_escape_save', default=None)

PREFIX = 'tianxia.subpath.qi.mercurial_cultivator.feature.'
VARIANT_PREFIX = 'tianxia.subpath.qi.living_quicksilver_immortal_embryo.feature.'
BLOCK = 'mercurial_cultivator'
QI = 'resource:core.qi'
TYPES = ('ACID', 'COLD', 'FIRE', 'LIGHTNING', 'POISON', 'THUNDER')
PHYSICAL = ('BLUDGEONING', 'PIERCING', 'SLASHING')
LEVELS = {'mercurial_qi': 3, 'liquid_form': 6, 'mercurial_adaptation': 10,
          'quicksilver_step': 14, 'prima_materia': 18}
STATE = 'condition:typed.mercurial.'
TELLS = ('Color shift', 'Metallic sheen', 'Steam', 'Frost', 'Electric arcs',
         'Acidic distortion', 'Poisonous iridescence', 'Thunderous ripples')
FORMS = ('Adamant', 'Flowing', 'Vapor', 'Reflective', 'Restorative', 'Conductive', 'Corrosive')


def owns(engine, actor, name):
    return row_of(engine, actor.entity_id, BLOCK, name)


def proficiency(engine, actor):
    row = next((r for r in engine.typed_passive_rows.get(actor.entity_id, ()) if r.get('block') == BLOCK), None)
    return int(row['numbers']['pb']) if row else int(actor.proficiency_bonus)


def held(actor, name):
    return next((c for c in actor.conditions.values() if c.condition_id == STATE + name), None)


def active(engine, actor, name):
    return bool(owns(engine, actor, name) and held(actor, name))


def stamp(engine):
    from ..turn_uses import current_turn_key
    return current_turn_key(engine)


def put(engine, actor, name, source, data, expiry='UNTIL_REMOVED'):
    engine._remove_condition(actor, STATE + name, PREFIX + source)
    engine._apply_condition(actor, STATE + name, PREFIX + source, actor.entity_id,
                            expires_on=expiry, data=data)


def choose(engine, actor, key, name, options, *, optional=False, labels=None, subject=None, prompt=None, automatic_options=None):
    from .rider_choices import pick
    return pick(engine, actor, 'mercurial.' + key, name, list(options), subject=subject or actor,
                optional=optional, labels=labels, preferred=list(options)[:1], prompt=prompt,
                automatic_options=automatic_options)


@hook('compile_passives')
def compile_owned(passives, info):
    ids = set(info['owned_ids'])
    if not any(PREFIX + name in ids for name in LEVELS):
        return passives
    from ..activation_settlement import path_numbers
    numbers = path_numbers(info, 'tianxia.path.qi_cultivation')
    # A replacement lineage never receives a second parent progression.
    if any(fid.startswith(VARIANT_PREFIX) for fid in ids):
        return passives
    cl = int(numbers.get('cl') or 0)
    return [*passives, *({'feature_id': PREFIX + name, 'block': BLOCK, 'kind': name,
                         'numbers': numbers, 'choice_owner': True}
                        for name, minimum in LEVELS.items() if PREFIX + name in ids and cl >= minimum)]


@hook('compile_actions')
def actions(info):
    ids = set(info['owned_ids'])
    if not any(PREFIX + name in ids for name in LEVELS):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..activation_settlement import path_numbers
    info = {**info, 'numbers': path_numbers(info, 'tianxia.path.qi_cultivation')}
    if any(fid.startswith(VARIANT_PREFIX) for fid in ids):
        return None
    out = []
    for name, cost, label, description in (
        ('liquid_form', 2, 'Liquid Form', 'Spend 2 Qi and a Bonus Action: become liquid metal until your next turn starts. Resist weapon Bludgeoning, Piercing and Slashing damage; pass through creatures and repeat one escape attempt with Advantage.'),
        ('quicksilver_step', 4, 'Quicksilver Step', 'Spend 4 Qi and a Bonus Action: teleport to a visible unoccupied space within 60 feet, then choose a Flowing Arrival benefit. Once per turn.'),
        ('prima_materia', 8, 'Prima Materia', 'Spend 8 Qi and a Bonus Action: for 1 minute resist six Mercurial damage types and physical damage, improve your Mercurial techniques, and choose a Form each turn. Once per scene.')):
        if PREFIX + name not in ids or int(info['numbers'].get('cl') or 1) < LEVELS[name]:
            continue
        effects = [{'type': 'mercurial_activate', 'name': name}]
        if name == 'quicksilver_step':
            effects = [{'type': 'mercurial_step_begin'},
                       {'type': 'teleport', 'applies_to': 'self', 'distance_ft': 60},
                       {'type': 'mercurial_arrival'}]
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.mercurial.{name}",
            display_name=label, owner_id=info['actor_id'], economy=EconomyKind.BONUS_ACTION,
            resolution_kind='TYPED', target_kind='SELF', range_ft=60 if name == 'quicksilver_step' else None,
            costs=((QI, cost),), parameters={'typed': {'source': PREFIX + name,
            'numbers': dict(info['numbers']), 'duration': {'kind': 'instant'},
            'riders': list((info['mechanics'].get(PREFIX + name) or {}).get('riders') or []),
            **({'manual_inline_choice': True} if name == 'quicksilver_step' else {}),
            'effects': effects}, 'description': description, 'expected_damage': 0}))
        if name == 'quicksilver_step':
            out.append(out[-1].model_copy(update={
                'source_definition_id': f"action:typed.{info['short']}.mercurial.exchange",
                'display_name': 'Quicksilver Step: Exchange with Domain Armament',
                'parameters': {'typed': {'source': PREFIX + name, 'numbers': dict(info['numbers']),
                    'duration': {'kind': 'instant'},
                    'manual_inline_choice': True,
                    'riders': list((info['mechanics'].get(PREFIX + name) or {}).get('riders') or []), 'effects': [
                        {'type': 'mercurial_step_begin'}, {'type': 'mercurial_exchange'}, {'type': 'mercurial_arrival'}]},
                    'description': 'Bonus Action and 4 Qi, once per turn: exchange positions with your floating Mercurial Domain Armament within 60 feet. Both subjects must fit. The same item moves to your former space; then choose Flowing Arrival.',
                    'expected_damage': 0}}))
    if PREFIX + 'prima_materia' in ids and int(info['numbers'].get('cl') or 1) >= 18:
        for shape in ('Weapon', 'Shield', 'Mirror', 'Orb', 'Chain', 'Tool', 'Cultivation implement'):
            out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.mercurial.sheath.{shape.lower().replace(' ', '_')}",
                display_name='Mutable Domain Armament: ' + shape, owner_id=info['actor_id'], economy=EconomyKind.NONE,
                resolution_kind='TYPED', target_kind='SELF', parameters={'typed': {'source': PREFIX + 'prima_materia',
                'numbers': dict(info['numbers']), 'duration': {'kind': 'instant'}, 'riders': [],
                'effects': [{'type': 'mercurial_sheath', 'shape': shape}]},
                'description': 'While Prima Materia lasts, change your Domain Armament’s projected appearance once during your turn without an action or Qi. A real item keeps its identity and properties; this grants no incompatible item properties.',
                'expected_damage': 0}))
    return out


@hook('compile_action')
def single_owned_provider(action, info):
    """The family's native commands replace its former rider-only buttons.

    Keep reviewed manual clauses on the real native commands, rather than
    publishing a second cost-paying button which performs only narration.
    """
    typed = (action.parameters or {}).get('typed') or {}
    source = typed.get('option_of') or typed.get('source')
    if (source not in {PREFIX + name for name in LEVELS} or source not in info['owned_ids']
            or '.mercurial.' in action.source_definition_id):
        return None
    if typed.get('effects'):
        return None
    from copy import deepcopy
    parameters = deepcopy(action.parameters)
    parameters['typed']['riders'] = []
    return action.model_copy(update={'parameters': parameters})


@hook('candidate_allowed')
def allowed(engine, actor, candidate, action):
    passage_frame = _REPOSITION.get()
    if passage_frame and passage_frame[0] is engine and passage_frame[1] == actor.entity_id and not active(engine, actor, 'liquid_form'):
        from ..target_knowledge import actors_for
        cells = {(p.x, p.y) for p in candidate.canonical_path or ()}
        crossed = {a.entity_id for a in actors_for(engine, actor) if a.active and a.entity_id != actor.entity_id
                   and cells.intersection(engine._actor_cells(a))}
        if len(crossed) > 1:
            return False
    if action is None:
        return None
    source = ((action.parameters or {}).get('typed') or {}).get('source', '')
    if source not in {PREFIX + name for name in LEVELS}:
        return None
    name = source.removeprefix(PREFIX)
    if not owns(engine, actor, name):
        return False
    if any(e.get('type') == 'mercurial_sheath' for e in action.parameters['typed'].get('effects', ())):
        from .qi_path import armament_condition
        return bool(active(engine, actor, 'prima_materia') and armament_condition(actor)
                    and engine.state.current_actor_id == actor.entity_id
                    and actor.turn_flags.get('_round_mercurial_sheath') != stamp(engine))
    if name == 'prima_materia' and held(actor, 'prima_used'):
        return False
    if name == 'quicksilver_step' and actor.turn_flags.get('_round_mercurial_step') == stamp(engine):
        return False
    if name == 'quicksilver_step':
        from ..typed_executor import condition_rules
        if any(r.get('no_teleport') for r in condition_rules(actor)):
            return False
        if any(e.get('type') == 'mercurial_exchange' for e in action.parameters['typed'].get('effects', ())):
            from .qi_path import armament_condition, armament_point
            from .teleport_steps import destination_allowed
            from ..gate2_runtime_models import Position
            if not armament_condition(actor):
                return False
            x, y = armament_point(actor)
            point = Position(x=x, y=y)
            start = actor.position
            return bool(destination_allowed(engine, actor, point, 60)
                        and engine.grid.placement_legal(point, footprint=engine._footprint(actor),
                            occupied_cells=engine._occupied_cells_except(actor.entity_id))
                        and engine.grid.placement_legal(start,
                            occupied_cells=engine._occupied_cells_except(actor.entity_id))
                        and engine._line_of_sight_actor_to_cell(actor, start))
    return None


@hook('technique_cost_discount')
def discounts(engine, actor, source, totals):
    if not active(engine, actor, 'prima_materia'):
        return None
    action = engine.action_catalog.get(source)
    typed = ((action.parameters or {}).get('typed') or {}) if action else {}
    name = str(typed.get('source', source)).removeprefix(PREFIX)
    if name == 'quicksilver_step' and owns(engine, actor, name):
        return {QI: min(2, totals.get(QI, 0))}
    if (name == 'liquid_form' and owns(engine, actor, name)
            and actor.turn_flags.get('_round_mercurial_liquid_free') != engine.state.round_number):
        return {QI: min(2, totals.get(QI, 0))}
    return None


@effect('mercurial_activate')
def activate(ctx, effect):
    name = effect['name']
    if not owns(ctx.engine, ctx.actor, name):
        raise ValueError('This creature does not own that Mercurial feature.')
    if name == 'prima_materia':
        expiry = f'START_OF_SLOT_AT:{ctx.engine.state.round_number + 10}:{ctx.engine.state.current_slot_index}'
    else:
        expiry = 'START_OF_SOURCE_NEXT_TURN'
        if active(ctx.engine, ctx.actor, 'prima_materia'):
            ctx.actor.turn_flags['_round_mercurial_liquid_free'] = ctx.engine.state.round_number
    label = ('Liquid Form: resist weapon Bludgeoning, Piercing and Slashing; move through creatures; escape with Advantage until your next turn starts'
             if name == 'liquid_form' else 'Prima Materia: resist Mercurial and physical damage and choose a Form each turn for 1 minute')
    put(ctx.engine, ctx.actor, name, name, {'label': label}, expiry)
    if name == 'liquid_form':
        repeat_escape(ctx)
    elif name == 'prima_materia':
        for c in list(ctx.actor.conditions.values()):
            source = ctx.engine.action_catalog.get(c.source_definition_id)
            if (c.condition_id in ('condition:typed.grappled', 'condition:typed.restrained')
                    and ordinary_lower_hold(ctx.engine, ctx.actor, source,
                        ctx.engine.state.actors.get(c.source_actor_id))):
                ctx.actor.conditions.pop(c.instance_id, None)
                ctx.engine._append_event('CONDITION_REMOVED', ctx.source, actor_id=ctx.actor.entity_id,
                    target_ids=(ctx.actor.entity_id,), payload={'condition_id': c.condition_id,
                    'instance_id': c.instance_id, 'reason': 'PRIMA_MATERIA'})


def ordinary_lower_hold(engine, subject, action, source_actor):
    if action is None or source_actor is None or not active(engine, subject, 'prima_materia'):
        return False
    typed = (action.parameters or {}).get('typed') or {}
    # The native ordinary Unarmed Strike declares its Grapple procedure. A
    # magical condition or a physical-looking cultivation grip is not inferred
    # to be ordinary from its name or the word Grappled.
    if typed.get('unarmed_option') != 'grapple':
        return False
    from ..activation_settlement import profile
    source_cl = profile(engine, source_actor, action)['source_cl']
    owner_cl = int(owns(engine, subject, 'prima_materia')['numbers'].get('cl') or 0)
    return 0 < source_cl < owner_cl


@hook('condition_attempt')
def perfected_hold_immunity(ctx, subject, effect):
    if effect.get('condition') in ('grappled', 'restrained') and ordinary_lower_hold(ctx.engine, subject, ctx.action, ctx.actor):
        return False
    return None


@hook('technique_accepted')
def activation_limits(engine, actor, action):
    source = ((action.parameters or {}).get('typed') or {}).get('source')
    if source == PREFIX + 'prima_materia' and owns(engine, actor, 'prima_materia'):
        if any(e.get('type') == 'mercurial_activate' for e in action.parameters['typed'].get('effects', ())):
            put(engine, actor, 'prima_used', 'prima_materia', {'label': 'Prima Materia used this scene'})
    if (source == PREFIX + 'liquid_form' and owns(engine, actor, 'liquid_form')
            and active(engine, actor, 'prima_materia')
            and actor.turn_flags.get('_round_mercurial_liquid_free') != engine.state.round_number):
        actor.turn_flags['_round_mercurial_liquid_free'] = engine.state.round_number


@hook('activation_end')
def step_limit(engine, actor, action, candidate, intent):
    if (((action.parameters or {}).get('typed') or {}).get('source') == PREFIX + 'quicksilver_step'
            and owns(engine, actor, 'quicksilver_step')):
        actor.turn_flags['_round_mercurial_step'] = stamp(engine)


def repeat_escape(ctx):
    from .repeat_saves import save_of
    conditions = {c.instance_id: c for c in ctx.actor.conditions.values()
                  if c.condition_id in ('grappled', 'restrained', 'condition:typed.grappled', 'condition:typed.restrained',
                                        'condition:core.grappled', 'condition:core.restrained')
                  and (save_of(c) is not None or type(c.data.get('escape_dc')) is int)}
    selected = choose(ctx.engine, ctx.actor, 'escape', 'Liquid Form', list(conditions), optional=True,
        labels={iid: 'Repeat the escape save or check against ' + c.condition_id.rsplit('.', 1)[-1].title()
                for iid, c in conditions.items()},
        prompt=f'Liquid Form: {ctx.actor.display_name} may immediately repeat one saving throw to escape Grappled or Restrained with Advantage.') if conditions else []
    if selected:
        c = conditions[selected[0]]
        save = save_of(c)
        if save is None and isinstance(c.data.get('escape_save'), str) and type(c.data.get('escape_dc')) is int:
            save = {'ability': c.data['escape_save'], 'dc': c.data['escape_dc']}
        if save is not None:
            from .adaptations import ending_save_scope
            with ending_save_scope(ctx.engine, ctx.actor, c):
                roll = ctx.engine._roll_save(ctx.actor, str(save['ability']).upper(), int(save['dc']), ctx.source,
                    extra_mode='ADVANTAGE', roll_context={'source_actor_id': c.source_actor_id,
                    'named': [c.condition_id.rsplit('.', 1)[-1]]})
            success = roll is not None and roll.total >= int(save['dc'])
        else:
            from .escape_checks import resolve_escape_check
            from .ability_source import escape_bonus
            success = resolve_escape_check(ctx, {'bonus': escape_bonus(ctx.engine, ctx.actor)},
                int(c.data['escape_dc']), [c], ('grappled', 'restrained'))
        if success:
            ctx.actor.conditions.pop(c.instance_id, None)
            ctx.engine._append_event('CONDITION_REMOVED', ctx.source, actor_id=ctx.actor.entity_id,
                target_ids=(ctx.actor.entity_id,), payload={'condition_id': c.condition_id,
                'instance_id': c.instance_id, 'reason': 'ESCAPED'})
            from .hold_escapes import escaped, how_for
            escaped(ctx.engine, ctx.actor, [c], how_for(save['ability'] if save else 'STR', ctx.actor),
                by=ctx.actor, source=ctx.source, way='repeat_save' if save else 'check')


@hook('damage_defenses')
def defenses(engine, actor, kind, typed, by):
    rows = []
    def resistance(source):
        rows.append({'kind': 'resistance', 'feature_id': PREFIX + source, 'damage_types': [kind]})
    if active(engine, actor, 'prima_materia') and kind in (*TYPES, *PHYSICAL):
        resistance('prima_materia')
    for name in ('alloy', 'adaptation'):
        source = 'mercurial_qi' if name == 'alloy' else 'mercurial_adaptation'
        c = held(actor, name) if owns(engine, actor, source) else None
        if c and c.data['damage_type'] == kind:
            resistance(source)
    packet = engine.damage_context()
    if active(engine, actor, 'liquid_form') and kind in PHYSICAL and (typed.get('weapon') or packet and packet.kind == 'weapon'):
        resistance('liquid_form')
    return rows or None


@hook('damage_type_override')
def transmute(ctx, kinds, targets):
    from ..activation_settlement import profile
    if (not owns(ctx.engine, ctx.actor, 'mercurial_qi') or not profile(ctx.engine, ctx.actor, ctx.action)['qi_powered']
            or not kinds):
        return None
    valid = [str(k).upper() for k in kinds if str(k).upper() not in ('FORCE', 'VOID', 'UNTYPED')]
    if not valid:
        return None
    if (ctx.typed.get('weapon') or any(e.get('type') == 'attack' for e in ctx.typed.get('effects') or [])) and not ctx.damage_cache.get('mercurial_attack_choice'):
        return None
    if any(k in PHYSICAL for k in valid) and ctx.typed.get('weapon') and not profile(ctx.engine, ctx.actor, ctx.action)['weapon_delivery']:
        return None
    if all(k in PHYSICAL for k in valid) and active(ctx.engine, ctx.actor, 'prima_materia'):
        selected = choose(ctx.engine, ctx.actor, 'prima_damage', 'Prima Materia', TYPES, optional=True,
            labels={k: 'Replace this physical technique component with ' + k.title() + ' damage at no cost' for k in TYPES},
            subject=targets[0] if targets else ctx.actor)
        return selected[0] if selected else None
    if ctx.damage_cache.get('mercurial_component'):
        return None
    cost = 0 if active(ctx.engine, ctx.actor, 'prima_materia') else 1
    if ctx.actor.turn_flags.get('_round_mercurial_transmute') == stamp(ctx.engine) or ctx.actor.resources.get(QI, 0) < cost:
        return None
    selected = choose(ctx.engine, ctx.actor, 'transmute', 'Elemental Transmutation', TYPES, optional=True,
        labels={k: f'{k.title()} damage; spend {cost} Qi for this component' for k in TYPES},
        subject=targets[0] if targets else ctx.actor,
        prompt=f'Elemental Transmutation: change one damage component of {ctx.action.display_name} by {ctx.actor.display_name}; spend {cost} Qi, once per turn?')
    if not selected:
        return None
    tell = choose(ctx.engine, ctx.actor, 'tell', 'Quicksilver Tell', TELLS,
        prompt=f'Quicksilver Tell: choose the visible expression of {ctx.actor.display_name}’s {ctx.action.display_name}. Qi Sensing can detect it unless a concealment feature hides it.')
    if cost:
        ctx.engine._spend_resource(ctx.actor, QI, cost, PREFIX + 'mercurial_qi')
    ctx.actor.turn_flags['_round_mercurial_transmute'] = stamp(ctx.engine)
    ctx.damage_cache['mercurial_component'] = selected[0]
    put(ctx.engine, ctx.actor, 'tell', 'mercurial_qi',
        {'label': 'Quicksilver Tell: ' + tell[0], 'expression': tell[0], 'damage_type': selected[0], 'qi_sensing_visible': 1},
        'END_OF_CURRENT_TURN')
    return selected[0]


@effect('mercurial_sheath')
def armament_sheath(ctx, effect):
    from .qi_path import armament_condition
    armed = armament_condition(ctx.actor)
    if not active(ctx.engine, ctx.actor, 'prima_materia') or armed is None:
        raise ValueError('Mutable Domain Armament requires an active Prima Materia and your manifested Domain Armament.')
    if ctx.actor.turn_flags.get('_round_mercurial_sheath') == stamp(ctx.engine):
        raise ValueError('Your Domain Armament has already changed form this turn.')
    ctx.actor.turn_flags['_round_mercurial_sheath'] = stamp(ctx.engine)
    ctx.engine._update_condition_data(ctx.actor, armed, {**armed.data, 'mercurial_sheath': effect['shape']}, ctx.source)


@hook('attack_damage_type_override')
def transmute_attack(ctx, effect, target, kinds, index):
    if index != 1 and not (active(ctx.engine, ctx.actor, 'prima_materia') and all(str(k).upper() in PHYSICAL for k in kinds)):
        return None
    ctx.damage_cache['mercurial_attack_choice'] = 1
    try:
        return transmute(ctx, kinds, [target])
    finally:
        ctx.damage_cache.pop('mercurial_attack_choice', None)


@hook('before_damage_defenses')
def adaptation(engine, actor, amount, kind, source, by):
    from ..typed_reactions import can_use_reaction, spend_reaction
    if (kind not in TYPES or amount <= 0 or not owns(engine, actor, 'mercurial_adaptation')
            or actor.turn_flags.get('_round_mercurial_adapt') == engine.state.round_number
            or actor.resources.get(QI, 0) < 3 or not can_use_reaction(engine, actor,
                engine.state.actors.get(by), {'feature_id': PREFIX + 'mercurial_adaptation'})):
        return
    action = engine.action_catalog.get(source)
    selected = choose(engine, actor, 'adapt', 'Mercurial Adaptation', [kind], optional=True,
        labels={kind: f'Reaction and 3 Qi: resist {kind.title()} damage for 1 minute'},
        prompt=f'Mercurial Adaptation: {actor.display_name} is about to take {kind.title()} damage from {action.display_name if action else "the triggering effect"}. Spend your Reaction and 3 Qi to gain Resistance before damage resolves?')
    if not selected:
        return
    spend_reaction(engine, actor, {'feature_id': PREFIX + 'mercurial_adaptation'})
    engine._spend_resource(actor, QI, 3, PREFIX + 'mercurial_adaptation')
    actor.turn_flags['_round_mercurial_adapt'] = engine.state.round_number
    put(engine, actor, 'adaptation', 'mercurial_adaptation', {'damage_type': kind,
        'label': 'Mercurial Adaptation: Resistance to ' + kind.title()},
        f'START_OF_SLOT_AT:{engine.state.round_number + 10}:{engine.state.current_slot_index}')
    put(engine, actor, 'reposition', 'mercurial_adaptation', {'by': by or '', 'action': source or '',
        'label': 'Adaptive Reposition after the triggering damage'}, 'END_OF_CURRENT_TURN')
    put(engine, actor, 'assimilation_pending', 'mercurial_adaptation',
        {'by': by or '', 'action': source or '', 'label': 'Assimilate the triggering Qi attack'}, 'END_OF_CURRENT_TURN')


@hook('event', nested=True)
def damage_settled(engine, event_type, kwargs):
    if event_type == 'CONDITION_REMOVED' and (kwargs.get('payload') or {}).get('condition_id') == STATE + 'liquid_form':
        from ..gate2_runtime_models import Position, DiceSpec
        for aid in kwargs.get('target_ids') or ():
            actor = engine.state.actors.get(aid)
            if not actor or not owns(engine, actor, 'liquid_form'):
                continue
            occupied = engine._occupied_cells_except(aid)
            if engine.grid.placement_legal(actor.position, footprint=engine._footprint(actor), occupied_cells=occupied):
                continue
            cells = [Position(x=x, y=y, z=actor.position.z) for y in range(engine.grid.height) for x in range(engine.grid.width)
                     if engine.grid.placement_legal(Position(x=x, y=y, z=actor.position.z),
                          footprint=engine._footprint(actor), occupied_cells=occupied)]
            if not cells:
                raise ValueError(f'Liquid Form cannot end: the map has no legal unoccupied space for {actor.display_name}.')
            start = actor.position
            actor.position = min(cells, key=lambda p: (engine.grid.distance_ft(start, p), p.y, p.x))
            engine._append_event('MOVEMENT_COMMITTED', PREFIX + 'liquid_form', actor_id=aid,
                payload={'destination': actor.position.model_dump(mode='json'),
                         'path': [start.model_dump(mode='json'), actor.position.model_dump(mode='json')],
                         'cost_ft': 0, 'forced': True})
            roll = engine.roller.roll(DiceSpec(count=3, sides=10), actor_id=aid, reason='LIQUID_FORM_REFORM')
            engine._record_roll(roll)
            engine._commit_damage(actor, roll.total, 'FORCE', PREFIX + 'liquid_form', aid,
                getattr(engine, '_active_intent', None), reaction_depth=0)
        return
    if event_type == 'CONDITION_REMOVED' and (kwargs.get('payload') or {}).get('condition_id') == STATE + 'prima_materia':
        from .qi_path import armament_condition
        for aid in kwargs.get('target_ids') or ():
            actor = engine.state.actors.get(aid)
            armed = armament_condition(actor) if actor else None
            if armed and 'mercurial_sheath' in armed.data:
                ctxdata = {k: v for k, v in armed.data.items() if k != 'mercurial_sheath'}
                engine._update_condition_data(actor, armed, ctxdata, PREFIX + 'prima_materia')
            if actor and owns(engine, actor, 'prima_materia'):
                for c in list(actor.conditions.values()):
                    if c.condition_id in (STATE + 'perfected', STATE + 'flowing_foe', STATE + 'next_save') and c.source_definition_id == PREFIX + 'prima_materia':
                        engine._remove_condition(actor, c.condition_id, c.source_definition_id)
                for mid, modifier in list(actor.modifiers.items()):
                    if modifier.source_definition_id == PREFIX + 'prima_materia' and modifier.target_field in ('armor_class', 'speed_ft'):
                        actor.modifiers.pop(mid, None)
                        engine._append_event('MODIFIER_REMOVED', modifier.source_definition_id, actor_id=actor.entity_id,
                            target_ids=(actor.entity_id,), payload={'modifier_id': mid, 'reason': 'PRIMA_MATERIA_ENDED'})
        return
    if event_type == 'SAVE_ROLLED':
        actor = engine.state.actors.get(kwargs.get('actor_id'))
        c = held(actor, 'next_save') if actor else None
        if c and any(owns(engine, actor, n) for n in ('quicksilver_step', 'prima_materia')):
            engine._remove_condition(actor, c.condition_id, c.source_definition_id)
        return
    if event_type != 'DAMAGE_COMMITTED':
        return
    for aid in kwargs.get('target_ids') or ():
        actor = engine.state.actors.get(aid)
        pending = held(actor, 'reposition') if actor else None
        if not pending or pending.data.get('action') != kwargs.get('source_definition_id'):
            continue
        engine._remove_condition(actor, STATE + 'reposition', PREFIX + 'mercurial_adaptation')
        from .rider_choices import step
        token = _REPOSITION.set((engine, actor.entity_id))
        try:
            step(engine, actor, 'mercurial.reposition', 'Adaptive Reposition', actor, 5,
                 PREFIX + 'mercurial_adaptation', ignored_oa=list(engine.state.actors),
                 trigger='the triggering damage has resolved')
        finally:
            _REPOSITION.reset(token)


@hook('activation_settlement')
def assimilate(ctx, receipt):
    if not receipt['qi_powered']:
        return
    for actor in ctx.engine.state.actors.values():
        pending = held(actor, 'assimilation_pending')
        if (not owns(ctx.engine, actor, 'mercurial_adaptation')
                or not pending or pending.data.get('action') != receipt['action_id']
                or pending.data.get('by') != ctx.actor.entity_id
                or actor.entity_id not in receipt['recipient_ids']):
            continue
        ctx.engine._remove_condition(actor, pending.condition_id, pending.source_definition_id)
        put(ctx.engine, actor, 'assimilated', 'mercurial_adaptation',
            {'label': 'Assimilate the Attack: ' + ', '.join(t.title() for t in receipt['damage_types']),
             'damage_types': ','.join(receipt['damage_types']), 'source_cl': receipt['source_cl'],
             'source_kind': receipt['source_kind']})


@hook('presentation_hidden_conditions')
def private_conditions(engine, actor):
    # These are source bookkeeping or private learned information, not public
    # condition pills/history. The observer contract supplies the permitted view.
    hidden = {STATE + name for name in ('assimilation_pending', 'assimilated', 'reposition', 'tell')}
    return [c.instance_id for c in actor.conditions.values() if c.condition_id in hidden] or None


@hook('observer_information')
def learned_information(engine, viewer):
    from .. import senses
    from ..target_knowledge import can_see
    rows = []
    learned = held(viewer, 'assimilated') if owns(engine, viewer, 'mercurial_adaptation') else None
    if learned:
        types = ', '.join(t.title() for t in learned.data['damage_types'].split(',') if t)
        cl = learned.data['source_cl']
        kind = learned.data['source_kind']
        text = (f'Assimilate the Attack: the activated Qi feature dealt {types}. '
                + (f'Its Source Cultivation Level was {cl}. ' if cl else 'Its Source Cultivation Level is unknown. ')
                + (f'It was {kind}-based. ' if kind else 'Its source category is unknown. ')
                + 'This reveals no unactivated features or exact statistics.')
        rows.append({'kind': 'declaration', 'source_id': PREFIX + 'mercurial_adaptation',
                     'viewer_id': viewer.entity_id, 'details': {'text': text}})
    if not engine._on_battlefield(viewer):
        return rows or None
    for actor in engine.state.actors.values():
        tell = held(actor, 'tell') if owns(engine, actor, 'mercurial_qi') else None
        if not tell or not engine._on_battlefield(actor):
            continue
        seen = can_see(engine, viewer, actor)
        reach = senses.reach(engine, viewer, 'qi_sensing', actor)
        cells = engine._actor_volume if viewer.position.z or actor.position.z or engine.grid.finite_heights else engine._actor_cells
        sensed = (reach > 0 and engine._distance_actor_to_actor(viewer, actor) <= reach
                  and engine.grid.line_of_sight_between_cell_sets(cells(viewer), cells(actor)))
        if not seen and not sensed:
            continue
        # Generic Hidden/Invisible never conceals active Qi. A source-authored
        # concealment profile is positive authority; names and narration aren't.
        concealed = any('qi_concealment' in ((c.data.get('information_profile') or {}).get('tags') or ())
                        for c in actor.conditions.values())
        if concealed and not seen:
            continue
        expression = tell.data['expression']
        text = (f'Quicksilver Tell: {actor.display_name} shows {expression.lower()} from Elemental Transmutation.' if seen else
                f'Quicksilver Tell: Qi Sensing detects {expression.lower()} from active Qi within range; this gives no creature identity or occupied space.')
        rows.append({'kind': 'declaration', 'source_id': PREFIX + 'mercurial_qi',
                     'viewer_id': viewer.entity_id, 'details': {'text': text}})
    return rows or None


@hook('damage_dealt')
def perfected_damage(ctx, target, amount):
    from ..activation_settlement import profile
    current = form(ctx.engine, ctx.actor)
    if (current != 'Corrosive' or amount <= 0
            or not profile(ctx.engine, ctx.actor, ctx.action)['qi_powered']
            or ctx.actor.turn_flags.get('_round_mercurial_form_damage') == stamp(ctx.engine)):
        return
    ctx.actor.turn_flags['_round_mercurial_form_damage'] = stamp(ctx.engine)
    from ..typed_executor import run_effects
    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache=ctx.damage_cache)
    run_effects(sub, [{'type': 'reaction_denied', 'applies_to': 'target', 'expires_on': 'START_OF_TARGET_NEXT_TURN'}])


@hook('activation_effects_resolved')
def conductive_damage(ctx, receipt):
    from .. import senses
    if (form(ctx.engine, ctx.actor) != 'Conductive' or not receipt['qi_powered'] or not receipt['damaged_ids']
            or ctx.actor.turn_flags.get('_round_mercurial_form_damage') == stamp(ctx.engine)):
        return
    options = {aid: ctx.engine.state.actors[aid] for aid in receipt['damaged_ids'] if aid in ctx.engine.state.actors}
    chosen = choose(ctx.engine, ctx.actor, 'conductive_target', 'Conductive Form', list(options),
        automatic_options=list(options),
        labels={aid: f'Deal an additional 2d8 Lightning or Thunder damage to {target.display_name}' for aid, target in options.items()})
    if not chosen:
        return
    target = options[chosen[0]]
    selected = choose(ctx.engine, ctx.actor, 'conductive', 'Conductive Form', ['LIGHTNING', 'THUNDER'], subject=target,
        labels={k: f'Deal an additional 2d8 {k.title()} damage to {target.display_name}' for k in ('LIGHTNING', 'THUNDER')})
    ctx.actor.turn_flags['_round_mercurial_form_damage'] = stamp(ctx.engine)
    from ..typed_executor import run_effects
    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache=ctx.damage_cache)
    run_effects(sub, [{'type': 'damage', 'applies_to': 'target', 'dice': {'count': 2, 'sides': 8},
                      'damage_types': [selected[0].lower()], 'resolved_damage_type': selected[0]}])


@hook('opportunity_allowed')
def no_opportunity(engine, reactor, mover):
    c = held(mover, 'flowing_foe')
    if active(engine, mover, 'prima_materia') and c and c.data['creature'] == reactor.entity_id:
        return False
    if active(engine, mover, 'liquid_form'):
        liquid = held(mover, 'liquid_form')
        if reactor.entity_id in liquid.data.get('crossed_ids', ()) or set(engine._actor_cells(reactor)).intersection(engine._actor_cells(mover)):
            return False
    return None


@effect('mercurial_arrival')
def arrival(ctx, effect):
    if not owns(ctx.engine, ctx.actor, 'quicksilver_step'):
        return
    ctx.actor.turn_flags['_round_mercurial_step'] = stamp(ctx.engine)
    if ctx.damage_cache.get('mercurial_start') == ctx.actor.position:
        return
    carry_companion(ctx)
    options = ['move', 'temporary_hp', 'save']
    if owns(ctx.engine, ctx.actor, 'mercurial_qi') and not held(ctx.actor, 'alloy_scene_used'):
        options.append('alloy')
    from .qi_path import armament_condition
    if armament_condition(ctx.actor):
        options.append('armament')
    selected = choose(ctx.engine, ctx.actor, 'arrival', 'Flowing Arrival', options, labels={
        'move': 'Move 5 feet without Opportunity Attacks', 'temporary_hp': f'Gain {proficiency(ctx.engine, ctx.actor)} Temporary HP',
        'save': 'Advantage on your next saving throw before your next turn starts',
        'alloy': 'Change Adaptive Alloy until your next Long Rest or Full Cultivation Session; once per scene',
        'armament': 'Move your Domain Armament up to 20 feet'},
        prompt=f'Flowing Arrival: choose one benefit for {ctx.actor.display_name} after Quicksilver Step at no additional cost.')
    if selected[0] == 'move':
        from .rider_choices import step
        step(ctx.engine, ctx.actor, 'mercurial.arrival_move', 'Flowing Arrival', ctx.actor, 5, ctx.source,
             ignored_oa=list(ctx.engine.state.actors))
    elif selected[0] == 'temporary_hp':
        from ..typed_executor import run_effects
        run_effects(ctx, [{'type': 'temp_hp', 'applies_to': 'self', 'flat': proficiency(ctx.engine, ctx.actor)}])
    elif selected[0] == 'save':
        put(ctx.engine, ctx.actor, 'next_save', 'quicksilver_step', {'label': 'Flowing Arrival: Advantage on next save'}, 'START_OF_SOURCE_NEXT_TURN')
    elif selected[0] == 'alloy':
        old = held(ctx.actor, 'alloy')
        alternatives = [t for t in TYPES if not old or t != old.data.get('damage_type')]
        damage = choose(ctx.engine, ctx.actor, 'arrival_alloy', 'Adaptive Alloy', alternatives)[0]
        clock = (old.data.get('choice_clock') or '') if old else ''
        put(ctx.engine, ctx.actor, 'alloy', 'mercurial_qi', {'damage_type': damage,
            'choice_clock': clock, 'override_until_rest': 1,
            'label': 'Adaptive Alloy: ' + damage.title() + ' Resistance until your next Long Rest or Full Cultivation Session'})
        put(ctx.engine, ctx.actor, 'alloy_scene_used', 'quicksilver_step', {'label': 'Flowing Arrival Alloy change used this scene'})
    elif selected[0] == 'armament':
        from .qi_path import move_armament, armament_point
        from .needle import cell_id
        from ..gate2_runtime_models import Position
        old = Position(x=armament_point(ctx.actor)[0], y=armament_point(ctx.actor)[1])
        from .qi_path import armament_move_allowed
        cells = [Position(x=x, y=y) for y in range(ctx.engine.grid.height) for x in range(ctx.engine.grid.width)
                 if armament_move_allowed(ctx.engine, ctx.actor, Position(x=x, y=y), max_distance_ft=20)]
        by_id = {cell_id(cell): cell for cell in cells}
        chosen = choose(ctx.engine, ctx.actor, 'arrival_armament', 'Flowing Arrival', list(by_id), optional=True,
            labels={key: 'Move the Domain Armament to ' + key.removeprefix('cell:') for key in by_id})
        if chosen and not move_armament(ctx.engine, ctx.actor, by_id[chosen[0]], ctx.source, max_distance_ft=20):
            ctx.engine._append_event('DECLARATION', ctx.source, actor_id=ctx.actor.entity_id,
                target_ids=(ctx.actor.entity_id,), payload={'text': 'Flowing Arrival: the Domain Armament could not reach that space; it remains where it is.'})


@effect('mercurial_step_begin')
def step_begin(ctx, effect):
    if not owns(ctx.engine, ctx.actor, 'quicksilver_step'):
        raise ValueError('This creature does not own Quicksilver Step.')
    ctx.damage_cache['mercurial_start'] = ctx.actor.position
    from .. import senses
    ctx.damage_cache['mercurial_companions'] = [a.entity_id for a in ctx.engine.state.actors.values()
        if a.entity_id != ctx.actor.entity_id and a.active and ctx.engine._distance_actor_to_actor(ctx.actor, a) <= 5]
    ctx.damage_cache['mercurial_known_companions'] = [aid for aid in ctx.damage_cache['mercurial_companions']
        if senses.perceives(ctx.engine, ctx.actor, ctx.engine.state.actors[aid])]


@effect('mercurial_exchange')
def exchange_armament(ctx, effect):
    from .qi_path import armament_condition, armament_point
    from .teleport_steps import destination_allowed
    from ..gate2_runtime_models import Position
    from ..typed_executor import teleport_subject
    armed = armament_condition(ctx.actor)
    if armed is None:
        raise ValueError('Quicksilver Step requires your own floating Domain Armament to exchange positions.')
    x, y = armament_point(ctx.actor)
    destination = Position(x=x, y=y)
    start = ctx.actor.position
    if not destination_allowed(ctx.engine, ctx.actor, destination, 60):
        raise ValueError('The Domain Armament exchange has no legal visible destination within 60 feet.')
    if not ctx.engine.grid.placement_legal(destination, footprint=ctx.engine._footprint(ctx.actor),
            occupied_cells=ctx.engine._occupied_cells_except(ctx.actor.entity_id)):
        raise ValueError('Your body does not fit at the Domain Armament’s position.')
    if not ctx.engine.grid.placement_legal(start, occupied_cells=ctx.engine._occupied_cells_except(ctx.actor.entity_id)):
        raise ValueError('The Domain Armament cannot fit in your former space.')
    if not ctx.engine._line_of_sight_actor_to_cell(ctx.actor, start):
        raise ValueError('Your former space is blocked or cannot contain the Domain Armament.')
    teleport_subject(ctx, ctx.actor, destination)
    if ctx.actor.position != destination:
        return
    # Preserve the same condition and any bound-item identity/properties. The
    # printed exchange moves it, rather than manifesting a second Armament.
    ctx.engine._update_condition_data(ctx.actor, armed, {**armed.data, 'ax': start.x, 'ay': start.y}, ctx.source)


def carry_companion(ctx):
    from ..gate2_runtime_models import Position
    from ..typed_executor import teleport_subject, condition_rules
    from .rider_choices import pick
    from .willing_targets import asks_consent
    engine, actor = ctx.engine, ctx.actor
    extra = 1 if active(engine, actor, 'prima_materia') else 2
    if actor.resources.get(QI, 0) < extra:
        return
    start = ctx.damage_cache['mercurial_start']
    # Only creatures the actor perceives (mercurial_known_companions): a hidden neighbour is never offered.
    subjects = {aid: engine.state.actors[aid] for aid in ctx.damage_cache.get('mercurial_known_companions', ())
        if engine.state.actors[aid].active and engine.grid.distance_ft(start, engine.state.actors[aid].position) <= 5
        and not any(r.get('no_teleport') for r in condition_rules(engine.state.actors[aid]))}
    cells = {}
    for aid, subject in subjects.items():
        destinations = [Position(x=actor.position.x + dx, y=actor.position.y + dy, z=actor.position.z)
                        for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx or dy)
                        and 0 <= actor.position.x + dx < engine.grid.width
                        and 0 <= actor.position.y + dy < engine.grid.height]
        cells[aid] = [p for p in destinations if engine.grid.placement_legal(p,
            footprint=engine._footprint(subject), occupied_cells=engine._occupied_cells_except(aid))]
    subjects = {aid: a for aid, a in subjects.items() if cells[aid]}
    if not subjects:
        return
    selected = pick(engine, actor, 'mercurial.companion', 'Carry a Companion', list(subjects),
        subject=actor, intent=ctx.intent, optional=True,
        automatic_options=list(subjects),
        labels={aid: f'Ask {a.display_name} to teleport to a legal space beside you; spend {extra} additional Qi if willing'
                for aid, a in subjects.items()},
        prompt=f'Quicksilver Step: {actor.display_name} may carry one willing creature that was within reach for {extra} additional Qi. Choose that creature or decline.')
    if not selected:
        return
    subject = subjects[selected[0]]
    if not asks_consent(engine, ctx.intent, subject, 'Carry a Companion',
        f'Quicksilver Step: will {subject.display_name} teleport with {actor.display_name} to an adjacent legal space? {actor.display_name} pays {extra} additional Qi.',
        prefer_accept=subject.team_id == actor.team_id, asker=actor):
        return
    from .needle import cell_id
    available = {cell_id(p): p for p in cells[subject.entity_id]}
    chosen = choose(engine, actor, 'companion_landing', 'Carry a Companion', list(available),
        labels={key: f'{subject.display_name} arrives at ' + key.removeprefix('cell:') for key in available}, subject=subject)
    if not chosen:
        return
    engine._spend_resource(actor, QI, extra, PREFIX + 'quicksilver_step')
    teleport_subject(ctx, subject, available[chosen[0]], unwilling=False, forced=False)


@hook('turn_start_choice')
def perfected(engine, actor):
    if not active(engine, actor, 'prima_materia'):
        return
    form_labels = {'Adamant': 'Adamant: +2 AC until your next turn starts',
                'Flowing': 'Flowing: +15 feet Speed and avoid one chosen creature’s Opportunity Attacks this turn',
                'Vapor': 'Vapor: Fly Speed 40 feet and Hover until your next turn starts; airtight barriers still stop you',
                'Reflective': 'Reflective: Advantage on your next saving throw before your next turn starts',
                'Restorative': f'Restorative: gain {2 * proficiency(engine, actor)} Temporary HP, replacing remaining HP from this Form',
                'Conductive': 'Conductive: the first Qi-powered damaging activation this turn deals +2d8 Lightning or Thunder damage to one damaged target',
                'Corrosive': 'Corrosive: the first creature damaged by your Qi-powered feature this turn cannot take Reactions until its next turn starts'}
    selected = choose(engine, actor, 'form', 'Perfected Adaptation', FORMS, labels=form_labels,
        prompt=f'Prima Materia: choose {actor.display_name}’s Form until its next turn starts. No additional Qi or action is required.')[0]
    # The persisted condition label states the Form's effect and when it ends, not just its name.
    put(engine, actor, 'perfected', 'prima_materia', {'form': selected, 'label': form_labels[selected]}, 'START_OF_SOURCE_NEXT_TURN')
    if selected in ('Adamant', 'Flowing'):
        engine._add_modifier(actor, PREFIX + 'prima_materia', 'armor_class' if selected == 'Adamant' else 'speed_ft',
            'ADD', 2 if selected == 'Adamant' else 15, 'SELF', expires_on='START_OF_SOURCE_NEXT_TURN',
            source_actor_id=actor.entity_id)
    if selected == 'Restorative':
        from .states import context
        from ..typed_executor import run_effects
        ctx = context(engine, actor, PREFIX + 'prima_materia', [actor])
        run_effects(ctx, [{'type': 'temp_hp', 'flat': 2 * proficiency(engine, actor), 'applies_to': 'self'}])
    elif selected == 'Reflective':
        put(engine, actor, 'next_save', 'prima_materia', {'label': 'Reflective Form: Advantage on next save'}, 'START_OF_SOURCE_NEXT_TURN')
    elif selected == 'Flowing':
        from .. import senses
        options = [a.entity_id for a in engine.state.actors.values() if a.entity_id != actor.entity_id]
        chosen = choose(engine, actor, 'flowing_foe', 'Flowing Form', options,
            automatic_options=list(options),
            labels={aid: 'Do not provoke Opportunity Attacks from ' + engine.state.actors[aid].display_name for aid in options}) if options else []
        if chosen:
            put(engine, actor, 'flowing_foe', 'prima_materia', {'creature': chosen[0], 'label': 'Flowing Form: chosen Opportunity Attacks avoided'}, 'START_OF_SOURCE_NEXT_TURN')


def form(engine, actor):
    c = held(actor, 'perfected')
    return c.data['form'] if c and active(engine, actor, 'prima_materia') else ''


@hook('flight')
def vapor(engine, actor):
    return {'fly_speed_ft': 40, 'flight_hover': 1} if form(engine, actor) == 'Vapor' else None


@hook('pass_through')
def passage(engine, actor, occupant):
    if active(engine, actor, 'liquid_form'):
        return 'free'
    frame = _REPOSITION.get()
    if frame and frame[0] is engine and frame[1] == actor.entity_id and owns(engine, actor, 'mercurial_adaptation'):
        return 'difficult'
    # Liquid Form explicitly ignores the nonmagical creature-space surcharge.
    # Prima Materia alone grants narrow openings, not creature passage.
    return None


@hook('pass_through_entered')
def crossed_creature(engine, mover, occupant, intent):
    if not active(engine, mover, 'liquid_form'):
        return
    liquid = held(mover, 'liquid_form')
    crossed = list(liquid.data.get('crossed_ids') or [])
    if occupant.entity_id not in crossed:
        crossed.append(occupant.entity_id)
        engine._update_condition_data(mover, liquid, {**liquid.data, 'crossed_ids': crossed}, PREFIX + 'liquid_form')


@hook('escape_mode')
@hook('escape_save_mode')
def liquid_escape(engine, actor, grips):
    return 'ADVANTAGE' if active(engine, actor, 'liquid_form') else None


@hook('escape_check_choice_required')
def liquid_escape_skill(ctx, effect, dc, grips, hazards):
    if active(ctx.engine, ctx.actor, 'liquid_form') and grips:
        return {'name': 'Liquid Form', 'feature_id': PREFIX + 'liquid_form'}
    return None


@hook('repeat_save_scope')
def liquid_repeat_scope(engine, resolution):
    actor = engine.state.actors.get(resolution.get('holder_id'))
    condition = actor.conditions.get(resolution.get('instance_id')) if actor else None
    if not actor or not condition or not active(engine, actor, 'liquid_form') or condition.condition_id.rsplit('.', 1)[-1] not in ('grappled', 'restrained'):
        return None
    @contextmanager
    def scope():
        token = _ESCAPE_SAVE.set((engine, actor.entity_id))
        try:
            yield
        finally:
            _ESCAPE_SAVE.reset(token)
    return scope()


@hook('skill_check_mode')
def liquid_escape_check(ctx, actor, ability, skill):
    if active(ctx.engine, actor, 'liquid_form') and set(ctx.typed.get('check_against') or ()).intersection({'grappled', 'restrained'}):
        return 'ADVANTAGE'
    return None


@hook('ability_check_hazard_mode')
def liquid_hazard_check(engine, actor, ability, skill, against, hazards):
    if active(engine, actor, 'liquid_form') and set(hazards).intersection({'grappled', 'restrained'}):
        return 'ADVANTAGE'
    return None


@hook('save_mode')
def next_save(engine, actor, ability, dc, source_id, context):
    frame = _ESCAPE_SAVE.get()
    if frame and frame[0] is engine and frame[1] == actor.entity_id and set(context.get('named') or ()).intersection({'grappled', 'restrained'}):
        return 'ADVANTAGE'
    return 'ADVANTAGE' if held(actor, 'next_save') and any(owns(engine, actor, n) for n in ('quicksilver_step', 'prima_materia')) else None


@hook('save_final')
def consume_save(ctx, actor, ability, named, failed):
    c = held(actor, 'next_save')
    if c and any(owns(ctx.engine, actor, n) for n in ('quicksilver_step', 'prima_materia')):
        ctx.engine._remove_condition(actor, c.condition_id, c.source_definition_id)


@hook('damage_dice_reroll')
def mutable_damage(ctx, effect, kinds, count):
    from ..activation_settlement import profile
    if (not active(ctx.engine, ctx.actor, 'prima_materia') or not profile(ctx.engine, ctx.actor, ctx.action)['qi_powered']
            or ctx.actor.turn_flags.get('_round_mercurial_mutable') == stamp(ctx.engine)):
        return None
    # The packet's own damage roll (ctx.damage_roll, set by typed_executor): not the last roll in the log, and not
    # the last DAMAGE roll either, since a later packet or a check can come after it.
    recorded = ctx.damage_roll
    dice = list(recorded.dice) if recorded is not None and recorded.dice else []
    maximum = min(count, proficiency(ctx.engine, ctx.actor))
    if not dice or maximum <= 0:
        return None
    options = [str(i) for i in range(len(dice))]
    from .rider_choices import pick
    selected = pick(ctx.engine, ctx.actor, 'mercurial.mutable_attack', 'Mutable Damage', options,
        intent=ctx.intent, optional=True, minimum=1, maximum=maximum,
        labels={str(i): f'Die {i + 1}: {value}; reroll and use its new result' for i, value in enumerate(dice)},
        preferred=sorted(options, key=lambda k: dice[int(k)])[:maximum],
        prompt=f'Mutable Damage: choose up to {maximum} dice from {ctx.action.display_name} to reroll once this turn. You must use the new results; no additional cost.')
    indices = sorted({int(i) for i in selected if i.isdigit() and int(i) < len(dice)})[:maximum]
    if indices:
        ctx.actor.turn_flags['_round_mercurial_mutable'] = stamp(ctx.engine)
        return {'indices': indices}
    return None


@hook('confirmed_damage_roll_adjustment')
def mutable_attack(engine, actor, target, spec, intent, source, roll):
    from .attack_scope import current
    from ..activation_settlement import profile
    frame = current(engine)
    if not frame or not active(engine, actor, 'prima_materia'):
        return None
    ctx = frame['context']
    if (frame.get('actor_id') != actor.entity_id or frame.get('source') != source
            or not profile(engine, actor, ctx.action)['qi_powered']
            or actor.turn_flags.get('_round_mercurial_mutable') == stamp(engine)):
        return None
    from .rider_choices import pick
    dice = list(roll.dice)
    if not dice:
        return None
    options = [str(i) for i in range(len(dice))]
    maximum = min(len(dice), proficiency(engine, actor))
    chosen = pick(engine, actor, 'mercurial.mutable_attack', 'Mutable Damage', options, subject=target,
        intent=intent, optional=True, minimum=1, maximum=maximum,
        labels={str(i): f'Die {i + 1}: {value}; reroll and use its new result' for i, value in enumerate(dice)},
        preferred=sorted(options, key=lambda k: dice[int(k)])[:maximum],
        prompt=f'Mutable Damage: choose up to {maximum} damage dice from {ctx.action.display_name} against {target.display_name} to reroll once this turn. You must use the new results; no additional cost.')
    if not chosen:
        return None
    actor.turn_flags['_round_mercurial_mutable'] = stamp(engine)
    from ..gate2_runtime_models import DiceSpec
    fresh = engine.roller.roll(DiceSpec(count=len(chosen), sides=spec['damage'].sides, modifier=0),
                               actor_id=actor.entity_id, reason='MUTABLE_DAMAGE')
    engine._record_roll(fresh)
    return fresh.total - sum(dice[int(i)] for i in chosen)


@hook('journey_rest')
def rest(session, aid):
    actor = session.state['actors'][aid]
    if any(r.get('block') == BLOCK and r.get('kind') == 'mercurial_qi' for r in actor['bundle'].get('typed_passives', ())):
        actor['travel_uses']['mercurial_alloy_rest'] = actor['long_rests']
        # Completing a rest opens a new choice; it does not silently erase the
        # existing adaptation before the owner chooses its replacement.


@hook('journey_options')
def alloy_options(session, aid):
    actor = session.state['actors'][aid]
    if not any(r.get('block') == BLOCK and r.get('kind') == 'mercurial_qi' for r in actor['bundle'].get('typed_passives', ())):
        return None
    options = []
    if actor.get('control_mode') == 'MANUAL':
        options.append({'id': 'mercurial.new_scene', 'kind': 'mercurial_scene_transition',
            'payload': {'authority': 'GM', 'reason': 'The table owner confirms that the continuous meaningful situation has ended.'},
            'label': 'GM ruling: the meaningful situation has ended; begin a new scene and refresh Mercurial scene uses. This is not a rest and restores no Qi.'})
        options.append({'id': 'mercurial.cultivation_environment', 'kind': 'mercurial_cultivation_environment',
            'payload': {'authority': 'GM', 'calm': 1, 'energy_source': 'Ambient spiritual energy confirmed by the table owner'},
            'label': 'GM ruling: confirm this place is reasonably calm and has sufficient ambient spiritual energy for a Full Cultivation Session; this grants no Qi or rest by itself'})
    environment = actor.get('source_selections', {}).get(PREFIX + 'cultivation_environment') or {}
    if (environment.get('journey_id') == session.state['journey_id'] and environment.get('calm') == 1
            and (environment.get('x'), environment.get('y')) == (actor['position']['x'], actor['position']['y'])
            and actor['travel_uses'].get('mercurial_cultivation_used') != actor['long_rests']
            and not actor['incapacitated']):
        options.append({'id': 'mercurial.cultivation', 'kind': 'mercurial_cultivation_session', 'payload': {},
            'label': 'Full Cultivation Session: spend 2 uninterrupted hours in the confirmed calm spiritual environment, recover all missing Qi, then choose Adaptive Alloy; once per Long Rest'})
    if 'mercurial_alloy_rest' not in actor['travel_uses']:
        return options
    return [*options, *({'id': 'mercurial.alloy.' + kind, 'kind': 'mercurial_alloy',
             'payload': {'damage_type': kind}, 'label': f"Adaptive Alloy: {actor['name']} chooses {kind.title()} Resistance after resting, until the next choice; no Qi cost"}
            for kind in TYPES)]


@hook('journey_command')
def alloy_command(session, aid, kind, payload):
    if kind == 'mercurial_scene_transition':
        return scene_transition(session, aid, payload)
    if kind in ('mercurial_cultivation_environment', 'mercurial_cultivation_session'):
        return cultivation_command(session, aid, kind, payload)
    if kind != 'mercurial_alloy':
        return None
    from ..journey import require
    require(set(payload) == {'damage_type'} and any(row['kind'] == kind and row['payload'] == payload for row in alloy_options(session, aid) or []),
            'Adaptive Alloy requires Mercurial Qi and a completed Long Rest or Full Cultivation Session.')
    actor = session.state['actors'][aid]
    actor.setdefault('source_selections', {})[PREFIX + 'mercurial_qi'] = {'damage_type': payload['damage_type'],
        'actor_id': aid, 'authority': 'owner_choice_after_rest', 'expires': 'until_next_choice',
        'choice_clock': f"{actor['long_rests']}:{actor['travel_uses'].get('mercurial_cultivation_serial', 0)}"}
    del actor['travel_uses']['mercurial_alloy_rest']
    session.emit('MERCURIAL_ALLOY_CHOSEN', aid, damage_type=payload['damage_type'], source=PREFIX + 'mercurial_qi')
    return True


def scene_transition(session, aid, payload):
    """An explicit native GM scene ruling, never inferred from inactivity/death.

    Applies to the owned family throughout this journey. The terminal combat
    remains immutable; only its continuation snapshot's per-scene use markers
    are released. Time, HP, Qi, Alloy choices and independent sources remain.
    """
    import json
    from ..journey import require
    actor = session.state['actors'][aid]
    require(actor.get('control_mode') == 'MANUAL' and set(payload) == {'authority', 'reason'}
            and payload.get('authority') == 'GM' and type(payload.get('reason')) is str
            and 1 <= len(payload['reason'].strip()) <= 400
            and any(r.get('block') == BLOCK for r in actor['bundle'].get('typed_passives', ())),
            'A table owner must explicitly confirm that the continuous meaningful situation ended.')
    affected = {}
    key = PREFIX + 'scene'
    number = 1 + max((a.get('source_selections', {}).get(key, {}).get('number', 0)
                      for a in session.state['actors'].values()), default=0)
    for owner_id, owner in session.state['actors'].items():
        if not any(r.get('block') == BLOCK for r in owner['bundle'].get('typed_passives', ())):
            continue
        owner.setdefault('source_selections', {})[key] = {**payload, 'actor_id': owner_id,
            'authority_actor_id': aid, 'number': number, 'expires': 'next_declared_scene'}
        snapshot = owner.get('encounter_snapshot') or {}
        conditions = snapshot.get('conditions') or {}
        removed = []
        for iid, encoded in list(conditions.items()):
            c = json.loads(encoded)
            if c.get('condition_id') in (STATE + 'prima_used', STATE + 'alloy_scene_used'):
                removed.append(encoded)
                del conditions[iid]
        affected[owner_id] = removed
        owner.get('source_selections', {}).pop(PREFIX + 'cultivation_environment', None)
    session.emit('MERCURIAL_SCENE_TRANSITION', aid, source=PREFIX + 'mercurial_qi', number=number,
                 authority='GM', reason=payload['reason'], released_markers=affected)
    return True


def cultivation_command(session, aid, kind, payload):
    from ..journey import require
    actor = session.state['actors'][aid]
    require(any(r.get('block') == BLOCK and r.get('kind') == 'mercurial_qi' for r in actor['bundle'].get('typed_passives', ())),
            'This creature does not own Mercurial Qi.')
    if kind == 'mercurial_cultivation_environment':
        require(actor.get('control_mode') == 'MANUAL' and set(payload) == {'authority', 'calm', 'energy_source'}
                and payload.get('authority') == 'GM' and type(payload.get('calm')) is int and payload['calm'] in (0, 1)
                and type(payload.get('energy_source')) is str and 1 <= len(payload['energy_source'].strip()) <= 400,
                'A table owner must explicitly identify the local spiritual-energy source and whether the environment is calm.')
        data = {**payload, 'actor_id': aid, 'journey_id': session.state['journey_id'], 'expires': 'when_leaving_this_place',
                'x': actor['position']['x'], 'y': actor['position']['y']}
        actor.setdefault('source_selections', {})[PREFIX + 'cultivation_environment'] = data
        session.emit('MERCURIAL_CULTIVATION_ENVIRONMENT', aid, source=PREFIX + 'mercurial_qi', declaration=data)
        return True
    require(not payload and not actor['incapacitated'] and any(r['kind'] == kind for r in alloy_options(session, aid) or []),
            'A Full Cultivation Session requires an unused Long Rest use and an explicitly confirmed calm spiritual environment.')
    session.tick(7200)
    maximum = next((r['maximum'] for r in actor['bundle']['actor_template']['resources'] if r['resource_id'] == QI), None)
    require(type(maximum) is int, 'This character has no native Qi resource pool.')
    restored = max(0, maximum - actor['resources'].get(QI, 0))
    actor['resources'][QI] = maximum
    actor['travel_uses']['mercurial_cultivation_used'] = actor['long_rests']
    actor['travel_uses']['mercurial_cultivation_serial'] = actor['travel_uses'].get('mercurial_cultivation_serial', 0) + 1
    actor['travel_uses']['mercurial_alloy_rest'] = actor['long_rests']
    session.emit('FULL_CULTIVATION_SESSION_COMPLETED', aid, source=PREFIX + 'mercurial_qi', seconds=7200,
                 restored_qi=restored, text=f"{actor['name']} completes a two-hour Full Cultivation Session and may choose Adaptive Alloy.")
    return True


@hook('journey_state_changed')
def leave_cultivation_site(session, aid):
    actor = session.state['actors'][aid]
    environment = actor.get('source_selections', {}).get(PREFIX + 'cultivation_environment') or {}
    if (session.state['phase'] != 'travel'
            or (environment.get('x'), environment.get('y')) != (actor['position']['x'], actor['position']['y'])):
        actor.get('source_selections', {}).pop(PREFIX + 'cultivation_environment', None)


@hook('match_initialize')
def alloy_from_journey(engine):
    for bundle in engine.typed_bundle_documents:
        actor = engine.state.actors.get(bundle['actor_id'])
        setup = bundle.get('journey_setup') or {}
        alloy = (setup.get('source_selections') or {}).get(PREFIX + 'mercurial_qi')
        if actor and alloy and owns(engine, actor, 'mercurial_qi') and alloy.get('damage_type') in TYPES:
            damage = alloy['damage_type']
            prior = held(actor, 'alloy')
            if prior and prior.data.get('override_until_rest') == 1 and prior.data.get('choice_clock') == alloy.get('choice_clock'):
                continue
            put(engine, actor, 'alloy', 'mercurial_qi', {'damage_type': damage, 'choice_clock': alloy.get('choice_clock', ''),
                'label': 'Adaptive Alloy: ' + damage.title() + ' Resistance until your next choice'})


@hook('journey_combat_setup')
def persistent_alloy(session, aid):
    actor = session.state['actors'][aid]
    owned = any(r.get('block') == BLOCK and r.get('kind') == 'mercurial_qi' for r in actor['bundle'].get('typed_passives', ()))
    if not owned:
        return None
    from ..journey import require
    require('mercurial_alloy_rest' not in actor['travel_uses'], 'Choose Adaptive Alloy after the completed rest before entering combat.')
    alloy = actor.get('source_selections', {}).get(PREFIX + 'mercurial_qi')
    if alloy:
        return {'source_selections': {PREFIX + 'mercurial_qi': dict(alloy)}}

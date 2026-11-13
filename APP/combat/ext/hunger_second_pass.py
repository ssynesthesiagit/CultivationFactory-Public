"""Owned Hunger combat rewards; preparation and source declarations stay explicit.

Only primitive condition data is retained. Automatic owners never invent a
rare meal, a source damage type or a qualifying Scholar target.

Shared helpers begin_courses, end_courses and scale_cut are consumed by
hunger_riders at the Mantle start/end and Thick Hide checkpoints.
"""
from __future__ import annotations
from . import hook
from . import hunger_riders as h
from .needle import ask, checkpoint_id, CHOICE
from .effect_durations import token
from .retained_updates import record_instance_update

DRAGON = h.H + 'dragon_marrow_banquet_scripture'
KING = h.H + 'demon_king_roast_method'
SCHOLAR = 'insight.monster-taste-scholar'
PRESSURE = 'condition:typed.demon_king_pressure'
SKY = 'condition:typed.dragon_marrow_sky'
ELEMENTS = ('acid', 'cold', 'fire', 'lightning', 'poison', 'thunder')


def _write(engine, actor, held, **values):
    held.data = {**held.data, **values}
    record_instance_update(engine, actor, 'condition', held.instance_id, held)


def _ask(ctx, key, options, prompt, *, automatic=True, automatic_options=None, target=None,
         name='Digestive Mantle', feature_id='Digestive Mantle'):
    target = target or ctx.actor
    return ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, key.upper(), ctx.actor.entity_id), ctx.actor,
               CHOICE + key, list(options), labels={x: x.replace('_', ' ').title() for x in options},
               target_id=target.entity_id, name=name, feature_id=feature_id,
               prompt=prompt, automatic=automatic, automatic_options=automatic_options, allow_decline=not automatic,
               default='first' if automatic else 'decline')


def _owner_use(ctx, key, prompt, target, name):
    """Players control spending; AI receives an automatic, perception-limited decision."""
    from . import ai_controlled
    automatic = ai_controlled(ctx.engine, ctx.actor)
    if automatic:
        from ..target_knowledge import can_see
        if not can_see(ctx.engine, ctx.actor, target):
            return []
    return _ask(ctx, key, ['use'], prompt, automatic=automatic, automatic_options=['use'],
                target=target, name=name, feature_id=name)


def begin_courses(ctx):
    """Called by the Mantle owner after its standing benefits are applied."""
    engine, actor = ctx.engine, ctx.actor
    held = h.mantle(actor)
    kind = held.data.get('satiety')
    if kind == 'dragon_marrow' and (h.row_of(engine, actor, 'dragon') or {}).get('second_pass') == 1:
        picked = _ask(ctx, 'dragon_sign', ['flood', 'sky', 'scale', 'breath', 'majesty'],
            'Dragon-Marrow Satiety: choose one sign. Sky grants Fly Speed equal to your Speed until the end of your next turn. '
            'Scale makes the first Thick Hide reduction three times your Proficiency Bonus. Breath adds 2d8 of the same type '
            'to one Acid, Cold, Fire, Lightning, Poison or Thunder damage instance from a Hunger or compatible sphere talent. '
            'Flood grants Swim Speed for the Mantle; Majesty grants one qualifying social check Advantage before your next long rest. '
            'The table currently resolves Sky, Scale and Breath.', automatic_options=['sky', 'scale', 'breath'])
        if picked:
            _write(engine, actor, held, dragon_sign=picked[0])
            if picked[0] == 'sky':
                from ..movement_speeds import land_speed_grant
                engine._apply_condition(actor, SKY, DRAGON, actor.entity_id,
                    expires_on=token('end', actor.entity_id, actor.turns_started + 1),
                    data={**land_speed_grant(engine, actor), 'label':'Dragon-Marrow: Sky Sign'})
        purity = _ask(ctx, 'dragon_source', ['ordinary', 'impure'],
            'Was this Dragon-Marrow source corrupted, demonic, unwillingly sacrificed or illegally obtained? '
            'Choose Impure if any applies; that Mantle gains 1 Impurity when it ends.', automatic=False)
        _write(engine, actor, held, dragon_impure=not purity or purity[0] == 'impure')
    if kind == 'demon_king' and (h.row_of(engine, actor, 'demon_king') or {}).get('second_pass') == 1:
        picked = _ask(ctx, 'demon_king_gift', ['resistance', 'attack', 'fear', 'pressure'],
            'Demon-King Satiety: choose Resistance to one strongly expressed damage type until your next turn starts, '
            '2d8 appropriate damage on one successful attack before the Mantle ends, Advantage against Frightened for the Mantle, '
            'or a 30-foot predatory-pressure aura until the end of your next turn. The aura hinders only lower-Realm enemies.',
            automatic_options=['fear', 'pressure'])
        if picked:
            gift = picked[0]
            _write(engine, actor, held, demon_king_gift=gift)
            if gift in ('resistance', 'attack'):
                kinds = (*ELEMENTS, 'necrotic', 'radiant', 'psychic', 'force', 'bludgeoning', 'piercing', 'slashing')
                chosen = _ask(ctx, 'demon_king_type', kinds,
                    'Choose the damage type appropriate to this demon beast. Resistance requires a type it strongly expressed.',
                    automatic=False)
                if chosen:
                    _write(engine, actor, held, demon_king_type=chosen[0])
                    if gift == 'resistance':
                        from ..typed_executor import run_effects
                        run_effects(ctx.with_source(KING), [{'type':'resistance','applies_to':'self',
                            'damage_types':chosen,'expires_on':token('start',actor.entity_id,actor.turns_started+1)}])
            if gift == 'pressure':
                _write(engine, actor, held, pressure_end=actor.turns_started+1)


def end_courses(engine, actor, held):
    """Called exactly once by the Mantle owner on replacement or expiry."""
    from types import SimpleNamespace
    from .end_effect import remove_instance
    if not (held.data.get('dragon_sign') or held.data.get('demon_king_gift')):
        return
    ctx = SimpleNamespace(engine=engine, actor=actor, source=h.MANTLE_ID)
    for kind, store in (('condition', actor.conditions), ('modifier', actor.modifiers)):
        for iid, item in list(store.items()):
            if item.source_actor_id == actor.entity_id and item.source_definition_id in (DRAGON, KING):
                remove_instance(ctx, actor, kind, iid, item)
    if held.data.get('dragon_sign') and held.data.get('dragon_impure'):
        h.change_impurity(engine, actor, 1, DRAGON, 'The impure Dragon-Marrow Mantle ends: gain 1 Impurity.')
    if held.data.get('demon_king_gift'):
        h.change_impurity(engine, actor, 1, KING, 'The Demon-King Mantle ends: gain 1 Impurity.')


def scale_cut(engine, actor, held, ordinary):
    """Called only after Thick Hide qualifies and spends its round allowance."""
    if held.data.get('dragon_sign') != 'scale' or held.data.get('dragon_scale_used'):
        return ordinary
    _write(engine, actor, held, dragon_scale_used=True)
    return 3 * int(held.data.get('pb') or actor.proficiency_bonus)


@hook('save')
def king_fear_save(ctx, subject, ability, named):
    held = h.mantle(subject)
    if held and held.data.get('demon_king_gift') == 'fear' and 'frightened' in named:
        return {'bonus':0, 'modes':['ADVANTAGE']}


@hook('save_mode')
def king_fear_native(engine, subject, ability, dc, source_id, context):
    return 'ADVANTAGE' if king_fear_save(None, subject, ability, (context or {}).get('named', ())) else None


@hook('hit_final')
def king_attack(ctx, target, kind):
    held = h.mantle(ctx.actor)
    if (held is None or held.data.get('demon_king_gift') != 'attack'
            or not held.data.get('demon_king_type') or held.data.get('demon_king_attack_used')):
        return
    choice = _owner_use(ctx, 'demon_king_attack_use',
        f"Use Demon-King Roast Method to add 2d8 {held.data['demon_king_type'].title()} damage to this hit on {target.display_name}?",
        target, 'Demon-King Roast Method')
    if not choice:
        return
    _write(ctx.engine, ctx.actor, held, demon_king_attack_used=True)
    from ..typed_executor import run_effects
    run_effects(ctx.on_hit_context(target, effect_source=KING), [{'type':'damage', 'applies_to':'target',
        'damage_types':[held.data['demon_king_type']], 'dice':{'count':2,'sides':8}}])


@hook('compile_action')
def sphere_damage_provenance(action, info):
    """Freeze sphere provenance for Breath, excluding ordinary weapon actions."""
    if DRAGON not in info['owned_ids']:
        return action
    typed = (action.parameters or {}).get('typed') or {}
    source = typed.get('option_of') or typed.get('source')
    record = info['mechanics'].get(source) or {}
    if record.get('sphere_id'):
        return action.model_copy(update={'parameters':{**action.parameters,
            'typed':{**typed, 'hunger_sphere_damage':True}}})
    return action


@hook('event')
def dragon_damage_and_pressure_consumption(engine, event_type, kwargs):
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor is None:
        return
    if event_type == 'ATTACK_ROLLED':
        from .condition_ownership import remove_instance
        for iid, condition in list(actor.conditions.items()):
            if condition.condition_id == PRESSURE:
                remove_instance(engine, actor, iid, KING)
        return
    # Breath is delivered by the shared deal_bonus seam below, inside the same
    # typed damage packet. Committed events have already lost save/critical context.


@hook('deal_bonus')
def dragon_breath_bonus(ctx, subject, amount):
    """Add Breath inside the originating packet so saves, criticals and defenses apply once."""
    source = ctx.action.source_definition_id
    typed = (getattr(ctx.action, 'parameters', None) or {}).get('typed') or {}
    return _breath_amount(ctx.engine, ctx.actor, subject, ctx.intent, source,
        str(getattr(ctx.engine, '_typed_pending_damage_type', '') or '').lower(), amount,
        ctx.critical_hit, ctx.action, typed)


def _breath_amount(engine, actor, target, intent, source, dtype, amount, critical, action, typed):
    held = h.mantle(actor)
    if (held is None or held.data.get('dragon_sign') != 'breath' or held.data.get('dragon_breath_used')
            or dtype not in ELEMENTS or amount <= 0 or not (source == h.MANTLE_ID or typed.get('hunger_sphere_damage'))):
        return None
    from ..typed_reactions import damage_bonus_eligible
    if not damage_bonus_eligible(engine, target, dtype, source, actor.entity_id):
        return None
    from types import SimpleNamespace
    ctx = SimpleNamespace(engine=engine, actor=actor, target=target, intent=intent, action=action,
                          critical_hit=bool(critical))
    choice = _owner_use(ctx, 'dragon_breath_use',
        f"Use Dragon-Marrow Breath to add 2d8 {dtype.title()} damage from {action.display_name} against {target.display_name}?",
        target, 'Dragon-Marrow Banquet Scripture')
    if not choice:
        return None
    _write(engine, actor, held, dragon_breath_used=True)
    from ..gate2_runtime_models import DiceSpec
    roll = engine.roller.roll(DiceSpec(count=2, sides=8, modifier=0), actor_id=actor.entity_id,
                              reason=f'DAMAGE:{DRAGON}', critical=critical)
    engine._record_roll(roll)
    engine._append_event('DAMAGE_ROLLED', DRAGON, actor_id=actor.entity_id,
        target_ids=(target.entity_id,), payload={**roll.model_dump(mode='json'), 'critical': bool(critical),
                                                  'bonus_component':'dragon_marrow_breath'})
    return int(roll.total)


@hook('confirmed_hit_damage_bonus')
def dragon_breath_confirmed_hit(engine, attacker, target, spec, intent, source, critical):
    if spec.get('damage') is None:
        return None
    action = engine.action_catalog.get(source)
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    if action is None:
        return None
    return _breath_amount(engine, attacker, target, intent, source,
        str(spec.get('damage_type') or '').lower(), 1, critical, action, typed)


def _realm(cl):
    return 0 if cl < 5 else 1 if cl < 10 else 2 if cl < 15 else 3


@hook('turn_start_choice')
def king_pressure_start(engine, target):
    from ..relations import relation, ENEMY
    from .passive_rows import known_level
    from . import ai_controlled
    from ..target_knowledge import can_see
    from ..targeting import line_of_effect
    for actor in engine.state.actors.values():
        held = h.mantle(actor)
        if (held is None or held.data.get('demon_king_gift') != 'pressure'
                or not held.data.get('pressure_end')
                or actor.turns_started > int(held.data['pressure_end'])
                or relation(engine, actor, target) != ENEMY
                or engine._distance_actor_to_actor(actor,target) > 30
                or not line_of_effect(engine, actor, target=target)):
            continue
        cl, tcl = known_level(engine, actor), known_level(engine, target)
        if cl is None or tcl is None or _realm(tcl) >= _realm(cl):
            continue
        if ai_controlled(engine, actor) and not can_see(engine, actor, target):
            continue
        dc = h.hunger_save_dc(engine, actor)
        roll = engine._roll_save(target, 'WIS', dc, KING)
        if roll is not None and roll.total < dc:
            engine._apply_condition(target, PRESSURE, KING, actor.entity_id,
                expires_on=token('start',target.entity_id,target.turns_started+1),
                data={'label':'Demon-King pressure: Disadvantage on your next attack'})


@hook('attack_mode')
def pressure_attack_mode(ctx, target):
    if any(c.condition_id == PRESSURE for c in ctx.actor.conditions.values()):
        return 'DISADVANTAGE'


@hook('turn_end')
def pressure_expires(engine, actor):
    held = h.mantle(actor)
    if held and held.data.get('pressure_end') == actor.turns_started:
        _write(engine, actor, held, pressure_end=0)


@hook('compile_block')
def scholar_row(block, spec, row, numbers):
    if block == 'hunger_scholar':
        return [{**row, 'kind':'scholar'}]


@hook('check_bonus')
def monster_taste_bonus(ctx, actor):
    from .passive_rows import row_of
    if (row_of(ctx.engine, actor.entity_id, 'hunger_scholar', 'scholar') is None
            or actor is not ctx.actor or str(ctx.typed.get('source') or '') != 'HUNGER_BASE_TASTE_THE_QI'):
        return None
    target = ctx.target or (ctx.targets[0] if len(ctx.targets) == 1 else None)
    if target is None:
        return None
    # A declaration avoids reading secret creature labels from a sealed roster.
    cached = ctx.damage_cache
    if 'hunger_scholar_source' not in cached:
        from . import ai_controlled
        from ..target_knowledge import can_see
        automatic_options = ['qualifying', 'other']
        if ai_controlled(ctx.engine, ctx.actor) and not can_see(ctx.engine, ctx.actor, target):
            automatic_options = ['other']
        picked = _ask(ctx, 'scholar_source', ['qualifying','other'],
            f"Monster-Taste Scholar: is {target.display_name} a beast, monstrosity, dragon, demon beast or strange corpse? "
            f"Declare what you know about the creature for {ctx.action.display_name}; qualifying grants +1 to your Hunger Check.",
            automatic=False, automatic_options=automatic_options, target=target,
            name='Monster-Taste Scholar', feature_id='Monster-Taste Scholar')
        cached['hunger_scholar_source'] = bool(picked and picked[0] == 'qualifying')
    return int(cached['hunger_scholar_source'])

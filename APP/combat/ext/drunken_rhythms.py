"""Post-save Drunken Style choices; all effects are opt-in reviewed rows.

Uses the existing at-hit mark snapshot, strict choice transport, condition
expiry, native forced movement and mode-removal hooks. Legacy rows retain
legacy behavior. No new engine seam or saved-state schema is required.
"""
from . import effect, hook

BEAT = 'condition:typed.drunken_missing_beat'
DEADLINE = 'START_OF_SOURCE_NEXT_TURN'


@effect('drunken_missing_beat')
def missing_beat(ctx, row):
    from .rider_choices import pick
    from .choice_prompt import action_context
    from .condition_ownership import remove_instance
    target = ctx.target
    if target is None or not target.active:
        return
    options = ['reaction', 'bonus', 'advantage', 'opportunity'] if row.get('failed') else ['opportunity']
    labels = {'reaction': 'Lose Reactions until the start of my next turn',
              'bonus': 'Lose the Bonus Action on your next turn, until the start of my next turn',
              'advantage': 'Cannot benefit from Advantage on attack rolls until the start of my next turn',
              'opportunity': 'Cannot make Opportunity Attacks until the start of my next turn; other Reactions remain available'}
    labels = {key: text.replace('my next turn', f"{ctx.actor.display_name}'s next turn").replace('your next turn', f"{target.display_name}'s next turn") for key, text in labels.items()}
    chosen = pick(ctx.engine, ctx.actor, 'drunken_missing_beat', 'Palm of the Missing Beat', options,
                  subject=target, labels=labels, optional=False, preferred=['reaction'] if row.get('failed') else options,
                  trigger=f'{ctx.action.display_name}: the Wisdom save ' + ('failed' if row.get('failed') else 'succeeded'),
                  prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, target, action=ctx.action))[0]
    for held in list(target.conditions.values()):
        if held.condition_id == BEAT and held.source_actor_id == ctx.actor.entity_id:
            remove_instance(ctx.engine, target, held.instance_id, ctx.source)
    ctx.engine._apply_condition(target, BEAT, ctx.source, ctx.actor.entity_id, expires_on=DEADLINE,
        data={'beat': chosen, 'bonus_turn': target.turns_started + 1, 'rule': {'no_reactions': True} if chosen == 'reaction' else {},
              'label': f'Palm of the Missing Beat: {labels[chosen]}'})


@hook('candidate_allowed')
def missing_bonus(engine, actor, candidate, action):
    if action is not None and str(getattr(action.economy, 'value', action.economy)) == 'BONUS_ACTION' \
            and any(c.condition_id == BEAT and c.data.get('beat') == 'bonus' and actor.turns_started == c.data.get('bonus_turn') for c in actor.conditions.values()):
        return False


@hook('attack_mode_removed')
def missing_advantage(engine, attacker, target, ranged):
    if any(c.condition_id == BEAT and c.data.get('beat') == 'advantage' for c in attacker.conditions.values()):
        return ['ADVANTAGE']


@hook('opportunity_allowed')
def missing_opportunity(engine, reactor, mover):
    if any(c.condition_id == BEAT and c.data.get('beat') == 'opportunity' for c in reactor.conditions.values()):
        return False


@effect('drunken_slipping_palm')
def slipping_palm(ctx, row):
    from .rider_choices import pick, step
    from .choice_prompt import action_context
    from .effective_size import steps
    from ..dynamic_size import CATEGORIES, current_category
    from ..typed_executor import run_effects
    target = ctx.target
    if target is None or not target.active:
        return
    options = ['step']
    if row.get('failed'):
        options.insert(0, 'push')
        purposes = {'prone', 'shove'}
        target_size = CATEGORIES.index(current_category(ctx.engine, target)) + steps(ctx.engine, target, 'resist', purposes)
        owner_size = CATEGORIES.index(current_category(ctx.engine, ctx.actor)) + steps(ctx.engine, ctx.actor, 'act', purposes)
        if target_size <= owner_size + 1:
            options.append('prone')
    labels = {'push': 'Push the target 5 feet away', 'prone': 'Knock the target Prone',
              'step': 'Move yourself up to 5 feet; this target cannot make an Opportunity Attack during the move'}
    chosen = pick(ctx.engine, ctx.actor, 'drunken_slipping_palm', 'Slipping Palm', options,
                  subject=target, labels=labels, optional=False, preferred=['step'],
                  trigger=f'{ctx.action.display_name}: the Dexterity save ' + ('failed' if row.get('failed') else 'succeeded'),
                  prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, target, action=ctx.action))[0]
    if chosen == 'step':
        step(ctx.engine, ctx.actor, 'drunken_slipping_step', 'Slipping Palm', target, 5, ctx.source,
             ctx.intent, ignored_oa=[target.entity_id],
             trigger=f'{ctx.action.display_name} hits {target.display_name}',
             prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, target, action=ctx.action))
    else:
        run_effects(ctx, [{'type': 'forced_movement', 'applies_to': 'target', 'distance_ft': 5, 'direction': 'away'}]
                    if chosen == 'push' else [{'type': 'condition', 'applies_to': 'target', 'condition': 'prone'}])


@hook('effect_allowed')
def rhythm_eligible(ctx, row):
    if row.get('type') == 'drunken_rhythm_gate':
        snapshot = ctx.damage_cache.get('_marks_at_hit', {}).get(getattr(ctx.target, 'entity_id', ''), {})
        from .trigger_occurrence import current_strike
        frame = current_strike(ctx.engine) or {}
        if snapshot.get('_drunken_used') or frame.get('scratch', {}).get('drunken_style_attack_talent'):
            return False
        if row.get('melee_only'):
            from ..typed_executor import ranged_attack_now
            if ranged_attack_now(ctx) or not (ctx.typed.get('weapon') or (ctx.attack_effect or {}).get('attack_kind') == 'unarmed'):
                return False
        return bool(ctx.target and ctx.damage_cache.get('_marks_at_hit', {}).get(ctx.target.entity_id, {}).get('Off-Rhythm'))


@effect('drunken_rhythm_gate')
def rhythm_gate(ctx, row):
    from ..typed_executor import run_effects
    from .rider_choices import pick
    if not rhythm_eligible(ctx, row):
        return
    focus = 'resource:core.martial_focus'
    if row.get('focus') and ctx.actor.resources.get(focus, 0) < 1:
        return
    if row.get('optional'):
        from .choice_prompt import action_context
        context = action_context(ctx.engine, ctx.actor, ctx.source, ctx.target, action=ctx.action)
        context['cost'] = 'Expend Martial Focus; no Action or Reaction' if row.get('focus') else 'No Action, Reaction or resource cost'
        save = next((e for e in row.get('effects') or [] if e.get('type') == 'save'), {})
        ability = {'wis': 'Wisdom', 'dex': 'Dexterity'}.get(str(save.get('ability') or '').lower(), str(save.get('ability') or '').title())
        choice = pick(ctx.engine, ctx.actor, row['use_key'], row['name'], ['use'], subject=ctx.target,
                      labels={'use': f'Force a {ability} saving throw' if save else 'Move the target 5 feet to a supported, unoccupied space without Opportunity Attacks'},
                      trigger=f'{ctx.action.display_name} hits a creature already Off-Rhythm from you',
                      prompt_context=context)
        if not choice:
            return
    ctx.damage_cache['_marks_at_hit'][ctx.target.entity_id]['_drunken_used'] = True
    if row.get('focus'):
        ctx.engine._spend_resource(ctx.actor, focus, 1, ctx.source)
    run_effects(ctx, row.get('effects') or [])


@effect('drunken_borrowed_momentum')
def borrowed_momentum(ctx, row):
    from ..typed_executor import ranged_attack_now
    from ..falling import supported
    from .forced_destination import routes, ask
    from .rider_choices import step
    from .choice_prompt import action_context
    from .needle import CHOICE, checkpoint_id
    if ctx.target is None or not ctx.target.active or ranged_attack_now(ctx):
        return
    cells = routes(ctx.engine, ctx.target, 5, want=lambda cell: supported(ctx.engine, ctx.target, cell))
    picked = None
    before = ctx.target.position
    if cells:
        picked = ask(ctx.engine, ctx.intent, ctx.actor, ctx.target, cells, source=ctx.source,
            checkpoint=checkpoint_id(ctx.engine, 'drunken_borrowed_momentum', ctx.actor.entity_id, ctx.target.entity_id),
            choice_id=CHOICE+'drunken_borrowed_momentum', name='Borrowed Momentum', target_id=ctx.target.entity_id,
            prompt=f'Borrowed Momentum after {ctx.action.display_name} hits: move {ctx.target.display_name} 5 feet to a supported, unoccupied space. No Opportunity Attacks.',
            ctx=ctx, allow_decline=True,
            prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, ctx.target, action=ctx.action))
    if not cells or (picked and ctx.target.position == before):
        step(ctx.engine, ctx.actor, 'drunken_borrowed_step', 'Borrowed Momentum', ctx.target, 5, ctx.source,
             ctx.intent, ignored_oa=[ctx.target.entity_id],
             trigger=f'{ctx.action.display_name}: the target cannot be moved to a supported space',
             prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, ctx.target, action=ctx.action))


@hook('effect_description')
def rhythm_description(row):
    if row.get('type') == 'drunken_rhythm_gate':
        cost = 'Expend Martial Focus on a qualifying hit. ' if row.get('focus') else ''
        return cost + 'Requires a creature already Off-Rhythm from you before the hit. You may decline. Choose the outcome after the save, or choose a legal movement destination.'

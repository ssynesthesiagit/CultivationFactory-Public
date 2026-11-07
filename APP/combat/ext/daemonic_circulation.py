"""Devil-Qi Circulation: an owned, Seed-gated choice retained for the scene.

Shared public helper selected(ctx) identifies an eligible selected type; the
Daemonic riders consumer uses it to avoid reopening an already-finalized menu.
"""
from . import effect, hook

FEATURE = 'insight.devil-qi-circulation'
SEED = 'condition:typed.stance.demon_seed'
STATE = 'condition:typed.devil_qi_circulation'
ESSENCE = 'resource:named.devoured_essence'
KINDS = ('necrotic', 'psychic', 'poison', 'fire', 'acid', 'force')


@hook('compile_block')
def compile_circulation(block, spec, row, numbers):
    if block == 'devil_qi_circulation':
        return [{**row, 'cl': int(numbers.get('cl') or 1),
                 'player_outcome': 'While Demon Seed is active, choose an optional damage type for your Daemonic talents. Once this scene, gain 1 Devoured Essence when a creature fails a save against a Daemonic talent using that type.'}]
    return None


@hook('compile_actions')
def choices(info):
    if FEATURE not in info['owned_ids'] or int(info['numbers'].get('cl') or 1) < 4:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.devil_qi_circulation.{kind}",
        display_name=f'Devil-Qi Circulation: {kind.title()}', owner_id=info['actor_id'],
        economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
        parameters={'setting_only': True, 'requires_condition': SEED,
                    'typed': {'source': FEATURE, 'numbers': info['numbers'], 'riders': [],
                              'effects': [{'type': 'devil_qi_circulation', 'kind': kind}]}})
        for kind in KINDS]


@effect('devil_qi_circulation')
def choose(ctx, spec):
    if spec['kind'] not in KINDS or not any(c.condition_id == SEED for c in ctx.actor.conditions.values()):
        return
    ctx.engine._remove_condition(ctx.actor, STATE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, STATE, ctx.source, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
                                data={'kind': spec['kind'], 'label': f"Devil-Qi Circulation: {spec['kind'].title()} for this scene"})


def selected(ctx):
    """Return the scene type only for an eligible Daemonic source, else None."""
    source = ctx.typed.get('source') or ctx.typed.get('option_of') or ''
    action = ctx.engine.action_catalog.get(source)
    if action is not None:
        typed = action.parameters.get('typed') or {}
        source = typed.get('source') or typed.get('option_of') or ''
    if not (source.startswith('TAL_DAEMONIC_CULTIVATION_') or source.startswith('tianxia.talent.daemonic_cultivation.')):
        return None
    return next((c.data['kind'] for c in ctx.actor.conditions.values() if c.condition_id == STATE), None)


def grant_reward(ctx, kind):
    if (ctx.failed_save is not True or str(kind).lower() != selected(ctx)
            or ctx.actor.turn_flags.get('_round_devil_qi_reward')):
        return
    ctx.actor.turn_flags['_round_devil_qi_reward'] = True
    ctx.engine._gain_resource(ctx.actor, ESSENCE, 1, FEATURE)


@hook('damage_type_override')
def circulation_damage(ctx, kinds, targets):
    kind = selected(ctx) if kinds and targets else None
    if not kind:
        return None
    from . import needle
    options = list(dict.fromkeys([kind, *[str(k).lower() for k in kinds]]))
    picks = needle.ask(ctx.engine, ctx.intent,
                       needle.checkpoint_id(ctx.engine, 'devil_qi_damage', ctx.source,
                                            *[t.entity_id for t in targets]), ctx.actor,
                       needle.CHOICE + 'devil_qi_damage', options,
                       labels={k:k.title() for k in options}, preferred=[kind],
                       target_id=targets[0].entity_id, name='Devil-Qi Circulation', feature_id=FEATURE,
                       prompt=f"{ctx.action.display_name}: choose the damage type against "
                              f"{', '.join(t.display_name for t in targets)}. "
                              f"Devil-Qi Circulation adds {kind.title()} as an option at no extra cost.")
    chosen = (picks or [kind])[0]
    # A deferred damaging consequence may choose its type while the selecting
    # failed save is still in this context, before any damage die is needed.
    grant_reward(ctx, chosen)
    return chosen


@hook('damage_roll_resolved')
def circulation_cached_reward(ctx, effect, cache_key):
    cached = ctx.damage_cache.get(cache_key)
    if isinstance(cached, tuple) and len(cached) == 2:
        # Area rolls can be prepared on a successful save and reused by a later
        # failed save. Check every retrieval, including fully resisted damage.
        grant_reward(ctx, cached[1])


@effect('devil_qi_circulation_marker')
def marker(ctx, spec):
    pass


@hook('technique_start')
def initial_choice(engine, actor, action):
    """Choose before the first eligible talent; AI also acquires its setting."""
    from types import SimpleNamespace
    from . import needle
    typed = action.parameters.get('typed') or {}
    probe = SimpleNamespace(typed=typed, actor=actor, engine=engine)
    if action.parameters.get('setting_only') or selected(probe) is not None:
        return
    source = typed.get('source') or typed.get('option_of') or ''
    if not (source.startswith('TAL_DAEMONIC_CULTIVATION_') or source.startswith('tianxia.talent.daemonic_cultivation.')):
        return
    if not any(c.condition_id == SEED for c in actor.conditions.values()):
        return
    if not any(r.get('block') == 'devil_qi_circulation' and int(r.get('cl') or 1) >= 4
               for r in engine.typed_passive_rows.get(actor.entity_id, ())):
        return
    intent = getattr(engine, '_active_intent', None)
    targets = [engine.state.actors[tid] for tid in getattr(intent, 'target_ids', ())
               if tid in engine.state.actors]
    subject = targets[0] if targets else actor
    from .choice_prompt import action_context
    picks = needle.ask(engine, intent,
                       needle.checkpoint_id(engine, 'devil_qi_circulation', actor.entity_id), actor,
                       needle.CHOICE + 'devil_qi_circulation', list(KINDS),
                       labels={k:k.title() for k in KINDS}, preferred=['necrotic'],
                       name='Devil-Qi Circulation', feature_id=FEATURE,
                       target_id=subject.entity_id,
                       prompt_context=action_context(engine, actor, action.source_definition_id, subject),
                       prompt=f'{action.display_name} affecting {", ".join(t.display_name for t in targets) or actor.display_name}: '
                              'Devil-Qi Circulation lets you choose the damage type for your Daemonic talents this scene. '
                              'This setting costs no extra action or resource.')
    if picks:
        choose(SimpleNamespace(engine=engine, actor=actor, source=FEATURE), {'kind':picks[0]})

"""Zephyr's Step: one finite grant, with passage owed by committed willing steps.

Uses compile_action, technique_used, pass_through, difficult_exempt,
support_surface, opportunity_allowed and movement_step_settled. Native motion
owns budgets, collisions and occupied endpoints. The printed difficult passage
permission composes with the same activation's explicit ignore-difficult rule;
creature_passage applies that exemption without weakening other grants.
No sibling ownership or capstone activation is inferred here. Generic committed
cost/action modifiers remain the native activation pipeline's responsibility.
"""
from copy import deepcopy
from . import hook

FEATURE = 'tianxia.subpath.qi.storm_soul_cultivator.feature.zephyr_s_step'
CONDITION = 'condition:typed.storm_soul_zephyr_s_step_flight'
CHOICE = 'choice:needle.zephyr.'


@hook('compile_action')
def compile_step(action, info):
    original = action.parameters.get('typed') or {}
    if original.get('source') != FEATURE or FEATURE not in info['owned_ids']:
        return None
    source = (info['mechanics'].get(FEATURE) or {}).get('source') or {}
    if source.get('file_sha256') != 'ca25b88915a2d83324a23feed94a54409d359369dbd0452fb29d28b938262584':
        return None
    typed = deepcopy(original)
    typed['min_cl'] = max(14, int(typed.get('min_cl') or 0))
    typed['riders'] = []
    # This is a self grant. Thunderhead's save is delivered only after movement.
    typed['effects'] = [{'type': 'condition', 'condition': CONDITION.removeprefix('condition:typed.'),
        'applies_to': 'self', 'expires_on': 'START_OF_SOURCE_NEXT_TURN',
        'condition_data': {'fly_speed_ft': 50, 'flight_hover': 1,
            'zephyr_active': 1, 'seen': [], 'affected': [],
            'numbers': dict(typed.get('numbers') or info['numbers']),
            'action_id': action.source_definition_id,
            'rule': {'ignore_difficult': True},
            'label': "Zephyr’s Step: Fly 50 feet, Hover, no Opportunity Attacks; ends at your next turn"}}]
    typed['manual_inline_choice'] = True
    return action.model_copy(update={'target_kind': 'SELF', 'range_ft': 0,
        'parameters': {**action.parameters, 'typed': typed,
            'description': 'Bonus Action, 3 Qi. Until your next turn: Fly 50 feet, Hover, ignore difficult terrain, '
                'cross liquids, open air and creature spaces without Opportunity Attacks. End in a free space. '
                'Thunderhead Passage: first approach within 5 feet; up to your Proficiency Bonus in distinct hostiles, '
                'Dexterity save, 3d8 Lightning or Thunder, half on success; failure prevents Reactions until its next turn.'}})


def active(actor):
    return next((c for c in reversed(list(actor.conditions.values())) if c.condition_id == CONDITION
        and c.source_actor_id == actor.entity_id and c.source_definition_id.endswith(FEATURE)
        and c.data.get('zephyr_active') == 1 and not c.data.get('suppressed')), None)


@hook('technique_used')
def activated(ctx):
    if ctx.typed.get('source') != FEATURE:
        return
    grants = [c for c in ctx.actor.conditions.values() if c.condition_id == CONDITION
        and c.source_actor_id == ctx.actor.entity_id and c.source_definition_id == ctx.source]
    for old in grants[:-1]:
        ctx.engine._remove_condition_instance(ctx.actor, old.instance_id, FEATURE)


@hook('pass_through')
def passage(engine, mover, occupant):
    return 'difficult' if active(mover) else None


@hook('opportunity_allowed')
def no_opportunity(engine, reactor, mover):
    return False if active(mover) else None


@hook('difficult_exempt')
def terrain(engine, actor):
    if active(actor):
        return {(x, y) for x in range(engine.grid.width) for y in range(engine.grid.height)}
    return None


@hook('support_surface')
def support(engine, actor, position):
    return True if active(actor) else None


@hook('movement_step_settled')
def thunderhead(engine, mover, previous, nxt, intent):
    from .. import typed_executor as te
    from ..movement_steps import context
    from ..relations import relation, ENEMY
    from ..target_knowledge import located
    from .needle import ask, checkpoint_id
    c = active(mover)
    if c is None or not context(engine, mover) or previous == nxt:
        return
    seen = list(c.data['seen'])
    first = [a for a in engine.state.actors.values() if a.active and a.entity_id != mover.entity_id
        and a.entity_id not in seen and relation(engine, mover, a) == ENEMY
        and engine._distance_actor_to_actor(mover, a) <= 5]
    if not first:
        return
    affected = list(c.data['affected'])
    remaining = max(0, int(c.data['numbers'].get('pb') or 0) - len(affected))
    chosen = []
    if remaining:
        ids = [a.entity_id for a in first]
        known = [a.entity_id for a in first if located(engine, mover, a)]
        chosen = ask(engine, intent, checkpoint_id(engine, 'zephyr_targets', c.instance_id), mover,
            CHOICE+'targets', ids, labels={a.entity_id: a.display_name if a.entity_id in known else 'Unseen hostile creature' for a in first},
            minimum=0, maximum=min(remaining, len(ids)), allow_decline=True,
            # Perception orders preferences, never printed proximity eligibility.
            default_count=min(remaining, len(ids)), preferred=known,
            name='Thunderhead Passage', feature_id=FEATURE,
            prompt=f'Thunderhead Passage: choose up to {remaining} creatures first approached within 5 feet. '
                'Each makes a Dexterity save against 3d8 Lightning or Thunder; half on success. '
                'A failure also prevents Reactions until its next turn. No additional Qi or action.')
    # A declined first approach is still the first approach; re-entry never retries it.
    engine._update_condition_data(mover, c, {**c.data,
        'seen': [*seen, *[a.entity_id for a in first]], 'affected': [*affected, *chosen]}, FEATURE)
    action = engine.action_catalog[c.data['action_id']]
    for aid in chosen:
        target = engine.state.actors[aid]
        target_known = located(engine, mover, target)
        target_name = target.display_name if target_known else 'Unseen hostile creature'
        kind = ask(engine, intent, checkpoint_id(engine, 'zephyr_damage', c.instance_id, aid), mover,
            CHOICE+'damage', ['LIGHTNING', 'THUNDER'], labels={'LIGHTNING': 'Lightning', 'THUNDER': 'Thunder'},
            # target_id also supplies presentation metadata; omit the hidden
            # identity there as well as in the prompt. Resolution still uses aid.
            name='Thunderhead Passage damage', feature_id=FEATURE, target_id=aid if target_known else None,
            prompt=f'Thunderhead Passage against {target_name}: choose Lightning or Thunder damage.')[0]
        damage = {'type': 'damage', 'applies_to': 'target', 'dice': {'count': 3, 'sides': 8},
            'damage_types': [kind], 'duration': 'instant'}
        save = {'type': 'save', 'applies_to': 'target', 'ability': 'dex', 'dc': 'technique_save_dc',
            'on_fail': [damage, {'type': 'reaction_denied', 'applies_to': 'target',
                'expires_on': 'START_OF_TARGET_NEXT_TURN'}],
            'on_success': [{'type': 'half_damage', 'applies_to': 'target'}]}
        typed = {'source': FEATURE, 'numbers': dict(c.data['numbers']), 'effects': [save], 'riders': []}
        te.run_effects(te.Context(engine, mover, action, intent, typed, [target], target,
            save_geometry={'origin_ids': [mover.entity_id], 'range_ft': 5},
            effect_resolution='delayed'), [save])

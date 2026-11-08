"""Hidden-Thunder's paid Duel Target declaration.

The source-owned condition records one target and a native one-minute round clock.
No item, ownership, perception, or Stored Thunder receipt is manufactured here.
This module does not implement the source's counter/severance procedures.
"""
from . import effect, hook
from ..gate2_runtime_models import EconomyKind
from ..action_geometry import distance

SOURCE = 'tianxia.subpath.qi.hidden_thunder_draw_saber_cultivator.feature.one_breath_duel'
DUEL = 'condition:typed.hidden_thunder_duel'
BLOCK = 'hidden_thunder_duel'


@hook('compile_passives')
def ownership(rows, info):
    if SOURCE not in info['owned_ids'] or int(info['numbers'].get('cl') or 1) < 10:
        return rows
    return [*rows, {'block': BLOCK, 'feature_id': SOURCE, 'numbers': dict(info['numbers'])}]


def owns_duel(engine, actor):
    """Read the exact compiled source ownership and CL gate; no implied grants."""
    return any(row.get('block') == BLOCK and row.get('feature_id') == SOURCE
               and int((row.get('numbers') or {}).get('cl') or 1) >= 10
               for row in (getattr(engine, 'typed_passive_rows', {}) or {}).get(actor.entity_id, []))


@hook('compile_action')
def compile_duel(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    if typed.get('source') != SOURCE or SOURCE not in info['owned_ids']:
        return None
    # Replace the extraction's immediate resource gain and blanket Disadvantage.
    # Neither is a printed effect of declaring the duel. The unimplemented
    # counter/tracking clauses remain visible in the existing source riders.
    return action.model_copy(update={'economy': EconomyKind.BONUS_ACTION,
        'target_kind': 'ANY_CREATURE', 'range_ft': 60, 'reach_ft': None,
        'costs': (('resource:core.qi', 4),),
        'parameters': {**action.parameters,
            'description': 'Choose one creature you can perceive within 60 feet as your Duel Target for 1 minute. Costs a Bonus Action and 4 Qi; replaces your previous Duel Target.',
            'typed': {**typed, 'min_cl': 10,
            'range_ft': 60, 'area': None, 'requires_sight': False,
            'requires_perception': True,
            'effects': [{'type': 'hidden_thunder_duel', 'evidence': 'Choose one creature you can perceive within 60 feet as your one Duel Target for 1 minute; a Bonus Action and 4 Qi.'}]}}})


@hook('candidate_allowed')
def perceived_duel(engine, actor, candidate, action):
    typed = (action.parameters or {}).get('typed') or {} if action is not None else {}
    if not any(e.get('type') == 'hidden_thunder_duel' for e in typed.get('effects') or []):
        return None
    if not owns_duel(engine, actor):
        return False
    from ..target_knowledge import located
    return len(candidate.target_ids) == 1 and all(
        (target := engine.state.actors.get(tid)) is not None
        and distance(engine, actor, target) <= 60
        and located(engine, actor, target) for tid in candidate.target_ids)


@effect('hidden_thunder_duel', harmful=False)
def declare_duel(ctx, row):
    from ..target_knowledge import located
    target = ctx.target
    if (ctx.typed.get('source') != SOURCE or not owns_duel(ctx.engine, ctx.actor)
            or target is None or int(ctx.numbers.get('cl') or 1) < 10
            or distance(ctx.engine, ctx.actor, target) > 60
            or not located(ctx.engine, ctx.actor, target)):
        raise ValueError('One-Breath Duel needs one creature you can perceive within 60 feet at cultivation level 10 or higher.')
    ctx.engine._remove_condition(ctx.actor, DUEL, ctx.source)
    ctx.engine._apply_condition(ctx.actor, DUEL, ctx.source, ctx.actor.entity_id,
        expires_on=ctx.expires_on(),
        data={'target_id': target.entity_id,
              'label': 'One-Breath Duel: your selected creature is your Duel Target for 1 minute'})


@hook('status_description')
def describe_duel(engine, holder, row, data):
    condition_id = row.get('condition_id') if isinstance(row, dict) else getattr(row, 'condition_id', None)
    if condition_id != DUEL:
        return None
    from ..information_results import creature_name
    target_name = creature_name(engine, holder, data.get('target_id'))
    return {'display_name': f'One-Breath Duel: {target_name}',
            'rules': f'{target_name} is your one Duel Target. Declaring the duel costs a Bonus Action and 4 Qi.',
            'duration': '1 minute; declaring another duel replaces this target'}

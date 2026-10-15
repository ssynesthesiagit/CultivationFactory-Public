"""Native physical-grapple choice and capacity consumers.

Newly compiled escape actions opt in to independent hold selection and their
already sealed Athletics/Acrobatics choices. Existing saved catalogs keep
their old selectors. Magical restraints retain their source-specific paths.
"""
from copy import deepcopy
from . import hook


@hook('compile_action', priority=100)
def seal(action, info):
    typed = action.parameters.get('typed') or {}
    kinds = {e.get('type') for e in typed.get('effects', ())}
    physical = typed.get('unarmed_option') == 'grapple' or typed.get('physical_grapple') is True
    if not kinds.intersection({'escape_grapple', 'release_grapple'}) and not physical:
        return action
    params = deepcopy(action.parameters)
    if kinds.intersection({'escape_grapple', 'release_grapple'}):
        params['typed']['physical_escape_contract' if 'escape_grapple' in kinds else 'physical_release_contract'] = 1
    if physical:
        params['typed'].update(native_grapple_steps=1, physical_part_choice=1)
    return action.model_copy(update={'parameters': params})


@hook('escape_grips_fallback')
def choose_hold(ctx, grips):
    from .hand_occupancy import physical_row
    if not ctx.typed.get('physical_escape_contract') or not grips or not all(
            physical_row(ctx.engine, grip) for grip in grips.values()):
        return None
    from .needle import ask, CHOICE, checkpoint_id
    ids = list(grips)
    labels = {iid: 'Grapple held by ' + ctx.engine.state.actors[grip.source_actor_id].display_name
              for iid, grip in grips.items()}
    if len(ids) == 1:
        return ids
    return ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'escape_hold', ctx.actor.entity_id),
        ctx.actor, CHOICE + 'escape_hold', ids, labels=labels,
        name='Escape one grapple', prompt='Choose the grapple this Action attempts to end.',
        preferred=sorted(ids, key=lambda iid: int(grips[iid].data.get('escape_dc', 10))))


@hook('release_grips_fallback')
def release_holds(ctx, grips):
    if not ctx.typed.get('physical_release_contract'):
        return None
    from .needle import ask, CHOICE, checkpoint_id
    if len(grips) <= 1:
        return list(grips)
    return ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'release_grips', ctx.actor.entity_id),
        ctx.actor, CHOICE + 'release_grips', list(grips),
        labels={iid: 'Release ' + ctx.engine.state.actors[row.target_id].display_name + ' ('
                + str(row.data.get('grappling_part', 'hold')).replace(':', ' ') + ')' for iid,row in grips.items()},
        minimum=0, maximum=len(grips), allow_decline=True, default='all',
        name='Release your grapples', prompt='Choose which of your grapples to release. Releasing costs no Action or resource.')


@hook('escape_check_choice_required')
def choose_skill(ctx, effect, dc, grips, hazards):
    if ctx.typed.get('physical_escape_contract') and grips:
        from .hand_occupancy import physical_row
        if all(physical_row(ctx.engine, grip) for grip in grips):
            return {'name': 'Escape grapple', 'feature_id': 'WRESTLING_BASE_GRAPPLING_REMINDER'}


@hook('candidate_allowed')
def size_gate(engine, actor, candidate, action):
    if action is None:
        return None
    typed = action.parameters.get('typed') or {}
    if typed.get('unarmed_option') not in {'grapple', 'shove_push', 'shove_prone'}:
        return None
    from ..typed_executor import Context, size_rank
    ctx = Context(engine, actor, action, None, typed, [], None, {})
    effect = next((r for r in typed.get('effects', ()) if r.get('type') == 'save'), {})
    return all(size_rank(ctx, engine.state.actors[tid], 'subject', effect) <=
               size_rank(ctx, actor, 'actor', effect) + int(effect.get('max_size_larger', 1))
               for tid in candidate.target_ids)


def parts_available(engine, actor, action):
    """Pure public use gate for declared hand/weapon/named-limb actions.

    Owning providers declare uses_body_parts, never guessed anatomy. A source
    must explicitly set shares_grappling_parts to allow concurrent use.
    """
    parts = action.parameters.get('uses_body_parts')
    if parts is None or action.parameters.get('shares_grappling_parts') is True:
        return None
    if not isinstance(parts, (list, tuple)) or any(not isinstance(p, str) or not p for p in parts):
        raise ValueError('uses_body_parts requires explicit part IDs')
    from .hand_occupancy import physical_holds, reserved_parts
    busy = {p for _, hold in physical_holds(engine, actor) for p in reserved_parts(hold)}
    return not busy.intersection(parts)


@hook('candidate_allowed')
def use_parts(engine, actor, candidate, action):
    return parts_available(engine, actor, action) if action else None


@hook('attack_allowed')
def strike_parts(ctx, target, effect):
    return parts_available(ctx.engine, ctx.actor, ctx.action)

"""Native physical-grapple choice and capacity consumers.

Newly compiled escape actions opt in to independent hold selection and their
already sealed Athletics/Acrobatics choices. Existing saved catalogs keep
their old selectors. Magical restraints retain their source-specific paths.
"""
from copy import deepcopy
from . import hook


@hook('compile_action')
def seal(action, info):
    typed = action.parameters.get('typed') or {}
    if not any(e.get('type') == 'escape_grapple' for e in typed.get('effects', ())):
        return action
    params = deepcopy(action.parameters)
    params['typed']['physical_escape_contract'] = 1
    return action.model_copy(update={'parameters': params})


@hook('escape_grips')
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

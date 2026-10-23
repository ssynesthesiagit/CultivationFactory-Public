"""Opt-in physical sonic delivery; shared by reviewed audible shockwaves.

The sound_transmission descriptor declares only source-authorized media.
No ability ID dispatch, inferred resonance, alternate origin or hearing gate.
"""
from . import effect, hook


@effect('sound_transmission')
def descriptor(ctx, row):
    # Admission already settled this descriptor before target reactions.
    pass


@hook('technique_declared')
def establish_medium(engine, actor, action, candidate, intent):
    """Owner/Ask fact confirmation uses the existing pre-payment declaration.

    Unknown/decline cancels without payment. This also lets native sequential
    choice discovery reach a complete, harmless preview while collecting the
    actual square and fact prompts; it cannot manufacture an air answer.
    """
    from .. import sound_transmission
    from ..typed_executor import Context
    typed = (action.parameters or {}).get('typed') or {}
    if not any(row.get('type') == 'sound_transmission' for row in typed.get('effects') or []):
        return None
    ctx = Context(engine, actor, action, intent, typed, [], None)
    if not sound_transmission.confirm_medium(ctx):
        return {'source_id': ctx.source, 'cancel': True,
                'label': f'{action.display_name} cancelled: the battlefield sound medium is not established. '
                         'No action or resources are spent.'}
    return None


@hook('before_target_reactions')
def recipients(ctx):
    from .. import sound_transmission
    rows = [row for row in ctx.typed.get('effects') or [] if row.get('type') == 'sound_transmission']
    if not rows:
        return
    if len(rows) != 1 or rows[0].get('medium') != 'air':
        raise ValueError('Physical sound delivery currently supports only an explicitly authorized audible air medium.')
    from .activation_requirements import effective_cl
    ctx.numbers['cl'] = effective_cl(ctx.actor, ctx.numbers.get('source_cl', ctx.numbers.get('cl') or 1))
    # Even an empty cone must validate the ambient medium before objects run.
    sound_transmission.reaches(ctx, ctx.actor)
    ctx.targets = [target for target in ctx.targets if sound_transmission.reaches(ctx, target)]
    ctx.target = ctx.targets[0] if len(ctx.targets) == 1 else None
    ctx.engine._append_event('PASSIVE_TRIGGERED', ctx.source, actor_id=ctx.actor.entity_id,
        target_ids=tuple(target.entity_id for target in ctx.targets),
        payload={'trigger': 'audible_declaration',
                 'text': f'{ctx.action.display_name}: {ctx.actor.display_name} declares an audible shout. '
                         'The physical shockwave affects only creatures and objects its sound can reach; '
                         'Deafened creatures can still be struck.'})

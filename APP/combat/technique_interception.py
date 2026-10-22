"""Transactional pre-payment declarations shared by native and typed actions.

Replies are recorded against the accepted candidate. Cloned action/target data
and damage/forced-movement limits live only for this activation, never in catalogs.
"""
from contextlib import contextmanager
from copy import deepcopy
from . import ext

FIELDS = {'source_id', 'label', 'cancel', 'spend_activation', 'range_delta_ft',
          'area_delta_ft', 'forced_cap_ft', 'movement_cap_ft', 'retarget_id', 'retarget_kind', 'damage_roll_reduction'}


class InterceptionError(ValueError):
    """A declaration error must roll back, even inside generic reaction adapters."""


def redirected_action(action, target_kind):
    """Change recipient domain while retaining the original harmful nature."""
    parameters = action.parameters
    if action.target_kind == 'HOSTILE_ENTITY' or parameters.get('harmful') is True:
        parameters = {**parameters, 'harmful': True}
    return action.model_copy(update={'target_kind': target_kind, 'parameters': parameters})


def named_ability(action):
    """Use the bound typed source's authority record, never cost or weapon delivery."""
    from .typed_numbers import authority_mechanics
    typed = action.parameters.get('typed') or {}
    sources = (typed.get('source'), typed.get('immortal_from'), typed.get('forged_from'))
    return any(source in authority_mechanics() for source in sources if source)


def _integer(reply, key, *, minimum=None, maximum=None):
    if key not in reply:
        return
    value = reply[key]
    if type(value) is not int or (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        raise ValueError(f'invalid interception {key}')


def prepare(engine, user, action, candidate, intent):
    # Same public contract as Cycle of Rebirth: prepare a local activation copy.
    action = ext.transform('activation_prepare', action, engine, user, candidate, intent)
    replies = ext.run_strict('technique_declared', engine, user, action, candidate, intent)
    if not replies:
        return action, candidate, False, {}
    changes, record, cancel = {}, [], False
    for reply in replies:
        if not isinstance(reply, dict) or set(reply) - FIELDS:
            raise ValueError('technique_declared must return a supported reply or None')
        if not all(isinstance(reply.get(k), str) and reply[k] for k in ('source_id', 'label')):
            raise ValueError('an interception needs a source and readable label')
        for key in ('cancel', 'spend_activation'):
            if key in reply and type(reply[key]) is not bool:
                raise ValueError('interception flags must be booleans')
        for key in ('range_delta_ft', 'area_delta_ft'):
            _integer(reply, key, maximum=0)
        for key in ('forced_cap_ft', 'movement_cap_ft', 'damage_roll_reduction'):
            _integer(reply, key, minimum=0)
        if 'retarget_kind' in reply and (reply.get('retarget_id') is None or reply['retarget_kind'] not in {'HOSTILE_ENTITY_OR_SELF', 'ANY_CREATURE'}):
            raise ValueError('invalid interception retarget_kind')
        if reply.get('retarget_id') is not None:
            if candidate.kind.value == 'REACTION':
                raise ValueError('reaction interceptions cannot redirect precomputed protection effects')
            target = engine.state.actors.get(reply['retarget_id'])
            area = (action.parameters.get('typed') or {}).get('area') or {}
            if target is None or not target.active or len(candidate.target_ids) != 1 or candidate.destination is not None or area.get('size_ft'):
                raise ValueError('only a single-creature effect can be redirected')
            from .recipients import allowed
            kind = reply.get('retarget_kind', 'HOSTILE_ENTITY_OR_SELF')
            if kind not in {'HOSTILE_ENTITY_OR_SELF', 'ANY_CREATURE'}:
                raise ValueError('invalid interception retarget_kind')
            # Side-neutral redirection changes only the recipient domain. Keep
            # the originating action's harmful classification so Charm and
            # other harmful-action protections still apply at final validation.
            check_action = redirected_action(action, kind)
            if not allowed(engine, user, target, check_action):
                raise ValueError('the redirected target is not legal')
            candidate = candidate.model_copy(update={'target_ids': (target.entity_id,)})
        if reply.get('cancel'):
            cancel = True
            changes['spend_activation'] = changes.get('spend_activation', False) or reply.get('spend_activation', False)
        for key in ('range_delta_ft', 'area_delta_ft', 'damage_roll_reduction'):
            changes[key] = changes.get(key, 0) + reply.get(key, 0)
        for key in ('forced_cap_ft', 'movement_cap_ft'):
            if key in reply:
                changes[key] = min(changes.get(key, reply[key]), reply[key])
        record.append(deepcopy(reply))
    typed = deepcopy(action.parameters.get('typed') or {})
    # Retargeting is an activation-local recipient decision. Preserve that
    # explicit creature for effect rows such as applies_to=ally, whose normal
    # fallback may otherwise select a nearby roster unrelated to the redirect.
    redirected = next((reply.get('retarget_id') for reply in reversed(record)
                       if reply.get('retarget_id') is not None), None)
    if redirected is not None:
        typed['_activation_redirect_recipient_id'] = redirected
    updates = {}
    if changes.get('range_delta_ft'):
        for field in ('range_ft', 'reach_ft'):
            value = getattr(action, field)
            if value is not None:
                updates[field] = max(5, value + changes['range_delta_ft'])
        for field in ('range_ft', 'long_range_ft', 'reaction_range_ft'):
            if type(typed.get(field)) is int:
                typed[field] = max(5, typed[field] + changes['range_delta_ft'])
    if changes.get('area_delta_ft'):
        if action.radius_ft is not None:
            updates['radius_ft'] = max(5, action.radius_ft + changes['area_delta_ft'])
        for area in (typed.get('area'), typed.get('zone_spec')):
            if isinstance(area, dict) and type(area.get('size_ft')) is int:
                area['size_ft'] = max(5, area['size_ft'] + changes['area_delta_ft'])
    if typed:
        updates['parameters'] = {**action.parameters, 'typed': typed}
    action = action.model_copy(deep=True, update=updates)
    engine._append_event('PASSIVE_TRIGGERED', action.source_definition_id, actor_id=user.entity_id,
        target_ids=candidate.target_ids, payload={'candidate_id': candidate.candidate_id, 'interceptions': record,
        'log': f"{action.display_name}: " + '; '.join(reply['label'] for reply in record)})
    return action, candidate, cancel, changes


@contextmanager
def activation(engine, user, action, candidate, intent, *, caller_pays=False, relocation_continuation=False,
               settle_on_exit=True):
    from .paid_relocation import activation as relocation_activation

    # Ordinary declarations belong to the accepted foreground activation.
    # A separately accepted reaction owns its payments, effects and late falls.
    # A declared free follow-up to the current named ability is still part of
    # that ability, including interception choices and any additional payment.
    ownership = relocation_activation(engine, user, action.source_definition_id,
                                      independent=candidate.kind.value == 'REACTION',
                                      continuation=relocation_continuation)
    with ownership:
        old = getattr(engine, '_interception_frame', None)
        try:
            action, candidate, cancel, changes = prepare(engine, user, action, candidate, intent)
        except ext.CheckpointError:
            raise
        except Exception as exc:
            raise InterceptionError(str(exc)) from exc
        engine._interception_frame = {'actor_id': user.entity_id, 'source_id': action.source_definition_id,
                                     'action': action, **changes}
        try:
            if cancel and changes.get('spend_activation') and not caller_pays:
                engine._consume_economy(user, action)
                engine._spend_costs(user, action.costs, action.source_definition_id)
            yield action, candidate, cancel
            if not cancel and settle_on_exit:
                from .paid_relocation import settle_activation
                settle_activation(engine, action.source_definition_id, intent)
        finally:
            engine._interception_frame = old


def frame(engine, actor_id, source):
    """Public declaration context for this actor/source's active resolution.

    Includes the actual ActionDefinition, even for a reaction not in the sealed
    catalog. Native child attacks can use it for display/decision provenance.
    The activation restores its parent on exit or pause; nothing is persisted.
    """
    row = getattr(engine, '_interception_frame', None)
    return row if row and row['actor_id'] == actor_id and row['source_id'] == source else {}


def damage_amount(engine, actor_id, source, roll_id, amount):
    row = frame(engine, actor_id, source)
    reduction = row.get('damage_roll_reduction', 0)
    if not reduction:
        return amount
    first = row.setdefault('first_damage_roll_id', roll_id)
    return max(0, amount - reduction) if first == roll_id else amount


def movement_distance(engine, actor_id, source, recipient_id, distance):
    """Remaining movement budget for this activation and recipient (query only)."""
    row = frame(engine, actor_id, source)
    if 'movement_cap_ft' not in row:
        return distance
    used = row.get('movement_used_ft', {}).get(recipient_id, 0)
    return min(distance, max(0, row['movement_cap_ft'] - used))


def movement_committed(engine, actor_id, source, recipient_id, distance):
    """Account only movement actually committed or granted; never saved state."""
    row = frame(engine, actor_id, source)
    if 'movement_cap_ft' in row:
        used = row.setdefault('movement_used_ft', {})
        used[recipient_id] = used.get(recipient_id, 0) + distance


def forced_distance(engine, actor_id, source, distance, recipient_id=None):
    limited = min(distance, frame(engine, actor_id, source).get('forced_cap_ft', distance))
    return movement_distance(engine, actor_id, source, recipient_id or actor_id, limited)

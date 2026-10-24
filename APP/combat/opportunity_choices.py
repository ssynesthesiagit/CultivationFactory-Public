"""Public opt-in OA profiles, shared by native profile and explicit OA callers.

Providers return owned, currently legal attack profiles. Geometry uses the
longest profile; commitment offers all profiles that reach the actual target.
No provider preserves the sealed default action byte for byte.
"""
from . import ext


def profiles(engine, actor, default):
    replies = ext.run_strict('opportunity_choices', engine, actor, default)
    if not replies:
        return None
    out = []
    for reply in replies:
        if not isinstance(reply, list):
            raise ValueError('opportunity_choices requires a list of owned attack profiles')
        for action in reply:
            if action.owner_id != actor.entity_id or action.resolution_kind != 'TYPED':
                raise ValueError('opportunity_choices requires the reactor’s typed profile')
            if not any(e.get('type') == 'attack' for e in (action.parameters.get('typed') or {}).get('effects') or []):
                raise ValueError('opportunity_choices requires an attack')
            if action not in out:
                out.append(action)
    return out or None


def choose(engine, actor, target, intent, default):
    def finish(action):
        answers = ext.run_strict('opportunity_profile_selected', engine, actor, target, action)
        if any(type(answer) is not bool for answer in answers):
            raise ValueError('opportunity_profile_selected requires bool or None')
        return None if False in answers else action
    options = profiles(engine, actor, default)
    if options is None:
        return finish(default)
    from .attack_reach import maximum
    options = [a for a in options if engine._distance_actor_to_actor(actor, target)
               <= maximum(engine, actor, a, base=int(a.range_ft or a.reach_ft or 5), opportunity=True)]
    if not options:
        return None
    if len(options) == 1:
        return finish(options[0])
    from .ext.needle import ask, checkpoint_id
    keys = {str(i): a for i, a in enumerate(options)}
    selected = ask(engine, intent, checkpoint_id(engine, 'opportunity_profile', actor.entity_id, target.entity_id), actor,
        'choice:needle.opportunity_profile', list(keys), labels={key: a.display_name for key, a in keys.items()},
        target_id=target.entity_id, name='Opportunity Attack',
        prompt=f'Opportunity Attack: choose one attack against {target.display_name}. This spends one available Reaction.')
    return finish(keys[selected[0]]) if selected else None

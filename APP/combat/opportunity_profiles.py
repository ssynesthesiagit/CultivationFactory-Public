"""Target-specific OA alternatives shared by movement previews and resolution.

The ordinary profile is never replaced or truncated. Each additional melee
profile threatens only its own target/reach. No provider means legacy behavior.
"""
from . import ext


def additional(engine, reactor, target):
    from .typed_reactions import opportunity_profile
    row, _, _ = opportunity_profile(engine, reactor)
    if row is None:
        return []
    found = []
    seen = set()
    for profiles in ext.run_strict('opportunity_target_profiles', engine, reactor, target):
        for action in profiles:
            if action.owner_id != reactor.entity_id or action.resolution_kind != 'TYPED':
                raise ValueError('opportunity_target_profiles requires owned typed melee actions')
            if action.source_definition_id in seen:
                continue
            seen.add(action.source_definition_id)
            reach = int(action.reach_ft or action.range_ft or 5)
            found.append(({**row, 'action_id': action.source_definition_id, 'reach_ft': reach}, action, reach))
    return found


def crosses(engine, reactor, target, previous, destination, *, profiles=None):
    """Pure extra-profile crossing; callers retain their ordinary-profile check."""
    before = engine._distance_actor_to_actor(target, reactor, actor_position=previous)
    after = engine._distance_actor_to_actor(target, reactor, actor_position=destination)
    projected = target if target.position == previous else target.model_copy(update={'position': previous})
    return any(before <= reach < after for _, _, reach in
               (additional(engine, reactor, projected) if profiles is None else profiles))


def _effective(engine, reactor, profile):
    """The ordinary profile's own condition-bound reach, exactly as eligibility used it.

    Native eligibility and movement previews ask ``opportunity_reach``, which folds
    ``attack_reach_bonus`` (Long Grip's +5 feet, Adamant's +5 feet) through
    ``attack_reach.maximum(..., opportunity=True)``. Selection must reach the same
    answer, or a legal ordinary attack at the bonus reach is filtered out and the
    paid Reaction buys nothing. Native (non-Factory) spec dicts carry their own
    fixed reach and never a condition-bound bonus, so they are returned unchanged.
    """
    row, action, reach = profile
    if row is None or action is None or row.get('native_spec') is not None:
        return profile
    from .attack_reach import maximum
    return row, action, maximum(engine, reactor, action, base=reach, opportunity=True)


def select(engine, reactor, target, intent, *, edge=None, reach_override=None):
    """Ask the owner among every legal profile; AI uses its existing choice path."""
    from .typed_reactions import opportunity_profile
    ordinary = _effective(engine, reactor, opportunity_profile(engine, reactor))
    extras = additional(engine, reactor, target)
    if not extras:
        return ordinary
    choices = []
    for row, action, reach in [ordinary, *extras]:
        if row is None:
            continue
        if edge is not None:
            before = engine._distance_actor_to_actor(target, reactor, actor_position=edge[0])
            after = engine._distance_actor_to_actor(target, reactor, actor_position=edge[1])
            if not before <= reach < after:
                continue
        elif engine._distance_actor_to_actor(reactor, target) > (reach_override if reach_override is not None else reach):
            continue
        choices.append((row, action, reach))
    if not choices:
        return None, None, 0
    if len(choices) == 1:
        return choices[0]
    from .ext import needle
    options = {str(row['action_id']): (row, action, reach) for row, action, reach in choices}
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, 'OPPORTUNITY_PROFILE', target.entity_id),
        reactor, 'choice:needle.opportunity_profile', list(options),
        labels={key: f'{getattr(action, "display_name", "Ordinary attack")} ({reach}-foot reach)'
                for key, (_, action, reach) in options.items()}, preferred=[next(iter(options))],
        name='Opportunity Attack', target_id=target.entity_id,
        prompt=f'Opportunity Attack against {target.display_name}: choose one melee attack. It uses your Reaction.')
    return options[(chosen or [next(iter(options))])[0]]

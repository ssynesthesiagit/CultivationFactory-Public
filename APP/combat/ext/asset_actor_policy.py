"""Source-profiled actor restrictions shared by paper, painted and mirror Assets.

The sealed summon.actor_policy is opt-in. A list of legal basic actions does
not grant any creator features, inventory, knowledge, identity or item powers.
Command 'free_once' uses the ordinary command transaction and its per-owner
turn reset, rather than granting an uncommanded autonomous turn.
"""
from . import hook


@hook('compile_summon')
def printed_reactions(bundle, info):
    if not (info['source'].get('actor_policy') or {}).get('printed_reactions_only'):
        return None
    bundle['typed_reactions'] = [r for r in bundle['typed_reactions'] if r.get('block') != 'opportunity']
    bundle['action_catalog'] = [a for a in bundle['action_catalog'] if not a['source_definition_id'].endswith('.opportunity_attack')]
    return bundle


@hook('summon_source_numbers')
def owning_path_numbers(numbers, info):
    if not (info['source'].get('actor_policy') or {}).get('owning_path'):
        return None
    from ..activation_settlement import path_numbers
    return path_numbers(info, info['source']['actor_policy']['owning_path'])


@hook('candidate_allowed')
def legal_profile(engine, actor, candidate, action):
    policy = (actor.summon or {}).get('actor_policy') or {}
    if not policy or action is None:
        return None
    if action.owner_id == actor.entity_id:
        return None  # only its sealed catalogue, never the owner's catalogue
    if action.owner_id == '*' and action.display_name not in policy.get('basic_actions', ()):
        return False
    return None


@hook('candidate_allowed')
def once_per_owner_turn(engine, actor, candidate, action):
    group = (getattr(action, 'parameters', None) or {}).get('summon_command')
    if not group:
        return None
    from ..summons import owned_by, commandable
    members = owned_by(engine, actor.entity_id, group)
    if members and any((c.summon or {}).get('command') == 'free_once' for c in members):
        return None if commandable(engine, actor, group) else False
    return None


@hook('summon_turn_policy')
def inert_body(engine, actor):
    policy = (actor.summon or {}).get('actor_policy') or {}
    if policy and any(c.data.get('asset_suppressed') or c.data.get('asset_soaked')
                      for c in actor.conditions.values()):
        return {'skip': True}
    return None


@hook('choice_reactors')
def source_owned_decisions(engine):
    """Enroll human recipients on AI turns only when a profiled Asset exists."""
    if not any((a.summon or {}).get('actor_policy') for a in engine.state.actors.values()):
        return None
    return tuple(a.entity_id for a in engine.state.actors.values() if a.active)

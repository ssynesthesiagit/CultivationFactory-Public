"""Recipient path choice shared by Predictive Step and Settle the Impact.

Uses the complete native grant-aware candidate menu and native step resolver.
This adapter owns no movement engine, ordinary budget or ability eligibility.
"""


def choose(engine, mover, feet, source, *, key, name, threat, intent=None, ignored=()):
    """Choose every legal route/mode, or stay; commit with selective OA immunity."""
    from .needle import ask, CHOICE, checkpoint_id, cell_id
    from ..target_knowledge import located
    from . import any_false
    paths = [c for c in engine._movement_candidates(mover, movement_grant_ft=feet)
             if not any_false('candidate_allowed', engine, mover, c,
                              engine.action_catalog.get(c.source_definition_id))]
    by_id, labels = {}, {}
    stay = cell_id(mover.position)
    labels[stay] = 'Stay in your current space'
    for path in paths:
        ident = cell_id(path.destination)
        mode = path.metadata.get('movement_mode', 'walk')
        if ident in labels:
            ident = 'route:' + path.candidate_id
        by_id[ident] = path
        p = path.destination
        labels[ident] = f'({p.x}, {p.y}, {p.z * 5} feet high): {mode.title()}, {path.movement_cost_ft} feet of movement'
    preferred = [stay]
    if threat is not None and located(engine, mover, threat) and by_id:
        preferred = [max(by_id, key=lambda k: engine.grid.distance_ft(threat.position, by_id[k].destination))]
    ignored = tuple(ignored)
    protection = ('without provoking Opportunity Attacks' if set(ignored) >= set(engine.state.actors)
                  else 'without Opportunity Attacks from ' + ', '.join(engine.state.actors[i].display_name for i in ignored)
                  if ignored else 'with ordinary Opportunity Attacks')
    picked = ask(engine, intent, checkpoint_id(engine, key, mover.entity_id), mover,
        CHOICE + key, list(labels), labels=labels, preferred=preferred, allow_decline=True,
        target_id=mover.entity_id, name=name,
        prompt=f'{name}: choose {mover.display_name}’s legal movement, up to {feet} feet {protection}, or stay put. No additional cost.',
        prompt_context={'cost': 'No additional cost'})
    if picked and picked[0] in by_id:
        engine._resolve_movement(mover, by_id[picked[0]], intent or getattr(engine, '_active_intent', None),
            granted_ft=feet, ignore_oa_from=ignored, grant_source=source, movement_context={'feature_id': source})
        return True
    return False

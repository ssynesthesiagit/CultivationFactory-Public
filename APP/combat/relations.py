"""Current relations for native combat, recipient rules and AI; GM journal commands.

Riders call relation(engine, actor, other), never compare team identifiers for
friendship. Identifiers remain useful for roster grouping. The same pure query
accepts a sealed DecisionContext. Pair overrides are symmetric and take priority
over team overrides; self is always an ally. A neutral team is neutral to every
other actor by default, including its own members. Attacks never change sides.
"""
from __future__ import annotations

from .relation_models import RelationChange, Relations

ALLY, ENEMY, NEUTRAL = 'ALLY', 'ENEMY', 'NEUTRAL'
NEUTRAL_TEAM = 'team:neutral'
SOURCE = 'system:combat.relations'


def ordinary_turn(candidates):
    """Shared phase guard for relation filtering in context and controller.

    Setup and accepted follow-up windows must finish before ordinary retreat,
    Dodge and neutral-target policy applies. Uses the existing candidate kinds;
    no new saved field or inferred actor state is needed.
    """
    from .fight_setup import SOURCE as SETUP
    return not any(c.source_definition_id == SETUP or c.kind in
                   {'OPTIONAL_RIDER', 'TAKE_NO_OPTIONAL_ACTION'} for c in candidates)


def relation(engine, a, b):
    """Return ALLY, ENEMY or NEUTRAL without mutating or caching fight state."""
    if a.entity_id == b.entity_id:
        return ALLY
    state = getattr(engine, 'state', engine)
    table = getattr(state, 'relations', None)
    if table is not None:
        left, right = sorted((a.entity_id, b.entity_id))
        value = table.actors.get(left, {}).get(right)
        if value is not None:
            return value
        left, right = sorted((a.team_id, b.team_id))
        value = table.teams.get(left, {}).get(right)
        if value is not None:
            return value
    if NEUTRAL_TEAM in (a.team_id, b.team_id):
        return NEUTRAL
    return ALLY if a.team_id == b.team_id else ENEMY


def enabled(engine):
    state = getattr(engine, 'state', engine)
    actors = state.actors.values() if isinstance(state.actors, dict) else state.actors
    return state.relations is not None or any(a.team_id == NEUTRAL_TEAM for a in actors)


def bystander(engine, actor):
    """Default neutral/mortal noncombatants retreat and Dodge; hooks may opt in/out.

    A new enemy immediately restores the ordinary combat policy. Explicit
    creature type 'mortal' is honored; no species or display-name inference.
    """
    from . import ext
    replies = ext.run_strict('bystander_policy', engine, actor)
    for reply in replies:
        if type(reply) is not bool:
            raise ValueError('bystander_policy must return None or bool')
        return reply
    if any(a.active and relation(engine, actor, a) == ENEMY for a in engine.state.actors.values()):
        return False
    return actor.team_id == NEUTRAL_TEAM or 'mortal' in actor.creature_types


def validate_change(engine, change):
    state = engine.state
    if state.terminal_result is not None or state.pending_resolution is not None or state.setup_tasks:
        raise ValueError('Finish the current choice or fight setup before changing sides.')
    if change.kind == 'TEAM_RELATION':
        teams = {a.team_id for a in state.actors.values()}
        if not {change.subject, change.other} <= teams:
            raise ValueError('Choose teams present in this fight.')
    elif change.subject not in state.actors or (change.kind == 'ACTOR_RELATION' and change.other not in state.actors):
        raise ValueError('Choose creatures present in this fight.')
    elif change.kind == 'ACTOR_SIDE' and not change.other.startswith('team:'):
        raise ValueError('A side needs a team identifier.')


def command_candidate(engine, change):
    """A bound GM command, never offered in an actor's or AI's legal menu."""
    from .canonical import canonical_sha256
    from .gate2_runtime_models import CandidateKind
    validate_change(engine, change)
    actor = engine.state.actors[engine.state.current_actor_id]
    candidate = engine._candidate(CandidateKind.ACTION, actor, SOURCE, 'Change sides or relations')
    document = change.model_dump(mode='json')
    return candidate.model_copy(update={
        'candidate_id': 'candidate:' + canonical_sha256([candidate.candidate_id, document])[:24],
        'metadata': {'relation_change': document},
    })


def command_intent(engine, change, *, expected_state_version):
    from .gate2_runtime_models import ActionIntent
    if expected_state_version != engine.state.state_version:
        raise ValueError('The fight changed. Refresh it before changing sides.')
    change = RelationChange.model_validate(change)
    candidate = command_candidate(engine, change)
    return ActionIntent(intent_id=f'relations:{candidate.candidate_id}',
        candidate_id=candidate.candidate_id, decision_id=candidate.decision_id,
        actor_id=candidate.actor_id, state_version=expected_state_version, relation_change=change)


def team_label(engine, team_id, *, exclude=None):
    """Describe a side by its fighters, never by an opaque storage identifier."""
    if team_id == NEUTRAL_TEAM:
        return 'Neutral'
    members = sorted((a for a in engine.state.actors.values()
                      if a.team_id == team_id and a.entity_id != exclude),
                     key=lambda a: (not a.primary_combatant, a.entity_id))
    return f"the side with {members[0].display_name}" if members else 'a new side'


def apply_change(engine, change):
    """Apply one validated command inside the native recorded transaction.

    Existing effects and recipient lists remain intact. Actor pair overrides
    survive a side change; change those pairs explicitly when desired. Owned
    companions do not silently follow an owner: change each creature explicitly.
    """
    validate_change(engine, change)
    if change.kind == 'ACTOR_SIDE':
        actor = engine.state.actors[change.subject]
        previous = actor.team_id
        side = team_label(engine, change.other, exclude=actor.entity_id)
        actor.team_id = change.other
        engine._append_event('ACTOR_SIDE_CHANGED', SOURCE, actor_id=actor.entity_id,
            payload={'team_id': actor.team_id, 'previous_team_id': previous,
                     'log': f'{actor.display_name} joins {side} until their side changes again. This costs no action; effects already on creatures stay on them.'})
    else:
        table = (engine.state.relations or Relations()).model_copy(deep=True)
        pairs = table.teams if change.kind == 'TEAM_RELATION' else table.actors
        left, right = sorted((change.subject, change.other))
        pairs.setdefault(left, {})[right] = change.relation
        engine.state.relations = table
        def label(value):
            if change.kind == 'ACTOR_RELATION':
                return engine.state.actors[value].display_name
            return team_label(engine, value)
        wording = {'ALLY': 'allies', 'ENEMY': 'enemies', 'NEUTRAL': 'neutral toward each other'}[change.relation]
        engine._append_event('RELATION_CHANGED', SOURCE,
            payload={**change.model_dump(mode='json'), 'relations_after': table.model_dump(mode='json'),
                     'log': f'{label(left)} and {label(right)} are now {wording} until changed again. This costs no action; effects already on creatures stay on them.'})
    engine._check_victory()


def peaceful_result(engine):
    """Victory ignores bystanders; allied coalitions can finish together.

    Return (kind, winning team, reason) or None while active enemies remain.
    No active enemy pair after an explicit truce ends combat without a winner.
    """
    from .gate2_runtime_models import TerminalKind
    primaries = [a for a in engine.state.actors.values() if a.primary_combatant]
    active = [a for a in primaries if a.active]
    if any(relation(engine, a, b) == ENEMY for a in active for b in active):
        return None
    fighters = [a for a in active if any(relation(engine, a, b) == ENEMY for b in primaries)]
    if fighters:
        teams = sorted({a.team_id for a in fighters})
        return TerminalKind.VICTORY, teams[0] if len(teams) == 1 else None, 'Opposing primary combatants are inactive.'
    return TerminalKind.DRAW_SIMULTANEOUS, None, 'No opposing primary combatants remain.'

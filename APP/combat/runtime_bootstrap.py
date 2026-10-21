"""Saved-roster constructor inputs for persistence upgrades and preview clones.

Consumers: Gate3/Gate4 recovery, Gate4 upgrade, CombatService preview cloning.
Constructors need a temporary match shell before installing the committed state.
Use that state's actual primary roster, teams and positions: default stock
fighters may not fit this arena at all. This never moves a saved actor, creates
a new combat option, or substitutes a guessed location for the committed one.
"""


def roster_from_state(state):
    return {
        'primary_actor_ids':[a.entity_id for a in state.actors.values() if a.primary_combatant],
        'team_by_actor':{aid:a.team_id for aid,a in state.actors.items()},
        'starting_positions':{aid:a.position.model_dump(mode='json') for aid,a in state.actors.items()},
        'rules':dict(state.rules),
    }

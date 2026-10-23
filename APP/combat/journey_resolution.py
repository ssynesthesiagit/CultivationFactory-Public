"""Apply sourced mechanical consequences on the native elapsed-scene caller.

``resolve(session, source, callback)`` reconstructs actual acquired bundles and
committed health in a turnless native engine, invokes callback(engine), then
exports its native damage/life state and source ledgers. No source calls means
no engine, rolls, changes or behavior. This is not a new fight or an inferred
turn/scene boundary. The caller's JourneyStore transaction owns persistence.

Users are scene-end backlash and source recovery/consequence procedures. Roll
authority, HP/Temporary HP, zero HP and source state all use existing combat
procedures. No creature or trigger receipt is fabricated by this adapter.
"""
from copy import deepcopy
from pathlib import Path


def resolve(session, source, callback):
    from .gate4_engine import Gate4ControllerEngine
    from .ext import run_strict, transform
    from .ext.journey_setup import encounter_snapshot, encounter_incapacitated
    bundles = []
    for aid, actor in session.state['actors'].items():
        bundle = deepcopy(actor['bundle'])
        for pool in bundle['actor_template']['resources']:
            pool['initial'] = actor['resources'].get(pool['resource_id'], pool['initial'])
        setup = {'incapacitated': actor['incapacitated'], 'exhaustion': actor['exhaustion']}
        if 'encounter_snapshot' in actor:
            setup['encounter_snapshot'] = deepcopy(actor['encounter_snapshot'])
        for supplied in run_strict('journey_combat_setup', session, aid):
            if not isinstance(supplied, dict) or set(supplied).intersection(setup):
                raise ValueError('Scene resolution requires disjoint native source setup fields')
            setup.update(supplied)
        bundle['journey_setup'] = setup
        bundles.append(bundle)
    actor_ids = list(session.state['actors'])
    engine = Gate4ControllerEngine(Path(__file__).resolve().parents[1],
        match_seed=session.state['journey_id'] + ':' + str(len(session.state['events'])) + ':' + source,
        typed_bundles=tuple(bundles), battlefield=session.state['battlefield'], start_turns=False,
        roster_setup={'primary_actor_ids': actor_ids,
                      'team_by_actor': {aid: 'team:journey' for aid in actor_ids},
                      'starting_positions': {aid: a['position'] for aid, a in session.state['actors'].items()}})
    first = len(engine.events)
    callback(engine)
    for aid, actor in session.state['actors'].items():
        creature = engine.state.actors[aid]
        copy = transform('journey_snapshot_actor', creature, session, aid, engine)
        actor['encounter_snapshot'] = encounter_snapshot(copy)
        actor['resources'] = dict(creature.resources)
        actor['incapacitated'] = int(encounter_incapacitated(actor['encounter_snapshot']))
        run_strict('journey_encounter_settled', session, aid, engine, creature)
    session.emit('SOURCE_CONSEQUENCE_RESOLVED', actor_ids[0], source=source,
                 events=[event.model_dump(mode='json') for event in engine.events[first:]],
                 rolls=[roll.model_dump(mode='json') for roll in engine.rolls])
    return engine

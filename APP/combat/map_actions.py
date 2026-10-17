"""Native short mapped actions inside elapsed-time journeys.

JourneySession owns the locked revision/atomic save. A declaration only records
intent; completion pays a six-second action interval and traverses its validated
route before publishing the completion. This is not a GM success/fact input.
The motion provider alone decides whether a completed action restores Focus.
Consumers: JourneySession.menu/command, the default automatic journey caller
(gate5_service.journey_auto_step, through auto_choice below) and future
journey_action_completed hooks.
"""
from __future__ import annotations

import copy

from . import motion
from .ext import run_strict
from .gate2_runtime_models import Position


SOURCES = {'system:combat.dash': 'Dash', 'system:combat.disengage': 'Disengage'}


def options(session, aid):
    actor = session.state['actors'][aid]
    if session.state['phase'] != 'travel' or actor['incapacitated'] or actor.get('carried_by'):
        return []
    pending = actor.get('map_action')
    if pending:
        return [{'id': kind + ':' + pending['id'], 'kind': kind,
                 'payload': {'id': pending['id']}, 'auto_select': 0,
                 'label': f"{actor['name']}: {verb} {SOURCES[pending['source']]} as an Action"
                          + (' (six seconds; follow the declared map route).' if verb == 'Complete' else ' without spending time or recovering resources.')}
                for kind, verb in (('map_action_complete', 'Complete'), ('map_action_cancel', 'Cancel'))]
    return [{'id': 'map-action:' + source, 'kind': 'map_action_declare',
             'payload': {'source': source, 'economy': 'ACTION', 'path': []}, 'auto_select': 0,
             'label': f"{actor['name']}: declare {name} as an Action (six seconds on completion). "
                      + ('You may follow a map route up to twice your walking Speed.' if name == 'Dash'
                         else 'You may follow a map route up to your walking Speed without provoking Opportunity Attacks.')}
            for source, name in SOURCES.items()]


def auto_choice(session, aid):
    """Deliberate automatic choice for this actor's mapped Actions, or None.

    The default LOCAL_AUTO journey caller (gate5_service.journey_auto_step)
    consults this before ordinary ranked travel, so a mapped Action can be
    chosen and settled without an external option id. It settles an already
    declared Action (complete it while the declaration is still valid,
    otherwise cancel the stale declaration) and otherwise declares Dash or
    Disengage, following no route (staying in place), only when completing it
    would restore a missing Martial Focus through the owned motion provider.
    A nonowner or a full Focus pool keeps ordinary travel, so mapped Actions
    never loop pointlessly. None leaves ordinary automatic travel unchanged.
    """
    actor = session.state['actors'][aid]
    if session.state['phase'] != 'travel' or actor['incapacitated'] or actor.get('carried_by'):
        return None
    rows = options(session, aid)
    pending = actor.get('map_action')
    if pending:
        kind = 'map_action_complete'
        if actor['position'] != pending['position']:
            kind = 'map_action_cancel'  # The creature moved; keep automatic travel working.
        else:
            try:
                route(session, aid, pending['source'], pending['path'])
            except ValueError:
                kind = 'map_action_cancel'  # Admission changed during the interval.
        return next(row for row in rows if row['kind'] == kind)
    for source in SOURCES:
        if motion.focus_regain_source(actor['bundle'].get('typed_passives', ()), actor['resources'],
                                      'ACTION', source):
            return next(row for row in rows if row['kind'] == 'map_action_declare'
                        and row['payload']['source'] == source)
    return None


def route(session, aid, source, path):
    """Validate the complete chosen walking route before any completion or gain.

    No destination ranking/truncation: callers may submit every legal route.
    Journey step admission owns terrain, LOS for automatic seats and occupancy.
    """
    from .journey import require
    actor = session.state['actors'][aid]
    require(isinstance(path, list), 'Choose a mapped walking route (or stay in place).')
    speed = int(actor['bundle']['actor_template']['speed_ft'])
    budget = speed * (2 if source == 'system:combat.dash' else 1)
    old = Position.model_validate(actor['position'])
    distance = 0
    for cell in path:
        require(isinstance(cell, dict) and set(cell) <= {'x', 'y', 'z'}
                and all(type(v) is int for v in cell.values()), 'Use whole map coordinates.')
        nxt = Position.model_validate(cell)
        distance += session.grid.distance_ft(old, nxt) * session.step_profile(aid, old, nxt)
        require(distance <= budget, 'This route exceeds the movement available with that Action.')
        old = nxt
    return old.model_dump(mode='json'), distance


def command(session, aid, kind, payload):
    if kind not in ('map_action_declare', 'map_action_complete', 'map_action_cancel'):
        return False
    from .journey import require
    actor = session.state['actors'][aid]
    require(not actor['incapacitated'] and not actor.get('carried_by'),
            'This creature cannot take a mapped Action while incapacitated or carried.')
    pending = actor.get('map_action')
    if kind == 'map_action_declare':
        require(not pending, 'Complete or cancel the declared Action first.')
        require(set(payload) == {'source', 'economy', 'path'} and payload['source'] in SOURCES
                and payload['economy'] == 'ACTION',
                'Choose Dash or Disengage as an Action. This does not grant a Bonus Action ability.')
        route(session, aid, payload['source'], payload['path'])
        actor['map_action'] = {'id': f"map-action:{session.state['revision']}",
                               **copy.deepcopy(payload), 'position': dict(actor['position'])}
        return True
    require(set(payload) == {'id'} and pending and payload['id'] == pending['id'],
            'That declared Action is no longer available; refresh the map.')
    del actor['map_action']
    if kind == 'map_action_cancel':
        return True
    require(actor['position'] == pending['position'], 'The creature moved; cancel and declare its route again.')
    destination, distance = route(session, aid, pending['source'], pending['path'])
    # Ordinary movement (journey.move) puts transported creatures in the
    # elapsed moving set, and so must a mapped Action's interval; otherwise a
    # carried traveller's owned stop-clock would wrongly advance while riding.
    moving = ((aid, *(other_id for other_id, other in session.state['actors'].items()
                      if other.get('carried_by') == aid)) if distance else ())
    session.tick(6, moving)
    # Expiry providers may have changed admission during the action interval.
    route(session, aid, pending['source'], pending['path'])
    actor['position'] = destination
    for other in session.state['actors'].values():
        if other.get('carried_by') == aid:
            other['position'] = dict(destination)
    for other_id in session.state['actors']:
        run_strict('journey_state_changed', session, other_id)
    receipt = {'id': pending['id'], 'source': pending['source'], 'economy': 'ACTION',
               'distance_ft': distance, 'position': destination, 'seconds_spent': 6}
    session.emit('MAP_ACTION_COMPLETED', aid, **receipt,
                 text=f"{actor['name']} completes {SOURCES[pending['source']]} as an Action (six seconds).")
    source = motion.focus_regain_source(actor['bundle'].get('typed_passives', ()), actor['resources'],
                                        receipt['economy'], receipt['source'])
    if source:
        before = actor['resources'][motion.FOCUS]
        actor['resources'][motion.FOCUS] = before + 1
        session.emit('RESOURCE_GAINED', aid, source=source, action_id=receipt['id'],
                     action_source=receipt['source'], resource_id=motion.FOCUS,
                     before=before, gained=1, after=before + 1,
                     text=f"{actor['name']} regains one Martial Focus (their ki reserve).")
    run_strict('journey_action_completed', session, aid, receipt)
    return True

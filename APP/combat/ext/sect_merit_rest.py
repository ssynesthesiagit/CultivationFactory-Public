"""Merit Dice recovery through owner-confirmed, elapsed-time journey actions.

Uses the public Sect Stewardship pool and journey command/menu hooks. The
owner supplies institutional facts by explicitly selecting a confirmation;
automatic seats never infer good standing, location or performance of a duty.
Ordinary Long Rest without these facts grants no Merit Dice. No scene truth,
Standing grade, wealth or other reward is created by these confirmations.
"""
from . import hook
from .sect_stewardship import MERIT
from ..journey import integer, require

SOURCE = 'SECT_STEWARDSHIP_BASE_MERIT_DICE'
COMMAND = 'sect_merit_rest'
INSTITUTION_TASKS = ('fulfilling a duty', 'checking a ledger', 'reporting to a superior',
                     'instructing a junior', 'cleaning a shared space', 'otherwise honoring your role')
TRAVEL_TASKS = ('maintaining records', 'writing reports', 'preserving tokens',
                'planning duties', 'honoring the sect’s rules while traveling')


def merit_pool(session, aid):
    """Find the natively compiled, owned pool, never a payload-supplied receipt."""
    actor = session.state['actors'][aid]
    return next((r for r in actor['bundle']['actor_template']['resources']
                 if r['resource_id'] == MERIT), None)


@hook('journey_options')
def options(session, aid):
    actor = session.state['actors'][aid]
    if session.state['phase'] != 'travel' or actor['incapacitated'] or merit_pool(session, aid) is None:
        return None
    result = []
    for mode, tasks in (('institution', INSTITUTION_TASKS), ('away', TRAVEL_TASKS)):
        for index, activity in enumerate(tasks):
            context = ('you are in good standing with at least one institution' if mode == 'institution'
                       else 'you are away from every institution')
            duration = 'spend 10 minutes' if mode == 'institution' else 'honor your role while traveling by'
            recovery = 'all spent Merit Dice' if mode == 'institution' else 'one spent Merit Die'
            result.append({'id': f'{COMMAND}:{mode}:{index}', 'kind': COMMAND,
                           'source': SOURCE, 'auto_select': 0,
                           'payload': {'mode': mode, 'confirmed': 1, 'activity': activity,
                                       'minutes': 10 if mode == 'institution' else 0},
                           'label': f'{actor["name"]}: Merit Dice — confirm {context}; {duration} '
                                    f'{activity}, then finish an eight-hour Long Rest to regain {recovery}. '
                                    'Confirm only facts the table has established; costs no Merit Dice.'})
    return result


@hook('journey_command')
def command(session, aid, kind, payload):
    if kind != COMMAND:
        return None
    pool = merit_pool(session, aid)
    require(pool is not None, 'Only a character with Sect Stewardship Merit Dice can use this recovery.')
    require(set(payload) == {'mode', 'confirmed', 'activity', 'minutes'}
            and type(payload['confirmed']) is int and payload['confirmed'] == 1
            and payload['mode'] in ('institution', 'away')
            and isinstance(payload['activity'], str) and payload['activity'].strip()
            and integer(payload['minutes']),
            'Confirm the institutional facts, a qualifying activity and its whole minutes for Merit Dice recovery.')
    actor = session.state['actors'][aid]
    require(not actor['incapacitated'], 'An incapacitated creature cannot start this rest.')
    mode = payload['mode']
    tasks = INSTITUTION_TASKS if mode == 'institution' else TRAVEL_TASKS
    require(payload['activity'] in tasks, 'Choose a printed Merit Dice recovery activity.')
    require(mode != 'institution' or payload['minutes'] >= 10,
            'Recovery in good standing requires at least 10 minutes honoring your role.')
    # One transaction: activity time, ordinary eight-hour rest, then this
    # ability's recovery. A failed hook rolls everything back in JourneyStore.
    session.tick(payload['minutes'] * 60)
    session.command(aid, 'long_rest', {})
    before = actor['resources'][MERIT]
    maximum = pool['maximum']
    actor['resources'][MERIT] = min(maximum, maximum if mode == 'institution' else before + 1)
    recovered = actor['resources'][MERIT] - before
    session.emit('MERIT_DICE_RECOVERED', aid, source=SOURCE, mode=mode,
                 activity=payload['activity'], minutes=payload['minutes'],
                 owner_confirmed=1, recovered=recovered,
                 text=f'{actor["name"]} finishes a Long Rest after {payload["activity"]}; '
                      f'the owner confirmed {"good standing with at least one institution" if mode == "institution" else "travel away from every institution"}. '
                      f'Regained {recovered} Merit Dice (maximum {maximum}); no wealth or other reward granted.')
    return True

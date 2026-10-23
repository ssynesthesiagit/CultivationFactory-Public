"""Body Beyond Distance: owned elapsed-time travel, never combat Speed.

Only this plug-in interprets the ability. The journey consumer owns transactions,
map steps and elapsed seconds; other abilities can use the same generic hooks.
"""
from . import hook
from fractions import Fraction

SOURCE = 'TAL_ATHLETICS_BODY_BEYOND_DISTANCE'
FOCUS = 'resource:core.martial_focus'


@hook('compile_block')
def compile_travel(block, spec, row, numbers):
    if block != 'journey_ability':
        return None
    return [{**row, 'block': block, 'journey': dict(spec['journey'])}]


def owned(session, aid):
    actor = session.state['actors'][aid]
    return any(row.get('feature_id') == SOURCE and row.get('block') == 'journey_ability'
               for row in actor['bundle'].get('typed_passives', ()))


def active(session, aid):
    if not owned(session, aid):
        return None
    return session.state['actors'][aid]['travel_effects'].get(SOURCE)


def end(session, aid, reason):
    if active(session, aid):
        del session.state['actors'][aid]['travel_effects'][SOURCE]
        if (session.state.get('carry_request') or {}).get('carrier') == aid:
            del session.state['carry_request']
        session.emit('TRAVEL_EFFECT_ENDED', aid, source=SOURCE,
                     text=f"Body Beyond Distance ends for {session.state['actors'][aid]['name']}: {reason}.")


@hook('journey_options')
def options(session, aid):
    if session.state['phase'] != 'travel':
        return None
    actor = session.state['actors'][aid]
    offered = carry_options(session, aid)
    if not owned(session, aid):
        return offered or None
    if actor['incapacitated'] or active(session, aid) or actor['travel_uses'].get(SOURCE) == actor['long_rests']:
        return offered
    if actor['resources'].get(FOCUS, 0) < 1:
        return offered
    return [*offered, {'id': SOURCE, 'kind': 'activate', 'source': SOURCE, 'payload': {'source': SOURCE},
             'label': f"{actor['name']}: Body Beyond Distance — take an Action and expend Martial Focus to travel at ten times your overland pace for up to one hour; once per Long Rest. Ends on combat, incapacitation, or stopping for more than one minute."}]


@hook('journey_command')
def command(session, aid, kind, payload):
    if kind in ('request_carry', 'carry_reply', 'set_down'):
        return carry_command(session, aid, kind, payload)
    if kind != 'activate' or payload.get('source') != SOURCE or not owned(session, aid):
        return None
    from ..journey import require
    require(set(payload) == {'source'} and any(row['kind'] == 'activate' for row in options(session, aid)), 'Body Beyond Distance is not available; it requires Martial Focus and an unused Long Rest use.')
    actor = session.state['actors'][aid]
    actor['resources'][FOCUS] -= 1
    actor['travel_uses'][SOURCE] = actor['long_rests']
    expiry = session.clock() + 3600
    actor['travel_effects'][SOURCE] = {'expires_at': expiry.numerator // expiry.denominator,
                                     'expiry_num': expiry.numerator, 'expiry_den': expiry.denominator,
                                     'stopped_seconds': 0, 'stopped_num': 0, 'stopped_den': 1}
    session.emit('TRAVEL_ACTION', aid, source=SOURCE, economy='ACTION', focus_cost=1,
                 text=f"{actor['name']} takes an Action and expends Martial Focus: Body Beyond Distance begins for up to one hour.")
    return True


@hook('journey_properties')
def properties(session, aid):
    if not active(session, aid):
        return None
    return {'pace_multiplier': 10, 'ignore_ordinary_travel_exhaustion': 1,
            'expires_at': active(session, aid)['expires_at'], 'carry_without_slowing': 1,
            'expiry_num': active(session, aid)['expiry_num'], 'expiry_den': active(session, aid)['expiry_den']}


@hook('journey_step')
def step(session, aid, old, nxt, regions):
    if not active(session, aid):
        return None
    supports = ['cliff', 'river', 'forest', 'broken_terrain', 'vertical_surface']
    if all(row['ordinary'] for row in regions if row['kind'] == 'water'):
        supports.append('water')
    return {'ignore_slowing': ['cliff', 'river', 'forest', 'broken_terrain'],
            'supported_kinds': supports}


@hook('journey_auto_blocked')
def awaiting_consent(session, aid):
    request = session.state.get('carry_request')
    if not request or request['carrier'] != aid or request['source'] != SOURCE or not active(session, aid):
        return None
    return session.state['actors'][request['target']]['control_mode'] == 'MANUAL'


def eligible_companion(session, carrier, target):
    actors = session.state['actors']
    if not active(session, carrier) or not session.near_visible(carrier, target):
        return False
    a, b = actors[carrier], actors[target]
    sizes = ('tiny', 'small', 'medium', 'large', 'huge', 'gargantuan')
    if a['incapacitated'] or b['incapacitated'] or a.get('carried_by') or b.get('carried_by'):
        return False
    if any(other.get('carried_by') in (carrier, target) for other in actors.values()):
        return False
    return sizes.index(str(b['size']).lower()) <= sizes.index(str(a['size']).lower())


def carry_options(session, aid):
    actors = session.state['actors']
    result = []
    request = session.state.get('carry_request')
    if request and request['target'] == aid:
        source = request['carrier']
        if eligible_companion(session, source, aid):
            for answer, verb in ((True, 'Accept'), (False, 'Decline')):
                result.append({'id': 'carry_reply:' + str(int(answer)), 'kind': 'carry_reply',
                               'payload': {'accept': answer},
                               'label': f"{verb} {actors[source]['name']}'s Body Beyond Distance request to carry {actors[aid]['name']} while travelling, without slowing the journey."})
    if active(session, aid) and not request:
        for target in sorted(actors):
            if eligible_companion(session, aid, target):
                result.append({'id': 'request_carry:' + target, 'kind': 'request_carry',
                               'auto_select': int(target not in actors[aid].get('carry_declined', [])),
                               'payload': {'target_id': target},
                               'label': f"Body Beyond Distance: ask {actors[target]['name']} to let {actors[aid]['name']} carry them while travelling; one creature of your size or smaller, without slowing your pace."})
    if owned(session, aid) and any(other.get('carried_by') == aid for other in actors.values()):
        for cell in session.adjacent(aid):
            from ..gate2_runtime_models import Position
            old = Position.model_validate(actors[aid]['position'])
            nxt = Position.model_validate(cell)
            # Setting down needs ordinary support, independently of the
            # carrier's supernatural movement. Offer every legal square.
            if nxt.z and not session.grid.roof_supported(nxt):
                continue
            if any(row['requires_support'] for row in session.regions(nxt)):
                continue
            try:
                session.step_profile(aid, old, nxt)
            except ValueError:
                continue
            result.append({'id': 'set_down:' + ','.join(str(cell.get(k, 0)) for k in ('x', 'y', 'z')),
                           'kind': 'set_down', 'payload': {'cell': cell},
                           'label': f"{actors[aid]['name']}: set the carried creature down at square ({cell['x']}, {cell['y']}), {cell.get('z', 0) * 5} feet high."})
    return result


def carry_command(session, aid, kind, payload):
    from ..journey import require
    actors = session.state['actors']
    if kind == 'request_carry':
        if not active(session, aid):
            return None
        target = payload.get('target_id')
        require(set(payload) == {'target_id'} and isinstance(target, str) and not session.state.get('carry_request')
                and eligible_companion(session, aid, target), 'Body Beyond Distance can carry one nearby, visible creature of your size or smaller, with consent.')
        session.state['carry_request'] = {'source': SOURCE, 'carrier': aid, 'target': target}
        session.emit('CARRY_REQUEST', aid, target_id=target,
                     text=f"Body Beyond Distance: {actors[aid]['name']} asks to carry {actors[target]['name']} during travel, without slowing the journey.")
        if actors[target]['control_mode'] == 'LOCAL_AUTO':
            carry_command(session, target, 'carry_reply', {'accept': True})
        return True
    if kind == 'carry_reply':
        request = session.state.get('carry_request')
        if not request or request['target'] != aid or request['source'] != SOURCE:
            return None
        require(set(payload) == {'accept'} and type(payload['accept']) is bool, 'Choose whether this creature is willing to be carried.')
        carrier = request['carrier']
        require(eligible_companion(session, carrier, aid), 'The carrying request is no longer legal.')
        if payload['accept']:
            actors[aid]['carried_by'] = carrier
            actors[aid]['position'] = dict(actors[carrier]['position'])
            actors[carrier]['carry_declined'] = [target for target in actors[carrier].get('carry_declined', []) if target != aid]
        else:
            actors[carrier]['carry_declined'] = sorted(set(actors[carrier].get('carry_declined', []) + [aid]))
        del session.state['carry_request']
        session.emit('CARRY_REPLY', aid, carrier_id=carrier, accepted=int(payload['accept']),
                     text=f"{actors[aid]['name']} {'accepts' if payload['accept'] else 'declines'} {actors[carrier]['name']}'s Body Beyond Distance carrying request.")
        return True
    if not owned(session, aid) or not any(other.get('carried_by') == aid for other in actors.values()):
        return None
    require(set(payload) == {'cell'} and any(row['kind'] == 'set_down' and row['payload'] == payload
            for row in carry_options(session, aid)), 'Choose one of the open, supported squares to set the creature down.')
    for other in actors.values():
        if other.get('carried_by') == aid:
            other['position'] = dict(payload['cell'])
            del other['carried_by']
    session.emit('SET_DOWN', aid, position=payload['cell'],
                 text=f"{actors[aid]['name']} sets the carried creature down at the chosen square.")
    return True


@hook('journey_elapsed')
def elapsed(session, aid, before, seconds, moving):
    state = active(session, aid)
    if not state:
        return None
    stopped = Fraction(0) if aid in moving else Fraction(state['stopped_num'], state['stopped_den']) + seconds
    state['stopped_num'], state['stopped_den'] = stopped.numerator, stopped.denominator
    state['stopped_seconds'] = stopped.numerator // stopped.denominator
    if session.clock() >= Fraction(state['expiry_num'], state['expiry_den']):
        end(session, aid, 'one hour has elapsed')
    elif stopped > 60:
        end(session, aid, 'stopped moving for more than one minute')


@hook('journey_state_changed')
def state_changed(session, aid):
    request = session.state.get('carry_request')
    if request and aid in (request['carrier'], request['target']) and not eligible_companion(session, request['carrier'], request['target']):
        del session.state['carry_request']
    if not active(session, aid):
        return None
    if session.state['phase'] != 'travel':
        end(session, aid, 'combat begins' if session.state['phase'] == 'combat' else 'the journey finishes')
    elif session.state['actors'][aid]['incapacitated']:
        end(session, aid, 'incapacitated')


@hook('journey_rest')
def rest(session, aid):
    # Uses key off completed Long Rests; no global resource or condition edits.
    return None

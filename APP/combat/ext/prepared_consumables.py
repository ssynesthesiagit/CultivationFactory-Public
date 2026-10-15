"""Prepared batches over the stock-materials ledger; shared by Culinary and Tea.

Public prepare/available/consume transfer real finite servings. Only a source's
completed native activity can prepare: the active activity identity and completed
work counter are checked against the immutable row. Source providers own recipe,
inputs, eligibility, and effects. There is no generic grant/GM-done command.
Physical products retain source, maker, numbers and absolute integer expiry;
transfer never resets age. Destroyed, eaten and expired portions cannot be reused.
"""
from copy import deepcopy
from . import hook
from . import material_ledger as materials
from ..journey import require, integer


def prepare(session, aid, activity, *, kind, count, lifetime, numbers, profile=None):
    from .journey_activities import current
    live = current(session, aid)
    require(live is activity and live['worked_seconds'] == live['required_seconds'],
            'Preparation requires the actual completed activity of its maker.')
    require(integer(count, 1) and integer(lifetime, 1) and isinstance(kind, str) and kind,
            'A batch needs a kind, positive portions and freshness duration.')
    from ..journey import validate_source_states
    validate_source_states(numbers); validate_source_states(profile or {})
    serial = len(session.state['events']) + 1
    key = session.state['journey_id'] + ':batch:' + str(serial)
    row = {'id':key, 'source_id':activity['source'], 'name':kind.replace('_',' ').title(),
           'kind':'prepared_consumable', 'unit':'portion', 'quantity':count,
           'acquired_at':int(session.clock()), 'expires_at':int(session.clock())+lifetime,
           'maker':aid, 'preparation':kind, 'numbers':deepcopy(numbers),
           'profile':deepcopy(profile or {}), 'provenance':activity['source']}
    materials.holdings(session, aid)[key] = row
    materials.record(session, aid, 'BATCH_PREPARED', batch=key, portions=count,
                     source=activity['source'], worked_seconds=activity['worked_seconds'])
    return row


def available(session, aid, key, *, kind=None):
    row=session.state['actors'][aid].get('material_holdings',{}).get(key)
    return row if row and row['kind']=='prepared_consumable' and row['quantity']>0 and (
        kind is None or row['preparation']==kind) and row['expires_at']>session.clock() else None


def consume(session, aid, key, amount=1, *, kind=None):
    require(available(session,aid,key,kind=kind) is not None, 'Choose your own fresh, unconsumed preparation.')
    return materials.consume(session,aid,key,amount,kind='prepared_consumable')


@hook('journey_command')
def command(session, aid, kind, payload):
    if kind not in ('prepared_transfer','prepared_destroy'):return None
    fields={'batch','quantity','recipient'} if kind=='prepared_transfer' else {'batch','quantity'}
    require(set(payload)==fields and isinstance(payload['batch'],str) and integer(payload['quantity'],1),
            'Choose an actual carried batch and whole number of portions.')
    row=materials.holdings(session,aid).get(payload['batch'])
    require(row is not None and row['kind']=='prepared_consumable', 'Choose your own physical preparation.')
    amount=payload['quantity']
    if kind=='prepared_transfer':
        recipient=payload['recipient']
        require(recipient in session.state['actors'] and recipient!=aid and session.near_visible(aid,recipient),
                'Pass portions to an adjacent creature through an unobstructed space.')
        target=materials.holdings(session,recipient)
        # A split keeps its batch identity, maker, expiry and remaining quantity.
        if row['id'] in target:
            require(all(target[row['id']][k]==v for k,v in row.items() if k!='quantity'), 'Incompatible batch identity.')
        materials.consume(session,aid,row['id'],amount)
        if row['id'] not in target:target[row['id']]={**deepcopy(row),'quantity':0}
        target[row['id']]['quantity']+=amount
        materials.record(session,aid,'BATCH_TRANSFERRED',batch=row['id'],recipient=recipient,quantity=amount)
    else:
        materials.consume(session,aid,row['id'],amount)
        materials.record(session,aid,'BATCH_DESTROYED',batch=row['id'],quantity=amount)
    return True

"""Prepared batches over the stock-materials ledger; shared by Culinary and Tea.

Public prepare/available/consume transfer real finite servings. Only a source's
completed native activity can prepare: the active activity identity and completed
work counter are checked against the immutable row. Source providers own recipe,
inputs, eligibility, and effects. There is no generic grant/GM-done command.
Physical products retain source, maker, numbers and absolute integer expiry;
transfer never resets age. Destroyed, eaten and expired portions cannot be reused.
"""
from copy import deepcopy
from fractions import Fraction
from . import hook
from . import material_ledger as materials
from ..journey import require, integer


CLOCK='prepared_consumables:clock'


def expiry(row):
    """Exact native journey-clock deadline; old integer batches remain readable."""
    return Fraction(row.get('expires_num',row['expires_at']),row.get('expires_den',1))


def created(row):
    return Fraction(row.get('created_num',row['acquired_at']),row.get('created_den',1))


def date_fields(row,start,end):
    row['acquired_at']=start.numerator//start.denominator
    row['expires_at']=end.numerator//end.denominator
    for name,value in (('created',start),('expires',end)):
        if value.denominator!=1:
            row[name+'_num']=value.numerator;row[name+'_den']=value.denominator
        else:
            row.pop(name+'_num',None);row.pop(name+'_den',None)


def record_clock(session,aid):
    now=session.clock()
    session.state['actors'][aid].setdefault('source_states',{})[CLOCK]={
        'journey':session.state['journey_id'],'num':now.numerator,'den':now.denominator}


@hook('journey_elapsed')
def elapsed(session,aid,before,seconds,moving):
    if any(r.get('kind')=='prepared_consumable' for r in session.state['actors'][aid].get('material_holdings',{}).values()):
        record_clock(session,aid)


@hook('journey_initialize')
def continue_batches(session,aid):
    actor=session.state['actors'][aid]
    prior=actor.get('source_states',{}).get(CLOCK)
    if not prior or prior['journey']==session.state['journey_id']:return
    before=Fraction(prior['num'],prior['den']);now=session.clock()
    for row in actor.get('material_holdings',{}).values():
        if row.get('kind')!='prepared_consumable':continue
        # Change clock coordinates only. Neither potency nor food age renews.
        date_fields(row,created(row)-before+now,expiry(row)-before+now)
    record_clock(session,aid)
    session.emit('BATCH_CLOCK_CONTINUED',aid,previous_journey=prior['journey'])


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
    date_fields(row,session.clock(),session.clock()+lifetime)
    materials.holdings(session, aid)[key] = row
    record_clock(session,aid)
    materials.record(session, aid, 'BATCH_PREPARED', batch=key, portions=count,
                     source=activity['source'], worked_seconds=activity['worked_seconds'])
    return row


def available(session, aid, key, *, kind=None):
    row=session.state['actors'][aid].get('material_holdings',{}).get(key)
    return row if row and row['kind']=='prepared_consumable' and row['quantity']>0 and (
        kind is None or row['preparation']==kind) and expiry(row)>session.clock() else None


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
        record_clock(session,recipient)
        materials.record(session,aid,'BATCH_TRANSFERRED',batch=row['id'],recipient=recipient,quantity=amount)
    else:
        materials.consume(session,aid,row['id'],amount)
        materials.record(session,aid,'BATCH_DESTROYED',batch=row['id'],quantity=amount)
    return True

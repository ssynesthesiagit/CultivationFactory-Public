"""Default-inert source-owned journey quotes, payments and elapsed clocks.

Public consumers: admitted journey ability commands and Qi Path cost riders.
Call pay only after source ownership/admission validation. Quotes are pure;
receipts derive from actual deductions. No providers preserve printed costs.
Unused clocks create no state and completed journeys retain elapsed-time limits.
"""
from fractions import Fraction
from types import MappingProxyType
from .ext import hook,run_strict
from .journey import require
CLOCK='system:journey.payments'


def clock(session,aid):
    state=session.state['actors'][aid].get('source_states',{}).get(CLOCK)
    if state is None:return session.clock()
    return Fraction(state['elapsed_num'],state['elapsed_den'])+session.clock()-Fraction(state['local_num'],state['local_den'])


def checkpoint(session,aid):
    now=clock(session,aid);local=session.clock()
    state=session.state['actors'][aid].setdefault('source_states',{}).setdefault(CLOCK,{})
    state.update(elapsed_num=now.numerator,elapsed_den=now.denominator,local_num=local.numerator,local_den=local.denominator)
    return now


def quote(session,aid,source,costs):
    """Pure printed/effective resource amounts and named reduction provenance.

    journey_payment_quote(session,aid,source,readonly_printed) -> dict|None:
    {resource: {amount: nonnegative int <= printed, source: native source id}}.
    Disjoint resource quotes compose. Multiple policies for the same resource
    must use their shared source owner rather than silently stack reductions.
    """
    require(type(source) is str and bool(source),'A native source is required for a journey payment.')
    listed={}
    for resource,amount in costs:
        require(type(resource) is str and type(amount) is int and amount>=0,
                'Journey costs require native resources and nonnegative integer amounts.')
        listed[resource]=listed.get(resource,0)+amount
    result={r:{'amount':n,'listed_amount':n,'discount_source':''} for r,n in listed.items()}
    claimed=set()
    for reply in run_strict('journey_payment_quote',session,aid,source,MappingProxyType(listed)):
        require(isinstance(reply,dict),'Journey payment quotes must be resource mappings.')
        for resource,row in reply.items():
            require(resource in listed and resource not in claimed and isinstance(row,dict)
                    and set(row)=={'amount','source'} and type(row['amount']) is int
                    and 0<=row['amount']<=listed[resource] and type(row['source']) is str and bool(row['source']),
                    'Journey payment quotes require one named source and a bounded integer amount per resource.')
            claimed.add(resource);result[resource].update(amount=row['amount'],discount_source=row['source'])
    return result


def affordable(session,aid,source,costs):
    return all(session.state['actors'][aid]['resources'].get(r,0)>=row['amount'] for r,row in quote(session,aid,source,costs).items())


def pay(session,aid,source,costs):
    """Pay exactly the native quote and strictly notify its receipt consumers."""
    actor=session.state['actors'][aid];amounts=quote(session,aid,source,costs)
    require(all(actor['resources'].get(r,0)>=row['amount'] for r,row in amounts.items()),'This creature cannot pay the journey cost.')
    now=checkpoint(session,aid);receipts=[]
    for resource,row in amounts.items():
        actor['resources'][resource]-=row['amount']
        session.emit('RESOURCE_SPENT',aid,source=source,resource_id=resource,**row,remaining=actor['resources'][resource])
        receipts.append({'source':source,'actor_id':aid,'resource_id':resource,**row,
                         'event_index':len(session.state['events'])-1,'turn':now//6})
    for receipt in receipts:run_strict('journey_payment_completed',session,aid,receipt)
    return receipts


@hook('journey_initialize')
def initialize_clock(session,aid):
    state=session.state['actors'][aid].get('source_states',{}).get(CLOCK)
    if state is not None:
        local=session.clock();state.update(local_num=local.numerator,local_den=local.denominator)


@hook('journey_elapsed')
def elapsed_clock(session,aid,before,seconds,moving):
    if CLOCK in session.state['actors'][aid].get('source_states',{}):checkpoint(session,aid)

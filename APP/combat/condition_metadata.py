"""Additive condition provenance shared by source observers and counterprocedures.

condition_metadata(ctx, subject, effect, current_data) -> metadata dict | None
is a strict pure query after the existing condition_state policy has settled.
New metadata cannot replace known values or alter duration/application decisions.
Nested documents compose; conflicting leaves fail atomically. Without a provider
this returns the original data without adding keys, events or serialization.
"""
from copy import deepcopy
from . import ext


def primitive(value,depth=0):
    if depth>32:return False
    if type(value) in (int,str):return True
    if isinstance(value,list):return all(primitive(v,depth+1) for v in value)
    return isinstance(value,dict) and all(type(k) is str and primitive(v,depth+1) for k,v in value.items())


def merge(current,extra):
    for key,value in extra.items():
        if key not in current or current[key] is None:current[key]=deepcopy(value)
        elif isinstance(current[key],dict) and isinstance(value,dict):merge(current[key],value)
        elif current[key]!=value:raise ValueError('Conflicting native condition metadata: '+key)
    return current


def augment(ctx,subject,effect,data):
    answers=ext.run_strict('condition_metadata',ctx,subject,effect,deepcopy(data))
    if not answers:return data
    result=deepcopy(data)
    for answer in answers:
        if not isinstance(answer,dict) or not primitive(answer):
            raise ValueError('Native condition metadata must contain only primitive source facts')
        merge(result,answer)
    return result

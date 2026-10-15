"""Owned, durable choices from a source's printed choose-one acquisition grant.

Used by Weather's starting Sign. Callers provide the source's legal choices and
must establish the printed grant; this module validates source ownership and
keeps the first selection through native conditions/replay. Missing historical
choices are repaired through a player decision, including on AI turns. This is
not permission to acquire an additional talent or to bypass access/Realm gates.
"""
from .alternative_payments import owned

CONDITION='condition:source.acquisition_choice'


def recorded(actor, source, key):
    return next((c.data['selection'] for c in actor.conditions.values()
        if c.condition_id==CONDITION and c.source_definition_id==source
        and c.data.get('key')==key and c.source_actor_id==actor.entity_id),None)


def choose(engine, actor, source, key, options, *, intent, labels, prompt):
    if not owned(engine,actor,source):
        raise ValueError('An acquisition choice requires its owned source.')
    old=recorded(actor,source,key)
    if old is not None:
        if old not in options:
            raise ValueError('The recorded acquisition choice is no longer legal.')
        return old
    from .ext.needle import ask,checkpoint_id,CHOICE
    selected=ask(engine,intent,checkpoint_id(engine,'ACQUIRE_'+key,actor.entity_id),actor,
        CHOICE+'acquisition_'+key,options,labels=labels,prompt=prompt,name='Choose a learned option',
        feature_id=source,automatic=False,allow_decline=False)
    if not selected:
        return None
    engine._apply_condition(actor,CONDITION,source,actor.entity_id,expires_on='UNTIL_REMOVED',
        data={'key':key,'selection':selected[0],'label':'Learned choice: '+labels[selected[0]]})
    return selected[0]


def descriptors(source_id, sheet):
    from . import ext
    return [row for rows in ext.run_strict('acquisition_choices',source_id,sheet) for row in (rows or [])]


def validate(source_id, sheet, selections):
    """Validate concrete character-learning choices before saving advancement."""
    specs=descriptors(source_id,sheet)
    if selections is None:
        return {}  # historical/pending choice, never an automatic selection
    if not isinstance(selections,dict) or set(selections)!={s['key'] for s in specs}:
        raise ValueError('Choose each option this source grants.')
    result={}
    for spec in specs:
        selected=selections[spec['key']]
        if not isinstance(selected,list) or len(selected)!=spec.get('count',1) or len(set(selected))!=len(selected) or any(s not in spec['options'] for s in selected):
            raise ValueError('Choose the printed number of different learned options.')
        result[spec['key']]=list(selected)
    return result


def source_options(sheet):
    """Source-defined learnable options absent from the canonical record index."""
    from . import ext
    return [row for rows in ext.run_strict('acquisition_source_options',sheet) for row in (rows or [])]


def apply_source_options(sheet, rows):
    """Replay validated native learning records into their source's choices."""
    from copy import deepcopy
    out=deepcopy(sheet)
    for saved in rows:
        available={row['id']:row for row in source_options(out)}
        record=available.get(saved.get('id'))
        if record is None:
            raise ValueError('An acquired source option no longer has a public source definition.')
        choices=out.setdefault('acquisition_choices',{}).setdefault(record['source_id'],{})
        values=choices.setdefault(record['key'],[])
        if record['value'] not in values:
            if not record['legal'] and not saved.get('gm'):
                raise ValueError('This source option does not meet its learning rules.')
            values.append(record['value'])
    return out

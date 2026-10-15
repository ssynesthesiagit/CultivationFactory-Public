"""Authoritative scene inputs shared by information abilities and travel.

External facts enter through the table owner's encounter/journey request. Actor
self-declarations have an explicit restricted vocabulary; GM facts are separate.
The sealed battlefield is the durable source, never a receipt invented by a
consumer. Missing keys mean unknown. Values have explicit access and authority;
consumer plug-ins register their vocabulary through source_fact_validate.
"""
from copy import deepcopy
from . import ext


def prepare(battlefield, rows, actor_ids):
    if rows is None:
        return battlefield
    if not isinstance(rows, list) or len(rows) > 256:
        raise ValueError('Scene sources must be a list of at most 256 records.')
    subjects = set(actor_ids) | {'scene'} | {f"object:map.{int(o['id'])}" for o in battlefield.get('map_objects', [])}
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'subject_id', 'authority_actor_id', 'authority_role', 'facts'}:
            raise ValueError('A source needs its subject, authority actor, authority role and facts.')
        subject, author, role = row['subject_id'], row['authority_actor_id'], row['authority_role']
        if any(not isinstance(v,str) for v in (subject,author,role)) or subject not in subjects or author not in actor_ids or role not in ('gm', 'actor') or subject in seen:
            raise ValueError('Choose one real scene subject and an admitted source authority.')
        if role == 'actor' and subject != author:
            raise ValueError('An actor can declare only their own facts.')
        facts = row['facts']
        if not isinstance(facts, dict) or not facts or len(facts) > 128:
            raise ValueError('A source needs a bounded set of typed facts.')
        for key, fact in facts.items():
            if (not isinstance(key, str) or not isinstance(fact, dict)
                    or set(fact) - {'value', 'access', 'cl', 'dc', 'creator_id'} or 'value' not in fact
                    or fact.get('access', 'surface') not in ('surface', 'internal', 'concealed')
                    or ('cl' in fact and (type(fact['cl']) is not int or fact['cl'] < 1))
                    or ('dc' in fact and (type(fact['dc']) is not int or fact['dc'] < 0))
                    or ('creator_id' in fact and (not isinstance(fact['creator_id'],str) or fact['creator_id'] not in actor_ids))):
                raise ValueError('Facts need a typed value, access and whole-number authority/DC.')
            from .observer_information import primitives
            if not primitives(fact):
                raise ValueError('Facts must use integer/string JSON data.')
            answers = ext.run_strict('source_fact_validate', key, fact['value'], role)
            if not any(answer is True for answer in answers):
                raise ValueError('Unknown or unauthorized scene fact: ' + key)
            if any(answer is False for answer in ext.run_strict('source_fact_context_validate',key,fact,row,battlefield,tuple(actor_ids))):
                raise ValueError('This scene fact conflicts with its native subject or map: '+key)
        seen.add(subject)
        result.append(deepcopy(row))
    return {**deepcopy(battlefield), 'encounter_sources': result}


def facts(battlefield, subject):
    """Authoritative facts only, not permission for a viewer to learn them."""
    row = next((r for r in battlefield.get('encounter_sources', []) if r['subject_id'] == subject), {})
    return deepcopy(row.get('facts', {}))


def authority(battlefield, subject):
    return next((r['authority_actor_id'] for r in battlefield.get('encounter_sources', [])
                 if r['subject_id'] == subject), None)

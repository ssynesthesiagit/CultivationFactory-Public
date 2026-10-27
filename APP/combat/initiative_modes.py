"""General genesis Initiative modes; no subscriber keeps the exact old draw.

initiative_modes(engine, actor) -> {advantage?, disadvantage?,
surprise_disadvantage?, ignore_surprise_disadvantage?} | None is a pure query
before MatchState exists. Only true boolean flags contribute. Ignoring Surprise
removes only that source of Disadvantage, never an unrelated contribution.
"""
from . import ext


def mode(engine, actor):
    replies=ext.run_strict('initiative_modes',engine,actor)
    declaration=declarations(engine._roster_setup.get('initiative_surprise'),engine.actor_templates)
    if actor.entity_id in declaration.get('actor_ids',[]):
        replies=[*replies,{'surprise_disadvantage':True}]
    return combine(replies)


def declarations(value, roster):
    """Validate a table-owner fact, consumed by this encounter's Initiative.

    CombatService supplies the authority; callers cannot impersonate a creature
    or copy a fact from another encounter. Absence retains the legacy format.
    """
    if value is None:return {}
    if not isinstance(value,dict) or set(value)!={'actor_ids','authority'} or value['authority']!='table_owner':
        raise ValueError('Invalid Initiative declaration authority')
    ids=value['actor_ids']
    if not isinstance(ids,list) or any(not isinstance(a,str) or a not in roster for a in ids) or len(set(ids))!=len(ids):
        raise ValueError('Surprise must name distinct creatures in this encounter')
    return {'actor_ids':sorted(ids),'authority':'table_owner'} if ids else {}


def combine(replies):
    """Combine independent sources without erasing unrelated Disadvantage."""
    keys={'advantage','disadvantage','surprise_disadvantage','ignore_surprise_disadvantage'}
    if any(not isinstance(r,dict) or set(r)-keys or any(type(v) is not bool for v in r.values()) for r in replies):
        raise ValueError('Invalid Initiative mode contribution')
    flags={key:any(r.get(key,False) for r in replies) for key in keys}
    disadvantage=flags['disadvantage'] or (flags['surprise_disadvantage'] and not flags['ignore_surprise_disadvantage'])
    return ('ADVANTAGE' if flags['advantage'] else 'DISADVANTAGE') if flags['advantage'] != disadvantage else 'NORMAL'

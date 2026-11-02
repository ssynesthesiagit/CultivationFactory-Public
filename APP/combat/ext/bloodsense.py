"""Bloodsense's five printed facts, projected privately from authored blood sources.

No physiology, corpse cause, spill, or sample identity is inferred from damage
types, creature names or a hidden character sheet. Missing evidence is unknown.
Recent spill (one hour) and freshly spilled blood (an authored fresh_until_seconds)
are separate facts: the former never silently lifts the Invisible exception.
"""
from . import hook
from .blood_bloodied import is_bloodied
from .. import senses
from ..encounter_sources import elapsed_seconds, sources, studied_sources


def direction(observer, position):
    dx, dy = position.x - observer.position.x, position.y - observer.position.y
    dz = position.z - observer.position.z
    compass = (('north' if dy < 0 else 'south' if dy > 0 else '') +
               ('east' if dx > 0 else 'west' if dx < 0 else ''))
    vertical = 'above' if dz > 0 else 'below' if dz < 0 else ''
    return ' and '.join(part for part in (compass, vertical) if part) or 'here'


def recent(row, now):
    at = row.get('occurred_at_seconds')
    return type(at) is int and 0 <= now - at <= 3600


@hook('observer_information')
def readings(engine, observer):
    if not observer.active or 'bloodsense' not in senses.of(engine, observer):
        return []
    now = elapsed_seconds(engine)
    authored = list(sources(engine, 'blood'))
    eligible = []
    for row, position, actor, obj in authored:
        probe = actor if actor is not None else senses.cell_probe(position)
        distance = (engine._distance_actor_to_actor(observer, actor) if actor is not None
                    else engine._distance_actor_to_cell(observer, position))
        reach = senses.reach(engine, observer, 'bloodsense', probe)
        if reach <= 0 or distance > reach:
            continue
        from ..targeting import line_of_effect
        clear = line_of_effect(engine, observer, target=actor, destination=position)
        if clear:
            eligible.append((row, position, actor, obj))
    fresh = {row.get('source_key') for row, _, _, _ in eligible
             if row.get('kind') == 'spill' and row.get('exposed') == 1 and recent(row, now)
             and type(row.get('fresh_until_seconds')) is int and now < row['fresh_until_seconds']
             and isinstance(row.get('source_key'), str) and row['source_key']}
    studied = [row for row in studied_sources(engine, observer, 'blood')
               if row.get('kind') == 'sample'
               and isinstance(row.get('source_key'), str) and row['source_key']]
    facts = []
    for row, position, actor, obj in eligible:
        kind = row.get('kind')
        if kind == 'creature' and actor is not None and actor.entity_id != observer.entity_id:
            if row.get('circulation') != 1 and row.get('exposed') != 1:
                continue
            invisible = any(c.condition_id == 'condition:typed.invisible' for c in actor.conditions.values())
            if invisible and row.get('source_key') not in fresh:
                # A printed talent may already lift invisibility for this pair.
                if not senses.sees_hidden(engine, observer, actor):
                    continue
            if is_bloodied(actor):
                facts.append({'ability': 'Bloodsense', 'kind': 'direction',
                              'direction': direction(observer, position)})
            if senses.ordinary_sight_perceives(engine, observer, actor):
                facts.append({'ability': 'Bloodsense', 'kind': 'injury', 'creature_id': actor.entity_id,
                              'injured': int(actor.current_hp < actor.maximum_hp)})
        elif kind == 'spill' and row.get('exposed') == 1 and recent(row, now):
            facts.append({'ability': 'Bloodsense', 'kind': 'recent_spill',
                          'direction': direction(observer, position), 'within_last_hour': 1})
        elif kind in ('corpse', 'sample') and row.get('obvious') == 1:
            visible = (senses.ordinary_sight_perceives(engine, observer, actor) if actor is not None
                       else senses.perceives_object(engine, observer, obj) if obj is not None
                       else senses.perceives_cell(engine, observer, position))
            if not visible:
                continue
            reference = obj.object_id if obj is not None else str(row.get('label') or kind)
            if kind == 'corpse' and type(row.get('likely_blood_loss')) is int and row['likely_blood_loss'] in (0, 1):
                facts.append({'ability': 'Bloodsense', 'kind': 'corpse_cause', 'source': reference,
                              'likely_blood_loss': row['likely_blood_loss']})
            elif kind == 'sample' and isinstance(row.get('source_key'), str) and row['source_key']:
                for other in studied:
                    if other is row:
                        continue
                    facts.append({'ability': 'Bloodsense', 'kind': 'sample_match', 'sample': reference,
                                  'studied_sample': str(other.get('label') or 'previously studied sample'),
                                  'same_creature': int(row['source_key'] == other['source_key'])})
    return facts

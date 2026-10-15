"""Earth Court information on the owner's connected Foundation Spaces.

Uses the shared source-owned Foundation cell provider and physical-contact
model. Only represented diagnostic facts are reported; vibration of a
concentration effect must be explicitly represented, never guessed.
"""
from . import effect, hook
from .earth_responses import foundation_cells, FOUNDATION_SOURCES

COURT = 'TAL_EARTH_TREMOR_COURT_HEARING'
LISTEN = 'condition:typed.tremor_court'


@hook('compile_action')
def court_action(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    if typed.get('source') == COURT:
        return action.model_copy(update={'target_kind': 'SELF', 'parameters': {**action.parameters,
            'typed': {**typed, 'effects': [{'type': 'tremor_court'}]}}})


def contact(engine, owner, actor):
    from ..contact_geometry import conducts, touches_cells, components
    from ..flight import profile
    from ..senses import is_creature
    if not is_creature(actor) or not actor.active or not components(engine, owner):
        return False
    from .. import zones
    cells = set()
    for zone in zones.typed_zones(engine):
        action = engine.action_catalog.get(zone.source_definition_id)
        if zone.owner_id == owner.entity_id and action is not None and (action.parameters.get('typed') or {}).get('source') in FOUNDATION_SOURCES:
            cells.update((p.x, p.y, p.z) for p in zone.affected_cells)
    known_xy = {(x, y) for x, y, z in cells}
    cells.update((x, y, owner.position.z) for x, y in foundation_cells(engine, owner) if (x, y) not in known_xy)
    if touches_cells(engine, actor, cells) and conducts(engine, owner, actor):
        return True
    # The printed exception reads a flying creature within five feet of the
    # contact plane; it grants no sight or information beyond that plane.
    flying = profile(engine, actor)
    if actor.position.z > 0 and (flying.speed_ft or flying.hover):
        ground_probe = actor.model_copy(update={'position': actor.position.model_copy(update={'z': actor.position.z - 1})})
        return touches_cells(engine, ground_probe, cells) and conducts(engine, owner, ground_probe)
    return False


def contacts(engine, owner):
    return [actor for actor in engine.state.actors.values() if contact(engine, owner, actor)]


@effect('tremor_court')
def listen(ctx, row):
    from ..contact_geometry import components
    if not components(ctx.engine, ctx.actor):
        return
    ctx.engine._apply_condition(ctx.actor, LISTEN, ctx.source, ctx.actor.entity_id,
        expires_on='START_OF_SOURCE_NEXT_TURN', data={'label': 'Tremor Court Hearing: locate creatures touching the solid surfaces you claimed with Set Foundation until your next turn starts; no sight or identity is granted'})
    # Diagnostics are a live query for the marker's lifetime, not stale facts
    # captured only at casting. Their scene qualifiers remain explicit.


@hook('observer_information')
def diagnostics(engine, viewer):
    if not any(c.condition_id == LISTEN for c in viewer.conditions.values()):
        return None
    from ..falling import supported
    from ..flight import profile
    output = []
    for target in contacts(engine, viewer):
        facts = []
        started = max((e.sequence for e in engine.events if e.event_type == 'TURN_STARTED' and e.actor_id == target.entity_id), default=0)
        moved = any(e.sequence > started and e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == target.entity_id
                    and len(e.payload.get('path') or []) > 1 and not e.payload.get('teleport') for e in engine.events)
        if not moved:
            facts.append('standing still')
        if any(c.condition_id == 'condition:typed.prone' for c in target.conditions.values()):
            facts.append('Prone')
        flying = profile(engine, target)
        if not supported(engine, target) and not target.climbing and (flying.speed_ft or flying.hover):
            facts.append('flying within 5 feet of the surface')
        for condition in target.conditions.values():
            for fact in condition.data.get('contact_diagnostics', []):
                if fact in ('moving quickly', 'standing still', 'Prone', 'carrying a heavy load', 'burrowing',
                            'flying within 5 feet of the surface', 'concentrating on a vibrating technique'):
                    facts.append(fact)
        if 'moving quickly' in facts and 'standing still' in facts:
            facts.remove('standing still')
        facts = sorted(set(facts))
        output.append({'text': 'Tremor Court Hearing: a contact is ' + ', '.join(facts) + '.',
                       'ability': 'Tremor Court Hearing', 'subject': target.entity_id, 'facts': ', '.join(facts)})
    return output


@hook('pinpoint_target')
def court_location(engine, viewer, target):
    if any(c.condition_id == LISTEN for c in viewer.conditions.values()) and contact(engine, viewer, target):
        return True

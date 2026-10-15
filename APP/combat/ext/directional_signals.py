"""Read coarse bodily signals without revealing a creature's location or identity."""
from . import effect, hook

SIGNAL = 'condition:typed.directional_signal'
READ = 'system:combat.sense_directional_signals'


def readings(engine, observer):
    """Directions and relative Realm only, for native same-plane encounter actors."""
    from ..table_advance import realm_of
    from .weather_signs import BANDS
    def level(actor):
        bundle = next((b for b in getattr(engine,'typed_bundle_documents',()) if b.get('actor_id')==actor.entity_id),{})
        return int(bundle.get('cl') or 1)
    own = BANDS.index(realm_of(level(observer)))
    audience = {s.lower() for s in observer.creature_types}
    output = set()
    for subject in engine.state.actors.values():
        for held in subject.conditions.values():
            data = held.data or {}
            if held.condition_id != SIGNAL or not audience.intersection(data.get('audience') or []):
                continue
            dx,dy = subject.position.x-observer.position.x,subject.position.y-observer.position.y
            direction = ('north' if dy<0 else 'south' if dy>0 else '') + ('east' if dx>0 else 'west' if dx<0 else '')
            direction = direction or 'here'
            other = BANDS.index(realm_of(level(subject)))
            relative = 'higher Realm' if other>own else 'lower Realm' if other<own else 'same Realm'
            output.add(f'{direction}: {relative}')
    return sorted(output)


@hook('match_start')
def add_reader(engine):
    from ..gate2_runtime_models import ActionDefinition
    if not any('signal_audience' in str((a.parameters.get('typed') or {}).get('effects') or []) for a in engine.action_catalog.values()):
        return
    engine.action_catalog[READ] = ActionDefinition(source_definition_id=READ,display_name='Sense Hell-Signaled directions',
        owner_id='*',economy='NONE',resolution_kind='TYPED',target_kind='SELF',parameters={
            'typed':{'effects':[{'type':'read_directional_signals'}],'numbers':{},'riders':[]},
            'description':'Sense the direction and relative Realm of Hell-Signaled creatures. This reveals no identity, distance, or precise location.'})


@hook('additional_actions')
def offer_reader(engine,actor):
    return [READ] if READ in engine.action_catalog and readings(engine,actor) else []


@hook('candidate_allowed')
def reader_allowed(engine,actor,candidate,action):
    if action is not None and action.source_definition_id==READ:
        return bool(readings(engine,actor))
    return None


@hook('ai_candidate_allowed')
def ai_reader_allowed(engine, actor, candidate, action):
    """Informational reads are player-directed; never let them occupy AI turns.

    The shared AI menu applies this restraint only to built-in AI choices, so
    player controlled creatures retain the free sensing option.
    """
    if action is not None and action.source_definition_id == READ:
        return False
    return None


@effect('read_directional_signals')
def read_signal(ctx,row):
    from . import note
    for reading in readings(ctx.engine,ctx.actor):
        note(ctx.engine,ctx.source,ctx.actor,'Hell-Signaled presence — '+reading+'.')

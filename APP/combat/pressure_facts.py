"""Published numeric-pressure provenance, shared by Qi instability and Guard.

Only actual native DAMAGE_COMMITTED receipts count. Unknown kinds remain
unknown strings, with exact action, source actor and affected actor identity;
there is no sphere, damage-type, ability-name or private capability inference.
"""


def committed_pressure_kinds(engine, subject_id, source_id, source_actor_id):
    """Kinds this exact source actually delivered to this subject."""
    return frozenset(e.payload['pressure_kind'] for e in engine.events
        if e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == source_id
        and e.actor_id == source_actor_id and subject_id in e.target_ids
        and isinstance(e.payload.get('pressure_kind'), str) and e.payload['pressure_kind'])

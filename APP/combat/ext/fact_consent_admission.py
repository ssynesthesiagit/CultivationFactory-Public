"""Private native admission records; no source schema means no behavior."""
from . import hook


@hook('fact_admission_schema')
def scene_boundary_schema(session, source, subject, kind):
    if source == 'system:journey.scene' and kind == 'scene_end':
        return {'authority': 'table_owner', 'value_type': 'text', 'maximum_seconds': 1,
                'description': 'The table owner ends this meaningful scene.'}
    return None


@hook('presentation_hidden_conditions')
def private_declarations(engine, actor):
    from ..fact_consent_admission import CONDITION
    return [c.instance_id for c in actor.conditions.values() if c.condition_id == CONDITION]

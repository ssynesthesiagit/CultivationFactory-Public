"""Private native admission records; no source schema means no behavior."""
from . import hook


@hook('presentation_hidden_conditions')
def private_declarations(engine, actor):
    from ..fact_consent_admission import CONDITION
    return [c.instance_id for c in actor.conditions.values() if c.condition_id == CONDITION]

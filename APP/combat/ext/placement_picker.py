"""Presentation of the engine's general lazy square-placement checkpoint."""
from . import hook


@hook('choice_options')
def choice_options(engine, intent, checkpoint, reactor_id, choice_id, context):
    from ..placement_menu import CHOICE
    from .needle import option_spec
    return option_spec(choice_id, context, CHOICE)


@hook('choice_map_pick')
def map_pick(engine, choice, context):
    from ..placement_menu import CHOICE
    if context.get('reaction_source_id') == CHOICE:
        return {'instruction': 'Click any highlighted legal square for this ability.'}
    return None

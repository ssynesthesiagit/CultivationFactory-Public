"""Presentation of the engine's general lazy square-placement checkpoint."""
from . import hook


def area_previews(engine, actor, action, rows):
    """Native footprints for the selected lazy action only, at its paused origin.

    Used by placement_menu.resolve; the eager root menu stays geometry-free.
    This is display data, never a source of legal aims or AI creature knowledge.
    """
    from ..action_geometry import activate, point
    from ..typed_executor import area_cells
    from ..zones import wall_cells_for
    from .needle import cell_id

    area = (action.parameters.get('typed') or {}).get('area') or {}
    if not area.get('size_ft'):
        return {}
    previews = {}
    for row in rows:
        if row.area is None:
            continue
        # resolve() runs before execution activates the selected origin. Scope
        # each native row explicitly, so relayed cones/lines start there too.
        with activate(engine, actor, action.source_definition_id, row.metadata.get('effect_origin')):
            cells = (wall_cells_for(engine, actor, row.destination, int(area['size_ft']),
                                    int(area.get('thick_ft') or 5)) if area.get('shape') == 'wall'
                     else area_cells(engine, point(engine, actor), row.destination, area))
        previews[cell_id(row.destination, include_altitude=True)] = [
            cell.model_dump(mode='json') for cell in cells]
    return previews


@hook('choice_options')
def choice_options(engine, intent, checkpoint, reactor_id, choice_id, context):
    from ..placement_menu import CHOICE
    from .needle import option_spec
    return option_spec(choice_id, context, CHOICE)


@hook('choice_map_pick')
def map_pick(engine, choice, context):
    from ..placement_menu import CHOICE
    if context.get('reaction_source_id') == CHOICE:
        import json
        areas = json.loads((context.get('choice_trigger') or {}).get('space_areas') or '{}')
        ids = {option['id'] for option in choice.get('options') or []}
        trigger = context.get('choice_trigger') or {}
        action = engine.action_catalog.get(trigger.get('source_definition_id'))
        label = trigger.get('action_name') or 'This ability'
        return {'prompt': (action.parameters.get('placement_prompt') if action else None)
                         or f'{label}: choose a square.',
                'instruction': 'Click any highlighted legal square for this ability.',
                'areas': {key: value for key, value in areas.items() if key in ids}}
    return None

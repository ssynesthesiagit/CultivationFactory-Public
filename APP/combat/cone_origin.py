"""General cone targeting alternatives for compiled human and AI action menus.

The ordinary action excludes the origin. A placed cone's inclusion alternative preserves
all costs, augments, recipient policies and effects; only geometry changes.
Both go through native placement, knowledge previews, acceptance and replay.
"""


def targeting_alternatives(action):
    """Return the original and an explicit origin-including cone alternative.

    Only cones explicitly placed at the aim point get an alternative. Unplaced
    cones run from their user; missing origin metadata grants no alternative.
    Explicit origin-inclusion specifications are unchanged. The general
    targeting_variant_of parameter binds availability to the original action's
    loadout without creating a second augment family or effect implementation.
    """
    typed = (action.parameters or {}).get('typed') or {}
    area = typed.get('area') or {}
    if (action.resolution_kind != 'TYPED' or area.get('shape') != 'cone'
            or not area.get('size_ft') or 'include_origin' in area
            or not area.get('placed')):
        return (action,)
    included_typed = {**typed, 'area': {**area, 'include_origin': True}}
    if (typed.get('zone_spec') or {}).get('shape') == 'cone':
        included_typed['zone_spec'] = {**typed['zone_spec'], 'include_origin': True}
    parameters = {**action.parameters, 'targeting_variant_of': action.source_definition_id,
                  'typed': included_typed}
    parameters.pop('augment_loadout', None)
    included = action.model_copy(update={
        'source_definition_id': action.source_definition_id + '.origin_included',
        'display_name': action.display_name + ' — include the cone’s starting space (the cone can affect creatures there too)',
        'parameters': parameters,
    })
    return (action, included)

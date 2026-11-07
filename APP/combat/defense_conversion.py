"""Source-qualified Immunity conversion shared by Venom and Maw defenses.

Legacy True replies convert all matching Immunity. A mapping may instead name
exact modifier_ids / feature_ids; it cannot convert an unselected overlapping
source. Inputs are the defenses that the native resolver already found legal.
This pure fold creates no immunity, condition, duration, or acquisition right.
"""


def immunity_result(modifier_ids, feature_ids, replies):
    modifiers, features = set(modifier_ids), set(feature_ids)
    selected_modifiers, selected_features = set(), set()
    all_sources = False
    for reply in replies:
        if type(reply) is bool:
            all_sources = all_sources or reply
            continue
        if not isinstance(reply, dict) or set(reply) - {'modifier_ids', 'feature_ids'}:
            raise ValueError('Immunity conversion requires bool or source-qualified identifiers')
        for key, selected in (('modifier_ids', selected_modifiers), ('feature_ids', selected_features)):
            values = reply.get(key, [])
            if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
                raise ValueError('Immunity conversion identifiers must be nonempty strings')
            selected.update(values)
    if all_sources:
        return False, bool(modifiers or features)
    converted = bool(modifiers & selected_modifiers or features & selected_features)
    remains = bool(modifiers - selected_modifiers or features - selected_features)
    return remains, converted

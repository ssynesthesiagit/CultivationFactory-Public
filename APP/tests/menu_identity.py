"""Choose the base table action by its stable compiled mechanic identity.

Option and alternate-payment rows have suffixes and are intentionally excluded.
"""


def action_group(menu, mechanic_id):
    for group in menu["actions"]:
        if group["source_definition_id"].endswith("." + mechanic_id):
            return group
    raise AssertionError(f"No base action for {mechanic_id!r}; available: "
                         f"{[group['source_definition_id'] for group in menu['actions']]}")

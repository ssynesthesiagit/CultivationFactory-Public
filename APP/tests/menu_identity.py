"""Choose a table action by its stable compiled mechanic identity."""


def action_group(menu, mechanic_id):
    return next(group for group in menu["actions"]
                if group["source_definition_id"].endswith("." + mechanic_id))

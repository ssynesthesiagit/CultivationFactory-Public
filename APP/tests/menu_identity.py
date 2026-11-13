"""Choose the base table action by its stable compiled mechanic identity.

Callers that need one specific option pass its full id (``system:combat.ready:counter``);
callers that only need the mechanic pass the base id and get its first family member.
"""


def matches_source(source_id, identity):
    """Match an exact source, its dot-delimited typed suffix, or its colon-delimited family.

    Compiled rows such as ``system:combat.ready:<option>`` and ``test:critical:<actor>``
    extend the base identity after a ``:``; those are the same mechanic. A different
    mechanic that merely shares a prefix (``test:critical_roll``) does not match.
    """
    family = identity.rstrip(":") + ":"
    return source_id == identity or source_id.endswith("." + identity) or source_id.startswith(family)


def candidate(combat, mid, name, target=None):
    """Legacy selector retained for existing wax test consumers."""
    return next(c for c in combat._load_session(mid).engine.legal_candidates()
                if c.display_name == name and (target is None or target in c.target_ids)).candidate_id


def candidate_by_source(combat, mid, source, target=None, destination=None):
    candidates = combat._load_session(mid).engine.legal_candidates()
    matches = [c for c in candidates if matches_source(c.source_definition_id, source)
               and (target is None or target in c.target_ids)
               and (destination is None or c.destination == destination)]
    assert matches, f"No legal candidate for {source!r} targeting {target!r} at {destination!r}"
    return matches[0].candidate_id


def action_group(menu, mechanic_id):
    for group in menu["actions"]:
        if matches_source(group["source_definition_id"], mechanic_id):
            return group
    raise AssertionError(f"No base action for {mechanic_id!r}; available: "
                         f"{[group['source_definition_id'] for group in menu['actions']]}")

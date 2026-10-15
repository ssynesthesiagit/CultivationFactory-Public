"""Movement classification shared by repayment and custom travel plug-ins.

Borrowed Second uses these predicates at activation and typed execution.
Custom travel rows declare self_movement=True; movement_role='rider' keeps a
mixed power available while its voluntary travel is denied. Unannotated ordinary
movement rows retain their historical primary classification. Target movement
and forced movement are independent of the user's repayment restriction.

Meridian Lock uses technique_categories to classify CP-funded techniques.
Extension effects declare technique_categories=['movement'] or ['escape'] in
sealed reviewed effect metadata, including permissions that grant passage or
immunity without directly moving a creature. Classification does not execute
effects, infer rules from prose, or change Borrowed Second's travel predicate.
"""


def moves_user(row: dict) -> bool:
    """Whether executing this row voluntarily moves (or grants movement to) its user."""
    return (row.get("applies_to") in (None, "self")
            and (row.get("self_movement") is True
                 or row.get("type") in ("movement", "teleport", "move_to_aim", "borrowed_second_step",
                                        "shadow_exchange", "shadow_long_road", "veil_escape_move")))


def primary_moves_user(typed: dict) -> bool:
    """Whether an activation primarily moves its user, excluding declared riders."""
    return any(moves_user(row) and row.get("movement_role") != "rider"
               for row in typed.get("effects", []))


def technique_categories(row: dict) -> frozenset[str]:
    """Pure leaf classification; callers traverse their nested effect packets.

    Built-in movement/escape effects retain their classification. Custom effects
    opt in with a JSON list of technique_categories. A movement rider is still
    part of a movement technique for a prohibition on purchasing techniques.
    """
    declared = row.get('technique_categories')
    categories = set(declared) if isinstance(declared, list) else set()
    kind = row.get('type')
    if (moves_user(row) or kind in {'movement', 'teleport', 'forced_movement',
                                  'rider_step', 'general_rider_step',
                                  'general_flight', 'flight'}
            or (kind == 'speed' and row.get('applies_to') == 'self'
                and int(row.get('flat') or 0) > 0)):
        categories.add('movement')
    if (kind in {'escape_grapple', 'escape_binding', 'escape_source_restraint', 'trap_escape'}
            or (kind in {'end_effect', 'remove_condition'} and
                (set(row.get('conditions') or [row.get('condition')]).intersection(
                    {'grappled', 'restrained', 'bound_limb', 'netted'})
                 or 'movement' in (row.get('categories') or [])))):
        categories.add('escape')
    return frozenset(categories)

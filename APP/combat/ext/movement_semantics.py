"""Movement classification shared by repayment and custom travel plug-ins.

Borrowed Second uses these predicates at activation and typed execution.
Custom travel rows declare self_movement=True; movement_role='rider' keeps a
mixed power available while its voluntary travel is denied. Unannotated ordinary
movement rows retain their historical primary classification. Target movement
and forced movement are independent of the user's restriction.
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

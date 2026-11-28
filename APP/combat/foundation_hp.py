"""Saved creation HP shared by foundation_combat and foundations3 compile hooks.

Creation has already applied these formulas to the sheet's maximum. Consumers
evaluate that saved contribution, not a new projection of the installed catalog.
"""
from stage2.formulas import evaluate_formula


def creation_hp(mechanics, pb):
    """Return the saved Foundation's flat maximum-HP contribution at this PB."""
    return sum(evaluate_formula(row['formula']['root'], {'pb': pb}).value
               for row in mechanics['hp_maximum_modifiers'])

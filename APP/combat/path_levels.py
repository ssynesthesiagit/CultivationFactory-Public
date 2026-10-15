"""Validated native Path levels shared by source acquisition and runtime compilation.

Attainment (or owning_path_level) is learned progression. effective_cl, when
explicitly supplied, is the current activation ceiling, including zero under
Realm Suppression. Its absence means unsuppressed learned progression. A
historical effective-only record is supported; booleans/strings are rejected.
Nothing here grants a Path or derives its level from a display name.
"""


def path_level(row, *, effective=False):
    for key in ('attainment', 'owning_path_level', 'effective_cl'):
        if key in row and (type(row[key]) is not int or not 0 <= row[key] <= 20):
            raise ValueError('Native Path levels must be whole numbers from 0 to 20.')
    learned = next((row[key] for key in ('attainment', 'owning_path_level', 'effective_cl') if key in row), None)
    if learned is None:
        raise ValueError('The native Path must supply its actual level.')
    return row['effective_cl'] if effective and 'effective_cl' in row else learned

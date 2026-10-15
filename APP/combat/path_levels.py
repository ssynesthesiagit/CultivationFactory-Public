"""Owning-Path CL from the existing portable multi-Path sheet contract.

Cai Clan and Predictive Step share this reader. It grants no Path, feature,
suppression or access permission. An existing single-Path sheet without an
explicit row keeps its previous compiled CL. Runtime suppression remains with
the public cultivation limit/suppression producers.
"""


def path_row(sheet, path_id):
    return next((row for row in (sheet.get('path_and_subpath') or {}).get('paths') or []
                 if isinstance(row, dict) and row.get('path_id') == path_id), None)


def effective_cl(sheet, path_id, fallback):
    row = path_row(sheet, path_id)
    return int(row['effective_cl']) if row is not None else int(fallback)

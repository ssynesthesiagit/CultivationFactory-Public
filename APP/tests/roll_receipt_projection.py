"""Stock-replay projection that ignores display-only roll receipts.

`mode_sources` rows are roll-reason receipts: additive hover/feed metadata that never
resolves, consumes or changes a roll. combat/roll_reasons.py's module docstring defines
them as display-only. Replay comparisons drop only that key, at every depth, so every
mode, total, choice and state field is still compared byte-for-byte.

Used by tests/test_a2_glass_stock.py and tests/test_roll_receipt_stock_projection.py.
"""


def without_roll_explanations(value):
    """Return value with every mode_sources key removed (dicts and lists, recursively)."""
    if isinstance(value, dict):
        return {key: without_roll_explanations(item) for key, item in value.items()
                if key != 'mode_sources'}
    if isinstance(value, list):
        return [without_roll_explanations(item) for item in value]
    return value

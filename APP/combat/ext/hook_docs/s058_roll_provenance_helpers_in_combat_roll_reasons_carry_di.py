"""Roll provenance helpers in combat.roll_reasons carry display-only receipts in
the matching d20_scope or ExplainedMode. remember(engine, rows) appends only to
the innermost frame; sources are {effect, owner, kind, why} strings and do not
resolve modes. condition_rows/roll_rules accept with_sources=True to retain
condition identity alongside each rule. typed_executor.ranged_attack_crowded
is the pure nearby-hostile query shared by resolution and attack previews.
"""

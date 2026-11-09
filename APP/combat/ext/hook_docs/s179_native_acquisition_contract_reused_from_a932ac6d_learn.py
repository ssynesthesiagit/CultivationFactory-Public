"""Native acquisition contract reused from a932ac6d (Learning/Life):
learning_choices(sheet, record_id, catalog_talents, draft=None) -> optional
list of {id,label,options:[{id,name}]}. Supports Sphere and talent acquisitions;
previews grant nothing and never truncate legal options.
learning_receipt(sheet_before, kind, record_id, selected, catalog_talents) ->
optional validated primitive receipt. Errors abort before the atomic save.
learning_projection(sheet, normalized_advancement) -> sheet: pure projection
of persisted receipts, without re-testing historical pre-learning conditions.
advancement_options(options, sheet, catalog_talents) -> options: pure optional
presentation transform. All four hooks are default-inert for other records."""

"""feature_access_policy(feature_id) -> dict | None: one recorded acquisition policy.
feature_access_projection(sheet, feature_id, source) -> sheet | None: project validated source.
feature_available(engine, actor, feature_id) -> bool | None: feature availability query.
resource_generation_allowed(engine, actor, row, reason, event) -> bool | None: gate a row.
table_fact_validate(engine, fact) -> bool | None: validate an owner/GM fact document.
save_roll_adjustment(engine, target, ability, dc, roll, source_id, phase, context) -> int: add a save bonus.
All six hooks are default-inert; multiple strict providers are validated by their consumers."""

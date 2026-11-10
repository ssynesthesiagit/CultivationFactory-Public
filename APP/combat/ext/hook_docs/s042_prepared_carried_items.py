"""Prepared carried items:
  compile_resources(info) also receives owner_sheet, the same normalized sheet
  passed to compile_actions. Read-only optional context: existing providers need
  not read it. Culinary rations use explicit equipment.sealed_field_rations
  entries, never grant unrecorded preparation or unlimited servings.
  Each entry records kind, count, age_hours, maker_cl, maker_pb, maker_key_mod.
  Bitter/Courage custom conditions may carry data.ration_save_category = poison,
  disease, contamination, bodily_toxin or morale, plus native origin_save or
  repeat_save provenance. Unknown category/save provenance grants no new save.
  Native Poisoned and Frightened conditions are recognized directly; the shared
  qi_path.affliction_category(engine, source_definition_id) reader supplies
  reviewed poison/disease categories from affliction_sources.json."""

"""Reviewed primary-menu exemptions keyed by printed ID; public software-only test data."""

EXEMPTIONS = {
  "FORMATIONS_BASE_COLLAPSE_ARRAY": {
    "printed_sha256": "10323a4613fa06f07d776510a037d37703578181d5823f24843d3774b9dbac92",
    "reason": "Requires an owned Formation Array within 120 feet, absent on a minimal fresh table. formations.compile_actions seals the Collapse Array button."
  },
  "TAL_BARRAGE_QUICK_DRAW_ARSENAL": {
    "printed_sha256": "fef139d8809802d1078acad74a5f7c18da9379b8378e4624665c07d1c72e56fb",
    "reason": "Requires an eligible carried ranged/thrown weapon to draw or stow; a bare minimal sheet has none. barrage_second_pass.quick_draw_action uses the sealed builder."
  },
  "tianxia.subpath.body.sky_treading_tendon_school.feature.tread_the_empty_sky": {
    "printed_sha256": "8865abb4724f14b5c9f6f5731b2967b0aab10c8a3baabdaf464748db980af8e0",
    "reason": "Requires being airborne, at least 1 Stamina, and no flight prohibition. sky_treading.tread_button is sealed by compile_actions; a grounded minimal table must not offer it."
  },
  "tianxia.talent.beauty.beauty_in_motion": {
    "printed_sha256": "b286ca810d36b79a932990b29645a6f6809fa07d55946f8f64c6e6b929230792",
    "reason": "Requires at least 10 feet of own-turn movement first. beauty_motion.activation publishes a sealed button; a fresh turn without movement must not offer it."
  },
}

"""Reviewed primary-menu exemptions keyed by printed ID; public software-only test data."""

EXEMPTIONS = {
  "FORMATIONS_BASE_COLLAPSE_ARRAY": {
    "printed_sha256": "aaeb8ecb1757bd9c17f4cffdc101f441f56252870abb130210e74b1ebc90765a",
    "reason": "Requires an owned Formation Array within 120 feet, absent on a minimal fresh table. formations.compile_actions seals the Collapse Array button."
  },
  "TAL_BARRAGE_QUICK_DRAW_ARSENAL": {
    "printed_sha256": "9e74257e78345359b30e2fa15fcb8c72bbec09c2002b3d1bd52e54b12cdb404b",
    "reason": "Requires an eligible carried ranged/thrown weapon to draw or stow; a bare minimal sheet has none. barrage_second_pass.quick_draw_action uses the sealed builder."
  },
  "tianxia.subpath.body.sky_treading_tendon_school.feature.tread_the_empty_sky": {
    "printed_sha256": "f0d78d42c4833b1c2ffd18234f4d0700d9c7364bdd9178631b7c0050835e9a68",
    "reason": "Requires being airborne, at least 1 Stamina, and no flight prohibition. sky_treading.tread_button is sealed by compile_actions; a grounded minimal table must not offer it."
  },
  "tianxia.talent.beauty.beauty_in_motion": {
    "printed_sha256": "a98ecee8ba168884ecc7ee507dafcec8d7341e614cee1947d40a6e3525f70b85",
    "reason": "Requires at least 10 feet of own-turn movement first. beauty_motion.activation publishes a sealed button; a fresh turn without movement must not offer it."
  },
}

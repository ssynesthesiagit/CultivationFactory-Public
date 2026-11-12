"""Guard-opening profile seam (INS7D):
  guard_break_profile(ctx, subject, row) -> dict | None is a strict transactional
  transform of one break_guard application before its condition is recorded.
  Providers receive a fresh row and may return beneficiary_id, next, axe,
  expires_on and label. The caster remains source_actor_id for expiry/replay;
  beneficiary_id restricts whose attacks use and consume the opening. None
  preserves the ordinary source/anyone rule. Shared by shield/cover openings;
  no ability identifier is tested in guard_broken. Shieldhook Adept opts in only
  for its owned Shield-Catching Beard effect. Sand-Born Footwork reuses existing
  miss, choice, terrain and check-hazard contracts with no native engine change."""

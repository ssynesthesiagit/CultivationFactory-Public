"""Creature-qualified sense range (A2GMISSUB2):
  sense_target_range(engine, viewer, sense, seen) -> nonnegative integer | None
  is a pure query for a minimum range against this particular creature. It runs
  only for an existing sense, before Pure Darkness reductions, and never for
  unrestricted_only queries. Providers must check their owned feature and the
  subject's recorded eligibility; square probes must not qualify as creatures.
  None/no provider preserves range. Physical sight, total cover and concealment
  rules still apply. This does not grant general Blindsight, reveal terrain or
  broaden a general sense displayed on the sheet. Exorcist uses it for Ghost Sight.
"""

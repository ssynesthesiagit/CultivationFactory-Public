"""Strike declaration (plug-in damaging actions):
  A compiled action whose damage comes from its own effect kind (not one of
  ai_tactics.STRIKE_KINDS, and with no action.damage or attack_bonus) must set
  parameters["delivers_strike"] = True, or the AI planner treats it as a
  non-attack and drops it from attacks, attack_range and offers. Set it only on
  rows that actually deliver damage to a target. Recovery and utility rows
  (Pick up, Escape a grapple) must never set it; their damage price is for
  scoring only. tests/test_custom_damage_producer_strikes.py pins the producers."""

"""INS7E rolled-damage settlement:
  typed_damage_roll_adjustment(ctx, dice, roll) -> signed int, DieReplacement or None runs after
  an actual typed damage draw and before its damage event/cache/defenses. This
  complements confirmed_damage_roll_adjustment for native weapon packets.
  No provider preserves the draw and amount. Strict, transactional choices
  must gate on owned rows and actual hit/source provenance. Fixed amounts and
  non-damage rolls bypass it. Consumers can settle choose-either die rerolls or
  other printed post-roll adjustments without redrawing/copying an attack.
  Red Execution Discipline uses these hooks once per Full Cultivation Session,
  and existing fresh_zero_hp/mark events for optional Martial Focus recovery.
  cultivation_session_completed(completed=1) is an explicit source effect
  notifying that a real Full Cultivation Session finished; no action, time
  bypass or rest permission is granted. Missing/false completion is inert."""

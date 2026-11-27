"""INS7E essence source effects (existing effect and fresh_zero_hp contracts):
  essence_profile records genuine/independent (integers) and kind (string) on
  actual effect recipients; inert unless a source explicitly types this effect.
  Constructs/illusions/clones/disposable summons/refund bodies require an
  independent genuine source. restore_essence requires fully_rebuilt=1 and
  clears only per-owner essence-consumption receipts, never ordinary healing.
  qi_devourer uses existing fresh_zero_hp, compile_block and Needle choice
  hooks. No ability/core special case or new native checkpoint is introduced.
"""

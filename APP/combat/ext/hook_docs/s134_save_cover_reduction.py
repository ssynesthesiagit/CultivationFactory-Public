"""save_cover_reduction(engine, target, ability, source_id, cover) -> None or
nonnegative integer levels is a pure strict query after save_bonus_details.
It reduces only an already supplied named cover contribution, through levels
0/2/5/99, and removes the same amount from the recorded save modifier. It does
not invent geometry or affect unnamed/other bonuses. No provider or absent
cover retains historical save bytes. target_cover uses the actual d20 source
actor and catalog action, never an enclosing unrelated active intent.
"""

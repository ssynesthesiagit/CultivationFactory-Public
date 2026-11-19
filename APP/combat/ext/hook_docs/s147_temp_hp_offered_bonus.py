"""temp_hp_offered_bonus(engine, subject, amount, source_id, source_actor_id, *, consume) -> nonnegative int
or None is a strict general addition to positive Temporary HP offers, after
denial and before interception and max-existing-Temporary-HP clamping.
consume=False is a pure estimate; consume=True commits provider allowances.
Missing providers preserve the original offer. Invalid replies abort the
transaction through CheckpointError. No ability identity enters core."""

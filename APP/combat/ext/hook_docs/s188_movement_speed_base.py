"""movement_speed_base(engine, actor) -> (feet, source_id, readable_name) | None.

Pure, default-inert base replacement for walking (also mounted/charge pools).
At most one provider supplies nonnegative integer feet. movement_speeds.speed
keeps the creature's own fixed adjustments around that replacement, then adds
ordinary motion and speed hooks and applies final halving/carrying limits.
The provider supplies only its base, never composes the recipient's modifiers.
The shared result carries the replacement delta and ordinary speed-hook
provenance to movement_explanations; diagnostics never recompose a base.
Mounts uses this for a bonded controlled pair. Unmounted actors return None.
Example provider: def base(engine, actor): return None
No state, events, modifiers or choices are produced by this query.
"""

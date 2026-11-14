"""A2GBODSUB6 object-area admission: object_damage technique rows can specify
needs (all tags), needs_any (at least one tag), and forbids (no listed tags).
Missing lists preserve historical selection. Explicit boolean component tags
are honored by object_rules.has_tag, with material/kind fallback otherwise.
Every qualifying object is snapshotted before any damage and hit once.
Map seeding carries fragile/temporary_barrier/formation_anchor/world_scale
classifications as booleans; immunity, Resistance and thresholds remain native."""

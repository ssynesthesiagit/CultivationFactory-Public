"""weapon_source_family(item, family) -> True/False/None. Strict pure query used by
factory_compiler._fits when a delivery names a source-defined weapon family (for
example "greatbow", from Star-Piercing Greatbow). item is the authoritative catalog
item from factory_authoring.starting_kits.item_definition, never the action label.
None means no opinion. If any provider answers, any(True) admits the weapon and
all-False rejects it; a non-bool answer raises ValueError. With no answers the
legacy name substring rule applies. It is run with run_strict, so an exception
unwinds the caller's transaction. Providers must be pure: no spending, events,
prompts or state writes. Owning a Source does not grant proficiency; it only
classifies the weapon for that Source's own delivery rules."""

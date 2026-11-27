"""Candidate query presence declarations (combat.ext shared helpers).

present_if(effects=(), features=(), conditions=(), parameters=(), typed_keys=(),
effect_keys=(), action_ids=(), action_suffixes=(), action_contains=())
returns the existing hook(present=...) predicate: present(engine) -> bool.
All supplied tokens are alternatives (OR), including alternatives across kinds.
False promises that the provider returns None for EVERY candidate in this
fight revision. Default hook registrations remain unfiltered. Keep actor-level
guards in the provider; presence never grants an option or changes hook order.

action_presence(actions) is the pure token reader over an iterable of actions;
it returns fresh token sets (frozensets), with conditions empty, without reading
or changing any fight state. fight_presence(engine) calls that same reader,
adds all actors' held conditions, and caches the result for these declarations.
It indexes the action catalog, including supplemental/system rows, rather than
only the current actor: another creature can impose a target or movement gate.
Features include spirit_traditions.feature_of(action), raw typed.source and
legacy source-map values (as read by Shadow). Conditions use every held
condition_id. Parameters and typed_keys include even false/None-valued keys
because some guards distinguish absence from a false value. Effects and
effect_keys traverse effects/options and their nested packets, including
on_hit, on_fail and condition_data. Broad nested matches can retain an inert
provider but cannot drop a veto. Source suffix/substring guards read the same
catalog source_definition_id strings; no display-name inference is indexed.

The index shares enumeration_cache(engine)'s revision/invalidation/lifetime.
It is computed once per revision, never written to saved state, and not kept
outside candidate_pass. Existing _selected retains providers if indexing or
predicate evaluation raises. Do not declare presence for guards depending on
transient projections or candidate metadata not represented in this index.
No new hook point, dispatch behaviour, query cache, engine flag or ability
implementation is introduced.
"""

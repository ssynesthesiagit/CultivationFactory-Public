"""Shared live sense-grant eligibility: sense_grant_allowed(engine, actor, grant, seen) -> bool | None. Called for each retained sense row before merging ranges.
seen is None for the sheet query and a creature or lightweight cell probe for
reach. False excludes only that grant; other sources of the same sense remain
available. Providers are pure, may not mutate rows, and must accept cell probes.
Timed Sense rows resolve their action's typed source/option_of as feature_id
(falling back to the stored source), just like compiled grants,
so eligibility can qualify one source without suppressing independent senses.
Mountain Core uses it for Stone Sense's current contact and moving-ground-target
restriction. The default is inert for all other sense sources.
Fruiting Body uses it for its live owned field and creature qualification;
its sense_rows provider expands only that source's condition list with the
public owner-scoped mark requirement IDs. No-target reads retain restricted
metadata for enumeration; cell probes cannot qualify that creature-only grant."""

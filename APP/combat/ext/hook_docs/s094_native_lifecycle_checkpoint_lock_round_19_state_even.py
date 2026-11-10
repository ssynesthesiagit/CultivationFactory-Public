"""Native lifecycle checkpoint (lock round 19): state_event(engine, event) receives
one recorded CombatEvent after native state processing on Gate2, Gate3 and
Gate4. Return None. It is strict, including nested events, so failures roll back
an active transaction; recursive delivery is bounded at eight calls. Providers
must require their owned condition/data and record all changes through existing
events. With no applicable provider it adds no event, choice or state. This is
separate from Gate4's event hook; a lifecycle consumer registers only here, never
at both points. Standard condition forfeiture uses this checkpoint."""

"""Source fact admission (combat.fact_consent_admission, reused from 1be03085):
fact_admission_schema(session, source, subject, kind) -> one dict or None;
fact_admission_validate(session, source, subject, kind, value) -> None, strict;
fact_admitted(session, record) -> None, strict;
combat_fact_admission_allowed(session, source, subject, kind) -> True or None.
No schema/admission subscriber rejects input with no mechanical change. Schemas
specify authority, bounded value type, maximum_seconds, subject_access and
combat_condition_data_paths. The NativeFactSession adapter exposes detached
condition and read-only modifier snapshots. Only whitelisted condition-data
paths may change; no mechanical values, new effects, consent or outcomes may
be declared. WORLD_FACT_V1 is an operator-only recorded-input policy, never a
fighter candidate. The same binding revalidates on commit, recovery and replay.
foundations3 consumes this contract for exact-source GM minor-penalty facts;
its willing-recipient wrapper and optional cleanup use the existing choice
transport. No owned Pulse row means no new combat action/recipient option."""

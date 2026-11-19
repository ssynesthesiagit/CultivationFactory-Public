"""before_d20(engine, request, intent) -> None | {source_id: str, natural_result: int}.
Strict transactional pre-draw choice; request contains actor_id, reason, modifier,
and mode, never a natural result, total, or future random value. Exactly one
producer may return a replacement. Read native d20_context() and match its
actor/reason before using ability/skill metadata; absent metadata stays unknown.
Consent/costs occur before raw_d20. The ordinary deterministic slot is then
consumed to preserve unique roll identities, and D20_REWRITTEN records original
and effective rolls with timing=before_roll. Post-roll hooks see the effective
record, with effective dice displaying the replacement value. The unused raw
values remain only in the rewrite event. Raw rerolls bypass this hook. No reply
preserves draws/events/state.
Steady Handler uses this hook only for its owner's Wisdom (Animal Handling)."""

"""Shared Body scene seam (combat/ext/body_modes_scene_resources.py, owner of the
Nine-Star/Nine-Star-adjacent Body scene contract): a family module never stores
its own scene identity, availability or paid-activation receipt.
body_mode_profiles(bundle) -> list[{source: str, name: str}] | None: one entry
per acquired Body scene source. The seam's own default provider derives the
profile from the compiled typed Body features, so Body Refining needs no
registration; a narrower family provider may declare its own source instead.
No profile answer leaves scenes, conditions, numbers and resources unchanged.
condition:typed.body_scene carries {source, scene_id, source_cl, label} for an
owning creature only; a combatant with no profile gets no record, and the
condition is never a player-facing label (presentation_hidden_conditions).
condition:typed.cultivation_suppression carries the table-owner fact's system,
effective_cl or feature_id, suppressed=1, its receipt and its exact remaining
scene time. It never erases anatomy, resources, selection or spent allowances;
availability alone goes false until the recorded expiry, which runs on the
round/slot clock and never on a rest, reroll or caller-supplied boolean.
cultivation_effective_cl(engine, actor, path_id) -> int|None and
cultivation_feature_available(engine, actor, feature_id) -> bool|None are the
upstream pure query adapters; body_modes_scene_resources.available,
effective_body_cl and journey_available read them without resetting payments.
fact_admission_schema may return authority="table_owner" for the suppression
kind, and fact_admission_validate checks the printed source rule, Source CL and
scope; the value enters only through fact_consent_admission.declare_world on
JourneyStore.admit(kind='body_suppression'), with a bounded duration.
journey_combat_bundle carries {scene_id, clock, suppressions+remaining time}
into the encounter without mutating the journey bundle; match_start re-applies
each fact as its own condition, and journey_snapshot_actor drops the scene and
suppression records from the continuation snapshot so a later encounter in the
same journey re-derives them (a renewed scene, one fresh condition per live
fact) instead of importing a stale identity or a spent expiry counter.
CombatService.journey_end_scene(journey_id,
revision, reason) is the only scene renewal: it commits SCENE_ENDED with
service-derived table_owner authority, advances the opaque scene identity and
strictly notifies journey_scene_end(session, old, new) -> None. Rest,
inactivity, reopen and encounter transitions never end a scene.
paid_activation_resolved(engine, actor, receipt) -> None, strict, is a
notification derived from real native RESOURCE_SPENT/RESOURCE_GAINED events of
the same source inside one transaction: {source, paid>0, payment_sequences,
completion_sequence, turn, round, source_cl}. The original action or reaction
remains the only payment authority; the receipt grants no resource."""

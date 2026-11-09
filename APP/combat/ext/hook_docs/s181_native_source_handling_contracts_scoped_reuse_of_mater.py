"""Native source/handling contracts (scoped reuse of materials 5ca14d86/132a12b1):
journey_admission(session, actor_id, kind, payload, provenance) -> True|None:
typed external facts only; owner authorization/revision checked by JourneyStore.
None leaves a fact unsupported; validation errors abort without writing.
journey_source_sheet(sheet, session, actor_id) -> sheet|None: pure transform
of the compiled Source sheet on every recompile; None keeps it. A source that
persists its own acquisition returns the sheet re-decorated from that state, so
later menus, views and combat bundles read the actual acquisition. It runs when
the source is acquired and again when the next journey opens the creature, so a
carried-over character is compiled from what it actually learned.
journey_acquisition(session, actor_id, source, payload, sheet) -> {sheet,
acquisition_id}|None: the one typed acquisition seam for a Source. None leaves
the source unsupported; a payload that is not this source's exact selection
command raises and aborts before any write, so a caller can never supply
feature IDs or a receipt. The provider derives the earned features from current
rule state and returns the exact sheet plus the receipt the caller commits.
journey_acquired(session, actor_id, source, acquisition_id, userdata_root) -> None, strict:
notification after that acquisition is committed; each consumer rebuilds its
own projection. No subscriber means no edits.
journey_initialize(session, actor_id) -> None, strict: notification when a
new journey is opened (JourneyStore.create, for every creature, after its
persisted continuation is applied and before the replay checkpoint); each
consumer re-anchors its own deadlines to the new journey clock. No subscriber
means no edits.
journey_initialized(session) -> None, strict: notification once per created
journey, after every creature's journey_initialize and still before the replay
checkpoint; a consumer that reads or rewrites the whole roster belongs here,
because inside journey_initialize a later creature still carries its previous
deadline. Per-creature work stays in journey_initialize. No subscriber means
no edits.
journey_persistent_fields() / journey_shared_fields() -> tuple[str]|None:
actor continuation / finite shared registry keys, respectively. Empty is inert.
A persisted field travels into the next journey, so a source that stores its
own acquisition and timed effects there continues them. Harvest manifestation and
ordinary Exhaustion attribution use fact_admission_validate; neither declaration grants
an ability or injury.
journey_view(state, viewer_id) -> state|None: pure redaction of provider-owned
private inputs; absent viewer is a public projection, never table-owner access.
journey_combat_bundle(bundle, session, actor_id) -> bundle|None: seal actual
acquired inventory/context at combat entry; None leaves the bundle unchanged.
compile_bundle info now also supplies acquired owned_ids and ability mods,
shared with compile_actions; these are context, never new grants.
journey_initialize(session, actor_id) -> None:
strict notification when an actor joins a journey session; providers restore
owned continuation state. No Primordial Dust counters owned means no writes.
journey_scene_end(session, previous, current) -> None:
strict notification on a scene transition, with previous and current scene IDs;
providers renew owned scene uses. No Primordial Dust counters owned means no writes.
journey_encounter_settled(session, actor_id, engine, actor) -> None:
strict notification after a finished encounter snapshot; material consumers may
persist their evented physical changes and other consumers may persist committed
encounter consumption into journey facts. No subscriber means no edits.
A condition whose data carries journey_transient=1 is bookkeeping its owner rebuilds
(the hidden concentration deadline); the snapshot skips it instead of forcing a GM checkpoint.
journey_snapshot_actor(actor, session, actor_id, engine) -> actor|None:
pure transform before encounter_snapshot; a consumer that transfers its own
physical state separately may exclude its own transport condition from a copy.
None preserves all normal snapshot validation and encounter conditions.
journey_continued_concentration(concentration) -> 'carry'|None: whether this
exact concentration instance may continue across a short encounter break. None
keeps the ordinary table checkpoint and grants no continuation to any other
source; any other reply is an error.
journey_exhaustion_applied(session, actor_id, count, ordinary) -> None: strict
notification of ordinary Exhaustion levels already applied by the journey; a
provider may only record its own source state and never edits the levels. None
leaves every actor's Exhaustion untouched.
journey_initialize(session, actor_id) -> None: strict notification after a new
journey session exists; a source may seal its own empty per-actor state block.
No subscriber leaves the stored session exactly as written.
journey_scene_end(session, previous_scene, next_scene) -> None: strict
notification after a committed scene boundary; a provider resets only its own
per-scene source state. None leaves every actor unchanged.
Native outside-combat work and continuation contracts (journey_activities,
journey_checks, journey_effects, journey_institutions and restful_dream_journey):
journey_before_command(session, actor_id, kind, payload) -> None: strict pre-mutation
gate run before any journey command mutates state; it may raise to refuse the command, and its return value is ignored. No subscriber leaves the command unchanged. Party-wide transitions must consider every affected actor's decisions.
activity_spec(session, actor_id, source, parameters) -> {seconds:int,label:str}
admits one source-owned procedure; activity_started(session, actor_id, activity), activity_validate(session, actor_id, activity), activity_finished(session, actor_id, activity) and
activity_interrupted(session, actor_id, activity) are strict transactional callbacks. Only actual
activity_work advances worked_seconds; interruption never grants completion.
activity_command_interrupts(session, owner_id, activity, acting_id, kind, payload)
-> True | None lets a source observe its recipient's interruption. No opt-in
leaves ordinary commands and state unchanged.
journey_short_rest(session, actor_id), journey_resource_spent(session, actor_id, resource_id, before, after, source),
journey_world_fact_committed(session, receipt) and journey_check_rolled(session, actor_id, spec) and journey_check_finished(session, actor_id, spec) are strict committed
notifications; no subscriber grants recovery or invents a fact.
journey_check_profile(session, actor_id, spec) -> {bonus?,merit?,advantage?} is
source-owned. journey_combat_bundle(bundle, session, actor_id) -> bundle | None
and character_source_projection(sheet, actor_record) -> sheet | None strictly
compose native admitted source state. character_source_projection_needed(sheet)
-> True | None opts into the cold actor read; absence skips that IO entirely.
journey_initialize(session, actor_id), journey_encounter_settled(session, actor_id,
engine, creature), journey_scene_end(session, old, new) are strict continuation
notifications. Settlement's creature is the immutable terminal combat actor;
subscribers importing continuing effects must read the admitted conditions in
session.state['actors'][actor_id]['encounter_snapshot'], which honors explicit
GM resolution of timed effects, rather than reimporting the terminal effects.
journey_snapshot_actor(actor,session,actor_id,engine) -> ActorState
| None is a strict pure transform of a copy before generic snapshot admission.
Missing subscribers preserve ordinary continuation and serialized state.
journey_auto_priority(session, actor_id, offered_option) -> int | None is a pure
strict ranking query over the actor's complete personally visible menu. Smaller
values rank first; no subscriber retains ordinary travel ordering. It cannot
remove options or authorize a choice owned by Manual/Ask me. Check, activity,
institution and Restful Dream providers share journey_decisions.autonomous.
fact_admission_schema(session,source,subject,kind) -> schema | None admits a
source-scoped actor or table-owner fact; absent/ambiguous schemas reject input.
reaction_admission (contract above) is the strict gate before consent/payment.
after_attack_roll=1 on compiled attacked rows moves their consent/effect window
after ATTACK_ROLLED and before hit consequences; missing opt-ins retain behavior."""

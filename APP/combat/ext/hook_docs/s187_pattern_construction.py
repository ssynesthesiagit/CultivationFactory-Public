"""Pattern construction and physical consumable contracts.

  ordinary_consumable_spec(engine, owner, item) -> dict | None
                                                 strict source-owned lookup of one ordinary physical item's typed
                                                 definition (effects and optional numbers, area, name, fragile)
                                                 for consumable_payloads, after carry confirms the owner actually
                                                 holds that item_id in its compiled starting kit. Keyed by the
                                                 engine's sealed bundle documents for that owner. Default inert:
                                                 with no subscriber, or a definition for that item_id, the item
                                                 stays an unknown mortal object and grants no weapon, damage,
                                                 condition or stock. Item names never classify an item; only an
                                                 actual typed source can define one.

Physical pattern construction / ordinary consumable delivery (MGR-T14).
Reused public contracts from stock-materials 5ca14d86f:
journey_admission(session, actor_id, kind, payload, reason) -> True only for a
validated typed external fact. JourneyStore.admit checks GM, provenance and
revision, locks the registry, and journals the input for deterministic replay.
journey_view(state, viewer_id) -> redacted copy or None; never grant knowledge.
journey_shared_fields() / journey_persistent_fields() -> owned field names to
retain in the journey registry; absent fields leave old sessions unchanged.
journey_combat_bundle(bundle, session, actor_id) -> copied transformed bundle or
None. CombatService seals the result before match creation; source modules own
only their projection, not core resolution. pattern_construction restores its
own actual elapsed-time devices through match_initialize; material modules may
use the same seam. compile_bundle info now also includes owned_ids and mods,
matching the upstream stock-materials interface.
ordinary_consumable_spec(engine, owner, carried_item) -> one typed specification
or None. consumable_payloads.available/reserve/release/activate use existing
carry quantity/possession contracts. Unknown and magical items are inert.
Specifications contain name, effects, optional numbers and area; they must be
authored by a source plug-in, never inferred from arbitrary labels or a GM's
generic approval. Trap stores only integer/string JSON and the stable item key.
formations.pulse_origins(engine, owner, action) publishes controlled active
array centers. remote_origins combines these with Flow Line Strike's Eye/Node
origins. Candidate and execution checks bind that same selected origin.
journey_encounter_settled(session, actor_id, verified_terminal_engine, creature) -> None:
strict notification inside the locked journey resume transaction, after native
health/resources are imported. Providers may reconcile their own source state
from committed events/objects/zones, never infer grants from tags. Errors abort
the save. No provider preserves previous resume behavior. pattern_construction
uses native elapsed rounds and terminal component snapshots so a second fight
cannot repair a Node or restore a spent/expired device.
Source-specific learning: Formation Training publishes six native first-pattern
buttons only while its source fact is unknown. The owned selection is a
permanent condition in combat or the journaled source field in a journey;
absence grants no Basic Pattern. Trap construction likewise asks the actual
learner to choose Dexterity/Intelligence when no acquired key choice exists.
Legacy bundles without learning/stock contracts retain their learning/stock menus.
Veiled Road reuses fact_consent_admission.admit_choice from the Soul-Collateral
owner's committed generic interface (7073de536). The recipient's controller
supplies source/scope/intent-bound willingness, independently of team relation.
Only the recipient and explicit readers can inspect the typed receipt; it
expires at the current turn's end and replays with the accepted intent.
The phased activation_admission seam is dispatched only by
technique_interception.prepare, before and after interception; it returns the
documented cancellation dictionary rather than a boolean.
Veiled Road's refusal arrives through activation_admission, so it cannot spend
the caster's Bonus Action or mark the recipient as affected by a Pulse, while
activation_end still cleans up both admitted and declined attempts.
Unknown ordinary item recipes enter via the existing GM journey_admit path,
kind ordinary_consumable_definition. It requires actual acquired item identity,
ordinary nature, exact source text/SHA, explicit fragility and a bounded typed
specification. It grants no stock, abilities, CP, hits or successful outcomes.
Native saves/damage/conditions and physical area consumers resolve the item.
Canonical sealed definitions cannot be overridden. Recipe receipts are private
to the recorded owner and replay as inputs; undeclared definitions stay unknown.
Physical Trap devices opt in through placed.physical_device. trap_devices
projects native objects with AC = stored Trap save DC and HP = 2 x stored CL,
using native object updates/damage. Zone removal disables the object; actual
object destruction ends the trap and destroys only explicitly fragile loads.
Nodes/Eyes of Prepared Arrays use the printed AC 15 and 3x/5x source CL HP.

journey_short_rest(session, actor_id) -> None, strict notification after the
native one-hour downtime command, parallel to journey_rest's eight-hour Long
Rest. Source providers alone refresh their own limits; no subscriber grants
no HP, CP, Hit Dice or other recovery. Nourishing Cycle persists actual native
recipient benefit across journey/encounter boundaries, and clears its own
once-per-short-rest gate only on either completed rest, never just a new fight.

Integration uses Mason's committed public continuation interface names from
425d34d1e/c0e1b3665: journey_combat_bundle runs before pool/setup sealing;
journey_snapshot_actor(creature, session, actor_id, terminal_engine) -> copied
RuntimeActorState or None is a pure source-owned snapshot projection, default
unchanged; journey_encounter_settled receives the original committed creature
after snapshot import. These are shared source boundaries, not alternate
inventory, object identity or scene schemas.
ordinary_consumables uses these same continuation hooks for physical Ball
Bearings/Caltrops areas: map-bound canonical zone JSON in its own persistent
actor field, no item refund or invented duration. Its journey_step hook asks
for native scene resolution on contact; absent owned spills stays inert.

Native elapsed-time scene opt-in: roster.rules.scene_window="elapsed_rounds_v1"
permits one or more actual actors to take normal initiative turns even with
no opposing team. It changes only early victory detection; maximum_rounds,
actual incapacitation, costs, choices, rolls, movement and reactions remain
native. No flag preserves ordinary combat creation/termination and stock state.
CombatService.journey_start_scene takes explicit teams and defaults to one
six-second round. journey_act open_scene uses the same API and normal pending
command gates. The terminal scene resumes via the public continuation hooks.
Pattern journey_step prevents a silent bypass of active device contact;
native movement in the offered table scene owns all actual consequences.
journey_step may return native_scene_required=<plain reason> to request native
table resolution of a step. The pure query supplies no success/trigger receipt;
step_profile rejects before elapsed time or position commits, while the source
offers open_scene through journey_options. Other movement overrides remain
unchanged. Absent this key, ordinary journey movement retains its behavior.

Source-input HTTP transport uses the existing mutation token middleware:
POST journeys/{id}/admit accepts typed revision/actor/kind/payload/gm/reason;
actor /act cannot supply this GM authority. POST /scene accepts the existing
explicit teams/positions schema with a one-round default. GET may select its
viewer projection; source logic and custom recipes stay private to the owner.

Event-origin use of the existing effect_origins protocol: Trap's public
firing_origin_scope(engine, owner, active_zone, occupied_position) validates
actual ownership/occupied cells, binds the native geometry, and publishes the
same record only while that device's effects resolve. Native source validity,
range, line of effect, cover, attack/save defenses and replay read it normally.
Scope exit (including a player-choice pause or exception) removes the transient
publisher. It grants no remote foreground Set Trap candidates. Payload activate
optionally accepts that source-validated origin_record for its own effects.

Physical journey construction uses the same offered choices for manual and
automatic seats. pattern_construction_picker keeps owner-private drafts in
journey state; planning spends nothing and final commands revalidate sources.
journey_resume advances the shared session clock once before settlement hooks;
journey_elapsed alone ages construction clocks, including other party members.

"""

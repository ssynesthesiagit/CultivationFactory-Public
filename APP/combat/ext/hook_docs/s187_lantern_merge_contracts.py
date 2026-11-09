"""Lantern Keeper and shared contract changes preserved during the main merge.

zero_hp_settled(engine, target, source_id, active_intent) -> None is a strict,
transactional notification after the ordinary zero-HP lifecycle has been settled.
It runs after zero_hp policy subscribers and the native life-state update, before
returning from that damage resolution. Subscribers must gate by their own owned
conditions and may apply follow-up effects; they do not select or replace the
base life state. No subscriber preserves the ordinary zero-HP behavior.


sound_path_allowed(engine, speaker, listener, source) -> None/bool/verdict.
Any False rejects ordinary hearing of this speaker, and True is a grant that
carries this printed sound past ordinary sound suppression (the Ninefold
Heavenly Bell heard through Silence inside its field). A refusal may name the
source that owns it: {'allowed': False, 'source': <definition id>}, which then
gives way to a grant only when that source's suppression is ordinary Silence
(combat.speech.ordinary_silence), so a protected obstruction and a Deafened
condition no Silence field accounts for keep their hold. speech.can_hear_from
first collects the listener's Deafened rules with the condition each came
from, then combines providers. Recipient admission, typed areas, generic
reactions and area previews share this helper. Neither query mutates state,
consumes usage or changes damage rules. Invalid replies fail transactionally.
Mantra of Silence supplies a concentration-linked zone with bounded exemptions
and holder-next-start relief, names its own source in that refusal, and leaves
Thunder intact.

observer_source_profile(engine, source, data) -> dict | None. Pure, default-inert classification of one
signed source instance (a stored condition's data or a placed zone's trigger_profile), merged over its own
information_profile by combat/observer_information.source_profile. The producer answers only for an object it
actually authored and returns primitive facts (tags, source_cl, save_dc, save_ability, permanent, ...): never a
tag guessed from an effect's name, damage or narration. Returning None -- the default for every source without
a provider -- leaves the stored profile and the ordinary authority reader exactly as they were, so a fight with
no such source keeps byte-identical conditions, perception rows and decisions. Two providers answering the same
source is an error, not a merge: one native producer owns each classification.

journey_initialize(session, actor_id) -> None. Strict lifecycle notification for one actor entering a journey scene;
with no provider the journey state is byte-identical. A provider binds only its own persisted scene/source state for
that actor and may raise to abort the transaction. It never resets another source's ledger, spends resources or performs
the action for the player. journey_scene_end(session, previous_scene, current_scene) is its paired scene notification with
the same default-inert contract.
journey_acquisition(session, actor_id, source, payload, sheet) -> {'sheet': dict, 'acquisition_id': str} | None. Strict
acquisition-time validation for one Open School / source choice: the provider checks its own prerequisites (required parent
path, attainment band, occupied slot) and returns the sheet changes it owns. None (the default for every source without a
provider) leaves the sheet and the committed acquisition unchanged; a rejected choice raises and aborts the transaction.
journey_source_sheet(sheet, session, actor_id) -> dict | None. Pure overlay of the actor's already committed source state
onto the sheet a caller is about to present or compile. None leaves the sheet byte-identical; it never invents a grant the
ledger does not hold and never spends resources.
journey_acquired(session, actor_id, source, receipt) -> None. Strict post-acquisition notification carrying the emitted
receipt, so a provider can bind the persisted state its own acquisition just committed. Inert without a provider; raising
aborts. It never re-runs acquisition or grants anything a second time.
damage_at_zero_failure_allowed(engine, target, source_id) -> bool | None. Pure query asked when damage would take the target
to 0 Hit Points: False keeps the target out of that failure handling (a soul-anchored ally stays Conscious-but-anchored per
its own record); None (the default) leaves ordinary zero-HP handling byte-identical. The provider owns the condition check.
armament_endpoint_allowed(engine, owner, point) -> bool | None. Pure query for one endpoint of a teleport/relocation: point is
a Position or an (x, y[, z]) tuple. False rejects the endpoint; True accepts it beyond ordinary control range because the
provider's own bound asset reaches there; None (the default) leaves the ordinary range check in force.
armament_asset_relocating(engine, owner, asset, point, source_id) -> bool | None. Strict pre-relocation notification for a
bound Domain Armament that is a real item: False vetoes the move, None (the default) leaves it unchanged. A provider may
commit only its own custody/possession change for that asset, never a second copy of the item.
initiative_modes(engine, actor) -> {'advantage': bool, 'disadvantage': bool, 'ignore_surprise_disadvantage': bool} | None.
One creature's own Initiative modifier, answered from its committed source state. initiative_modes.combine folds every
answer into NORMAL/ADVANTAGE/DISADVANTAGE for that creature's roll only; None (the default for every creature without the
source) leaves the roll exactly as it is. A mode never applies to another creature's Initiative and never changes surprise
itself.
observer_information_rows(engine, viewer) -> list[dict] | None. Live source-scoped private facts for one viewer
(kind, viewer_id, source_id, primitive details). combat/observer_information.readings and information_results.for_observer
consume them in the native perception/DecisionContext projection only; None or an empty list (the default) leaves that
projection unchanged. A row reveals presence, direction or wording its provider already entitles this viewer to; it never
grants sight, a creature's identity/statistics or a targeting permission.

Lantern Keeper shared hook contracts:
runtime_roof_surfaces(engine) -> iterable of runtime surfaces or None.
The engine may be a JourneyAssetContext during journey synchronization.
Pure, default-inert query; providers expose only currently active owned surfaces.
armament_endpoint_allowed(engine, owner, point) -> bool | None.
Pure query: point is a Position or (x, y) tuple. False rejects an endpoint;
True accepts it beyond ordinary control range; no answers use ordinary range.
armament_asset_relocating(engine, owner, asset, point, source_id) -> bool | None.
Pre-relocation notification: False vetoes movement; None leaves it unchanged.
Providers may commit owned custody changes; absent providers are inert.
damage_at_zero_failure_allowed(engine, actor, source_id) -> bool | None.
Pure query; None leaves ordinary zero-HP failure handling unchanged.
journey_initialize(session, actor_id) -> None and
journey_scene_end(session, previous_scene, current_scene) -> None are strict
lifecycle notifications. Providers bind only their own persisted scene state;
absent providers leave journey state unchanged; exceptions abort the transaction.
possession_operation_allowed(engine, actor, holder, item, operation, source)
-> bool | None is the shared permission for one operation on one real carried
identity, asked strictly before any custody writes. actor performs it, holder
is the current holder (or the original owner of a dropped record), item is the
exact possession row, operation is 'drop', 'transfer' or 'move', and source is
the moving source's definition id. carry.operation_allowed dispatches it and
rejects a malformed reply; the drop, transfer and item-mover adapters in
scoundrel_riders.py ask it first, which is what the Lantern record's real-item
custody (real-item create, bind and release) travels through. False vetoes the
operation with nothing moved, None leaves ordinary custody unchanged and no
subscriber keeps every existing operation intact. A provider owns its own
artifact, authority, seal, distance and consent requirements and can never
create, duplicate or take an item the caller did not already reach.

"""

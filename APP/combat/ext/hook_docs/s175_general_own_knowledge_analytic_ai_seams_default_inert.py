"""General own-knowledge/analytic AI seams (default-inert):
target_personal_knowledge(engine, viewer, target) -> Knowledge | False | None.
Pure personal targeting override inside candidate_knowledge.query only,
after native sight/field checks; False means unknown, None retains legacy
knowledge. Native/manual targeting and execution never consume this hook.
personal_observation_receipt(engine) -> dict[str, primitive] | None. Runs only
at committed target observation, including creation. Its personal memories
are stamped into the final event; no new sequence or query-side writes.
ai_observation_frame(engine, actor, candidates, policy) -> OwnKnowledgeFrame
| None. Pure personal projection; exclude hidden truth and global revisions.
Frames may carry the actor's own relative occupied-volume offsets; movement
and menu evaluators translate them with occupied_at(anchor), including every
cell when checking perceived area boundaries. Absent frames retain native
behavior. Directly perceived allies retain authorized support/mobility facts;
remembered allies and opponents never supply their current private sheets.
Search consumes the same frame's projected roster and sighting sequences via
ai_search.search_move(sightings=...). Team journal hints are excluded when a
frame exists; absent frames retain native team receipts and redacted hints.
ai_observed_objectives(engine, viewer) -> tuple[Position, ...] | None. Pure
scenario objective suggestions, rechecked against personal square perception.
No provider means no fabricated objective or pressure toward unknown cells.
ai_movement_hazards(engine, viewer, candidates, frame) -> dict[candidate_id,
dict[str, bool]] | None. Pure perceived hazard_exposure/zone_hazard_exposure
estimates; no candidate removal or mechanics changes. No reply retains native
metadata. Providers reuse zones.hazard_test's projected zone_states seam.
ai_policy_enrichment(policy, sheet) -> dict[str, Any] | None. Pure optional
policy field additions from the owner sheet and optional package guidance.
Called through ai_policy.enrich_policy for both installed package paths;
absent/invalid optional guidance is neutral. No reply retains the base policy.
ai_movement_order(context, rows) -> tuple[candidate_id, ...] | None. Pure
destination ordering before optional-choice expansion; MUST be a permutation,
keeping the complete native menu. Consumers may show five then More.
ai_score_components(context, candidate, option_ids) -> tuple[ComponentScore,
...] | None. Pure additive analytic value after ordinary scoring; emergency
early returns retain precedence. No rolling/spending/engine copies.
Used by ai_movement, opt-in CF_COMBAT_AI_SLICES_1_2=1. No hook answer means
byte-identical legacy context, events, scores and movement representatives.
attack_target_interception(engine, attacker, target, source_id, intent, index) -> {source_id, recipient_object_id,
condition_instance_id} | None. Strict checkpoint before creature defender hooks and the d20. A provider that resolves
successful targeting of a noncreature decoy returns its receipt and the attack is redirected to that object. None (the
default for every non-owner) leaves the original attack intact. Economy is already paid and never refunded; an
intercepted strike delivers no creature roll, damage or on-hit effects. Providers check ownership and perception of the
actual recipient. attack_declaration.intercepted caches answers and abstentions so typed/native boundaries never roll twice.
shared_space(engine, left, right) -> True | None. Pure opt-in query for a live explicit sharing relationship, such as a rider
and mount: True allows partial or equal-size overlap and mutual collision exemption for that pair. None (the default for
every creature pair) leaves native occupancy rules, including existing rider/mount validation, unchanged. It never moves
a creature, removes terrain or grants passage to any third occupant.
observer_information(engine, observer) -> list[dict] | None. Pure, default-inert private fact projection.
information_results.for_observer consumes it in the native senses.perception query and the active actor's player/AI
DecisionContext. Providers enforce ownership, source/range/visibility/expiry and return only entitled facts, never complete
enemy records, source identities or diagnoses. It grants no sight, targeting, team knowledge or public journal notes.
observer_source_profile(engine, source, data) -> dict | None. Pure, default-inert classification of one native source for
the private readings above: the owning provider returns the profile fields it owns and only one owner may supply it, so no
provider leaves ordinary perception unchanged. It grants no sight, target selection, team knowledge or public notes, and it
never edits the source or the viewer.
zones' continuous inside[].modifiers[] may supply operation='ADD' or 'SET'; an omitted
operation keeps the historical SET. Native zone reconciliation creates and removes the exact
scoped modifier instances; Harvest Winter uses ranged AC ADD, preserving unrelated armor and
melee AC. Any other operation fails transactionally.
cover_miss_recipient(engine, attacker, target, spec, roll, intent, total, cover) -> another active actor id | None. Runs
once, only for an original-roll miss caused by cover (not a natural 1, forced miss or an unrelated AC defense). The provider
owns recipient eligibility, knowledge and geometry; the resolver reuses the d20 and modifier total, recomputes recipient AC
and cover, runs ordinary hit defenses and damage, and never redirects that roll again. None (the default) leaves the miss a
miss.
pass_through_stop(engine, mover, occupant) -> True | None. Pure opt-in query allowing a passage-granted endpoint in that
occupant's footprint. It never removes terrain, hidden contacts or any other occupant's collision; movement_attempt still
owns entry checks. None (the default) keeps the occupied stop forbidden.
scene_end(engine) -> None. Strict transactional notification before the final MATCH_ENDED event; with no provider it is
inert. A provider may remove only conditions it marks as scene-bound. It never changes unrelated UNTIL_REMOVED conditions or
emits post-terminal events."""

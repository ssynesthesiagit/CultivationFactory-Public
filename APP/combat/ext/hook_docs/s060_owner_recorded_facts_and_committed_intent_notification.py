"""Owner-recorded facts and committed-intent notification (table_facts, from
Read the Thread 5d7bea3): TabletopService.record_fact and protected POST
/api/tabletop/matches/{match_id}/facts accept a strict TableFact plus expected
state version. These are owner/GM commands, never actor/model menu options.
The source, bearer, witnesses, horizon, exact action and operational answers
are journaled in TABLE_FACT_RECORDED. Same record_id corrects; active=False
withdraws. table_facts.records(engine, viewer) exposes only current witnessed
facts. Raw provenance is excluded from actor/model recent_events and uses the
existing history_hidden display contract to stay out of the public table feed.
table_fact_privacy also hides the native authoring-command envelope, so neither
public history nor model observations mistake GM input for an actor's action.
The complete command and source remain in the owner's replay journal.
table_fact_validate(engine, fact) -> None may reject source-specific declarations
with ValueError. No subscriber leaves the shared schema unchanged; validation
must not mutate state. Glass Heart consumes answers glass_heart.scope,
glass_heart.pressure, glass_heart.anti_farming and glass_heart.scene. Each answer
category equals its key, condition is the exact native action ID, and fact is
one of the enums documented in glass_heart.VALUES; visible_sign explains the
source input. Scope/pressure require explicit genuine_unarranged_event in the
same record and action binding. Excluded farming never receives that fact.
intent_resolved(engine, actor, candidate, intent, start_sequence) -> None runs
strictly within the accepted native transaction after uncanceled resolution,
before turn advancement. No subscribers means no extra event or state change.
Consumers inspect committed events after start_sequence, never planned costs
or offered/declined reactions. Glass Heart uses actual net CP payment and
successful CHECK_ROLLED; after_save_resolved handles settled save outcomes.
glass_heart.preexisting_reflection(engine, bearer, trigger_sequence) is the
public same-event spending guard. Callers bind the actual native hit/roll
sequence, so an earlier event in one multiattack can feed a later event.
foundation_resources.affinity_spheres(foundation_id) -> frozenset[str] is the
shared printed-compatibility reader for resource generators. It grants neither
sphere access nor truth scope and returns empty when authority is unavailable.
Glass Heart's journey_rest consumer recharges only its owned Perfected use
counter after the existing native eight-hour Long Rest; it does not recover CP,
HP, Reflection or another creature's/ability's resources. Journey's existing
combat balance import/export carries that paid use between bound encounters.
Glass Heart's scene for Refraction is a GM-only control: TabletopService.
record_glass_scene and POST /api/tabletop/matches/{match_id}/glass-scene take a
bearer and a plain scene (major_combat | emotionally_decisive), build the
glass_heart.scene record with glass_heart.scene_document, and record it through
record_fact. The table's "Refraction scene" button (static/tabletop/glass-scene.js)
sends the same request. refraction_used spends the scene when Refraction is used,
so the next use needs a fresh declaration."""

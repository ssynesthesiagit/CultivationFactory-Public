"""Recorded observation and acquisition seams (feature_access, table_facts):
  feature_access_policy(feature_id) -> None | dict with path, minimum_cl,
  classification and source_kinds. One provider per feature; no provider leaves
  compilation unchanged. TabletopService.acquire_feature records the explicit
  owner/GM source, table_advance.apply preserves it, and compiler admission checks
  current effective Path CL without deleting that acquired relationship.
  TabletopService.record_fact(match_id, document, expected_state_version=N) is an
  owner/GM command, never an actor/model menu option. Its strict TableFact binds
  current observations, audience, source, horizon, Source CL, actual check DC,
  operational answers and optional exact known actions. Same record_id corrects
  a source; active=False withdraws it. table_facts.records(engine, viewer) keeps
  only that creature's witnessed current facts; observable additionally checks
  range/sight. Corrections and expiry are replayed from native journal intents.
  Owner HTTP producers are POST /api/tabletop/characters/{project_id}/features
  (feature_id, source) and POST /api/tabletop/matches/{match_id}/facts
  (document, expected_state_version), under the table's existing session-token
  guard. TABLE_FACT_RECORDED remains owner-only; OBSERVATION_ANSWERED carries
  audience-scoped operational text, not raw source content or private provenance.
  intent_resolved(engine, actor, candidate, intent, start_sequence) -> None is a
  strict hook inside the accepted native transaction, after uncanceled action
  resolution or movement, before ending a turn. It covers every candidate kind,
  including non-attack actions. candidate/intent are the FINAL resolved action:
  an interception that redirected the recipient and a lazy CELL placeholder that
  bound its square are already applied (for kinds that resolve without a
  replacement, the accepted candidate is passed). Movement subscribers must
  inspect actual committed displacement (interrupted paths are not completed
  paths). Default-inert: no subscriber result changes an outcome and no new
  journal event is emitted.
  table_facts.action_matches consumes exact candidate/source/targets/options,
  the exact aim (destination, including a CELL action's square) and movement
  endpoint, explicit actor knowledge and current prerequisites.
  It never infers intention or a private action from a name or generic category.
  table_facts.reaction_matches consumes native REACTION_RESOLVED receipts with
  the same source/targets/knowledge/prerequisite binding; a predicted variant
  requires explicit option_ids on that receipt. Offers/declines never qualify.
  Audience-scoped events use payload.audience_actor_ids; recent_events projects
  them only to those creatures, independently of team knowledge policy."""

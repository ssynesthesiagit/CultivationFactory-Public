"""Terrain occlusion: SquareGrid.bind_occluder_policy(policy) rebuilds immutable
  region geometry before restored queries: cell-v1 retains predecessor cells;
  cross-v1 honors occluder="cell"|"centerline" with altitude-aware crosses.
  The terrain_occlusion match_start hook(engine)->None records cross-v1 in
  MATCH_CREATED only for maps using crosses; it is inert otherwise. Gate 3/4
  restore/upgrade bind the saved policy before sight, targeting or perception.
  Unstamped saves always bind cell-v1. No movement, cover or dynamic zone rules
  change. Map presentation exposes the bound geometry, never current defaults.
  Cross intersections have a bounded grid-local geometry cache, cleared on
  policy rebind; full-cell terrain and dynamic obscurement remain fresh checks.
  The same match_start provider calls terrain_occlusion.bind_roofs(grid, arena)
  on new/restored engines. Authored roof_cells become horizontal sight surfaces,
  never movement columns; absent roofs are inert. sight_geometry(grid) exports
  current bound spans and roof tops for airborne continuous table fog. Airborne
  senses.perceives_cell uses exact surface-ended rays from physical footprint
  cells at the viewer's base altitude; creature rays retain volume endpoints.
  Solid finite tops are separate scene surfaces too; perceives_object queries
  an object's visible top/near face independently of its floor. Derived object
  ids and surface limits only guide presentation, never alter targeting rules.
  combat.sight_lines.bind(grid, dynamic=()) is the general derived
  line-geometry seam; the optional second argument supplies dynamic sources.
  Grid construction/policy rebind and zones.sync_walls call it. Cell blockers
  use connected centre runs with full-depth end caps; movement cells remain
  untouched. source(cells, kind, bottom, top, name, *, segments=None, scale=2,
  tag='wall') exports doubled integer segments and the structured sight kind the
  table reads (wall/object/tree/terrain/door). A 'centerline' occluder's rows are
  the region's own centre lines; sight_lines.cross_segments(cells) builds the
  centre plus of each square at scale 2, the default scenery blocker
  (combat/scenery_sight.py terrain_occluder, combat/object_rules.py sight).
  zones.sync_walls passes a wall zone's own occluder/sight_class from its
  trigger_profile['wall'], so a placed object's plus and its kind come from the
  same typed data as its movement block; absent fields keep centre runs and
  'wall'. Classification never reads a name, description, shape or look.
  clear(grid,start,end,physical=False,near_endpoint=False,screens=False)->bool is
  shared by sight and effect_cover rays, with physical queries checking only
  BLOCKED sources. near_endpoint=True preserves creature sight from/to an
  occupied endpoint cell at its bound height, for SIGHT_BLOCKED screens and
  solid BLOCKED walls/objects alike (a barrier is targetable at its near face):
  only that endpoint cell's ray interval is exempt, so intervening cells in the
  same source still block. Effect and projectile queries keep
  near_endpoint=False, so their endpoints stay exact. segment_clear likewise
  accepts screens=False; screens=True exempts an occupied walk-through screen
  at either endpoint for perception, not a solid interior. The derived grid
  walk_through_spans table records sight-only spans minus overlapping solid
  spans; sight_geometry exports their walk_through flag on volumes. The table
  is rebuilt by policy binding, not by dynamic line-source binding.
  Absent sources are inert. sight_geometry exports these
  same lines and height spans to ground/airborne fog and known-only markers.
  A terrain region may supply sight_segments={scale:int,segments:[[[x,y],
  [x,y]],...]}. source(...,segments=None,scale=2) validates axis-aligned
  integer pairs; provided segments replace ONLY that region's sight/physical
  rays, never its movement/cover footprint. Missing data retains centre runs
  and caps. An empty list is sight-inert. Authored sources do not invent solid
  horizontal cell tops. Map plant art and compilation share scenery-sight.json
  placements and the 5-ft height / 1-ft diameter minimum; tiny shoots get no
  source or marker. Explicit finite spans survive arena sealing and reload.
Targeting policy (owner 2026-10-06): combat.targeting.reason is the pure
  creature-recipient legality seam used by recipients.allowed, for menus,
  controllers and attack declaration. It delegates sight to the same senses
  policy as fog; combat.targeting.line_of_effect checks solid grid geometry
  independently of darkness. CELL generation uses it for the point of origin.
  attack_line_of_effect(engine, actor, target, source) checks area origins rather
  than individual area recipients; existing area selection clips propagation.
  Native and portable attack packets call combat.targeting.attack_missed after
  declaration/checkpoint movement and before its attack roll. It records a
  percentile roll only when the fight's configured percentage is positive;
  absent/zero percentages and clear targets remain inert. Existing unseen
  Advantage/Disadvantage and empty remembered-square misses are unchanged.
  targeting.policy(engine) supplies the same saved settings to attack resolution,
  remembered_square_label(engine, actor, target) and status_text zone cards.
  attack_modes.presentation_modes(engine, actor, target) is a read-only menu
  query for uncancelled condition/modifier and sight contributions after the
  same strict owned removals as resolution. It creates/consumes no modifiers,
  events or dice; targeting uses it to explain cancellation or removal rather
  than promising Disadvantage unconditionally. Later action-specific penalties
  and reaction choices are not predicted by this actor/target query.
  The targeting_policy match_start provider also binds ai_knowledge_policy=1
  in MATCH_CREATED. knowledge_policy.roster(engine, viewer) returns known
  geometry for AI restraint/mount choices; unstamped saves retain prior choices.
  Knowledge-policy journal projection is a pure read; raw journals are unchanged.
  Continuations preserve this integer policy. No observation schema is changed.
  The targeting_policy match_start provider binds the two integer percentages
  in the existing MATCH_CREATED payload, without adding an event/state field.
  Constructor events are replaced on load. Saved fights must carry a valid
  targeting policy in their creation data; unsupported data receives a clear
  error. No setting is inferred from an engine fingerprint or source registry.
  read_queries.pure scopes nested recipient/targeting/perception queries to one synchronous
  call on one engine. can_see uses actor-object keys (projected footprints stay
  distinct), and zones.typed_zones shares its derived rows only within that call.
  Queries/providers must not mutate inputs. The scope resets on return or error;
  no answers survive into execution, a reaction, a new action/origin or a refresh.
  Flight capability checks and each AI flight safety position also own a pure
  query scope: condition/provider gates share derived zones only on that
  unchanged engine and projected position. No frame spans movement or a commit.
  Outside a pure-query scope typed_zones remains uncached. No stored fight fields
  or candidate IDs change. Containers returned by the zone query are fresh lists.
  Native opportunity_eligible uses explicit footprint positions to reject
  non-crossing route edges before constructing an isolated projected mover.
  On a leave-reach edge, disengage_protection and opportunity_allowed still
  receive the deep-copied mover at its previous position. These are pure
  eligibility queries, never notifications for unrelated route edges; their
  default-inert results do not spend resources or record player decisions.
  recipients.allowed shares sight across its targeting, knowledge and reach
  checks; senses.perception shares zones across one viewer's cells/creatures.
  read_queries.candidate_pass(engine) is a read-only context manager used by
  action_legality.observe.
  It shares queries only within one shot_geometry action/origin frame, keyed
  by that frame's retained object identity, state_version and event_sequence.
  New actions/origins, recorded changes and outer-call exit invalidate reuse.
  Loadout/terrain queries outside a shot frame remain call-local or uncached.
  It must not wrap execution, reactions or any other state-changing operation.
  A transient spec.concealment_missed flag distinguishes an actual miss from
  canceled/empty aims. Normal miss riders and completion responses still run;
  d20/natural-result responses never run without an actual attack d20.
  This global owner targeting rule is not an ability-specific sight exception.
Candidate construction (lock round 22): a movement query computes immutable
  ranged-attack descriptors once per observed hostile entity ID and passes them
  to tactical_cover(..., attacks=...). The dictionary is local to that query:
  another actor, changed equipment/conditions/catalogue, rollback, reload or
  next query always recomputes it. Unknown/remembered actors retain their
  observed action list; the cache never substitutes live hidden actor data.
  It caches no legality, cover-hook reply, candidate or fight state. Existing
  per-position cover providers and candidate ordering remain authoritative.
  tactical_cover also shares geometry-only sight rays between attacks against
  the same prospective target; cover_bonus(ray_paths=None) remains uncached by
  default. Provider replies still run separately for every attack/ray, and
  providers must treat ray context as read-only. Neither cache outlives its call."""

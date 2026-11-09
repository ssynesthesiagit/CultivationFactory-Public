"""- The core weapon/unarmed modifier adapter resolves explicitly printed delivery
  categories through its category index. In that adapter a modifier's Sphere
  ``any_attack`` scope is narrowed to its declared core category names; it does
  not filter core weapons by ``sphere_id``. The separate Sphere-action pass
  retains its original scope. With no explicit core targets the adapter is inert.
  Extensions may use the immutable ``compile_action`` transform to seal a named
  feature's follow-up into linked modifier effect lists and captured hit choices;
  free loadout settings are not applications of that modifier.
- Typed modifier target scope ``attack_or_sphere_technique`` (factory_compiler) is a reusable data selector with ``scope_filter.attack_flags``, ``weapon_families`` and ``sphere_ids`` arrays. An attack qualifies by configured flag/family; an active technique qualifies by configured sphere. Empty categories match nothing. Reviewed modifier data can therefore describe eligibility without per-ability names in the compiler.
- Perception queries: combat/senses.py perceives(engine, viewer, target,
  locate_concealed=False) is the shared creature/footprint decision;
  perceives_cell(engine, viewer, position) queries empty terrain, and
  perception(engine, viewer) projects cells and creature ids for tabletop fog.
  These public queries consume existing sense/zone hooks without adding abilities
  or changing saved state. Callers must not reconstruct blindness or area policy.
- Area risk previews reuse typed_executor.effect_subjects and save_subjects per
  effect, including nested save recipients and legacy printed exclusions. They
  apply the same enemies-only default to generic creature save wording;
  explicit inclusive wording admits allies, while emitted cones/lines always
  spare their user. Owner recipient overrides remain authoritative.
  They resolve a bound Context.target as one recipient; a multi-recipient root
  Context leaves target=None and supplies its complete targets list. Per-save
  subcontexts then bind that save's creature without changing the root roster.
  Both queries are pure: no rolls, decisions, payments or persistent state. Explicit
  self harm has separate self_harm/self_expected_damage metadata and controller
  cost; only endangered area recipients appear in friendly-fire warnings.
  area_effect_risk(ctx, effect) -> None | 'harmful' | 'harmless' is a pure leaf
  classification query. Providers answer only for their own effect type; no
  row means no behavior. Conflicting/invalid answers are rejected. A harmful
  non-damage effect contributes a recipient and zero estimated damage, retaining
  the controller's ally-count penalty. Unknown saving-throw leaves conservatively
  retain warnings; known beneficial leaves are excluded. Recipient scopes always
  use the executor query, including enemy-only saves. No persistent state changes.
- Simultaneous recipients: typed_executor.simultaneous(ctx, subjects) wraps one
  save or damage row applied to two or more recipients in the engine's
  victory_deferred() hold. An early defeat in the batch (including the user in
  its own unrestricted area) cannot end combat before the remaining recipients
  save and take their results; the ordinary victory check then runs once, so a
  batch that defeats every side ends as DRAW_SIMULTANEOUS. Holds nest; a pause
  or error discards the pending check with its transaction. One recipient keeps
  the immediate check. Plug-ins applying one effect to several creatures may use
  the same helper. Transient engine attributes only; no saved fields.
- On-hit self riders: an attack with an explicitly self-directed on_hit row
  holds victory until the strike resolves, and those self rows still execute
  when the hit defeats its target. Target-directed rows retain their existing
  active-target gate. No self row means the old hit and victory behavior.
- Whole activation: a typed action row with hold_victory_until_resolved=True
  runs all of its effects inside the same victory_deferred() hold
  (typed_executor.activation_hold). A defeat by an early effect then cannot skip
  the activation's later printed clauses, such as payment and object or zone
  effects. Only rows that opt in change; the stock Treasure Consumables set it.
- Granted attacks: an opted-in typed action sets granted_attack=True and marks
  its one root attack effect granted_attack_root=True. Nested attack-granting
  effects and Cleave cannot grant another attack from that action. Missing
  markers preserve existing actions. This general executor contract is available
  to any plug-in that supplies a printed Granted Attack.
Relations and side changes (lock round 17):
- combat.relations.relation(engine, a, b) -> ALLY | ENEMY | NEUTRAL is the shared
  pure live query; a/b are actor states or visible actors. DecisionContext is
  also accepted in place of engine. No cached allegiance. Default: same team
  allies, different teams enemies; team:neutral is neutral to every other actor,
  including another neutral. Self is an ally. Optional MatchState.relations
  contains symmetric sorted team pairs and actor pairs; actor pairs win.
  Missing tables serialize exactly as before. New tables enter through sealed
  roster_setup.relations or recorded commands, never an unrecorded mutation.
- CombatService.change_relations(match_id, change=..., expected_state_version=N)
  is the owner/GM entry point. ACTOR_SIDE(subject actor, other team) changes only
  that actor. TEAM_RELATION/ACTOR_RELATION(subject, other, relation) change a pair.
  These commands use normal journal prepare/commit/recovery and explicit
  ACTOR_SIDE_CHANGED/RELATION_CHANGED events. They spend no economy or rolls,
  invalidate stale decisions, and reject pending choices, setup or ended fights.
  Actor pair overrides and already applied recipients survive side changes;
  companions keep their side unless explicitly changed. Attacks do not change
  relations. New enemy/ally checks must query the current relation. Combat ends
  when no active opposing primaries remain; neutral bystanders cannot prevent it.
- Create-fight: create_factory_match accepts neutral_actor_ids (catalog IDs or
  actor:factory.<project>); each fighter belongs to exactly one group. Confirmed
  setup accepts two combat teams plus optional team:neutral, displayed as Neutral.
- Pure strict bystander_policy(engine, actor) -> None | bool selects retreat and
  Dodge AI. First non-None reply wins. Default neutral actors without enemies
  use it; explicit mortal creature types also use it when they have no enemies.
  No inference from a creature's name. A new enemy restores ordinary combat AI.
  Manual turns keep their normal menus and reaction ownership. Bystander AI
  retreats through safe legal movement, Dodges, then ends its turn. AI never
  explicitly targets a neutral; harmful-area nonenemy_area_count penalizes
  bystanders like allies. This optional metadata is absent in legacy fights.
  compile_actions may set action.parameters.ai_area_family to a stable string
  identifying alternate area shapes of one ability. Decision contexts copy it
  into candidate metadata; the AI prefers a hostile-hitting placement without
  unavoidable allied recipients (including its caster) within that family.
  Without the field, placements group by source ID. Explicit activation self
  costs and harmless/optionally spared allies do not veto a placement. No engine
  recipients, saved candidates, or player choices change.
  Rider migration must also use this seam for area recipients: enemies exclude
  neutrals, each creature includes them. Friendly-fire activation is separate."""

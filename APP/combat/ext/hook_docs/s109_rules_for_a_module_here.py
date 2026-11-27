"""Rules for a module here:
- Empyreal Administrator owner-authored Subpath (cai_clan.py) uses existing hooks only.
  compile_block seals cai_clan_passive ownership rows for Court of Duty and
  Edict of Shared Purpose, publishing automatic sheet status and their outcomes.
  Their runtime consumers remain the owning action's sealed cai_clan kit.
  cai_investiture(ctx, effect) selects a fixed willing allied group with the
  owner's choice transport (allied recipients with sight and line of effect at
  activation), then stores concentration-linked layers; court=true
  applies its once-per-combat limit and enhanced group. cai_censure(ctx, effect)
  is a Judgment Saber on-hit mark. cai_flare_protection(ctx, effect) grants
  Temporary HP only to this caster's invested allies in the resolved area.
  cai_end_investiture(ctx, effect) ends only this owner's Layer/Court copies
  through concentration.end_copy; candidate_allowed exposes its free control
  only while such an activation exists. Other Concentration remains intact.
  Source ownership is sealed in optional action.parameters.cai_clan; absent
  metadata / absent owned conditions is inert. Layer condition data are integer
  bonuses and plain display strings; Censure stores its dice count at placement.
  The damage-context event claims a single Censure after a confirmed attack
  deals positive HP/Temporary-HP damage, before its zero-HP outcome settles.
  The Radiant component shares the hit's HP-excess accounting without creating
  another death-save failure; it has no attack provenance and cannot claim another.
  A bounded last-claimed-roll turn flag prevents another component of that same
  hit from claiming a second mark; a different attack roll remains eligible.
  Reduction uses a separate round-bound condition, surviving turn changes and
  re-investment, and chooses the maximum rather than stacking Administrators.
  Typed recipients use damage_reduction; native/legacy recipients use
  final_damage after defenses. The latter returns {amount: defended minus
  reduction}, clamped to zero, only for a positive packet and an owned layer.
- Independent triggered weapon attacks retain weapon_source_id in the public
  typed_reactions.triggered_context. Grip, family and deferred-bonus queries
  resolve the actual owned weapon; contexts without an attached weapon stay inert.
  weapon_hits.triggered_melee_weapon(engine, actor, unarmed=False) returns the
  strongest available, readied melee attack (preferring natural attacks for an
  explicit Unarmed Strike), or None. Shared by that context and Moon-Falling
  Counter; legacy catalogs preserve their unmanaged-grip policy.
- Reviewed normal/long attack ranges: factory_compiler copies a positive
  range.feet/long_feet pair to typed range_ft/long_range_ft independently of
  weapon delivery. Public action range stays the maximum; the executor applies
  long-range disadvantage. No declared pair leaves existing metadata unchanged.
- A plug-in-owned passive activation may use reviewed activation.trigger=null
  and source=reviewed_plugin_activation to avoid a second generic paid trigger.
  The printed trigger remains in rules_text/effect evidence and is enforced by
  the owning plug-in. Existing row_allowed can reject legacy generic copies;
  it must return None for unrelated owned rows and characters.
- Movement reconciliation: zones.on_moved(engine, mover, start, end, *, forced=False, entry_at=None)
  -> None. Pass the committed segment's endpoints and forced classification, including
  when another callback has already moved the creature again (mounted Overrun, or any
  deferred placement). Crossing and terrain-distance matching use that segment. Opt in
  with entry_at=end to check its recorded entry despite a later displacement; None keeps
  the existing live-position entry check. Following areas and continuous inside effects
  always use the live position. It never relocates the creature or adds movement events.
  With no applicable areas it adds no zone effects; omitted entry_at changes no behavior.
- Typed modifier target scope ``attack_or_sphere_technique`` (factory_compiler) is a reusable data selector with ``scope_filter.attack_flags``, ``weapon_families``, ``implement_ids`` and ``sphere_ids`` arrays. An attack qualifies by configured flag/family or exact sealed weapon implement_id; an active technique qualifies by configured sphere. Empty categories match nothing. The same explicit selector is applied to native weapon actions through the existing core modifier pass; named melee selectors retain their melee restriction. Reviewed modifier data can therefore describe eligibility without per-ability names in the compiler."""

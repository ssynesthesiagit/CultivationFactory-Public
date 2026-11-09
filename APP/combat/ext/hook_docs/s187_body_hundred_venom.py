"""Body and Hundred-Venom contracts.

turn_resources_refreshed(engine, actor) strictly follows turn resource refresh;
providers may only record turn-scoped effects for that actor.
body_mode_profiles(bundle) -> list of profile dicts (source, feature_levels,
optional scene_resources) contributes to Body mode availability; no reply is inert.
cultivation_effective_cl(engine, actor, system) -> int | None lowers effective
Body CL; invalid or negative replies leave the compiled CL unchanged.
cultivation_feature_available(engine, actor, feature) -> False blocks a feature;
True or None leaves the other gates in control.
cultivation_row_available(engine, actor, block, row) -> policy replies gate an
offered row; missing replies preserve availability.
cultivation_effect_binding(engine, holder, item) -> binding | None attaches a
cultivation effect to an item holder; None adds nothing.
path_rider_rows(engine, actor, kind, rows) -> rows strictly replaces Path rider
rows while preserving each row's identity fields.
damage_type_grant_available(ctx, source) -> False withholds a source's grant;
True or None leaves it unchanged. These queries do not roll or emit events.

resolution_numbers(ctx, numbers) -> replacement dict | None transforms a typed
resolution's numeric profile; None preserves it, invalid replies raise. Providers
must be inert for nonowners.
attack_damage_type_options(ctx, attack, target, kinds, attack_index) -> nonempty
subset | None is queried once per strike before the damage type choice, including
borrowed-weapon reactions. None preserves all options; invalid replies raise.
Providers narrow options only when their owned source explicitly requires it.

installed_source_sheet(sheet, userdata_root, actor_id) -> sheet | None projects
durable owner-scoped acquisitions at compilation; None preserves the sheet.
journey_acquired(session, actor_id, source, acquisition_id, userdata_root) is a
strict notification after successful acquisition; subscribers may persist their
own records under userdata_root. Without a subscriber it makes no edits.
"""

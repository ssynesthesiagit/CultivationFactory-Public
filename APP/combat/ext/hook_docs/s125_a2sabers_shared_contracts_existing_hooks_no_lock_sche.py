"""A2SABERS shared contracts (existing hooks; no lock/schema change):
Stance if_target.marks_any_source names typed mark prefixes independent of
the caster; absent, ordinary marks still require the stance owner.
Stance hit_rider target_at_hit is opt-in. The shared pure
stances.hit_target_receipt captures per-instance qualified indexes through
hit_snapshot; hit_final copies these to the transient resolution cache before
ordinary after_hit. Damage that newly makes a target Bloodied and later on-hit
marks do not retroactively qualify the same hit. No owning row means no receipt,
no state or event change. Old rows keep their current-state predicate.
New stance weapon_name_words matches the canonical delivered item name through
weapon_hits.weapon_item, so Opportunity Attack labels do not hide a saber.
New weapon_source_id bindings use the existing possession and managed-grip
policy; stowed/disarmed sabers cannot deliver Circle. Its attach row may opt
into weapon_attack_numbers, copying only the actual weapon attack bonus.
Beheading Feint remains CORE: generic and custom movement reactions do not
share a complete movement-only veto at the locked reaction transport."""

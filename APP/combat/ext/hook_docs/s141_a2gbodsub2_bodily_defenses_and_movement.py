"""A2GBODSUB2 bodily defenses and movement:
A2GBODSUB2: subject_teleport_attempt(ctx, subject, start, destination) is a
strict transactional veto before every typed teleport. The original Context
identifies the paying source and its CL; subject identifies the creature moved.
False stops placement after payment; None preserves ordinary landing gates.
Self and willing transports must be qualified by the ability provider. Avatar
of the Mountain uses this seam for hostile source-CL checks and opposed checks.
flight_grant_allowed(engine, actor, condition) is a pure per-condition query
before native flight aggregation. False excludes only that recorded capability;
it cannot remove innate wings or mutate a grant. World-Shaking Cadence excludes
finite temporary Fly Speed conditions until target-next-turn start. Permanent
grants and no subscriber retain their ordinary profile.
cultivation_contests.holds_position(engine, defender, source, feature) records
two Cultivation Checks using sealed key modifier + PB; ties keep the defender's
position. Immortal Gold and Avatar share this helper. Waterfall Stance and
Gilded Bones use falling_damage after defenses without changing distance.
Elephant states use native dynamic_size.apply_growth and matching expiry;
dynamic_size.fitting_category is the public pure legal-size preview. Actual
footprints supply actual size; size_steps now supplies only functional steps.
flight_provider_allowed(engine, actor, capability) is the strict pure counterpart
for cultivated flight providers. False excludes one provider's complete grant;
restrictions without positive Fly Speed remain authoritative. Providers granting
permanent anatomy may explicitly set flight_anatomy=1. Native actor fly_speed_ft
and permanent recorded anatomy remain independent. Cadence suppresses cultivated
positive-speed providers; it restores them through ordinary condition expiry.
Bodily-save readers use explicit save_categories (fracture, crushing,
bone_breaking, corrosion, bodily_decay, physical_deformation, disease), never
guess from prose or the creature's other conditions.
ability_check_hazard_mode(engine, actor, ability, skill, against, hazards) is a
strict pure mode query for explicitly qualified ordinary checks. It runs only
when check_modes receives hazards; no metadata leaves existing checks unchanged.
It combines Advantage/Disadvantage normally and neither invents a check nor a
hazard from descriptive text. Gilded Bones and Golden Sheen use their printed
bodily categories. Typed contests already carry spec.hazards into this seam.
Moon-Mirror Soul Vessel uses the same seam for its owned Wisdom checks against
an explicitly hostile opponent and a printed pressure category; it never infers
the cause from a skill/name or consumes a round allowance. Absent ownership,
opponent, or category leaves the ordinary check unchanged.
A state may explicitly opt into ends_if_unconscious=true (separate from
ends_if_incapacitated). It records this flag and removes its exact source-owned
conditions/modifiers and matching owner/source zones when unconscious/down;
Stunned alone does not end it.
Elephant King uses it so its native size and defenses share one lifetime."""

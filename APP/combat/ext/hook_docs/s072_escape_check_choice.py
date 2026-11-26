"""escape_check_choice(ctx, row, dc, grips, hazards) -> dict|None requests an
explicit physical escape skill and returns ability, skill, sealed bonus, and
optional narrowed hazard scope. Only one provider may answer. Providers use the
ordinary session choice transport; no answer preserves the legacy mixed-skill
roll. escape_checks seals both Athletics and Acrobatics bonuses at compilation;
runtime system escapes may read that sealed metadata from the actor's actions.
Explicit ability/check-skill rolls and saving throws bypass this choice seam."""

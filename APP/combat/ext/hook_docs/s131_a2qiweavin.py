"""Automatic typed saving throws (A2QIWEAVIN):
automatic_save_success(ctx, subject, effect) -> True or None, strict.
Called after recipient/size/immunity gates, before any die, pending d20
reaction, one-use save modifier or save-choice consumption. A positive
result follows normal success settlement and success effects, with no
natural die. Delivery owns recipient eligibility; automatic settlement does
not recheck the activation's geometry because no save reaction moved the
recipient. Providers own consent/selection and log the automatic result.
No subscriber leaves historic rolling unchanged. evasion may suppress
save-for-half damage for a protected recipient; unconditional damage stays.
Modifier selector target_requires.has_area=true is a general compile-time
area gate; target_requires.concentration=true requires a Concentration
technique. Both are independent of sphere or effect type and filter before broad
modifier ranking; it creates no area and changes no saved action.
Modifier all_targets=true retains every eligible activation rather than
ranking down to the ordinary broad-variant presentation limit. Requirements
still apply; absent flag retains historical presentation limits."""

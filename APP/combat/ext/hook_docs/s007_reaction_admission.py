"""reaction_admission(engine, row, target, attacker, intent, attack_spec) ->
  bool | None. Ordered any_false query after generic eligibility/range/subject
  checks and before consent/payment/effects. False vetoes this reaction only;
  None/no provider preserves admission. Uses ordinary invoke error policy
  (diagnostic + neutral reply), not run_strict; controller pauses/checkpoint
  errors propagate under that policy. Providers must not spend resources or
  apply reaction effects; controller-owned fact admission may record readiness.
on_attack_rolled(engine, attacker, target, spec, intent) in typed_reactions
  offers only rows explicitly opting into after_attack_roll, after the roll
  and before hit consequences. Returns new attack-bound AC; no opted-in row
  returns zero and preserves the before-roll reaction path."""

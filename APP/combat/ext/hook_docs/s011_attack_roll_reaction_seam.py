"""Attack-roll reaction seam:
  on_attack_rolled(engine, attacker, target, spec, intent=None) -> AC int | None
  runs after the attack roll and before damage or hit effects. Providers may
  offer attack-specific reactions; None leaves ordinary resolution unchanged.
  The runtime adapter and native engine use the same hook contract."""

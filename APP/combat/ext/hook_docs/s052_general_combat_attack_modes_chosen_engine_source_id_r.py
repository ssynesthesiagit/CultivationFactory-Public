"""General combat.attack_modes.chosen(engine, source_id, resolved_spec=None)
returns strict explicit accepted-attacker mode contributions. A sealed action's
parameters.chosen_attack_modes records modes intentionally accepted by selecting
that action; a typed attack effect can carry chosen_attack_modes, forwarded to
its strike spec. Per-strike attack_spec_choice providers set that spec field
only after the attacker accepts the choice. Values are ADVANTAGE/DISADVANTAGE
strings, not guessed intention from condition/source/final-mode. These modes
compose before cancellation/removal; ATTACK_ROLLED retains chosen_attack_modes
when nonempty even if the final mode is NORMAL. Missing/empty is inert; queries
are pure and never decide for a player. The same receipt is used by native,
typed and portable attacks. Providers must mark intentional contributions,
never automatic penalties or enemy-imposed modes. Heartfire admission reads
this journal receipt; it does not infer intention from a rolled mode."""

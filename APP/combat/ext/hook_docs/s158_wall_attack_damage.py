"""wall_attack_damage(ctx, zone, section, amount, melee) -> None runs strictly
after a real wall attack deals positive damage and records section damage,
before the attack chain continues. zone/section identify the struck wall even
if this hit destroys it. amount is damage after defenses; melee reports the
compiled weapon's explicit delivery (typed.wall_melee), independently of its
reach or the struck section's distance. The compiler preserves melee/ranged
delivery from the source weapon's typed projectile range; unknown delivery is
not reported as melee. Providers own trigger eligibility, consent, Reaction
payment and consequences. ControllerPause rolls back the enclosing transaction.
No provider changes nothing. Waxen Trail uses contest_check_mode provenance:
spec.hazards contains tracking + ordinary_terrain only for that explicit task.
Opponent identifies the tracked creature; unscoped checks gain no benefit."""

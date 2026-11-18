"""Object weapon/unarmed hit seams (objects._attack):
  object_hit_roll_bonus(ctx, object, kind, dice_spec) -> int | None is a pure
  additive query after a confirmed object hit and before its primary damage
  roll. The signed bonuses enter the dice modifier, also for fixed damage and
  critical hits. kind is the compiled weapon group (unarmed, axe or weapon).
  object_hit(ctx, object, kind) -> None runs once after that hit's damage has
  resolved, even when object defenses prevent damage; it never runs on misses.
  Strict dispatch keeps stateful grants in the enclosing transaction. These
  hooks carry an ObjectState, not a creature, and do not dispatch creature-only
  riders. Missing providers leave object behavior unchanged; subscribers must
  gate benefits on ownership. Both seams apply independently to each attack."""

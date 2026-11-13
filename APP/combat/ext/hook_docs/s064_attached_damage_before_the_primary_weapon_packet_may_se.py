"""Attached damage before the primary weapon packet may set
Context.defer_damage_notifications=True on its child Context. Its positive
damage is included once in the enclosing attack damage_dealt callback. This
transient field defaults to False, does not defer damage events or defeat
notifications, and must only be used inside that enclosing attack checkpoint."""

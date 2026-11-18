"""movement_begin(engine, mover, candidate, intent, granted_ft) -> None. Strict
callback inside the accepted willing-movement transaction, before opportunity
policy and per-step payment. Only nonempty native voluntary/granted paths call
it; forced pushes and teleports do not. Providers may ask choices and grant
benefits; the existing path legality, step hazards and allowance checks still
own movement. A pre-start interruption recorded after this intent's
INTENT_ACCEPTED receipt suppresses dispatch, because no movement step begins.
No subscriber means no state/event change. Complete Step uses
the current mover's own-turn gate and the mark owner's shared response limit.
Surplus Step reuses mark_spent and after_move: map-only ignore_difficult,
actual willing path distance, a single PB temp-HP grant, current-turn expiry.

  created_durability_bonus(ctx, kind) -> nonnegative integer or None. Pure,
      additive creation-time query (durability.creation_bonus). Typed walls name
      "barrier"; bound objects use explicit creation_kind/kind, default "object".
      Frozen into evented HP before creation commits; previews, damage, repairs
      and reload never reapply it. No provider means unchanged bytes.
  confirmed_hit_damage_dice(engine, attacker, target, spec, intent, source, critical)
      -> DiceSpec or None. Strict sequential query after settled hit and critical
      prevention, before roll bonuses and native critical doubling. Replacement
      dice compose through spec['damage']. Misses never call it. No provider or
      None retains the original spec/recorded bytes. New paid Sundering Pressure
      rows use it against explicit Constructs; old actions never acquire the row.
"""

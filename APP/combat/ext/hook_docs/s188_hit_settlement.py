"""Confirmed-hit damage settlement.

hook('after_hit', 'after_hit_effects' or 'mark_applied', damage=True) identifies a callback
that adds hit damage. ext.collect_hit invokes these during collection in their
original registration order and queues every other subscriber. Mixed callbacks
submit their non-damage tails with hit_settlement.consequence(ctx, work), the
same defer-or-run operation; no additional queue is created. Without a hit the
ordinary synchronous behavior is retained. Each subscriber still runs once.
A hit's mark declaration collects only mark-triggered added damage (Court's
Form), with collect_hit(..., damage=True). The mark mutation uses the same FIFO;
only successful placement notifies non-damage mark_applied subscribers, with
damage=False. The default None visits both groups. Rejection does not notify
non-damage subscribers; custom handlers keep actual-placement notifications.
Attack-result saves, choices and movement tails use consequence too; roll
reservations and damage-collection snapshots remain at their original boundary.

Both typed save rows and Python tails use that SAME roll_id-keyed FIFO.
block_attack drains it after every save-independent attached packet. Saves
own their complete outcome branch; branch damage retains attack identity,
but critical scaling/attack defenses still require inherit_attack_damage_context.
Queued work is rebuilt when ChoicePause replays the original transaction.
Nested attacks own distinct queues. Scope cleanup discards every unrun entry.

hook(..., packet=True) marks packet-time event bookkeeping/component producers,
not after-damage consequences. Ordinary DAMAGE_COMMITTED event/state_event
callbacks wait in that same FIFO, retaining their explicit packet frame.
Life-state accounting and nested hit-component delivery stay at commit time.
No active collecting hit means all these paths remain synchronous.

damage_floor uses the existing strict arguments and integer/None result.
Within a hit its first lethal-packet reply (including decline) is retained per
callback/recipient until attack_damage_final; subsequent packets reuse it.
Nonlethal packets and standalone packets retain the original callback behavior.
Per-packet defenses, damage application reactions and lethal rescues stay live.

Every DAMAGE_COMMITTED carries hit_roll_id (existing AttackDamage.roll_id or
None for separate damage) and damage_label (this packet's display attribution).
combat.damage_context.packet_metadata defines these fields in one place.
"""

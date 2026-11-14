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
collect_effects(ctx, effects, dispatch, resume) is the typed batch boundary.
It dispatches save-independent damage producers and mark declarations during
collection, and appends uninterrupted remaining blocks to the ONE continuation
in their original relative order. Built-in and plug-in effects follow the same
contract; a save owns its entire branch. A plug-in operation with scoped flags
is resumed as a whole, not split at a nested save after its finally has run.
The original Context remains alive through its continuation; no shallow
per-operation Context snapshots are used to reconstruct a lost scope.

effect(name, damage=True) opts a dynamic plug-in damage producer into this
collection phase (for example a Form choice). The default False delays an
ordinary effect as one complete operation; without a collecting hit it is inert.
Typed effects exposing damage children are structural producers automatically.
Mixed collectors still submit after-damage tails with consequence.
Roll reservations remain at their original boundary.

hit_final installs the captured hit_snapshot receipts at the original confirmed
hit boundary, before stances.after_hit or other damage collectors consume them.
It is not an after-damage continuation notification; hit_settled remains after
all attached damage and consequences.

Both typed save rows and Python tails use that SAME roll_id-keyed FIFO.
block_attack drains it after every save-independent attached packet. Saves
own their complete outcome branch; branch damage retains attack identity,
but critical scaling/attack defenses still require inherit_attack_damage_context.
Queued work is rebuilt when ChoicePause replays the original transaction.
Nested attacks own distinct queues. Each hit holds the engine's existing
victory_deferred() scope through collection, its continuation and final riders.
Packet-time life-state accounting stays live, but a killing packet cannot end
the scene and disable the hit's remaining steps. finish closes that hit's hold;
nested holds preserve the parent's boundary. Scope cleanup unwinds unfinished
holds in reverse order, passing through pauses/errors so no aborted hit settles
victory, and discards every unrun entry.

hook(..., packet=True) marks packet-time event bookkeeping/component producers,
not after-damage consequences. Ordinary DAMAGE_COMMITTED event/state_event
callbacks wait in that same FIFO, retaining their explicit packet frame.
Life-state accounting and nested hit-component delivery stay at commit time.
Each packet carries hp_before, standing_before and bloodied_before (integer
facts) and condition_ids_before (a list of condition ids, including guard
pressure). These are captured before HP/life-state mutation; later subscribers
judge pre-blow eligibility from the event, never the recipient's later state.
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

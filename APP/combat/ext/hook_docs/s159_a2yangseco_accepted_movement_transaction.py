"""A2YANGSECO accepted movement transaction:
willing_movement_completed(engine, mover, intent, movement_receipt, starting_resources) -> None. Strict accepted-transaction notification after a
native willing route actually crossed a square and settled its hazards,
following geometry and falling. The event receipt is the native committed path;
starting_resources is a defensive copy captured before movement_begin. Forced
pushes, teleports and zero-step interruptions never dispatch. Providers may
offer optional follow-up movement without processing the outer step's hazards
twice. No providers means no state/event change. Neither argument is persisted
separately. Any movement-triggered conversion may use the pre-existing-resource
fact; Reed Slip is the first consumer.
Public reed_slip.conversion_distance quotes 5 feet plus the existing shared
foundation_conversion_bonus.conversion_bonus('reed_slip'). The base consumer
calls settle_conversion_bonus with the native payment sequence/resource after
real payment and before movement/OAs; the shared provider alone owns selected
expressions, additive values and round settlement. No bonus rows means base
distance and no extra settlement. Refined/Perfected owners supply their rows.
The public reed_slip.settled_conversion records the actual primitive receipt:
conversion, paid, resource_id, payment_event_sequence, round, allowance_ft,
bonus_ft, geometric moved_ft, terrain/drag movement_cost_ft and exempt_actor_id.
Quotes and cancelled choices never publish a payment receipt. Shared provider
import provenance: Bone 2c597cff, Reed extension 9b62760c (helper only). Its
source_status producer now captures any explicit owner_sheet.foundation, so
conversion_available can also gate base conversions on actual suppression and
source-specific owner exclusions. Unknown/private source facts are preserved.
Its willing_movement_completed hook requires an actual willing route, pre-existing
Flex and an owned compiled row. Native granted_movement scopes exactly one OA
exemption to that slip; nothing remains on the actor after traversal."""

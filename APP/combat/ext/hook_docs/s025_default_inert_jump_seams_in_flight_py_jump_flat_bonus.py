"""Default-inert jump seams in flight.py: jump_flat_bonus_ft(engine, actor) -> int
keeps a subset of jump_bonus_ft unscaled by a standing start;
jump_distance_bonus_ft(engine, actor) -> int opts into straight horizontal
native jumps, preserving step legality, support, occupancy and reactions.
Pure jump_extension_ft(engine, actor) -> nonnegative int adds flat feet after
standing scaling to either height or distance; no provider means zero.
Pure jump_extension_preview_ft(engine, actor, ground_path) -> nonnegative int
may quote a contingent extension; execution still requires the real receipt.
Pure jump_preview_allowed(engine, actor) -> True or None permits enumeration
below the ordinary score/bonus gate when a provider could earn an extension
during a quoted run-up. With no True answer the ordinary gate remains in force.
It only enables enumeration: jump_extension_preview_ft must validate the actual
run-up, and execution still requires the real extension and native admission.
Strict rest_completed(engine, actor, kind) -> None notifies source-owned rest
consumers after the rest_completed typed effect validates its primitive receipt
and short/long kind. With no provider, combat effects remain unchanged.
Default-inert jump seams in flight.py: jump_distance_bonus_ft(engine, actor) -> int
opts into straight horizontal native jumps, preserving step legality, support,
occupancy and reactions. A fighter with no such answer has no straight jump, so flat jump feet alone
(jump_bonus_ft, granted by Flowing Pursuit) lengthen only its high jump until a long-jump opt-in answers.
jump_distance_multiplier(engine, actor) -> positive integer multiplies the
score-derived long- and high-jump distance, before the standing-start halving
and before every additive jump foot. The default is 1; the greatest valid
supplied multiplier applies. jump_steps and horizontal_jump_feet both measure
their distance with flight.jump_distance, so a multiplier never scales a flat
extension or a next-jump receipt and a standing jump stays exactly half the
running jump. Register a multiplier here rather than jump_height_multiplier:
both scale the same score-derived height, so answering both triples the printed
jump twice. A multiplier also opts that creature into straight long jumps: the
printed record triples its long-jump distance, so the straight jump that
distance buys must be offered, not withheld."""

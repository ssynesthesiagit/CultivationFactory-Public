"""A2GTRA5: save_bonus_status adapts its existing flat saving-throw status to
native save_bonus. active_save_pending excludes already-shaped typed saves.
Native hazard-specific bonuses require the exact d20_context named hazards;
missing hazard metadata does not infer a bonus. No status means no change.
Knife Between Thoughts uses reaction_allowed to veto Reactions
aimed at the marked condition's source owner; unrelated recipients stay legal.
Ripple of Before records all three position coordinates and validates native
volume placement for conceptual translation; historical two-coordinate flags
read as ground level. The return restores no resource or other state.
movement_elevation_surcharge(engine, actor, previous, destination, mode)
-> None or nonnegative integer feet is a strict pure query in native
flight.step_cost. It runs only for a height-changing adjacent segment;
level movement and forced displacement keep their ordinary prices. Replies
add before dragging. Flight/jump route quotes and actual steps share this
function and recheck after reactions. With no provider the query is inert.
standing_burden may opt into elevation=True; its owned condition records
elevation_extra_ft and its ordinary standing burden with the same expiry.
death_save_mode(engine, actor) -> None, ADVANTAGE or DISADVANTAGE is a strict
pure query in life_state's mode reader. Replies compose with all existing
sources using normal Advantage cancellation. With no replies, lifecycle and rolls remain unchanged. A reply also opts markerless legacy non-summons into
ordinary dying through the existing wants_dying reader. Providers own live
ally/range/membership predicates; the seam stores no condition or event.
scoundrel_riders.drop_held_object is the public exact-identity forced drop
adapter: it rechecks hand occupancy and protected/fused/soul-bound flags,
journals the ordinary transfer ledger at the holder's feet and refreshes
loads. spirit_traditions.drop_held owns the replayable single-object choice.
Commanding Voice runs Drop at the target's next turn and Kneel vetoes native
standing until that turn ends. Dance of Borrowed Limbs adds the Drop command.
Theater of Strings uses stand_cost for allies/self within the actual volume
and its existing once-round motion event answers native standing and Prone.
Yokai True Form publishes printed Kitsune/Tengu native flight; Tengu Mask
uses falling_damage_distance for PB*10 protection. Grand Silk seals native
escape_option for the target's Action repeat Dexterity save. Grave Keeper
supplies death_save_mode only to allies within ten feet of its live Echo;
Echo defenses use object_damage_defenses. Gravebeat ends on Unconscious.

"""

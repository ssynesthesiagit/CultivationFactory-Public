"""Lock 21 movement continuity: movement_history.endpoints(engine, actor_id) reads
committed MOVEMENT_COMMITTED start/destination positions since the last turn
boundary, non-move intent, reaction, HP/condition change or other creature/forced
movement. Gate4 contexts expose these as optional movement_endpoints (integer
Position tuples, including altitude), omitted when empty. The controller excludes
ordinary-turn MOVE destinations already used in that uninterrupted segment before ranking
movement representatives. Routes may cross old ground to reach a new destination;
non-move choices, movement-only domains and manual legal moves are unchanged. A meaningful intervening
event resets the segment, so an attack can be followed by a retreat.
DAMAGE_COMMITTED during a move precedes its final MOVEMENT_COMMITTED receipt:
that receipt contributes its destination, but its pre-damage start is discarded.
Starts enter history only after scanning back to the accepted MOVE without a
reset (or the beginning of a retained journal). No hidden
enemy path is exposed: only this actor's own committed endpoints enter context.
No saved-state field, new event, RNG or mutation; fresh reload derives the same
history from the journal. Old contexts lacking the field remain valid and inert."""
